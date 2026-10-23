"""Supply-chain cooldown: which releases a dependency floor may adopt.

Purpose
-------
A malicious release is usually found and pulled within days of its upload. A project that only
adopts releases older than a cooldown never installs one in that window. uv enforces the cooldown
itself through ``[tool.uv] exclude-newer`` (for the whole tree, transitive dependencies included)
and exempts packages through ``exclude-newer-package``. bmk keeps that block present in every
project and judges floors against the cutoff uv itself RESOLVED.

bmk deliberately does not parse uv's input grammar. uv refuses a value outside it with only a
warning, then ignores the whole ``[tool.uv]`` block, so a second parser that accepts slightly more
(or reads a date differently) judges floors under a cooldown uv is not applying. uv writes what it
resolved into ``uv.lock`` ``[options]`` in a small canonical form - an ISO span or a UTC timestamp -
and writes nothing when it refused the value, which is what turns a typo into an error here. The
project's own lock cannot be the source: a floor younger than the cooldown makes it fail, and that
floor is exactly what bmk has to read the cutoff to repair. So :func:`uv_resolved_options` asks uv
about the ``[tool.uv]`` values alone, in a scratch project with no dependencies, which locks offline
in milliseconds and cannot fail on a floor.

Contents
--------
* ``LockOptions`` / ``LockedCutoff`` - the ``uv.lock`` ``[options]`` table, read into typed cutoffs.
* ``ReleasePolicy`` - the project's cutoff per package, as uv resolved it into ``uv.lock``.
* ``uv_resolved_options`` - asks uv to resolve ``[tool.uv]`` values into that canonical form.
* ``admitted_releases`` - a PyPI ``releases`` map reduced to the files uploaded before a cutoff.
* ``own_closure`` - the own packages a project reaches, directly or through other own packages.
* ``ensure_uv_cooldown`` - writes the cooldown and the exemptions into ``[tool.uv]``.
* ``floor_pin`` / ``reconcile_floor_pins`` - the per-package cutoff that admits a floor release
  still inside the cooldown, and keeping bmk's own such entries current.
* ``SupplyChainSettings`` - the default cooldown and the own-package list from bmk's config.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import rtoml
from packaging.requirements import InvalidRequirement, Requirement
from pydantic import BaseModel, ConfigDict

from bmk.adapters.stagerunner.helpers import _typed_tomlkit
from bmk.adapters.stagerunner.helpers._pypi_models import PypiFile, PypiReleases, parse_moment

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

__all__ = [
    "DEFAULT_COOLDOWN",
    "DEFAULT_OWN_PACKAGES",
    "LockOptions",
    "LockedCutoff",
    "OwnPackageUnreadableError",
    "ReleasePolicy",
    "SupplyChainConfigError",
    "SupplyChainSettings",
    "admitted_releases",
    "ensure_uv_cooldown",
    "floor_pin",
    "normalize",
    "own_closure",
    "read_lock_options",
    "reconcile_floor_pins",
    "uv_resolved_options",
]

DEFAULT_COOLDOWN = "7 days"

# Our own packages on PyPI: they always follow the newest release, so they are exempt from the
# cooldown. Every name here was checked to be a bitranox project on PyPI (its project URLs).
DEFAULT_OWN_PACKAGES: frozenset[str] = frozenset(
    {
        "agentdag",
        "bmk",
        "btx-lib-list",
        "btx-lib-mail",
        "btx-skill-jev-judge",
        "check-zpools",
        "fake-winreg",
        "finanzonline-databox",
        "finanzonline-uid",
        "hugesitemap",
        "igittigitt",
        "ipscout",
        "keep-github-workflows-active",
        "lib-cli-exit-tools",
        "lib-detect-testenv",
        "lib-layered-config",
        "lib-log-rich",
        "lib-registry",
        "lib-shopify-graphql",
        "lib-shopware6-api",
        "lib-shopware6-api-base",
        "lsdsk",
        "proxmox-srvbackup",
        "pwshpy",
        "pyproj-dep-analyze",
        "soundtouch-zonemaster",
        "vnc-remote-control",
    }
)


class SupplyChainConfigError(ValueError):
    """A cooldown value that cannot be read; refused rather than guessed."""


class OwnPackageUnreadableError(Exception):
    """An own package's requirements could not be read, so the exemption list would be incomplete."""


