"""Behaviour tests for makescripts._shellcheck: config reading, file discovery, and orchestration."""

from __future__ import annotations

import contextlib
import os
import subprocess
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

from bmk.adapters.stagerunner.helpers._shellcheck import (
    find_sh_files,
    get_bashate_config,
    main,
    run_bashate,
    run_shellcheck,
    run_shfmt,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

_REAL_RUN = subprocess.run


@contextlib.contextmanager
def _fake_linters(**mock_kwargs: Any) -> Generator[MagicMock]:
    """Fake every subprocess.run the linters make; git (the file discovery) runs for real.

    The patch target is process-wide, so without the routing the discovery's
    ``git ls-files`` would be answered by the linter fake.
    """
    fake = MagicMock(**mock_kwargs)

    def route(cmd: list[str], **kwargs: Any) -> object:
        if cmd[0] == "git":
            # Forwarding Any kwargs leaves pyright unable to pick a run() overload.
            return cast("subprocess.CompletedProcess[bytes]", _REAL_RUN(cmd, **kwargs))
        return fake(cmd, **kwargs)

    with patch("bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run", side_effect=route):
        yield fake


# ---------------------------------------------------------------------------
# get_bashate_config
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_bashate_config_returns_fallback_when_no_pyproject(tmp_path: Path) -> None:
    """Falls back to built-in defaults when pyproject.toml is absent."""
    settings = get_bashate_config(tmp_path / "nonexistent.toml")

    assert settings.max_line_length == 120
    assert isinstance(settings.ignores, tuple)
    assert "E003" in settings.ignores


@pytest.mark.os_agnostic
def test_get_bashate_config_returns_fallback_when_no_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Falls back to built-in defaults and warns when [tool.bashate] is absent."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'test'\n")

    settings = get_bashate_config(pyproject)

    assert settings.max_line_length == 120
    assert "E003" in settings.ignores
    captured = capsys.readouterr()
    assert "WARNING: No [tool.bashate] section found" in captured.err
    assert "[tool.bashate]" in captured.err


@pytest.mark.os_agnostic
def test_get_bashate_config_reads_from_pyproject(tmp_path: Path) -> None:
    """Reads custom values from [tool.bashate]."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 100\nignores = ["E006", "E010"]\n'
    )

    settings = get_bashate_config(pyproject)

    assert settings.max_line_length == 100
    assert "E006" in settings.ignores
    assert "E010" in settings.ignores
    assert len(settings.ignores) == 2


@pytest.mark.os_agnostic
def test_get_bashate_config_reads_ignores_from_pyproject(tmp_path: Path) -> None:
    """Verify ignores list parsing with single entry."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 80\nignores = ["E003"]\n')

    settings = get_bashate_config(pyproject)

    assert settings.max_line_length == 80
    assert settings.ignores == ("E003",)


# ---------------------------------------------------------------------------
# find_sh_files
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_find_sh_files_excludes_venv(tmp_path: Path) -> None:
    """Files under .venv are excluded from results."""
    venv_dir = tmp_path / ".venv" / "bin"
    venv_dir.mkdir(parents=True)
    (venv_dir / "activate.sh").write_text("# venv")

    project_script = tmp_path / "src" / "scripts"
    project_script.mkdir(parents=True)
    (project_script / "build.sh").write_text("# build")

    files = find_sh_files(tmp_path)

    assert len(files) == 1
    assert files[0].name == "build.sh"


@pytest.mark.os_agnostic
def test_find_sh_files_excludes_suffixed_venv(tmp_path: Path) -> None:
    """A suffixed venv dir (.venv-win, the Windows env in the dual-OS layout) is excluded."""
    venv_dir = tmp_path / ".venv-win" / "bin"
    venv_dir.mkdir(parents=True)
    (venv_dir / "activate.sh").write_text("# win venv")

    project_script = tmp_path / "src" / "scripts"
    project_script.mkdir(parents=True)
    (project_script / "build.sh").write_text("# build")

    files = find_sh_files(tmp_path)

    assert len(files) == 1
    assert files[0].name == "build.sh"


@pytest.mark.os_agnostic
def test_find_sh_files_excludes_node_modules(tmp_path: Path) -> None:
    """Files under node_modules are excluded from results."""
    nm_dir = tmp_path / "node_modules" / "pkg"
    nm_dir.mkdir(parents=True)
    (nm_dir / "script.sh").write_text("# npm")

    files = find_sh_files(tmp_path)

    assert len(files) == 0


