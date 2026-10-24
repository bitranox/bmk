"""The project venv's Python version: chosen from the classifiers, kept at the latest patch.

`requires-python` is a floor (`>=3.10`) with no upper bound, so it never names the newest
version a project supports. The `Programming Language :: Python :: X.Y` classifiers do, and the
CI workflow already derives its test matrix from exactly those - so reading them here keeps the
local venv and the CI matrix agreeing about "the newest supported Python" instead of drifting
apart, which is the same class of defect as a gate resolving the wrong interpreter.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import os
import sys
import sysconfig
import venv as stdlib_venv
from typing import TYPE_CHECKING

import pytest

from bmk.adapters.stagerunner import venv as venv_mod

if TYPE_CHECKING:
    from pathlib import Path

    from uv_stub import StubUv


def _pyproject(tmp_path: Path, classifiers: list[str]) -> Path:
    body = ["[project]", 'name = "demo"', 'version = "0.1.0"', 'requires-python = ">=3.10"', "classifiers = ["]
    body += [f'  "{c}",' for c in classifiers]
    body.append("]")
    (tmp_path / "pyproject.toml").write_text("\n".join(body) + "\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# all_python_minors: every X.Y the classifiers declare, ascending
#
# The full matrix `test-all` runs. desired_python_minor is now just its last element.
# Same key and rules as CI's matrix parse (dotted entries only, numeric order).
# ---------------------------------------------------------------------------


def test_all_python_minors_ascending(tmp_path: Path) -> None:
    _pyproject(
        tmp_path,
        [
            "Programming Language :: Python :: 3.14",
            "Programming Language :: Python :: 3.10",
            "Programming Language :: Python :: 3.12",
        ],
    )
    assert venv_mod.all_python_minors(tmp_path) == ["3.10", "3.12", "3.14"]


def test_all_python_minors_orders_numerically_not_lexically(tmp_path: Path) -> None:
    """3.9 must sort BELOW 3.14, which a string sort gets backwards."""
    _pyproject(
        tmp_path,
        ["Programming Language :: Python :: 3.14", "Programming Language :: Python :: 3.9"],
    )
    assert venv_mod.all_python_minors(tmp_path) == ["3.9", "3.14"]


def test_all_python_minors_skips_bare_major_and_unrelated(tmp_path: Path) -> None:
    _pyproject(
        tmp_path,
        [
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3 :: Only",
            "License :: OSI Approved :: MIT License",
            "Programming Language :: Python :: 3.11",
        ],
    )
    assert venv_mod.all_python_minors(tmp_path) == ["3.11"]


def test_all_python_minors_empty_when_none_declared(tmp_path: Path) -> None:
    _pyproject(tmp_path, ["License :: OSI Approved :: MIT License"])
    assert venv_mod.all_python_minors(tmp_path) == []


def test_all_python_minors_empty_without_pyproject(tmp_path: Path) -> None:
    assert venv_mod.all_python_minors(tmp_path) == []


def test_all_python_minors_empty_on_unparseable(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("!!! not toml [[[", encoding="utf-8")
    assert venv_mod.all_python_minors(tmp_path) == []


def test_desired_python_minor_is_the_last_of_all(tmp_path: Path) -> None:
    """desired_python_minor and all_python_minors must never disagree."""
    _pyproject(
        tmp_path,
        ["Programming Language :: Python :: 3.10", "Programming Language :: Python :: 3.14"],
    )
    minors = venv_mod.all_python_minors(tmp_path)
    assert venv_mod.desired_python_minor(tmp_path) == minors[-1]


# ---------------------------------------------------------------------------
# desired_python_minor: the highest X.Y the classifiers declare
# ---------------------------------------------------------------------------


def test_picks_the_highest_classifier(tmp_path: Path) -> None:
    _pyproject(
        tmp_path,
        [
            "Programming Language :: Python :: 3.10",
            "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.14",
        ],
    )
    assert venv_mod.desired_python_minor(tmp_path) == "3.14"


def test_picks_the_highest_numerically_not_lexically(tmp_path: Path) -> None:
    """ "3.9" must not beat "3.14": lexically it would, numerically it must not."""
    _pyproject(
        tmp_path,
        ["Programming Language :: Python :: 3.14", "Programming Language :: Python :: 3.9"],
    )
    assert venv_mod.desired_python_minor(tmp_path) == "3.14"


def test_ignores_the_bare_major_classifier(tmp_path: Path) -> None:
    """`:: Python :: 3` carries no minor; CI skips it via the dotted check and so must we."""
    _pyproject(
        tmp_path,
        [
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3 :: Only",
            "Programming Language :: Python :: 3.12",
        ],
    )
    assert venv_mod.desired_python_minor(tmp_path) == "3.12"


def test_ignores_unrelated_classifiers(tmp_path: Path) -> None:
    _pyproject(
        tmp_path,
        ["License :: OSI Approved :: MIT License", "Typing :: Typed", "Programming Language :: Python :: 3.13"],
    )
    assert venv_mod.desired_python_minor(tmp_path) == "3.13"


def test_none_when_no_python_classifier(tmp_path: Path) -> None:
    """No declared version -> bmk must not choose one; uv's own default stands."""
    _pyproject(tmp_path, ["License :: OSI Approved :: MIT License"])
    assert venv_mod.desired_python_minor(tmp_path) is None