_RE_SEPARATOR = re.compile(r"[-_.]+")


def normalize(name: str) -> str:
    """A package name in PEP 503 form, which is how uv keys ``exclude-newer-package``."""
    return _RE_SEPARATOR.sub("-", name).lower()


@dataclass(frozen=True)
class SupplyChainSettings:
    """What bmk writes into a project's ``[tool.uv]`` when the project has not chosen itself.

    Attributes:
        cooldown: The ``exclude-newer`` value for a project that has none.
        own_packages: Names exempted from the cooldown when a project reaches them.
    """

    cooldown: str = DEFAULT_COOLDOWN
    own_packages: frozenset[str] = DEFAULT_OWN_PACKAGES

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> SupplyChainSettings:
        """Read ``[bmk.supply_chain]``; a missing key keeps its default.

        Raises:
            SupplyChainConfigError: When ``cooldown`` is not a value uv accepts, or
                ``own_packages`` is not a list of names.
        """
        cooldown = section.get("cooldown", DEFAULT_COOLDOWN)
        if not isinstance(cooldown, str) or not _RE_WRITABLE_COOLDOWN.fullmatch(cooldown):
            raise SupplyChainConfigError(
                f"bmk.supply_chain.cooldown {cooldown!r} is not one bmk may write: use '<N> days', "
                "'<N> weeks', '<N> hours' (lowercase) or an ISO 8601 span such as 'P7D'"
            )
        own = section.get("own_packages", sorted(DEFAULT_OWN_PACKAGES))
        if not isinstance(own, (list, tuple)) or not all(isinstance(n, str) for n in cast("list[Any]", own)):
            raise SupplyChainConfigError(f"bmk.supply_chain.own_packages must be a list of names, got {own!r}")
        return cls(cooldown=cooldown, own_packages=frozenset(normalize(n) for n in cast("list[str]", own)))


# --- the exclude-newer grammar -------------------------------------------------------------------

# What bmk itself may WRITE into a project: a strict subset of uv's grammar. uv refuses a value
# outside its grammar only with a warning and then ignores the whole [tool.uv] block, so a value
# bmk writes must be one uv certainly takes ("14 Days", "14D", " 14 days " and "P14DT" are not).
_RE_WRITABLE_COOLDOWN = re.compile(
    r"[1-9]\d* (?:hours?|days?|weeks?)|P(?=\d|T\d)(?:\d+W)?(?:\d+D)?(?:T(?=\d)(?:\d+H)?(?:\d+M)?(?:\d+S)?)?"
)

# The canonical forms uv writes into uv.lock [options] (uv 0.13). A span carries no calendar unit
# (uv refuses months and years) and its sign is ignored by uv, so "5 days ago" and "5 days" lock the
# same releases; a timestamp is RFC 3339 in UTC.
_RE_LOCKED_SPAN = re.compile(
    r"-?P(?=\d|T\d)(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?"
    r"(?:T(?=\d)(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?)?"
)


