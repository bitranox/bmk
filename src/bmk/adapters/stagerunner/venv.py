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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from filelock import FileLock, Timeout
from pydantic import BaseModel, ConfigDict, ValidationError

from bmk.adapters.stagerunner.helpers import _typed_tomlkit
from bmk.adapters.stagerunner.helpers._toml_config import load_pyproject_config

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

# Sync targets, tried in order: a project with no ``[dev]`` extra (bmk itself is
# one - all its tooling is a runtime dependency by design) must still sync.
# Mirrors the fallback chain in ``src/bmk/makefile/Makefile``.
_INSTALL_TARGETS: tuple[str, ...] = (".[dev]", ".")

#: How long a bmk waits for another bmk to finish mutating the same venv. Generous,
#: because the thing being waited on is a full resolve-and-install on a cold start,
#: which is minutes on a heavy dependency tree. Overridable for tests and for a
#: caller that would rather fail fast.
_LOCK_TIMEOUT_ENV = "BMK_VENV_LOCK_TIMEOUT"
#: Where the lock files live; overridable so a test never touches the real one.
_LOCK_DIR_ENV = "BMK_VENV_LOCK_DIR"
_DEFAULT_LOCK_TIMEOUT = 600.0


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

    return list(config.project.python_minors())


def desired_python_minor(cwd: Path) -> str | None:
    """Highest ``X.Y`` the project's Python classifiers declare, or None.

    The single newest version, used to build the default ``.venv``. It is exactly the last
    of :func:`all_python_minors`; the two never disagree. See that function for why the
    classifiers (not ``requires-python``) are the source and why the order is numeric.
    """
    minors = all_python_minors(cwd)
    return minors[-1] if minors else None


class _UvVersionParts(BaseModel):
    """The ``version_parts`` object of one ``uv python list`` JSON entry."""

    model_config = ConfigDict(extra="ignore")

    major: int
    minor: int
    patch: int


class _UvPythonEntry(BaseModel):
    """One entry of ``uv python list --output-format json``.

    Only the fields this module needs are declared; ``extra="ignore"`` drops the
    rest (``key``, ``path``, ...). An entry that lacks these or types them oddly
    fails validation and is skipped, exactly as the previous hand-written guards did.

    ``implementation`` matters: several implementations (CPython, PyPy, ...) can be
    installed for the same ``X.Y``. ``uv venv --python <minor>`` provisions CPython, so
    the patch comparison must only consider CPython - otherwise a PyPy build whose patch
    happens to exceed the installed CPython's would be reported as "newest", never match
    the CPython venv, and rebuild it on every run.
    """

    model_config = ConfigDict(extra="ignore")

    version: str
    version_parts: _UvVersionParts
    implementation: str
    path: str | None = None
    variant: str = "default"
    key: str = ""

    @property
    def is_default_build(self) -> bool:
        """The build ``uv python install X.Y`` installs; older uv lists no ``variant``, only the key."""
        return self.variant == "default" and "+freethreaded" not in self.key


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
    for raw_entry in cast("list[Any]", entries):
        try:
            entry = _UvPythonEntry.model_validate(raw_entry)
        except ValidationError:
            continue
        if entry.implementation != "cpython":
            continue
        if f"{entry.version_parts.major}.{entry.version_parts.minor}" != minor:
            continue
        patch = entry.version_parts.patch
        if best is None or patch > best[0]:
            best = (patch, entry.version)
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


def _uv_env() -> dict[str, str]:
    """The ambient environment minus ``VIRTUAL_ENV`` for a provisioning uv call.

    Provisioning runs BEFORE :func:`context.build_context` pins ``VIRTUAL_ENV`` at the
    project venv, so a uv call here would otherwise inherit whatever venv the caller's
    shell activated (an IDE's, say). uv then prints
    ``warning: VIRTUAL_ENV=... does not match the project environment path ... and will
    be ignored`` on every provisioning call. bmk targets the venv explicitly
    (``uv venv <path>``, ``uv pip install --python <path>``), so ``VIRTUAL_ENV`` is pure
    noise here - drop it so the output stays clean and uv cannot prefer a foreign env.
    """
    return {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}