@pytest.mark.os_agnostic
def test_find_sh_files_excludes_git(tmp_path: Path) -> None:
    """Files under .git are excluded from results."""
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    (git_dir / "pre-commit.sh").write_text("# hook")

    files = find_sh_files(tmp_path)

    assert len(files) == 0


@pytest.mark.os_agnostic
def test_find_sh_files_excludes_linked_worktree(tmp_path: Path) -> None:
    """A nested directory whose ``.git`` is a FILE (linked git worktree) is excluded.

    A linked worktree's ``.git`` is a file containing a ``gitdir:`` pointer, not a
    directory. Its contents belong to whatever branch is checked out there, not to
    this project, so a script inside it must never be linted as this project's source.
    """
    worktree_dir = tmp_path / ".claude" / "worktrees" / "other-branch"
    worktree_dir.mkdir(parents=True)
    (worktree_dir / ".git").write_text("gitdir: /some/other/repo/.git/worktrees/other-branch\n")
    (worktree_dir / "vendored.sh").write_text("# belongs to another branch")

    project_script = tmp_path / "src" / "scripts"
    project_script.mkdir(parents=True)
    (project_script / "build.sh").write_text("# build")

    files = find_sh_files(tmp_path)

    assert len(files) == 1
    assert files[0].name == "build.sh"


@pytest.mark.os_agnostic
def test_find_sh_files_excludes_nested_clone(tmp_path: Path) -> None:
    """A nested directory whose ``.git`` is a DIRECTORY (a full nested clone/submodule) is excluded."""
    nested_repo = tmp_path / "vendor" / "some-dependency"
    nested_repo.mkdir(parents=True)
    (nested_repo / ".git").mkdir()
    (nested_repo / "vendored.sh").write_text("# belongs to a nested checkout")

    project_script = tmp_path / "src" / "scripts"
    project_script.mkdir(parents=True)
    (project_script / "build.sh").write_text("# build")

    files = find_sh_files(tmp_path)

    assert len(files) == 1
    assert files[0].name == "build.sh"


@pytest.mark.os_agnostic
def test_find_sh_files_includes_root_files_when_root_itself_has_git(tmp_path: Path) -> None:
    """The project root's own ``.git`` must not exclude the project's own scripts (no over-correction)."""
    (tmp_path / ".git").mkdir()

    project_script = tmp_path / "src" / "scripts"
    project_script.mkdir(parents=True)
    (project_script / "build.sh").write_text("# build")

    files = find_sh_files(tmp_path)

    assert len(files) == 1
    assert files[0].name == "build.sh"


@pytest.mark.os_agnostic
def test_find_sh_files_includes_root_files_when_root_is_itself_a_worktree(tmp_path: Path) -> None:
    """A project checked out AS a linked worktree has a ``.git`` FILE at its root, not a directory.

    This is the shape of the case that motivated the exclusion: bmk (or any project) may itself be
    developed inside a worktree, and the root marker must never exclude the project's own scripts.
    """
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/feature\n")

    project_script = tmp_path / "src" / "scripts"
    project_script.mkdir(parents=True)
    (project_script / "build.sh").write_text("# build")

    files = find_sh_files(tmp_path)

    assert len(files) == 1
    assert files[0].name == "build.sh"


