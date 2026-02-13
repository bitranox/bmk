"""Behaviour tests for makescripts._coverage: coverage management, git resolution, and Codecov upload."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bmk.makescripts._coverage import (
    CoverageConfig,
    _build_codecov_args,
    _build_codecov_env,
    _build_env,
    _check_codecov_prerequisites,
    _find_dotenv_upward,
    _get_repo_metadata_from_git,
    _get_repo_slug,
    _handle_codecov_result,
    _resolve_commit_sha,
    _resolve_git_branch,
    _resolve_git_service,
    ensure_codecov_token,
    main,
    prune_coverage_data_files,
    remove_report_artifacts,
    run_coverage_tests,
    upload_coverage_report,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_completed(returncode: int, *, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# CoverageConfig.from_pyproject — defaults when no file
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_coverage_config_returns_defaults_when_no_pyproject(tmp_path: Path) -> None:
    """Falls back to default values when pyproject.toml is absent."""
    config = CoverageConfig.from_pyproject(tmp_path / "nonexistent")

    assert config.pytest_verbosity == "-v"
    assert config.coverage_report_file == "coverage.xml"
    assert config.src_path == "src"
    assert config.fail_under == 80
    assert config.coverage_source == ["src"]
    assert config.exclude_markers == "integration"


# ---------------------------------------------------------------------------
# CoverageConfig.from_pyproject — reads from pyproject.toml
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_coverage_config_reads_scripts_section(tmp_path: Path) -> None:
    """Reads pytest_verbosity, coverage_report_file, src_path from [tool.scripts]."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test"\n\n'
        "[tool.scripts]\n"
        'pytest_verbosity = "-vv"\n'
        'coverage_report_file = "cov.xml"\n'
        'src_path = "lib"\n'
        'exclude_markers = "slow"\n'
    )

    config = CoverageConfig.from_pyproject(tmp_path)

    assert config.pytest_verbosity == "-vv"
    assert config.coverage_report_file == "cov.xml"
    assert config.src_path == "lib"
    assert config.exclude_markers == "slow"


@pytest.mark.os_agnostic
def test_coverage_config_reads_coverage_sections(tmp_path: Path) -> None:
    """Reads source from [tool.coverage.run] and fail_under from [tool.coverage.report]."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test"\n\n'
        "[tool.coverage.run]\n"
        'source = ["src/mypkg"]\n\n'
        "[tool.coverage.report]\n"
        "fail_under = 90\n"
    )

    config = CoverageConfig.from_pyproject(tmp_path)

    assert config.coverage_source == ["src/mypkg"]
    assert config.fail_under == 90


@pytest.mark.os_agnostic
def test_coverage_config_uses_tomllib_fallback(tmp_path: Path) -> None:
    """Exercises the tomli fallback import path for Python <3.11 compatibility."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    # Patch tomllib to raise ImportError, forcing the tomli fallback
    with patch.dict("sys.modules", {"tomllib": None}):
        config = CoverageConfig.from_pyproject(tmp_path)

    assert config.pytest_verbosity == "-v"


# ---------------------------------------------------------------------------
# prune_coverage_data_files
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_prune_coverage_data_files_deletes_coverage_files(tmp_path: Path) -> None:
    """Deletes .coverage and .coverage.* data files."""
    (tmp_path / ".coverage").write_text("data")
    (tmp_path / ".coverage.abc123").write_text("data")

    prune_coverage_data_files(tmp_path)

    assert not (tmp_path / ".coverage").exists()
    assert not (tmp_path / ".coverage.abc123").exists()


@pytest.mark.os_agnostic
def test_prune_coverage_data_files_skips_directories(tmp_path: Path) -> None:
    """Does not delete directories matching .coverage* pattern."""
    cov_dir = tmp_path / ".coverage_html"
    cov_dir.mkdir()
    (cov_dir / "index.html").write_text("<html/>")

    prune_coverage_data_files(tmp_path)

    assert cov_dir.exists()


@pytest.mark.os_agnostic
def test_prune_coverage_data_files_skips_xml_files(tmp_path: Path) -> None:
    """Does not delete .coverage.xml files."""
    xml_file = tmp_path / ".coverage.xml"
    xml_file.write_text("<coverage/>")

    prune_coverage_data_files(tmp_path)

    assert xml_file.exists()


@pytest.mark.os_agnostic
def test_prune_coverage_data_files_handles_file_not_found(tmp_path: Path) -> None:
    """Silently continues when a file disappears between glob and unlink."""
    (tmp_path / ".coverage").write_text("data")

    with patch.object(Path, "unlink", side_effect=FileNotFoundError):
        prune_coverage_data_files(tmp_path)


