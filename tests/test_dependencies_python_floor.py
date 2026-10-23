"""A raised floor must stay installable on the oldest Python the project supports.

PyPI is the one external edge here, so the tests replace ``httpx2.stream`` with a fake index
serving canned JSON per package, and drive ``check_dependencies`` / ``update_dependencies`` on
a real ``pyproject.toml``.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import httpx2
import orjson
import pytest
import rtoml
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

from bmk.adapters.stagerunner.helpers import _dependencies
from bmk.adapters.stagerunner.helpers._dependencies import (
    DependencyStatus,
    check_dependencies,
    update_dependencies,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path


def _release(requires_python: str | None, *, yanked: bool = False) -> list[dict[str, Any]]:
    return [{"requires_python": requires_python, "yanked": yanked, "filename": "x.whl"}]


# hypothesis as published on 2026-10-11: 6.169.0 is the first release that drops Python 3.10.
_HYPOTHESIS: dict[str, Any] = {
    "info": {"version": "6.169.0"},
    "releases": {
        "6.168.4": _release(">=3.10"),
        "6.168.5": _release(">=3.10"),
        "6.169.0": _release(">=3.11"),
    },
}


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self) -> Iterator[bytes]:
        yield self._body


class _FakeIndex:
    """Serves ``https://pypi.org/pypi/<name>/json`` from a dict, the way ``httpx2.stream`` would."""

    def __init__(self, packages: dict[str, dict[str, Any]]) -> None:
        self._packages = dict(packages)
        self._failures: dict[str, tuple[int, Exception]] = {}
        self.fetches: Counter[str] = Counter()

    def serve(self, name: str, data: dict[str, Any]) -> None:
        self._packages[name] = data

    def fail_from(self, name: str, *, fetch: int, error: Exception) -> None:
        """Raise ``error`` on the ``fetch``-th request for ``name`` and every one after it."""
        self._failures[name] = (fetch, error)

    @contextmanager
    def stream(self, method: str, url: str, **_: object) -> Generator[_FakeResponse]:
        assert method == "GET"
        name = url.removeprefix("https://pypi.org/pypi/").removesuffix("/json")
        self.fetches[name] += 1
        failure = self._failures.get(name)
        if failure is not None and self.fetches[name] >= failure[0]:
            raise failure[1]
        yield _FakeResponse(orjson.dumps(self._packages[name]))


@pytest.fixture
def pypi(monkeypatch: pytest.MonkeyPatch) -> _FakeIndex:
    index = _FakeIndex({"hypothesis": _HYPOTHESIS})
    monkeypatch.setattr(_dependencies.httpx2, "stream", index.stream)
    return index


