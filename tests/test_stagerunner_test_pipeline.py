"""Tests for the test / cov / test_integration pipeline registrations."""

from __future__ import annotations

from bmk.adapters.stagerunner.registry import PIPELINES, PORTED_PREFIXES
from bmk.domain.stages import group_into_batches


def test_new_pipelines_ported() -> None:
    assert {"test", "cov", "test_integration"} <= PORTED_PREFIXES


def test_test_pipeline_stage_names_and_orders() -> None:
    stages = PIPELINES["test"]
    by_name = {s.name: s.order for s in stages}
    assert by_name["update_deps"] == 10
    assert by_name["ruff_format_apply"] == 20
    assert by_name["ruff_fix_apply"] == 30
    assert by_name["shellcheck"] == 60
    # The order-40 batch runs these in parallel:
    order_40 = {s.name for s in stages if s.order == 40}
    assert order_40 == {
        "bandit",
        "lint_imports",
        "pip_audit",
        "pyright",
        "pytest",
        "ruff_format_check",
        "ruff_lint",
        "psscriptanalyzer",
    }


def test_test_pipeline_batches_are_ordered() -> None:
    batches = group_into_batches(list(PIPELINES["test"]), key=lambda s: s.order)
    orders = [batch[0].order for batch in batches]
    assert orders == [10, 20, 30, 40, 60]
    assert len(next(b for b in batches if b[0].order == 40)) == 8  # parallel batch


def test_cov_pipeline() -> None:
    assert [(s.name, s.order) for s in PIPELINES["cov"]] == [("coverage", 10), ("clean", 20)]


def test_test_integration_pipeline() -> None:
    assert [(s.name, s.order) for s in PIPELINES["test_integration"]] == [("pytest_integration", 10)]
