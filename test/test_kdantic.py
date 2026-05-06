from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

import kdantic.cli as mut
from kdantic.helpers.annotations import CRDMetaData, CRDMetaDataNames

# -----------------------
# Test models
# -----------------------


class SpecModel(BaseModel):
    foo: int = 1


class StatusModel(BaseModel):
    ok: bool = True


# -----------------------
# Shared fixtures
# -----------------------


@pytest.fixture
def fake_settings(monkeypatch, tmp_path):
    class Mode:
        import_name: str | None = None
        path: str | None = None

    class Verbosity:
        quiet: bool = False
        verbose: bool = False

    class Settings:
        crd_version = "apiextensions.k8s.io/v1"
        crd_kind = "CustomResourceDefinition"
        helm = False
        output_directory = tmp_path
        output_overwrite = True
        model_name = None
        project_root = None
        mode = Mode()
        verbosity = Verbosity()

        def model_dump(self):
            return {
                "crd_version": self.crd_version,
                "crd_kind": self.crd_kind,
                "helm": self.helm,
                "output_directory": self.output_directory,
                "output_overwrite": self.output_overwrite,
                "model_name": self.model_name,
                "project_root": self.project_root,
                "mode": {"import_name": self.mode.import_name, "path": self.mode.path},
                "verbosity": {
                    "quiet": self.verbosity.quiet,
                    "verbose": self.verbosity.verbose,
                },
            }

    s = Settings()
    monkeypatch.setattr(mut, "kdantic_settings", s, raising=True)
    return s


# -----------------------
# _make_version_block
# -----------------------


def _make_meta(version: str = "v1", cel_rules: list | None = None) -> CRDMetaData:
    return CRDMetaData(
        group="example.com",
        version=version,
        scope="Namespaced",
        names=CRDMetaDataNames(kind="Widget", plural="widgets", singular="widget", shortNames=[]),
        cel_rules=cel_rules,
    )


def test_make_version_block_spec_and_status(monkeypatch):
    """
    If spec_model and status_model are provided, both schemas appear and
    status subresource is enabled.
    """

    def fake_build_schema(model, custom_formats):
        return {"title": model.__name__, "custom_formats_seen": custom_formats}

    monkeypatch.setattr(mut, "build_k8s_model_schema", fake_build_schema, raising=True)

    vb = mut._make_version_block(
        _make_meta(),
        spec_model=SpecModel,
        status_model=StatusModel,
        custom_formats={"ipvanynetwork": "x"},
    )

    props = vb["schema"]["openAPIV3Schema"]["properties"]
    assert props["spec"]["title"] == "SpecModel"
    assert props["status"]["title"] == "StatusModel"
    assert vb["subresources"] == {"status": {}}


def test_make_version_block_only_spec(monkeypatch):
    """
    If only spec_model is provided, it only emits spec and no subresources.
    """
    monkeypatch.setattr(
        mut,
        "build_k8s_model_schema",
        lambda model, _formats: {"title": model.__name__},
        raising=True,
    )

    vb = mut._make_version_block(
        _make_meta(),
        spec_model=SpecModel,
        status_model=None,
        custom_formats={},
    )

    props = vb["schema"]["openAPIV3Schema"]["properties"]
    assert "spec" in props
    assert "status" not in props
    assert "subresources" not in vb


def test_make_version_block_cel_rules_serialization(monkeypatch, caplog):
    """
    CEL rules: list[dict] from CRDMetaData is assigned directly to x-kubernetes-validations.
    Normalization (BaseModel -> dict, Mapping -> dict) is handled by CRDMetaData._coerce_cel_rules.
    """
    monkeypatch.setattr(
        mut,
        "build_k8s_model_schema",
        lambda model, _formats: {"title": model.__name__},
        raising=True,
    )

    caplog.set_level("INFO", logger="kdantic")

    meta = _make_meta(cel_rules=[{"expr": "has(self.spec)"}, {"rule": "self.spec.foo > 0"}])

    vb = mut._make_version_block(meta, spec_model=SpecModel, status_model=None, custom_formats={})

    xvals = vb["schema"]["openAPIV3Schema"].get("x-kubernetes-validations")
    assert isinstance(xvals, list)
    assert len(xvals) == 2
    assert xvals[0]["expr"] == "has(self.spec)"
    assert xvals[1]["rule"] == "self.spec.foo > 0"

    assert any("Model has CEL rules" in rec.message for rec in caplog.records)


def test_make_version_block_no_cel_rules_omits_extension(monkeypatch):
    """
    If CRDMetaData.cel_rules is None or empty, x-kubernetes-validations must not appear.
    """
    monkeypatch.setattr(
        mut,
        "build_k8s_model_schema",
        lambda model, _formats: {"title": model.__name__},
        raising=True,
    )

    for cel_rules in (None, []):
        vb = mut._make_version_block(
            _make_meta(cel_rules=cel_rules),
            spec_model=SpecModel,
            status_model=None,
            custom_formats={},
        )

        assert "x-kubernetes-validations" not in vb["schema"]["openAPIV3Schema"]