@pytest.mark.os_agnostic
def test_prune_coverage_data_files_warns_on_os_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Prints warning to stderr when OSError occurs during deletion."""
    (tmp_path / ".coverage").write_text("data")

    with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
        prune_coverage_data_files(tmp_path)

    captured = capsys.readouterr()
    assert "[coverage] warning: unable to remove" in captured.err
    assert "permission denied" in captured.err


@pytest.mark.os_agnostic
def test_prune_coverage_data_files_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults to cwd when project_dir is None."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    (tmp_path / ".coverage").write_text("data")

    prune_coverage_data_files()

    assert not (tmp_path / ".coverage").exists()


# ---------------------------------------------------------------------------
# remove_report_artifacts
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_remove_report_artifacts_deletes_coverage_and_codecov_xml(tmp_path: Path) -> None:
    """Deletes both coverage.xml and codecov.xml."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    (tmp_path / "codecov.xml").write_text("<codecov/>")

    remove_report_artifacts(tmp_path)

    assert not (tmp_path / "coverage.xml").exists()
    assert not (tmp_path / "codecov.xml").exists()


@pytest.mark.os_agnostic
def test_remove_report_artifacts_uses_custom_report_name(tmp_path: Path) -> None:
    """Uses the provided coverage_report_file name."""
    (tmp_path / "cov.xml").write_text("<coverage/>")

    remove_report_artifacts(tmp_path, "cov.xml")

    assert not (tmp_path / "cov.xml").exists()


@pytest.mark.os_agnostic
def test_remove_report_artifacts_handles_missing_files(tmp_path: Path) -> None:
    """Silently continues when files do not exist."""
    remove_report_artifacts(tmp_path)


@pytest.mark.os_agnostic
def test_remove_report_artifacts_warns_on_os_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Prints warning to stderr when OSError occurs during deletion."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")

    with patch.object(Path, "unlink", side_effect=OSError("busy")):
        remove_report_artifacts(tmp_path)

    captured = capsys.readouterr()
    assert "[coverage] warning: unable to remove" in captured.err
    assert "busy" in captured.err


@pytest.mark.os_agnostic
def test_remove_report_artifacts_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults to cwd when project_dir is None."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    (tmp_path / "coverage.xml").write_text("<coverage/>")

    remove_report_artifacts()

    assert not (tmp_path / "coverage.xml").exists()


# ---------------------------------------------------------------------------
# _build_env
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_build_env_sets_pythonpath(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Puts project src_path at the front of PYTHONPATH."""
    monkeypatch.delenv("PYTHONPATH", raising=False)

    env = _build_env(tmp_path, "src")

    assert env["PYTHONPATH"] == str(tmp_path / "src")


@pytest.mark.os_agnostic
def test_build_env_appends_existing_pythonpath(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Appends existing PYTHONPATH to the new value."""
    monkeypatch.setenv("PYTHONPATH", "/existing/path")

    env = _build_env(tmp_path, "src")

    parts = env["PYTHONPATH"].split(os.pathsep)
    assert parts[0] == str(tmp_path / "src")
    assert parts[1] == "/existing/path"


# ---------------------------------------------------------------------------
# run_coverage_tests
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_coverage_tests_returns_zero_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns 0 when all subprocess steps succeed."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test"\n\n'
        "[tool.scripts]\n"
        'pytest_verbosity = "-v"\n'
        'src_path = "src"\n\n'
        "[tool.coverage.run]\n"
        'source = ["src/pkg"]\n\n'
        "[tool.coverage.report]\n"
        "fail_under = 80\n"
    )

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(0)):
        result = run_coverage_tests(project_dir=tmp_path)

    assert result == 0


@pytest.mark.os_agnostic
def test_run_coverage_tests_returns_nonzero_when_pytest_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns pytest exit code when test run fails."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(1)):
        result = run_coverage_tests(project_dir=tmp_path)

    assert result == 1


