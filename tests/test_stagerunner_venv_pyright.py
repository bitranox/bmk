"""Tests for keeping bmk's venvs out of the project's pyright run.

The defect these lock down, in full: pyright's ``exclude`` REPLACES its built-in
defaults (``**/node_modules``, ``**/__pycache__``, ``**/.*``) rather than adding
to them. So a project that lists any exclude of its own - ``exclude =
["scripts/menu.py"]`` is the bitranox template's default - silently loses
``**/.*`` and with it the only rule that kept dot-directories out.

That was harmless while nothing put a venv in the project. bmk now does: it
provisions ``.venv`` and the Makefile installs bmk into ``.venv-bmk``. pyright
then walks thousands of site-packages files in strict mode and never finishes -
measured: one such run spun for 6h20m at 78% CPU and produced nothing, with no
error message to say why.

bmk creates these directories, so bmk excludes them, exactly as it gitignores
them (``ensure_venv_ignored``). The alternative - a note telling every repo to
re-list the defaults - is the failure mode that caused this.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit

from bmk.adapters.stagerunner.venv import ensure_venv_typecheck_excluded


def _write(project: Path, body: str) -> None:
    (project / "pyproject.toml").write_text(body, encoding="utf-8")


def _exclude(project: Path) -> list[str]:
    doc = tomlkit.parse((project / "pyproject.toml").read_text(encoding="utf-8"))
    return list(doc["tool"]["pyright"]["exclude"])  # type: ignore[index]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path


# --- the defect: an explicit exclude drops pyright's defaults ---------------


@pytest.mark.os_agnostic
def test_glob_exclude_is_idempotent_across_matrix_venvs(project: Path) -> None:
    """The `.venv*` entry is added once and recognised as covering every concrete venv.

    Runs for several different matrix venvs must not grow the exclude list - which pins that
    an existing `.venv*` counts as covering `.venv-3.10`, `.venv-3.14`, etc.
    """
    _write(project, '[tool.pyright]\nexclude = ["scripts/menu.py"]\n')

    ensure_venv_typecheck_excluded(project, project / ".venv")
    ensure_venv_typecheck_excluded(project, project / ".venv-3.10")
    ensure_venv_typecheck_excluded(project, project / ".venv-3.14")

    assert _exclude(project).count(".venv*") == 1


@pytest.mark.os_agnostic
def test_explicit_exclude_gains_the_venv_glob(project: Path) -> None:
    """One `.venv*` entry keeps every venv (default, siblings, and .venv-<minor>) out of strict pyright."""
    _write(project, '[tool.pyright]\nexclude = ["scripts/menu.py"]\n')

    ensure_venv_typecheck_excluded(project, project / ".venv")

    excluded = _exclude(project)
    assert "scripts/menu.py" in excluded, "must not drop what the project already excluded"
    assert ".venv*" in excluded, "the .venv* glob covers every venv, including the matrix"


@pytest.mark.os_agnostic
def test_comments_and_formatting_survive(project: Path) -> None:
    """A round-trip, not a rewrite: pyproject.toml is the user's file.

    This repo's own pyproject carries a load-bearing comment block explaining a
    disabled dependency; a regex or a re-dump would lose it.
    """
    _write(
        project,
        '[tool.pyright]\n# menu.py is textual-heavy and not worth strict mode\nexclude = ["scripts/menu.py"]\n\n[tool.ruff]\nline-length = 120\n',
    )

    ensure_venv_typecheck_excluded(project, project / ".venv")

    text = (project / "pyproject.toml").read_text(encoding="utf-8")
    assert "# menu.py is textual-heavy and not worth strict mode" in text
    assert "line-length = 120" in text


# --- cases that must be left alone -----------------------------------------


@pytest.mark.os_agnostic
def test_no_exclude_key_is_left_alone(project: Path) -> None:
    """With no exclude, pyright's own ``**/.*`` default already covers them.

    Adding entries here would only take the defaults away from the project - the
    precise mistake being fixed.
    """
    _write(project, '[tool.pyright]\ntypeCheckingMode = "strict"\n')

    ensure_venv_typecheck_excluded(project, project / ".venv")

    doc = tomlkit.parse((project / "pyproject.toml").read_text(encoding="utf-8"))
    assert "exclude" not in doc["tool"]["pyright"]  # type: ignore[operator]


@pytest.mark.os_agnostic
def test_include_narrows_scope_so_nothing_is_added(project: Path) -> None:
    """An include list means pyright never walks the venv in the first place."""
    _write(project, '[tool.pyright]\ninclude = ["src", "tests"]\nexclude = ["scripts/menu.py"]\n')

    ensure_venv_typecheck_excluded(project, project / ".venv")

    assert _exclude(project) == ["scripts/menu.py"]


@pytest.mark.os_agnostic
def test_no_pyright_section_is_left_alone(project: Path) -> None:
    _write(project, '[project]\nname = "x"\n')

    ensure_venv_typecheck_excluded(project, project / ".venv")

    assert "pyright" not in (project / "pyproject.toml").read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_missing_pyproject_never_raises(project: Path) -> None:
    """Provisioning must degrade, never abort a run."""
    ensure_venv_typecheck_excluded(project, project / ".venv")


@pytest.mark.os_agnostic
def test_unparseable_pyproject_never_raises(project: Path) -> None:
    _write(project, "[tool.pyright\nexclude = [")

    ensure_venv_typecheck_excluded(project, project / ".venv")


# --- idempotence and existing coverage --------------------------------------


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "pattern",
    ["**/.*", ".venv", "**/.venv", "**/.venv/**", ".venv/"],
)
def test_existing_pattern_is_not_duplicated(project: Path, pattern: str) -> None:
    """Each spelling that already covers .venv must not gain a second entry.

    pyright accepts several forms; appending a duplicate on every run is how a
    config file grows without bound.
    """
    _write(project, f'[tool.pyright]\nexclude = ["{pattern}"]\n')

    ensure_venv_typecheck_excluded(project, project / ".venv")

    assert _exclude(project).count(".venv") == (1 if pattern == ".venv" else 0)


@pytest.mark.os_agnostic
def test_running_twice_changes_nothing(project: Path) -> None:
    _write(project, '[tool.pyright]\nexclude = ["scripts/menu.py"]\n')

    ensure_venv_typecheck_excluded(project, project / ".venv")
    once = (project / "pyproject.toml").read_text(encoding="utf-8")
    ensure_venv_typecheck_excluded(project, project / ".venv")

    assert (project / "pyproject.toml").read_text(encoding="utf-8") == once


@pytest.mark.os_agnostic
def test_wildcard_default_alone_is_enough(project: Path) -> None:
    """A project that re-listed pyright's defaults is already correct."""
    _write(project, '[tool.pyright]\nexclude = ["**/node_modules", "**/__pycache__", "**/.*", "scripts/menu.py"]\n')

    ensure_venv_typecheck_excluded(project, project / ".venv")

    assert _exclude(project) == ["**/node_modules", "**/__pycache__", "**/.*", "scripts/menu.py"]


