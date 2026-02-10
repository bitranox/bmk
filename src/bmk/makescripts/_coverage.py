"""Coverage file management, test execution, and Codecov upload helpers.

Purpose
-------
Isolate everything related to cleaning coverage artefacts, running tests with
coverage, resolving git metadata for Codecov, and uploading coverage reports.

Contents
--------
* ``prune_coverage_data_files`` / ``remove_report_artifacts`` -- housekeeping
  before and after coverage runs.
* ``run_coverage_tests`` -- run pytest under coverage and generate reports.
* ``ensure_codecov_token`` -- discovers ``CODECOV_TOKEN`` from the environment
  or ``.env`` file and returns it without mutating global state.
* ``upload_coverage_report`` -- drives the official Codecov CLI uploader.
* Git resolution helpers (commit SHA, branch, service).
* ``main`` -- entry point for standalone execution.

System Role
-----------
Called from the test orchestrator (``test.py``) after pytest completes,
or standalone via ``cov_010_coverage.sh`` stage script.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "prune_coverage_data_files",
    "remove_report_artifacts",
    "run_coverage_tests",
    "ensure_codecov_token",
    "upload_coverage_report",
    "main",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageConfig:
    """Configuration for coverage runs loaded from pyproject.toml."""

    pytest_verbosity: str
    coverage_report_file: str
    src_path: str
    fail_under: int
    coverage_source: list[str]
    exclude_markers: str

    @classmethod
    def from_pyproject(cls, project_dir: Path) -> CoverageConfig:
        """Load coverage configuration from pyproject.toml.

        Args:
            project_dir: Directory containing pyproject.toml.

        Returns:
            CoverageConfig with values from pyproject.toml or defaults.
        """
        pyproject_path = project_dir / "pyproject.toml"
        if not pyproject_path.is_file():
            return cls(
                pytest_verbosity="-v",
                coverage_report_file="coverage.xml",
                src_path="src",
                fail_under=80,
                coverage_source=["src"],
                exclude_markers="integration",
            )

        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]

        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)

        tool = data.get("tool", {})
        scripts = tool.get("scripts", {})
        coverage_run = tool.get("coverage", {}).get("run", {})
        coverage_report = tool.get("coverage", {}).get("report", {})

        return cls(
            pytest_verbosity=scripts.get("pytest_verbosity", "-v"),
            coverage_report_file=scripts.get("coverage_report_file", "coverage.xml"),
            src_path=scripts.get("src_path", "src"),
            fail_under=coverage_report.get("fail_under", 80),
            coverage_source=coverage_run.get("source", ["src"]),
            exclude_markers=scripts.get("exclude_markers", "integration"),
        )


# ---------------------------------------------------------------------------
# Coverage File Management
# ---------------------------------------------------------------------------


def prune_coverage_data_files(project_dir: Path | None = None) -> None:
    """Delete SQLite coverage data shards to keep the Codecov CLI simple.

    Args:
        project_dir: Directory to search for coverage files. Defaults to cwd.
    """
    if project_dir is None:
        project_dir = Path.cwd()
    for path in project_dir.glob(".coverage*"):
        if path.is_dir() or path.suffix == ".xml":
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"[coverage] warning: unable to remove {path}: {exc}", file=sys.stderr)


def remove_report_artifacts(
    project_dir: Path | None = None,
    coverage_report_file: str = "coverage.xml",
) -> None:
    """Remove coverage reports that might lock the SQLite database on reruns.

    Args:
        project_dir: Directory to search for coverage files. Defaults to cwd.
        coverage_report_file: Name of the coverage report file.
    """
    if project_dir is None:
        project_dir = Path.cwd()
    for name in (coverage_report_file, "codecov.xml"):
        artifact = project_dir / name
        try:
            artifact.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"[coverage] warning: unable to remove {artifact}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Coverage Test Execution
# ---------------------------------------------------------------------------


def _build_env(project_dir: Path, src_path: str) -> dict[str, str]:
    """Build environment for subprocess execution.

    Args:
        project_dir: Project root directory.
        src_path: Source path to add to PYTHONPATH.

    Returns:
        Environment dictionary with updated PYTHONPATH.
    """
    pythonpath_parts = [str(project_dir / src_path)]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        pythonpath_parts.append(existing)
    pythonpath = os.pathsep.join(pythonpath_parts)
    return os.environ.copy() | {"PYTHONPATH": pythonpath}


def run_coverage_tests(
    *,
    project_dir: Path | None = None,
    verbose: bool = False,
    generate_xml: bool = True,
    include_integration: bool = False,
) -> int:
    """Run pytest under coverage and generate reports.

    Args:
        project_dir: Project directory. Defaults to cwd.
        verbose: Enable verbose output.
        generate_xml: Generate XML coverage report for Codecov.
        include_integration: Include integration tests (excluded by default).

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    if project_dir is None:
        project_dir = Path.cwd()

    config = CoverageConfig.from_pyproject(project_dir)
    coverage_source = ",".join(config.coverage_source)

    # Clean up before run
    prune_coverage_data_files(project_dir)
    remove_report_artifacts(project_dir, config.coverage_report_file)

    base_env = _build_env(project_dir, config.src_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        coverage_file = Path(tmpdir) / ".coverage"
        env = base_env | {"COVERAGE_FILE": str(coverage_file)}

        # Run pytest under coverage
        coverage_cmd = [
            sys.executable,
            "-m",
            "coverage",
            "run",
            f"--source={coverage_source}",
            "-m",
            "pytest",
        ]

        # Add marker filter unless including integration tests
        marker_filter = ""
        if not include_integration and config.exclude_markers:
            marker_filter = f"not {config.exclude_markers}"
            coverage_cmd.extend(["-m", marker_filter])

        coverage_cmd.append(config.pytest_verbosity)

        # Build display command
        marker_display = f"-m '{marker_filter}' " if marker_filter else ""
        print(
            f"[coverage] python -m coverage run --source={coverage_source} "
            f"-m pytest {marker_display}{config.pytest_verbosity}"
        )

        result = subprocess.run(
            coverage_cmd,
            env=env,
            cwd=project_dir,
            check=False,
        )
        if result.returncode != 0:
            return result.returncode

        # Generate terminal report
        report_cmd = [
            sys.executable,
            "-m",
            "coverage",
            "report",
            "-m",
            f"--fail-under={config.fail_under}",
        ]
        print(f"[coverage] python -m coverage report -m --fail-under={config.fail_under}")

        report_result = subprocess.run(
            report_cmd,
            env=env,
            cwd=project_dir,
            check=False,
        )
        if report_result.returncode != 0:
            return report_result.returncode

        # Generate XML report for Codecov
        if generate_xml:
            xml_cmd = [
                sys.executable,
                "-m",
                "coverage",
                "xml",
                "-o",
                config.coverage_report_file,
            ]
            print(f"[coverage] python -m coverage xml -o {config.coverage_report_file}")

            xml_result = subprocess.run(
                xml_cmd,
                env=env,
                cwd=project_dir,
                check=False,
            )
            if xml_result.returncode != 0:
                print(
                    f"[coverage] warning: XML report generation failed (exit {xml_result.returncode})",
                    file=sys.stderr,
                )
                # Don't fail the whole run for XML generation failure

    return 0


# ---------------------------------------------------------------------------
# Codecov Token Management
# ---------------------------------------------------------------------------


def ensure_codecov_token(project_dir: Path | None = None) -> str | None:
    """Find and return codecov token without mutating os.environ.

    Checks the ``CODECOV_TOKEN`` environment variable first, then falls
    back to reading the ``.env`` file in *project_dir*.

    Args:
        project_dir: Directory containing .env file. Defaults to cwd.

    Returns:
        The token string if found, or ``None`` if unavailable.
    """
    existing = os.getenv("CODECOV_TOKEN")
    if existing:
        return existing
    if project_dir is None:
        project_dir = Path.cwd()
    env_path = project_dir / ".env"
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == "CODECOV_TOKEN":
            token = value.strip().strip("\"'")
            if token:
                return token
            break
    return None


# ---------------------------------------------------------------------------
# Git Utilities
# ---------------------------------------------------------------------------


def _resolve_commit_sha() -> str | None:
    """Resolve the current git commit SHA from environment or git."""
    sha = os.getenv("GITHUB_SHA")
    if sha:
        return sha.strip()
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    candidate = proc.stdout.strip()
    return candidate or None


def _resolve_git_branch() -> str | None:
    """Resolve the current git branch from environment or git."""
    branch = os.getenv("GITHUB_REF_NAME")
    if branch:
        return branch.strip()
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    candidate = proc.stdout.strip()
    if candidate in {"", "HEAD"}:
        return None
    return candidate


def _resolve_git_service(repo_host: str | None) -> str | None:
    """Map repository host to Codecov git service identifier.

    Args:
        repo_host: Repository host (e.g., 'github.com').

    Returns:
        Codecov service identifier or None.
    """
    host = (repo_host or "").lower()
    mapping = {
        "github.com": "github",
        "gitlab.com": "gitlab",
        "bitbucket.org": "bitbucket",
    }
    return mapping.get(host)


def _get_repo_slug(repo_owner: str | None, repo_name: str | None) -> str | None:
    """Get the repository slug (owner/name) if available.

    Args:
        repo_owner: Repository owner/organization.
        repo_name: Repository name.

    Returns:
        Slug in "owner/name" format, or None.
    """
    if repo_owner and repo_name:
        return f"{repo_owner}/{repo_name}"
    return None


def _get_repo_metadata_from_git() -> tuple[str | None, str | None, str | None]:
    """Extract repo metadata from git remote origin.

    Returns:
        Tuple of (host, owner, name) or (None, None, None).
    """
    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None, None, None

    url = proc.stdout.strip()
    # Handle SSH URLs: git@github.com:owner/repo.git
    if url.startswith("git@"):
        parts = url.split(":", 1)
        if len(parts) == 2:
            host = parts[0].replace("git@", "")
            path = parts[1].removesuffix(".git")
            path_parts = path.split("/")
            if len(path_parts) >= 2:
                return host, path_parts[0], path_parts[1]
    # Handle HTTPS URLs: https://github.com/owner/repo.git
    elif url.startswith("https://") or url.startswith("http://"):
        url_without_proto = url.split("://", 1)[1]
        parts = url_without_proto.removesuffix(".git").split("/")
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2]
    return None, None, None


