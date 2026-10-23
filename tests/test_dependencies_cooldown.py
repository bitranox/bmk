"""A floor only rises to a release older than the project's uv cooldown (``[tool.uv] exclude-newer``).

A floor bmk writes must stay resolvable under the cooldown uv itself enforces, or ``uv lock``
fails; packages the project exempts (``exclude-newer-package``, our own packages) follow the newest
release. PyPI is the one external edge, so ``httpx2.stream`` serves canned JSON per package, with
upload times relative to the real clock, and the tests drive ``check_dependencies`` /
``update_dependencies`` / ``ensure_uv_cooldown`` on a real ``pyproject.toml``.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import httpx2
import orjson
import pytest
import rtoml

from bmk.adapters.config.loader import get_default_config_path
from bmk.adapters.stagerunner.helpers import _dependencies, _supply_chain
from bmk.adapters.stagerunner.helpers._dependencies import (
    DependencyStatus,
    check_dependencies,
    update_dependencies,
)
from bmk.adapters.stagerunner.helpers._supply_chain import (
    ReleasePolicy,
    SupplyChainConfigError,
    SupplyChainSettings,
    admitted_releases,
    ensure_uv_cooldown,
    own_closure,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path

_NOW = datetime.now(timezone.utc)


def _uploaded(days_ago: float, *, requires_python: str | None = ">=3.10") -> list[dict[str, Any]]:
    stamp = (_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return [{"requires_python": requires_python, "yanked": False, "upload_time_iso_8601": stamp}]


def _doc(version: str, releases: dict[str, list[dict[str, Any]]], requires: list[str] | None = None) -> dict[str, Any]:
    return {"info": {"version": version, "requires_dist": requires}, "releases": releases}


# 1.1 is a month old, 1.2 three days old: inside a 14-day cooldown only 1.1 is adoptable.
_WIDGET = _doc("1.2", {"1.0": _uploaded(90), "1.1": _uploaded(30), "1.2": _uploaded(3)})


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self) -> Iterator[bytes]:
        yield self._body


class _FakeIndex:
    """PyPI's JSON API: ``/pypi/<name>/json`` from ``packages``, ``/pypi/<name>/<version>/json`` from ``versions``."""

    def __init__(self, packages: dict[str, dict[str, Any]]) -> None:
        self.packages = dict(packages)
        self.versions: dict[str, list[str]] = {}

    @contextmanager
    def stream(self, method: str, url: str, **_: object) -> Generator[_FakeResponse]:
        assert method == "GET"
        path = url.removeprefix("https://pypi.org/pypi/").removesuffix("/json")
        if "/" in path:
            # A release no test describes requires nothing.
            yield _FakeResponse(orjson.dumps({"info": {"requires_dist": self.versions.get(path, [])}}))
            return
        if path not in self.packages:
            raise httpx2.ConnectError(f"{path}: PyPI unreachable")
        yield _FakeResponse(orjson.dumps(self.packages[path]))


@pytest.fixture
def pypi(monkeypatch: pytest.MonkeyPatch) -> _FakeIndex:
    index = _FakeIndex({"widget": _WIDGET})
    monkeypatch.setattr(_dependencies.httpx2, "stream", index.stream)
    return index


def _write(tmp_path: Path, *, deps: str, tool_uv: str = "", classifiers: bool = True) -> Path:
    """A project with ``tool_uv`` as its [tool.uv]; the real uv resolves those values for bmk."""
    pyproject = tmp_path / "pyproject.toml"
    python = (
        'requires-python = ">=3.10"\nclassifiers = ["Programming Language :: Python :: 3.10"]\n' if classifiers else ""
    )
    uv = f"\n[tool.uv]\n{tool_uv}\n" if tool_uv else ""
    pyproject.write_text(
        f'[project]\nname = "demo"\nversion = "1.0.0"\n{python}dependencies = [{deps}]\n{uv}', encoding="utf-8"
    )
    return pyproject


def _raise(pyproject: Path) -> str:
    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)
    return pyproject.read_text(encoding="utf-8")


# --- floors follow the cooldown -------------------------------------------------------------------


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_third_party_floor_rises_only_to_a_release_older_than_the_cooldown(tmp_path: Path) -> None:
    pyproject = _write(tmp_path, deps='"widget>=1.0"', tool_uv='exclude-newer = "14 days"')

    assert '"widget>=1.1"' in _raise(pyproject)


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_without_a_cooldown_the_floor_still_follows_the_newest_release(tmp_path: Path) -> None:
    pyproject = _write(tmp_path, deps='"widget>=1.0"')

    assert '"widget>=1.2"' in _raise(pyproject)


@pytest.mark.os_agnostic
def test_an_exempt_package_follows_the_newest_release(tmp_path: Path, pypi: _FakeIndex) -> None:
    pypi.versions["widget/1.2"] = []  # needs nothing, so uv can lock it under the cooldown
    tool_uv = 'exclude-newer = "14 days"\nexclude-newer-package = { widget = false }'
    pyproject = _write(tmp_path, deps='"widget>=1.0"', tool_uv=tool_uv)

    assert '"widget>=1.2"' in _raise(pyproject)


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_per_package_override_admits_a_young_security_fix(tmp_path: Path) -> None:
    tool_uv = 'exclude-newer = "14 days"\nexclude-newer-package = { widget = "1 day" }'
    pyproject = _write(tmp_path, deps='"widget>=1.0"', tool_uv=tool_uv)

    assert '"widget>=1.2"' in _raise(pyproject)


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_the_cooldown_applies_without_any_python_classifier(tmp_path: Path) -> None:
    pyproject = _write(tmp_path, deps='"widget>=1.0"', tool_uv='exclude-newer = "14 days"', classifiers=False)

    assert '"widget>=1.1"' in _raise(pyproject)


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_floor_at_the_newest_cooled_release_is_up_to_date_not_outdated(tmp_path: Path) -> None:
    pyproject = _write(tmp_path, deps='"widget>=1.1"', tool_uv='exclude-newer = "14 days"')

    [dep] = check_dependencies(pyproject)

    # The deps gate fails on OUTDATED, so a release still inside the cooldown must not count.
    assert dep.status is DependencyStatus.UP_TO_DATE
    assert "cooldown" in dep.latest


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_floor_younger_than_the_cooldown_is_kept_never_lowered(tmp_path: Path) -> None:
    # User decision 2026-10-12 16:06: lowering a floor because of the cooldown dropped real fixes
    # (lib_layered_config 7.1.5 -> 7.1.3) and went below the floors bmk 3.19.0 already published.
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    [dep] = check_dependencies(pyproject)

    assert dep.status is DependencyStatus.ERROR
    assert "cooldown" in dep.latest
    assert '"widget>=1.2"' in _raise(pyproject)


