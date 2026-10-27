"""Create git tags and GitHub releases for versioned deployments.

Purpose
-------
Self-contained release orchestrator for the stagerunner pipeline. Reads the
project version from ``pyproject.toml``, validates the working tree, creates
an annotated git tag, pushes to the remote, and optionally creates a GitHub
release via the ``gh`` CLI.

Contents
--------
* ``release`` - Orchestrate the full release flow.
* ``main`` - Main entry point for standalone execution.

System Role
-----------
Development automation helper executed by ``rel_020_release.sh`` inside the
stagerunner pipeline. Uses ``_toml_config`` for pyproject parsing and
``subprocess.run`` for all git/gh operations - no external script imports.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from bmk.adapters.stagerunner.helpers._plugin_manifest import PluginManifest, PluginManifestError
from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config
from bmk.domain.version import version_problem

if TYPE_CHECKING:
    from bmk.adapters.stagerunner.helpers._toml_config import PyprojectConfig

__all__ = [
    "cmd_exists",
    "ensure_clean",
    "get_default_remote",
    "gh_available",
    "gh_release_create",
    "gh_release_edit",
    "gh_release_exists",
    "git_branch",
    "git_create_annotated_tag",
    "git_push",
    "git_tag_exists",
    "main",
    "release",
    "run",
    "shipped_skill_needs_a_bump",
]


# ---------------------------------------------------------------------------
# Git / GitHub helpers (self-contained, no script imports)
# ---------------------------------------------------------------------------


def run(args: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command."""
    return subprocess.run(args, check=check, capture_output=capture, text=True)


def cmd_exists(name: str) -> bool:
    """Check if an executable exists on PATH."""
    return shutil.which(name) is not None


def git_branch() -> str:
    """Get the current git branch name."""
    result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)
    return result.stdout.strip()


def git_tag_exists(name: str) -> bool:
    """Check if a git tag exists locally."""
    result = run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{name}"], check=False, capture=True)
    return result.returncode == 0


def git_create_annotated_tag(name: str, message: str) -> None:
    """Create an annotated git tag."""
    run(["git", "tag", "-a", name, "-m", message])


def git_push(remote: str, ref: str) -> None:
    """Push a ref to a remote repository."""
    run(["git", "push", remote, ref])


def gh_available() -> bool:
    """Check if the GitHub CLI (gh) is available."""
    return cmd_exists("gh")


def gh_release_exists(tag: str) -> bool:
    """Check if a GitHub release exists for the given tag."""
    result = run(["gh", "release", "view", tag], check=False, capture=True)
    return result.returncode == 0


def gh_release_create(tag: str, title: str, body: str) -> None:
    """Create a new GitHub release."""
    run(["gh", "release", "create", tag, "-t", title, "-n", body], check=False)


def gh_release_edit(tag: str, title: str, body: str) -> None:
    """Edit an existing GitHub release."""
    run(["gh", "release", "edit", tag, "-t", title, "-n", body], check=False)


def ensure_clean() -> None:
    """Ensure the git working tree has no uncommitted changes."""
    unstaged = run(["git", "diff", "--quiet"], check=False, capture=True)
    staged = run(["git", "diff", "--cached", "--quiet"], check=False, capture=True)
    if unstaged.returncode != 0 or staged.returncode != 0:
        print("[release] Working tree not clean. Commit or stash changes first.", file=sys.stderr)
        raise SystemExit(1)


def get_default_remote(config: PyprojectConfig) -> str:
    """Read default git remote from pyproject.toml [tool.git].default-remote.

    Falls back to "origin" if not configured (absent, blank, or not a string).
    """
    return config.tool.git.default_remote or "origin"


# ---------------------------------------------------------------------------
# Release orchestration
# ---------------------------------------------------------------------------


def _git_output(project_dir: Path, *args: str) -> str | None:
    """Return a git command's stdout, or None when git cannot answer."""
    try:
        done = subprocess.run(["git", *args], cwd=str(project_dir), capture_output=True, text=True, check=False)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


class PluginVersionPair(NamedTuple):
    """The plugin manifest's version at the previous tag and on disk now.

    Named fields because both are plain strings: positionally, swapping them would
    still type-check and the refusal message would quote the old version as current.

    Attributes:
        at_tag: The version ``.claude-plugin/plugin.json`` held at the previous tag.
        on_disk: The version it holds in the working tree.
    """

    at_tag: str
    on_disk: str


def _plugin_version_pair(project_dir: Path, plugin_path: Path, previous_tag: str) -> PluginVersionPair | None:
    """Return the plugin version at ``previous_tag`` and the one on disk now.

    None when either cannot be read - the manifest is newer than the tag, or one side
    is not a JSON object - because there is then no honest comparison to make.

    Args:
        project_dir: The repository the tag belongs to.
        plugin_path: The working-tree ``.claude-plugin/plugin.json``.
        previous_tag: The tag of the previous release.

    Returns:
        Both versions, or None when either side cannot be read.
    """
    old_blob = _git_output(project_dir, "show", f"{previous_tag}:.claude-plugin/plugin.json")
    if old_blob is None:
        return None
    try:
        was = PluginManifest.from_json(old_blob).version
        now = PluginManifest.from_json(plugin_path.read_text(encoding="utf-8")).version
    except (OSError, json.JSONDecodeError, PluginManifestError):
        return None
    return PluginVersionPair(at_tag=was, on_disk=now)


