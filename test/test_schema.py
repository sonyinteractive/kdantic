from __future__ import annotations

import enum
import logging
import re
from typing import Annotated, Literal

import kdantic.helpers.schema as mut
import pytest
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def fake_settings(monkeypatch, tmp_path):
    """
    Patch mut.kdantic_settings with just the attributes used by this module.
    """

    class S:
        crd_identity_fields = {
            "apiVersion",
            "kind",
            "metadata",
        }  # excluded from payload schema
        helm = False
        helm_template = "chartname"

    s = S()
    monkeypatch.setattr(mut, "kdantic_settings", s, raising=True)
    return s


@pytest.fixture(autouse=True)
def clear_schema_cache():
    mut._schema_cache.clear()
    yield
    mut._schema_cache.clear()


# -----------------------------------------------------------------------------
# unwrap_all_fieldinfos
# -----------------------------------------------------------------------------


def test_unwrap_all_fieldinfos_collects_fieldinfo_from_annotated():
    T = Annotated[int, Field(title="My Title", description="My Desc")]
    base, infos = mut.unwrap_all_fieldinfos(T)
    assert base is int
    assert len(infos) == 1
    assert infos[0].title == "My Title"
    assert infos[0].description == "My Desc"


def test_unwrap_all_fieldinfos_follows_module_alias_annotated():
    """
    If a type is re-exported/aliased in its module name to an Annotated alias,
    unwrap_all_fieldinfos should follow it and collect FieldInfo extras.
    """

    class Dummy:
        __module__ = "dummy_mod"

    class FakeMod:
        pass

    alias = Annotated[Dummy, Field(title="Alias Title")]
    FakeMod.Dummy = alias

    import sys

    sys.modules["dummy_mod"] = FakeMod

    base, infos = mut.unwrap_all_fieldinfos(Dummy)
    assert base is Dummy
    assert len(infos) == 1
    assert infos[0].title == "Alias Title"


# -----------------------------------------------------------------------------
# build_enum_schema + _literal_strings
# -----------------------------------------------------------------------------


def test_build_enum_schema_uses_member_value_type():
    class E(enum.Enum):
        A = 1
        B = 2

    schema = mut.build_enum_schema(E)
    assert schema["enum"] == [1, 2]
    assert schema["type"] in {
        "integer",
        "number",
    }  # depends on openapi_primitive mapping


def test_literal_strings_returns_only_string_literals():
    assert mut._literal_strings(Literal["a", "b"]) == ["a", "b"]
    assert mut._literal_strings(Literal["a", 1]) == ["a"]
    assert mut._literal_strings(int) is None


# -----------------------------------------------------------------------------
# get_openapi_schema_for_type
# -----------------------------------------------------------------------------


def test_get_openapi_schema_for_type_union_picks_first_non_none(monkeypatch):
    monkeypatch.setattr(
        mut,
        "openapi_primitive",
        lambda t: "integer" if t is int else None,
        raising=True,
    )

    schema = mut.get_openapi_schema_for_type(int | None, "x", custom_formats={})
    assert schema == {"type": "integer"}


def test_get_openapi_schema_for_type_literal_string_enum(monkeypatch):
    schema = mut.get_openapi_schema_for_type(Literal["x", "y"], "f", custom_formats={})
    assert schema["type"] == "string"
    assert schema["enum"] == ["x", "y"]


def test_get_openapi_schema_for_type_custom_format_by_name_lower(monkeypatch):
    monkeypatch.setattr(mut, "openapi_primitive", lambda _t: None, raising=True)

    class IPvAnyNetwork:
        __name__ = "IPvAnyNetwork"

    schema = mut.get_openapi_schema_for_type(IPvAnyNetwork, "net", custom_formats={"ipvanynetwork": "ipvanynetwork"})
    assert schema == {"type": "string", "format": "ipvanynetwork"}


def test_get_openapi_schema_for_type_list(monkeypatch):
    monkeypatch.setattr(
        mut,
        "openapi_primitive",
        lambda t: "integer" if t is int else None,
        raising=True,
    )
    schema = mut.get_openapi_schema_for_type(list[int], "nums", custom_formats={})
    assert schema["type"] == "array"
    assert schema["items"] == {"type": "integer"}


def test_get_openapi_schema_for_type_mapping_warns_on_non_string_keys(monkeypatch, caplog):
    monkeypatch.setattr(
        mut,
        "openapi_primitive",
        lambda t: "integer" if t is int else None,
        raising=True,
    )
    caplog.set_level(logging.WARNING, logger="kdantic")

    schema = mut.get_openapi_schema_for_type(dict[int, int], "m", custom_formats={})
    assert schema["type"] == "object"
    assert schema["additionalProperties"] == {"type": "integer"}
    assert any("map keys coerced to string" in rec.message for rec in caplog.records)


def test_get_openapi_schema_for_type_basemodel_recurses(monkeypatch):
    monkeypatch.setattr(mut, "openapi_primitive", lambda _t: None, raising=True)

    class Child(BaseModel):
        x: int

    monkeypatch.setattr(mut, "build_k8s_model_schema", lambda m, cf, is_root=True: {"title": m.__name__}, raising=True)

    schema = mut.get_openapi_schema_for_type(Child, "child", custom_formats={})
    assert schema == {"title": "Child"}