def test_none_when_no_pyproject(tmp_path: Path) -> None:
    assert venv_mod.desired_python_minor(tmp_path) is None


def test_none_on_unparseable_pyproject(tmp_path: Path) -> None:
    """A broken manifest must degrade, never raise: provisioning is best-effort."""
    (tmp_path / "pyproject.toml").write_text("!!! not toml [[[", encoding="utf-8")
    assert venv_mod.desired_python_minor(tmp_path) is None


# ---------------------------------------------------------------------------
# latest_installed_patch: the newest patch uv has for that minor
#
# The decision is the pure _highest_installed_patch, tested on every OS with the listing uv
# prints; only the wiring (which command asks uv) needs the stub uv on PATH.
# ---------------------------------------------------------------------------


_UV_JSON = json.dumps(
    [
        {
            "key": "cpython-3.14.5-linux",
            "version": "3.14.5",
            "version_parts": {"major": 3, "minor": 14, "patch": 5},
            "implementation": "cpython",
        },
        {
            "key": "cpython-3.14.0-linux",
            "version": "3.14.0",
            "version_parts": {"major": 3, "minor": 14, "patch": 0},
            "implementation": "cpython",
        },
        {
            "key": "cpython-3.13.13-linux",
            "version": "3.13.13",
            "version_parts": {"major": 3, "minor": 13, "patch": 13},
            "implementation": "cpython",
        },
    ]
)


@pytest.mark.os_agnostic
def test_highest_installed_patch_picks_the_highest_for_the_minor() -> None:
    assert venv_mod._highest_installed_patch(_UV_JSON, "3.14") == "3.14.5"


@pytest.mark.os_agnostic
def test_highest_installed_patch_compares_numerically() -> None:
    """patch 13 must beat patch 5 - a lexical compare would invert it.

    Both patches of ONE minor, 13 listed second: the shared listing's minors each hold patches
    that sort the same either way, so it could not tell a numeric compare from a lexical one.
    """
    listing = json.dumps([_entry("3.13.5", installed=True), _entry("3.13.13", installed=True)])
    assert venv_mod._highest_installed_patch(listing, "3.13") == "3.13.13"


@pytest.mark.os_agnostic
def test_highest_installed_patch_of_a_prerelease_is_in_the_form_the_venv_reports() -> None:
    """uv lists a beta as ``3.16.0b1``; a venv on it reports ``sys.version_info[:3]``, ``3.16.0``.

    ``_discard_venv_on_wrong_python`` compares the two for equality, so returning uv's text would
    never match and the venv would be deleted and rebuilt on every run for a pre-release classifier.
    """
    listing = json.dumps([{**_entry("3.16.0", installed=True), "version": "3.16.0b1"}])
    assert venv_mod._highest_installed_patch(listing, "3.16") == "3.16.0"