# -----------------------
# build_crd_object
# -----------------------


@dataclass
class Names:
    kind: str
    plural: str
    singular: str
    shortNames: list[str]


@dataclass
class Meta:
    group: str
    names: Names
    scope: str
    version: str
    cel_rules: Any = None


def test_build_crd_object_basic(fake_settings):
    vb = {"name": "v1", "schema": {"openAPIV3Schema": {"type": "object"}}}
    meta = Meta(
        group="example.com",
        names=Names(
            kind="Widget", plural="widgets", singular="widget", shortNames=["wdg"]
        ),
        scope="Namespaced",
        version="v1",
    )

    crd = mut.build_crd_object(meta, vb)

    assert crd["apiVersion"] == fake_settings.crd_version
    assert crd["kind"] == fake_settings.crd_kind
    assert crd["metadata"]["name"] == "widgets.example.com"
    assert crd["spec"]["group"] == "example.com"
    assert crd["spec"]["names"]["kind"] == "Widget"
    assert crd["spec"]["versions"] == [vb]
    assert "labels" not in crd["metadata"]


def test_build_crd_object_adds_helm_labels_when_enabled(fake_settings, monkeypatch):
    fake_settings.helm = True
    monkeypatch.setattr(mut, "HELM_SENTINEL", {"managed-by": "helm"}, raising=True)

    vb = {"name": "v1", "schema": {"openAPIV3Schema": {"type": "object"}}}
    meta = Meta(
        group="example.com",
        names=Names(
            kind="Widget", plural="widgets", singular="widget", shortNames=["wdg"]
        ),
        scope="Namespaced",
        version="v1",
    )

    crd = mut.build_crd_object(meta, vb)

    assert crd["metadata"]["labels"] == {"managed-by": "helm"}


# -----------------------
# generate_crds
# -----------------------


def test_generate_crds_uses_module_loader_when_import_name_set(
    fake_settings, monkeypatch
):
    fake_settings.mode.import_name = "my.pkg.models"
    fake_settings.mode.path = None

    calls = {"module": 0, "path": 0}

    def fake_load_models_from_module(import_name, filter_name, project_root):
        calls["module"] += 1
        assert import_name == "my.pkg.models"
        return {}

    def fake_load_models_from_any_path(path, filter_name):
        calls["path"] += 1
        return {}

    monkeypatch.setattr(
        mut, "load_models_from_module", fake_load_models_from_module, raising=True
    )
    monkeypatch.setattr(
        mut, "load_models_from_any_path", fake_load_models_from_any_path, raising=True
    )

    mut.generate_crds(custom_formats={})
    assert calls["module"] == 1
    assert calls["path"] == 0


def test_generate_crds_uses_path_loader_when_no_import_name(fake_settings, monkeypatch):
    fake_settings.mode.import_name = None
    fake_settings.mode.path = "/tmp/models.py"

    calls = {"path": 0}

    def fake_load_models_from_any_path(path, filter_name):
        calls["path"] += 1
        assert path == "/tmp/models.py"
        return {}

    monkeypatch.setattr(
        mut, "load_models_from_any_path", fake_load_models_from_any_path, raising=True
    )
    monkeypatch.setattr(
        mut,
        "load_models_from_module",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("should not call module loader")
        ),
        raising=True,
    )

    mut.generate_crds(custom_formats={})
    assert calls["path"] == 1


def test_generate_crds_skips_non_pydantic_models(fake_settings, monkeypatch, caplog):
    fake_settings.mode.import_name = "x"
    caplog.set_level("WARNING", logger="kdantic")

    monkeypatch.setattr(
        mut,
        "load_models_from_module",
        lambda *_a, **_k: {"Nope": object()},
        raising=True,
    )
    # Make sure it doesn't proceed far enough to write
    monkeypatch.setattr(
        mut,
        "write_crd",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not write")),
        raising=True,
    )

    mut.generate_crds(custom_formats={})

    assert any("not a subclass of BaseModel" in rec.message for rec in caplog.records)


def test_generate_crds_skips_missing_spec(fake_settings, monkeypatch, caplog):
    fake_settings.mode.import_name = "x"
    caplog.set_level("WARNING", logger="kdantic")

    class MissingSpec(BaseModel):
        x: int

    monkeypatch.setattr(
        mut,
        "load_models_from_module",
        lambda *_a, **_k: {"MissingSpec": MissingSpec},
        raising=True,
    )
    monkeypatch.setattr(
        mut, "get_model_fields_map", lambda *_a, **_k: {"x": object()}, raising=True
    )
    monkeypatch.setattr(
        mut,
        "write_crd",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not write")),
        raising=True,
    )

    mut.generate_crds(custom_formats={})

    assert any("missing required 'spec' field" in rec.message for rec in caplog.records)


