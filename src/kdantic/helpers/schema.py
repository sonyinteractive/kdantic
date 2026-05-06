import re
import sys
import types
import enum as _stdlib_enum
import logging
import yaml
from pathlib import Path
from typing import Annotated, Union, get_args, get_origin, Literal
from collections.abc import Mapping as _MappingABC
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from kdantic.helpers.settings import kdantic_settings
from kdantic.helpers.shared import (
    openapi_primitive,
    get_field_annotation,
    _is_optional,
    _strip_optional,
    get_field_description,
    get_field_title,
    get_default_factory,
    get_default,
    get_model_fields_map,
)

from pydantic_core import PydanticUndefined

logger = logging.getLogger("kdantic")
_schema_cache: dict[tuple[type[BaseModel], int, bool], dict] = {}


HELM_SENTINEL = "__HELM_SENTINEL__"

# ------------------------------------------------------------------------------
# Schema helpers
# ------------------------------------------------------------------------------


def unwrap_all_fieldinfos(current_type: object) -> tuple[object, list[FieldInfo]]:
    infos: list[FieldInfo] = []
    seen: set = set()
    while current_type not in seen:
        seen.add(current_type)

        if get_origin(current_type) is Annotated:
            base, *extras = get_args(current_type)
            current_type = base
            for meta in extras:
                if isinstance(meta, FieldInfo):
                    infos.append(meta)
            continue

        if isinstance(current_type, type):
            mod = sys.modules.get(current_type.__module__)
            alias = getattr(mod, current_type.__name__, None) if mod else None
            if alias and alias is not current_type:
                if get_origin(alias) is Annotated:
                    base, *extras = get_args(alias)
                    current_type = base
                    for meta in extras:
                        if isinstance(meta, FieldInfo):
                            infos.append(meta)
                    continue
        break

    return current_type, infos


def build_enum_schema(enum_type: type[_stdlib_enum.Enum]) -> dict:
    enum_values = [member.value for member in enum_type]  # type: ignore[index]
    if enum_values:
        primitive = openapi_primitive(type(enum_values[0]))
    else:
        primitive = "string"
    return {"type": primitive or "string", "enum": enum_values}


def _literal_strings(annotation: object) -> list[str] | None:
    """Return list of string values if annotation is Literal['a','b',...]."""
    if get_origin(annotation) is Literal:
        vals = [a for a in get_args(annotation) if isinstance(a, str)]
        return vals or None
    return None


def get_openapi_schema_for_type(
    field_type: object, field_name: str, custom_formats: dict, is_nested: bool = False
) -> dict:
    base_type, fieldinfos = unwrap_all_fieldinfos(field_type)
    origin = get_origin(base_type) or base_type
    args = get_args(base_type)

    # Handle true unions (e.g., int | str). Keep Kubernetes-friendly "no anyOf":
    # pick the first non-None member; if none, default to "string".
    if origin in (Union, types.UnionType):
        members = [t for t in args if t is not type(None)]  # noqa: E721
        if members:
            return get_openapi_schema_for_type(members[0], field_name, custom_formats, is_nested)
        return {"type": "string"}

    # Literal[...] string enums
    lits = _literal_strings(base_type)
    if lits:
        schema: dict = {"type": "string", "enum": lits}
    else:
        primitive = openapi_primitive(origin) if isinstance(origin, type) else None
        if primitive:
            schema = {"type": primitive}
        else:
            # Safe lowercasing (UnionType has no __name__)
            name_lower = (getattr(origin, "__name__", None) or "").lower()

            if name_lower in custom_formats:
                schema = {"type": "string", "format": custom_formats[name_lower]}
            elif origin is list:
                item_t = args[0] if args else object
                schema = {
                    "type": "array",
                    "items": get_openapi_schema_for_type(
                        item_t, field_name, custom_formats, is_nested=True
                    ),
                }
            elif origin in {dict, _MappingABC}:
                key_t = args[0] if args else str
                val_t = args[1] if len(args) > 1 else object
                if key_t not in (str, object):
                    logger.warning(
                        f"{field_name}: map keys coerced to string in CRD schema (OpenAPI requires string keys)"
                    )
                schema = {
                    "type": "object",
                    "additionalProperties": get_openapi_schema_for_type(
                        val_t, field_name, custom_formats, is_nested=True
                    ),
                }
            elif isinstance(origin, type) and issubclass(origin, BaseModel):
                schema = build_k8s_model_schema(origin, custom_formats, is_root=False)
            elif isinstance(origin, type) and issubclass(origin, _stdlib_enum.Enum):
                schema = build_enum_schema(origin)  # type: ignore[arg-type]
            else:
                schema = {"type": "string"}

    # Apply FieldInfo extras (title/description/extra JSON schema)
    for idx, info in enumerate(fieldinfos):
        if idx == 0 and "title" not in schema:
            schema["title"] = info.title or field_name.replace("_", " ").title()
        extras = info.json_schema_extra or {}
        for k, v in extras.items():
            schema[k] = v
        if idx == 0 and info.description:
            schema["description"] = info.description

    return schema