@pytest.mark.os_agnostic
def test_a_floor_no_release_outside_the_cooldown_satisfies_is_an_error_not_ok(tmp_path: Path, pypi: _FakeIndex) -> None:
    # Review L1: every release is younger than the cooldown, so `uv lock` cannot resolve the floor
    # at all; [ok] left only uv's own message to explain the red gate.
    pypi.packages["widget"] = _doc("1.2", {"1.2": _uploaded(3)})
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    [dep] = check_dependencies(pyproject)

    assert dep.status is DependencyStatus.ERROR
    assert "cooldown" in dep.latest


@pytest.mark.os_agnostic
def test_the_report_names_the_release_the_cooldown_holds_back_not_the_absolute_latest(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    # Review L3: 1.2 needs a newer Python, 1.1 is what the cooldown holds back.
    releases = {"1.0": _uploaded(90), "1.1": _uploaded(5), "1.2": _uploaded(2, requires_python=">=3.11")}
    pypi.packages["widget"] = _doc("1.2", releases)
    pyproject = _write(tmp_path, deps='"widget>=1.0"', tool_uv='exclude-newer = "14 days"')

    [dep] = check_dependencies(pyproject)

    assert dep.status is DependencyStatus.UP_TO_DATE
    assert dep.latest.startswith("1.1 ")


@pytest.mark.os_agnostic
def test_a_stale_project_lock_does_not_decide_the_cutoff(tmp_path: Path, pypi: _FakeIndex) -> None:
    # Measured on bmk itself: the project's `uv lock` failed BECAUSE of a too-young floor, so its
    # uv.lock still held an older [tool.uv] that exempted the package, and the floor was never lowered.
    stale = '[options]\nexclude-newer = "0001-01-01T00:00:00Z"\nexclude-newer-span = "P1D"\n\n[options.exclude-newer-package]\nwidget = false\n'
    (tmp_path / "uv.lock").write_text(f"version = 1\n\n{stale}", encoding="utf-8")
    pypi.versions["widget/1.2"] = []
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    [dep] = check_dependencies(pyproject)

    # The stale lock exempted widget, which would read [ok]; the cutoff uv resolves today holds it.
    assert dep.status is DependencyStatus.ERROR
    assert "cooldown" in dep.latest


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_cooldown_uv_refused_stops_the_check_instead_of_disabling_the_cooldown(tmp_path: Path) -> None:
    # uv only warns about "two weeks" and resolves no [options] at all.
    pyproject = _write(tmp_path, deps='"widget>=1.0"', tool_uv='exclude-newer = "two weeks"')

    with pytest.raises(SupplyChainConfigError, match="two weeks"):
        check_dependencies(pyproject)


# --- the cutoff uv resolved, read back from uv.lock --------------------------------------------------

# The canonical [options] uv 0.13 writes into uv.lock (measured 2026-10-12): a relative value becomes an
# ISO span next to a placeholder timestamp, an absolute one a UTC timestamp, and the sign of a span is
# ignored ("5 days ago" and "5 days" lock the same releases).
_PLACEHOLDER = '"0001-01-01T00:00:00Z"'


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("span", "age"),
    [
        ("P14D", timedelta(days=14)),
        ("P2W", timedelta(days=14)),
        ("-P3W", timedelta(days=21)),
        ("PT1H30M", timedelta(hours=1, minutes=30)),
        ("P1DT12H", timedelta(days=1, hours=12)),
        ("PT90S", timedelta(seconds=90)),
    ],
)
def test_a_locked_span_is_counted_back_from_now(span: str, age: timedelta) -> None:
    options = {"exclude-newer": "0001-01-01T00:00:00Z", "exclude-newer-span": span}

    assert ReleasePolicy.from_lock(options, now=_NOW).default == _NOW - age


@pytest.mark.os_agnostic
def test_a_locked_timestamp_is_an_absolute_cutoff() -> None:
    policy = ReleasePolicy.from_lock({"exclude-newer": "2026-10-01T22:00:00Z"}, now=_NOW)

    assert policy.default == datetime(2026, 10, 1, 22, 0, tzinfo=timezone.utc)


@pytest.mark.os_agnostic
def test_locked_per_package_values_exempt_pin_or_span() -> None:
    options = {
        "exclude-newer": "0001-01-01T00:00:00Z",
        "exclude-newer-span": "P14D",
        "exclude-newer-package": {
            "lib-log-rich": False,
            "orjson": "2026-10-01T22:00:00Z",
            "ruff": {"timestamp": "0001-01-01T00:00:00Z", "span": "P1W"},
        },
    }

    policy = ReleasePolicy.from_lock(options, now=_NOW)

    assert policy.cutoff_for("Lib_Log_Rich") is None
    assert policy.cutoff_for("orjson") == datetime(2026, 10, 1, 22, 0, tzinfo=timezone.utc)
    assert policy.cutoff_for("ruff") == _NOW - timedelta(weeks=1)
    assert policy.cutoff_for("widget") == _NOW - timedelta(days=14)


@pytest.mark.os_agnostic
def test_no_locked_cutoff_means_none() -> None:
    assert ReleasePolicy.from_lock({}, now=_NOW) == ReleasePolicy()


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "options",
    [
        {"exclude-newer-span": "P1M"},
        {"exclude-newer-span": "14 days"},
        {"exclude-newer": "yesterday"},
        {"exclude-newer-package": {"x": True}},
        {"exclude-newer-package": {"x": {"span": 14}}},
    ],
)
def test_a_locked_value_bmk_cannot_read_is_refused_not_guessed(options: dict[str, object]) -> None:
    with pytest.raises(SupplyChainConfigError):
        ReleasePolicy.from_lock(options, now=_NOW)


@pytest.mark.os_agnostic
def test_a_cooldown_uv_refused_is_an_error_naming_the_value() -> None:
    # uv only warns about "14 Days" and then locks with NO [options]: the cooldown is silently off.
    with pytest.raises(SupplyChainConfigError, match="14 Days"):
        ReleasePolicy.from_project(exclude_newer="14 Days", packages={}, lock_options={}, now=_NOW)


@pytest.mark.os_agnostic
def test_a_per_package_value_uv_refused_is_an_error_naming_the_package() -> None:
    options = {"exclude-newer": "0001-01-01T00:00:00Z", "exclude-newer-span": "P2D"}

    with pytest.raises(SupplyChainConfigError, match="widget"):
        ReleasePolicy.from_project(exclude_newer="2 days", packages={"widget": "1 dya"}, lock_options=options, now=_NOW)


@pytest.mark.os_agnostic
def test_a_project_without_a_cooldown_needs_no_lock() -> None:
    assert ReleasePolicy.from_project(exclude_newer=None, packages={}, lock_options=None, now=_NOW) == ReleasePolicy()


