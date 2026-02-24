"""Pre-command Makefile version check: prompt when local Makefile is outdated."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.commands.install_cmd import _extract_version

# =============================================================================
# _extract_version unit tests
# =============================================================================


@pytest.mark.os_agnostic
def test_extract_version_parses_sentinel() -> None:
    """Extracts version string from a valid sentinel line."""
    assert _extract_version("# BMK MAKEFILE 1.0.0") == "1.0.0"


@pytest.mark.os_agnostic
def test_extract_version_parses_multipart_version() -> None:
    """Extracts version with extra whitespace."""
    assert _extract_version("# BMK MAKEFILE 2.3.4") == "2.3.4"


@pytest.mark.os_agnostic
def test_extract_version_returns_none_for_custom() -> None:
    """Returns None for a non-sentinel line."""
    assert _extract_version("# My custom Makefile") is None


@pytest.mark.os_agnostic
def test_extract_version_returns_none_for_sentinel_without_version() -> None:
    """Returns None when sentinel exists but no version follows."""
    assert _extract_version("# BMK MAKEFILE") is None


# =============================================================================
# Pre-command check: skip scenarios
# =============================================================================


@pytest.mark.os_agnostic
def test_no_makefile_skips_check(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Makefile in cwd — subcommand runs normally without prompt."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

    result: Result = cli_runner.invoke(cli_mod.cli, ["info"], obj=production_factory)

    assert result.exit_code == 0


@pytest.mark.os_agnostic
def test_custom_makefile_skips_check(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Custom Makefile (no sentinel) — subcommand runs normally."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    (tmp_path / "Makefile").write_text("# My custom Makefile\nall:\n", encoding="utf-8")

    result: Result = cli_runner.invoke(cli_mod.cli, ["info"], obj=production_factory)

    assert result.exit_code == 0
    assert "outdated" not in result.output


@pytest.mark.os_agnostic
def test_up_to_date_skips_check(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local version matches bundled — subcommand runs normally."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    from bmk.adapters.cli.commands.install_cmd import _BUNDLED_MAKEFILE

    bundled_first = _BUNDLED_MAKEFILE.read_text(encoding="utf-8").split("\n", maxsplit=1)[0]
    (tmp_path / "Makefile").write_text(f"{bundled_first}\nlocal content\n", encoding="utf-8")

    result: Result = cli_runner.invoke(cli_mod.cli, ["info"], obj=production_factory)

    assert result.exit_code == 0
    assert "outdated" not in result.output


# =============================================================================
# Pre-command check: outdated scenarios
# =============================================================================


@pytest.mark.os_agnostic
def test_outdated_user_accepts(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outdated Makefile + user accepts → file updated, subcommand continues."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "text")
    (tmp_path / "Makefile").write_text("# BMK MAKEFILE 0.0.1\nold\n", encoding="utf-8")

    result: Result = cli_runner.invoke(
        cli_mod.cli,
        ["info"],
        obj=production_factory,
        input="y\n",
    )

    assert result.exit_code == 0
    assert "Makefile updated to" in result.output
    updated = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert updated.startswith("# BMK MAKEFILE")
    assert "old" not in updated


@pytest.mark.os_agnostic
def test_outdated_user_declines(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outdated Makefile + user declines → original preserved, subcommand runs."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "text")
    original = "# BMK MAKEFILE 0.0.1\nold\n"
    (tmp_path / "Makefile").write_text(original, encoding="utf-8")

    result: Result = cli_runner.invoke(
        cli_mod.cli,
        ["info"],
        obj=production_factory,
        input="n\n",
    )

    assert result.exit_code == 0
    assert (tmp_path / "Makefile").read_text(encoding="utf-8") == original


@pytest.mark.os_agnostic
def test_outdated_auto_accepts_in_json_mode(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outdated Makefile in JSON mode → auto-updated without prompt."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "json")
    (tmp_path / "Makefile").write_text("# BMK MAKEFILE 0.0.1\nold\n", encoding="utf-8")

    result: Result = cli_runner.invoke(
        cli_mod.cli,
        ["info"],
        obj=production_factory,
    )

    assert result.exit_code == 0
    updated = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert updated.startswith("# BMK MAKEFILE")
    assert "old" not in updated


# =============================================================================
# Install command bypasses the check
# =============================================================================


@pytest.mark.os_agnostic
def test_install_command_skips_check(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'bmk install' never triggers the version check prompt."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    (tmp_path / "Makefile").write_text("# BMK MAKEFILE 0.0.1\nold\n", encoding="utf-8")

    result: Result = cli_runner.invoke(cli_mod.cli, ["install"], obj=production_factory)

    assert result.exit_code == 0
    assert "outdated" not in result.output
    assert "Updating existing bmk Makefile" in result.output
