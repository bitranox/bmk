"""Behaviour tests for makescripts._run: dependency extraction, local discovery, and CLI invocation."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bmk.makescripts._run import _extract_dependency_names, _find_local_dependencies, run_cli
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


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_completed(returncode: int) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], returncode=returncode)


# ---------------------------------------------------------------------------
# run_cli — successful invocation
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_cli_returns_zero_on_success(tmp_path: Path) -> None:
    """Returns 0 when uvx invocation succeeds."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    config = _config_with_dependencies(["requests>=2.0"])

    with (
        patch("bmk.makescripts._run.load_pyproject_config", return_value=config),
        patch("bmk.makescripts._run.subprocess.run", return_value=_make_completed(0)),
    ):
        result = run_cli(project_dir=project_dir, args=["--version"])

    assert result == 0


@pytest.mark.os_agnostic
def test_run_cli_propagates_nonzero_exit_code(tmp_path: Path) -> None:
    """Propagates non-zero exit code from uvx."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    config = _config_with_dependencies([])

    with (
        patch("bmk.makescripts._run.load_pyproject_config", return_value=config),
        patch("bmk.makescripts._run.subprocess.run", return_value=_make_completed(42)),
    ):
        result = run_cli(project_dir=project_dir, args=["bad-command"])

    assert result == 42


# ---------------------------------------------------------------------------
# run_cli — empty project name
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_cli_returns_one_when_project_name_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 1 and prints error when project name is empty."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    config = PyprojectConfig(project=ProjectSection(name="", dependencies=()))

    with patch("bmk.makescripts._run.load_pyproject_config", return_value=config):
        result = run_cli(project_dir=project_dir, args=["--help"])

    assert result == 1
    assert "Could not read project name" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# run_cli — default args
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_cli_defaults_to_help_when_args_empty(tmp_path: Path) -> None:
    """Defaults to --help when args list is empty."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    config = _config_with_dependencies([])

    with (
        patch("bmk.makescripts._run.load_pyproject_config", return_value=config),
        patch("bmk.makescripts._run.subprocess.run", return_value=_make_completed(0)) as mock_run,
    ):
        run_cli(project_dir=project_dir, args=[])

    cmd = mock_run.call_args[0][0]
    assert cmd[-1] == "--help"


# ---------------------------------------------------------------------------
# run_cli — command construction
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_cli_builds_uvx_command_with_project_dir(tmp_path: Path) -> None:
    """Command includes uvx --from <project_dir> --no-cache."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    config = _config_with_dependencies([])

    with (
        patch("bmk.makescripts._run.load_pyproject_config", return_value=config),
        patch("bmk.makescripts._run.subprocess.run", return_value=_make_completed(0)) as mock_run,
    ):
        run_cli(project_dir=project_dir, args=["info"])

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "uvx"
    assert "--from" in cmd
    assert str(project_dir) in cmd
    assert "--no-cache" in cmd


@pytest.mark.os_agnostic
def test_run_cli_appends_project_name_and_args(tmp_path: Path) -> None:
    """Command ends with project name followed by forwarded arguments."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    config = _config_with_dependencies([])

    with (
        patch("bmk.makescripts._run.load_pyproject_config", return_value=config),
        patch("bmk.makescripts._run.subprocess.run", return_value=_make_completed(0)) as mock_run,
    ):
        run_cli(project_dir=project_dir, args=["--verbose", "test"])

    cmd = mock_run.call_args[0][0]
    assert cmd[-3] == "test-project"
    assert cmd[-2] == "--verbose"
    assert cmd[-1] == "test"


@pytest.mark.os_agnostic
def test_run_cli_includes_local_deps_with_flags(tmp_path: Path) -> None:
    """Local dependencies are passed as --with flags in the command."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    sibling = tmp_path / "lib_alpha"
    sibling.mkdir()
    (sibling / "pyproject.toml").write_text("[project]\nname = 'lib-alpha'\n")
    config = _config_with_dependencies(["lib-alpha>=1.0"])

    with (
        patch("bmk.makescripts._run.load_pyproject_config", return_value=config),
        patch("bmk.makescripts._run.subprocess.run", return_value=_make_completed(0)) as mock_run,
    ):
        run_cli(project_dir=project_dir, args=["info"])

    cmd = mock_run.call_args[0][0]
    with_idx = cmd.index("--with")
    assert cmd[with_idx + 1] == str(sibling)


@pytest.mark.os_agnostic
def test_run_cli_prints_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Prints the command being executed to stdout."""
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    config = _config_with_dependencies([])

    with (
        patch("bmk.makescripts._run.load_pyproject_config", return_value=config),
        patch("bmk.makescripts._run.subprocess.run", return_value=_make_completed(0)),
    ):
        run_cli(project_dir=project_dir, args=["info"])

    captured = capsys.readouterr().out
    assert "[run]" in captured
    assert "uvx" in captured
