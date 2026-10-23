"""A stub ``uv`` executable first on PATH: the external edge of venv provisioning.

``stagerunner/venv.py`` calls ``uv`` by bare name through PATH, so a script named ``uv`` placed
first on PATH receives every provisioning call through the REAL module and the REAL subprocess
plumbing (``_run``, ``_run_keeping_stderr``, ``_run_capture``). Tests then assert on what the stub
recorded and on real stdout/stderr, instead of patching bmk's own runners: a patched runner
proves only that bmk called its own function, never what reached the process boundary (argv, cwd,
environment), and it silently stops covering a runner a refactor routes around it.

The stub is a POSIX shell script, so the ``stub_uv`` fixture (``tests/conftest.py``) skips on
Windows. Imported by bare module name: ``tests/`` has no ``__init__.py``, so pytest's default
import mode puts this directory on ``sys.path`` (``from tests.uv_stub import`` would fail under a
bare ``pytest`` run).
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ESC",
    "LOCK_MARKER",
    "PIP_MARKER",
    "SYNC_COLOURED",
    "SYNC_FILLER_LINES",
    "SYNC_LAST_FILLER",
    "SYNC_MARKER",
    "VENV_MARKER",
    "StubUv",
    "UvCall",
]

SYNC_MARKER = "stub-uv-sync-error-7f3a"
# What a failing `uv venv`, `uv lock` and `uv pip install` print on stderr, so a test can tell uv's
# own reason from bmk's header. The pip marker is followed by the install target that failed.
VENV_MARKER = "stub-uv-venv-error-2c9e"
LOCK_MARKER = "stub-uv-lock-error-81d4"
PIP_MARKER = "stub-uv-pip-error-e6b0"
# uv puts its verdict FIRST and the detail after it (measured, uv 0.13.0: a failing build printed
# 26 lines with `error: Failed to build` on line 6), so the stub follows its error with more lines
# than any tail a reader might be tempted to cap the report at.
SYNC_FILLER_LINES = 25
SYNC_LAST_FILLER = f"filler-{SYNC_FILLER_LINES}"
SYNC_COLOURED = "stub-uv-coloured-line-5b1d"
# Built with chr() so no escape sequence has to survive the source text: FORCE_COLOR makes uv colour
# its error lines even into a pipe.
ESC = chr(0x1B)

# Separates one recorded call from the next in the log. No argv word bmk builds can equal it.
_CALL_SEPARATOR = "@@stub-uv-call"
_UNSET = "@@unset"
# The exit code the stub answers with when bmk aims a mutating command outside the test's tmp_path.
_REFUSED_OUTSIDE = 97


@dataclass(frozen=True)
class UvCall:
    """One invocation the stub received.

    Attributes:
        argv: The full command line, ``"uv"`` first, so it compares against the lists bmk builds.
        cwd: The physical working directory uv ran in.
        project_environment: ``UV_PROJECT_ENVIRONMENT`` as uv saw it, or None when unset.
        virtual_env_set: Whether ``VIRTUAL_ENV`` reached uv at all.
    """

    argv: tuple[str, ...]
    cwd: Path
    project_environment: str | None
    virtual_env_set: bool


class StubUv:
    """Writes the stub ``uv`` under ``root`` and reads back what it recorded.

    Every subcommand succeeds unless configured otherwise via :meth:`install`, which rewrites the
    script and may be called again mid-test.
    """

    def __init__(self, root: Path, *, allowed: Path) -> None:
        """Place the stub at ``root/bin/uv``; ``allowed`` bounds every path it may create or remove."""
        self.root = root
        self.bin_dir = root / "bin"
        self.log = root / "calls.log"
        self._allowed = allowed

    def install(
        self,
        *,
        venv_rc: int = 0,
        venv_creates: bool = True,
        venv_reports: str | None = None,
        python_rc: int = 0,
        lock_rc: int = 0,
        lock_upgrade_rc: int = 0,
        lock_aftermath: str = ":",
        sync_rc: int = 0,
        sync_aftermath: str = ":",
        pip_install_rc: Mapping[str, int] | None = None,
        installed_json: str = "[]",
        offered_json: str = "[]",
    ) -> None:
        """Write the stub with these answers.

        Args:
            venv_rc: Exit code of ``uv venv``; a non-zero one prints :data:`VENV_MARKER` on stderr.
            venv_creates: Whether a ``uv venv`` that exits 0 creates the venv-shaped directory; False
                makes uv report success and leave nothing behind.
            venv_reports: What the created venv's ``bin/python`` prints for any command line, in the
                shape bmk's interpreter probe reads (``<implementation> <X.Y.Z> <0|1>``, the last
                field the free-threaded flag); None leaves an empty, unrunnable file there.
            python_rc: Exit code of every ``uv python ...``; a non-zero ``list`` prints nothing.
            lock_rc: Exit code of ``uv lock``; a non-zero one prints :data:`LOCK_MARKER` on stderr.
            lock_upgrade_rc: The same, for a ``uv lock --upgrade`` only, so a failing upgrade can be
                told from the plain ``uv lock`` bmk runs elsewhere (one reads the cutoff back).
            lock_aftermath: Shell run by a ``uv lock`` that succeeds, in the directory uv runs in (the
                project), e.g. to rewrite ``uv.lock`` the way a real upgrade that moved a pin does.
            sync_rc: Exit code of ``uv sync``, which always prints :data:`SYNC_MARKER`, one
                SGR-coloured line and :data:`SYNC_FILLER_LINES` filler lines on stderr.
            sync_aftermath: Shell run by ``uv sync`` against ``$UV_PROJECT_ENVIRONMENT`` first.
            pip_install_rc: Exit code of ``uv pip install`` per install target (its last word);
                a target not listed succeeds, a failing one prints :data:`PIP_MARKER` and the target.
            installed_json: What ``uv python list --only-installed`` prints.
            offered_json: What any other ``uv python list`` prints.
        """
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        stub = self.bin_dir / "uv"
        stub.write_text(
            self._script(
                venv_rc=venv_rc,
                venv_creates=venv_creates,
                venv_reports=venv_reports,
                python_rc=python_rc,
                lock_rc=lock_rc,
                lock_upgrade_rc=lock_upgrade_rc,
                lock_aftermath=lock_aftermath,
                sync_rc=sync_rc,
                sync_aftermath=sync_aftermath,
                pip_install_rc=pip_install_rc or {},
                installed_json=installed_json,
                offered_json=offered_json,
            ),
            encoding="utf-8",
        )
        stub.chmod(0o755)

    def calls(self) -> list[UvCall]:
        """Every call recorded so far, in order."""
        if not self.log.is_file():
            return []
        blocks = self.log.read_text(encoding="utf-8").split(f"{_CALL_SEPARATOR}\n")
        return [_parse_call(block) for block in blocks if block]

    def commands(self) -> list[list[str]]:
        """Just the argv of every call, in the list shape bmk builds them in."""
        return [list(call.argv) for call in self.calls()]

    def _script(
        self,
        *,
        venv_rc: int,
        venv_creates: bool,
        venv_reports: str | None,
        python_rc: int,
        lock_rc: int,
        lock_upgrade_rc: int,
        lock_aftermath: str,
        sync_rc: int,
        sync_aftermath: str,
        pip_install_rc: Mapping[str, int],
        installed_json: str,
        offered_json: str,
    ) -> str:
        allowed = shlex.quote(str(self._allowed))
        pip_cases = "".join(f"      {shlex.quote(target)}) rc={rc} ;;\n" for target, rc in pip_install_rc.items())
        create = '    mkdir -p "$last/bin" && echo "home = /usr" > "$last/pyvenv.cfg" && : > "$last/bin/python"\n'
        if venv_reports is not None:
            report = shlex.quote(f"#!/bin/sh\necho {venv_reports}\n")
            create += f'    printf %s {report} > "$last/bin/python" && chmod +x "$last/bin/python"\n'
        # A mutating subcommand refuses a target outside tmp_path, so a `rm -rf` aftermath or a
        # `mkdir` can never reach a real venv if bmk stopped passing its own path.
        return (
            "#!/bin/sh\n"
            f'printf "%s\\n" "{_CALL_SEPARATOR}" "$(pwd -P)" "${{UV_PROJECT_ENVIRONMENT-{_UNSET}}}" '
            f'"${{VIRTUAL_ENV+set}}" "$@" >> {shlex.quote(str(self.log))}\n'
            "inside() {\n"
            # The match is textual, so a `..` component would climb out of tmp_path unseen.
            '  case "$1" in */../*|*/..) return 1 ;; esac\n'
            f'  case "$1" in {allowed}/*) return 0 ;; *) return 1 ;; esac\n'
            "}\n"
            'case "$1" in\n'
            "  venv)\n"
            "    for last; do :; done\n"
            f'    inside "$last" || exit {_REFUSED_OUTSIDE}\n'
            f'    [ {venv_rc} -eq 0 ] || {{ echo "error: {VENV_MARKER}" >&2; exit {venv_rc}; }}\n'
            f"{create if venv_creates else ''}"
            "    exit 0 ;;\n"
            "  python)\n"
            f"    [ {python_rc} -eq 0 ] || exit {python_rc}\n"
            '    if [ "$2" = list ]; then\n'
            '      case " $* " in\n'
            "        *' --only-installed '*) cat <<'STUB_JSON'\n"
            f"{installed_json}\n"
            "STUB_JSON\n"
            "          ;;\n"
            "        *) cat <<'STUB_JSON'\n"
            f"{offered_json}\n"
            "STUB_JSON\n"
            "          ;;\n"
            "      esac\n"
            "    fi\n"
            "    exit 0 ;;\n"
            f"  lock) rc={lock_rc}\n"
            f'    case " $* " in *" --upgrade "*) [ "$rc" -ne 0 ] || rc={lock_upgrade_rc} ;; esac\n'
            f'    [ "$rc" -eq 0 ] || {{ echo "error: {LOCK_MARKER}" >&2; exit "$rc"; }}\n'
            f"    {lock_aftermath}\n"
            "    exit 0 ;;\n"
            "  pip)\n"
            "    for last; do :; done\n"
            "    rc=0\n"
            '    case "$last" in\n'
            f"{pip_cases}"
            "    esac\n"
            f'    [ "$rc" -eq 0 ] || {{ echo "error: {PIP_MARKER} $last" >&2; exit "$rc"; }}\n'
            "    exit 0 ;;\n"
            "  sync)\n"
            f'    inside "$UV_PROJECT_ENVIRONMENT" || exit {_REFUSED_OUTSIDE}\n'
            f"    {sync_aftermath}\n"
            f'    echo "error: {SYNC_MARKER}" >&2\n'
            f"    echo '{ESC}[31m{SYNC_COLOURED}{ESC}[0m' >&2\n"
            f'    i=1; while [ "$i" -le {SYNC_FILLER_LINES} ]; do echo "filler-$i" >&2; i=$((i + 1)); done\n'
            f"    exit {sync_rc} ;;\n"
            "esac\n"
            "exit 0\n"
        )


def _parse_call(block: str) -> UvCall:
    """One log block: cwd, UV_PROJECT_ENVIRONMENT, VIRTUAL_ENV marker, then one argv word per line."""
    cwd, project_environment, virtual_env, *argv = block.removesuffix("\n").split("\n")
    return UvCall(
        argv=("uv", *argv),
        cwd=Path(cwd),
        project_environment=None if project_environment == _UNSET else project_environment,
        virtual_env_set=virtual_env == "set",
    )
