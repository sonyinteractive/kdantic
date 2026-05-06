from __future__ import annotations

from typing import Any

import kdantic.helpers.annotations as mut
import pytest
from pydantic import BaseModel

# -----------------------------------------------------------------------------
# Fixtures and shared helpers
# -----------------------------------------------------------------------------


@pytest.fixture
def fake_settings(monkeypatch):
    """Patch mut.kdantic_settings with only fields used by build_crd_meta()."""

    class S:
        default_group = "default.group"
        default_version = "v0"
        default_scope = "Cluster"
        default_singular = None
        default_plural = None
        default_short_names = None

    s = S()
    monkeypatch.setattr(mut, "kdantic_settings", s, raising=True)
    return s


class _ValidMeta:
    """Minimal __crd_meta__ object satisfying CRDMetaProtocol with all attrs None."""

    group: str | None = None
    version: str | None = None
    scope: str | None = None
    kind: str | None = None
    singular: str | None = None
    plural: str | None = None
    short_names: list[str] | None = None
    cel_rules: list[dict[str, Any]] | None = None

    # Class-level annotations required for _validate_dunder_crd_metadata to inspect
    __annotations__ = {
        "group": "str | None",
        "version": "str | None",
        "scope": "str | None",
        "kind": "str | None",
        "singular": "str | None",
        "plural": "str | None",
        "short_names": "list[str] | None",
        "cel_rules": "list[dict[str, Any]] | None",
    }


def _make_meta_instance(**overrides) -> _ValidMeta:
    """Return a fresh _ValidMeta instance with optional attribute overrides."""
    m = _ValidMeta()
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


# -----------------------------------------------------------------------------
# _validate_dunder_crd_metadata
# -----------------------------------------------------------------------------


def test_validate_dunder_meta_none_ok():
    mut._validate_dunder_crd_metadata(None)


def test_validate_dunder_meta_rejects_extra_attributes():
    class Meta:
        group: str | None
        version: str | None
        scope: str | None
        kind: str | None
        singular: str | None
        plural: str | None
        short_names: list[str] | None
        cel_rules: list[dict[str, Any]] | None

        typoed: str | None

    with pytest.raises(TypeError, match=r"Extra attributes in __crd_meta__"):
        mut._validate_dunder_crd_metadata(Meta())


def test_validate_dunder_meta_rejects_missing_attributes():
    class Meta:
        group: str | None

    with pytest.raises(TypeError, match=r"Missing attributes in __crd_meta__"):
        mut._validate_dunder_crd_metadata(Meta())


def test_validate_dunder_meta_short_names_must_be_iterable_of_stringlikes():
    m = _make_meta_instance(short_names="nope")
    with pytest.raises(TypeError, match=r"short_names.*must be an iterable"):
        mut._validate_dunder_crd_metadata(m)

    m.short_names = ["ok", object()]
    with pytest.raises(TypeError, match=r"All elements of 'short_names' must be string-like"):
        mut._validate_dunder_crd_metadata(m)


def test_validate_dunder_meta_cel_rules_mapping_rule_must_be_string():
    m = _make_meta_instance(cel_rules=[{"rule": 123}])
    with pytest.raises(TypeError, match=r"cel_rules\[0\]\.rule must be a string"):
        mut._validate_dunder_crd_metadata(m)


def test_validate_dunder_meta_cel_rules_accepts_mapping_and_basemodel():
    class RuleModel(BaseModel):
        rule: str
        message: str | None = None

    m = _make_meta_instance(cel_rules=[{"rule": "self.spec.foo > 0"}, RuleModel(rule="has(self.spec)")])
    mut._validate_dunder_crd_metadata(m)


def test_validate_dunder_meta_cel_rules_rejects_unknown_item():
    m = _make_meta_instance(cel_rules=[object()])
    with pytest.raises(TypeError, match=r"cel_rules\[0\] must be a mapping or BaseModel"):
        mut._validate_dunder_crd_metadata(m)


# -----------------------------------------------------------------------------
# CRDMetaData._coerce_cel_rules
# -----------------------------------------------------------------------------