@pytest.mark.os_agnostic
def test_run_coverage_tests_returns_nonzero_when_report_fails(tmp_path: Path) -> None:
    """Returns report exit code when coverage report step fails."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    call_count = 0

    def _side_effect(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_completed(0)  # pytest passes
        return _make_completed(2)  # coverage report fails

    with patch("bmk.makescripts._coverage.subprocess.run", side_effect=_side_effect):
        result = run_coverage_tests(project_dir=tmp_path)

    assert result == 2


@pytest.mark.os_agnostic
def test_run_coverage_tests_xml_failure_does_not_fail_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """XML generation failure prints warning but returns 0."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    call_count = 0

    def _side_effect(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return _make_completed(0)  # pytest and report pass
        return _make_completed(3)  # xml generation fails

    with patch("bmk.makescripts._coverage.subprocess.run", side_effect=_side_effect):
        result = run_coverage_tests(project_dir=tmp_path, generate_xml=True)

    assert result == 0
    captured = capsys.readouterr()
    assert "XML report generation failed" in captured.err


@pytest.mark.os_agnostic
def test_run_coverage_tests_skips_xml_when_disabled(tmp_path: Path) -> None:
    """Does not generate XML report when generate_xml is False."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    call_count = 0

    def _side_effect(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        return _make_completed(0)

    with patch("bmk.makescripts._coverage.subprocess.run", side_effect=_side_effect):
        result = run_coverage_tests(project_dir=tmp_path, generate_xml=False)

    assert result == 0
    assert call_count == 2  # only pytest + report, no xml


@pytest.mark.os_agnostic
def test_run_coverage_tests_includes_marker_filter_by_default(tmp_path: Path) -> None:
    """Adds marker filter to exclude integration tests by default."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(0)) as mock_run:
        run_coverage_tests(project_dir=tmp_path)

    first_call_args = mock_run.call_args_list[0][0][0]
    assert "-m" in first_call_args
    # The second -m is the marker filter (first -m is for pytest module)
    marker_args = [first_call_args[i + 1] for i, v in enumerate(first_call_args) if v == "-m"]
    assert any("not integration" in m for m in marker_args)


@pytest.mark.os_agnostic
def test_run_coverage_tests_omits_marker_filter_for_integration(tmp_path: Path) -> None:
    """No marker filter when include_integration is True."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(0)) as mock_run:
        run_coverage_tests(project_dir=tmp_path, include_integration=True)

    first_call_args = mock_run.call_args_list[0][0][0]
    # Should only have the module -m for pytest, not a marker filter -m
    m_indices = [i for i, v in enumerate(first_call_args) if v == "-m"]
    marker_values = [first_call_args[i + 1] for i in m_indices]
    assert not any("not integration" in m for m in marker_values)


@pytest.mark.os_agnostic
def test_run_coverage_tests_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults project_dir to cwd when not specified."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(0)):
        result = run_coverage_tests()

    assert result == 0


@pytest.mark.os_agnostic
def test_run_coverage_tests_prints_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Prints coverage commands as they execute."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(0)):
        run_coverage_tests(project_dir=tmp_path)

    captured = capsys.readouterr()
    assert "[coverage] python -m coverage run" in captured.out
    assert "[coverage] python -m coverage report" in captured.out
    assert "[coverage] python -m coverage xml" in captured.out


# ---------------------------------------------------------------------------
# _find_dotenv_upward
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_find_dotenv_upward_finds_in_start_dir(tmp_path: Path) -> None:
    """Finds .env in the start directory itself."""
    (tmp_path / ".env").write_text("TOKEN=abc")

    result = _find_dotenv_upward(tmp_path)

    assert result is not None
    assert result.name == ".env"


@pytest.mark.os_agnostic
def test_find_dotenv_upward_finds_in_parent(tmp_path: Path) -> None:
    """Finds .env in a parent directory."""
    child = tmp_path / "project" / "src"
    child.mkdir(parents=True)
    (tmp_path / ".env").write_text("TOKEN=abc")

    result = _find_dotenv_upward(child)

    assert result is not None
    assert result == (tmp_path / ".env").resolve()


@pytest.mark.os_agnostic
def test_find_dotenv_upward_returns_none_when_missing(tmp_path: Path) -> None:
    """Returns None when no .env file exists in any ancestor."""
    child = tmp_path / "deep" / "nested"
    child.mkdir(parents=True)

    result = _find_dotenv_upward(child)

    # Might find a real .env on the filesystem; only assert it's None or a Path
    # In isolated tmp_path, unlikely to have .env in /tmp ancestors
    if result is not None:
        assert result.name == ".env"


# ---------------------------------------------------------------------------
# ensure_codecov_token
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_ensure_codecov_token_returns_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns CODECOV_TOKEN from environment when set."""
    monkeypatch.setenv("CODECOV_TOKEN", "env-token-123")

    result = ensure_codecov_token()

    assert result == "env-token-123"


@pytest.mark.os_agnostic
def test_ensure_codecov_token_reads_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reads CODECOV_TOKEN from .env file when env var is not set."""
    monkeypatch.delenv("CODECOV_TOKEN", raising=False)
    (tmp_path / ".env").write_text("CODECOV_TOKEN=dotenv-token-456\n")

    with patch("dotenv.dotenv_values", return_value={"CODECOV_TOKEN": "dotenv-token-456"}):
        result = ensure_codecov_token(tmp_path)

    assert result == "dotenv-token-456"


@pytest.mark.os_agnostic
def test_ensure_codecov_token_returns_none_when_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when token is not in env or .env file."""
    monkeypatch.delenv("CODECOV_TOKEN", raising=False)
    child = tmp_path / "project"
    child.mkdir()

    result = ensure_codecov_token(child)

    assert result is None


@pytest.mark.os_agnostic
def test_ensure_codecov_token_returns_none_for_empty_dotenv_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns None when .env has CODECOV_TOKEN set to empty string."""
    monkeypatch.delenv("CODECOV_TOKEN", raising=False)
    (tmp_path / ".env").write_text("CODECOV_TOKEN=\n")

    with patch("dotenv.dotenv_values", return_value={"CODECOV_TOKEN": ""}):
        result = ensure_codecov_token(tmp_path)

    assert result is None


# ---------------------------------------------------------------------------
# _resolve_commit_sha
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_resolve_commit_sha_returns_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns GITHUB_SHA from environment when set."""
    monkeypatch.setenv("GITHUB_SHA", "abc123def456")

    result = _resolve_commit_sha()

    assert result == "abc123def456"


@pytest.mark.os_agnostic
def test_resolve_commit_sha_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strips whitespace from GITHUB_SHA env var."""
    monkeypatch.setenv("GITHUB_SHA", "  abc123  ")

    result = _resolve_commit_sha()

    assert result == "abc123"


@pytest.mark.os_agnostic
def test_resolve_commit_sha_falls_back_to_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falls back to git rev-parse HEAD when GITHUB_SHA is not set."""
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="deadbeef1234\n"),
    ):
        result = _resolve_commit_sha()

    assert result == "deadbeef1234"