@pytest.mark.os_agnostic
def test_highest_installed_patch_none_for_absent_minor() -> None:
    assert venv_mod._highest_installed_patch(_UV_JSON, "3.11") is None


@pytest.mark.os_agnostic
def test_highest_installed_patch_none_when_uv_gave_no_listing() -> None:
    """uv missing or erroring must not raise - the caller degrades to uv's own choice."""
    assert venv_mod._highest_installed_patch(None, "3.14") is None


@pytest.mark.os_agnostic
def test_highest_installed_patch_none_on_garbage_json() -> None:
    assert venv_mod._highest_installed_patch("not json at all", "3.14") is None


@pytest.mark.os_agnostic
def test_highest_installed_patch_ignores_non_cpython_even_with_higher_patch() -> None:
    """Only CPython counts: uv provisions CPython, so a higher-patch PyPy must not win.

    Otherwise the reported "newest" never matches the CPython venv and it rebuilds every run.
    """
    mixed = json.dumps(
        [
            {
                "key": "cpython-3.11.15-linux",
                "version": "3.11.15",
                "version_parts": {"major": 3, "minor": 11, "patch": 15},
                "implementation": "cpython",
            },
            {
                "key": "pypy-3.11.20-linux",
                "version": "3.11.20",
                "version_parts": {"major": 3, "minor": 11, "patch": 20},
                "implementation": "pypy",
            },
        ]
    )
    assert venv_mod._highest_installed_patch(mixed, "3.11") == "3.11.15"


@pytest.mark.os_agnostic
def test_highest_installed_patch_skips_malformed_entry() -> None:
    """An entry missing version_parts (or typed oddly) is skipped, not fatal."""
    partial = json.dumps(
        [
            {"key": "broken", "version": "3.12.9"},  # no version_parts -> ValidationError -> skipped
            {
                "key": "cpython-3.12.7-linux",
                "version": "3.12.7",
                "version_parts": {"major": 3, "minor": 12, "patch": 7},
                "implementation": "cpython",
            },
        ]
    )
    assert venv_mod._highest_installed_patch(partial, "3.12") == "3.12.7"


@pytest.mark.os_posix
def test_latest_installed_patch_asks_uv_for_the_installed_pythons(tmp_path: Path, stub_uv: StubUv) -> None:
    """The listing must be the installed one: a download on offer is not an interpreter yet."""
    stub_uv.install(installed_json=_UV_JSON)

    assert venv_mod.latest_installed_patch("3.14", tmp_path) == "3.14.5"
    assert stub_uv.commands() == [["uv", "python", "list", "--only-installed", "--output-format", "json"]]


# ---------------------------------------------------------------------------
# venv_version: ask the interpreter, never pyvenv.cfg's text
#
# uv builds a venv against the MINOR alias, so `uv python upgrade` migrates an existing
# venv onto the new patch by repointing that alias - while pyvenv.cfg's version_info,
# written once at creation, keeps reporting the old one. Measured:
#     venv on the 3.12 alias  -> pyvenv.cfg 3.12.12, interpreter 3.12.12
#     uv python upgrade 3.12
#     same venv, untouched    -> pyvenv.cfg 3.12.12, interpreter 3.12.13
# Reading the text would rebuild a venv uv had already upgraded, in every repo, on every
# patch release. These pin that the text is NOT the source of truth.
# ---------------------------------------------------------------------------

# What venv_version's probe prints. Not platform.python_version(): that keeps a pre-release
# suffix ("3.15.0rc1") the probe's sys.version_info[:3] drops.
_RUNNING_VERSION = ".".join(map(str, sys.version_info[:3]))
# No interpreter this suite runs on can report it, so a match can only come from the cfg text.
_STALE_CFG_VERSION = "3.0.0"


