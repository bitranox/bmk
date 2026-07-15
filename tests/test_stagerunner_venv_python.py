"""The project venv's Python version: chosen from the classifiers, kept at the latest patch.

`requires-python` is a floor (`>=3.10`) with no upper bound, so it never names the newest
version a project supports. The `Programming Language :: Python :: X.Y` classifiers do, and the
CI workflow already derives its test matrix from exactly those - so reading them here keeps the
local venv and the CI matrix agreeing about "the newest supported Python" instead of drifting
apart, which is the same class of defect as a gate resolving the wrong interpreter.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from bmk.adapters.stagerunner import venv as venv_mod


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
        {"key": "cpython-3.14.5-linux", "version": "3.14.5", "version_parts": {"major": 3, "minor": 14, "patch": 5}},
        {"key": "cpython-3.14.0-linux", "version": "3.14.0", "version_parts": {"major": 3, "minor": 14, "patch": 0}},
        {"key": "cpython-3.13.13-linux", "version": "3.13.13", "version_parts": {"major": 3, "minor": 13, "patch": 13}},
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


# ---------------------------------------------------------------------------
# venv_version: what the existing venv actually is
# ---------------------------------------------------------------------------


def test_venv_version_reads_pyvenv_cfg(tmp_path: Path) -> None:
    v = tmp_path / ".venv"
    v.mkdir()
    (v / "pyvenv.cfg").write_text("home = /x\nversion_info = 3.14.0\n", encoding="utf-8")
    assert venv_mod.venv_version(v) == "3.14.0"


def test_venv_version_handles_a_four_part_version_info(tmp_path: Path) -> None:
    """uv writes `version_info = 3.14.0.final.0` in some versions; keep the X.Y.Z part."""
    v = tmp_path / ".venv"
    v.mkdir()
    (v / "pyvenv.cfg").write_text("version_info = 3.14.0.final.0\n", encoding="utf-8")
    assert venv_mod.venv_version(v) == "3.14.0"


def test_venv_version_none_when_absent(tmp_path: Path) -> None:
    assert venv_mod.venv_version(tmp_path / "nope") is None