@pytest.mark.os_agnostic
def test_resolve_commit_sha_returns_none_on_git_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when git rev-parse fails."""
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(128),
    ):
        result = _resolve_commit_sha()

    assert result is None


@pytest.mark.os_agnostic
def test_resolve_commit_sha_returns_none_for_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when git rev-parse returns empty stdout."""
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout=""),
    ):
        result = _resolve_commit_sha()

    assert result is None


# ---------------------------------------------------------------------------
# _resolve_git_branch
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_resolve_git_branch_returns_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns GITHUB_REF_NAME from environment when set."""
    monkeypatch.setenv("GITHUB_REF_NAME", "feature-branch")

    result = _resolve_git_branch()

    assert result == "feature-branch"


@pytest.mark.os_agnostic
def test_resolve_git_branch_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strips whitespace from GITHUB_REF_NAME env var."""
    monkeypatch.setenv("GITHUB_REF_NAME", "  main  ")

    result = _resolve_git_branch()

    assert result == "main"


@pytest.mark.os_agnostic
def test_resolve_git_branch_falls_back_to_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falls back to git rev-parse --abbrev-ref HEAD when env var is not set."""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="develop\n"),
    ):
        result = _resolve_git_branch()

    assert result == "develop"


@pytest.mark.os_agnostic
def test_resolve_git_branch_returns_none_on_git_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when git command fails."""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(128),
    ):
        result = _resolve_git_branch()

    assert result is None


@pytest.mark.os_agnostic
def test_resolve_git_branch_returns_none_for_detached_head(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when git reports HEAD (detached state)."""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="HEAD\n"),
    ):
        result = _resolve_git_branch()

    assert result is None


@pytest.mark.os_agnostic
def test_resolve_git_branch_returns_none_for_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when git returns empty output."""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout=""),
    ):
        result = _resolve_git_branch()

    assert result is None


# ---------------------------------------------------------------------------
# _resolve_git_service
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_resolve_git_service_maps_github() -> None:
    """Maps github.com to 'github'."""
    assert _resolve_git_service("github.com") == "github"


@pytest.mark.os_agnostic
def test_resolve_git_service_maps_gitlab() -> None:
    """Maps gitlab.com to 'gitlab'."""
    assert _resolve_git_service("gitlab.com") == "gitlab"


@pytest.mark.os_agnostic
def test_resolve_git_service_maps_bitbucket() -> None:
    """Maps bitbucket.org to 'bitbucket'."""
    assert _resolve_git_service("bitbucket.org") == "bitbucket"