def _real_venv_with_stale_cfg(tmp_path: Path) -> Path:
    """A real venv on the running interpreter whose pyvenv.cfg names another version.

    That is the post-``uv python upgrade`` state: the interpreter moved on, the text did not.
    """
    v = tmp_path / ".venv"
    # symlinks on POSIX as `python -m venv` does: a copied standalone build can lose its libpython
    stdlib_venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(v)
    cfg = v / "pyvenv.cfg"
    kept = [line for line in cfg.read_text(encoding="utf-8").splitlines() if not line.startswith("version")]
    stale = [f"version = {_STALE_CFG_VERSION}", f"version_info = {_STALE_CFG_VERSION}"]
    cfg.write_text("\n".join([*kept, *stale]) + "\n", encoding="utf-8")
    return v


def _fake_venv(tmp_path: Path, *, cfg_says: str) -> Path:
    v = tmp_path / ".venv"
    (v / ("Scripts" if os.name == "nt" else "bin")).mkdir(parents=True)
    venv_mod.venv_python(v).write_text("", encoding="utf-8")
    (v / "pyvenv.cfg").write_text(f"home = /x\nversion_info = {cfg_says}\n", encoding="utf-8")
    return v


@pytest.mark.os_agnostic
def test_venv_version_asks_the_interpreter_and_ignores_a_stale_pyvenv_cfg(tmp_path: Path) -> None:
    """The exact post-upgrade state: the cfg names one version, the interpreter is another.

    Returning the cfg text here is what would trigger a needless full rebuild; the running
    version is the only right answer, which also rules out every other wrong one.
    """
    v = _real_venv_with_stale_cfg(tmp_path)

    assert venv_mod.venv_version(v) == _RUNNING_VERSION


@pytest.mark.os_agnostic
def test_venv_version_none_when_the_interpreter_will_not_run(tmp_path: Path) -> None:
    """A broken venv reports nothing, so the caller leaves it alone rather than guessing.

    The interpreter is an empty file: POSIX refuses to exec it (EACCES, not executable) and
    Windows refuses to load it (WinError 193, not a valid Win32 application), both an OSError.
    """
    v = _fake_venv(tmp_path, cfg_says="3.14.0")

    assert venv_mod.venv_version(v) is None


@pytest.mark.os_agnostic
def test_venv_version_none_when_absent(tmp_path: Path) -> None:
    assert venv_mod.venv_version(tmp_path / "nope") is None


# ---------------------------------------------------------------------------
# _python_request: with no classifier, the uv sync request names the venv's kind of interpreter.
# A bare X.Y lets a recreate fall back to uv's default CPython (measured, uv 0.13.0: a PyPy venv
# came back as CPython), so PyPy is asked for as pypy@X.Y and a free-threaded build as X.Yt.
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("probe", "uv_request"),
    [
        ("cpython 3.10.19 0", "3.10"),
        ("pypy 3.11.13 0", "pypy@3.11"),
        ("cpython 3.13.5 1", "3.13t"),
        ("graalpy 3.11.7 0", "3.11"),
    ],
    ids=["cpython", "pypy", "free-threaded", "unknown-implementation"],
)
def test_the_request_names_the_venvs_kind_of_interpreter(probe: str, uv_request: str) -> None:
    assert venv_mod._python_request(venv_mod._parse_interpreter_probe(probe)) == uv_request


@pytest.mark.os_agnostic
@pytest.mark.parametrize("probe", [None, "", "3.10.19", "cpython 3.10.19", "cpython 3.10.19 yes"])
def test_no_request_when_the_probe_could_not_answer(probe: str | None) -> None:
    assert venv_mod._parse_interpreter_probe(probe) is None
    assert venv_mod._python_request(None) is None


