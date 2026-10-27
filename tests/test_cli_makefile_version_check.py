"""Pre-command Makefile version check: prompt when local Makefile is outdated."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from bmk import __init__conf__
from bmk.adapters import cli as cli_mod
from bmk.adapters.cli.commands.install_cmd import extract_version

if TYPE_CHECKING:
    from collections.abc import Callable

    from click.testing import CliRunner, Result

# Body of the stale Makefile these tests plant, and the string they assert is gone
# once it has been regenerated. It must be a marker that CANNOT occur in a real
# template. A short English word will not do: the template is mostly prose, so
# something like "old" also matches "threshold" or any comment using the word, and
# the assertion then fails for a reason unrelated to the behaviour under test.
_STALE_MARKER = "STALE-MAKEFILE-BODY-DO-NOT-KEEP"

_STALE_MAKEFILE = "# BMK MAKEFILE 0.0.1\n" + _STALE_MARKER + "\n"

# Bound for one real `bmk info` in a subprocess. It is the test's own clock, not the
# subject's: a run that waits on stdin for an answer never ends by itself, so without it a
# regression would hang the suite instead of failing with a cause.
_RUN_DEADLINE_SECONDS = 60.0

_PREFIX = __init__conf__.LAYEREDCONF_SLUG.upper().replace("-", "_")
_HOMES = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA", "LOCALAPPDATA")
_APP_ROOTS = ("LIB_LAYERED_CONFIG_ETC", "LIB_LAYERED_CONFIG_MAC_APP_ROOT", "LIB_LAYERED_CONFIG_PROGRAMDATA")


def _isolated_env(home: Path, **extra: str) -> dict[str, str]:
    """This process's environment minus bmk, logging and config variables; homes and app roots under `home`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith((_PREFIX, "BMK_", "LOG_", "LIB_LAYERED_CONFIG"))}
    env.update(dict.fromkeys(_HOMES, str(home)))
    # The app layer has its own root per OS; point all three at `home` so a config deployed on
    # this host cannot reach the child.
    env.update(dict.fromkeys(_APP_ROOTS, str(home)))
    env.update(extra)
    return env