def _write_pyproject(tmp_path: Path, *, dev: str, python: str = 'requires-python = ">=3.10"') -> Path:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "demo"\n'
        'version = "1.0.0"\n'
        f"{python}\n"
        "classifiers = [\n"
        '  "Programming Language :: Python :: 3.10",\n'
        '  "Programming Language :: Python :: 3.14",\n'
        "]\n"
        "dependencies = []\n"
        "\n"
        "[project.optional-dependencies]\n"
        f"dev = [\n  {dev},\n]\n",
        encoding="utf-8",
    )
    return pyproject


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_the_floor_rises_only_to_the_newest_release_the_oldest_supported_python_can_install(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4"')

    deps = check_dependencies(pyproject)
    updated = update_dependencies(deps, pyproject, quiet=True)

    assert updated == 1
    assert '"hypothesis>=6.168.5"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_floor_already_at_the_newest_installable_release_is_not_outdated(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.5"')

    (dep,) = check_dependencies(pyproject)

    assert dep.status is not DependencyStatus.OUTDATED
    assert update_dependencies([dep], pyproject, quiet=True) == 0


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_marker_that_limits_the_dependency_to_newer_pythons_lets_its_floor_follow_them(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, dev="\"hypothesis>=6.168.4; python_version >= '3.11'\"")

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert "\"hypothesis>=6.169.0; python_version >= '3.11'\"" in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_project_that_states_no_python_versions_still_follows_the_latest_release(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\ndependencies = ["hypothesis>=6.168.4"]\n',
        encoding="utf-8",
    )

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"hypothesis>=6.169.0"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_a_yanked_release_is_never_chosen_as_the_fallback(tmp_path: Path, pypi: _FakeIndex) -> None:
    pypi_data = {
        "info": {"version": "6.169.0"},
        "releases": {
            "6.168.4": _release(">=3.10"),
            "6.168.5": _release(">=3.10", yanked=True),
            "6.169.0": _release(">=3.11"),
        },
    }
    pypi.serve("hypothesis", pypi_data)
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.3"')

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"hypothesis>=6.168.4"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_a_lookup_failing_after_the_first_fetch_does_not_raise_the_floor_past_the_oldest_python(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    pypi.fail_from("hypothesis", fetch=2, error=httpx2.TimeoutException("read timed out"))
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4"')

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"hypothesis>=6.168.5"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_each_package_is_fetched_from_pypi_once(tmp_path: Path, pypi: _FakeIndex) -> None:
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4,<7"')

    check_dependencies(pyproject)

    assert pypi.fetches == Counter({"hypothesis": 1})


@pytest.mark.os_agnostic
def test_a_release_list_pypi_did_not_send_keeps_the_floor_and_says_why(tmp_path: Path, pypi: _FakeIndex) -> None:
    pypi.serve("hypothesis", {"info": {"version": "6.169.0"}})
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4"')

    (dep,) = check_dependencies(pyproject)

    assert dep.status is DependencyStatus.ERROR
    assert "floor kept" in dep.latest
    assert update_dependencies([dep], pyproject, quiet=True) == 0
    assert '"hypothesis>=6.168.4"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "error",
    [httpx2.ReadError("connection reset"), httpx2.RemoteProtocolError("peer closed the connection")],
    ids=["read-error", "remote-protocol-error"],
)
def test_a_transport_error_from_pypi_is_reported_rather_than_raised(
    tmp_path: Path, pypi: _FakeIndex, error: Exception
) -> None:
    pypi.fail_from("hypothesis", fetch=1, error=error)
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4"')

    (dep,) = check_dependencies(pyproject)

    assert dep.status is DependencyStatus.ERROR


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_floor_the_oldest_python_cannot_install_is_lowered_to_the_newest_release_it_can(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.169.0"')

    (dep,) = check_dependencies(pyproject)
    updated = update_dependencies([dep], pyproject, quiet=True)

    assert "does not install on Python 3.10" in dep.latest
    assert updated == 1
    assert '"hypothesis>=6.168.5"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_an_uninstallable_floor_is_lowered_even_when_a_newer_release_exists(tmp_path: Path, pypi: _FakeIndex) -> None:
    newer = {**_HYPOTHESIS["releases"], "6.170.0": _release(">=3.11")}
    pypi.serve("hypothesis", {"info": {"version": "6.170.0"}, "releases": newer})
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.169.0"')

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"hypothesis>=6.168.5"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_floor_the_oldest_python_installs_is_never_lowered(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.5"')
    before = pyproject.read_text(encoding="utf-8")

    (dep,) = check_dependencies(pyproject)

    assert dep.status is DependencyStatus.PINNED
    assert update_dependencies([dep], pyproject, quiet=True) == 0
    assert pyproject.read_text(encoding="utf-8") == before


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_floor_whose_marker_excludes_the_oldest_python_is_not_lowered(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, dev="\"hypothesis>=6.169.0; python_version >= '3.11'\"")
    before = pyproject.read_text(encoding="utf-8")

    (dep,) = check_dependencies(pyproject)

    assert dep.status is DependencyStatus.UP_TO_DATE
    assert update_dependencies([dep], pyproject, quiet=True) == 0
    assert pyproject.read_text(encoding="utf-8") == before


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
@pytest.mark.parametrize(
    "requires_python",
    ['requires-python = ">=3.10.1"', 'requires-python = "==3.10.12"'],
    ids=["patch-floor", "exact-patch"],
)
def test_a_requires_python_naming_a_patch_still_holds_the_floor_to_that_python(
    tmp_path: Path, requires_python: str
) -> None:
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4"', python=requires_python)

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"hypothesis>=6.168.5"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_patch_floor_without_classifiers_still_holds_the_floor_to_that_python(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\nrequires-python = ">=3.10.1"\n'
        'dependencies = ["hypothesis>=6.168.4"]\n',
        encoding="utf-8",
    )

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"hypothesis>=6.168.5"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_marker_on_the_full_python_version_is_judged_on_the_patch_it_names(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, dev="\"hypothesis>=6.168.4; python_full_version >= '3.10.1'\"")

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert "\"hypothesis>=6.168.5; python_full_version >= '3.10.1'\"" in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ('"hypothesis>=6.168.3,!=6.168.5"', '"hypothesis>=6.168.4,!=6.168.5"'),
        ('"hypothesis>=6.168.3,<=6.168.4"', '"hypothesis>=6.168.4,<=6.168.4"'),
    ],
    ids=["exclusion", "inclusive-upper-bound"],
)
def test_the_held_floor_satisfies_the_requirements_own_bounds(tmp_path: Path, declared: str, expected: str) -> None:
    pyproject = _write_pyproject(tmp_path, dev=declared)

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert expected in pyproject.read_text(encoding="utf-8")