def _run(argv: list[str], cwd: Path, *, quiet: bool, env: Mapping[str, str] | None = None) -> int:
    """Run ``argv`` in ``cwd``, silencing output when quiet; ``env`` defaults to :func:`_uv_env`."""
    output = subprocess.DEVNULL if quiet else None
    try:
        # argv is built from literals and a resolved path, never from user
        # input, and runs without a shell.
        return subprocess.run(
            argv, cwd=cwd, stdout=output, stderr=output, env=dict(env) if env is not None else _uv_env(), check=False
        ).returncode
    except OSError:
        # uv missing from PATH. Degrade to the caller's fallback rather than
        # breaking a run that may not have needed the venv at all.
        return 1


def _run_capture(argv: list[str], cwd: Path) -> str | None:
    """Run ``argv`` in ``cwd`` and return stdout, or None if it could not run."""
    try:
        # argv is built from literals; no shell, no user input.
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=_uv_env(), check=False)
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


def _minor_needs_install(minor: str, cwd: Path) -> bool:
    """False only when uv reports that it has nothing newer to install for ``minor``.

    ``uv python list`` (without ``--only-installed``) lists what is installed plus, for each
    minor, the newest download when that one is NOT installed; such an entry has no ``path``.
    So a download entry for ``minor`` means "install/upgrade has work to do", and no entry at
    all means the minor is absent. Read-only and offline (~0.05s). If uv cannot answer, the
    answer is True: the old always-run behaviour, never a skipped install on a guess.

    Only the ``default`` variant counts: ``uv python install X.Y`` installs that one, while uv
    also lists a never-installed ``freethreaded`` download beside every 3.13+ minor.
    ``--allow-python-downloads``: with ``python-downloads`` set to manual or never (env OR any uv
    config file) uv hides every download entry, and "nothing listed" would read as "current".
    """
    raw = _run_capture(["uv", "python", "list", "--allow-python-downloads", "--output-format", "json"], cwd)
    if not raw:
        return True
    try:
        entries = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return True
    if not isinstance(entries, list):
        return True
    relevant: list[_UvPythonEntry] = []
    for raw_entry in cast("list[Any]", entries):
        try:
            entry = _UvPythonEntry.model_validate(raw_entry)
        except ValidationError:
            continue
        same_minor = f"{entry.version_parts.major}.{entry.version_parts.minor}" == minor
        if entry.implementation == "cpython" and entry.is_default_build and same_minor:
            relevant.append(entry)
    return not relevant or any(entry.path is None for entry in relevant)


