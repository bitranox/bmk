"""A release writes bmk's own cooldown into the package, beside the Makefile template.

``bmk install`` deploys it as ``.bmk-cooldown.mk`` next to the Makefile, which includes it and
passes its ``BMK_COOLDOWN`` flags to uv (``tests/test_makefile_cooldown.py``). Flags rather than a
``uv.toml`` for ``--config-file``: that option makes uv ignore the user's and the system's own uv
config (measured, uv 0.13.0), so a machine that needs a private index or a proxy there would lose it.

It carries the window and the packages exempted with ``false``, plus the project itself, so a fresh
bmk release is never held back by its own cooldown. A DATED value is dropped: a fixed instant turns
tighter than the rolling window once the window passes it, and uv then silently resolves an older
bmk (user decision 2026-10-23, OPEN-WORK [107]).
"""

from __future__ import annotations

import shlex
import sys
from typing import TYPE_CHECKING

import pytest

from bmk.adapters.stagerunner.helpers._sync_initconf import main, sync_makefile_cooldown, synced_paths

if TYPE_CHECKING:
    from pathlib import Path


def _project(tmp_path: Path, uv_table: str = "", *, makefile: bool = True, name: str = "my-pkg") -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "2.0.0"\n\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/my_pkg"]\n' + uv_table,
        encoding="utf-8",
    )
    if makefile:
        makefile_dir = tmp_path / "src" / "my_pkg" / "makefile"
        makefile_dir.mkdir(parents=True)
        (makefile_dir / "Makefile").write_text("# BMK MAKEFILE 2.0.0\n", encoding="utf-8")
    return tmp_path


def _flags(project: Path) -> list[str]:
    text = (project / "src" / "my_pkg" / "makefile" / "cooldown.mk").read_text(encoding="utf-8")
    (line,) = [line for line in text.splitlines() if line.startswith("BMK_COOLDOWN :=")]
    return shlex.split(line.removeprefix("BMK_COOLDOWN :="))


_UV_TABLE = """
[tool.uv]
exclude-newer = "7 days"

[tool.uv.exclude-newer-package]
own-lib = false
certifi = "2026-10-20T02:24:17Z"
other = "2026-10-01"
"""


@pytest.mark.os_agnostic
def test_the_window_and_the_exemptions_are_written_with_the_project_itself_exempt(tmp_path: Path) -> None:
    project = _project(tmp_path, _UV_TABLE)

    assert sync_makefile_cooldown(project) is True

    assert _flags(project) == [
        "--exclude-newer",
        "7 days",
        "--exclude-newer-package",
        "my-pkg=false",
        "--exclude-newer-package",
        "own-lib=false",
    ]


@pytest.mark.os_agnostic
def test_a_project_without_a_cooldown_gets_a_file_that_sets_none(tmp_path: Path) -> None:
    project = _project(tmp_path, "\n[tool.uv]\ndev-dependencies = []\n")

    assert sync_makefile_cooldown(project) is True

    assert _flags(project) == []


@pytest.mark.os_agnostic
def test_a_dated_global_window_sets_no_cooldown(tmp_path: Path) -> None:
    """A fixed cutoff would freeze bmk's dependencies at that date, the stale-pin failure once more."""
    project = _project(tmp_path, '\n[tool.uv]\nexclude-newer = "2026-10-01T00:00:00Z"\n')

    sync_makefile_cooldown(project)

    assert _flags(project) == []


@pytest.mark.os_agnostic
def test_a_value_the_shell_would_reinterpret_is_never_written(tmp_path: Path) -> None:
    """The fragment is expanded into a bash command line, so only plain names and spans pass."""
    project = _project(
        tmp_path,
        '\n[tool.uv]\nexclude-newer = "7 days"\n\n[tool.uv.exclude-newer-package]\n"a;b" = false\n',
        name="x$(id)",
    )

    sync_makefile_cooldown(project)

    assert _flags(project) == ["--exclude-newer", "7 days"]


@pytest.mark.os_agnostic
def test_a_second_sync_with_nothing_changed_writes_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path, _UV_TABLE)
    sync_makefile_cooldown(project)

    assert sync_makefile_cooldown(project) is False


@pytest.mark.os_agnostic
def test_a_project_without_a_makefile_template_gets_no_cooldown_file(tmp_path: Path) -> None:
    project = _project(tmp_path, _UV_TABLE, makefile=False)

    assert sync_makefile_cooldown(project) is False
    assert not (project / "src" / "my_pkg" / "makefile").exists()


@pytest.mark.os_agnostic
def test_the_bump_undo_covers_the_cooldown_file(tmp_path: Path) -> None:
    project = _project(tmp_path, _UV_TABLE)

    assert project / "src" / "my_pkg" / "makefile" / "cooldown.mk" in synced_paths(project)


@pytest.mark.os_agnostic
def test_the_sync_entry_point_writes_the_cooldown_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path, _UV_TABLE)
    monkeypatch.setattr(sys, "argv", ["_sync_initconf.py", "--project-dir", str(project)])

    assert main() == 0
    assert _flags(project)[:2] == ["--exclude-newer", "7 days"]