@pytest.mark.os_agnostic
def test_a_project_with_a_cooldown_but_no_lock_is_an_error() -> None:
    with pytest.raises(SupplyChainConfigError, match=r"uv\.lock"):
        ReleasePolicy.from_project(exclude_newer="2 days", packages={}, lock_options=None, now=_NOW)


@pytest.mark.os_agnostic
def test_a_release_is_admitted_through_any_file_uploaded_before_the_cutoff() -> None:
    late_wheel = _uploaded(30) + _uploaded(1)
    releases = {"1.0": late_wheel, "1.1": _uploaded(2), "1.2": []}

    admitted = admitted_releases(releases, _NOW - timedelta(days=14))

    # uv compares each FILE: the late wheel of 1.0 is dropped, the release stays; 1.1 has nothing left.
    assert list(admitted) == ["1.0"]
    assert len(admitted["1.0"]) == 1


# --- the [tool.uv] block bmk keeps in the project --------------------------------------------------


@pytest.mark.os_agnostic
def test_the_block_is_written_when_absent(tmp_path: Path) -> None:
    pyproject = _write(tmp_path, deps='"widget>=1.0"')

    changes = ensure_uv_cooldown(pyproject, cooldown="14 days", exempt={"lib_log_rich", "lib-cli-exit-tools"})

    uv = rtoml.load(pyproject)["tool"]["uv"]
    assert uv["exclude-newer"] == "14 days"
    assert uv["exclude-newer-package"] == {"lib-cli-exit-tools": False, "lib-log-rich": False}
    assert changes


@pytest.mark.os_agnostic
def test_the_block_keeps_what_the_project_already_chose(tmp_path: Path) -> None:
    tool_uv = '# our own policy\nexclude-newer = "7 days"\nexclude-newer-package = { Lib_Log_Rich = "1 day" }'
    pyproject = _write(tmp_path, deps='"widget>=1.0"', tool_uv=tool_uv)

    ensure_uv_cooldown(pyproject, cooldown="14 days", exempt={"lib_log_rich", "igittigitt"})

    text = pyproject.read_text(encoding="utf-8")
    uv = rtoml.load(pyproject)["tool"]["uv"]
    assert "# our own policy" in text
    assert uv["exclude-newer"] == "7 days"
    assert uv["exclude-newer-package"] == {"Lib_Log_Rich": "1 day", "igittigitt": False}


