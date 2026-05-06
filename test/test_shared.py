from __future__ import annotations

from typing import Literal

import kdantic.helpers.shared as mut
from pydantic import BaseModel


# -----------------------------------------------------------------------------
# Optional helpers
# -----------------------------------------------------------------------------


def test_is_optional_pep604():
    assert mut._is_optional(int | None) is True
    assert mut._is_optional(int) is False


def test_is_optional_typing_union():
    from typing import Union

    assert mut._is_optional(Union[int, None]) is True


def test_strip_optional_returns_inner_type():
    assert mut._strip_optional(int | None) is int
    assert mut._strip_optional(str) is str


# -----------------------------------------------------------------------------
# Small shared helpers
# -----------------------------------------------------------------------------


def test_normalize_short_names_from_string():
    assert mut._normalize_short_names("a,b, c") == ["a", "b", "c"]
    assert mut._normalize_short_names("") == []


def test_normalize_short_names_from_list_tuple_and_scalar():
    assert mut._normalize_short_names([" a ", ""]) == ["a"]
    assert mut._normalize_short_names(("x", " y")) == ["x", "y"]
    assert mut._normalize_short_names(123) == ["123"]


def test_normalize_scope_accepts_prefixes():
    assert mut._normalize_scope("Namespaced") == "Namespaced"
    assert mut._normalize_scope("namespace") == "Namespaced"
    assert mut._normalize_scope("Cluster") == "Cluster"
    assert mut._normalize_scope("clus") == "Cluster"
    assert mut._normalize_scope("other") is None
    assert mut._normalize_scope(None) is None


def test_literal_str_from_annotations_returns_first_literal():
    class M(BaseModel):
        kind: Literal["Foo", "Bar"]

    assert mut._literal_str_from_annotations(M, "kind") == "Foo"
    assert mut._literal_str_from_annotations(M, "missing") is None


def test_only_letters_strips_non_alpha_and_lowercases():
    assert mut._only_letters("A1_B-2") == "ab"


def test_short_name_generation():
    # "Widget" -> only letters "widget" (len 6) => w + widget[3] + t = "wgt"
    assert mut._short_name("Widget") == "wgt"
    # small kinds fall back to the letters as-is
    assert mut._short_name("AB") == "ab"
    assert mut._short_name("") == "cr"


def test_pluralize_rules():
    assert mut._pluralize("bus") == "buses"
    assert mut._pluralize("box") == "boxes"
    assert mut._pluralize("church") == "churches"
    assert mut._pluralize("dish") == "dishes"
    assert mut._pluralize("party") == "parties"
    assert mut._pluralize("key") == "keys"
    assert mut._pluralize("cat") == "cats"


def test_openapi_primitive_mapping():
    assert mut.openapi_primitive(bool) == "boolean"
    assert mut.openapi_primitive(int) == "integer"
    assert mut.openapi_primitive(float) == "number"
    assert mut.openapi_primitive(str) == "string"

    class X: ...

    assert mut.openapi_primitive(X) is None