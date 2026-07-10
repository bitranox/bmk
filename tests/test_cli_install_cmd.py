"""CLI install command stories: Makefile deployment and sentinel detection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.exit_codes import ExitCode

# =============================================================================
# Command existence tests
# =============================================================================


@pytest.mark.os_agnostic
def test_cli_install_command_exists(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
) -> None:
    """Verify 'install' command is registered."""
    result: Result = cli_runner.invoke(cli_mod.cli, ["install", "--help"], obj=production_factory)

    assert result.exit_code == 0
    assert "Install or update" in result.output


# =============================================================================
# Fresh install tests
# =============================================================================


@pytest.mark.os_agnostic
def test_cli_install_fresh_creates_makefile(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Makefile is created when none exists."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    result: Result = cli_runner.invoke(cli_mod.cli, ["install"], obj=production_factory)

    assert result.exit_code == 0
    assert "Installing bmk Makefile" in result.output
    assert (tmp_path / "Makefile").exists()


@pytest.mark.os_agnostic
def test_cli_install_fresh_copies_bundled_content(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installed Makefile starts with the bmk sentinel."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    cli_runner.invoke(cli_mod.cli, ["install"], obj=production_factory)

    content = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert content.startswith("# BMK MAKEFILE")


# =============================================================================
# Overwrite managed Makefile tests
# =============================================================================


@pytest.mark.os_agnostic
def test_cli_install_overwrites_managed_makefile(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Managed Makefile (with sentinel) is overwritten."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    makefile = tmp_path / "Makefile"
    makefile.write_text("# BMK MAKEFILE V0.9\nold content\n", encoding="utf-8")

    result: Result = cli_runner.invoke(cli_mod.cli, ["install"], obj=production_factory)

    assert result.exit_code == 0
    assert "Updating existing bmk Makefile" in result.output
    content = makefile.read_text(encoding="utf-8")
    assert "old content" not in content
    assert content.startswith("# BMK MAKEFILE")


# =============================================================================
# Skip custom Makefile tests
# =============================================================================


@pytest.mark.os_agnostic
def test_cli_install_skips_custom_makefile(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Custom Makefile (without sentinel) is not overwritten."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    makefile = tmp_path / "Makefile"
    original = "# My custom Makefile\nall:\n\techo hello\n"
    makefile.write_text(original, encoding="utf-8")

    result: Result = cli_runner.invoke(cli_mod.cli, ["install"], obj=production_factory)

    assert result.exit_code == ExitCode.GENERAL_ERROR
    assert "not managed by bmk" in result.output
    assert makefile.read_text(encoding="utf-8") == original


# =============================================================================
# Bundled Makefile not found tests
# =============================================================================


@pytest.mark.os_agnostic
def test_cli_install_errors_when_bundled_missing(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graceful error when bundled Makefile is missing."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setattr(
        "bmk.adapters.cli.commands.install_cmd._BUNDLED_MAKEFILE",
        tmp_path / "nonexistent" / "Makefile",
    )

    result: Result = cli_runner.invoke(cli_mod.cli, ["install"], obj=production_factory)

    assert result.exit_code == ExitCode.FILE_NOT_FOUND
    assert "Bundled Makefile not found" in result.output


# =============================================================================
# Tool-venv provisioning
# =============================================================================


@pytest.mark.os_agnostic
def test_bundled_makefile_provisions_dev_extra() -> None:
    """The bundled Makefile installs bmk's tool venv WITH the project's [dev] extra.

    Test-only deps declared in [dev] (test-import libraries, fakes, property-test
    helpers) must land in the venv bmk runs pytest in, otherwise `make test`
    diverges from CI. The base-deps install is kept as a fallback for projects
    that have no [dev] extra.
    """
    import bmk

    bundled_makefile = Path(bmk.__file__).parent / "makefile" / "Makefile"
    content = bundled_makefile.read_text(encoding="utf-8")

    assert '--with ".[dev]"' in content
    assert "--with ." in content  # base-deps fallback preserved
