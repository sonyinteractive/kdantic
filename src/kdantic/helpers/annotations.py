"""
Helpers for deriving Kubernetes CustomResourceDefinition (CRD) metadata from
Pydantic model annotations, optional dunder metadata objects, and settings.
The resolution order ensures explicit model intent overrides defaults while
producing consistent, validated CRD metadata structures.
"""

import logging
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, get_type_hints, runtime_checkable

from kdantic.helpers.settings import kdantic_settings
from kdantic.helpers.shared import (
    _literal_str_from_annotations,
    _pluralize,
    _short_name,
    get_default,
    get_model_fields_map,
)
from pydantic import BaseModel, Field, model_validator

logging.getLogger("kdantic").addHandler(logging.NullHandler())
log = logging.getLogger("kdantic")


@runtime_checkable
class CRDMetaProtocol(Protocol):
    """
    PEP-544 Protocol describing the expected shape of a model-level __crd_meta__ object.

    All attributes are optional (may be None). This is used for structural validation
    to catch typos and ensure only the supported keys are provided.

    Attributes:
        group: API group (e.g. "apps").
        version: API version (e.g. "v1").
        scope: "Namespaced" or "Cluster".
        kind: Kubernetes Kind (e.g. "Deployment").
        singular: Singular resource name (DNS-safe lowercase).
        plural: Plural resource name.
        short_names: Optional list of short names (kubectl shortcuts).
        cel_rules: Optional list of CEL rules (each a dict with 'rule' and optional 'message').

    """

    group: str | None
    version: str | None
    scope: str | None
    kind: str | None
    singular: str | None
    plural: str | None
    short_names: list[str] | None
    cel_rules: list[dict[str, Any]] | None

    @classmethod
    def fields(cls) -> list[str]:
        """Return the ordered list of protocol attribute names."""
        return list(cls.__annotations__.keys())


def _validate_dunder_crd_metadata(meta: Any) -> None:
    """
    Validate a __crd_meta__ object against CRDMetaProtocol.

    Ensures:
      - Only the allowed attributes are present.
      - All declared attributes are annotated.
      - Values are either None or string-like (except short_names which must be an iterable of string-like items).

    Raises:
        TypeError: If the structure or any value is invalid.

    """
    if meta is None:
        return

    proto_fields = CRDMetaProtocol.fields()
    meta_annotations = getattr(type(meta), "__annotations__", {})
    declared = set(meta_annotations.keys())

    extra = [f for f in declared if f not in proto_fields]
    if extra:
        raise TypeError(f"Extra attributes in __crd_meta__: {extra} (perhaps a typo?)")

    missing = [f for f in proto_fields if f not in declared]
    if missing:
        raise TypeError(f"Missing attributes in __crd_meta__: {missing}")

    def _is_string_like(obj: Any) -> bool:
        return isinstance(obj, (str, bytes, bytearray))

    for name in proto_fields:
        value = getattr(meta, name, None)
        if value is None:
            continue

        if name == "short_names":
            if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Iterable):
                raise TypeError("Attribute 'short_names' must be an iterable of string-like objects or None")

            bad_elems: list[str] = []
            for idx, elem in enumerate(value):
                if not _is_string_like(elem):
                    bad_elems.append(f"{idx}:{type(elem).__name__}")
            if bad_elems:
                raise TypeError(f"All elements of 'short_names' must be string-like; bad elements at {bad_elems}")
        elif name == "cel_rules":
            if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Iterable):
                raise TypeError(
                    "Attribute 'cel_rules' must be an iterable of mappings/BaseModels (each with 'rule' and optional 'message') or None"
                )
            for idx, elem in enumerate(value):
                if isinstance(elem, Mapping):
                    rule = elem.get("rule")
                    if not isinstance(rule, (str, bytes, bytearray)):
                        raise TypeError(f"cel_rules[{idx}].rule must be a string")
                    if (
                        "message" in elem
                        and elem["message"] is not None
                        and not isinstance(elem["message"], (str, bytes, bytearray))
                    ):
                        raise TypeError(f"cel_rules[{idx}].message must be a string if provided")
                    continue

                if isinstance(elem, BaseModel):
                    rule = getattr(elem, "rule", None)
                    if not isinstance(rule, (str, bytes, bytearray)):
                        raise TypeError(f"cel_rules[{idx}].rule must be a string")
                    message = getattr(elem, "message", None)
                    if message is not None and not isinstance(message, (str, bytes, bytearray)):
                        raise TypeError(f"cel_rules[{idx}].message must be a string if provided")
                    continue

                raise TypeError(f"cel_rules[{idx}] must be a mapping or BaseModel, got {type(elem).__name__}")
        elif not _is_string_like(value):
            raise TypeError(
                f"Attribute '{name}' on __crd_meta__ must be string-like | None, got {type(value).__name__}"
            )