@pytest.mark.os_agnostic
def test_find_sh_files_returns_empty_for_no_files(tmp_path: Path) -> None:
    """Returns empty list when no .sh files exist."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# python")

    files = find_sh_files(tmp_path)

    assert files == []


@pytest.mark.os_agnostic
def test_find_sh_files_returns_sorted(tmp_path: Path) -> None:
    """Results are sorted by path."""
    (tmp_path / "z_script.sh").write_text("# z")
    (tmp_path / "a_script.sh").write_text("# a")
    (tmp_path / "m_script.sh").write_text("# m")

    files = find_sh_files(tmp_path)

    assert len(files) == 3
    assert files[0].name == "a_script.sh"
    assert files[1].name == "m_script.sh"
    assert files[2].name == "z_script.sh"


@pytest.mark.os_agnostic
def test_find_sh_files_skips_a_script_git_ignores(tmp_path: Path, git_project: Callable[..., None]) -> None:
    """A script in a directory whose own ``.gitignore`` says ``*`` is not linted.

    Scratch launchers left in such a directory are not project source; linting them
    turned ``make test`` red while the code under test was clean.
    """
    (tmp_path / "build.sh").write_text("# build")
    git_project("add", "build.sh")
    scratch = tmp_path / ".bitranox" / "sdd"
    scratch.mkdir(parents=True)
    (scratch / ".gitignore").write_text("*\n")
    (scratch / "launch.sh").write_text("cd somewhere\n")

    files = find_sh_files(tmp_path)

    assert [f.relative_to(tmp_path).as_posix() for f in files] == ["build.sh"]


@pytest.mark.os_agnostic
def test_find_sh_files_keeps_an_untracked_script_git_does_not_ignore(
    tmp_path: Path, git_project: Callable[..., None]
) -> None:
    """A new script that is not yet added but not ignored either is still linted."""
    (tmp_path / "build.sh").write_text("# build")
    git_project("add", "build.sh")
    (tmp_path / "new.sh").write_text("# new")

    files = find_sh_files(tmp_path)

    assert [f.name for f in files] == ["build.sh", "new.sh"]


@pytest.mark.os_agnostic
def test_find_sh_files_skips_a_tracked_script_deleted_from_disk(
    tmp_path: Path, git_project: Callable[..., None]
) -> None:
    """The index still lists a deleted file; only files that exist reach the linters."""
    (tmp_path / "build.sh").write_text("# build")
    (tmp_path / "gone.sh").write_text("# gone")
    git_project("add", "build.sh", "gone.sh")
    (tmp_path / "gone.sh").unlink()

    files = find_sh_files(tmp_path)

    assert [f.name for f in files] == ["build.sh"]


@pytest.mark.os_agnostic
def test_find_sh_files_returns_a_non_ascii_name_unquoted(tmp_path: Path, git_project: Callable[..., None]) -> None:
    """git quotes a non-ASCII path by default; the returned path must be the real file."""
    (tmp_path / "skript-ä.sh").write_text("# umlaut")
    git_project("add", "skript-ä.sh")

    files = find_sh_files(tmp_path)

    assert files == [tmp_path / "skript-ä.sh"]


@pytest.mark.os_agnostic
def test_find_sh_files_answers_for_the_project_despite_an_inherited_git_dir(
    tmp_path: Path, git_project: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``GIT_DIR`` inherited from a hook must not make git answer for another repository.

    Only the project's own index knows the script below is tracked; read through a
    foreign repository it looks like an ignored, untracked file and drops out.
    """
    (tmp_path / ".gitignore").write_text("vendor/\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "keep.sh").write_text("# tracked on purpose")
    git_project("add", "-f", "vendor/keep.sh")
    other = tmp_path.parent / f"{tmp_path.name}-other"
    other.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=other, check=True, capture_output=True)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    files = find_sh_files(tmp_path)

    assert [f.relative_to(tmp_path).as_posix() for f in files] == ["vendor/keep.sh"]


