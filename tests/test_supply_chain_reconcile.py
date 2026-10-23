"""``reconcile_floor_pins`` on a real ``pyproject.toml``: what it returns, prints and writes.

The order of the change lines, the order of the keys in the written table and the form of that
table (standard or inline) are all part of the contract: a project diffs the file bmk rewrote, and
the change lines are what ``deps --update`` reports. So each case pins the whole written text and
the whole stderr, not a parsed view of them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from bmk.adapters.stagerunner.helpers._supply_chain import reconcile_floor_pins

if TYPE_CHECKING:
    from pathlib import Path

_PREFIX = "[tool.uv] exclude-newer-package:"
_CUTOFF = datetime(2026, 6, 1, tzinfo=timezone.utc)

# The entries bmk would recognise as its own, by name and value. A fixed set stands in for the
# release-list lookup the real predicate does, which needs PyPI; the function only asks yes or no.
_OURS = frozenset(
    {
        ("bmk-updated", "2026-01-01T00:00:01Z"),
        ("bmk-removed", "2026-01-02T00:00:01Z"),
        ("bmk-kept", "2026-12-01T00:00:01Z"),
        ("odd-name", "2026-01-03T00:00:01Z"),
    }
)

_PINS = {
    "zeta": "2026-05-05T00:00:01Z",
    "bmk_updated": "2026-02-02T00:00:01Z",
    "alpha": "2026-04-04T00:00:01Z",
    "odd.name": "2026-07-07T00:00:01Z",
    "hand": "2026-09-09T00:00:01Z",
}

_HEAD = '[project]\nname = "demo"\n\n[tool.uv]\nexclude-newer = "7 days"\n'

_MIXED_CHANGES = [
    f'{_PREFIX} bmk-updated = "2026-02-02T00:00:01Z"',
    f"{_PREFIX} bmk-removed pin removed, the cooldown admits it",
    f'{_PREFIX} odd-name = "2026-07-07T00:00:01Z"',
    f'{_PREFIX} alpha = "2026-04-04T00:00:01Z" (floor younger than the cooldown)',
    f'{_PREFIX} zeta = "2026-05-05T00:00:01Z" (floor younger than the cooldown)',
]


def _ours(name: str, value: object) -> bool:
    return (name, value) in _OURS


def _kept_line(pyproject: Path, name: str) -> str:
    return (
        f"{pyproject}: {_PREFIX} {name} pin kept: no declared floor demands it, "
        "and the cooldown does not admit its release yet\n"
    )


def _project(tmp_path: Path, text: str) -> Path:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(text, encoding="utf-8")
    return pyproject


@pytest.mark.os_agnostic
def test_standard_table_is_edited_in_place_keeping_comments_and_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pyproject = _project(
        tmp_path,
        _HEAD + "\n[tool.uv.exclude-newer-package]\n"
        "# the project's own choice\n"
        'hand = "2026-03-03T00:00:00Z"\n'
        'bmk-updated = "2026-01-01T00:00:01Z"  # bmk wrote this\n'
        'bmk-removed = "2026-01-02T00:00:01Z"\n'
        'bmk-kept = "2026-12-01T00:00:01Z"\n'
        'Odd_Name = "2026-01-03T00:00:01Z"\n'
        "own = false\n",
    )

    changes = reconcile_floor_pins(pyproject, pins=_PINS, is_floor_pin=_ours, cutoff=_CUTOFF)

    assert changes == _MIXED_CHANGES
    assert pyproject.read_text(encoding="utf-8") == (
        _HEAD + "\n[tool.uv.exclude-newer-package]\n"
        "# the project's own choice\n"
        'hand = "2026-03-03T00:00:00Z"\n'
        'bmk-updated = "2026-02-02T00:00:01Z"  # bmk wrote this\n'
        'bmk-kept = "2026-12-01T00:00:01Z"\n'
        'Odd_Name = "2026-07-07T00:00:01Z"\n'
        "own = false\n"
        'alpha = "2026-04-04T00:00:01Z"\n'
        'zeta = "2026-05-05T00:00:01Z"\n'
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == _kept_line(pyproject, "bmk-kept")


@pytest.mark.os_agnostic
def test_inline_table_is_rebuilt_current_entries_first_then_new_keys_sorted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pyproject = _project(
        tmp_path,
        _HEAD + 'exclude-newer-package = { hand = "2026-03-03T00:00:00Z", bmk-updated = "2026-01-01T00:00:01Z", '
        'bmk-removed = "2026-01-02T00:00:01Z", bmk-kept = "2026-12-01T00:00:01Z", '
        'Odd_Name = "2026-01-03T00:00:01Z", own = false }\n',
    )

    changes = reconcile_floor_pins(pyproject, pins=_PINS, is_floor_pin=_ours, cutoff=_CUTOFF)

    assert changes == _MIXED_CHANGES
    assert pyproject.read_text(encoding="utf-8") == (
        _HEAD + 'exclude-newer-package = {hand = "2026-03-03T00:00:00Z", bmk-updated = "2026-02-02T00:00:01Z", '
        'bmk-kept = "2026-12-01T00:00:01Z", Odd_Name = "2026-07-07T00:00:01Z", own = false, '
        'alpha = "2026-04-04T00:00:01Z", zeta = "2026-05-05T00:00:01Z"}\n'
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == _kept_line(pyproject, "bmk-kept")


@pytest.mark.os_agnostic
def test_nothing_to_change_returns_empty_and_leaves_the_file_byte_identical(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        _HEAD
        + '\n[tool.uv.exclude-newer-package]\nhand = "2026-03-03T00:00:00Z"\nbmk-updated = "2026-01-01T00:00:01Z"\n'
    )
    pyproject = _project(tmp_path, text)
    before = pyproject.read_bytes()

    changes = reconcile_floor_pins(
        pyproject, pins={"bmk-updated": "2026-01-01T00:00:01Z"}, is_floor_pin=_ours, cutoff=_CUTOFF
    )

    assert changes == []
    assert pyproject.read_bytes() == before
    assert capsys.readouterr() == ("", "")


@pytest.mark.os_agnostic
def test_a_project_without_tool_uv_and_no_pins_is_not_rewritten(tmp_path: Path) -> None:
    pyproject = _project(tmp_path, '[project]\nname = "demo"\n')
    before = pyproject.read_bytes()

    assert reconcile_floor_pins(pyproject, pins={}, is_floor_pin=_ours, cutoff=_CUTOFF) == []
    assert pyproject.read_bytes() == before


@pytest.mark.os_agnostic
def test_pins_without_any_table_create_an_inline_one_in_sorted_order(tmp_path: Path) -> None:
    pyproject = _project(tmp_path, _HEAD)

    changes = reconcile_floor_pins(
        pyproject,
        pins={"zeta": "2026-05-05T00:00:01Z", "Alpha": "2026-04-04T00:00:01Z"},
        is_floor_pin=_ours,
        cutoff=_CUTOFF,
    )

    assert changes == [
        f'{_PREFIX} alpha = "2026-04-04T00:00:01Z" (floor younger than the cooldown)',
        f'{_PREFIX} zeta = "2026-05-05T00:00:01Z" (floor younger than the cooldown)',
    ]
    assert pyproject.read_text(encoding="utf-8") == (
        _HEAD + 'exclude-newer-package = {alpha = "2026-04-04T00:00:01Z", zeta = "2026-05-05T00:00:01Z"}\n'
    )


@pytest.mark.os_agnostic
def test_a_standard_table_left_empty_is_removed(tmp_path: Path) -> None:
    pyproject = _project(tmp_path, _HEAD + '\n[tool.uv.exclude-newer-package]\nbmk-removed = "2026-01-02T00:00:01Z"\n')

    changes = reconcile_floor_pins(pyproject, pins={}, is_floor_pin=_ours, cutoff=_CUTOFF)

    assert changes == [f"{_PREFIX} bmk-removed pin removed, the cooldown admits it"]
    assert pyproject.read_text(encoding="utf-8") == _HEAD + "\n"


@pytest.mark.os_agnostic
def test_an_inline_table_left_empty_is_removed(tmp_path: Path) -> None:
    pyproject = _project(tmp_path, _HEAD + 'exclude-newer-package = { bmk-removed = "2026-01-02T00:00:01Z" }\n')

    changes = reconcile_floor_pins(pyproject, pins={}, is_floor_pin=_ours, cutoff=_CUTOFF)

    assert changes == [f"{_PREFIX} bmk-removed pin removed, the cooldown admits it"]
    assert pyproject.read_text(encoding="utf-8") == _HEAD


@pytest.mark.os_agnostic
def test_without_a_cutoff_a_pin_nothing_demands_is_removed_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pyproject = _project(
        tmp_path,
        _HEAD + '\n[tool.uv.exclude-newer-package]\nhand = "2026-03-03T00:00:00Z"\nbmk-kept = "2026-12-01T00:00:01Z"\n',
    )

    changes = reconcile_floor_pins(pyproject, pins={}, is_floor_pin=_ours, cutoff=None)

    assert changes == [f"{_PREFIX} bmk-kept pin removed, the cooldown admits it"]
    assert pyproject.read_text(encoding="utf-8") == (
        _HEAD + '\n[tool.uv.exclude-newer-package]\nhand = "2026-03-03T00:00:00Z"\n'
    )
    assert capsys.readouterr() == ("", "")