def _with_old_releases(pypi: _FakeIndex) -> None:
    """Add releases the way old PyPI uploads look: one for 3.8, one with no Requires-Python at all."""
    releases = {**_HYPOTHESIS["releases"], "5.0.0": _release(None), "6.0.0": _release(">=3.8")}
    pypi.serve("hypothesis", {"info": {"version": "6.169.0"}, "releases": releases})


@pytest.mark.os_agnostic
def test_a_requires_python_older_than_every_classifier_does_not_drag_the_floor_down(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    _with_old_releases(pypi)
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4"', python='requires-python = ">=3.8"')

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"hypothesis>=6.168.5"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_a_requires_python_with_no_lower_bound_states_no_oldest_python(tmp_path: Path, pypi: _FakeIndex) -> None:
    _with_old_releases(pypi)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\nrequires-python = "<4"\ndependencies = ["hypothesis>=6.168.4"]\n',
        encoding="utf-8",
    )

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"hypothesis>=6.169.0"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
def test_a_requires_python_above_the_lowest_classifier_still_narrows_it(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4"', python='requires-python = ">=3.11"')

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"hypothesis>=6.169.0"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
@pytest.mark.parametrize(
    "declared",
    ['"hypothesis<=7,>=6.168.5"', '"hypothesis!=6.169.0,>=6.168.5"'],
    ids=["upper-bound-first", "exclusion-first"],
)
def test_a_cap_or_exclusion_written_before_the_floor_is_not_read_as_the_floor(tmp_path: Path, declared: str) -> None:
    pyproject = _write_pyproject(tmp_path, dev=declared)

    (dep,) = check_dependencies(pyproject)

    assert dep.current_min == "6.168.5"
    assert dep.status is not DependencyStatus.OUTDATED


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("hypothesis>=6.168.3,<=6.168.4", "hypothesis>=6.168.4,<=6.168.4"),
        ("hypothesis>=6.168.3,!=6.169.0", "hypothesis>=6.168.5,!=6.169.0"),
    ],
    ids=["inclusive-cap", "exclusion"],
)
def test_a_project_that_states_no_python_versions_keeps_the_floor_inside_its_own_bounds(
    tmp_path: Path, pypi: _FakeIndex, declared: str, expected: str
) -> None:
    """With no Python to hold the floor to, only the main path judges it, and ``<=`` and ``!=`` bound it too."""
    releases = {v: _release(">=3.10") for v in ("6.168.3", "6.168.4", "6.168.5", "6.169.0")}
    pypi.serve("hypothesis", {"info": {"version": "6.169.0"}, "releases": releases})
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f'[project]\nname = "demo"\nversion = "1.0.0"\ndependencies = ["{declared}"]\n', encoding="utf-8"
    )

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)
    (written,) = rtoml.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]

    assert written == expected


