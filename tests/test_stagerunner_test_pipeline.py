"""Tests for the test / cov / test_integration pipeline registrations."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bmk.adapters.stagerunner import tools
from bmk.adapters.stagerunner.actions import PipAuditAction, ToolAction
from bmk.adapters.stagerunner.registry import PIPELINES, PORTED_PREFIXES
from bmk.domain.stages import group_into_batches

if TYPE_CHECKING:
    from bmk.adapters.stagerunner.model import StageContext


def test_new_pipelines_ported() -> None:
    assert {"test", "cov", "test_integration"} <= PORTED_PREFIXES


def test_test_pipeline_stage_names_and_orders() -> None:
    stages = PIPELINES["test"]
    by_name = {s.name: s.order for s in stages}
    assert by_name["update_deps"] == 10
    assert by_name["ruff_format_apply"] == 20
    assert by_name["ruff_fix_apply"] == 30
    # The order-40 batch runs every read-only check in parallel; shellcheck only reads too
    # (shfmt -d, never -w), so it joins the batch rather than running alone after it.
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
        "shellcheck",
    }


def test_test_pipeline_batches_are_ordered() -> None:
    batches = group_into_batches(list(PIPELINES["test"]), key=lambda s: s.order)
    orders = [batch[0].order for batch in batches]
    assert orders == [10, 15, 20, 30, 40]
    assert len(next(b for b in batches if b[0].order == 40)) == 9  # parallel batch


def test_the_lock_is_checked_after_the_floors_rise_and_before_any_gate_reads_the_tree() -> None:
    # update_deps re-locks and re-syncs the venv itself; this stage then refuses a lock that no
    # longer matches pyproject, alone in its batch, before any gate reads the tree.
    stages = PIPELINES["test"]
    lock = next(s for s in stages if s.name == "uv_lock")
    update = next(s for s in stages if s.name == "update_deps")
    others = [s for s in stages if s.name not in {"uv_lock", "update_deps"}]
    assert update.order < lock.order < min(s.order for s in others)
    assert isinstance(lock.action, ToolAction)


def test_the_lock_stage_only_checks_and_never_moves_the_lock_under_a_synced_venv() -> None:
    # An upgrade HERE would change the lock after update_deps synced the venv from it, so every
    # gate in the 40 batch would test a different tree from the one the lock pins.
    assert tools.uv_lock_argv(cast("StageContext", None)) == ["uv", "lock", "--check"]


def test_cov_pipeline() -> None:
    assert [(s.name, s.order) for s in PIPELINES["cov"]] == [("coverage", 10), ("clean", 20)]


def test_test_integration_pipeline() -> None:
    assert [(s.name, s.order) for s in PIPELINES["test_integration"]] == [("pytest_integration", 10)]


def test_pip_audit_stage_bootstraps_pip_and_self_heals() -> None:
    # The pip_audit stage resolves its interpreter at run time, bootstraps a current
    # pip into it, then audits - so a pip-less or clean-removed .venv never breaks it.
    pip_audit = next(s for s in PIPELINES["test"] if s.name == "pip_audit")
    assert isinstance(pip_audit.action, PipAuditAction)
