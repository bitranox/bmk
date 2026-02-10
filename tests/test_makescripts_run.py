"""Behaviour tests for makescripts._run: dependency extraction and local discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from bmk.makescripts._run import _extract_dependency_names, _find_local_dependencies
from bmk.makescripts._toml_config import ProjectSection, PyprojectConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_with_dependencies(deps: list[str]) -> PyprojectConfig:
    """Build a PyprojectConfig with the given project dependencies."""
    project = ProjectSection(name="test-project", dependencies=tuple(deps))
    return PyprojectConfig(project=project)


# ---------------------------------------------------------------------------
# _extract_dependency_names — normalisation
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_extract_dependency_names_normalises_hyphens() -> None:
    """Hyphens in package names are replaced by underscores."""
    config = _config_with_dependencies(["rich-click", "lib-log-rich"])

    result = _extract_dependency_names(config)

    assert result == ["rich_click", "lib_log_rich"]


@pytest.mark.os_agnostic
def test_extract_dependency_names_strips_version_specifiers() -> None:
    """Version specifiers are removed, only package name is returned."""
    config = _config_with_dependencies(["rich-click>=1.9.7", "pydantic>=2.12.5"])

    result = _extract_dependency_names(config)

    assert result == ["rich_click", "pydantic"]


@pytest.mark.os_agnostic
def test_extract_dependency_names_strips_extras() -> None:
    """Extras brackets are stripped, only the base package name is returned."""
    config = _config_with_dependencies(["pyright[nodejs]>=1.1.408"])

    result = _extract_dependency_names(config)

    assert result == ["pyright"]


@pytest.mark.os_agnostic
def test_extract_dependency_names_handles_empty_dependencies() -> None:
    """Returns empty list when project has no dependencies."""
    config = _config_with_dependencies([])

    result = _extract_dependency_names(config)

    assert result == []


@pytest.mark.os_agnostic
def test_extract_dependency_names_handles_exact_version_pin() -> None:
    """Exact version pins (==) are stripped correctly."""
    config = _config_with_dependencies(["orjson==3.11.7"])

    result = _extract_dependency_names(config)

    assert result == ["orjson"]


@pytest.mark.os_agnostic
def test_extract_dependency_names_handles_tilde_version() -> None:
    """Tilde version constraints (~=) are stripped correctly."""
    config = _config_with_dependencies(["requests~=2.31.0"])

    result = _extract_dependency_names(config)

    assert result == ["requests"]


@pytest.mark.os_agnostic
def test_extract_dependency_names_preserves_underscores() -> None:
    """Underscore names pass through unchanged."""
    config = _config_with_dependencies(["lib_layered_config>=5.0.0"])

    result = _extract_dependency_names(config)

    assert result == ["lib_layered_config"]


@pytest.mark.os_agnostic
def test_extract_dependency_names_handles_whitespace() -> None:
    """Leading and trailing whitespace in dependency strings is ignored."""
    config = _config_with_dependencies(["  rich-click>=1.0  "])

    result = _extract_dependency_names(config)

    assert result == ["rich_click"]


@pytest.mark.os_agnostic
def test_extract_dependency_names_handles_bare_name() -> None:
    """Bare package names without version specifiers are returned as-is (normalised)."""
    config = _config_with_dependencies(["requests"])

    result = _extract_dependency_names(config)

    assert result == ["requests"]


# ---------------------------------------------------------------------------
# _find_local_dependencies — no matches
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_find_local_dependencies_returns_empty_when_no_siblings(tmp_path: Path) -> None:
    """Returns empty list when no sibling directories match dependencies."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    config = _config_with_dependencies(["nonexistent-package"])

    result = _find_local_dependencies(project_dir, config)

    assert result == []


