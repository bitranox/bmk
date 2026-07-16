"""Behaviour tests for stagerunner.helpers._toml_config: degradation and Poetry version translation."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmk.adapters.stagerunner.helpers._toml_config import PoetryDepSpec, PyprojectConfig

# ---------------------------------------------------------------------------
# PyprojectConfig.from_path - degradation on a missing/malformed file
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_from_path_malformed_toml_returns_defaults_and_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A malformed pyproject.toml degrades to an all-default config and warns on stderr."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project\nname = 'broken'\n")

    config = PyprojectConfig.from_path(pyproject)

    assert config == PyprojectConfig()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"Warning: Failed to parse {pyproject}:" in captured.err


@pytest.mark.os_agnostic
def test_from_path_missing_file_returns_defaults_without_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-existent path degrades to an all-default config with no stderr output."""
    pyproject = tmp_path / "does_not_exist.toml"

    config = PyprojectConfig.from_path(pyproject)

    assert config == PyprojectConfig()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# ---------------------------------------------------------------------------
# PoetryDepSpec.to_requirement_string
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_to_requirement_string_tilde_becomes_floor_bound() -> None:
    """A tilde constraint translates to a PEP 508 '>=' floor bound."""
    spec = PoetryDepSpec(name="requests", version="~1.2")

    assert spec.to_requirement_string() == "requests>=1.2"


@pytest.mark.os_agnostic
def test_to_requirement_string_wildcard_returns_bare_name() -> None:
    """A wildcard '*' constraint carries no version - just the bare package name."""
    spec = PoetryDepSpec(name="requests", version="*")

    assert spec.to_requirement_string() == "requests"


@pytest.mark.os_agnostic
def test_to_requirement_string_empty_version_returns_bare_name() -> None:
    """No version at all also collapses to the bare package name."""
    spec = PoetryDepSpec(name="requests")

    assert spec.to_requirement_string() == "requests"


@pytest.mark.os_agnostic
def test_to_requirement_string_already_pep508_passes_through_verbatim() -> None:
    """A constraint with no caret/tilde prefix is already PEP 508 and is appended as-is."""
    spec = PoetryDepSpec(name="requests", version=">=1.0,<2.0")

    assert spec.to_requirement_string() == "requests>=1.0,<2.0"