@pytest.mark.os_agnostic
def test_a_requirement_with_only_an_upper_bound_is_never_reported_outdated(tmp_path: Path, pypi: _FakeIndex) -> None:
    pypi.serve("foo", {"info": {"version": "2.5"}, "releases": {v: _release(">=3.8") for v in ("1.0", "2.0", "2.5")}})
    pyproject = _write_pyproject(tmp_path, dev='"foo<=3"')

    (dep,) = check_dependencies(pyproject)

    assert dep.status is not DependencyStatus.OUTDATED


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "releases",
    [{}, {"6.168.5": [], "6.169.0": []}, {"6.168.5": {"requires_python": ">=3.10"}}],
    ids=["no-releases", "no-files", "not-a-file-list"],
)
def test_a_release_list_with_nothing_installable_keeps_the_floor(
    tmp_path: Path, pypi: _FakeIndex, releases: dict[str, Any]
) -> None:
    pypi.serve("hypothesis", {"info": {"version": "6.169.0"}, "releases": releases})
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4"')

    (dep,) = check_dependencies(pyproject)

    assert dep.status is DependencyStatus.ERROR
    assert update_dependencies([dep], pyproject, quiet=True) == 0
    assert '"hypothesis>=6.168.4"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.usefixtures("pypi")
@pytest.mark.parametrize(
    "declared",
    ['"hypothesis>6.168.4"', '"hypothesis>6.169.0"', '"hypothesis>6.168.5"'],
    ids=["raised", "lowered-from-uninstallable", "already-uninstallable"],
)
def test_a_strict_floor_is_written_as_an_inclusive_one_on_the_release_it_was_held_to(
    tmp_path: Path, declared: str
) -> None:
    pyproject = _write_pyproject(tmp_path, dev=declared)

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"hypothesis>=6.168.5"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_a_corrupt_response_body_is_reported_rather_than_raised(tmp_path: Path, pypi: _FakeIndex) -> None:
    pypi.fail_from("hypothesis", fetch=1, error=httpx2.DecodingError("bad gzip"))
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4"')

    (dep,) = check_dependencies(pyproject)

    assert dep.status is DependencyStatus.ERROR


def _serve_pkg(pypi: _FakeIndex, latest: str, releases: dict[str, list[dict[str, Any]]]) -> None:
    pypi.serve("pkg", {"info": {"version": latest}, "releases": releases})


@pytest.mark.os_agnostic
@pytest.mark.parametrize("declared", ['"pkg>=8.0rc1"', '"pkg==8.0rc1"'], ids=["floor", "pin"])
def test_a_prerelease_floor_that_installs_is_never_lowered(tmp_path: Path, pypi: _FakeIndex, declared: str) -> None:
    _serve_pkg(pypi, "8.0", {"7.0": _release(">=3.10"), "8.0rc1": _release(">=3.10"), "8.0": _release(">=3.11")})
    pyproject = _write_pyproject(tmp_path, dev=declared)
    before = pyproject.read_text(encoding="utf-8")

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert pyproject.read_text(encoding="utf-8") == before