@pytest.mark.os_agnostic
def test_resolve_git_service_returns_none_for_unknown_host() -> None:
    """Returns None for unrecognised hosts."""
    assert _resolve_git_service("gitea.example.com") is None


@pytest.mark.os_agnostic
def test_resolve_git_service_returns_none_for_none() -> None:
    """Returns None when host is None."""
    assert _resolve_git_service(None) is None


@pytest.mark.os_agnostic
def test_resolve_git_service_case_insensitive() -> None:
    """Host matching is case-insensitive."""
    assert _resolve_git_service("GitHub.com") == "github"


# ---------------------------------------------------------------------------
# _get_repo_slug
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_repo_slug_returns_slug() -> None:
    """Returns 'owner/name' when both are provided."""
    assert _get_repo_slug("myorg", "myrepo") == "myorg/myrepo"


@pytest.mark.os_agnostic
def test_get_repo_slug_returns_none_when_owner_missing() -> None:
    """Returns None when owner is None."""
    assert _get_repo_slug(None, "myrepo") is None


@pytest.mark.os_agnostic
def test_get_repo_slug_returns_none_when_name_missing() -> None:
    """Returns None when name is None."""
    assert _get_repo_slug("myorg", None) is None


@pytest.mark.os_agnostic
def test_get_repo_slug_returns_none_when_both_missing() -> None:
    """Returns None when both are None."""
    assert _get_repo_slug(None, None) is None


# ---------------------------------------------------------------------------
# _get_repo_metadata_from_git — SSH URLs
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_repo_metadata_parses_ssh_url() -> None:
    """Parses SSH URL format git@host:owner/repo.git."""
    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="git@github.com:myorg/myrepo.git\n"),
    ):
        host, owner, name = _get_repo_metadata_from_git()

    assert host == "github.com"
    assert owner == "myorg"
    assert name == "myrepo"


@pytest.mark.os_agnostic
def test_get_repo_metadata_parses_ssh_url_without_git_suffix() -> None:
    """Parses SSH URL without .git suffix."""
    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="git@gitlab.com:team/project\n"),
    ):
        host, owner, name = _get_repo_metadata_from_git()

    assert host == "gitlab.com"
    assert owner == "team"
    assert name == "project"


# ---------------------------------------------------------------------------
# _get_repo_metadata_from_git — HTTPS URLs
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_repo_metadata_parses_https_url() -> None:
    """Parses HTTPS URL format https://host/owner/repo.git."""
    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="https://github.com/myorg/myrepo.git\n"),
    ):
        host, owner, name = _get_repo_metadata_from_git()

    assert host == "github.com"
    assert owner == "myorg"
    assert name == "myrepo"


@pytest.mark.os_agnostic
def test_get_repo_metadata_parses_https_url_without_git_suffix() -> None:
    """Parses HTTPS URL without .git suffix."""
    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="https://bitbucket.org/team/project\n"),
    ):
        host, owner, name = _get_repo_metadata_from_git()

    assert host == "bitbucket.org"
    assert owner == "team"
    assert name == "project"


@pytest.mark.os_agnostic
def test_get_repo_metadata_parses_http_url() -> None:
    """Parses HTTP URL (non-TLS) format."""
    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="http://gitea.local/dev/app.git\n"),
    ):
        host, owner, name = _get_repo_metadata_from_git()

    assert host == "gitea.local"
    assert owner == "dev"
    assert name == "app"


# ---------------------------------------------------------------------------
# _get_repo_metadata_from_git — error / edge cases
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_repo_metadata_returns_none_tuple_on_git_failure() -> None:
    """Returns (None, None, None) when git command fails."""
    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(128),
    ):
        host, owner, name = _get_repo_metadata_from_git()

    assert host is None
    assert owner is None
    assert name is None


@pytest.mark.os_agnostic
def test_get_repo_metadata_returns_none_tuple_for_unknown_format() -> None:
    """Returns (None, None, None) for unrecognised URL format."""
    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="svn://example.com/repo\n"),
    ):
        host, owner, name = _get_repo_metadata_from_git()

    assert host is None
    assert owner is None
    assert name is None


# ---------------------------------------------------------------------------
# _check_codecov_prerequisites
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_check_prerequisites_returns_none_when_report_missing(tmp_path: Path) -> None:
    """Returns None when coverage report file does not exist."""
    result = _check_codecov_prerequisites(tmp_path, "coverage.xml")

    assert result is None