class CRDMetaDataNames(BaseModel):
    """
    Names sub-structure of a CRD spec.

    Fields:
        kind: Kubernetes Kind (PascalCase).
        singular: Singular resource identifier (lowercase).
        plural: Plural resource identifier.
        shortNames: List of kubectl shorthand aliases.
    """

    kind: str
    singular: str
    plural: str
    shortNames: list[str]


class CRDMetaData(BaseModel):
    """
    Top-level CRD metadata container resolved from model + settings.

    Fields:
        group: API group.
        version: API version.
        scope: Cluster scope ("Cluster" or "Namespaced").
        names: Nested name variants (kind, singular, plural, shortNames).
        cel_rules: Optional list of CEL rules (each a dict with 'rule' and optional 'message').
    """

    group: str
    version: str
    scope: str
    names: CRDMetaDataNames
    cel_rules: list[dict[str, Any]] | None = Field(default=None, repr=False)

    @model_validator(mode="before")
    @classmethod
    def _coerce_cel_rules(cls, data: Any):
        if not isinstance(data, dict):
            return data
        rules = data.get("cel_rules")
        if rules is None:
            return data
        if isinstance(rules, (str, bytes, bytearray)) or not isinstance(rules, Iterable):
            return data

        normalized: list[dict[str, Any]] = []
        for r in rules:
            if isinstance(r, BaseModel):
                normalized.append(r.model_dump(by_alias=True, exclude_none=True))
            elif isinstance(r, Mapping):
                normalized.append(dict(r))
            else:
                raise TypeError(f"Invalid cel_rules item type: {type(r).__name__}; expected Mapping or BaseModel")
        new = dict(data)
        new["cel_rules"] = normalized
        return new


# ------------------------------------------------------------------------------
# CRD metadata derivation (annotations → CLI cfg → dunder)
# with explicit CLI flags taking highest precedence
# ------------------------------------------------------------------------------


def _derive_kind_from_annotations(model: type[BaseModel]) -> str | None:
    """
    Derive the 'kind' string from model annotations or field defaults.

    Args:
        model (type[BaseModel]): The Pydantic model class to inspect.

    Returns:
        str | None: The derived kind string, or None if not found.

    Example:
        >>> class MyModel(BaseModel):
        ...     kind: str = "ExampleKind"
        >>> _derive_kind_from_annotations(MyModel)
        'ExampleKind'

    """
    lit = _literal_str_from_annotations(model, "kind")
    if lit:
        return lit
    fields = get_model_fields_map(model)
    f = fields.get("kind")
    if f is not None:
        dv = get_default(f)
        if isinstance(dv, str):
            return dv
        if dv is not None and hasattr(dv, "value") and isinstance(dv.value, str):
            return dv.value
    return None


