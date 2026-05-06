import importlib
import importlib.util
import logging
import os
import pkgutil
import sys
import types

from kdantic.helpers.shared import get_model_fields_map
from pydantic import BaseModel

logger = logging.getLogger("kdantic")

# ------------------------------------------------------------------------------
# Unified loading: dotted package or filesystem path
# ------------------------------------------------------------------------------


def import_by_dotted_name(dotted: str, project_root: str | None = None):
    if project_root:
        root = os.path.abspath(project_root)
        if root not in sys.path:
            sys.path.insert(0, root)
    return importlib.import_module(dotted)


def _collect_models_from_module(module_obj) -> dict[str, type[BaseModel]]:
    out: dict[str, type[BaseModel]] = {}

    def harvest(mobj):
        for attr_name, attr_val in vars(mobj).items():
            if isinstance(attr_val, type) and issubclass(attr_val, BaseModel):
                fields_map = get_model_fields_map(attr_val)
                if fields_map:
                    out[attr_name] = attr_val

    harvest(module_obj)
    if hasattr(module_obj, "__path__"):  # recurse packages
        for _, subname, _ in pkgutil.walk_packages(module_obj.__path__, prefix=module_obj.__name__ + "."):
            try:
                harvest(importlib.import_module(subname))
            except (ImportError, SyntaxError) as imp_err:
                logger.debug(f"Skipping {subname}: {imp_err}")
                continue
    return out


def load_models_from_module(
    dotted: str, filter_name: str | None = None, project_root: str | None = None
) -> dict[str, type[BaseModel]]:
    module_obj = import_by_dotted_name(dotted, project_root)
    models = _collect_models_from_module(module_obj)
    if filter_name:
        if filter_name in models:
            return {filter_name: models[filter_name]}
        raise ValueError(f"Model '{filter_name}' not found in {dotted}")
    return models


def _dotted_from_path(path_str: str) -> tuple[str, str]:
    """
    If path is inside a package tree, return (project_root, dotted_module).
    Raises if not a package.
    """
    abs_path = os.path.abspath(path_str)
    if os.path.isdir(abs_path):
        base_dir = abs_path
        mod_parts: list[str] = []
    else:
        base_dir = os.path.dirname(abs_path)
        mod_parts = [os.path.splitext(os.path.basename(abs_path))[0]]

    pkg_parts: list[str] = []
    cur = base_dir
    while True:
        if os.path.exists(os.path.join(cur, "__init__.py")):
            pkg_parts.append(os.path.basename(cur))
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        else:
            project_root = cur
            break

    if not pkg_parts:
        raise ValueError("not inside a package")
    dotted = ".".join(list(reversed(pkg_parts)) + mod_parts)
    return project_root, dotted


def _import_file_under(package_name: str, file_path: str, package_dir: str):
    """
    Load a single .py file as package_name.module, so relative imports work.
    """
    pkg = sys.modules.get(package_name)
    if not pkg:
        pkg = types.ModuleType(package_name)
        pkg.__path__ = [package_dir]  # make it a package
        sys.modules[package_name] = pkg

    mod_name = f"{package_name}.{os.path.splitext(os.path.basename(file_path))[0]}"
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = package_name  # key for relative imports
    sys.modules[mod_name] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _load_from_loose_dir(dir_path: str) -> dict[str, type[BaseModel]]:
    """
    Treat a directory without __init__.py as a synthetic package.
    """
    abs_dir = os.path.abspath(dir_path)
    pkg_name = "kdantic_models"
    models: dict[str, type[BaseModel]] = {}
    for fname in os.listdir(abs_dir):
        if fname.endswith(".py") and not fname.startswith("__"):
            module_obj = _import_file_under(pkg_name, os.path.join(abs_dir, fname), abs_dir)
            for attr_name, attr_val in vars(module_obj).items():
                if isinstance(attr_val, type) and issubclass(attr_val, BaseModel):
                    fields_map = get_model_fields_map(attr_val)
                    if fields_map:
                        models[attr_name] = attr_val
    return models


def load_models_from_any_path(path_str: str, filter_name: str | None = None) -> dict[str, type[BaseModel]]:
    """
    Best-effort loader:
    - If path is (or is inside) a package, import by dotted name (preserves relatives).
    - Else if path is a directory without __init__.py, synthetic package loader (preserves relatives).
    - Else fallback to direct file exec (strenum compat + warning suppression).
    """
    abs_path = os.path.abspath(path_str)
    if os.path.isdir(abs_path):
        if os.path.exists(os.path.join(abs_path, "__init__.py")):
            proj_root, dotted = _dotted_from_path(abs_path)
            module_obj = import_by_dotted_name(dotted, proj_root)
            models = _collect_models_from_module(module_obj)
        else:
            models = _load_from_loose_dir(abs_path)
    else:
        try:
            proj_root, dotted = _dotted_from_path(abs_path)
            models = load_models_from_module(dotted, project_root=proj_root)
        except Exception:
            spec = importlib.util.spec_from_file_location("model_module", abs_path)
            module_obj = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module_obj)  # type: ignore[attr-defined]
            models = {
                name_k: obj_v
                for name_k, obj_v in vars(module_obj).items()
                if isinstance(obj_v, type) and issubclass(obj_v, BaseModel) and get_model_fields_map(obj_v)
            }

    if filter_name:
        if filter_name in models:
            return {filter_name: models[filter_name]}
        raise ValueError(f"Model '{filter_name}' not found in {path_str}")
    return models