class LockedCutoff(BaseModel):
    """One cutoff as uv locked it: a span counted back from now, or a fixed moment.

    A value bmk cannot read is kept as its ``refusal`` rather than raised while the lock is read: it
    is refused when the cutoff is USED, so a placeholder timestamp uv writes beside a span is never
    judged, and a check that refuses the project's settings first still names that reason.

    Attributes:
        span: The span uv wrote; it wins over the placeholder timestamp written beside it.
        timestamp: The fixed cutoff, when uv wrote no span.
        refusal: Why bmk cannot read the locked value; None when it can.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    span: timedelta | None = None
    timestamp: datetime | None = None
    refusal: str | None = None

    @classmethod
    def read(cls, timestamp: object, span: object) -> LockedCutoff:
        """The cutoff a ``timestamp`` / ``span`` pair locks, as uv wrote them (either may be None)."""
        if span is not None:
            match = _RE_LOCKED_SPAN.fullmatch(span) if isinstance(span, str) else None
            if match is None:
                return cls(refusal=f"uv.lock holds an exclude-newer span bmk cannot read: {span!r}")
            return cls(span=_span_of(match))
        moment = parse_moment(timestamp) if isinstance(timestamp, str) else None
        if moment is None:
            return cls(refusal=f"uv.lock holds an exclude-newer timestamp bmk cannot read: {timestamp!r}")
        return cls(timestamp=moment)

    def at(self, now: datetime) -> datetime:
        """The cutoff as a moment, a span counted back from ``now``.

        Raises:
            SupplyChainConfigError: For a value outside the canonical form uv writes.
        """
        if self.span is not None:
            return now - self.span
        if self.timestamp is not None:
            return self.timestamp
        raise SupplyChainConfigError(self.refusal or "uv.lock holds an exclude-newer value bmk cannot read")


def _span_of(match: re.Match[str]) -> timedelta:
    parts = {key: float(value) for key, value in match.groupdict().items() if value is not None}
    return timedelta(
        weeks=parts.get("w", 0),
        days=parts.get("d", 0),
        hours=parts.get("h", 0),
        minutes=parts.get("m", 0),
        seconds=parts.get("s", 0),
    )


class LockOptions(BaseModel):
    """The cooldown part of a ``uv.lock`` ``[options]`` table, read into typed cutoffs.

    Attributes:
        states_exclude_newer: Whether the lock carries ``exclude-newer``: its absence is how uv says
            it refused a stated cooldown.
        default: ``exclude-newer`` / ``exclude-newer-span`` as one cutoff; None when uv wrote neither.
        per_package: ``exclude-newer-package`` by normalized name; None means exempt.
        package_refusal: Why bmk cannot read ``exclude-newer-package``; None when it can.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    states_exclude_newer: bool = False
    default: LockedCutoff | None = None
    per_package: dict[str, LockedCutoff | None] = {}
    package_refusal: str | None = None

    @classmethod
    def from_table(cls, options: Mapping[str, object]) -> LockOptions:
        """Read the ``[options]`` table uv wrote.

        Only ``exclude-newer``, ``exclude-newer-span`` and ``exclude-newer-package`` are read; every
        other key is uv's own business.
        """
        states = "exclude-newer" in options
        default = None
        if states or "exclude-newer-span" in options:
            default = LockedCutoff.read(options.get("exclude-newer"), options.get("exclude-newer-span"))
        packages = options.get("exclude-newer-package", {})
        if not isinstance(packages, dict):
            refusal = f"uv.lock holds an exclude-newer-package bmk cannot read: {packages!r}"
            return cls(states_exclude_newer=states, default=default, package_refusal=refusal)
        per_package = {
            normalize(str(name)): _locked_package_cutoff(value)
            for name, value in cast("dict[object, object]", packages).items()
        }
        return cls(states_exclude_newer=states, default=default, per_package=per_package)


def _locked_package_cutoff(value: object) -> LockedCutoff | None:
    if value is False:
        return None
    if isinstance(value, dict):
        entry = cast("dict[str, object]", value)
        return LockedCutoff.read(entry.get("timestamp"), entry.get("span"))
    return LockedCutoff.read(value, None)


# --- the policy a project states in [tool.uv] ------------------------------------------------------