def test_crdmetadata_coerces_cel_rules_items_to_dicts():
    class RuleModel(BaseModel):
        rule: str
        message: str | None = None

    data = {
        "group": "g",
        "version": "v1",
        "scope": "Cluster",
        "names": {"kind": "K", "singular": "k", "plural": "ks", "shortNames": ["k"]},
        "cel_rules": [
            {"rule": "self.spec.foo > 0"},
            RuleModel(rule="has(self.spec)", message=None),
        ],
    }
    meta = mut.CRDMetaData.model_validate(data)
    assert meta.cel_rules == [{"rule": "self.spec.foo > 0"}, {"rule": "has(self.spec)"}]


def test_crdmetadata_coerce_cel_rules_rejects_invalid_item_type():
    data = {
        "group": "g",
        "version": "v1",
        "scope": "Cluster",
        "names": {"kind": "K", "singular": "k", "plural": "ks", "shortNames": ["k"]},
        "cel_rules": [object()],
    }
    with pytest.raises(TypeError, match=r"Invalid cel_rules item type"):
        mut.CRDMetaData.model_validate(data)


# -----------------------------------------------------------------------------
# build_crd_meta (precedence + error handling)
# -----------------------------------------------------------------------------


def test_build_crd_meta_annotations_override_dunder_and_settings(fake_settings, monkeypatch):
    """Annotation-derived values (group/version/kind/scope) take priority over dunder and settings."""

    class Model(BaseModel):
        pass

    monkeypatch.setattr(mut, "_derive_group_version_from_annotations", lambda *_: ("ann.group", "v7"), raising=True)
    monkeypatch.setattr(mut, "_derive_scope_from_annotations", lambda *_: "Namespaced", raising=True)
    monkeypatch.setattr(mut, "_derive_kind_from_annotations", lambda *_: "AnnKind", raising=True)
    monkeypatch.setattr(mut, "_pluralize", lambda s: s + "s", raising=True)
    monkeypatch.setattr(mut, "_short_name", lambda kind: kind.lower(), raising=True)

    Model.__crd_meta__ = _make_meta_instance(
        group="dunder.group",
        version="v2",
        scope="Cluster",
        kind="DunderKind",
        singular="dunderkind",
        plural="dunderkinds",
        short_names=["dk"],
        cel_rules=[{"rule": "x"}],
    )

    meta = mut.build_crd_meta(Model)

    assert meta.group == "ann.group"
    assert meta.version == "v7"
    assert meta.scope == "Namespaced"
    assert meta.names.kind == "AnnKind"
    assert meta.names.singular == "dunderkind"
    assert meta.names.plural == "dunderkinds"
    assert meta.cel_rules == [{"rule": "x"}]


def test_build_crd_meta_invalid_dunder_is_ignored_and_falls_back(fake_settings, monkeypatch, caplog):
    """If __crd_meta__ fails protocol validation, it is ignored and settings defaults are used."""
    caplog.set_level("ERROR", logger="kdantic")

    class Model(BaseModel):
        pass

    monkeypatch.setattr(mut, "_derive_group_version_from_annotations", lambda *_: (None, None), raising=True)
    monkeypatch.setattr(mut, "_derive_scope_from_annotations", lambda *_: None, raising=True)
    monkeypatch.setattr(mut, "_derive_kind_from_annotations", lambda *_: None, raising=True)
    monkeypatch.setattr(mut, "_pluralize", lambda s: s + "s", raising=True)
    monkeypatch.setattr(mut, "_short_name", lambda kind: "sn", raising=True)

    class BadMeta:
        group: str | None

    Model.__crd_meta__ = BadMeta()

    meta = mut.build_crd_meta(Model)

    assert meta.group == fake_settings.default_group
    assert meta.version == fake_settings.default_version
    assert meta.scope == fake_settings.default_scope
    assert meta.names.kind == mut._derive_kind_by_name(Model)
    assert any("Ignoring invalid __crd_meta__" in rec.message for rec in caplog.records)