def _derive_group_version_from_annotations(
    model: type[BaseModel],
) -> tuple[str | None, str | None]:
    """
    Derive the (group, version) tuple from model annotations or field defaults.

    Args:
        model (type[BaseModel]): The Pydantic model class to inspect.

    Returns:
        tuple[str | None, str | None]: The derived (group, version) tuple, or (None, None) if not found.

    Example:
        >>> class MyModel(BaseModel):
        ...     apiVersion: str = "mygroup/v1"
        >>> _derive_group_version_from_annotations(MyModel)
        ('mygroup', 'v1')

    """
    lit = _literal_str_from_annotations(model, "apiVersion")
    value = lit
    if value is None:
        fields = get_model_fields_map(model)
        f = fields.get("apiVersion")
        if f is not None:
            dv = get_default(f)
            if isinstance(dv, str):
                value = dv
            elif dv is not None and hasattr(dv, "value") and isinstance(dv.value, str):
                value = dv.value
    if not value or "/" not in value:
        log.debug(f"apiVersion not in group/version form: {value!r}")
        return None, None
    group_str, version_str = value.split("/", 1)
    return group_str, version_str


def _derive_scope_from_annotations(model: type[BaseModel]) -> str | None:
    """
    Derive the scope ('Namespaced' or 'Cluster') from model annotations.

    Args:
        model (type[BaseModel]): The Pydantic model class to inspect.

    Returns:
        str | None: 'Namespaced' if a 'namespace' field is present, otherwise 'Cluster'.

    Example:
        >>> class MyModel(BaseModel):
        ...     namespace: str
        >>> _derive_scope_from_annotations(MyModel)
        'Namespaced'

    """
    fields = get_model_fields_map(model)
    if "namespace" in fields:
        return "Namespaced"

    meta_field = fields.get("metadata")
    meta_type: type[BaseModel] | None = None

    try:
        hints = get_type_hints(model)
    except Exception:
        hints = {}

    meta_ann = hints.get("metadata")
    if isinstance(meta_ann, type) and issubclass(meta_ann, BaseModel):
        meta_type = meta_ann
    elif meta_field is not None:
        meta_type = meta_field.annotation

    if isinstance(meta_type, type) and issubclass(meta_type, BaseModel):
        if "namespace" in get_model_fields_map(meta_type):
            return "Namespaced"
    return "Cluster"


def _derive_kind_by_name(model: type[BaseModel]) -> str:
    """
    Derive the kind name from the model class name.

    Args:
        model (type[BaseModel]): The Pydantic model class.

    Returns:
        str: The derived kind name.

    Example:
        >>> class K8sFooModel(BaseModel): pass
        >>> _derive_kind_by_name(K8sFooModel)
        'Foo'

    """
    name_s = model.__name__
    name_s = name_s.removeprefix("K8s")
    name_s = name_s.removesuffix("Model")
    return name_s or model.__name__


def _derive_singular_from_kind(kind: str) -> str:
    """
    Derive the singular name from the kind string.

    Args:
        kind (str): The kind string.

    Returns:
        str: The singular name (lowercase).

    Example:
        >>> _derive_singular_from_kind("Pod")
        'pod'

    """
    return (kind or "").lower()