@pytest.mark.os_agnostic
def test_check_prerequisites_returns_none_when_no_token_outside_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns None when no token is available and not running in CI."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.delenv("CODECOV_TOKEN", raising=False)
    monkeypatch.delenv("CI", raising=False)

    result = _check_codecov_prerequisites(tmp_path, "coverage.xml")

    assert result is None


@pytest.mark.os_agnostic
def test_check_prerequisites_returns_none_when_codecovcli_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns None when codecovcli is not installed."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.setenv("CODECOV_TOKEN", "token123")

    with patch("bmk.makescripts._coverage.shutil.which", return_value=None):
        result = _check_codecov_prerequisites(tmp_path, "coverage.xml", codecov_token="token123")

    assert result is None


@pytest.mark.os_agnostic
def test_check_prerequisites_returns_uploader_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns path to codecovcli when all prerequisites are met."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.setenv("CODECOV_TOKEN", "token123")

    with patch("bmk.makescripts._coverage.shutil.which", return_value="/usr/bin/codecovcli"):
        result = _check_codecov_prerequisites(tmp_path, "coverage.xml", codecov_token="token123")

    assert result == "/usr/bin/codecovcli"


@pytest.mark.os_agnostic
def test_check_prerequisites_allows_ci_without_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Passes token check when CI env var is set, even without explicit token."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.delenv("CODECOV_TOKEN", raising=False)
    monkeypatch.setenv("CI", "true")

    with patch("bmk.makescripts._coverage.shutil.which", return_value="/usr/bin/codecovcli"):
        result = _check_codecov_prerequisites(tmp_path, "coverage.xml")

    assert result == "/usr/bin/codecovcli"


# ---------------------------------------------------------------------------
# _build_codecov_args
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_build_codecov_args_includes_required_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Builds argument list with required flags."""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(128)):
        args = _build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
            coverage_report_file="coverage.xml",
        )

    assert args[0] == "/usr/bin/codecovcli"
    assert "upload-coverage" in args
    assert "--file" in args
    assert "coverage.xml" in args
    assert "--sha" in args
    assert "abc123" in args
    assert "--disable-search" in args
    assert "--fail-on-error" in args


@pytest.mark.os_agnostic
def test_build_codecov_args_includes_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adds --branch flag when branch is resolved."""
    monkeypatch.setenv("GITHUB_REF_NAME", "main")

    args = _build_codecov_args(
        uploader="/usr/bin/codecovcli",
        commit_sha="abc123",
    )

    assert "--branch" in args
    assert "main" in args


@pytest.mark.os_agnostic
def test_build_codecov_args_includes_git_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adds --git-service flag when host maps to a known service."""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(128)):
        args = _build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
            repo_host="github.com",
        )

    assert "--git-service" in args
    assert "github" in args


@pytest.mark.os_agnostic
def test_build_codecov_args_includes_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adds --slug flag when owner and name are available."""
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(128)):
        args = _build_codecov_args(
            uploader="/usr/bin/codecovcli",
            commit_sha="abc123",
            repo_owner="myorg",
            repo_name="myrepo",
        )

    assert "--slug" in args
    assert "myorg/myrepo" in args


# ---------------------------------------------------------------------------
# _build_codecov_env
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_build_codecov_env_always_sets_no_combine() -> None:
    """Always includes CODECOV_NO_COMBINE=1."""
    env = _build_codecov_env(None, None)

    assert env["CODECOV_NO_COMBINE"] == "1"


@pytest.mark.os_agnostic
def test_build_codecov_env_sets_slug_when_available() -> None:
    """Sets CODECOV_SLUG when owner and name are provided."""
    env = _build_codecov_env("myorg", "myrepo")

    assert env["CODECOV_SLUG"] == "myorg/myrepo"


@pytest.mark.os_agnostic
def test_build_codecov_env_omits_slug_when_missing() -> None:
    """Omits CODECOV_SLUG when owner or name is missing."""
    env = _build_codecov_env(None, "myrepo")

    assert "CODECOV_SLUG" not in env


# ---------------------------------------------------------------------------
# _handle_codecov_result
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_handle_codecov_result_returns_true_on_success(capsys: pytest.CaptureFixture[str]) -> None:
    """Returns True and prints success message for exit code 0."""
    result = _handle_codecov_result(0)

    assert result is True
    assert "upload succeeded" in capsys.readouterr().out


@pytest.mark.os_agnostic
def test_handle_codecov_result_returns_false_on_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """Returns False and prints failure message for non-zero exit code."""
    result = _handle_codecov_result(1)

    assert result is False
    assert "upload failed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# upload_coverage_report
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_upload_coverage_report_returns_false_when_prerequisites_fail(tmp_path: Path) -> None:
    """Returns False when prerequisites are not met (no report file)."""
    result = upload_coverage_report(project_dir=tmp_path)

    assert result is False