def _run_bmk_info(project: Path, *, stdin: int) -> tuple[int, str, str]:
    """Run the real `bmk info` in text mode with `stdin`; return exit code, stdout, stderr.

    Fails the test, naming the cause, when the run outlives `_RUN_DEADLINE_SECONDS`.
    """
    out, err = project / "stdout.txt", project / "stderr.txt"
    with out.open("wb") as out_file, err.open("wb") as err_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "bmk", "info"],
            cwd=project,
            env=_isolated_env(project, BMK_OUTPUT_FORMAT="text"),
            stdin=stdin,
            stdout=out_file,
            stderr=err_file,
        )
        try:
            returncode = proc.wait(timeout=_RUN_DEADLINE_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail(f"bmk was still running after {_RUN_DEADLINE_SECONDS}s: it waited on stdin for an answer")
    return returncode, out.read_text(encoding="utf-8"), err.read_text(encoding="utf-8")


# =============================================================================
# extract_version unit tests
# =============================================================================


@pytest.mark.os_agnostic
def test_extract_version_parses_sentinel() -> None:
    """Extracts version string from a valid sentinel line."""
    assert extract_version("# BMK MAKEFILE 1.0.0") == "1.0.0"


@pytest.mark.os_agnostic
def test_extract_version_parses_multipart_version() -> None:
    """Extracts version with extra whitespace."""
    assert extract_version("# BMK MAKEFILE 2.3.4") == "2.3.4"


@pytest.mark.os_agnostic
def test_extract_version_returns_none_for_custom() -> None:
    """Returns None for a non-sentinel line."""
    assert extract_version("# My custom Makefile") is None


@pytest.mark.os_agnostic
def test_extract_version_returns_none_for_sentinel_without_version() -> None:
    """Returns None when sentinel exists but no version follows."""
    assert extract_version("# BMK MAKEFILE") is None


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
    """No Makefile in cwd - subcommand runs normally without prompt."""
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
    """Custom Makefile (no sentinel) - subcommand runs normally."""
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
    """Local version matches bundled - subcommand runs normally."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    from bmk.adapters.cli.commands.install_cmd import BUNDLED_MAKEFILE

    bundled_first = BUNDLED_MAKEFILE.read_text(encoding="utf-8").split("\n", maxsplit=1)[0]
    (tmp_path / "Makefile").write_text(f"{bundled_first}\nlocal content\n", encoding="utf-8")

    result: Result = cli_runner.invoke(cli_mod.cli, ["info"], obj=production_factory)

    assert result.exit_code == 0
    assert "outdated" not in result.output


# =============================================================================
# Pre-command check: outdated scenarios
# =============================================================================


@pytest.mark.os_agnostic
def test_outdated_text_mode_does_not_wait_on_an_open_stdin_that_is_not_a_terminal(tmp_path: Path) -> None:
    """An agent's pipe stays open and is never written: the check must not read it.

    `/dev/null` would not show this - it answers end-of-file at once, which the prompt reads as
    a refusal. Only an open pipe with no writer blocks, which is what an unattended caller hands
    a child process.
    """
    (tmp_path / "Makefile").write_text(_STALE_MAKEFILE, encoding="utf-8")
    read_end, write_end = os.pipe()
    try:
        returncode, _stdout, stderr = _run_bmk_info(tmp_path, stdin=read_end)
    finally:
        os.close(read_end)
        os.close(write_end)

    assert returncode == 0
    assert (tmp_path / "Makefile").read_text(encoding="utf-8") == _STALE_MAKEFILE
    assert "bmk install" in stderr


@pytest.mark.os_agnostic
def test_outdated_text_mode_declines_when_stdin_is_not_a_terminal(
    cli_runner: CliRunner,
    production_factory: Callable[[], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Text piped in is not a person answering: the Makefile is kept and stderr says how to update."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "text")
    (tmp_path / "Makefile").write_text(_STALE_MAKEFILE, encoding="utf-8")

    result: Result = cli_runner.invoke(cli_mod.cli, ["info"], obj=production_factory, input="y\n")

    assert result.exit_code == 0
    assert (tmp_path / "Makefile").read_text(encoding="utf-8") == _STALE_MAKEFILE
    assert "Update?" not in result.output
    assert "bmk install" in result.stderr


def _answer_on_a_terminal(project: Path, answer: bytes) -> tuple[int, str]:
    """Run `bmk info` with a real terminal as stdin, type `answer`; return exit code and stdout."""
    # The os_posix marker skips the CALLERS at run time, but pyright still checks this body on
    # Windows, where typeshed has no pty.openpty; this branch makes the rest unreachable there.
    if sys.platform == "win32":
        pytest.skip("needs a POSIX pseudo-terminal")
    # Imported here, not at module level: pty is POSIX-only and would break collection on Windows.
    import pty

    controller, terminal = pty.openpty()
    try:
        # The terminal buffers the typed line until the prompt reads it.
        os.write(controller, answer)
        returncode, stdout, _stderr = _run_bmk_info(project, stdin=terminal)
    finally:
        os.close(terminal)
        os.close(controller)
    return returncode, stdout


@pytest.mark.os_posix
def test_outdated_user_accepts_on_a_terminal(tmp_path: Path) -> None:
    """Outdated Makefile + a person answering y on a terminal -> file updated, command continues."""
    (tmp_path / "Makefile").write_text(_STALE_MAKEFILE, encoding="utf-8")

    returncode, stdout = _answer_on_a_terminal(tmp_path, b"y\n")

    assert returncode == 0
    assert "Makefile updated to" in stdout
    updated = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert updated.startswith("# BMK MAKEFILE")
    assert _STALE_MARKER not in updated


@pytest.mark.os_posix
def test_outdated_user_declines_on_a_terminal(tmp_path: Path) -> None:
    """Outdated Makefile + a person answering n on a terminal -> original kept, command runs."""
    (tmp_path / "Makefile").write_text(_STALE_MAKEFILE, encoding="utf-8")

    returncode, stdout = _answer_on_a_terminal(tmp_path, b"n\n")

    assert returncode == 0
    assert "Update?" in stdout
    assert (tmp_path / "Makefile").read_text(encoding="utf-8") == _STALE_MAKEFILE


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
    (tmp_path / "Makefile").write_text("# BMK MAKEFILE 0.0.1\n" + _STALE_MARKER + "\n", encoding="utf-8")

    result: Result = cli_runner.invoke(
        cli_mod.cli,
        ["info"],
        obj=production_factory,
    )

    assert result.exit_code == 0
    updated = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert updated.startswith("# BMK MAKEFILE")
    assert _STALE_MARKER not in updated


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
    (tmp_path / "Makefile").write_text("# BMK MAKEFILE 0.0.1\n" + _STALE_MARKER + "\n", encoding="utf-8")

    result: Result = cli_runner.invoke(cli_mod.cli, ["install"], obj=production_factory)

    assert result.exit_code == 0
    assert "outdated" not in result.output
    assert "Updating existing bmk Makefile" in result.output


# =============================================================================
# release never rewrites the Makefile it is about to check is committed
# =============================================================================


@pytest.mark.os_agnostic
@pytest.mark.parametrize("command", ["release", "rel", "r"])
def test_release_leaves_an_outdated_makefile_alone_in_json_mode(
    cli_pipeline_probe: Callable[..., Result], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    # release refuses a dirty working tree; a Makefile it rewrote itself would make every release
    # right after a new bmk version refuse, naming a change the same command made.
    monkeypatch.setenv("BMK_OUTPUT_FORMAT", "json")
    (tmp_path / "Makefile").write_text(_STALE_MAKEFILE, encoding="utf-8")

    result = cli_pipeline_probe([command], prefix="rel")

    assert result.exit_code == 0, result.output
    assert (tmp_path / "PROBE").read_text(encoding="utf-8") == "ran"
    assert (tmp_path / "Makefile").read_text(encoding="utf-8") == _STALE_MAKEFILE
