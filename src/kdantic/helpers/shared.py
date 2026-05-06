import types
from typing import Union, get_args, get_origin, Literal, get_type_hints
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

# re-export so callers only need one import
__all__ = ["PydanticUndefined"]


# ------------------------------------------------------------------------------
# Pydantic v2 field helpers
# ------------------------------------------------------------------------------


def get_model_fields_map(model_cls: type[BaseModel]) -> dict[str, FieldInfo]:
    """Return the model's fields mapping."""
    return model_cls.model_fields


def get_field_annotation(model_field: FieldInfo) -> object:
    """Return the field's type annotation."""
    return model_field.annotation


def get_field_title(model_field: FieldInfo) -> str | None:
    """Return the field title if set, otherwise None."""
    return model_field.title or None


def get_field_description(model_field: FieldInfo) -> str | None:
    """Return the field description if set, otherwise None."""
    return model_field.description or None


def get_default(model_field: FieldInfo) -> object:
    """Return the field's default value, or PydanticUndefined if not set."""
    return model_field.get_default()


def get_default_factory(model_field: FieldInfo):
    """Return the field's default_factory if set, otherwise None."""
    return model_field.default_factory


# ------------------------------------------------------------------------------
# Optional helpers (PEP 604)
# ------------------------------------------------------------------------------


def _is_optional(tp: object) -> bool:
    """Support typing.Union[T, None] and PEP 604 T | None."""
    origin = get_origin(tp)
    union_type = getattr(types, "UnionType", None)  # Python 3.10+
    if origin in (Union, union_type):
        return type(None) in get_args(tp)  # noqa: E721
    return False


def _strip_optional(tp: object) -> object:
    """Strip Optional wrapper, returning the inner type."""
    return (
        next((t for t in get_args(tp) if t is not type(None)), tp)
        if _is_optional(tp)
        else tp
    )  # noqa: E721


# ------------------------------------------------------------------------------
# Small shared helpers
# ------------------------------------------------------------------------------


def _normalize_short_names(value: object) -> list[str]:
    """Normalize a short_names value to a list of strings."""
    if not value:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()]


def _normalize_scope(scope: str | None) -> str | None:
    """Normalize a scope string to 'Namespaced' or 'Cluster'."""
    if not scope:
        return None
    s = scope.strip().lower()
    if s.startswith("name"):
        return "Namespaced"
    if s.startswith("clus"):
        return "Cluster"
    return None


def _literal_str_from_annotations(
    model: type[BaseModel], field_name: str
) -> str | None:
    """Return the first string value of a Literal annotation on a field, or None."""
    try:
        hints = get_type_hints(model)
    except Exception:
        hints = getattr(model, "__annotations__", {})
    ann = hints.get(field_name)
    if get_origin(ann) is Literal:
        vals = [a for a in get_args(ann) if isinstance(a, str)]
        if vals:
            return vals[0]
    return None


def _only_letters(s: str) -> str:
    """Return only the alphabetic characters of s, lowercased."""
    return "".join(ch for ch in s.lower() if ch.isalpha())


def _short_name(kind: str) -> str:
    """Derive a three-letter kubectl short name from a Kind string."""
    k = _only_letters(kind)
    if len(k) >= 3:
        return k[0] + k[len(k) // 2] + k[-1]
    return k or "cr"


def _pluralize(kind: str) -> str:
    """Return a simple English plural of kind (lowercase)."""
    k = kind.lower()
    if k.endswith(("s", "x", "z", "ch", "sh")):
        return k + "es"
    if k.endswith("y") and len(k) > 1 and k[-2] not in "aeiou":
        return k[:-1] + "ies"
    return k + "s"


def openapi_primitive(py_type: type) -> str | None:
    """Return the OpenAPI type string for a Python primitive type, else None."""
    # bool is a subclass of int; check it first
    if py_type is bool:
        return "boolean"
    if py_type is int:
        return "integer"
    if py_type is float:
        return "number"
    if py_type is str:
        return "string"
    return None