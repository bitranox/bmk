"""Tests for pure stage-ordering primitives in the domain layer."""

from __future__ import annotations

from bmk.domain.stages import group_into_batches, normalize_returncode


def test_group_into_batches_groups_equal_keys_and_sorts() -> None:
    items = [("a", 40), ("b", 10), ("c", 40), ("d", 20)]
    batches = group_into_batches(items, key=lambda t: t[1])
    assert [[t[0] for t in b] for b in batches] == [["b"], ["d"], ["a", "c"]]


def test_group_into_batches_preserves_declaration_order_within_batch() -> None:
    items = [("a", 40), ("c", 40), ("b", 40)]
    batches = group_into_batches(items, key=lambda t: t[1])
    assert [t[0] for t in batches[0]] == ["a", "c", "b"]


def test_group_into_batches_empty_is_empty() -> None:
    assert group_into_batches([], key=lambda t: t) == []


def test_normalize_returncode_maps_signal_to_128_plus_n() -> None:
    assert normalize_returncode(-2) == 130
    assert normalize_returncode(0) == 0
    assert normalize_returncode(1) == 1
