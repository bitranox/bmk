"""The project venv's Python version: chosen from the classifiers, kept at the latest patch.

`requires-python` is a floor (`>=3.10`) with no upper bound, so it never names the newest
version a project supports. The `Programming Language :: Python :: X.Y` classifiers do, and the
CI workflow already derives its test matrix from exactly those - so reading them here keeps the
local venv and the CI matrix agreeing about "the newest supported Python" instead of drifting
apart, which is the same class of defect as a gate resolving the wrong interpreter.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from bmk.adapters.stagerunner import venv as venv_mod

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest


def _uv_returns(payload: str | None) -> Callable[..., str | None]:
    """Typed stand-in for `_run_capture` (a bare lambda is not strict-clean)."""

    def _fake(*_args: object, **_kwargs: object) -> str | None:
        return payload

    return _fake


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


def test_latest_installed_patch_picks_the_highest_for_the_minor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(_UV_JSON))
    assert venv_mod.latest_installed_patch("3.14", tmp_path) == "3.14.5"


def test_latest_installed_patch_compares_numerically(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """patch 13 must beat patch 5 - a lexical compare would invert it."""
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(_UV_JSON))
    assert venv_mod.latest_installed_patch("3.13", tmp_path) == "3.13.13"


def test_latest_installed_patch_none_for_absent_minor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(_UV_JSON))
    assert venv_mod.latest_installed_patch("3.11", tmp_path) is None


def test_latest_installed_patch_none_when_uv_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """uv missing or erroring must not raise - the caller degrades to uv's own choice."""
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(None))
    assert venv_mod.latest_installed_patch("3.14", tmp_path) is None


def test_latest_installed_patch_none_on_garbage_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns("not json at all"))
    assert venv_mod.latest_installed_patch("3.14", tmp_path) is None


def test_latest_installed_patch_ignores_non_cpython_even_with_higher_patch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(mixed))
    assert venv_mod.latest_installed_patch("3.11", tmp_path) == "3.11.15"


def test_latest_installed_patch_skips_malformed_entry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(partial))
    assert venv_mod.latest_installed_patch("3.12", tmp_path) == "3.12.7"


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


def _fake_venv(tmp_path: Path, *, cfg_says: str) -> Path:
    v = tmp_path / ".venv"
    (v / ("Scripts" if os.name == "nt" else "bin")).mkdir(parents=True)
    venv_mod.venv_python(v).write_text("", encoding="utf-8")
    (v / "pyvenv.cfg").write_text(f"home = /x\nversion_info = {cfg_says}\n", encoding="utf-8")
    return v


def test_venv_version_asks_the_interpreter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    v = _fake_venv(tmp_path, cfg_says="3.12.12")
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns("3.12.13\n"))

    assert venv_mod.venv_version(v) == "3.12.13"


def test_venv_version_ignores_a_stale_pyvenv_cfg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The exact post-upgrade state: cfg says 3.12.12, the interpreter is 3.12.13.

    Returning the cfg text here is what would trigger a needless full rebuild.
    """
    v = _fake_venv(tmp_path, cfg_says="3.12.12")
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns("3.12.13\n"))

    assert venv_mod.venv_version(v) != "3.12.12"


def test_venv_version_none_when_the_interpreter_will_not_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A broken venv reports nothing, so the caller leaves it alone rather than guessing."""
    v = _fake_venv(tmp_path, cfg_says="3.14.0")
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(None))

    assert venv_mod.venv_version(v) is None


def test_venv_version_none_when_absent(tmp_path: Path) -> None:
    assert venv_mod.venv_version(tmp_path / "nope") is None


# ---------------------------------------------------------------------------
# _ensure_minor_installed: never touch uv's Python store when nothing is newer
# ---------------------------------------------------------------------------
# `uv python install` and `uv python upgrade` rewrite EVERY minor alias symlink in uv's
# Python store even when they change nothing (measured, uv 0.13.0: "already on the latest
# supported patch release", yet all six aliases got a new mtime). Every venv resolves its
# interpreter through such an alias, so each no-op call briefly removes the interpreter of
# every venv on the machine: test-all's 3.10 cell, syncing while a later cell ran its
# install, failed "No interpreter found at path .venv-3.10/bin/python" (bmk OPEN-WORK [102]).


def _entry(version: str, *, installed: bool, implementation: str = "cpython") -> dict[str, object]:
    major, minor, patch = (int(p) for p in version.split(".")[:3])
    return {
        "version": version,
        "version_parts": {"major": major, "minor": minor, "patch": patch},
        "implementation": implementation,
        "path": f"/uv/python/{implementation}-{version}/bin/python3" if installed else None,
    }