# --- the managed venv may be somewhere else ---------------------------------


@pytest.mark.os_agnostic
def test_custom_venv_matching_the_glob_needs_no_extra_entry(project: Path) -> None:
    """A `.venv-custom` path is already covered by `.venv*` - no separate entry."""
    _write(project, '[tool.pyright]\nexclude = ["scripts/menu.py"]\n')

    ensure_venv_typecheck_excluded(project, project / ".venv-custom")

    assert ".venv*" in _exclude(project)


@pytest.mark.os_agnostic
def test_non_venv_named_environment_gets_its_own_entry(project: Path) -> None:
    """UV_PROJECT_ENVIRONMENT can name a venv OUTSIDE the `.venv*` pattern (e.g. `env`)."""
    _write(project, '[tool.pyright]\nexclude = ["scripts/menu.py"]\n')

    ensure_venv_typecheck_excluded(project, project / "env")

    excluded = _exclude(project)
    assert ".venv*" in excluded
    assert "env" in excluded, "a non-.venv* venv is not covered by the glob, so it needs its own entry"


@pytest.mark.os_agnostic
def test_venv_outside_the_repo_adds_only_the_glob(project: Path, tmp_path: Path) -> None:
    """A venv that is not inside the project cannot be walked by pyright."""
    _write(project, '[tool.pyright]\nexclude = ["scripts/menu.py"]\n')
    outside = tmp_path.parent / "elsewhere-venv"

    ensure_venv_typecheck_excluded(project, outside)

    excluded = _exclude(project)
    assert "elsewhere-venv" not in excluded
    assert ".venv*" in excluded