@dataclass(frozen=True)
class ReleasePolicy:
    """The cutoff uv applies to each package of one project.

    Attributes:
        default: ``exclude-newer`` as a cutoff, or None when the project sets none.
        per_package: ``exclude-newer-package`` by normalized name; None means exempt.
    """

    default: datetime | None = None
    per_package: Mapping[str, datetime | None] = field(default_factory=lambda: {})

    @classmethod
    def from_lock(cls, options: LockOptions, *, now: datetime) -> ReleasePolicy:
        """The cutoffs uv resolved, from a ``uv.lock`` ``[options]`` table.

        Raises:
            SupplyChainConfigError: For a value outside the canonical form uv writes.
        """
        default = options.default.at(now) if options.default is not None else None
        if options.package_refusal is not None:
            raise SupplyChainConfigError(options.package_refusal)
        per_package = {
            name: cutoff.at(now) if cutoff is not None else None for name, cutoff in options.per_package.items()
        }
        return cls(default=default, per_package=per_package)

    @classmethod
    def from_project(
        cls,
        *,
        exclude_newer: object,
        packages: Mapping[str, object],
        lock_options: LockOptions | None,
        now: datetime,
    ) -> ReleasePolicy:
        """The policy for a project whose ``[tool.uv]`` states ``exclude_newer`` and ``packages``.

        A value the project states but the lock does not carry is one uv refused: uv only warns
        and then ignores the whole block, so the cooldown would be off with nothing saying so.

        Raises:
            SupplyChainConfigError: When the project states a cooldown and there is no lock, or the
                lock lacks a value the project states, or holds one bmk cannot read.
        """
        if exclude_newer is None and not packages:
            return cls()
        if lock_options is None:
            raise SupplyChainConfigError("[tool.uv] states a cooldown but there is no uv.lock to read it from")
        locked_names = set(lock_options.per_package)
        if exclude_newer is not None and not lock_options.states_exclude_newer:
            raise SupplyChainConfigError(
                f"uv did not accept [tool.uv] exclude-newer = {exclude_newer!r} (uv.lock carries no cutoff); "
                "run 'uv lock' to see uv's warning"
            )
        for name, value in packages.items():
            if normalize(name) not in locked_names:
                raise SupplyChainConfigError(
                    f"uv did not accept [tool.uv] exclude-newer-package {name} = {value!r}; run 'uv lock' to see why"
                )
        return cls.from_lock(lock_options, now=now)

    def cutoff_for(self, name: str) -> datetime | None:
        """The cutoff for ``name``: its own override if it has one, else the project default."""
        return self.per_package.get(normalize(name), self.default)