@pytest.mark.os_agnostic
def test_find_local_dependencies_ignores_sibling_without_pyproject(tmp_path: Path) -> None:
    """Sibling directory matching a dependency name but lacking pyproject.toml is skipped."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    sibling = tmp_path / "some_lib"
    sibling.mkdir()
    config = _config_with_dependencies(["some-lib"])

    result = _find_local_dependencies(project_dir, config)

    assert result == []


# ---------------------------------------------------------------------------
# _find_local_dependencies — matching siblings
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_find_local_dependencies_finds_underscore_sibling(tmp_path: Path) -> None:
    """Finds sibling directory using the underscore variant of the dependency name."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    sibling = tmp_path / "rich_click"
    sibling.mkdir()
    (sibling / "pyproject.toml").write_text("[project]\nname = 'rich-click'\n")
    config = _config_with_dependencies(["rich-click>=1.0"])

    result = _find_local_dependencies(project_dir, config)

    assert len(result) == 1
    assert result[0][0] == "rich-click"
    assert result[0][1] == str(sibling)


@pytest.mark.os_agnostic
def test_find_local_dependencies_finds_hyphen_sibling(tmp_path: Path) -> None:
    """Finds sibling directory using the hyphen variant of the dependency name."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    sibling = tmp_path / "lib-log-rich"
    sibling.mkdir()
    (sibling / "pyproject.toml").write_text("[project]\nname = 'lib-log-rich'\n")
    config = _config_with_dependencies(["lib-log-rich>=6.0"])

    result = _find_local_dependencies(project_dir, config)

    assert len(result) == 1
    assert result[0][0] == "lib-log-rich"
    assert result[0][1] == str(sibling)


@pytest.mark.os_agnostic
def test_find_local_dependencies_prefers_underscore_over_hyphen(tmp_path: Path) -> None:
    """When both underscore and hyphen directories exist, underscore is preferred."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    underscore_sibling = tmp_path / "my_lib"
    underscore_sibling.mkdir()
    (underscore_sibling / "pyproject.toml").write_text("[project]\nname = 'my-lib'\n")
    hyphen_sibling = tmp_path / "my-lib"
    hyphen_sibling.mkdir()
    (hyphen_sibling / "pyproject.toml").write_text("[project]\nname = 'my-lib'\n")
    config = _config_with_dependencies(["my-lib>=1.0"])

    result = _find_local_dependencies(project_dir, config)

    assert len(result) == 1
    assert result[0][0] == "my-lib"
    assert result[0][1] == str(underscore_sibling)


@pytest.mark.os_agnostic
def test_find_local_dependencies_returns_hyphen_package_name(tmp_path: Path) -> None:
    """Package names in the result use hyphens (PyPI convention)."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    sibling = tmp_path / "lib_layered_config"
    sibling.mkdir()
    (sibling / "pyproject.toml").write_text("[project]\nname = 'lib-layered-config'\n")
    config = _config_with_dependencies(["lib_layered_config>=5.0"])

    result = _find_local_dependencies(project_dir, config)

    assert len(result) == 1
    assert result[0][0] == "lib-layered-config"


@pytest.mark.os_agnostic
def test_find_local_dependencies_discovers_multiple_siblings(tmp_path: Path) -> None:
    """Multiple dependencies with matching siblings are all discovered."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()

    lib_a = tmp_path / "lib_alpha"
    lib_a.mkdir()
    (lib_a / "pyproject.toml").write_text("[project]\nname = 'lib-alpha'\n")

    lib_b = tmp_path / "lib-beta"
    lib_b.mkdir()
    (lib_b / "pyproject.toml").write_text("[project]\nname = 'lib-beta'\n")

    config = _config_with_dependencies(["lib-alpha>=1.0", "lib-beta>=2.0", "unrelated-pkg"])

    result = _find_local_dependencies(project_dir, config)

    found_names = [name for name, _path in result]
    assert "lib-alpha" in found_names
    assert "lib-beta" in found_names
    assert len(result) == 2


@pytest.mark.os_agnostic
def test_find_local_dependencies_with_empty_dependencies(tmp_path: Path) -> None:
    """Returns empty list when project has no dependencies at all."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    config = _config_with_dependencies([])

    result = _find_local_dependencies(project_dir, config)

    assert result == []