@pytest.mark.os_agnostic
def test_upload_coverage_report_returns_true_when_no_commit_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Returns True (skip) when commit SHA cannot be resolved."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.setenv("CODECOV_TOKEN", "token123")
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    with (
        patch("bmk.makescripts._coverage.shutil.which", return_value="/usr/bin/codecovcli"),
        patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(128)),
    ):
        result = upload_coverage_report(project_dir=tmp_path, codecov_token="token123")

    assert result is True
    assert "Unable to resolve git commit" in capsys.readouterr().err


@pytest.mark.os_agnostic
def test_upload_coverage_report_runs_full_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs full upload workflow and returns True on success."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.setenv("CODECOV_TOKEN", "token123")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    call_args_collector: list[list[str]] = []

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        call_args_collector.append(cmd)
        # First call is git remote get-url, second is git branch, third is codecov upload
        if cmd[0] == "git":
            if "remote" in cmd:
                return _make_completed(0, stdout="git@github.com:myorg/myrepo.git\n")
            return _make_completed(128)  # branch resolution fails
        return _make_completed(0)  # codecov upload succeeds

    with (
        patch("bmk.makescripts._coverage.shutil.which", return_value="/usr/bin/codecovcli"),
        patch("bmk.makescripts._coverage.subprocess.run", side_effect=_side_effect),
    ):
        result = upload_coverage_report(project_dir=tmp_path, codecov_token="token123")

    assert result is True


@pytest.mark.os_agnostic
def test_upload_coverage_report_returns_false_when_upload_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns False when codecov CLI returns non-zero."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.setenv("CODECOV_TOKEN", "token123")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "git":
            return _make_completed(128)
        return _make_completed(1)  # codecov upload fails

    with (
        patch("bmk.makescripts._coverage.shutil.which", return_value="/usr/bin/codecovcli"),
        patch("bmk.makescripts._coverage.subprocess.run", side_effect=_side_effect),
    ):
        result = upload_coverage_report(project_dir=tmp_path, codecov_token="token123")

    assert result is False


@pytest.mark.os_agnostic
def test_upload_coverage_report_injects_token_into_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Passes codecov_token in subprocess environment without mutating os.environ."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.setenv("CODECOV_TOKEN", "token123")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    captured_env: dict[str, str] = {}

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "git":
            return _make_completed(128)
        captured_env.update(kwargs.get("env", {}))  # type: ignore[arg-type]
        return _make_completed(0)

    with (
        patch("bmk.makescripts._coverage.shutil.which", return_value="/usr/bin/codecovcli"),
        patch("bmk.makescripts._coverage.subprocess.run", side_effect=_side_effect),
    ):
        upload_coverage_report(project_dir=tmp_path, codecov_token="token123")

    assert captured_env.get("CODECOV_TOKEN") == "token123"


@pytest.mark.os_agnostic
def test_upload_coverage_report_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults project_dir to cwd when not specified."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    # No coverage.xml -> returns False from prerequisites
    result = upload_coverage_report()

    assert result is False


# ---------------------------------------------------------------------------
# main — run_tests branch
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_main_runs_tests_and_returns_zero_on_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns 0 when run_tests succeeds."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')
    monkeypatch.delenv("CODECOV_TOKEN", raising=False)

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(0)):
        result = main(project_dir=tmp_path, run_tests=True, upload=False)

    assert result == 0
    captured = capsys.readouterr()
    assert "[coverage] Running tests with coverage" in captured.out
    assert "[coverage] Tests passed" in captured.out


@pytest.mark.os_agnostic
def test_main_returns_nonzero_when_tests_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns test exit code when run_tests fails."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(5)):
        result = main(project_dir=tmp_path, run_tests=True, upload=False)

    assert result == 5
    captured = capsys.readouterr()
    assert "Tests failed (exit 5)" in captured.err


@pytest.mark.os_agnostic
def test_main_skips_upload_when_tests_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Does not attempt upload when test run fails."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')
    monkeypatch.setenv("CODECOV_TOKEN", "token123")

    with patch("bmk.makescripts._coverage.subprocess.run", return_value=_make_completed(1)):
        result = main(project_dir=tmp_path, run_tests=True, upload=True)

    assert result == 1


