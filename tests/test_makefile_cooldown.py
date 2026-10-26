"""The template's ``_ensure_bmk`` gives bmk's tool env bmk's own supply-chain cooldown.

The cooldown lives in ``.bmk-cooldown.mk`` beside the Makefile (``bmk install`` deploys both),
never in the Makefile itself: it sets ``BMK_COOLDOWN`` to uv flags. What uv does shaped the recipe
(measured, uv 0.13.0):

* ``uv tool upgrade`` stores no option given on its command line, so the upgrade alone cannot
  apply a cooldown that changed.
* ``uv tool install "bmk>=MIN" <flags>`` over an existing install changes no package and REPLACES
  the receipt's options; a plain upgrade afterwards resolves under them.
* Flags, not ``--config-file``: that option makes uv ignore the user's and the system's uv config.

So the common path refreshes the receipt with the flags, then upgrades. A refresh the cooldown cannot
satisfy (a bmk floor younger than the window) retries without it and says so on stderr, the user's
decided fallback; a refresh that fails outright never reaches the destructive reinstall.

These run the REAL recipe under make. ``uv`` and the tool env's ``python`` are stubs at the process
boundary: the stub uv records each call and answers with scripted exit codes, and the stub python
answers ``bmk_selfcheck`` and passes ``bmk_toollock ... -- cmd`` through to the command.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parent.parent / "src" / "bmk" / "makefile" / "Makefile"
COOLDOWN_NAME = ".bmk-cooldown.mk"
_FLAGS = '--exclude-newer "7 days" --exclude-newer-package bmk=false'
# What the stub uv logs for those flags: "$*" joins the words, so the quotes are gone.
_LOGGED = "--exclude-newer 7 days --exclude-newer-package bmk=false"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("make") is None,
    reason="runs the template under GNU make with POSIX shell stubs",
)

_STUB_UV = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_LOG"
case "$*" in
  "tool dir --bin") echo "$STUB_ROOT/bin"; exit 0 ;;
  "tool dir") echo "$STUB_ROOT/tools"; exit 0 ;;
  "tool upgrade"*) exit "${STUB_UPGRADE_RC:-0}" ;;
  *--exclude-newer*) exit "${STUB_COOLDOWN_INSTALL_RC:-0}" ;;
  "tool install"*) exit "${STUB_PLAIN_INSTALL_RC:-0}" ;;
esac
exit 0
"""

_STUB_PYTHON = """#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "bmk_selfcheck" ]; then exit "${STUB_SELFCHECK_RC:-0}"; fi
if [ "$1" = "-m" ] && [ "$2" = "bmk_toollock" ]; then
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
  shift
  exec "$@"
fi
exit 0
"""


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _project(tmp_path: Path, *, cooldown: bool, flags: str = _FLAGS, dirname: str = "project") -> Path:
    project = tmp_path / dirname
    project.mkdir()
    shutil.copy(TEMPLATE, project / "Makefile")
    if cooldown:
        (project / COOLDOWN_NAME).write_text(f"BMK_COOLDOWN := {flags}\n", encoding="utf-8")
    return project