@pytest.mark.os_agnostic
def test_a_new_block_is_appended_after_everything_the_file_already_says(tmp_path: Path) -> None:
    # Review L4: tomlkit grouped the new table after the FIRST [tool.*] table, above
    # [project.urls] and with no blank line, so the diff touched the middle of the file.
    original = (
        '[project]\nname = "demo"\nversion = "1.0.0"\ndependencies = []\n\n'
        '[tool.ruff]\nline-length = 120\n\n[project.urls]\nHomepage = "https://example.invalid"\n\n'
        "[tool.pyright]\nstrict = []\n"
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(original, encoding="utf-8")

    ensure_uv_cooldown(pyproject, cooldown="2 days", exempt={"lib_log_rich"})

    text = pyproject.read_text(encoding="utf-8")
    assert text.startswith(original + "\n[tool.uv]\n")
    assert rtoml.loads(text)["tool"]["uv"] == {
        "exclude-newer": "2 days",
        "exclude-newer-package": {"lib-log-rich": False},
    }


@pytest.mark.os_agnostic
def test_a_second_run_changes_nothing(tmp_path: Path) -> None:
    pyproject = _write(tmp_path, deps='"widget>=1.0"')
    ensure_uv_cooldown(pyproject, cooldown="14 days", exempt={"lib_log_rich"})
    first = pyproject.read_text(encoding="utf-8")

    changes = ensure_uv_cooldown(pyproject, cooldown="14 days", exempt={"lib_log_rich"})

    assert changes == []
    assert pyproject.read_text(encoding="utf-8") == first


@pytest.mark.os_agnostic
def test_the_exemption_covers_own_packages_reached_through_other_own_packages() -> None:
    requires = {
        "lib-log-rich": ["lib-cli-exit-tools>=2.4.0", "rich>=15", "pydantic>=2"],
        "lib-cli-exit-tools": ["click>=8"],
        "rich": ["lib-log-rich"],  # a foreign package is never walked, whatever it names
    }

    exempt = own_closure(
        ["lib_log_rich", "rich", "demo-tool"],
        own=frozenset({"lib-log-rich", "lib-cli-exit-tools", "demo-tool", "igittigitt"}),
        requires_of=lambda name: requires.get(name, []),
        project="demo_tool",
    )

    # lib-cli-exit-tools is reached only through lib-log-rich; the project never exempts itself.
    assert exempt == {"lib-log-rich", "lib-cli-exit-tools"}


# --- the update path end to end --------------------------------------------------------------------


class _Uv:
    """Records the project lock upgrade and the venv sync ``main`` asks for (the cutoff itself is
    resolved by the real uv)."""

    def __init__(self, project: Path) -> None:
        self.project = project
        self.calls: list[str] = []

    def upgrade(self) -> bool:
        self.calls.append("upgrade")
        return True

    def sync(self) -> bool | None:
        self.calls.append("sync")
        return True


def _update(pyproject: Path, uv: _Uv, settings: SupplyChainSettings) -> int:
    locked = _dependencies.LockedProject(upgrade=uv.upgrade, sync=uv.sync)
    return _dependencies.main(
        update=True, quiet=True, pyproject=pyproject, python="/venv/bin/python", supply_chain=settings, locked=locked
    )


_SETTINGS = SupplyChainSettings(cooldown="14 days", own_packages=frozenset({"lib-log-rich"}))


@pytest.mark.os_agnostic
def test_an_update_writes_the_block_locks_raises_under_it_and_syncs_from_the_lock(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    pypi.packages["lib-log-rich"] = _doc("6.5.1", {"6.3.7": _uploaded(40), "6.5.1": _uploaded(4)})
    pypi.versions["lib-log-rich/6.5.1"] = []
    uv = _Uv(tmp_path)
    pyproject = _write(tmp_path, deps='"widget>=1.0", "lib_log_rich>=6.3.7"')

    code = _update(pyproject, uv, _SETTINGS)

    text = pyproject.read_text(encoding="utf-8")
    assert code == 0
    assert '"widget>=1.1"' in text  # third party: newest outside the cooldown
    assert '"lib_log_rich>=6.5.1"' in text  # own: newest, and lockable (needs nothing young)
    assert rtoml.load(pyproject)["tool"]["uv"] == {
        "exclude-newer": "14 days",
        "exclude-newer-package": {"lib-log-rich": False},
    }
    # Re-locked at the newest admitted releases after the edit, then the venv is brought to that
    # lock instead of pip-installing floors into it.
    assert uv.calls == ["upgrade", "sync"]


@pytest.mark.os_agnostic
def test_an_update_with_nothing_to_raise_still_upgrades_the_lock_and_syncs(tmp_path: Path, pypi: _FakeIndex) -> None:
    # A transitive package can move inside an unchanged manifest; the venv must follow the lock.
    _ = pypi
    uv = _Uv(tmp_path)
    tool_uv = 'exclude-newer = "14 days"'
    pyproject = _write(tmp_path, deps='"widget>=1.1"', tool_uv=tool_uv)

    assert _update(pyproject, uv, SupplyChainSettings(cooldown="14 days", own_packages=frozenset())) == 0

    assert uv.calls == ["upgrade", "sync"]


@pytest.mark.os_agnostic
def test_an_own_floor_rises_only_to_the_newest_release_the_cooldown_can_lock(tmp_path: Path, pypi: _FakeIndex) -> None:
    # Review H3 of 064688b, reproduced with real uv: lib_log_rich 6.5.1 needs orjson>=3.13.0, which is
    # younger than the cooldown, so a floor of >=6.5.1 makes `uv lock` unsatisfiable.
    pypi.packages["lib-log-rich"] = _doc(
        "6.5.1", {"6.0.0": _uploaded(90), "6.3.7": _uploaded(40), "6.5.1": _uploaded(4)}
    )
    pypi.packages["orjson"] = _doc("3.13.0", {"3.10.0": _uploaded(200), "3.13.0": _uploaded(5)})
    pypi.versions["lib-log-rich/6.5.1"] = ["orjson>=3.13.0", "pytest>=8; extra == 'dev'"]
    pypi.versions["lib-log-rich/6.3.7"] = ["orjson>=3.10.0"]
    uv = _Uv(tmp_path)
    pyproject = _write(tmp_path, deps='"lib_log_rich>=6.0.0"')

    assert _update(pyproject, uv, _SETTINGS) == 0

    assert '"lib_log_rich>=6.3.7"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_an_own_floor_the_cooldown_cannot_lock_is_kept_and_what_it_needs_is_pinned(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    # The declared floor 6.5.1 already demands orjson 3.13.0, so that release is pinned rather than
    # the floor lowered to 6.3.7.
    pypi.packages["lib-log-rich"] = _doc("6.5.1", {"6.3.7": _uploaded(40), "6.5.1": _uploaded(4)})
    pypi.packages["orjson"] = _doc("3.13.0", {"3.10.0": _uploaded(200), "3.13.0": _uploaded(5)})
    pypi.versions["lib-log-rich/6.5.1"] = ["orjson>=3.13.0"]
    pypi.versions["lib-log-rich/6.3.7"] = ["orjson>=3.10.0"]
    uv = _Uv(tmp_path)
    pyproject = _write(tmp_path, deps='"lib_log_rich>=6.5.1"')

    assert _update(pyproject, uv, _SETTINGS) == 0

    assert '"lib_log_rich>=6.5.1"' in pyproject.read_text(encoding="utf-8")
    assert _pins(pyproject) == {"orjson": _pin_of(5)}


@pytest.mark.os_agnostic
def test_a_requirement_whose_marker_never_applies_does_not_block_an_own_release(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    pypi.packages["lib-log-rich"] = _doc("6.5.1", {"6.3.7": _uploaded(40), "6.5.1": _uploaded(20)})
    pypi.packages["orjson"] = _doc("3.13.0", {"3.13.0": _uploaded(5)})
    # Only for a dev extra nobody requests, and only below the project's oldest Python.
    pypi.versions["lib-log-rich/6.5.1"] = ["orjson>=3.13.0; extra == 'dev'", "orjson>=3.13.0; python_version < '3.9'"]
    uv = _Uv(tmp_path)
    pyproject = _write(tmp_path, deps='"lib_log_rich>=6.3.7"')

    assert _update(pyproject, uv, _SETTINGS) == 0

    assert '"lib_log_rich>=6.5.1"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_an_exemption_list_is_not_written_while_an_own_package_cannot_be_read(
    tmp_path: Path, pypi: _FakeIndex, capsys: pytest.CaptureFixture[str]
) -> None:
    # Review L2: the walk read an unreachable own package as "requires nothing" and wrote an
    # exemption list missing every own package behind it - the silent older-release case.
    pypi.packages["lib-log-rich"] = _doc("6.5.1", {"6.5.1": _uploaded(40)}, requires=["lib-cli-exit-tools>=2"])
    pyproject = _write(tmp_path, deps='"lib_log_rich>=6.5.1"')
    own = frozenset({"lib-log-rich", "lib-cli-exit-tools", "lib-x", "lib-y"})
    settings = SupplyChainSettings(cooldown="14 days", own_packages=own)
    pypi.packages.pop("widget")
    pypi.packages["lib-cli-exit-tools"] = _doc("2.4.0", {"2.4.0": _uploaded(40)}, requires=["lib-x>=1"])
    pypi.versions["lib-log-rich/6.5.1"] = []
    # lib-x is unreachable, so whether it needs lib-y (it does, say) cannot be known.

    _update(pyproject, _Uv(tmp_path), settings)

    assert "exclude-newer-package" not in pyproject.read_text(encoding="utf-8")
    assert "lib-x" in capsys.readouterr().err


# --- a young floor is pinned at its own upload, never lowered --------------------------------------


def _pin_of(days_ago: float) -> str:
    """The cutoff bmk pins for a release uploaded ``days_ago``: the next whole second after it."""
    uploaded = _NOW - timedelta(days=days_ago)
    return (uploaded.replace(microsecond=0) + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pins(pyproject: Path) -> dict[str, object]:
    """The timestamp entries of ``[tool.uv] exclude-newer-package`` (exemptions left out)."""
    table = rtoml.load(pyproject)["tool"]["uv"].get("exclude-newer-package", {})
    return {name: value for name, value in table.items() if value is not False}


_NO_OWN = SupplyChainSettings(cooldown="14 days", own_packages=frozenset())


@pytest.mark.os_agnostic
def test_a_pin_is_the_next_whole_second_after_the_newest_file_of_the_release() -> None:
    files = [
        {"upload_time_iso_8601": "2026-10-12T00:15:37.721228Z"},
        {"upload_time_iso_8601": "2026-10-12T00:15:41.100000Z"},
    ]

    assert _supply_chain.floor_pin(files) == "2026-10-12T00:15:42Z"


@pytest.mark.os_agnostic
def test_an_update_pins_a_young_floor_at_its_upload_and_keeps_the_floor(tmp_path: Path, pypi: _FakeIndex) -> None:
    _ = pypi
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert '"widget>=1.2"' in pyproject.read_text(encoding="utf-8")
    assert _pins(pyproject) == {"widget": _pin_of(3)}
    # With the pin in place the floor is judged admitted, so the gate reads it as current.
    [dep] = check_dependencies(pyproject)
    assert dep.status is DependencyStatus.UP_TO_DATE


@pytest.mark.os_agnostic
def test_what_a_pinned_release_itself_requires_is_pinned_too(tmp_path: Path, pypi: _FakeIndex) -> None:
    # bmk's own gate, 2026-10-12: pydantic 2.14.1 was pinned, but it requires pydantic-core==2.50.1,
    # uploaded the same evening, and `uv lock` failed on that.
    pypi.packages["gadget"] = _doc("2.0", {"1.0": _uploaded(90), "2.0": _uploaded(2)})
    pypi.versions["widget/1.2"] = ["gadget==2.0"]
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(3), "gadget": _pin_of(2)}


@pytest.mark.os_agnostic
def test_pins_are_written_as_a_tidy_inline_table(tmp_path: Path, pypi: _FakeIndex) -> None:
    pypi.packages["gadget"] = _doc("2.0", {"1.0": _uploaded(90), "2.0": _uploaded(2)})
    tool_uv = 'exclude-newer = "14 days"\nexclude-newer-package = { lib-log-rich = false }'
    pyproject = _write(tmp_path, deps='"widget>=1.2", "gadget>=2.0"', tool_uv=tool_uv)

    _update(pyproject, _Uv(tmp_path), _NO_OWN)

    line = next(x for x in pyproject.read_text(encoding="utf-8").splitlines() if x.startswith("exclude-newer-package"))
    assert line == (
        f'exclude-newer-package = {{lib-log-rich = false, gadget = "{_pin_of(2)}", widget = "{_pin_of(3)}"}}'
    )


@pytest.mark.os_agnostic
def test_a_pin_the_cooldown_has_caught_up_with_is_removed(tmp_path: Path, pypi: _FakeIndex) -> None:
    _ = pypi
    tool_uv = f'exclude-newer = "14 days"\nexclude-newer-package = {{ widget = "{_pin_of(30)}" }}'
    pyproject = _write(tmp_path, deps='"widget>=1.1"', tool_uv=tool_uv)

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    # A timestamp pin replaces the default for its package: left in place it would hold widget at
    # 1.1 for good once the cooldown has passed it.
    assert _pins(pyproject) == {}


@pytest.mark.os_agnostic
def test_a_pin_no_floor_demands_stays_while_the_cooldown_does_not_admit_its_release(
    tmp_path: Path, pypi: _FakeIndex, capsys: pytest.CaptureFixture[str]
) -> None:
    """lsdsk, 2026-10-21: certifi pinned by hand at the very value bmk would write, for a release
    one day old. No declared floor demanded it, so it read as bmk's own, was removed as "the
    cooldown admits it" although the cooldown did not, and the next lock went back to the release
    the pin had been placed to leave behind.
    """
    pypi.packages["gadget"] = _doc("2.0", {"1.0": _uploaded(90), "2.0": _uploaded(2)})
    tool_uv = f'exclude-newer = "14 days"\nexclude-newer-package = {{ gadget = "{_pin_of(2)}" }}'
    pyproject = _write(tmp_path, deps='"widget>=1.0"', tool_uv=tool_uv)

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"gadget": _pin_of(2)}
    err = capsys.readouterr().err
    assert "gadget pin kept" in err
    assert "no declared floor demands it" in err


@pytest.mark.os_agnostic
def test_a_self_reference_of_an_unpublished_project_does_not_freeze_the_pins(tmp_path: Path, pypi: _FakeIndex) -> None:
    """`demo[cli]` in demo's own requirements comes from the source tree, never from PyPI.

    PyPI knowing nothing of an unpublished project used to make every release list "unjudgeable",
    so bmk left all pins as they were - and a pin the cooldown had caught up with then held its
    package at that release for good.
    """
    assert "demo" not in pypi.packages
    tool_uv = f'exclude-newer = "14 days"\nexclude-newer-package = {{ widget = "{_pin_of(30)}" }}'
    pyproject = _write(tmp_path, deps='"widget>=1.1", "demo[cli]"', tool_uv=tool_uv)

    _update(pyproject, _Uv(tmp_path), _NO_OWN)

    assert _pins(pyproject) == {}


@pytest.mark.os_agnostic
def test_a_pin_follows_a_floor_raised_by_hand(tmp_path: Path, pypi: _FakeIndex) -> None:
    pypi.packages["widget"] = _doc("1.2", {"1.0": _uploaded(90), "1.1": _uploaded(5), "1.2": _uploaded(3)})
    tool_uv = f'exclude-newer = "14 days"\nexclude-newer-package = {{ widget = "{_pin_of(5)}" }}'
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv=tool_uv)

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert '"widget>=1.2"' in pyproject.read_text(encoding="utf-8")
    assert _pins(pyproject) == {"widget": _pin_of(3)}