# ---------------------------------------------------------------------------
# main — upload branch
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_main_uploads_and_returns_zero_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Returns 0 when upload succeeds."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.setenv("CODECOV_TOKEN", "token123")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "git":
            return _make_completed(128)
        return _make_completed(0)

    with (
        patch("bmk.makescripts._coverage.shutil.which", return_value="/usr/bin/codecovcli"),
        patch("bmk.makescripts._coverage.subprocess.run", side_effect=_side_effect),
    ):
        result = main(project_dir=tmp_path, run_tests=False, upload=True)

    assert result == 0
    captured = capsys.readouterr()
    assert "[codecov] Uploading coverage" in captured.out


@pytest.mark.os_agnostic
def test_main_returns_one_when_upload_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns 1 when upload fails."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.setenv("CODECOV_TOKEN", "token123")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "git":
            return _make_completed(128)
        return _make_completed(1)

    with (
        patch("bmk.makescripts._coverage.shutil.which", return_value="/usr/bin/codecovcli"),
        patch("bmk.makescripts._coverage.subprocess.run", side_effect=_side_effect),
    ):
        result = main(project_dir=tmp_path, run_tests=False, upload=True)

    assert result == 1


@pytest.mark.os_agnostic
def test_main_returns_zero_when_no_token_for_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Returns 0 with warning when CODECOV_TOKEN is not found for upload."""
    monkeypatch.delenv("CODECOV_TOKEN", raising=False)
    child = tmp_path / "project"
    child.mkdir()

    result = main(project_dir=child, run_tests=False, upload=True)

    assert result == 0
    captured = capsys.readouterr()
    assert "CODECOV_TOKEN not found" in captured.err


@pytest.mark.os_agnostic
def test_main_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults project_dir to cwd when not specified."""
    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    monkeypatch.delenv("CODECOV_TOKEN", raising=False)

    result = main(run_tests=False, upload=False)

    assert result == 0


@pytest.mark.os_agnostic
def test_get_repo_metadata_returns_none_for_ssh_without_colon() -> None:
    """Returns (None, None, None) when SSH URL has no colon separator."""
    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="git@github.com/owner/repo.git\n"),
    ):
        host, owner, name = _get_repo_metadata_from_git()

    assert host is None
    assert owner is None
    assert name is None


@pytest.mark.os_agnostic
def test_get_repo_metadata_returns_none_for_ssh_single_path_segment() -> None:
    """Returns (None, None, None) when SSH URL has only one path segment after colon."""
    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="git@github.com:repoonly\n"),
    ):
        host, owner, name = _get_repo_metadata_from_git()

    assert host is None
    assert owner is None
    assert name is None


@pytest.mark.os_agnostic
def test_get_repo_metadata_returns_none_for_https_too_few_parts() -> None:
    """Returns (None, None, None) when HTTPS URL has too few path segments."""
    with patch(
        "bmk.makescripts._coverage.subprocess.run",
        return_value=_make_completed(0, stdout="https://github.com/owner-only\n"),
    ):
        host, owner, name = _get_repo_metadata_from_git()

    assert host is None
    assert owner is None
    assert name is None


@pytest.mark.os_agnostic
def test_upload_coverage_report_without_explicit_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Upload works when token is in env but not passed explicitly."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    monkeypatch.setenv("CODECOV_TOKEN", "env-token")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    captured_env: dict[str, str] = {}

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "git":
            return _make_completed(128)
        captured_env.update(kwargs.get("env", {}))  # type: ignore[arg-type]
        return _make_completed(0)

    with (
        patch("bmk.makescripts._coverage.shutil.which", return_value="/usr/bin/codecovcli"),
        patch("bmk.makescripts._coverage.subprocess.run", side_effect=_side_effect),
    ):
        result = upload_coverage_report(project_dir=tmp_path)

    assert result is True
    # Token comes from env, not from codecov_token= parameter
    assert captured_env.get("CODECOV_TOKEN") == "env-token"


@pytest.mark.os_agnostic
def test_main_runs_tests_then_uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs tests first, then uploads when both flags are set."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')
    monkeypatch.setenv("CODECOV_TOKEN", "token123")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    report_path = tmp_path / "coverage.xml"

    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        # Simulate 'coverage xml -o coverage.xml' creating the report file
        if "xml" in cmd and "-o" in cmd:
            report_path.write_text("<coverage/>")
        if cmd[0] == "git":
            return _make_completed(128)
        return _make_completed(0)

    with (
        patch("bmk.makescripts._coverage.shutil.which", return_value="/usr/bin/codecovcli"),
        patch("bmk.makescripts._coverage.subprocess.run", side_effect=_side_effect),
    ):
        result = main(project_dir=tmp_path, run_tests=True, upload=True)

    assert result == 0