def test_get_openapi_schema_for_type_enum(monkeypatch):
    monkeypatch.setattr(mut, "openapi_primitive", lambda t: "string" if t is str else None, raising=True)

    class Color(enum.Enum):
        RED = "red"
        BLUE = "blue"

    schema = mut.get_openapi_schema_for_type(Color, "c", custom_formats={})
    assert schema["type"] == "string"
    assert schema["enum"] == ["red", "blue"]


def test_get_openapi_schema_for_type_applies_fieldinfo_extras(monkeypatch):
    monkeypatch.setattr(
        mut,
        "openapi_primitive",
        lambda t: "integer" if t is int else None,
        raising=True,
    )

    T = Annotated[int, Field(title="T", description="D", json_schema_extra={"minimum": 0})]
    schema = mut.get_openapi_schema_for_type(T, "age", custom_formats={})

    assert schema["type"] == "integer"
    assert schema["title"] == "T"
    assert schema["description"] == "D"
    assert schema["minimum"] == 0


# -----------------------------------------------------------------------------
# build_field_schemas
# -----------------------------------------------------------------------------


def test_build_field_schemas_excludes_identity_fields(fake_settings):
    class Root(BaseModel):
        apiVersion: str
        kind: str
        metadata: dict
        spec: str

    props, required = mut.build_field_schemas(Root.model_fields.items(), custom_formats={}, is_root=True)

    assert "apiVersion" not in props
    assert "kind" not in props
    assert "metadata" not in props
    assert "spec" in props
    assert required == ["spec"]

    class Nested(BaseModel):
        kind: str
        name: str

    nested_props, nested_required = mut.build_field_schemas(Nested.model_fields.items(), custom_formats={}, is_root=False)

    assert "kind" in nested_props
    assert "name" in nested_props
    assert nested_required == ["kind", "name"]


def test_build_field_schemas_real_model_behaviors(fake_settings):
    """Covers serialization alias, optional/nullable, explicit default, and required logic."""

    class Spec(BaseModel):
        renamed_field: str = Field(serialization_alias="renamedField")
        optional_field: str | None = None
        required_field: int
        field_with_default: int = 7

    props, required = mut.build_field_schemas(Spec.model_fields.items(), custom_formats={})

    assert "renamedField" in props
    assert "renamedField" in required

    assert "optional_field" not in required
    assert props["optional_field"]["nullable"] is True

    assert "required_field" in required

    assert "field_with_default" not in required
    assert props["field_with_default"]["default"] == 7


# -----------------------------------------------------------------------------
# build_k8s_model_schema + caching
# -----------------------------------------------------------------------------


def test_build_k8s_model_schema_uses_cache(fake_settings):
    class M(BaseModel):
        a: int

    cf = {}
    s1 = mut.build_k8s_model_schema(M, cf)
    s2 = mut.build_k8s_model_schema(M, cf)

    assert s1 is s2


# -----------------------------------------------------------------------------
# sanitize_for_yaml
# -----------------------------------------------------------------------------


def test_sanitize_for_yaml_drops_pydanticundefined_and_converts_enum():
    class E(enum.Enum):
        A = "a"

    undef = mut.PydanticUndefined

    obj = {
        "keep": 1,
        "drop": undef,
        "enum": E.A,
        "list": [1, undef, E.A],
        "nested": {"x": undef, "y": 2},
    }

    out = mut.sanitize_for_yaml(obj)
    assert "drop" not in out
    assert out["enum"] == "a"
    assert out["list"] == [1, "a"]
    assert out["nested"] == {"y": 2}


# -----------------------------------------------------------------------------
# write_crd
# -----------------------------------------------------------------------------


def test_write_crd_refuses_overwrite_by_default(fake_settings, tmp_path):
    p = tmp_path / "out.yaml"
    p.write_text("already")

    with pytest.raises(FileExistsError):
        mut.write_crd(str(p), {"a": 1}, overwrite=False)


def test_write_crd_writes_yaml_and_creates_parents(fake_settings, tmp_path):
    p = tmp_path / "a" / "b" / "crd.yaml"
    mut.write_crd(str(p), {"a": 1}, overwrite=True)

    text = p.read_text()
    assert re.search(r"^a:\s*1\s*$", text, re.MULTILINE)  # simple YAML content


def test_write_crd_helm_injection_replaces_sentinel(fake_settings, tmp_path):
    """
    If kdantic_settings.helm is truthy, write_crd replaces:
      labels: __HELM_SENTINEL__
    with the Helm include snippet.
    """
    fake_settings.helm = "mychart"

    p = tmp_path / "crd.yaml"
    doc = {
        "metadata": {
            "labels": mut.HELM_SENTINEL,
        }
    }

    mut.write_crd(str(p), doc, overwrite=True)
    text = p.read_text()

    assert mut.HELM_SENTINEL not in text
    assert '{{- include "mychart.labels" . | nindent 4 }}' in text


def test_write_crd_does_not_inject_when_no_sentinel(fake_settings, tmp_path):
    fake_settings.helm = "mychart"

    p = tmp_path / "crd.yaml"
    doc = {"metadata": {"labels": {"x": "y"}}}

    mut.write_crd(str(p), doc, overwrite=True)
    text = p.read_text()

    assert '{{- include "mychart.labels"' not in text
    assert "x: y" in text
