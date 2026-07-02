"""Tests for the bump / commit / bld / push / rel / run pipelines and resolution."""

from __future__ import annotations

from pathlib import Path

from bmk.adapters.stagerunner.registry import PIPELINES, PORTED_PREFIXES, resolve_python_pipeline


def test_bump_pipelines_registered() -> None:
    for kind in ("bump_major", "bump_minor", "bump_patch"):
        assert [(s.name, s.order) for s in PIPELINES[kind]] == [("bump", 10), ("sync_initconf", 20)]


def test_commit_pipeline_stage_is_interactive() -> None:
    stages = PIPELINES["commit"]
    assert [(s.name, s.order) for s in stages] == [("sync_initconf", 5), ("commit", 10)]
    commit_stage = next(s for s in stages if s.name == "commit")
    assert commit_stage.interactive is True


def test_bld_pipeline() -> None:
    assert [(s.name, s.order) for s in PIPELINES["bld"]] == [("clean", 10), ("build", 20)]


def test_push_pipeline_orders() -> None:
    stages = PIPELINES["push"]
    assert [(s.name, s.order) for s in stages] == [
        ("update_deps", 10),
        ("build", 20),
        ("test", 20),
        ("clean", 30),
        ("commit", 40),
        ("push", 50),
    ]


def test_rel_and_run_pipelines() -> None:
    assert [(s.name, s.order) for s in PIPELINES["rel"]] == [("release", 10)]
    assert [(s.name, s.order) for s in PIPELINES["run"]] == [("run", 10)]


def test_all_phase4_prefixes_ported() -> None:
    expected = {"bump_major", "bump_minor", "bump_patch", "commit", "bld", "push", "rel", "run"}
    assert expected <= PORTED_PREFIXES


def test_resolve_python_pipeline_builtin(tmp_path: Path) -> None:
    stages = resolve_python_pipeline(tmp_path, "clean")
    assert stages is not None
    assert [s.name for s in stages] == ["clean"]


def test_resolve_python_pipeline_unknown_prefix_returns_none(tmp_path: Path) -> None:
    assert resolve_python_pipeline(tmp_path, "totally_unknown") is None


def test_resolve_python_pipeline_custom_prefix_from_overlay(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[[tool.bmk.pipelines.deploy.add]]\nname = "ship"\norder = 10\nargv = ["true"]\n',
        encoding="utf-8",
    )
    stages = resolve_python_pipeline(tmp_path, "deploy")
    assert stages is not None
    assert [s.name for s in stages] == ["ship"]