# ---------------------------------------------------------------------------
# Codecov Upload
# ---------------------------------------------------------------------------


def upload_coverage_report(
    *,
    project_dir: Path | None = None,
    coverage_report_file: str = "coverage.xml",
    codecov_token: str | None = None,
) -> bool:
    """Upload coverage report via the official Codecov CLI when available.

    Args:
        project_dir: Project directory containing coverage report. Defaults to cwd.
        coverage_report_file: Name of the coverage report file.
        codecov_token: Codecov token to inject into the subprocess environment.
            When provided, avoids reliance on a globally-set environment variable.

    Returns:
        True if upload succeeded, False otherwise.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    uploader = _check_codecov_prerequisites(project_dir, coverage_report_file, codecov_token=codecov_token)
    if uploader is None:
        return False

    commit_sha = _resolve_commit_sha()
    if commit_sha is None:
        print("[codecov] Unable to resolve git commit; skipping upload", file=sys.stderr)
        return False

    # Get repo metadata from git
    repo_host, repo_owner, repo_name = _get_repo_metadata_from_git()

    args = _build_codecov_args(
        uploader=uploader,
        commit_sha=commit_sha,
        coverage_report_file=coverage_report_file,
        repo_host=repo_host,
        repo_owner=repo_owner,
        repo_name=repo_name,
    )
    env_overrides = _build_codecov_env(repo_owner, repo_name)

    # Build subprocess environment without mutating os.environ
    env = os.environ.copy()
    env.update(env_overrides)
    if codecov_token:
        env.setdefault("CODECOV_TOKEN", codecov_token)

    result = subprocess.run(
        args,
        env=env,
        check=False,
        cwd=project_dir,
    )
    return _handle_codecov_result(result.returncode)


def _check_codecov_prerequisites(
    project_dir: Path,
    coverage_report_file: str = "coverage.xml",
    *,
    codecov_token: str | None = None,
) -> str | None:
    """Check prerequisites for codecov upload, return uploader path or None.

    Args:
        project_dir: Project directory containing coverage report.
        coverage_report_file: Name of the coverage report file.
        codecov_token: Codecov token discovered by the caller.

    Returns:
        Path to codecovcli executable, or None if prerequisites not met.
    """
    report_path = project_dir / coverage_report_file
    if not report_path.is_file():
        print(f"[codecov] Coverage report not found: {report_path}")
        return None

    has_token = bool(codecov_token or os.getenv("CODECOV_TOKEN"))
    if not has_token and not os.getenv("CI"):
        print("[codecov] CODECOV_TOKEN not configured; skipping upload (set CODECOV_TOKEN or run in CI)")
        return None

    uploader = shutil.which("codecovcli")
    if uploader is None:
        print(
            "[codecov] 'codecovcli' not found; install with 'pip install codecov-cli' to enable uploads",
            file=sys.stderr,
        )
        return None

    return uploader


def _build_codecov_args(
    *,
    uploader: str,
    commit_sha: str,
    coverage_report_file: str = "coverage.xml",
    repo_host: str | None = None,
    repo_owner: str | None = None,
    repo_name: str | None = None,
) -> list[str]:
    """Build the codecov CLI arguments.

    Args:
        uploader: Path to codecovcli executable.
        commit_sha: Git commit SHA.
        coverage_report_file: Name of the coverage report file.
        repo_host: Repository host (e.g., 'github.com').
        repo_owner: Repository owner/organization.
        repo_name: Repository name.

    Returns:
        List of command-line arguments.
    """
    args = [
        uploader,
        "upload-coverage",
        "--file",
        coverage_report_file,
        "--disable-search",
        "--fail-on-error",
        "--sha",
        commit_sha,
        "--name",
        f"local-{platform.system()}-{platform.python_version()}",
        "--flag",
        "local",
    ]

    branch = _resolve_git_branch()
    if branch:
        args.extend(["--branch", branch])

    git_service = _resolve_git_service(repo_host)
    if git_service:
        args.extend(["--git-service", git_service])

    slug = _get_repo_slug(repo_owner, repo_name)
    if slug:
        args.extend(["--slug", slug])

    return args


def _build_codecov_env(repo_owner: str | None, repo_name: str | None) -> dict[str, str]:
    """Build environment overrides for codecov upload.

    Args:
        repo_owner: Repository owner/organization.
        repo_name: Repository name.

    Returns:
        Dictionary of environment variable overrides.
    """
    env_overrides: dict[str, str] = {"CODECOV_NO_COMBINE": "1"}
    slug = _get_repo_slug(repo_owner, repo_name)
    if slug:
        env_overrides["CODECOV_SLUG"] = slug
    return env_overrides


def _handle_codecov_result(exit_code: int) -> bool:
    """Handle the codecov upload result.

    Args:
        exit_code: Exit code from codecov CLI.

    Returns:
        True if upload succeeded, False otherwise.
    """
    if exit_code == 0:
        print("[codecov] upload succeeded")
        return True
    print(f"[codecov] upload failed (exit {exit_code})", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def main(
    *,
    project_dir: Path | None = None,
    run_tests: bool = False,
    upload: bool = True,
    verbose: bool = False,
    include_integration: bool = False,
) -> int:
    """Main entry point for coverage operations.

    Args:
        project_dir: Project directory. Defaults to cwd.
        run_tests: Run pytest with coverage before uploading.
        upload: Upload coverage to Codecov after running tests.
        verbose: Enable verbose output.
        include_integration: Include integration tests (excluded by default).

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    if project_dir is None:
        project_dir = Path.cwd()

    # Run tests with coverage if requested
    if run_tests:
        print(f"[coverage] Running tests with coverage in {project_dir}...")
        exit_code = run_coverage_tests(
            project_dir=project_dir,
            verbose=verbose,
            include_integration=include_integration,
        )
        if exit_code != 0:
            print(f"[coverage] Tests failed (exit {exit_code})", file=sys.stderr)
            return exit_code
        print("[coverage] Tests passed")

    # Upload coverage if requested
    if upload:
        print(f"[codecov] Uploading coverage from {project_dir}...")

        # Discover token without mutating global environment
        token = ensure_codecov_token(project_dir)

        # Upload coverage
        success = upload_coverage_report(project_dir=project_dir, codecov_token=token)
        if not success:
            return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Run tests with coverage and upload to Codecov",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run tests with coverage and upload (excludes integration tests)
  python _coverage.py --run --project-dir /path/to/project

  # Run all tests including integration tests
  python _coverage.py --run --integration --project-dir /path/to/project

  # Upload existing coverage.xml only
  python _coverage.py --project-dir /path/to/project

  # Run tests only, skip upload
  python _coverage.py --run --no-upload --project-dir /path/to/project
""",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory containing pyproject.toml (default: cwd)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run pytest with coverage before uploading",
    )
    parser.add_argument(
        "--integration",
        action="store_true",
        help="Include integration tests (excluded by default)",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip uploading coverage to Codecov",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )
    args, _unknown = parser.parse_known_args()
    sys.exit(
        main(
            project_dir=args.project_dir,
            run_tests=args.run,
            upload=not args.no_upload,
            verbose=args.verbose,
            include_integration=args.integration,
        )
    )