def _record_runs(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    # hermetic: a developer's own python-downloads setting must not decide these tests
    monkeypatch.delenv("UV_PYTHON_DOWNLOADS", raising=False)
    seen: list[list[str]] = []

    def _fake_run(argv: list[str], _cwd: Path, *, quiet: bool = True, env: object = None) -> int:
        _ = quiet, env
        seen.append(argv)
        return 0

    monkeypatch.setattr(venv_mod, "_run", _fake_run)
    return seen


def test_a_current_minor_runs_neither_install_nor_upgrade(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    listing = json.dumps([_entry("3.12.15", installed=True), _entry("3.12.12", installed=True)])
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(listing))
    runs = _record_runs(monkeypatch)

    venv_mod.ensure_minors_installed(tmp_path, ["3.12"])

    assert runs == []


def test_a_newer_patch_on_offer_runs_install_and_upgrade(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    listing = json.dumps([_entry("3.12.16", installed=False), _entry("3.12.15", installed=True)])
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(listing))
    runs = _record_runs(monkeypatch)

    venv_mod.ensure_minors_installed(tmp_path, ["3.12"])

    assert ["uv", "python", "install", "3.12"] in runs
    assert ["uv", "python", "upgrade", "3.12"] in runs


def test_an_absent_minor_is_installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    listing = json.dumps([_entry("3.15.0", installed=False), _entry("3.14.8", installed=True)])
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(listing))
    runs = _record_runs(monkeypatch)

    venv_mod.ensure_minors_installed(tmp_path, ["3.15"])

    assert ["uv", "python", "install", "3.15"] in runs


def test_when_uv_cannot_list_both_commands_still_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No answer is not 'current': fall back to the old always-run behaviour."""
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(None))
    runs = _record_runs(monkeypatch)

    venv_mod.ensure_minors_installed(tmp_path, ["3.12"])

    assert ["uv", "python", "install", "3.12"] in runs
    assert ["uv", "python", "upgrade", "3.12"] in runs


def test_a_newer_pypy_download_does_not_trigger_a_cpython_upgrade(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    listing = json.dumps([_entry("3.12.15", installed=True), _entry("3.12.99", installed=False, implementation="pypy")])
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(listing))
    runs = _record_runs(monkeypatch)

    venv_mod.ensure_minors_installed(tmp_path, ["3.12"])

    assert runs == []


def test_a_freethreaded_download_without_a_variant_field_is_still_not_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A uv that predates the ``variant`` field still names the build in its ``key``."""
    freethreaded = {**_entry("3.14.8", installed=False), "key": "cpython-3.14.8+freethreaded-linux-x86_64-gnu"}
    current = {**_entry("3.14.8", installed=True), "key": "cpython-3.14.8-linux-x86_64-gnu"}
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(json.dumps([current, freethreaded])))
    runs = _record_runs(monkeypatch)

    venv_mod.ensure_minors_installed(tmp_path, ["3.14"])

    assert runs == []


def test_a_freethreaded_download_does_not_make_a_current_minor_look_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real listing: uv shows a not-installed +freethreaded build beside every 3.13+ minor.

    `uv python install 3.14` never installs that variant, so counting it reads every 3.13+
    minor as stale forever and the alias-rewriting commands run on every gate (review of f6fecca).
    """
    freethreaded = {**_entry("3.14.8", installed=False), "variant": "freethreaded"}
    listing = json.dumps([{**_entry("3.14.8", installed=True), "variant": "default"}, freethreaded])
    monkeypatch.setattr(venv_mod, "_run_capture", _uv_returns(listing))
    runs = _record_runs(monkeypatch)

    venv_mod.ensure_minors_installed(tmp_path, ["3.14"])

    assert runs == []


def test_the_listing_asks_for_downloads_whatever_python_downloads_says(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """uv hides every download entry under python-downloads manual/never - set in env OR config.

    Then "nothing on offer" would read as "current" and a stale minor would never be upgraded.
    `--allow-python-downloads` makes the listing show what is on offer regardless (measured, uv
    0.13.0: 13 download entries again under a pyproject `manual` and under UV_PYTHON_DOWNLOADS=never).
    """
    asked: list[list[str]] = []

    def _fake_capture(argv: list[str], *_args: object, **_kwargs: object) -> str | None:
        asked.append(argv)
        return None

    monkeypatch.setattr(venv_mod, "_run_capture", _fake_capture)
    _record_runs(monkeypatch)

    venv_mod.ensure_minors_installed(tmp_path, ["3.12"])

    assert asked == [["uv", "python", "list", "--allow-python-downloads", "--output-format", "json"]]