@pytest.mark.os_agnostic
def test_a_post_release_floor_that_does_not_install_is_lowered_and_settles(tmp_path: Path, pypi: _FakeIndex) -> None:
    _serve_pkg(pypi, "8.0", {"7.0": _release(">=3.10"), "7.0.post1": _release(">=3.11"), "8.0": _release(">=3.11")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=7.0.post1"')

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)
    (settled,) = check_dependencies(pyproject)

    assert '"pkg>=7.0"' in pyproject.read_text(encoding="utf-8")
    assert settled.status is not DependencyStatus.OUTDATED


@pytest.mark.os_agnostic
def test_an_exact_pin_on_a_yanked_release_that_installs_is_never_lowered(tmp_path: Path, pypi: _FakeIndex) -> None:
    yanked = _release(">=3.10", yanked=True)
    _serve_pkg(pypi, "8.0", {"6.0": _release(">=3.10"), "6.5": yanked, "8.0": _release(">=3.11")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg==6.5"')

    (dep,) = check_dependencies(pyproject)

    assert dep.status is not DependencyStatus.OUTDATED


# An exact pin names one release on purpose (a byte-determinism test pinned to one pack, say), so
# the update holds it as written whichever way the floor logic would move it.
_EXACT_PINS = ['"pkg==7.0"', '"pkg===7.0"', '"pkg[cli]==7.0"', "\"pkg==7.0; python_version >= '3.10'\""]


@pytest.mark.os_agnostic
@pytest.mark.parametrize("declared", _EXACT_PINS, ids=["eq", "arbitrary-eq", "extras", "marker"])
def test_an_exact_pin_with_a_newer_release_is_held_as_written(tmp_path: Path, pypi: _FakeIndex, declared: str) -> None:
    _serve_pkg(pypi, "8.0", {"7.0": _release(">=3.10"), "8.0": _release(">=3.10")})
    pyproject = _write_pyproject(tmp_path, dev=declared)
    before = pyproject.read_text(encoding="utf-8")

    (dep,) = check_dependencies(pyproject)
    updated = update_dependencies([dep], pyproject, quiet=True)

    assert dep.status is DependencyStatus.PINNED
    assert updated == 0
    assert pyproject.read_text(encoding="utf-8") == before


@pytest.mark.os_agnostic
def test_an_exact_pin_the_oldest_python_cannot_install_is_never_lowered(tmp_path: Path, pypi: _FakeIndex) -> None:
    _serve_pkg(pypi, "8.0", {"7.0": _release(">=3.10"), "8.0": _release(">=3.11")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg==8.0"')
    before = pyproject.read_text(encoding="utf-8")

    (dep,) = check_dependencies(pyproject)
    updated = update_dependencies([dep], pyproject, quiet=True)

    assert dep.status is not DependencyStatus.OUTDATED
    assert updated == 0
    assert pyproject.read_text(encoding="utf-8") == before


@pytest.mark.os_agnostic
@pytest.mark.parametrize("declared", ['"pkg=1.0.post1"', '"pkg=1.0,<2.dev1"'], ids=["floor", "ceiling"])
def test_a_requirement_that_does_not_parse_is_reported_rather_than_raised(
    tmp_path: Path, pypi: _FakeIndex, declared: str
) -> None:
    _serve_pkg(pypi, "8.0", {"7.0": _release(">=3.10"), "8.0": _release(">=3.11")})
    pyproject = _write_pyproject(tmp_path, dev=declared)

    (dep,) = check_dependencies(pyproject)

    assert dep.status is not DependencyStatus.OUTDATED


@pytest.mark.os_agnostic
def test_the_report_names_the_floor_as_written(tmp_path: Path, pypi: _FakeIndex) -> None:
    _serve_pkg(pypi, "8.0", {"7.0": _release(">=3.10"), "8.0": _release(">=3.11")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg>7.0"')

    (dep,) = check_dependencies(pyproject)

    assert "floor >7.0 does not install on Python 3.10" in dep.latest


@pytest.mark.os_agnostic
def test_a_prerelease_the_floor_does_not_name_does_not_make_it_installable(tmp_path: Path, pypi: _FakeIndex) -> None:
    _serve_pkg(pypi, "8.0", {"7.0": _release(">=3.10"), "8.0": _release(">=3.11"), "8.1b1": _release(">=3.10")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=8.0"')

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)

    assert '"pkg>=7.0"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.parametrize("declared", ['"pkg>=1.0.a1"', '"pkg>=1.0.rc1"'], ids=["dotted-alpha", "dotted-rc"])
def test_a_dotted_prerelease_floor_is_read_and_rewritten_whole(tmp_path: Path, pypi: _FakeIndex, declared: str) -> None:
    _serve_pkg(pypi, "8.0", {"7.0": _release(">=3.10"), "8.0": _release(">=3.11")})
    pyproject = _write_pyproject(tmp_path, dev=declared)

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)

    assert '"pkg>=7.0"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_a_wildcard_pin_moved_to_a_post_release_stays_a_valid_wildcard(tmp_path: Path, pypi: _FakeIndex) -> None:
    _serve_pkg(pypi, "8.0.post1", {"7.0": _release(">=3.10"), "8.0.post1": _release(">=3.10")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg==1.*"')

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)

    assert '"pkg==8.0.*"' in pyproject.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_a_floor_with_an_epoch_is_rewritten_to_a_valid_requirement(tmp_path: Path, pypi: _FakeIndex) -> None:
    _serve_pkg(pypi, "8.0", {"7.0": _release(">=3.10"), "8.0": _release(">=3.11")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=1!1.0"')

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)
    (written,) = rtoml.loads(pyproject.read_text(encoding="utf-8"))["project"]["optional-dependencies"]["dev"]

    assert Requirement(written).name == "pkg"


def _written_dev(pyproject: Path) -> str:
    (written,) = rtoml.loads(pyproject.read_text(encoding="utf-8"))["project"]["optional-dependencies"]["dev"]
    return str(written)


# Versions are ordered as PEP 440 orders them. A leading-digits tuple ties every release that
# differs only in a post, pre or dev part, and reads an epoch as the whole version, so the tie is
# broken by string order: "1.0.post2" > "1.0.post10", "1!9.0" > "1!10.0".


@pytest.mark.os_agnostic
def test_a_post_release_numbered_past_nine_is_newer_than_one_below_it(tmp_path: Path, pypi: _FakeIndex) -> None:
    _serve_pkg(pypi, "1.0.post10", {"1.0.post2": _release(">=3.10"), "1.0.post10": _release(">=3.10")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=1.0.post2"')

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)

    assert _written_dev(pyproject) == "pkg>=1.0.post10"


@pytest.mark.os_agnostic
def test_a_floor_below_a_newer_release_in_the_same_epoch_is_raised(tmp_path: Path, pypi: _FakeIndex) -> None:
    _serve_pkg(pypi, "1!9.0", {"1!7.0": _release(">=3.10"), "1!9.0": _release(">=3.10")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=1!7.0"')

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)

    assert _written_dev(pyproject) == "pkg>=1!9.0"


@pytest.mark.os_agnostic
def test_an_epoch_floor_the_oldest_python_cannot_install_is_lowered_to_the_newest_one_it_can(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    releases = {"1!9.0": _release(">=3.10"), "1!10.0": _release(">=3.10"), "1!11.0": _release(">=3.11")}
    _serve_pkg(pypi, "1!11.0", releases)
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=1!11.0"')

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)

    assert _written_dev(pyproject) == "pkg>=1!10.0"


# uv takes a prerelease when the requirement names one, or when the package publishes nothing else.


@pytest.mark.os_agnostic
def test_a_prerelease_floor_on_a_package_with_only_prereleases_is_lowered_to_the_one_that_installs(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    _serve_pkg(pypi, "8.0b2", {"8.0b1": _release(">=3.10"), "8.0b2": _release(">=3.11")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=8.0b2"')

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)

    assert _written_dev(pyproject) == "pkg>=8.0b1"


@pytest.mark.os_agnostic
def test_a_prerelease_floor_that_does_not_install_is_lowered_to_the_newest_prerelease_that_does(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    releases = {"7.0": _release(">=3.10"), "8.0b1": _release(">=3.10"), "8.0b2": _release(">=3.11")}
    _serve_pkg(pypi, "8.0b2", releases)
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=8.0b2"')

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)

    assert _written_dev(pyproject) == "pkg>=8.0b1", "the floor names a prerelease, so uv takes 8.0b1 over 7.0"


@pytest.mark.os_agnostic
def test_a_final_floor_on_a_package_with_only_prereleases_follows_the_one_uv_would_install(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    _serve_pkg(pypi, "8.0b2", {"8.0b1": _release(">=3.10"), "8.0b2": _release(">=3.11")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=1.0"')

    (dep,) = check_dependencies(pyproject)
    update_dependencies([dep], pyproject, quiet=True)

    assert dep.status is not DependencyStatus.ERROR, dep.latest
    assert _written_dev(pyproject) == "pkg>=8.0b1"


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "declared", ['"pkg>=1.0c1"', '"pkg>=1.0RC1"', '"pkg>=1.0.c1"'], ids=["c", "upper-rc", "dotted-c"]
)
def test_a_rewrite_that_would_not_be_valid_pep_508_is_never_written(
    tmp_path: Path, pypi: _FakeIndex, capsys: pytest.CaptureFixture[str], declared: str
) -> None:
    _serve_pkg(pypi, "9.0.post1", {"7.0": _release(">=3.10"), "9.0.post1": _release(">=3.10")})
    pyproject = _write_pyproject(tmp_path, dev=declared)
    before = pyproject.read_text(encoding="utf-8")

    updated = update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)

    assert updated == 0
    assert pyproject.read_text(encoding="utf-8") == before
    assert "not a valid requirement" in capsys.readouterr().err


# The later classifier Pythons a raised floor must keep (OPEN-WORK [85]).


@pytest.mark.os_agnostic
def test_later_for_names_each_later_classifier_python_the_requirement_is_installed_on() -> None:
    support = _dependencies.PythonSupport(10, later_minors=(12, 14))

    assert support.later_for("pkg>=1") == ("3.12.0", "3.14.0")
    assert support.later_for("pkg>=1; python_version < '3.13'") == ("3.12.0",)


@pytest.mark.os_agnostic
def test_python_support_carries_the_later_classifier_minors(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, dev='"hypothesis>=6.168.4"')
    config = _dependencies.load_pyproject_config(pyproject)

    support = _dependencies.python_support(config)

    assert support is not None
    assert (support.lowest_minor, support.later_minors) == (10, (14,))


# A raised floor must keep every later supported Python the requirement already installs on
# (user decision 2026-10-23: never lose a Python). _write_pyproject declares 3.10 and 3.14. uv
# installs a capped release anyway, so only pip on 3.14 would show the break (measured, uv 0.13.0).
_CAPPED = {"1.0": _release(">=3.8"), "2.0": _release(">=3.8,<3.13")}


@pytest.mark.os_agnostic
def test_a_floor_is_not_raised_to_a_release_that_drops_a_later_supported_python(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    _serve_pkg(pypi, "2.0", _CAPPED)
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=1.0"')
    before = pyproject.read_text(encoding="utf-8")

    (dep,) = check_dependencies(pyproject)
    update_dependencies([dep], pyproject, quiet=True)

    assert pyproject.read_text(encoding="utf-8") == before
    assert dep.status is DependencyStatus.PINNED
    assert "does not install on Python 3.14" in dep.latest


@pytest.mark.os_agnostic
def test_a_floor_below_the_cap_is_raised_only_as_far_as_keeps_the_later_python(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    _serve_pkg(pypi, "2.0", {"0.5": _release(">=3.8"), **_CAPPED})
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=0.5"')

    (dep,) = check_dependencies(pyproject)
    update_dependencies([dep], pyproject, quiet=True)

    assert _written_dev(pyproject) == "pkg>=1.0"
    assert "newest that keeps Python 3.14" in dep.latest


@pytest.mark.os_agnostic
def test_a_python_no_admitted_release_ever_installed_on_does_not_hold_the_floor(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    _serve_pkg(pypi, "2.0", {"1.0": _release(">=3.8,<3.13"), "2.0": _release(">=3.8,<3.13")})
    pyproject = _write_pyproject(tmp_path, dev='"pkg>=1.0"')

    (dep,) = check_dependencies(pyproject)
    update_dependencies([dep], pyproject, quiet=True)

    assert dep.status is not DependencyStatus.ERROR, dep.latest
    assert _written_dev(pyproject) == "pkg>=2.0"


@pytest.mark.os_agnostic
def test_a_marker_that_excludes_the_later_python_lets_the_floor_follow_the_cap(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    _serve_pkg(pypi, "2.0", _CAPPED)
    pyproject = _write_pyproject(tmp_path, dev="\"pkg>=1.0; python_version < '3.13'\"")

    update_dependencies(check_dependencies(pyproject), pyproject, quiet=True)

    assert Requirement(_written_dev(pyproject)).specifier == SpecifierSet(">=2.0")


# pythonnet as published (PyPI JSON, read 2026-10-23): no 3.x release installs on both 3.10 and
# 3.15, while 2.5.2 declares no Requires-Python. bmk 3.22.6 lowered pwshpy's `pythonnet>=3.1.0` to
# `>=2.5.2` (OPEN-WORK [3]), because it looked for ONE release covering every supported Python.
_PYTHONNET: dict[str, Any] = {
    "info": {"version": "3.2.1"},
    "releases": {
        "2.5.2": _release(None),
        "3.0.5": _release("<3.14,>=3.7"),
        "3.1.0": _release("<3.15,>=3.10"),
        "3.2.0": _release("<3.16,>=3.11"),
        "3.2.1": _release("<3.16,>=3.11"),
    },
}


def _write_pyproject_310_315(tmp_path: Path, *, dev: str) -> Path:
    pyproject = tmp_path / "pyproject.toml"
    classifiers = "".join(f'  "Programming Language :: Python :: 3.{m}",\n' for m in range(10, 16))
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\nrequires-python = ">=3.10"\n'
        f"classifiers = [\n{classifiers}]\n"
        "dependencies = []\n\n[project.optional-dependencies]\n"
        f"dev = [\n  {dev},\n]\n",
        encoding="utf-8",
    )
    return pyproject


@pytest.mark.os_agnostic
def test_a_floor_no_single_release_covers_every_python_for_is_never_lowered(tmp_path: Path, pypi: _FakeIndex) -> None:
    """3.1.0 installs on 3.10, and 3.15 still finds 3.2.x above it: each Python keeps a release."""
    pypi.serve("pythonnet", _PYTHONNET)
    pyproject = _write_pyproject_310_315(tmp_path, dev='"pythonnet>=3.1.0"')

    deps = check_dependencies(pyproject)
    updated = update_dependencies(deps, pyproject, quiet=True)

    assert updated == 0
    assert '"pythonnet>=3.1.0"' in pyproject.read_text(encoding="utf-8")
    [dep] = deps
    assert dep.status is not DependencyStatus.OUTDATED, dep


@pytest.mark.os_agnostic
def test_a_raise_stops_where_some_supported_python_would_find_no_release_above_it(
    tmp_path: Path, pypi: _FakeIndex
) -> None:
    """From 3.0.5: 3.10's newest is 3.1.0 and 3.15's is 3.2.1, so the floor rises to 3.1.0, not past it."""
    pypi.serve("pythonnet", _PYTHONNET)
    pyproject = _write_pyproject_310_315(tmp_path, dev='"pythonnet>=3.0.5"')

    deps = check_dependencies(pyproject)
    update_dependencies(deps, pyproject, quiet=True)

    assert '"pythonnet>=3.1.0"' in pyproject.read_text(encoding="utf-8")