@pytest.mark.os_agnostic
@pytest.mark.parametrize("override", ['"2020-01-01T00:00:00Z"', "false"])
# >=1.2 is younger than the cooldown, so the floor itself would demand a pin (review L2 of 5f02a5b:
# with only >=1.0 the override never competed with a pin and the arm could not fail).
@pytest.mark.parametrize("floor", ["widget>=1.0", "widget>=1.2"])
def test_an_override_the_project_set_itself_is_never_touched(
    tmp_path: Path, pypi: _FakeIndex, override: str, floor: str
) -> None:
    _ = pypi
    tool_uv = f'exclude-newer = "14 days"\nexclude-newer-package = {{ widget = {override} }}'
    pyproject = _write(tmp_path, deps=f'"{floor}"', tool_uv=tool_uv)

    _update(pyproject, _Uv(tmp_path), _NO_OWN)

    assert rtoml.load(pyproject)["tool"]["uv"]["exclude-newer-package"] == {
        "widget": rtoml.loads(f"v = {override}")["v"]
    }


@pytest.mark.os_agnostic
def test_an_own_floor_rises_to_the_newest_release_a_pinned_floor_makes_lockable(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    # bmk itself, 2026-10-12: it declares rtoml>=0.14.0 (one day old), and lib_layered_config 7.1.6
    # needs exactly that, so the pin makes 7.1.6 lockable and the own floor rises to it.
    pypi.packages["lib-log-rich"] = _doc("6.5.1", {"6.3.7": _uploaded(40), "6.5.1": _uploaded(4)})
    pypi.packages["orjson"] = _doc("3.13.0", {"3.10.0": _uploaded(200), "3.13.0": _uploaded(5)})
    pypi.versions["lib-log-rich/6.5.1"] = ["orjson>=3.13.0"]
    pypi.versions["lib-log-rich/6.3.7"] = ["orjson>=3.10.0"]
    pyproject = _write(tmp_path, deps='"orjson>=3.13.0", "lib_log_rich>=6.3.7"')

    assert _update(pyproject, _Uv(tmp_path), _SETTINGS) == 0

    text = pyproject.read_text(encoding="utf-8")
    assert '"orjson>=3.13.0"' in text
    assert '"lib_log_rich>=6.5.1"' in text
    assert _pins(pyproject) == {"orjson": _pin_of(5)}


# Second review of 5f02a5b: `uv lock` is universal, so a requirement behind any marker or extra that
# can apply somewhere needs its pin too - the host's own platform must not decide it.
_GADGET = _doc("2.0", {"1.0": _uploaded(90), "2.0": _uploaded(2)})


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "marker",
    [
        "python_version >= '3.12'",
        "platform_system == 'Windows'",
        "os_name == 'nt'",
        "sys_platform == 'win32'",
        "platform_machine == 'aarch64'",
        "implementation_name == 'pypy'",
        # Third review of 6d1fbe8: values no fixed list of platforms names.
        "platform_machine == 'ppc64le'",
        "sys_platform == 'freebsd'",
        "implementation_name == 'graalpy'",
        "platform_release >= '99'",
        "implementation_version < '3.11'",
        "python_full_version >= '3.11.2' and python_full_version < '3.11.8'",
        "python_version > '3.12'",
        # Fourth review of 1036264: Python literals that are not plain dotted digits, and values that
        # sit between two literals or around a substring.
        "python_version == '3.11.*'",
        "python_full_version == '3.11.*'",
        "python_version in '3.11 3.12'",
        "python_version not in '3.10 3.11'",
        "python_full_version >= '3.12.0rc1'",
        "platform_release > '5.1' and platform_release < '5.2'",
        "'arm' in platform_machine and platform_machine != 'arm'",
        "platform_version == 'a\"b'",
    ],
)
def test_a_requirement_behind_a_marker_that_applies_somewhere_is_pinned_too(
    tmp_path: Path, pypi: _FakeIndex, marker: str
) -> None:
    pypi.packages["gadget"] = _GADGET
    pypi.versions["widget/1.2"] = [f"gadget>=2.0; {marker}"]
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(3), "gadget": _pin_of(2)}


