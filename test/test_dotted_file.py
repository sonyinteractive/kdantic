from __future__ import annotations

import sys
import types
from pathlib import Path

import kdantic.helpers.dotted_file as mut
import pytest
from pydantic import BaseModel

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _write_py(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def isolate_sys_modules_and_path(monkeypatch):
    """
    Prevent synthetic packages and imported modules from leaking across tests.
    Also avoid polluting sys.path.
    """
    before_modules = set(sys.modules.keys())
    before_path = list(sys.path)

    yield

    # remove any new modules
    for k in list(sys.modules.keys()):
        if k not in before_modules:
            sys.modules.pop(k, None)

    # restore sys.path
    sys.path[:] = before_path


@pytest.fixture
def patch_shared_helpers(monkeypatch):
    """Decouple dotted_file tests from shared: stub get_model_fields_map to use model_fields directly."""

    def fake_get_model_fields_map(model_cls):
        return dict(model_cls.model_fields)

    monkeypatch.setattr(mut, "get_model_fields_map", fake_get_model_fields_map, raising=True)


# -----------------------------------------------------------------------------
# import_by_dotted_name
# -----------------------------------------------------------------------------


def test_import_by_dotted_name_inserts_project_root(monkeypatch, tmp_path, patch_shared_helpers):
    # Create a package under tmp_path / proj / pkg / __init__.py
    proj = tmp_path / "proj"
    pkg = proj / "pkg"
    pkg.mkdir(parents=True)
    _write_py(pkg / "__init__.py", "X = 1\n")

    # Ensure project_root not already in sys.path
    assert str(proj) not in sys.path

    mod = mut.import_by_dotted_name("pkg", project_root=str(proj))
    assert mod.X == 1
    assert str(proj) in sys.path


# -----------------------------------------------------------------------------
# _collect_models_from_module
# -----------------------------------------------------------------------------


def test_collect_models_from_module_harvests_only_models_with_fields(
    patch_shared_helpers,
):
    class Empty(BaseModel):
        pass

    class NonEmpty(BaseModel):
        a: int

    m = types.ModuleType("m")
    m.Empty = Empty
    m.NonEmpty = NonEmpty
    m.NotAClass = 123

    out = mut._collect_models_from_module(m)
    assert "NonEmpty" in out
    assert "Empty" not in out  # fields_map is empty => excluded
    assert out["NonEmpty"] is NonEmpty


def test_collect_models_from_module_recurses_packages_and_skips_bad_imports(
    monkeypatch, tmp_path, patch_shared_helpers
):
    """
    Simulate:
      pkg/
        __init__.py (exports RootModel)
        good.py      (exports GoodModel)
        bad.py       (syntax error)
    Ensure recursion finds RootModel and GoodModel, skips bad module.
    """
    proj = tmp_path / "proj"
    pkg = proj / "pkg"
    pkg.mkdir(parents=True)

    _write_py(
        pkg / "__init__.py",
        "from pydantic import BaseModel\nclass RootModel(BaseModel):\n  x: int\n",
    )
    _write_py(
        pkg / "good.py",
        "from pydantic import BaseModel\nclass GoodModel(BaseModel):\n  y: int\n",
    )
    _write_py(pkg / "bad.py", "this is not python :::\n")

    # import package
    mod = mut.import_by_dotted_name("pkg", project_root=str(proj))

    # Real walk_packages will find submodules; importlib.import_module will choke on bad.py
    out = mut._collect_models_from_module(mod)
    assert "RootModel" in out
    assert "GoodModel" in out
    assert "bad" not in out  # module file name isn't added anyway; ensure no crash


# -----------------------------------------------------------------------------
# load_models_from_module
# -----------------------------------------------------------------------------


def test_load_models_from_module_filter_success(monkeypatch, tmp_path, patch_shared_helpers):
    proj = tmp_path / "proj"
    pkg = proj / "pkg"
    pkg.mkdir(parents=True)

    _write_py(
        pkg / "__init__.py",
        "from pydantic import BaseModel\nclass A(BaseModel):\n  x: int\nclass B(BaseModel):\n  y: int\n",
    )

    out = mut.load_models_from_module("pkg", filter_name="B", project_root=str(proj))
    assert list(out.keys()) == ["B"]
    assert out["B"].__name__ == "B"


def test_load_models_from_module_filter_missing_raises(monkeypatch, tmp_path, patch_shared_helpers):
    proj = tmp_path / "proj"
    pkg = proj / "pkg"
    pkg.mkdir(parents=True)

    _write_py(
        pkg / "__init__.py",
        "from pydantic import BaseModel\nclass A(BaseModel):\n  x: int\n",
    )

    with pytest.raises(ValueError, match=r"Model 'B' not found"):
        mut.load_models_from_module("pkg", filter_name="B", project_root=str(proj))


# -----------------------------------------------------------------------------
# _dotted_from_path
# -----------------------------------------------------------------------------


def test_dotted_from_path_file_inside_package(tmp_path):
    proj = tmp_path / "proj"
    pkg = proj / "pkg"
    sub = pkg / "sub"
    sub.mkdir(parents=True)

    _write_py(pkg / "__init__.py", "")
    _write_py(sub / "__init__.py", "")
    f = sub / "models.py"
    _write_py(f, "# models\n")

    project_root, dotted = mut._dotted_from_path(str(f))
    assert project_root == str(proj)
    assert dotted == "pkg.sub.models"


def test_dotted_from_path_dir_inside_package(tmp_path):
    proj = tmp_path / "proj"
    pkg = proj / "pkg"
    pkg.mkdir(parents=True)
    _write_py(pkg / "__init__.py", "")

    project_root, dotted = mut._dotted_from_path(str(pkg))
    assert project_root == str(proj)
    assert dotted == "pkg"


def test_dotted_from_path_not_in_package_raises(tmp_path):
    d = tmp_path / "loose"
    d.mkdir()
    with pytest.raises(ValueError, match="not inside a package"):
        mut._dotted_from_path(str(d))


# -----------------------------------------------------------------------------
# _import_file_under / _load_from_loose_dir
# -----------------------------------------------------------------------------


def test_import_file_under_creates_synthetic_package_and_imports(tmp_path, patch_shared_helpers):
    d = tmp_path / "loose"
    d.mkdir()
    f = d / "m.py"
    _write_py(f, "from pydantic import BaseModel\nclass M(BaseModel):\n  a: int\n")

    mod = mut._import_file_under("kdantic_models", str(f), str(d))
    assert hasattr(mod, "M")
    assert mod.__package__ == "kdantic_models"
    # module should be registered as kdantic_models.m
    assert "kdantic_models.m" in sys.modules


def test_load_from_loose_dir_loads_models_from_multiple_files(tmp_path, patch_shared_helpers):
    d = tmp_path / "loose"
    d.mkdir()

    _write_py(d / "a.py", "from pydantic import BaseModel\nclass A(BaseModel):\n  x: int\n")
    _write_py(d / "b.py", "from pydantic import BaseModel\nclass B(BaseModel):\n  y: int\n")
    _write_py(
        d / "__ignore.py",
        "from pydantic import BaseModel\nclass Ignore(BaseModel): z:int\n",
    )

    out = mut._load_from_loose_dir(str(d))
    assert set(out.keys()) == {"A", "B"}


# -----------------------------------------------------------------------------
# load_models_from_any_path
# -----------------------------------------------------------------------------


def test_load_models_from_any_path_directory_that_is_package(tmp_path, patch_shared_helpers):
    """
    If dir has __init__.py => treat as package, import by dotted.
    """
    proj = tmp_path / "proj"
    pkg = proj / "pkg"
    pkg.mkdir(parents=True)

    _write_py(
        pkg / "__init__.py",
        "from pydantic import BaseModel\nclass A(BaseModel):\n  x: int\n",
    )

    out = mut.load_models_from_any_path(str(pkg))
    assert "A" in out


def test_load_models_from_any_path_directory_loose(tmp_path, patch_shared_helpers):
    """
    If dir has no __init__.py => synthetic package loader.
    """
    d = tmp_path / "loose"
    d.mkdir()

    _write_py(d / "m.py", "from pydantic import BaseModel\nclass M(BaseModel):\n  x: int\n")

    out = mut.load_models_from_any_path(str(d))
    assert "M" in out


def test_load_models_from_any_path_file_inside_package(tmp_path, patch_shared_helpers):
    """
    If file is inside package tree => uses _dotted_from_path + load_models_from_module.
    """
    proj = tmp_path / "proj"
    pkg = proj / "pkg"
    pkg.mkdir(parents=True)
    _write_py(pkg / "__init__.py", "")

    f = pkg / "models.py"
    _write_py(f, "from pydantic import BaseModel\nclass A(BaseModel):\n  x: int\n")

    out = mut.load_models_from_any_path(str(f))
    assert "A" in out


def test_load_models_from_any_path_file_not_in_package_execs_directly(tmp_path, patch_shared_helpers):
    """
    If file is not in a package => direct spec_from_file_location path.
    """
    f = tmp_path / "models.py"
    _write_py(
        f,
        "from pydantic import BaseModel\nclass A(BaseModel):\n  x: int\nclass Empty(BaseModel):\n  pass\n",
    )

    out = mut.load_models_from_any_path(str(f))
    assert "A" in out
    assert "Empty" not in out  # excluded because no fields


def test_load_models_from_any_path_filter_success(tmp_path, patch_shared_helpers):
    f = tmp_path / "models.py"
    _write_py(
        f,
        "from pydantic import BaseModel\nclass A(BaseModel):\n  x: int\nclass B(BaseModel):\n  y: int\n",
    )

    out = mut.load_models_from_any_path(str(f), filter_name="B")
    assert list(out.keys()) == ["B"]


def test_load_models_from_any_path_filter_missing_raises(tmp_path, patch_shared_helpers):
    f = tmp_path / "models.py"
    _write_py(f, "from pydantic import BaseModel\nclass A(BaseModel):\n  x: int\n")

    with pytest.raises(ValueError, match=r"Model 'B' not found"):
        mut.load_models_from_any_path(str(f), filter_name="B")