def build_field_schemas(
    fields_iter, custom_formats: dict, is_root: bool = True
) -> tuple[dict[str, dict], list[str]]:
    props: dict[str, dict] = {}
    required: list[str] = []

    for field_name, model_field in fields_iter:
        # exclude k8s identity/metadata control fields from CRD payload schema
        # but only at the root level (spec/status), not in nested models
        if is_root and field_name in kdantic_settings.crd_identity_fields:
            continue

        # prefer the serializationAlias as a name if present
        field_name_in_schema = model_field.serialization_alias or field_name

        field_type = get_field_annotation(model_field)
        is_optional = _is_optional(field_type)
        base_field_type = _strip_optional(field_type)

        schema = get_openapi_schema_for_type(
            base_field_type, field_name, custom_formats, is_nested=not is_root
        )

        description = get_field_description(model_field)
        title = get_field_title(model_field)
        if description:
            schema["description"] = description
        if "title" not in schema:
            schema["title"] = title or field_name.replace("_", " ").title()

        default_factory = get_default_factory(model_field)
        default_val = get_default(model_field)
        explicit_default = (
            default_val is not ...
            and default_val is not PydanticUndefined
            and default_val is not None
        )
        if explicit_default:
            schema["default"] = default_val

        if not is_optional and default_factory is None and not explicit_default:
            required.append(field_name_in_schema)

        if is_optional:
            schema["nullable"] = True

        props[field_name_in_schema] = schema

    return props, required


def build_k8s_model_schema(
    model: type[BaseModel], custom_formats: dict | None = None, is_root: bool = True
) -> dict:
    cf = custom_formats or {}
    cache_key = (model, id(cf), is_root)
    if cache_key in _schema_cache:
        return _schema_cache[cache_key]

    fields_map = get_model_fields_map(model)
    props, required = build_field_schemas(fields_map.items(), cf, is_root)
    schema = {
        "type": "object",
        "title": model.__name__,
        "properties": props,
        **({"required": required} if required else {}),
    }
    _schema_cache[cache_key] = schema
    return schema


def sanitize_for_yaml(obj: object):
    if isinstance(obj, dict):
        return {
            k: sanitize_for_yaml(v)
            for k, v in obj.items()
            if v is not PydanticUndefined
        }
    if isinstance(obj, list):
        return [sanitize_for_yaml(i) for i in obj if i is not PydanticUndefined]
    if isinstance(obj, _stdlib_enum.Enum):
        return obj.value
    return obj


def write_crd(path: Path | str, crd_doc: dict, overwrite: bool = False) -> None:
    yaml_dump = yaml.safe_dump(sanitize_for_yaml(crd_doc), sort_keys=False, indent=2)
    if kdantic_settings.helm:
        helm_injection = (
            f'{{{{- include "{kdantic_settings.helm}.labels" . | nindent 4 }}}}'
        )
        pattern = r"(?m)^(?P<indent>\s*)labels:\s*" + re.escape(HELM_SENTINEL) + r"\s*$"
        replacement = r"\g<indent>labels:\n\g<indent>  " + helm_injection
        yaml_dump = re.sub(pattern, replacement, yaml_dump)

    p = Path(path)
    if p.exists() and not overwrite:
        raise FileExistsError(f"File already exists: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml_dump)