@pytest.mark.os_agnostic
def test_the_probe_on_the_running_interpreter_gives_its_own_request(tmp_path: Path) -> None:
    """The real probe through a real venv: one subprocess answers both the version and the request."""
    v = _real_venv_with_stale_cfg(tmp_path)
    minor = f"{sys.version_info[0]}.{sys.version_info[1]}"
    expected = {
        "pypy": f"pypy@{minor}",
        "cpython": f"{minor}t" if sysconfig.get_config_var("Py_GIL_DISABLED") else minor,
    }.get(sys.implementation.name, minor)

    assert venv_mod._python_request(venv_mod._probe_interpreter(v)) == expected


# ---------------------------------------------------------------------------
# _ensure_minor_installed: never touch uv's Python store when nothing is newer
# ---------------------------------------------------------------------------
# `uv python install` and `uv python upgrade` rewrite EVERY minor alias symlink in uv's
# Python store even when they change nothing (measured, uv 0.13.0: "already on the latest
# supported patch release", yet all six aliases got a new mtime). Every venv resolves its
# interpreter through such an alias, so each no-op call briefly removes the interpreter of
# every venv on the machine: test-all's 3.10 cell, syncing while a later cell ran its
# install, failed "No interpreter found at path .venv-3.10/bin/python" (bmk OPEN-WORK [102]).
#
# The decision is the pure _listing_needs_install; the stub uv covers only what reaches uv.


def _entry(version: str, *, installed: bool, implementation: str = "cpython") -> dict[str, object]:
    major, minor, patch = (int(p) for p in version.split(".")[:3])
    return {
        "version": version,
        "version_parts": {"major": major, "minor": minor, "patch": patch},
        "implementation": implementation,
        "path": f"/uv/python/{implementation}-{version}/bin/python3" if installed else None,
    }


_LIST_OFFERED = ["uv", "python", "list", "--allow-python-downloads", "--output-format", "json"]


@pytest.mark.os_agnostic
def test_a_current_minor_needs_no_install() -> None:
    listing = json.dumps([_entry("3.12.15", installed=True), _entry("3.12.12", installed=True)])

    assert venv_mod._listing_needs_install(listing, "3.12") is False


@pytest.mark.os_agnostic
def test_a_newer_patch_on_offer_needs_an_install() -> None:
    listing = json.dumps([_entry("3.12.16", installed=False), _entry("3.12.15", installed=True)])

    assert venv_mod._listing_needs_install(listing, "3.12") is True


@pytest.mark.os_agnostic
def test_an_absent_minor_needs_an_install() -> None:
    listing = json.dumps([_entry("3.15.0", installed=False), _entry("3.14.8", installed=True)])

    assert venv_mod._listing_needs_install(listing, "3.15") is True


@pytest.mark.os_agnostic
def test_no_listing_still_needs_an_install() -> None:
    """No answer is not 'current': fall back to the old always-run behaviour."""
    assert venv_mod._listing_needs_install(None, "3.12") is True


@pytest.mark.os_agnostic
def test_a_newer_pypy_download_does_not_make_a_cpython_minor_need_an_install() -> None:
    listing = json.dumps([_entry("3.12.15", installed=True), _entry("3.12.99", installed=False, implementation="pypy")])

    assert venv_mod._listing_needs_install(listing, "3.12") is False


@pytest.mark.os_agnostic
def test_an_unknown_implementation_never_counts_as_cpython() -> None:
    """An implementation bmk has no member for (decoded as OTHER) is never taken for CPython."""
    listing = json.dumps(
        [_entry("3.12.15", installed=True), _entry("3.12.99", installed=False, implementation="graalpy")]
    )

    assert venv_mod._listing_needs_install(listing, "3.12") is False
    assert (
        venv_mod._highest_installed_patch(
            json.dumps(
                [_entry("3.12.15", installed=True), _entry("3.12.99", installed=True, implementation="graalpy")]
            ),
            "3.12",
        )
        == "3.12.15"
    )