@pytest.mark.os_agnostic
def test_a_requirement_behind_a_requested_extra_is_pinned_too(tmp_path: Path, pypi: _FakeIndex) -> None:
    pypi.packages["gadget"] = _GADGET
    pypi.versions["widget/1.2"] = ["gadget>=2.0; extra == 'fast'"]
    pyproject = _write(tmp_path, deps='"widget[fast]>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(3), "gadget": _pin_of(2)}


@pytest.mark.os_agnostic
@pytest.mark.parametrize("marker", ["extra == 'fast'", "python_version < '3.9'"])
def test_a_requirement_that_applies_nowhere_the_project_runs_is_not_pinned(
    tmp_path: Path, pypi: _FakeIndex, marker: str
) -> None:
    # The negative arm of the two above: an extra the project does not request, a Python below its oldest.
    pypi.packages["gadget"] = _GADGET
    pypi.versions["widget/1.2"] = [f"gadget>=2.0; {marker}"]
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(3)}


@pytest.mark.os_agnostic
def test_no_pin_is_written_when_an_older_upload_already_satisfies_the_floor(tmp_path: Path, pypi: _FakeIndex) -> None:
    # A backport: 1.9.5 is two days old, but 2.0 (a month old) satisfies >=1.9.5 too. A pin at 1.9.5's
    # upload would also admit 2.1, five days old, which nothing asked for.
    pypi.packages["widget"] = _doc(
        "2.1", {"1.9.4": _uploaded(200), "2.0": _uploaded(30), "2.1": _uploaded(5), "1.9.5": _uploaded(2)}
    )
    pyproject = _write(tmp_path, deps='"widget>=1.9.5"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {}


@pytest.mark.os_agnostic
def test_a_pin_goes_to_the_satisfying_release_uploaded_first(tmp_path: Path, pypi: _FakeIndex) -> None:
    # 1.3 satisfies >=1.2 and was uploaded before 1.2: pinning at 1.3's upload admits less.
    pypi.packages["widget"] = _doc("1.3", {"1.1": _uploaded(30), "1.2": _uploaded(3), "1.3": _uploaded(5)})
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(5)}


@pytest.mark.os_agnostic
def test_a_pin_goes_to_a_release_that_installs_on_the_oldest_python(tmp_path: Path, pypi: _FakeIndex) -> None:
    # 1.2 needs Python 3.11 and the project supports 3.10, so only 1.2.1 can serve the floor there.
    pypi.packages["widget"] = _doc(
        "1.2.1",
        {"1.1": _uploaded(30), "1.2": _uploaded(3, requires_python=">=3.11"), "1.2.1": _uploaded(2)},
    )
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(2)}


@pytest.mark.os_agnostic
def test_a_pin_is_still_recognised_after_its_release_gains_a_file(tmp_path: Path, pypi: _FakeIndex) -> None:
    # bmk pinned 1.1 when it had one file; a wheel uploaded later moved the release's newest upload,
    # and the old pin must still read as bmk's own, or it would freeze widget for good.
    pypi.packages["widget"] = _doc("1.1", {"1.0": _uploaded(90), "1.1": [*_uploaded(30), *_uploaded(20)]})
    tool_uv = f'exclude-newer = "14 days"\nexclude-newer-package = {{ widget = "{_pin_of(30)}" }}'
    pyproject = _write(tmp_path, deps='"widget>=1.1"', tool_uv=tool_uv)

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {}


@pytest.mark.os_agnostic
def test_a_standard_pin_table_keeps_its_comments_and_its_form(tmp_path: Path, pypi: _FakeIndex) -> None:
    pypi.packages["gadget"] = _doc("2.0", {"1.0": _uploaded(90), "2.0": _uploaded(40)})
    tool_uv = (
        'exclude-newer = "14 days"\n\n'
        "[tool.uv.exclude-newer-package]\n"
        "# CVE-2026-1234: needs the fix released yesterday\n"
        'gadget = "2026-10-12T00:00:00Z"  # drop after 2026-10-20\n'
    )
    pyproject = _write(tmp_path, deps='"widget>=1.2", "gadget>=1.0"', tool_uv=tool_uv)

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    text = pyproject.read_text(encoding="utf-8")
    assert "[tool.uv.exclude-newer-package]" in text
    assert "# CVE-2026-1234: needs the fix released yesterday" in text
    assert 'gadget = "2026-10-12T00:00:00Z"  # drop after 2026-10-20' in text
    assert _pins(pyproject) == {"gadget": "2026-10-12T00:00:00Z", "widget": _pin_of(3)}