def build_crd_meta(
    model: type[BaseModel],
) -> CRDMetaData:
    """
    Build CRDMetaData for a given Pydantic model, resolving values from multiple sources in priority order.
    Validates an optional __crd_meta__ attribute against a PEP 544 Protocol (CRDMetaProtocol). Invalid
    shapes are logged and ignored.

    The function determines the CRD metadata fields by checking, in order:
      1. **Annotations**: Attempts to extract `apiVersion`, `kind`, and `scope` from model field annotations or
        defaults.
      2. **Dunder Metadata**: Checks for a single dunder attribute `__crd_meta__` on the model, which should be a
        BaseModel-like object (see below).
      3. **Settings Fallback**: Uses global `settings` defaults if neither annotations nor dunder metadata
        provide a value (originating from the CLI, or a configurartion file).
      4. **Derivation**: For names, derives `kind` from the class name, `singular` from kind, and `plural` from
        singular if not otherwise set.

    The `__crd_meta__` attribute, if present, must be an object (typically a Pydantic BaseModel) with the following
    attributes (protocol):

        - group: str | None
        - version: str | None
        - scope: str | None
        - kind: str | None
        - singular: str | None
        - plural: str | None
        - short_names: list[str] | None
        - cel_rules: list[dict[str, Any]] | None

    Args:
        model (type[BaseModel]): The Pydantic model class to inspect.

    Returns:
        CRDMetaData: The constructed CRDMetaData object with resolved group, version, scope, and names.

    Example:
        >>> class MyMeta(BaseModel):
        ...     group: str = "mygroup"
        ...     version: str = "v1"
        ...     scope: str = "Namespaced"
        ...     kind: str = "Foo"
        ...     singular: str = "foo"
        ...     plural: str = "foos"
        ...     short_names: list[str] = ["foo"]
        >>> class MyModel(BaseModel):
        ...     kind: str = "Foo"
        ...     apiVersion: str = "mygroup/v1"
        ...     namespace: str
        ...     __crd_meta__ = MyMeta()
        >>> build_crd_meta(MyModel)
        CRDMetaData(
            group='mygroup',
            version='v1',
            scope='Namespaced',
            names={'kind': 'Foo', 'singular': 'foo', 'plural': 'foos', 'shortNames': ['foo']}
        )

    The resolution order for each field is:
        - group: annotation (`apiVersion`), dunder metadata (`group`), settings default
        - version: annotation (`apiVersion`), dunder metadata (`version`), settings default
        - scope: annotation (namespace field), dunder metadata (`scope`), settings default
        - kind: annotation (`kind`), dunder metadata (`kind`), derived from class name
        - singular: dunder metadata (`singular`), settings default, derived from kind
        - plural: dunder metadata (`plural`), settings default, derived from singular
        - short_names: dunder metadata (`shortNames`), settings default, derived from kind

    """
    # 1) Annotations (apiVersion/kind/scope inference)
    group_from_ann, version_from_ann = _derive_group_version_from_annotations(model)
    scope_from_ann = _derive_scope_from_annotations(model)
    kind_from_ann = _derive_kind_from_annotations(model)

    # 2) Dunder metadata (protocol: see docstring)
    meta = getattr(model, "__crd_meta__", None)
    if meta is not None:
        try:
            _validate_dunder_crd_metadata(meta)
            log.debug(f"using __crd_meta__ from {model.__name__}: {meta!r}")
        except TypeError as e:
            log.error(
                "Ignoring invalid __crd_meta__ on %s: %s",
                model.__name__,
                e,
            )
            meta = None

    def _get_meta_attr(attr, default=None):
        return getattr(meta, attr, default) if meta is not None else default

    d_group = _get_meta_attr("group")
    d_version = _get_meta_attr("version")
    d_scope = _get_meta_attr("scope")
    d_kind = _get_meta_attr("kind")
    d_singular = _get_meta_attr("singular")
    d_plural = _get_meta_attr("plural")
    d_short = list(_get_meta_attr("short_names") or [])
    d_cel = _get_meta_attr("cel_rules")

    # 3) Choose high-level values
    group_val = group_from_ann or d_group or kdantic_settings.default_group
    version_val = version_from_ann or d_version or kdantic_settings.default_version
    scope_val = scope_from_ann or d_scope or kdantic_settings.default_scope
    kind_val = kind_from_ann or d_kind or _derive_kind_by_name(model)
    short_names_val = d_short or kdantic_settings.default_short_names or [_short_name(kind_val)]

    # 4) Names resolution (singular/plural/shortNames) with the requested fallback order
    singular_val = d_singular or kdantic_settings.default_singular or _derive_singular_from_kind(kind_val)
    plural_val = d_plural or kdantic_settings.default_plural or _pluralize(singular_val)

    metadata = CRDMetaData(
        group=group_val,
        version=version_val,
        scope=scope_val,
        names={
            "kind": kind_val,
            "singular": singular_val,
            "plural": plural_val,
            "shortNames": short_names_val,
        },
        cel_rules=d_cel,
    )
    log.info(f"CRD metadata for {model.__name__}: {metadata}")
    return metadata