@pytest.mark.os_agnostic
def test_a_freethreaded_download_without_a_variant_field_is_still_not_the_default() -> None:
    """A uv that predates the ``variant`` field still names the build in its ``key``."""
    freethreaded = {**_entry("3.14.8", installed=False), "key": "cpython-3.14.8+freethreaded-linux-x86_64-gnu"}
    current = {**_entry("3.14.8", installed=True), "key": "cpython-3.14.8-linux-x86_64-gnu"}

    assert venv_mod._listing_needs_install(json.dumps([current, freethreaded]), "3.14") is False


@pytest.mark.os_agnostic
def test_a_freethreaded_download_does_not_make_a_current_minor_look_stale() -> None:
    """The real listing: uv shows a not-installed +freethreaded build beside every 3.13+ minor.

    `uv python install 3.14` never installs that variant, so counting it reads every 3.13+
    minor as stale forever and the alias-rewriting commands run on every gate (review of f6fecca).
    """
    freethreaded = {**_entry("3.14.8", installed=False), "variant": "freethreaded"}
    listing = json.dumps([{**_entry("3.14.8", installed=True), "variant": "default"}, freethreaded])

    assert venv_mod._listing_needs_install(listing, "3.14") is False


@pytest.mark.os_posix
def test_a_current_minor_reaches_uv_only_to_list(tmp_path: Path, stub_uv: StubUv) -> None:
    """Nothing newer -> neither alias-rewriting command may reach uv."""
    stub_uv.install(offered_json=json.dumps([_entry("3.12.15", installed=True)]))

    venv_mod.ensure_minors_installed(tmp_path, ["3.12"])

    assert stub_uv.commands() == [_LIST_OFFERED]


@pytest.mark.os_posix
def test_a_needed_install_runs_install_before_upgrade(tmp_path: Path, stub_uv: StubUv) -> None:
    """``install`` fetches an absent minor, ``upgrade`` then moves it to the newest patch."""
    listing = json.dumps([_entry("3.12.16", installed=False), _entry("3.12.15", installed=True)])
    stub_uv.install(offered_json=listing)

    venv_mod.ensure_minors_installed(tmp_path, ["3.12"])

    assert stub_uv.commands() == [
        _LIST_OFFERED,
        ["uv", "python", "install", "3.12"],
        ["uv", "python", "upgrade", "3.12"],
    ]


@pytest.mark.os_posix
def test_when_uv_cannot_list_both_commands_still_run(tmp_path: Path, stub_uv: StubUv) -> None:
    """No answer is not 'current': fall back to the old always-run behaviour.

    Every ``uv python`` call fails here, install and upgrade included: their exit code is
    ignored, so a failing install must not stop the upgrade either.
    """
    stub_uv.install(python_rc=1)

    venv_mod.ensure_minors_installed(tmp_path, ["3.12"])

    assert stub_uv.commands() == [
        _LIST_OFFERED,
        ["uv", "python", "install", "3.12"],
        ["uv", "python", "upgrade", "3.12"],
    ]


@pytest.mark.os_posix
def test_the_listing_asks_for_downloads_whatever_python_downloads_says(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stub_uv: StubUv
) -> None:
    """uv hides every download entry under python-downloads manual/never - set in env OR config.

    Then "nothing on offer" would read as "current" and a stale minor would never be upgraded.
    `--allow-python-downloads` makes the listing show what is on offer regardless (measured, uv
    0.13.0: 13 download entries again under a pyproject `manual` and under UV_PYTHON_DOWNLOADS=never).

    The stub uv only records its argv, so this pins that bmk passes the flag; what uv does with
    it is the measurement above, not something this test can see.
    """
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "never")

    venv_mod.ensure_minors_installed(tmp_path, ["3.12"])

    listings = [cmd for cmd in stub_uv.commands() if cmd[:3] == ["uv", "python", "list"]]
    assert listings == [_LIST_OFFERED]