def uv_resolved_options(exclude_newer: object, packages: Mapping[str, object]) -> LockOptions:
    """The ``[options]`` uv resolves ``[tool.uv]`` values into; empty when uv refused them.

    Runs ``uv lock --offline`` in a scratch project that carries only these values and no
    dependencies, so the answer is uv's own reading and cannot be blocked by any floor.

    Raises:
        SupplyChainConfigError: When uv cannot be run, or fails for another reason.
    """
    uv: dict[str, object] = {}
    if exclude_newer is not None:
        uv["exclude-newer"] = exclude_newer
    if packages:
        uv["exclude-newer-package"] = dict(packages)
    manifest = {
        "project": {"name": "bmk-cutoff-probe", "version": "0", "requires-python": ">=3.10"},
        "tool": {"uv": uv},
    }
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    with tempfile.TemporaryDirectory(prefix="bmk-cutoff-") as scratch:
        root = Path(scratch)
        (root / "pyproject.toml").write_text(_typed_tomlkit.dumps(manifest), encoding="utf-8")
        try:
            # argv is literal and runs without a shell; the values travel in the scratch file.
            result = subprocess.run(
                ["uv", "lock", "--offline"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as exc:
            raise SupplyChainConfigError(f"uv could not be run to read the cooldown: {exc}") from exc
        if result.returncode != 0:
            raise SupplyChainConfigError(f"uv could not resolve the cooldown: {result.stderr.strip()}")
        options = read_lock_options(root / "uv.lock")
    return options if options is not None else LockOptions()


def read_lock_options(lock: Path) -> LockOptions | None:
    """The ``[options]`` table of ``lock``: empty when uv wrote none, None when there is no lock.

    Raises:
        SupplyChainConfigError: When the lock exists but is not TOML bmk can read.
    """
    try:
        text = lock.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SupplyChainConfigError(f"{lock} cannot be read: {exc}") from exc
    try:
        document = rtoml.loads(text)
    except rtoml.TomlParsingError as exc:
        raise SupplyChainConfigError(f"{lock} is not valid TOML: {exc}") from exc
    options = document.get("options", {})
    return LockOptions.from_table(cast("dict[str, object]", options)) if isinstance(options, dict) else LockOptions()


def admitted_releases(releases: PypiReleases, cutoff: datetime | None) -> dict[str, tuple[PypiFile, ...]]:
    """``releases`` holding only the files uploaded before ``cutoff``, as uv filters them.

    uv judges each FILE, not the version: a release stays available through any file uploaded in
    time, and a release with none left is gone. A file without an upload time is dropped, since
    nothing shows it predates the cutoff.
    """
    if cutoff is None:
        return dict(releases)
    admitted: dict[str, tuple[PypiFile, ...]] = {}
    for version, files in releases.items():
        kept = tuple(f for f in files if f.uploaded is not None and f.uploaded < cutoff)
        if kept:
            admitted[version] = kept
    return admitted


# --- keeping [tool.uv] in the project --------------------------------------------------------------


def own_closure(
    direct: Iterable[str],
    *,
    own: frozenset[str],
    requires_of: Callable[[str], Iterable[str] | None],
    project: str,
) -> set[str]:
    """Every own package the project reaches, directly or only through another own package.

    The exemption must cover all of them: an exempt package whose newest release needs a newer
    release of another own package resolves to an OLDER release when that one is not exempt too.
    Foreign packages are never walked, so a foreign dependency naming an own package adds nothing.

    Args:
        direct: The names the project depends on.
        own: Our own packages, normalized.
        requires_of: The requirement strings of a package's newest release, by normalized name;
            None when they cannot be read.
        project: The project's own name, never exempted from itself.

    Raises:
        OwnPackageUnreadableError: When an own package's requirements cannot be read: an own package
            behind it would be missing from the list, which is the silent case this exists for.
    """
    own_set = {normalize(n) for n in own} - {normalize(project)}
    reached = {normalize(n) for n in direct} & own_set
    queue = deque(sorted(reached))
    while queue:
        name = queue.popleft()
        requires = requires_of(name)
        if requires is None:
            raise OwnPackageUnreadableError(name)
        for spec in requires:
            try:
                required = normalize(Requirement(spec).name)
            except InvalidRequirement:
                continue
            if required in own_set and required not in reached:
                reached.add(required)
                queue.append(required)
    return reached


def ensure_uv_cooldown(pyproject: Path, *, cooldown: str, exempt: Iterable[str]) -> list[str]:
    """Write the cooldown and the exemptions into ``[tool.uv]``, keeping what the project chose.

    An ``exclude-newer`` already set is left alone, and so is any package already listed under
    ``exclude-newer-package`` in any spelling, since an override there is a deliberate choice
    (a security fix newer than the cooldown). Only missing entries are added.

    Returns:
        One line per change; empty when the file was already complete and is left untouched.
    """
    text = pyproject.read_text(encoding="utf-8")
    appended = _appended_block(text, cooldown=cooldown, exempt=exempt)
    if appended is not None:
        pyproject.write_text(appended[0], encoding="utf-8")
        return appended[1]
    document = _typed_tomlkit.parse(text)
    tool = _subtable(document, "tool", super_table=True)
    uv = _subtable(tool, "uv")
    changes: list[str] = []
    if "exclude-newer" not in uv:
        uv["exclude-newer"] = cooldown
        changes.append(f'[tool.uv] exclude-newer = "{cooldown}"')
    packages = uv.get("exclude-newer-package")
    if packages is None:
        packages = _typed_tomlkit.inline_table()
    listed = {normalize(str(name)) for name in packages}
    for name in sorted({normalize(n) for n in exempt} - listed):
        packages[name] = False
        changes.append(f"[tool.uv] exclude-newer-package: {name} = false")
    if packages and "exclude-newer-package" not in uv:
        uv["exclude-newer-package"] = packages
    if changes:
        pyproject.write_text(_typed_tomlkit.dumps(document), encoding="utf-8")
    return changes


def _appended_block(text: str, *, cooldown: str, exempt: Iterable[str]) -> tuple[str, list[str]] | None:
    """A project with no ``[tool.uv]`` gets the block appended at the end, as text.

    tomlkit would group a new table after the FIRST ``[tool.*]`` table, which in a file that
    interleaves ``[tool.*]`` and ``[project.*]`` lands it mid-file; appending keeps the diff to new
    lines only. The result is re-parsed, and anything that does not come back as exactly the block
    (a ``tool`` written as an inline table, say) returns None for the tomlkit path to handle.
    """
    if "uv" in _typed_tomlkit.parse(text).get("tool", {}):
        return None
    names = sorted({normalize(n) for n in exempt})
    lines = ["[tool.uv]", f'exclude-newer = "{cooldown}"']
    if names:
        lines.append("exclude-newer-package = { " + ", ".join(f"{n} = false" for n in names) + " }")
    candidate = text.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n"
    try:
        uv = _typed_tomlkit.parse(candidate)["tool"]["uv"]
    except Exception:  # an append that does not parse falls back to the structural edit
        return None
    if uv.get("exclude-newer") != cooldown or sorted(uv.get("exclude-newer-package", {})) != names:
        return None
    changes = [
        f'[tool.uv] exclude-newer = "{cooldown}"',
        *(f"[tool.uv] exclude-newer-package: {n} = false" for n in names),
    ]
    return candidate, changes


def _subtable(parent: Any, key: str, *, super_table: bool = False) -> Any:
    if key not in parent:
        parent[key] = _typed_tomlkit.table(super_table=super_table)
    return parent[key]


# --- floors younger than the cooldown --------------------------------------------------------------

# A floor the project declares is never lowered for the cooldown: lowering drops the fixes the
# floor was raised for, and undoes floors already published. Instead the release the floor needs
# gets a per-package cutoff just after its own upload, which admits it and nothing uploaded later.
# bmk recognises its own entries by that exact value, so an override the project set is never
# touched; once the cooldown admits the release, the entry is dropped, because a timestamp replaces
# the default cutoff for its package and would otherwise hold the package back for good.


def floor_pin(files: Iterable[PypiFile]) -> str | None:
    """The cutoff that admits every file of a release: the next whole second after the newest one.

    Returns None when no file carries an upload time.
    """
    moments = [f.uploaded for f in files if f.uploaded is not None]
    if not moments:
        return None
    pin = max(moments).astimezone(timezone.utc).replace(microsecond=0) + timedelta(seconds=1)
    return pin.strftime("%Y-%m-%dT%H:%M:%SZ")


def reconcile_floor_pins(
    pyproject: Path,
    *,
    pins: Mapping[str, str],
    is_floor_pin: Callable[[str, object], bool],
    cutoff: datetime | None,
) -> list[str]:
    """Make bmk's floor pins in ``[tool.uv] exclude-newer-package`` exactly ``pins``.

    An entry ``is_floor_pin`` does not recognise is the project's own choice and is left alone,
    also when ``pins`` names that package. A recognised entry no declared floor demands is removed
    only once ``cutoff`` admits the release it serves: recognition is by value, so a pin the project
    placed by hand at the same second reads as bmk's, and removing it while the cooldown still
    excludes that release would take away what it was placed for (a security fix in a transitive
    dependency). Kept, it is named on stderr; a stale pin of bmk's own goes within one cooldown.

    Returns:
        One line per change; empty when the file is left untouched.
    """
    document = _typed_tomlkit.parse(pyproject.read_text(encoding="utf-8"))
    uv = _subtable(_subtable(document, "tool", super_table=True), "uv")
    current: dict[str, object] = {str(name): value for name, value in uv.get("exclude-newer-package", {}).items()}
    wanted = {normalize(name): pin for name, pin in pins.items()}
    entries, changes = _reconciled_pins(
        current, pyproject=pyproject, wanted=wanted, is_floor_pin=is_floor_pin, cutoff=cutoff
    )
    if not changes:
        return []
    _store_entries(uv, current=current, entries=entries)
    pyproject.write_text(_typed_tomlkit.dumps(document), encoding="utf-8")
    return changes


def _reconciled_pins(
    current: Mapping[str, object],
    *,
    pyproject: Path,
    wanted: Mapping[str, str],
    is_floor_pin: Callable[[str, object], bool],
    cutoff: datetime | None,
) -> tuple[dict[str, object], list[str]]:
    """The entries ``exclude-newer-package`` should hold, and one line per change from ``current``.

    ``current`` keeps the spelling of its names, so a project that wrote ``Foo_Bar`` still finds
    that key; new keys follow, sorted, so the file grows in a stable order.

    Args:
        current: The table as written, by its own key spelling.
        pyproject: The file, named in the stderr line about a kept pin.
        wanted: bmk's floor pins, by normalized name.
        is_floor_pin: Whether an entry is one bmk wrote.
        cutoff: The default cutoff, which decides when a pin nothing demands may go.

    Returns:
        The entries in write order, and the change lines in the order they are reported.
    """
    entries: dict[str, object] = {}
    changes: list[str] = []
    for name, value in current.items():
        key = normalize(name)
        if not is_floor_pin(key, value):
            entries[name] = value
        elif key not in wanted and _admits_beyond(value, cutoff):
            entries[name] = value
            print(
                f"{pyproject}: [tool.uv] exclude-newer-package: {key} pin kept: no declared floor demands it, "
                "and the cooldown does not admit its release yet",
                file=sys.stderr,
            )
        elif key not in wanted:
            changes.append(f"[tool.uv] exclude-newer-package: {key} pin removed, the cooldown admits it")
        else:
            entries[name] = wanted[key]
            if value != wanted[key]:
                changes.append(f'[tool.uv] exclude-newer-package: {key} = "{wanted[key]}"')
    listed = {normalize(name) for name in current}
    for key in sorted(set(wanted) - listed):
        entries[key] = wanted[key]
        changes.append(f'[tool.uv] exclude-newer-package: {key} = "{wanted[key]}" (floor younger than the cooldown)')
    return entries, changes


def _store_entries(uv: Any, *, current: Mapping[str, object], entries: Mapping[str, object]) -> None:
    """Make ``[tool.uv] exclude-newer-package`` hold exactly ``entries``, dropping it when empty.

    Args:
        uv: The parsed ``[tool.uv]`` table, changed in place.
        current: The entries the table held before, by its own key spelling.
        entries: What it should hold, in write order.
    """
    container = uv.get("exclude-newer-package")
    if _typed_tomlkit.is_standard_table(container) and entries:
        # Edited in place, so the project's comments and the table's own form survive.
        _apply_entries(container, current=current, entries=entries)
    # An inline table is rebuilt rather than edited: tomlkit appends to one without the spacing
    # the rest of it has ('..., a = 1,b = 2}').
    elif entries:
        table = _typed_tomlkit.inline_table()
        for name, value in entries.items():
            table[name] = value
        uv["exclude-newer-package"] = table
    elif "exclude-newer-package" in uv:
        del uv["exclude-newer-package"]


def _admits_beyond(pin: object, cutoff: datetime | None) -> bool:
    """Whether ``pin`` admits an upload the default ``cutoff`` excludes.

    A pin at or before the cutoff admits nothing more, and would hold its package back.
    """
    moment = parse_moment(pin) if isinstance(pin, str) else None
    return cutoff is not None and moment is not None and moment > cutoff


def _apply_entries(table: Any, *, current: Mapping[str, object], entries: Mapping[str, object]) -> None:
    """Make the standard ``table`` hold exactly ``entries``, touching only the keys that change."""
    for name in current:
        if name not in entries:
            del table[name]
    for name, value in entries.items():
        if current.get(name) != value:
            table[name] = value
