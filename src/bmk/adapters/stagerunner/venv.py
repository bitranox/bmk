"""Resolve, create and sync the target project's virtual environment.

bmk's gates only tell the truth if the interpreter they inspect matches the
project's ``pyproject.toml``. This module is the single source of truth for two
questions: *which* venv is the project's, and *is it current*.

Provisioning runs before the pipeline starts (see
:func:`bmk.adapters.cli.commands._shared.run_command`), not as a stage. That is a
hard requirement, not a preference: :func:`context.build_context` pins
``VIRTUAL_ENV`` / ``PIPAPI_PYTHON_LOCATION`` once, up front, and ``StageContext``
is frozen, so a venv created by a stage could not repair the pins for the stages
that follow it in the same run.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from bmk.adapters.stagerunner.helpers import _typed_tomlkit
from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config

# Sync targets, tried in order: a project with no ``[dev]`` extra (bmk itself is
# one - all its tooling is a runtime dependency by design) must still sync.
# Mirrors the fallback chain in ``src/bmk/makefile/Makefile``.
_INSTALL_TARGETS: tuple[str, ...] = (".[dev]", ".")


def resolve_project_venv(cwd: Path, env: Mapping[str, str]) -> Path:
    """Path of the project's venv.

    Honours uv's ``UV_PROJECT_ENVIRONMENT`` (absolute, or relative to ``cwd``)
    rather than hardcoding ``.venv``. A tree shared between OSes cannot use one
    venv path for both: on the bitranox softdev mount ``.venv`` is the Linux venv
    and Windows points ``UV_PROJECT_ENVIRONMENT`` at ``.venv-win``, so syncing
    ``.venv`` from Windows would rebuild it and break the Linux side.
    """
    configured = env.get("UV_PROJECT_ENVIRONMENT", "").strip()
    if not configured:
        return cwd / ".venv"
    candidate = Path(configured)
    return candidate if candidate.is_absolute() else cwd / candidate


def venv_python(venv: Path) -> Path:
    """Interpreter inside ``venv`` for the current OS."""
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


_PY_CLASSIFIER = "Programming Language :: Python :: "


def all_python_minors(cwd: Path) -> list[str]:
    """Every ``X.Y`` the project's Python classifiers declare, ascending numerically.

    The trove classifiers are the only place a project states which Python versions it
    supports; ``requires-python`` is a floor and names none of them. This reads the SAME key
    the CI workflow parses for its test matrix (``Programming Language :: Python :: X.Y``,
    dotted entries only - a bare ``:: Python :: 3`` is skipped), so the local matrix
    (``test-all``) and the CI matrix cannot disagree about which versions are supported.

    Sorted numerically, not lexically: as strings ``"3.9" > "3.14"``, which is backwards.

    Returns ``[]`` when the project declares nothing or cannot be read - a degrade, never a
    raise, since provisioning is best-effort.
    """
    manifest = cwd / "pyproject.toml"
    if not manifest.is_file():
        return []
    try:
        config = load_pyproject_config(manifest)
    except Exception:  # an unreadable manifest degrades, never aborts
        return []

    found: list[tuple[tuple[int, ...], str]] = []
    for classifier in config.project.classifiers:
        if not classifier.startswith(_PY_CLASSIFIER):
            continue
        version = classifier[len(_PY_CLASSIFIER) :].strip()
        if "." not in version:
            continue
        try:
            parts = tuple(int(p) for p in version.split("."))
        except ValueError:
            continue
        found.append((parts, version))
    return [version for _, version in sorted(found)]


def desired_python_minor(cwd: Path) -> str | None:
    """Highest ``X.Y`` the project's Python classifiers declare, or None.

    The single newest version, used to build the default ``.venv``. It is exactly the last
    of :func:`all_python_minors`; the two never disagree. See that function for why the
    classifiers (not ``requires-python``) are the source and why the order is numeric.
    """
    minors = all_python_minors(cwd)
    return minors[-1] if minors else None


def latest_installed_patch(minor: str, cwd: Path) -> str | None:
    """Newest installed patch of ``minor`` (e.g. ``3.14`` -> ``3.14.5``), or None.

    Asks uv rather than reading its store layout. ``uv python find`` is NOT usable for
    this: it answers with the interpreter for the current CONTEXT (an active venv, or the
    cwd's own ``.venv``), not the one uv would provision.
    """
    raw = _run_capture(["uv", "python", "list", "--only-installed", "--output-format", "json"], cwd)
    if not raw:
        return None
    try:
        entries = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(entries, list):
        return None

    best: tuple[int, str] | None = None
    for entry in cast("list[dict[str, Any]]", entries):
        parts = entry.get("version_parts")
        version = entry.get("version")
        if not isinstance(parts, dict) or not isinstance(version, str):
            continue
        typed = cast("dict[str, Any]", parts)
        if f"{typed.get('major')}.{typed.get('minor')}" != minor:
            continue
        patch = typed.get("patch")
        if not isinstance(patch, int):
            continue
        if best is None or patch > best[0]:
            best = (patch, version)
    return best[1] if best else None


_VERSION_PROBE = "import sys; print('.'.join(map(str, sys.version_info[:3])))"


def venv_version(venv: Path) -> str | None:
    """``X.Y.Z`` the venv's interpreter ACTUALLY reports, or None.

    Deliberately NOT ``pyvenv.cfg``'s ``version_info``: that text is written once, at
    creation, and then goes stale. uv builds a venv against the MINOR alias
    (``.../cpython-3.12-linux.../bin``), so ``uv python upgrade 3.12`` migrates the venv onto
    the new patch simply by moving what that alias resolves to - the interpreter becomes
    3.12.13 while ``version_info`` still reads 3.12.12. Measured, both halves:

        venv on the 3.12 alias   -> pyvenv.cfg 3.12.12, interpreter 3.12.12
        uv python upgrade 3.12   -> installs 3.12.13, repoints the alias
        same venv, untouched     -> pyvenv.cfg 3.12.12, interpreter 3.12.13

    Trusting the text would rebuild a venv uv had ALREADY upgraded: a full re-resolve, in
    every repo, on every patch release, for nothing. It also inverts the design - because
    ``upgrade`` migrates alias-built venvs by itself, a new patch needs no rebuild at all
    and only a MINOR change does. Asking the interpreter costs one subprocess and is true in
    both directions.
    """
    python = venv_python(venv)
    if not python.is_file():
        return None
    raw = _run_capture([str(python), "-c", _VERSION_PROBE], venv.parent)
    return raw.strip() or None if raw else None


def is_venv(venv: Path) -> bool:
    """Whether ``venv`` is a usable virtual environment.

    ``pyvenv.cfg`` is the marker: a bare directory that merely shares the name is
    not a venv, and pinning tools at one would point them at nothing.
    """
    return venv.is_dir() and (venv / "pyvenv.cfg").is_file()


def _run(argv: list[str], cwd: Path, *, quiet: bool) -> int:
    """Run ``argv`` in ``cwd``, silencing output when quiet."""
    output = subprocess.DEVNULL if quiet else None
    try:
        # argv is built from literals and a resolved path, never from user
        # input, and runs without a shell.
        return subprocess.run(argv, cwd=cwd, stdout=output, stderr=output, check=False).returncode
    except OSError:
        # uv missing from PATH. Degrade to the caller's fallback rather than
        # breaking a run that may not have needed the venv at all.
        return 1


def _run_capture(argv: list[str], cwd: Path) -> str | None:
    """Run ``argv`` in ``cwd`` and return stdout, or None if it could not run."""
    try:
        # argv is built from literals; no shell, no user input.
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _git(argv: list[str], cwd: Path) -> tuple[int, str]:
    """Run a git command in ``cwd``, returning (exit code, stdout)."""
    try:
        result = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError:
        return 1, ""
    return result.returncode, result.stdout


def _is_git_worktree(cwd: Path) -> bool:
    """Whether ``cwd`` sits inside a git work tree."""
    code, out = _git(["rev-parse", "--is-inside-work-tree"], cwd)
    return code == 0 and out.strip() == "true"


def _untrack(cwd: Path, name: str) -> bool:
    """Drop ``name`` from the index if git tracks it, keeping it on disk.

    A tracked venv is not a cosmetic problem: the sync rewrites its contents on
    every run, so git would see thousands of modified files each time and any
    commit would sweep them in.

    Returns:
        True if something was untracked.
    """
    code, out = _git(["ls-files", "--", name], cwd)
    if code != 0 or not out.strip():
        return False
    count = len(out.strip().splitlines())
    if _git(["rm", "-r", "--cached", "--quiet", "--", name], cwd)[0] != 0:
        return False
    # Announce unconditionally, never gated on quiet: this stages deletions in
    # the user's index, and `push` commits automatically.
    print(f"[bmk] untracked {count} file(s) under '{name}' (kept on disk; the deletion is staged)")
    return True


_VENV_GLOB = ".venv*"
# A synthetic name ONLY the `.venv*` glob covers - not the old literal `.venv/`. `git
# check-ignore` needs a concrete path, not a pattern, so probing this is how we ask "is the
# glob declared" without matching a stale literal.
_VENV_IGNORE_PROBE = ".venv-bmkignoreprobe"


def _ignore_entries(cwd: Path, venv: Path) -> list[str]:
    """Names to gitignore: one ``.venv*`` glob, plus a non-matching custom venv path.

    A single ``.venv*`` covers ``.venv``, ``.venv-win`` (the Windows sibling on a
    cross-OS checkout), ``.venv-bmk`` (the Makefile's own bmk env), and every
    ``.venv-<minor>`` the version matrix creates - so the matrix needs no per-version line.

    A venv placed OUTSIDE that pattern via ``UV_PROJECT_ENVIRONMENT`` (e.g. ``env``) is not
    covered by the glob, so its own name is added too.
    """
    entries = [_VENV_GLOB]
    try:
        managed = venv.resolve().relative_to(cwd.resolve()).parts[0]
    except ValueError:
        return entries  # venv lives outside the repo; the glob is all that is relevant
    if not fnmatch.fnmatch(managed, _VENV_GLOB):
        entries.append(managed)
    return entries


def _is_declared(cwd: Path, name: str) -> bool:
    """Whether the REPOSITORY's own rules ignore ``name``.

    Not simply "is this path ignored": ``uv venv`` drops a ``.gitignore``
    containing ``*`` INSIDE every venv it creates, so a uv-made venv reports as
    ignored by its own nested file. That is uv hiding its artifact, not the repo
    declaring the name, and treating it as declared would leave ``.venv``
    undeclared while its ``.venv-win`` sibling got written - the names applied
    inconsistently across repos.

    ``check-ignore -v`` reports ``<source>:<line>:<pattern>\\t<path>``, so the
    source file tells the two apart.

    Queried with a trailing slash: a ``dir/`` rule only matches a path git knows
    is a directory, which it cannot for one that does not exist yet.
    """
    code, out = _git(["check-ignore", "-v", "--", f"{name}/"], cwd)
    if code != 0 or not out.strip():
        return False
    source = out.split(":", 1)[0]
    return not source.startswith(f"{name}/")


def _append_to_gitignore(cwd: Path, missing: list[str]) -> None:
    """Append ``missing`` entries to .gitignore under a labelled section."""
    gitignore = cwd / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    block = "\n# Python virtual environments (managed by bmk)\n" + "".join(f"{n}/\n" for n in missing)
    gitignore.write_text(existing + prefix + block, encoding="utf-8")
    print(f"[bmk] added to .gitignore: {', '.join(missing)}")


def _covered(cwd: Path, name: str) -> bool:
    """Whether the repo already ignores ``name``.

    For the ``.venv*`` glob, ``git check-ignore`` cannot be asked about a pattern - only a
    concrete path - so a synthetic probe name only the glob covers stands in for it. A stale
    literal ``.venv/`` does NOT match the probe, so the glob is still (correctly) added.
    """
    probe = _VENV_IGNORE_PROBE if name == _VENV_GLOB else name
    return _is_declared(cwd, probe)


def ensure_venv_ignored(cwd: Path, venv: Path) -> None:
    """Keep every venv out of git: untrack any tracked one, gitignore via a ``.venv*`` glob.

    bmk creates these directories, so bmk is responsible for them not polluting the
    repository. Never raises: a git problem must not fail a build.
    """
    if not _is_git_worktree(cwd):
        return

    entries = _ignore_entries(cwd, venv)
    for name in entries:
        _untrack(cwd, name)  # `.venv*` untracks every venv in one pass (git glob pathspec)

    # git decides what is already covered, so an existing rule - a wildcard, a nested
    # .gitignore, a global excludesFile - is respected rather than duplicated.
    missing = [n for n in entries if not _covered(cwd, n)]
    if missing:
        _append_to_gitignore(cwd, missing)


def _pyright_covers(name: str, patterns: list[str]) -> bool:
    """Whether any of pyright's ``exclude`` ``patterns`` already keeps ``name`` out.

    pyright accepts several spellings for the same directory (``.venv``,
    ``.venv/``, ``**/.venv``, ``**/.venv/**``) and one wildcard - ``**/.*``, its
    own default - that covers every dot-directory at once. All of them must count
    as covered, or the exclude list grows by a duplicate entry on every run.
    """
    for raw in patterns:
        # Only a trailing "/**" or "/" is noise ("**/.venv/**" and ".venv/" both
        # mean the directory). Stripping "*" generally would maul "**/.*" into
        # "**/." and miss pyright's own default.
        pattern = raw[:-3] if raw.endswith("/**") else raw
        pattern = pattern.rstrip("/")
        if pattern in (name, f"**/{name}"):
            return True
        # fnmatch has no concept of "**", so a leading "**/" is matched by
        # comparing the bare name against the remainder: "**/.*" -> ".*".
        bare = pattern[3:] if pattern.startswith("**/") else pattern
        if fnmatch.fnmatch(name, bare):
            return True
    return False


def ensure_venv_typecheck_excluded(cwd: Path, venv: Path) -> None:
    """Keep bmk's venvs out of the project's pyright run.

    pyright's ``exclude`` REPLACES its built-in defaults (``**/node_modules``,
    ``**/__pycache__``, ``**/.*``) instead of extending them. So any project that
    lists an exclude of its own silently loses ``**/.*``, the rule that kept
    dot-directories out. That cost nothing until bmk started creating ``.venv``
    and ``.venv-bmk`` inside the project; now pyright walks thousands of
    site-packages files in strict mode and effectively never returns - a run
    measured at 6h20m of spin with no output and no error explaining it.

    bmk creates the directories, so bmk excludes them, exactly as it gitignores
    them (:func:`ensure_venv_ignored`).

    Two cases are deliberately left untouched:

    * **No ``exclude`` key.** pyright's defaults are in force and ``**/.*``
      already covers every venv here. Writing an exclude list would REPLACE those
      defaults - it would cause the very bug it is meant to prevent.
    * **An ``include`` list.** pyright then only walks those paths, so a venv
      outside them is never reached.

    Never raises: a malformed or unreadable pyproject.toml must not fail a build
    that may not even use the type-checker.
    """
    pyproject = cwd / "pyproject.toml"
    if not pyproject.is_file():
        return
    try:
        document = _typed_tomlkit.parse(pyproject.read_text(encoding="utf-8"))
    except (OSError, ValueError, _typed_tomlkit.TOMLKitError):
        return

    tool: Mapping[str, Any] = document.get("tool", {})
    pyright: Mapping[str, Any] | None = tool.get("pyright")
    if pyright is None or "exclude" not in pyright or pyright.get("include"):
        return

    if not isinstance(pyright["exclude"], list):
        return  # not a list; not ours to interpret
    # Cast, never copy: this must stay the tomlkit array that belongs to the
    # document, or appending would mutate a throwaway and write back the original.
    excludes = cast("list[Any]", pyright["exclude"])
    current = [str(item) for item in excludes]

    missing = [name for name in _ignore_entries(cwd, venv) if not _pyright_covers(name, current)]
    if not missing:
        return

    for name in missing:
        excludes.append(name)
    try:
        pyproject.write_text(_typed_tomlkit.dumps(document), encoding="utf-8")
    except OSError:
        return
    # Announce unconditionally: this edits the user's pyproject.toml, and `push`
    # commits automatically.
    print(f"[bmk] excluded from pyright: {', '.join(missing)} (its 'exclude' replaces the **/.* default)")


def _ensure_minor_installed(minor: str, cwd: Path, *, quiet: bool) -> None:
    """Make ``minor`` available to uv at its latest patch.

    BOTH commands are needed, and neither substitutes for the other:

    * ``uv python install`` covers a minor that is not present at all - the classifiers can
      change (a project adds ``:: Python :: 3.15``) and the version must then be fetched.
    * ``uv python upgrade`` covers a minor that IS present but behind on patches. ``install``
      will NOT do this: given an installed 3.14.0 it reports "Installed Python 3.14.0" and
      keeps the stale one (measured), which is how every venv on a box can sit on 3.14.0
      while 3.14.5 is a download away.

    Both are best-effort: a failure leaves uv's own interpreter choice in place rather than
    breaking a command that may not have needed a new Python at all. When already current
    this costs ~0.1s and works offline ("already on the latest supported patch release").
    """
    _run(["uv", "python", "install", minor], cwd, quiet=quiet)
    _run(["uv", "python", "upgrade", minor], cwd, quiet=quiet)


def _discard_venv_on_wrong_python(venv: Path, minor: str | None, cwd: Path, *, quiet: bool) -> None:
    """Remove an existing venv built on the wrong Python, so it gets recreated.

    A venv's interpreter cannot be upgraded in place, so matching the declared version means
    rebuilding. The path does not change, so the pins derived from it stay valid - and this
    runs before ``build_context`` freezes them.

    Only fires on a real mismatch against a target uv actually reports; if uv cannot answer
    (offline, absent, unexpected output) the existing venv is left exactly as it was. The
    rebuild costs a full re-resolve, so it must never be triggered by a guess.
    """
    if not minor or not is_venv(venv):
        return
    target = latest_installed_patch(minor, cwd)
    current = venv_version(venv)
    if not target or not current or current == target:
        return
    if not quiet:
        print(f"[venv] python {current} -> {target}: rebuilding {venv.name}")
    shutil.rmtree(venv, ignore_errors=True)


def ensure_project_venv(cwd: Path, env: Mapping[str, str], *, quiet: bool = True) -> Path | None:
    """Create the project venv if absent, then sync it to ``pyproject.toml``.

    An existing venv is updated in place, so its path - and therefore the pins
    derived from it - stay stable across the run. The one exception is the Python
    version: an interpreter cannot be upgraded in place, so a venv built on a
    version other than the one the project's classifiers declare is rebuilt at the
    same path (see ``_discard_venv_on_wrong_python``). That happens here, before
    ``build_context`` freezes the pins, so nothing downstream sees a stale path.

    The sync needs ``--exact`` *and* ``--upgrade``; either alone leaves the venv
    lying about what the project resolves, in a different way:

    * ``--exact`` removes packages the manifest no longer asks for. Without it, a
      dropped dependency lingers and pip-audit reports CVEs against a package the
      project does not actually resolve.
    * ``--upgrade`` re-resolves packages that are already installed. Without it,
      uv keeps any installed version that still satisfies its constraint, so a
      stale *unconstrained* transitive (``setuptools`` via ``pbr``, say) never
      moves off a vulnerable release even though a fresh resolution would pick the
      fixed one.

    The trade-off is that packages installed into the venv by hand do not survive
    a sync.

    ``--exact`` also removes ``pip`` (a uv-created venv ships none anyway); the
    ``pip_audit`` stage bootstraps a current pip into the resolved interpreter
    before every audit, so that repairs itself.

    Because bmk creates this directory, it also keeps it out of git
    (``ensure_venv_ignored``).

    Returns:
        The venv path, or ``None`` if it could not be provisioned. Never raises:
        a provisioning failure must degrade to bmk's previous behaviour (gates
        run against bmk's own interpreter), not abort the command.
    """
    if not (cwd / "pyproject.toml").is_file():
        return None
    venv = resolve_project_venv(cwd, env)
    return ensure_project_venv_at(cwd, venv, desired_python_minor(cwd), quiet=quiet)


def ensure_project_venv_at(cwd: Path, venv: Path, minor: str | None, *, quiet: bool = True) -> Path | None:
    """Provision a venv at an EXPLICIT path on an EXPLICIT Python minor, then sync it.

    The building block behind both the default ``.venv`` (via :func:`ensure_project_venv`,
    ``minor`` = the highest classifier) and the per-version matrix (``test-all`` calls this
    once per declared minor with ``venv = .venv-<minor>``). Every step is a pure function of
    ``(venv, minor)``, so nothing here assumes the default path or the newest version.

    ``minor=None`` means "no declared version": uv's own interpreter choice stands and no
    ``--python`` pin is passed - the historical default-venv behaviour.

    The sync needs ``--exact`` AND ``--upgrade``; each covers a distinct way a venv drifts
    (a dropped dep lingering; an unconstrained transitive never moving off a vulnerable
    release). Packages installed by hand do not survive it. See :func:`ensure_project_venv`.

    Returns the venv path, or ``None`` if it could not be provisioned. Never raises: a
    failure degrades rather than aborting the command.
    """
    if minor:
        _ensure_minor_installed(minor, cwd, quiet=quiet)
    _discard_venv_on_wrong_python(venv, minor, cwd, quiet=quiet)

    create = ["uv", "venv", *(["--python", minor] if minor else []), str(venv)]
    if not is_venv(venv) and _run(create, cwd, quiet=quiet) != 0:
        return None
    if not is_venv(venv):
        return None

    ensure_venv_ignored(cwd, venv)
    ensure_venv_typecheck_excluded(cwd, venv)

    python = venv_python(venv)
    for target in _INSTALL_TARGETS:
        argv = ["uv", "pip", "install", "--python", str(python), "--exact", "--upgrade", "-e", target]
        if _run(argv, cwd, quiet=quiet) == 0:
            return venv
    return None