@pytest.mark.os_agnostic
def test_find_sh_files_keeps_a_tracked_script_under_an_ignored_path(
    tmp_path: Path, git_project: Callable[..., None]
) -> None:
    """A script git tracks is project source even where a ``.gitignore`` pattern covers it."""
    (tmp_path / ".gitignore").write_text("vendor/\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "keep.sh").write_text("# tracked on purpose")
    (tmp_path / "vendor" / "scratch.sh").write_text("# ignored")
    git_project("add", "-f", "vendor/keep.sh")

    files = find_sh_files(tmp_path)

    assert [f.relative_to(tmp_path).as_posix() for f in files] == ["vendor/keep.sh"]


@pytest.mark.os_agnostic
@pytest.mark.parametrize("variable", ["GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS"])
def test_find_sh_files_ignores_an_inherited_pathspec_mode(
    tmp_path: Path, git_project: Callable[..., None], monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    """git exports these for ``git --literal-pathspecs``; inherited, they made the list empty."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "top.sh").write_text("# top")
    (tmp_path / "sub" / "deep.sh").write_text("# deep")
    git_project("add", "top.sh", "sub/deep.sh")
    monkeypatch.setenv(variable, "1")

    files = find_sh_files(tmp_path)

    assert [f.relative_to(tmp_path).as_posix() for f in files] == ["sub/deep.sh", "top.sh"]


@pytest.mark.os_agnostic
def test_find_sh_files_walks_a_project_directory_its_parent_repository_ignores(
    tmp_path: Path, git_project: Callable[..., None]
) -> None:
    """A project inside a repository that ignores it is not that repository's source, so walk it."""
    (tmp_path / ".gitignore").write_text("proj/\n")
    project = tmp_path / "proj"
    project.mkdir()
    (project / "tool.sh").write_text("# tool")

    files = find_sh_files(project)

    assert [f.name for f in files] == ["tool.sh"]


@pytest.mark.os_agnostic
def test_find_sh_files_warns_when_git_refuses_a_work_tree(
    tmp_path: Path,
    git_project: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When git fails inside a checkout the walk is used, and the reader is told why.

    ``GIT_TEST_ASSUME_DIFFERENT_OWNER`` makes git refuse the repository as it does for
    dubious ownership, so the walk lints the ignored script again - which must not be silent.
    git's configuration is pinned to nothing, because a ``safe.directory = *`` anywhere in it
    (GitHub's runners set one) makes git accept the repository and the premise never holds.
    """
    (tmp_path / ".gitignore").write_text("scratch/\n")
    (tmp_path / "ok.sh").write_text("# ok")
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "junk.sh").write_text("# junk")
    git_project("add", "ok.sh", ".gitignore")
    empty_config = tmp_path.parent / f"{tmp_path.name}-gitconfig"
    empty_config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in [n for n in os.environ if n.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))]:
        monkeypatch.delenv(name)
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    monkeypatch.delenv("GIT_CONFIG_PARAMETERS", raising=False)
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    refused = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"], cwd=tmp_path, capture_output=True, check=False
    )
    assert refused.returncode != 0, "premise: git must refuse this repository"

    files = find_sh_files(tmp_path)

    assert [f.relative_to(tmp_path).as_posix() for f in files] == ["ok.sh", "scratch/junk.sh"]
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "git" in err


@pytest.mark.os_agnostic
def test_find_sh_files_outside_git_walks_without_a_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Outside any checkout the walk is the normal path and says nothing."""
    (tmp_path / "build.sh").write_text("# build")

    files = find_sh_files(tmp_path)

    assert [f.name for f in files] == ["build.sh"]
    assert capsys.readouterr().err == ""


@pytest.mark.os_agnostic
def test_main_lints_only_the_scripts_git_lists(tmp_path: Path, git_project: Callable[..., None]) -> None:
    """End to end through the git listing: the ignored script never reaches a linter."""
    (tmp_path / "build.sh").write_text("#!/bin/bash\n")
    (tmp_path / ".gitignore").write_text("scratch/\n")
    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "launch.sh").write_text("cd somewhere\n")
    git_project("add", "build.sh", ".gitignore")

    with _fake_linters(return_value=_make_completed(0)) as fake:
        result = main(project_dir=tmp_path)

    linted = [arg for call in fake.call_args_list for arg in call.args[0]]
    assert result == 0
    assert any(arg.endswith("build.sh") for arg in linted)
    assert not any("launch.sh" in arg for arg in linted)


# ---------------------------------------------------------------------------
# run_shellcheck
# ---------------------------------------------------------------------------


def _make_completed(returncode: int, *, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.mark.os_agnostic
def test_run_shellcheck_returns_zero_on_clean(tmp_path: Path) -> None:
    """Returns 0 when shellcheck reports no violations."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch(
        "bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run", return_value=_make_completed(0)
    ) as mock_run:
        result = run_shellcheck(files=[script])

    assert result == 0
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "shellcheck"
    assert str(script) in cmd


@pytest.mark.os_agnostic
def test_run_shellcheck_returns_nonzero_on_violations(tmp_path: Path) -> None:
    """Returns non-zero when shellcheck finds violations."""
    script = tmp_path / "bad.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run", return_value=_make_completed(1)):
        result = run_shellcheck(files=[script])

    assert result == 1


@pytest.mark.os_agnostic
def test_run_shellcheck_verbose_prints_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose mode prints the command being run."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run", return_value=_make_completed(0)):
        run_shellcheck(files=[script], verbose=True)

    assert "Running:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_shfmt
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_shfmt_returns_zero_when_no_diffs(tmp_path: Path) -> None:
    """Returns 0 when shfmt finds no formatting differences."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run", return_value=_make_completed(0)):
        result = run_shfmt(files=[script])

    assert result == 0


@pytest.mark.os_agnostic
def test_run_shfmt_returns_one_when_diffs_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 1 and prints diff when shfmt finds formatting differences."""
    script = tmp_path / "bad.sh"
    script.write_text("#!/bin/bash\n")
    with patch(
        "bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run",
        return_value=_make_completed(0, stdout="--- a/bad.sh\n+++ b/bad.sh\n"),
    ):
        result = run_shfmt(files=[script])

    assert result == 1
    captured = capsys.readouterr()
    assert "bad.sh" in captured.out
    assert "shfmt found formatting differences" in captured.err


@pytest.mark.os_agnostic
def test_run_shfmt_verbose_prints_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose mode prints the command being run."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run", return_value=_make_completed(0)):
        run_shfmt(files=[script], verbose=True)

    assert "Running:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_bashate
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_bashate_returns_zero_on_clean(tmp_path: Path) -> None:
    """Returns 0 when bashate reports no style issues."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch(
        "bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run", return_value=_make_completed(0)
    ) as mock_run:
        result = run_bashate(files=[script], max_line_length=120, ignores=("E003",))

    assert result == 0
    cmd = mock_run.call_args[0][0]
    assert "--max-line-length=120" in cmd
    assert "--ignore=E003" in cmd


@pytest.mark.os_agnostic
def test_run_bashate_returns_nonzero_on_violations(tmp_path: Path) -> None:
    """Returns non-zero when bashate finds style issues."""
    script = tmp_path / "bad.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run", return_value=_make_completed(1)):
        result = run_bashate(files=[script], max_line_length=120, ignores=())

    assert result == 1


@pytest.mark.os_agnostic
def test_run_bashate_omits_ignore_flag_when_empty(tmp_path: Path) -> None:
    """No --ignore flag when ignores tuple is empty."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch(
        "bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run", return_value=_make_completed(0)
    ) as mock_run:
        run_bashate(files=[script], max_line_length=80, ignores=())

    cmd = mock_run.call_args[0][0]
    assert not any(arg.startswith("--ignore") for arg in cmd)


@pytest.mark.os_agnostic
def test_run_bashate_verbose_prints_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose mode prints the command being run."""
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/bash\n")
    with patch("bmk.adapters.stagerunner.helpers._shellcheck.subprocess.run", return_value=_make_completed(0)):
        run_bashate(files=[script], max_line_length=120, ignores=(), verbose=True)

    assert "Running:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_main_returns_zero_when_no_sh_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 0 and prints skip message when no .sh files exist."""
    result = main(project_dir=tmp_path)

    assert result == 0
    assert "No .sh files found" in capsys.readouterr().out


@pytest.mark.os_agnostic
def test_main_returns_zero_when_all_tools_pass(tmp_path: Path) -> None:
    """Returns 0 when all three linters pass."""
    (tmp_path / "script.sh").write_text("#!/bin/bash\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 120\nignores = ["E003"]\n'
    )

    with _fake_linters(return_value=_make_completed(0)):
        result = main(project_dir=tmp_path)

    assert result == 0


@pytest.mark.os_agnostic
def test_main_returns_one_when_shellcheck_fails(tmp_path: Path) -> None:
    """Returns 1 when shellcheck reports violations."""
    (tmp_path / "script.sh").write_text("#!/bin/bash\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 120\nignores = ["E003"]\n'
    )

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "shellcheck":
            return _make_completed(1)
        return _make_completed(0)

    with _fake_linters(side_effect=_side_effect):
        result = main(project_dir=tmp_path)

    assert result == 1


@pytest.mark.os_agnostic
def test_main_returns_one_when_shfmt_fails(tmp_path: Path) -> None:
    """Returns 1 when shfmt finds formatting differences."""
    (tmp_path / "script.sh").write_text("#!/bin/bash\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 120\nignores = ["E003"]\n'
    )

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "shfmt":
            return _make_completed(0, stdout="--- diff output\n")
        return _make_completed(0)

    with _fake_linters(side_effect=_side_effect):
        result = main(project_dir=tmp_path)

    assert result == 1


@pytest.mark.os_agnostic
def test_main_returns_one_when_bashate_fails(tmp_path: Path) -> None:
    """Returns 1 when bashate reports style issues."""
    (tmp_path / "script.sh").write_text("#!/bin/bash\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 120\nignores = ["E003"]\n'
    )

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "bashate":
            return _make_completed(1)
        return _make_completed(0)

    with _fake_linters(side_effect=_side_effect):
        result = main(project_dir=tmp_path)

    assert result == 1


@pytest.mark.os_agnostic
def test_main_aggregates_failures_from_multiple_tools(tmp_path: Path) -> None:
    """Returns 1 when multiple tools fail (runs all tools, doesn't short-circuit)."""
    (tmp_path / "script.sh").write_text("#!/bin/bash\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.bashate]\nmax-line-length = 120\nignores = ["E003"]\n'
    )
    call_count = 0

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        return _make_completed(1)

    with _fake_linters(side_effect=_side_effect):
        result = main(project_dir=tmp_path)

    assert result == 1
    assert call_count == 3