@pytest.mark.os_agnostic
@pytest.mark.parametrize("quiet", [True, False])
def test_a_check_fails_on_a_floor_uv_lock_cannot_satisfy(tmp_path: Path, pypi: _FakeIndex, quiet: bool) -> None:
    # The floor is younger than the cooldown and nothing pins it: `uv lock` fails on it, so the deps
    # gate must fail too rather than leave only uv's own message to explain a red gate later.
    _ = pypi
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    [dep] = check_dependencies(pyproject)
    assert dep.status is DependencyStatus.ERROR
    assert _dependencies.main(quiet=quiet, pyproject=pyproject) == 1


@pytest.mark.os_agnostic
def test_a_check_does_not_fail_when_pypi_could_not_be_read(tmp_path: Path, pypi: _FakeIndex) -> None:
    # An unreadable release list is not a finding about the project: the floor is kept, reported, and
    # the gate stays green, so a PyPI outage cannot block every push.
    pypi.packages.pop("widget")
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _dependencies.main(quiet=True, pyproject=pyproject) == 0


# Third review of 6d1fbe8: the oldest Python a top-level requirement is installed on was decided on the
# host's platform, so a Windows-only floor judged on Linux read as "installs on no Python".
_WINDOWS_312 = "sys_platform == 'win32' and python_version >= '3.12'"


@pytest.mark.os_agnostic
def test_a_platform_gated_floor_is_judged_on_the_python_it_applies_to_on_any_host(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    pypi.packages["gadget"] = _doc("2.0", {"2.0": _uploaded(100, requires_python=">=3.12")})
    pyproject = _write(tmp_path, deps=f'"gadget>=2.0; {_WINDOWS_312}"')

    [dep] = check_dependencies(pyproject)
    assert dep.status is not DependencyStatus.ERROR
    assert _dependencies.main(quiet=True, pyproject=pyproject) == 0


@pytest.mark.os_agnostic
@pytest.mark.parametrize("marker", [_WINDOWS_312, "platform_system == 'Darwin' and python_version >= '3.12'"])
def test_a_young_platform_gated_floor_is_pinned_on_any_host(tmp_path: Path, pypi: _FakeIndex, marker: str) -> None:
    pypi.packages["gadget"] = _doc("2.0", {"1.0": _uploaded(90), "2.0": _uploaded(2, requires_python=">=3.12")})
    pyproject = _write(tmp_path, deps=f'"gadget>=2.0; {marker}"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"gadget": _pin_of(2)}


@pytest.mark.os_agnostic
def test_a_pin_admits_whole_releases_and_walks_what_uv_then_resolves(tmp_path: Path, pypi: _FakeIndex) -> None:
    # 1.3's sdist is five days old, its wheel one. A pin at 1.2 would show uv 1.3's sdist without its
    # wheel, so the pin moves on until 1.3 is whole; uv then resolves 1.3, and 1.3's young
    # requirement is the one that needs a pin.
    pypi.packages["widget"] = _doc(
        "1.3", {"1.1": _uploaded(30), "1.2": _uploaded(3), "1.3": [*_uploaded(5), *_uploaded(1)]}
    )
    pypi.packages["gadget"] = _GADGET
    pypi.versions["widget/1.3"] = ["gadget>=2.0"]
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(1), "gadget": _pin_of(2)}


@pytest.mark.os_agnostic
def test_a_pin_admits_every_file_of_the_release_it_serves(tmp_path: Path, pypi: _FakeIndex) -> None:
    # bmk's own gate, 2026-10-12: a pin after pydantic-core's FIRST wheel locked one macOS wheel of
    # dozens. Real releases upload many files over minutes; the pin must come after the last of them.
    pypi.packages["widget"] = _doc("1.2", {"1.1": _uploaded(30), "1.2": [*_uploaded(3), *_uploaded(2.9)]})
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(2.9)}


@pytest.mark.os_agnostic
def test_releases_uploaded_in_the_same_second_walk_the_highest(tmp_path: Path, pypi: _FakeIndex) -> None:
    same = _uploaded(3)
    pypi.packages["widget"] = _doc("2.0", {"1.1": _uploaded(30), "1.9.5": same, "2.0": same})
    pypi.packages["gadget"] = _GADGET
    pypi.versions["widget/2.0"] = ["gadget>=2.0"]
    pyproject = _write(tmp_path, deps='"widget>=1.9.5"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(3), "gadget": _pin_of(2)}


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "marker", ["python_version == '3.11.*'", "python_version in '3.11 3.12'", "python_full_version >= '3.11.0rc1'"]
)
def test_a_floor_gated_to_newer_pythons_by_any_spelling_is_judged_there(
    tmp_path: Path, pypi: _FakeIndex, marker: str
) -> None:
    pypi.packages["gadget"] = _doc("2.0", {"2.0": _uploaded(100, requires_python=">=3.11")})
    pyproject = _write(tmp_path, deps=f'"gadget>=2.0; {marker}"')

    assert _dependencies.main(quiet=True, pyproject=pyproject) == 0


@pytest.mark.os_agnostic
@pytest.mark.parametrize("marker", ["python_full_version >= '3.11.0rc1'", "python_version not in '3.9 3.10'"])
def test_the_oldest_python_of_a_gated_floor_is_never_a_far_future_one(
    tmp_path: Path, pypi: _FakeIndex, marker: str
) -> None:
    # Capped below 3.20: an "oldest" Python of 3.50 would read as installing on nothing.
    pypi.packages["gadget"] = _doc("2.0", {"2.0": _uploaded(100, requires_python=">=3.11,<3.20")})
    pyproject = _write(tmp_path, deps=f'"gadget>=2.0; {marker}"')

    assert _dependencies.main(quiet=True, pyproject=pyproject) == 0


@pytest.mark.os_agnostic
def test_the_pin_waits_for_a_release_seen_only_through_a_file_that_does_not_install(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    # At 1.2's pin, 1.3 shows only a file needing Python 3.12, so the pin moves on until 1.3 is whole,
    # and the walk follows 1.3, which needs nothing young; 1.2's requirement is then not uv's choice.
    pypi.packages["widget"] = _doc(
        "1.3",
        {
            "1.1": _uploaded(30),
            "1.2": _uploaded(5),
            "1.3": [*_uploaded(6, requires_python=">=3.12"), *_uploaded(1)],
        },
    )
    pypi.packages["gadget"] = _GADGET
    pypi.versions["widget/1.2"] = ["gadget>=2.0"]
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(1)}


