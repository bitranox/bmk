"""Behaviour tests for the tomlkit boundary wrapper.

This module is the single seam through which bmk EDITS a user's TOML (the dependency-floor
bumps in `_dependencies.update_dependencies` write `pyproject.toml` back through it). Its
load-bearing property is therefore not "it parses TOML" but "a parse/dumps round-trip
preserves everything it did not deliberately change" - comments most of all, since a
pyproject.toml's comments carry the reasoning for its pins.
"""

from __future__ import annotations

import pytest

from bmk.adapters.stagerunner.helpers._typed_tomlkit import TOMLKitError, dumps, parse

# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_parse_returns_an_editable_mapping() -> None:
    """A parsed document supports item access and mutation."""
    doc = parse('[project]\nname = "demo"\n')

    assert doc["project"]["name"] == "demo"


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("unclosed table header", "[project\nname = 1\n"),
        ("bare value", "name =\n"),
        ("unterminated string", 'name = "demo\n'),
        ("garbage", "!!! not toml at all !!!\n"),
        ("duplicate key", '[project]\nname = "a"\nname = "b"\n'),
    ],
)
def test_parse_raises_tomlkiterror_on_malformed_input(label: str, text: str) -> None:
    """Malformed TOML raises TOMLKitError rather than returning a half-parsed document.

    Callers catch TOMLKitError by name, so a different exception type escaping this seam
    would surface as an unhandled crash.
    """
    with pytest.raises(TOMLKitError):
        parse(text)


@pytest.mark.os_agnostic
def test_parse_accepts_empty_input() -> None:
    """An empty file is valid TOML: an empty document, not an error."""
    assert dict(parse("")) == {}


# ---------------------------------------------------------------------------
# dumps - round-trip fidelity
# ---------------------------------------------------------------------------


_PYPROJECT = """# Top-of-file rationale that must survive.
[project]
name = "demo"
dependencies = [
    # This floor is load-bearing: do not raise it in a sweep.
    "build>=1.5.0",
    "ruff>=0.15.21",  # trailing comment
]

[tool.bmk]
enabled = true
"""


@pytest.mark.os_agnostic
def test_round_trip_without_edits_is_byte_identical() -> None:
    """parse -> dumps changes nothing when nothing was edited."""
    assert dumps(parse(_PYPROJECT)) == _PYPROJECT


@pytest.mark.os_agnostic
def test_round_trip_preserves_comments_and_formatting_across_an_edit() -> None:
    """Editing one value leaves every comment and the surrounding layout intact.

    This is the property that protects a user's pyproject.toml when bmk bumps a dependency
    floor: a plain read/write TOML library would silently drop all of these comments.
    """
    doc = parse(_PYPROJECT)
    doc["tool"]["bmk"]["enabled"] = False

    out = dumps(doc)

    assert "# Top-of-file rationale that must survive." in out
    assert "# This floor is load-bearing: do not raise it in a sweep." in out
    assert "# trailing comment" in out
    assert "enabled = false" in out
    assert '"build>=1.5.0"' in out


@pytest.mark.os_agnostic
def test_round_trip_preserves_a_comment_attached_to_a_replaced_dependency() -> None:
    """Rewriting a dependency string keeps the comment on the line above it."""
    doc = parse(_PYPROJECT)
    doc["project"]["dependencies"][1] = "ruff>=0.16.0"

    out = dumps(doc)

    assert "# This floor is load-bearing: do not raise it in a sweep." in out
    assert "ruff>=0.16.0" in out