def test_generate_crds_extracts_optional_status_type(
    fake_settings, monkeypatch, tmp_path
):
    """
    status: StatusModel | None should be unwrapped to StatusModel before calling _make_version_block.
    """
    fake_settings.mode.import_name = "x"
    fake_settings.output_directory = tmp_path

    class Root(BaseModel):
        spec: SpecModel
        status: StatusModel | None = None

    monkeypatch.setattr(
        mut, "load_models_from_module", lambda *_a, **_k: {"Root": Root}, raising=True
    )

    spec_field = object()
    status_field = object()
    monkeypatch.setattr(
        mut,
        "get_model_fields_map",
        lambda *_a, **_k: {"spec": spec_field, "status": status_field},
        raising=True,
    )

    def fake_get_field_annotation(field):
        if field is spec_field:
            return SpecModel
        if field is status_field:
            return StatusModel | None
        raise AssertionError("unexpected field")

    monkeypatch.setattr(
        mut, "get_field_annotation", fake_get_field_annotation, raising=True
    )

    meta = Meta(
        group="example.com",
        names=Names(kind="Root", plural="roots", singular="root", shortNames=["rt"]),
        scope="Namespaced",
        version="v1",
        cel_rules=None,
    )
    monkeypatch.setattr(mut, "build_crd_meta", lambda *_a, **_k: meta, raising=True)

    captured = {}

    def fake_make_version_block(meta_, spec_model, status_model, custom_formats):
        captured["version"] = meta_.version
        captured["spec_model"] = spec_model
        captured["status_model"] = status_model
        captured["custom_formats"] = custom_formats
        return {"name": meta_.version, "schema": {"openAPIV3Schema": {"type": "object"}}}

    monkeypatch.setattr(
        mut, "_make_version_block", fake_make_version_block, raising=True
    )
    monkeypatch.setattr(
        mut,
        "build_crd_object",
        lambda meta_, vb: {"meta": meta_.group, "vb": vb},
        raising=True,
    )

    written = []

    def fake_write_crd(path, obj, overwrite):
        written.append((path, obj, overwrite))

    monkeypatch.setattr(mut, "write_crd", fake_write_crd, raising=True)

    mut.generate_crds(custom_formats={"fmt": "x"})

    assert captured["spec_model"] is SpecModel
    assert captured["status_model"] is StatusModel  # union unwrapped
    assert captured["custom_formats"] == {"fmt": "x"}

    assert len(written) == 1
    out_path, obj, overwrite = written[0]
    assert out_path == tmp_path / "roots.example.com.yaml"
    assert overwrite is True
    assert obj["meta"] == "example.com"


def test_generate_crds_continues_after_exception(
    fake_settings, monkeypatch, tmp_path, caplog
):
    """
    If one model errors during generation, it should log and continue with the next model.
    """
    fake_settings.mode.import_name = "x"
    fake_settings.output_directory = tmp_path
    caplog.set_level("WARNING", logger="kdantic")

    class A(BaseModel):
        spec: SpecModel

    class B(BaseModel):
        spec: SpecModel

    monkeypatch.setattr(
        mut, "load_models_from_module", lambda *_a, **_k: {"A": A, "B": B}, raising=True
    )

    spec_field = object()
    monkeypatch.setattr(
        mut,
        "get_model_fields_map",
        lambda *_a, **_k: {"spec": spec_field},
        raising=True,
    )
    monkeypatch.setattr(
        mut, "get_field_annotation", lambda *_a, **_k: SpecModel, raising=True
    )

    meta_a = Meta(
        group="example.com",
        names=Names(kind="A", plural="as", singular="a", shortNames=["a"]),
        scope="Namespaced",
        version="v1",
    )
    meta_b = Meta(
        group="example.com",
        names=Names(kind="B", plural="bs", singular="b", shortNames=["b"]),
        scope="Namespaced",
        version="v1",
    )

    def fake_build_crd_meta(model_cls):
        return meta_a if model_cls is A else meta_b

    monkeypatch.setattr(mut, "build_crd_meta", fake_build_crd_meta, raising=True)

    call_count = {"n": 0}

    def fake_make_version_block(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("boom")
        return {"name": "v1", "schema": {"openAPIV3Schema": {"type": "object"}}}

    monkeypatch.setattr(
        mut, "_make_version_block", fake_make_version_block, raising=True
    )
    monkeypatch.setattr(
        mut,
        "build_crd_object",
        lambda meta_, vb: {"plural": meta_.names.plural},
        raising=True,
    )

    written = []
    monkeypatch.setattr(
        mut,
        "write_crd",
        lambda path, obj, overwrite: written.append((path, obj)),
        raising=True,
    )

    mut.generate_crds(custom_formats={})

    assert len(written) == 1
    assert written[0][1] == {"plural": "bs"}
    assert any("Failed to generate CRD for A" in rec.message for rec in caplog.records)