@pytest.mark.os_agnostic
def test_a_pin_never_cuts_through_the_files_of_a_higher_release(tmp_path: Path, pypi: _FakeIndex) -> None:
    # Fifth review: at 1.9's pin, 2.0's sdist is visible and its wheel is not, so uv would lock 2.0 with
    # the sdist alone. The pin moves on to where 2.0 is whole.
    pypi.packages["widget"] = _doc(
        "2.0", {"1.8": _uploaded(30), "1.9": _uploaded(3), "2.0": [*_uploaded(5), *_uploaded(1)]}
    )
    pyproject = _write(tmp_path, deps='"widget>=1.9"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(1)}


@pytest.mark.os_agnostic
def test_a_floor_release_the_cooldown_cuts_gets_a_whole_release_pin(tmp_path: Path, pypi: _FakeIndex) -> None:
    # pydantic-core 2.50.1, 2026-10-12: 137 files over four minutes straddled the 1-day cutoff. uv
    # would lock the release with only its older files, so the floor needs a pin admitting it whole.
    pypi.packages["gadget"] = _doc("2.0", {"2.0": [*_uploaded(15), *_uploaded(13)]})
    pyproject = _write(tmp_path, deps='"gadget>=2.0"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"gadget": _pin_of(13)}


@pytest.mark.os_agnostic
def test_an_existing_pin_for_a_cut_floor_release_is_kept_as_demanded(
    tmp_path: Path, pypi: _FakeIndex, capsys: pytest.CaptureFixture[str]
) -> None:
    pypi.packages["gadget"] = _doc("2.0", {"2.0": [*_uploaded(15), *_uploaded(13)]})
    tool_uv = f'exclude-newer = "14 days"\nexclude-newer-package = {{ gadget = "{_pin_of(13)}" }}'
    pyproject = _write(tmp_path, deps='"gadget>=2.0"', tool_uv=tool_uv)

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"gadget": _pin_of(13)}
    assert "no declared floor demands it" not in capsys.readouterr().err


@pytest.mark.os_agnostic
def test_a_floor_release_the_cooldown_admits_whole_needs_no_pin(tmp_path: Path, pypi: _FakeIndex) -> None:
    pypi.packages["gadget"] = _doc("2.0", {"2.0": [*_uploaded(16), *_uploaded(15)]})
    pyproject = _write(tmp_path, deps='"gadget>=2.0"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {}


@pytest.mark.os_agnostic
def test_a_release_whose_installable_file_has_no_upload_time_leaves_the_pins_alone(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    untimed = {"requires_python": ">=3.10", "yanked": False}
    pypi.packages["widget"] = _doc(
        "1.2", {"1.1": _uploaded(30), "1.2": [*_uploaded(3, requires_python=">=3.12"), untimed]}
    )
    pyproject = _write(tmp_path, deps='"widget>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {}


@pytest.mark.os_agnostic
def test_extras_the_marker_does_not_name_do_not_widen_the_search(tmp_path: Path, pypi: _FakeIndex) -> None:
    # Fifth review: every requested extra was an axis of its own, so a package requested with many
    # extras pushed ordinary markers past the cap, where they were taken to apply.
    pypi.packages["gadget"] = _GADGET
    pypi.versions["widget/1.2"] = [
        "gadget>=2.0; python_version < '3.9' and extra == 'sqs' and platform_machine != 'a' and sys_platform != 'b'"
    ]
    extras = ",".join(f"x{i}" for i in range(40))
    pyproject = _write(tmp_path, deps=f'"widget[{extras}]>=1.2"', tool_uv='exclude-newer = "14 days"')

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert _pins(pyproject) == {"widget": _pin_of(3)}


@pytest.mark.os_agnostic
def test_a_standard_pin_table_left_empty_is_removed(tmp_path: Path, pypi: _FakeIndex) -> None:
    _ = pypi
    tool_uv = f'exclude-newer = "14 days"\n\n[tool.uv.exclude-newer-package]\nwidget = "{_pin_of(30)}"\n'
    pyproject = _write(tmp_path, deps='"widget>=1.1"', tool_uv=tool_uv)

    assert _update(pyproject, _Uv(tmp_path), _NO_OWN) == 0

    assert "exclude-newer-package" not in pyproject.read_text(encoding="utf-8")


# --- [bmk.supply_chain] ------------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_an_empty_section_keeps_the_defaults() -> None:
    settings = SupplyChainSettings.from_config({})

    # User decision 2026-10-19: seven days, raised from the one day chosen 2026-10-12 once the
    # fleet's own projects had moved to it.
    assert settings.cooldown == "7 days"
    assert "lib-log-rich" in settings.own_packages


@pytest.mark.os_agnostic
def test_the_shipped_section_sets_the_same_cooldown() -> None:
    # The shipped file, not the constant, is what an installed bmk reads, so the two must agree.
    shipped = get_default_config_path().parent / "defaultconfig.d" / "10-bmk.toml"
    section = rtoml.load(shipped)["bmk"]["supply_chain"]

    assert SupplyChainSettings.from_config(section).cooldown == "7 days"


@pytest.mark.os_agnostic
def test_a_configured_own_list_replaces_the_default_and_is_normalized() -> None:
    settings = SupplyChainSettings.from_config({"cooldown": "7 days", "own_packages": ["My_Lib"]})

    assert settings == SupplyChainSettings(cooldown="7 days", own_packages=frozenset({"my-lib"}))


@pytest.mark.os_agnostic
@pytest.mark.parametrize("section", [{"cooldown": "1 month"}, {"own_packages": "lib_log_rich"}])
def test_a_misconfigured_section_is_refused(section: dict[str, object]) -> None:
    with pytest.raises(SupplyChainConfigError):
        SupplyChainSettings.from_config(section)


# Each of these was accepted by bmk and written into projects, while uv 0.13 refuses it and then
# silently ignores the WHOLE [tool.uv] block (review H1/H2 of 064688b, probed against real uv).
@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "cooldown",
    [False, True, 14, "14 Days", "14 DAYS", "1 WEEK", "14D", "2W", " 14 days ", "\t14 days", "14 days,", "P14DT"],
)
def test_a_cooldown_uv_would_refuse_is_never_accepted_for_writing(cooldown: object) -> None:
    with pytest.raises(SupplyChainConfigError):
        SupplyChainSettings.from_config({"cooldown": cooldown})


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "cooldown", ["2 days", "1 day", "7 days", "2 weeks", "1 week", "36 hours", "P7D", "P2W", "PT36H"]
)
def test_a_cooldown_both_uv_and_bmk_read_is_accepted(cooldown: str) -> None:
    assert SupplyChainSettings.from_config({"cooldown": cooldown}).cooldown == cooldown