def _ensure_bmk(tmp_path: Path, project: Path, **rcs: int) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    stub_root = tmp_path / "stub"
    _write_exec(stub_root / "path" / "uv", _STUB_UV)
    _write_exec(stub_root / "tools" / "bmk" / "bin" / "python", _STUB_PYTHON)
    log = stub_root / "calls.log"
    env = {
        "PATH": os.pathsep.join([str(stub_root / "path"), "/usr/bin", "/bin"]),
        "HOME": str(tmp_path),
        "STUB_ROOT": str(stub_root),
        "STUB_LOG": str(log),
        **{f"STUB_{name.upper()}": str(rc) for name, rc in rcs.items()},
    }
    proc = subprocess.run(
        ["make", "--no-print-directory", "_ensure_bmk"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    calls = [line for line in log.read_text(encoding="utf-8").splitlines() if not line.startswith("tool dir")]
    return proc, calls


def _min() -> str:
    line = next(line for line in TEMPLATE.read_text(encoding="utf-8").splitlines() if line.startswith("BMK_MIN := "))
    return line.split(":= ", 1)[1].strip()


@pytest.mark.os_posix
def test_the_common_path_refreshes_the_receipt_from_the_cooldown_file_then_upgrades(tmp_path: Path) -> None:
    project = _project(tmp_path, cooldown=True)

    proc, calls = _ensure_bmk(tmp_path, project)

    assert proc.returncode == 0, proc.stderr
    assert calls == [
        f"tool install bmk>={_min()} {_LOGGED}",
        "tool upgrade bmk",
    ]
    assert COOLDOWN_NAME not in proc.stderr, "a met cooldown is silent"


@pytest.mark.os_posix
def test_a_cooldown_the_refresh_cannot_meet_falls_back_to_none_and_says_so(tmp_path: Path) -> None:
    project = _project(tmp_path, cooldown=True)

    proc, calls = _ensure_bmk(tmp_path, project, cooldown_install_rc=1)

    assert proc.returncode == 0, proc.stderr
    assert calls == [
        f"tool install bmk>={_min()} {_LOGGED}",
        f"tool install bmk>={_min()}",
        "tool upgrade bmk",
    ]
    assert COOLDOWN_NAME in proc.stderr, "the fallback must name the file whose cooldown was dropped"


@pytest.mark.os_posix
def test_a_refresh_that_fails_outright_still_upgrades_and_never_reinstalls(tmp_path: Path) -> None:
    project = _project(tmp_path, cooldown=True)

    proc, calls = _ensure_bmk(tmp_path, project, cooldown_install_rc=1, plain_install_rc=1)

    assert proc.returncode == 0, proc.stderr
    assert calls[-1] == "tool upgrade bmk"
    assert not any("--reinstall" in call for call in calls), "a failed refresh must not rebuild the shared env"


@pytest.mark.os_posix
def test_without_a_cooldown_file_the_common_path_only_upgrades(tmp_path: Path) -> None:
    project = _project(tmp_path, cooldown=False)

    proc, calls = _ensure_bmk(tmp_path, project)

    assert proc.returncode == 0, proc.stderr
    assert calls == ["tool upgrade bmk"]


@pytest.mark.os_posix
def test_the_guarded_repair_installs_under_the_cooldown(tmp_path: Path) -> None:
    project = _project(tmp_path, cooldown=True)

    proc, calls = _ensure_bmk(tmp_path, project, selfcheck_rc=1)

    assert proc.returncode == 0, proc.stderr
    assert calls == [f"tool install --reinstall --force bmk>={_min()} {_LOGGED}"]


@pytest.mark.os_posix
def test_the_last_resort_repair_drops_the_cooldown_and_says_so(tmp_path: Path) -> None:
    project = _project(tmp_path, cooldown=True)

    proc, calls = _ensure_bmk(tmp_path, project, selfcheck_rc=1, cooldown_install_rc=1)

    assert proc.returncode == 0, proc.stderr
    assert calls == [
        f"tool install --reinstall --force bmk>={_min()} {_LOGGED}",
        f"tool install --reinstall --force bmk>={_min()}",
    ]
    assert COOLDOWN_NAME in proc.stderr


@pytest.mark.os_posix
def test_a_failed_upgrade_still_falls_through_to_the_repair(tmp_path: Path) -> None:
    project = _project(tmp_path, cooldown=False)

    proc, calls = _ensure_bmk(tmp_path, project, upgrade_rc=1)

    assert proc.returncode == 0, proc.stderr
    assert calls == ["tool upgrade bmk", f"tool install --reinstall --force bmk>={_min()}"]


@pytest.mark.os_posix
def test_a_project_path_with_a_space_still_gets_the_cooldown(tmp_path: Path) -> None:
    project = _project(tmp_path, cooldown=True, dirname="my project")

    proc, calls = _ensure_bmk(tmp_path, project)

    assert proc.returncode == 0, proc.stderr
    assert calls[0] == f"tool install bmk>={_min()} {_LOGGED}"


@pytest.mark.os_posix
def test_a_cooldown_file_that_sets_none_behaves_like_no_file(tmp_path: Path) -> None:
    project = _project(tmp_path, cooldown=True, flags="")

    proc, calls = _ensure_bmk(tmp_path, project)

    assert proc.returncode == 0, proc.stderr
    assert calls == ["tool upgrade bmk"]


# ``help`` greps $(MAKEFILE_LIST) for "target: ## text" lines. With one file grep prints bare
# lines; with two (the template ``-include``s the cooldown) it prefixes each with "Makefile:",
# and awk's ":.*?## " separator then reads "Makefile" as every target's name.
DEV_MAKEFILE = TEMPLATE.parents[3] / "Makefile"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _help_lines(project: Path, *extra: str) -> list[str]:
    files = [arg for name in ("Makefile", *extra) for arg in ("-f", name)]
    proc = subprocess.run(
        ["make", "--no-print-directory", *files, "help"],
        cwd=project,
        env={"PATH": os.pathsep.join(["/usr/bin", "/bin"]), "HOME": str(project)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return [_ANSI.sub("", line).split()[0] for line in proc.stdout.splitlines() if line.strip()]


@pytest.mark.os_posix
@pytest.mark.parametrize("cooldown", [True, False], ids=["with-cooldown", "without-cooldown"])
def test_help_names_each_target_whether_or_not_the_cooldown_file_is_included(tmp_path: Path, cooldown: bool) -> None:
    project = _project(tmp_path, cooldown=cooldown)

    names = _help_lines(project)

    assert "test" in names
    assert "Makefile" not in names


@pytest.mark.os_posix
def test_the_dev_makefile_help_names_each_target_beside_a_second_makefile(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(DEV_MAKEFILE, project / "Makefile")
    (project / "extra.mk").write_text("EXTRA := 1\n", encoding="utf-8")

    names = _help_lines(project, "extra.mk")

    assert "test" in names
    assert "Makefile" not in names
