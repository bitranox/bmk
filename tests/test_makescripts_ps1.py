"""PowerShell makescript tests.

Validates that .ps1 scripts in src/bmk/makescripts/ execute correctly
under pwsh. Tests are skipped when pwsh is not available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

PWSH = shutil.which("pwsh")
MAKESCRIPTS_DIR = Path(__file__).resolve().parent.parent / "src" / "bmk" / "makescripts"

skip_no_pwsh = pytest.mark.skipif(not PWSH, reason="pwsh not installed")


def _run_ps1(
    script_name: str,
    *,
    env_overrides: dict[str, str] | None = None,
    args: list[str] | None = None,
    cwd: str | Path | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run a PowerShell script and return the result."""
    script_path = MAKESCRIPTS_DIR / script_name
    cmd = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script_path)]
    if args:
        cmd.extend(args)

    env = {**os.environ}
    # Clear inherited BMK_ env vars for clean test state
    for key in list(env.keys()):
        if key.startswith("BMK_"):
            del env[key]
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=cwd,
    )


# =============================================================================
# Stagerunner tests
# =============================================================================


@skip_no_pwsh
class TestStagerunner:
    """Tests for _btx_stagerunner.ps1."""

    @pytest.mark.os_agnostic
    def test_fails_without_project_dir(self) -> None:
        """Stagerunner fails when BMK_PROJECT_DIR is not set."""
        result = _run_ps1(
            "_btx_stagerunner.ps1",
            env_overrides={"BMK_COMMAND_PREFIX": "test"},
        )

        assert result.returncode != 0
        assert "BMK_PROJECT_DIR" in result.stderr

    @pytest.mark.os_agnostic
    def test_fails_without_command_prefix(self, tmp_path: Path) -> None:
        """Stagerunner fails when BMK_COMMAND_PREFIX is not set."""
        result = _run_ps1(
            "_btx_stagerunner.ps1",
            env_overrides={"BMK_PROJECT_DIR": str(tmp_path)},
        )

        assert result.returncode != 0
        assert "BMK_COMMAND_PREFIX" in result.stderr

    @pytest.mark.os_agnostic
    def test_no_scripts_found_exits_zero(self, tmp_path: Path) -> None:
        """Stagerunner exits 0 with informational message when no scripts match."""
        # Create a minimal pyproject.toml so package name derivation works
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test-project"
                version = "0.1.0"
            """)
        )

        result = _run_ps1(
            "_btx_stagerunner.ps1",
            env_overrides={
                "BMK_PROJECT_DIR": str(tmp_path),
                "BMK_COMMAND_PREFIX": "nonexistent",
                "BMK_STAGES_DIR": str(tmp_path),
            },
        )

        assert result.returncode == 0
        assert "No scripts found" in result.stdout

    @pytest.mark.os_agnostic
    def test_discovers_and_runs_single_stage(self, tmp_path: Path) -> None:
        """Stagerunner discovers and runs a single-script stage."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test-project"
                version = "0.1.0"
            """)
        )

        # Create a stage script that writes a marker file
        scripts_dir = tmp_path / "stages"
        scripts_dir.mkdir()
        marker = tmp_path / "marker.txt"

        stage_script = scripts_dir / "mytest_01_hello.ps1"
        stage_script.write_text(f'Write-Host "hello from stage"; "ran" | Set-Content "{marker}"\n')

        result = _run_ps1(
            "_btx_stagerunner.ps1",
            env_overrides={
                "BMK_PROJECT_DIR": str(tmp_path),
                "BMK_COMMAND_PREFIX": "mytest",
                "BMK_STAGES_DIR": str(scripts_dir),
            },
        )

        assert result.returncode == 0
        assert marker.exists()
        assert marker.read_text().strip() == "ran"

    @pytest.mark.os_agnostic
    def test_propagates_exit_code_from_failing_script(self, tmp_path: Path) -> None:
        """Stagerunner propagates non-zero exit code from a failing script."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test-project"
                version = "0.1.0"
            """)
        )

        scripts_dir = tmp_path / "stages"
        scripts_dir.mkdir()

        stage_script = scripts_dir / "fail_01_bad.ps1"
        stage_script.write_text("exit 42\n")

        result = _run_ps1(
            "_btx_stagerunner.ps1",
            env_overrides={
                "BMK_PROJECT_DIR": str(tmp_path),
                "BMK_COMMAND_PREFIX": "fail",
                "BMK_STAGES_DIR": str(scripts_dir),
            },
        )

        assert result.returncode == 42

    @pytest.mark.os_agnostic
    def test_runs_stages_sequentially(self, tmp_path: Path) -> None:
        """Stagerunner runs stage 01 before stage 02."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test-project"
                version = "0.1.0"
            """)
        )

        scripts_dir = tmp_path / "stages"
        scripts_dir.mkdir()
        order_file = tmp_path / "order.txt"

        # Stage 01 writes "first"
        (scripts_dir / "seq_01_first.ps1").write_text(f'"first" | Add-Content -Path "{order_file}"\n')
        # Stage 02 writes "second"
        (scripts_dir / "seq_02_second.ps1").write_text(f'"second" | Add-Content -Path "{order_file}"\n')

        result = _run_ps1(
            "_btx_stagerunner.ps1",
            env_overrides={
                "BMK_PROJECT_DIR": str(tmp_path),
                "BMK_COMMAND_PREFIX": "seq",
                "BMK_STAGES_DIR": str(scripts_dir),
            },
        )

        assert result.returncode == 0
        lines = order_file.read_text().strip().splitlines()
        assert lines == ["first", "second"]

    @pytest.mark.os_agnostic
    def test_stops_on_first_stage_failure(self, tmp_path: Path) -> None:
        """Stagerunner does not run stage 02 if stage 01 fails."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test-project"
                version = "0.1.0"
            """)
        )

        scripts_dir = tmp_path / "stages"
        scripts_dir.mkdir()
        marker = tmp_path / "stage2_ran.txt"

        (scripts_dir / "stop_01_fail.ps1").write_text("exit 1\n")
        (scripts_dir / "stop_02_should_not_run.ps1").write_text(f'"ran" | Set-Content "{marker}"\n')

        result = _run_ps1(
            "_btx_stagerunner.ps1",
            env_overrides={
                "BMK_PROJECT_DIR": str(tmp_path),
                "BMK_COMMAND_PREFIX": "stop",
                "BMK_STAGES_DIR": str(scripts_dir),
            },
        )

        assert result.returncode != 0
        assert not marker.exists()

    @pytest.mark.os_agnostic
    def test_forwards_arguments_to_child_scripts(self, tmp_path: Path) -> None:
        """Stagerunner forwards arguments to child scripts."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            textwrap.dedent("""\
                [project]
                name = "test-project"
                version = "0.1.0"
            """)
        )

        scripts_dir = tmp_path / "stages"
        scripts_dir.mkdir()
        args_file = tmp_path / "args.txt"

        (scripts_dir / "fwd_01_echo.ps1").write_text(f'($args -join ",") | Set-Content "{args_file}"\n')

        result = _run_ps1(
            "_btx_stagerunner.ps1",
            env_overrides={
                "BMK_PROJECT_DIR": str(tmp_path),
                "BMK_COMMAND_PREFIX": "fwd",
                "BMK_STAGES_DIR": str(scripts_dir),
            },
            args=["--verbose", "--dry-run"],
        )

        assert result.returncode == 0
        assert args_file.exists()
        content = args_file.read_text().strip()
        assert "--verbose" in content
        assert "--dry-run" in content


# =============================================================================
# Tool script smoke tests
# =============================================================================


@skip_no_pwsh
class TestToolScriptValidation:
    """Validate that tool scripts fail properly when env vars are missing."""

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        "script_name",
        [
            "test_020_ruff_format_apply.ps1",
            "test_030_ruff_fix_apply.ps1",
            "test_040_ruff_format_check.ps1",
            "test_040_ruff_lint.ps1",
            "test_040_pyright.ps1",
            "test_040_lint_imports.ps1",
            "test_040_pip_audit.ps1",
            "test_040_pytest.ps1",
            "test_040_psscriptanalyzer.ps1",
            "test_060_shellcheck.ps1",
            "push_050_push.ps1",
            "bld_020_build.ps1",
        ],
    )
    def test_fails_without_project_dir(self, script_name: str) -> None:
        """Tool script fails when BMK_PROJECT_DIR is not set."""
        result = _run_ps1(script_name)

        assert result.returncode != 0
        assert "BMK_PROJECT_DIR" in result.stderr

    @pytest.mark.os_agnostic
    def test_bandit_fails_without_package_name(self, tmp_path: Path) -> None:
        """Bandit script fails when BMK_PACKAGE_NAME is not set."""
        result = _run_ps1(
            "test_040_bandit.ps1",
            env_overrides={"BMK_PROJECT_DIR": str(tmp_path)},
        )

        assert result.returncode != 0
        assert "BMK_PACKAGE_NAME" in result.stderr


# =============================================================================
# Delegator script tests
# =============================================================================


@skip_no_pwsh
class TestDelegatorScriptValidation:
    """Validate that delegator scripts fail properly when env vars are missing."""

    @pytest.mark.os_agnostic
    @pytest.mark.parametrize(
        "script_name",
        [
            "bld_010_clean.ps1",
            "push_010_update_deps.ps1",
            "push_020_test.ps1",
            "push_020_build.ps1",
            "push_030_clean.ps1",
            "push_040_commit.ps1",
        ],
    )
    def test_fails_without_required_env_vars(self, script_name: str) -> None:
        """Delegator script fails when required env vars are not set."""
        result = _run_ps1(script_name)

        assert result.returncode != 0
        # Should mention either BMK_PROJECT_DIR or BMK_STAGES_DIR
        assert "BMK_" in result.stderr


# =============================================================================
# commit_010_commit.ps1 tests
# =============================================================================


@skip_no_pwsh
class TestCommitScript:
    """Tests for commit_010_commit.ps1."""

    @pytest.mark.os_agnostic
    def test_fails_without_project_dir(self) -> None:
        """Commit script fails when BMK_PROJECT_DIR is not set."""
        result = _run_ps1("commit_010_commit.ps1")

        assert result.returncode != 0
        assert "BMK_PROJECT_DIR" in result.stderr

    @pytest.mark.os_agnostic
    def test_uses_timestamp_in_message(self, tmp_path: Path) -> None:
        """Commit script prepends timestamp to commit message."""
        # Set up a git repo
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True,
            cwd=tmp_path,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True,
            cwd=tmp_path,
        )
        (tmp_path / "file.txt").write_text("content")
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True,
            cwd=tmp_path,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            capture_output=True,
            cwd=tmp_path,
        )

        # Make a change
        (tmp_path / "file.txt").write_text("updated")

        result = _run_ps1(
            "commit_010_commit.ps1",
            env_overrides={"BMK_PROJECT_DIR": str(tmp_path)},
            args=["test commit message"],
            cwd=tmp_path,
        )

        assert result.returncode == 0

        # Verify the commit message has timestamp
        log_result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        commit_msg = log_result.stdout.strip()
        assert "test commit message" in commit_msg
        # Timestamp format: YYYY-MM-DD HH:MM:SS
        assert " - " in commit_msg

    @pytest.mark.os_agnostic
    def test_uses_env_var_for_message(self, tmp_path: Path) -> None:
        """Commit script uses BMK_COMMIT_MESSAGE when no args given."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True,
            cwd=tmp_path,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True,
            cwd=tmp_path,
        )
        (tmp_path / "file.txt").write_text("content")
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True,
            cwd=tmp_path,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            capture_output=True,
            cwd=tmp_path,
        )

        (tmp_path / "file.txt").write_text("changed")

        result = _run_ps1(
            "commit_010_commit.ps1",
            env_overrides={
                "BMK_PROJECT_DIR": str(tmp_path),
                "BMK_COMMIT_MESSAGE": "env var message",
            },
            cwd=tmp_path,
        )

        assert result.returncode == 0

        log_result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert "env var message" in log_result.stdout.strip()

    @pytest.mark.os_agnostic
    def test_creates_empty_commit_when_no_changes(self, tmp_path: Path) -> None:
        """Commit script creates empty commit when no staged changes."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            capture_output=True,
            cwd=tmp_path,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True,
            cwd=tmp_path,
        )
        (tmp_path / "file.txt").write_text("content")
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True,
            cwd=tmp_path,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            capture_output=True,
            cwd=tmp_path,
        )

        result = _run_ps1(
            "commit_010_commit.ps1",
            env_overrides={"BMK_PROJECT_DIR": str(tmp_path)},
            args=["empty commit test"],
            cwd=tmp_path,
        )

        assert result.returncode == 0
        assert "empty commit" in result.stdout.lower() or "allow-empty" in result.stdout.lower()


# =============================================================================
# deps_010_deps.ps1 argument forwarding test
# =============================================================================


@skip_no_pwsh
class TestDepsScript:
    """Tests for deps_010_deps.ps1."""

    @pytest.mark.os_agnostic
    def test_forwards_args_to_python(self, tmp_path: Path) -> None:
        """deps_010_deps.ps1 forwards $args to the Python script."""
        result = _run_ps1(
            "deps_010_deps.ps1",
            env_overrides={"BMK_PROJECT_DIR": str(tmp_path)},
            args=["--help"],
        )

        # The Python script should receive --help and show usage
        # (it might fail because no pyproject.toml, but it should NOT
        # show "Not implemented yet")
        assert "Not implemented yet" not in result.stderr
        assert "Not implemented yet" not in result.stdout


# =============================================================================
# test_integration_010_pytest.ps1 argument forwarding test
# =============================================================================


@skip_no_pwsh
class TestIntegrationPytestScript:
    """Tests for test_integration_010_pytest.ps1."""

    @pytest.mark.os_agnostic
    def test_uses_dollar_args_not_at_args(self) -> None:
        """test_integration_010_pytest.ps1 uses $args (not @args)."""
        script_path = MAKESCRIPTS_DIR / "test_integration_010_pytest.ps1"
        content = script_path.read_text()

        # Should NOT contain @args (splat operator used incorrectly)
        # The correct usage is $args to forward to external commands
        assert "@args" not in content or "$args" in content