def shipped_skill_needs_a_bump(project_dir: Path) -> str | None:
    """Return why the release must stop, or None when it may proceed.

    A repo that ships a Claude Code skill publishes it through its own marketplace,
    and an install re-fetches only when ``.claude-plugin/plugin.json`` changes version.
    So a release that edits ``skills/`` without moving that version ships the code and
    leaves every install on the old skill - no error, nothing to notice, and the skill
    then documents behaviour the tool no longer has.

    The version sync raises the plugin version to the package version, which covers
    almost every case. It cannot cover one: when the two are already equal there is
    nothing to raise, and the skill edit would ship unannounced. That is what this
    catches.

    Silent (returns None) when there is nothing to judge: no plugin manifest, no
    skills dir, no git, no previous tag, or the skill was not touched.
    """
    plugin_path = project_dir / ".claude-plugin" / "plugin.json"
    if not plugin_path.exists() or not (project_dir / "skills").is_dir():
        return None

    previous_tag = (_git_output(project_dir, "describe", "--tags", "--abbrev=0") or "").strip()
    if not previous_tag:
        return None  # first release: nothing to have drifted from

    changed = (_git_output(project_dir, "diff", "--name-only", f"{previous_tag}..HEAD", "--", "skills") or "").strip()
    versions = _plugin_version_pair(project_dir, plugin_path, previous_tag) if changed else None
    if versions is None or versions.at_tag != versions.on_disk:
        return None

    files = ", ".join(sorted(changed.split())[:3])
    return (
        f"skills/ changed since {previous_tag} ({files}) but .claude-plugin/plugin.json is still {versions.on_disk}. "
        "An install re-fetches a skill only when that version changes, so this release would "
        "ship the code and leave every install on the old skill. Bump the plugin version "
        "(semver) and commit it, then release again."
    )


def release(*, project_dir: Path, remote: str | None = None) -> int:
    """Create a versioned release with git tag and GitHub release.

    Args:
        project_dir: Root directory of the project.
        remote: Git remote name. Auto-detected from pyproject.toml if not given.

    Returns:
        Exit code (0 on success).
    """
    pyproject_path = project_dir / "pyproject.toml"
    config = load_pyproject_config(pyproject_path)

    version = config.project.version
    problem = version_problem(version)
    if problem is not None:
        print(f"[release] pyproject.toml version: {problem}", file=sys.stderr)
        return 1

    stale_skill = shipped_skill_needs_a_bump(project_dir)
    if stale_skill is not None:
        print(f"[release] {stale_skill}", file=sys.stderr)
        return 1

    if remote is None:
        remote = get_default_remote(config)

    print(f"[release] Target version {version}")
    print(f"[release] Remote: {remote}")

    ensure_clean()

    # Push branch
    branch = git_branch()
    if branch == "HEAD":
        # rev-parse --abbrev-ref answers the literal "HEAD" when detached; pushing that ref
        # fails only after the tag exists locally, so refuse before anything is created.
        print(
            "[release] HEAD is detached: check out the branch to release (a clean "
            "`git worktree add <path> <branch>` works when the main checkout is busy).",
            file=sys.stderr,
        )
        return 1
    print(f"[release] Pushing branch {branch} to {remote}")
    git_push(remote, branch)

    # Tag and push
    tag = f"v{version}"
    if git_tag_exists(tag):
        print(f"[release] Tag {tag} already exists locally")
    else:
        git_create_annotated_tag(tag, f"Release {tag}")
    print(f"[release] Pushing tag {tag}")
    git_push(remote, tag)

    # Create or edit GitHub release
    if gh_available():
        if gh_release_exists(tag):
            gh_release_edit(tag, tag, f"Release {tag}")
        else:
            print(f"[release] Creating GitHub release {tag}")
            gh_release_create(tag, tag, f"Release {tag}")
    else:
        print("[release] gh CLI not found; skipping GitHub release creation")

    print(f"[release] Done: {tag} tagged and pushed.")
    return 0


def main(*, project_dir: Path, remote: str | None = None) -> int:
    """Main entry point for release utility.

    Args:
        project_dir: Root directory of the project.
        remote: Git remote name override.

    Returns:
        Exit code (0 on success).
    """
    return release(project_dir=project_dir, remote=remote)


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Create git tags and GitHub releases")
    parser.add_argument(
        "--project-dir",
        type=Path,
        required=True,
        help="Project root directory",
    )
    parser.add_argument(
        "--remote",
        type=str,
        default=None,
        help="Git remote name (default: auto-detect from pyproject.toml or 'origin')",
    )
    args, _unknown = parser.parse_known_args()
    sys.exit(main(project_dir=args.project_dir, remote=args.remote))