def ensure_minors_installed(cwd: Path, minors: list[str], *, quiet: bool = True) -> None:
    """Prepare every minor, one after another, BEFORE any venv of them is synced.

    ``test-all`` calls this ahead of its parallel cells: an install that does change uv's
    store rewrites every minor alias, and a cell syncing at that moment loses its interpreter.
    """
    for minor in minors:
        _ensure_minor_installed(minor, cwd, quiet=quiet)


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
    breaking a command that may not have needed a new Python at all.

    Neither runs when uv has nothing newer (:func:`_minor_needs_install`): both rewrite EVERY
    minor alias symlink in uv's Python store even when they change nothing (measured, uv
    0.13.0), and every venv on the machine resolves its interpreter through such an alias, so
    a no-op call briefly breaks every venv - another bmk's included.
    """
    if not _minor_needs_install(minor, cwd):
        return
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


def _lock_dir() -> Path:
    """Directory holding the venv locks, per user, outside every repository."""
    override = os.environ.get(_LOCK_DIR_ENV)
    return Path(override) if override else Path.home() / ".cache" / "bmk" / "venv-locks"


def sync_lock_path(venv: Path) -> Path:
    """The lock file guarding every mutation of ``venv``.

    Deliberately OUTSIDE the project, keyed by a digest of the venv's absolute path.
    A lock is machine state, not project content, and the two repo-local options both
    fail: inside the venv is destroyed by the rebuild this very lock has to guard
    (``_discard_venv_on_wrong_python`` ``rmtree``s it), and beside the venv leaves an
    untracked file in the user's ``git status`` - ``_append_to_gitignore`` writes every
    entry with a trailing slash, so the existing ``.venv*`` rules match DIRECTORIES
    only and cannot cover a lock file however it is named.

    Out-of-repo also means provisioning still serialises when the checkout is read-only.

    Scope note: the directory is per USER, so two people sharing one checkout do not
    exclude each other. They would already be sharing one venv, which is broken for
    other reasons; the case this exists for - a subagent and the main agent, or two
    repos gated at once - runs as one user and shares the lock correctly.
    """
    digest = hashlib.sha256(str(venv.resolve()).encode("utf-8")).hexdigest()[:16]
    return _lock_dir() / f"{digest}.lock"


def _lock_timeout() -> float:
    """Seconds to wait for another bmk, from the environment or the default."""
    raw = os.environ.get(_LOCK_TIMEOUT_ENV)
    if raw is None:
        return _DEFAULT_LOCK_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_LOCK_TIMEOUT


@contextmanager
def _venv_sync_lock(venv: Path, *, quiet: bool) -> Generator[bool, None, None]:
    """Hold the exclusive lock for ``venv``; yield False if another bmk holds it.

    Scope is deliberately the SYNC ONLY, never the caller's whole gate. A lock held for
    a gate's lifetime would deadlock bmk against itself, because ``push`` runs the test
    pipeline and ``test-all`` spawns a cell per Python version, all inside one process
    tree. A rare flake is better than a reliable hang.

    A timeout does NOT fall through to syncing anyway. Provisioning is allowed to fail
    (the caller degrades to bmk's own interpreter), but it is never allowed to run
    concurrently with another bmk's sync, which is the corruption this exists to stop.
    """
    path = sync_lock_path(venv)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if not quiet:
            print(f"[venv] no lock directory ({exc}); proceeding unguarded", file=sys.stderr)
        yield True
        return
    lock = FileLock(str(path), timeout=_lock_timeout())
    try:
        lock.acquire()
    except Timeout:
        # stderr, always: the caller degrades silently to another interpreter, so this
        # message is the only thing that tells anyone the gate is about to be weaker.
        print(
            f"[venv] another bmk is still provisioning {venv.name}; "
            f"waited {_lock_timeout():g}s for {path} and gave up. "
            "Nothing was changed. Re-run once the other command finishes.",
            file=sys.stderr,
        )
        yield False
        return
    except OSError as exc:
        # An unlockable location (a filesystem without the primitive) must not make bmk
        # unusable there; degrade to the old unguarded behaviour and say so.
        if not quiet:
            print(f"[venv] could not lock {path} ({exc}); proceeding unguarded", file=sys.stderr)
        yield True
        return
    try:
        yield True
    finally:
        lock.release()


def ensure_project_venv_at(
    cwd: Path, venv: Path, minor: str | None, *, quiet: bool = True, install_python: bool = True
) -> Path | None:
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

    ``install_python=False`` leaves uv's Python store alone: ``test-all`` prepares every minor
    serially before its parallel cells, and a cell that installed again could rewrite the minor
    aliases under a sibling's sync whenever that prep did not converge (bmk OPEN-WORK [102]).

    Returns the venv path, or ``None`` if it could not be provisioned. Never raises: a
    failure degrades rather than aborting the command.
    """
    # Outside the lock on purpose: this installs into uv's machine-wide Python store,
    # a DIFFERENT shared resource from this venv, and it is idempotent.
    if minor and install_python:
        _ensure_minor_installed(minor, cwd, quiet=quiet)

    with _venv_sync_lock(venv, quiet=quiet) as acquired:
        if not acquired:
            return None
        return _provision_locked(cwd, venv, minor, quiet=quiet)


def _provision_locked(cwd: Path, venv: Path, minor: str | None, *, quiet: bool) -> Path | None:
    """Everything that MUTATES the venv, run under :func:`_venv_sync_lock`.

    The rebuild belongs in here as much as the sync does: an interpreter change
    ``rmtree``s the whole venv, which is the widest window of all.
    """
    _discard_venv_on_wrong_python(venv, minor, cwd, quiet=quiet)

    create = ["uv", "venv", *(["--python", minor] if minor else []), str(venv)]
    if not is_venv(venv) and _run(create, cwd, quiet=quiet) != 0:
        return None
    if not is_venv(venv):
        return None

    ensure_venv_ignored(cwd, venv)
    ensure_venv_typecheck_excluded(cwd, venv)

    python = venv_python(venv)
    synced = _sync_from_lock(cwd, venv, python, quiet=quiet)
    if synced is not None:
        return venv if synced else None
    for target in _INSTALL_TARGETS:
        argv = ["uv", "pip", "install", "--python", str(python), "--exact", "--upgrade", "-e", target]
        if _run(argv, cwd, quiet=quiet) == 0:
            return venv
    return None


def _sync_from_lock(cwd: Path, venv: Path, python: Path, *, quiet: bool) -> bool | None:
    """Lock the project, then make ``venv`` exactly what ``uv.lock`` pins.

    The lock is the source because ``uv pip install --upgrade`` keeps an installed release that
    still satisfies the manifest, even one newer than the project's ``[tool.uv]`` cooldown
    (measured: ruff 0.17.0 stayed installed while the lock pinned 0.16.9). The gates would then
    check a different tree from the one the lock pins and CI installs.

    ``uv sync`` installs into the PROJECT environment, so the target venv is named through
    ``UV_PROJECT_ENVIRONMENT``; that is how the per-version matrix venvs get their own sync.

    Returns:
        True when synced from the lock; False when the lock was made but the sync failed, which
        must surface rather than be covered by a manifest install; None when no lock could be
        made, so the caller may fall back to the manifest.
    """
    if not lock_project(cwd, quiet=quiet):
        print(f"[venv] uv lock failed in {cwd}; provisioning {venv.name} from pyproject.toml instead", file=sys.stderr)
        return None
    argv = ["uv", "sync", "--locked", "--python", str(python), "--no-default-groups", *_sync_extras(cwd)]
    env = {**_uv_env(), "UV_PROJECT_ENVIRONMENT": str(venv)}
    if quiet:
        rc, stderr = _run_keeping_stderr(argv, cwd, quiet=True, env=env)
    else:
        # Text mode inherits the terminal: a piped stderr would hold back a multi-minute first sync
        # until uv exits, and uv drops its progress display when stderr is not a terminal.
        rc, stderr = _run(argv, cwd, quiet=False, env=env), ""
    if rc == 0:
        return True
    _report_failed_sync(venv, rc, stderr, quiet=quiet)
    return False


def _report_failed_sync(venv: Path, rc: int, stderr: str, *, quiet: bool) -> None:
    """Say on stderr that the sync failed, why uv says it did, and what it left of ``venv``.

    Always printed, never gated on ``quiet``: the caller degrades silently to an ERROR, and the
    failure is intermittent, so asking for a text-mode re-run would lose the very evidence it
    asks for. When not quiet, uv's output already streamed above, so only the header is printed.

    When quiet, ALL of uv's stderr follows, uncapped: uv puts its verdict first and the detail
    after it (uv 0.13.0, a failing build: ``error: Failed to build`` on line 6 of 26), so any tail
    drops the cause, and the block prints only on a failure. The block goes out as ONE write,
    because parallel test-all cells share this stderr and only the header names the venv.
    """
    header = f"[venv] uv sync from uv.lock failed for {venv.name} (exit {rc}; venv afterwards: {_venv_state(venv)})"
    lines = [header]
    if quiet:
        lines = [f"{header}:", *(f"    {line}" for line in _ANSI_SGR.sub("", stderr).splitlines())]
    sys.stderr.write("\n".join(lines) + "\n")
    sys.stderr.flush()


def _venv_state(venv: Path) -> str:
    """What is at ``venv``: ``venv``, ``directory without pyvenv.cfg``, ``empty directory`` or ``absent``."""
    if is_venv(venv):
        return "venv"
    if not venv.is_dir():
        return "absent"
    try:
        empty = next(venv.iterdir(), None) is None
    except OSError:
        empty = False
    return "empty directory" if empty else "directory without pyvenv.cfg"


def _sync_extras(cwd: Path) -> list[str]:
    """``--extra dev`` when the project declares it: uv refuses an undeclared extra (exit 2)."""
    try:
        extras = load_pyproject_config(cwd / "pyproject.toml").project.optional_dependencies
    except Exception:  # an unreadable manifest is uv's to report, never a reason to skip the sync
        return []
    return ["--extra", "dev"] if "dev" in extras else []


def _exempt_packages(cwd: Path) -> list[str]:
    """Packages ``[tool.uv] exclude-newer-package`` sets to ``false``: no cooldown, our own."""
    try:
        table = load_pyproject_config(cwd / "pyproject.toml").tool.uv.exclude_newer_package
    except Exception:  # an unreadable manifest is uv's to report; refreshing nothing is the old behaviour
        return []
    return sorted(name for name, value in table.items() if value is False)


def lock_project(cwd: Path, *, quiet: bool = True, upgrade: bool = False) -> bool:
    """Run ``uv lock`` once at a time per project: matrix cells sync in parallel from one lock.

    ``upgrade`` re-resolves every package at its newest release the project's cooldown admits;
    without it an existing lock is only brought in line with the manifest. An upgrade also
    refreshes every package the project exempts from the cooldown (our own): PyPI serves the
    index with ``max-age=600`` and uv honours it, so without a refresh a release from minutes
    ago stays invisible and the own floor, which rises only to what the lock resolves, stays put.
    """
    argv = ["uv", "lock", *(["--upgrade"] if upgrade else [])]
    refresh = _lock_argv(cwd, upgrade=upgrade)[len(argv) :]
    path = _lock_dir() / f"{hashlib.sha256(str(cwd.resolve()).encode('utf-8')).hexdigest()[:16]}.uvlock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(path), timeout=_lock_timeout()):
            return _lock_with_refresh(argv, refresh, cwd, quiet=quiet)
    except Timeout:
        print(f"[venv] another bmk is still locking {cwd}; waited {_lock_timeout():g}s and gave up", file=sys.stderr)
        return False
    except OSError:
        # An unlockable location must not make bmk unusable there; lock unguarded instead.
        return _lock_with_refresh(argv, refresh, cwd, quiet=quiet)


def _lock_argv(cwd: Path, *, upgrade: bool) -> list[str]:
    """``uv lock``; an upgrade adds ``--upgrade`` and a ``--refresh-package`` per exempt own package."""
    if not upgrade:
        return ["uv", "lock"]
    refresh = [arg for name in _exempt_packages(cwd) for arg in ("--refresh-package", name)]
    return ["uv", "lock", "--upgrade", *refresh]


_UV_ERROR_EXIT = 2

# What uv says when it rejects the refresh flag ITSELF (uv 0.13.0, measured): offline configured in
# the environment, a config file or the command line ("cannot be used with `--refresh`"), or a
# name clap will not parse. Exit 2 alone is not enough: it is uv's general error status, shared by
# an unreachable index and a malformed manifest.
_REFRESH_REFUSALS = ("cannot be used with `--refresh`", "for '--refresh-package")
# FORCE_COLOR / CLICOLOR_FORCE put escape codes inside those very words, and under CLICOLOR_FORCE
# `--color never` does not reach clap's own parse errors, so the text is compared with its SGR
# sequences removed.
_ANSI_SGR = re.compile(r"\x1b\[[0-9;]*m")


def _refresh_refused(rc: int, stderr: str) -> bool:
    """True only when uv refused ``--refresh-package`` itself, so the plain lock may stand in."""
    plain = _ANSI_SGR.sub("", stderr)
    return rc == _UV_ERROR_EXIT and any(marker in plain for marker in _REFRESH_REFUSALS)


def _run_keeping_stderr(
    argv: list[str], cwd: Path, *, quiet: bool, env: Mapping[str, str] | None = None
) -> tuple[int, str]:
    """Like :func:`_run`, but hands back stderr (still shown when not quiet) to be classified or reported."""
    try:
        # argv is built from literals and package names from the project's own manifest; no shell.
        done = subprocess.run(
            argv,
            cwd=cwd,
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(env) if env is not None else _uv_env(),
            check=False,
        )
    except OSError:
        return 1, ""
    if not quiet:
        sys.stderr.write(done.stderr)
    return done.returncode, done.stderr


def _lock_with_refresh(argv: list[str], refresh: list[str], cwd: Path, *, quiet: bool) -> bool:
    """Lock with the own-package refresh, and once more without it only if uv refused the refresh.

    The plain lock is the old behaviour, so the refresh may only ever add, never break a gate. Any
    other failure stands: retried without the refresh, an index that is down for the revalidation
    could lock from the max-age=600 cache, and the own floor would silently stay put again.
    """
    if not refresh:
        return _run(argv, cwd, quiet=quiet) == 0
    rc, stderr = _run_keeping_stderr([*argv, *refresh], cwd, quiet=quiet)
    if not _refresh_refused(rc, stderr):
        return rc == 0
    print(
        "[venv] uv refused --refresh-package (offline is configured, or a package name it rejects); "
        "locking without refreshing our own packages",
        file=sys.stderr,
    )
    return _run(argv, cwd, quiet=quiet) == 0
