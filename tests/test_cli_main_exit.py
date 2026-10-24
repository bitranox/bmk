"""Exit codes and stderr through the real ``main()`` entry point.

``CliRunner.invoke(cli, ...)`` calls the click command tree directly and never runs
``main()``'s ``standalone_mode=False`` handling, which is where a bare ``SystemExit`` from a
command falls into the catch-all branch and is printed to stderr as ``SystemExit: N`` - text
a user reads as a crash. These tests go through ``main()`` itself, as a console script does,
with the services replaced at the composition seam.
"""

from __future__ import annotations

import ast
import dataclasses
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
import pytest
import rtoml
from lib_layered_config import Config

import bmk.adapters.cli
from bmk.adapters.cli.exit_codes import ExitCode
from bmk.adapters.cli.main import main
from bmk.adapters.memory.email import EmailSpy
from bmk.adapters.stagerunner.registry import PIPELINES
from bmk.composition import AppServices, build_testing

if TYPE_CHECKING:
    from collections.abc import Callable

EMAIL = {"email": {"smtp_hosts": ["smtp.test.com:587"], "from_address": "sender@test.com"}}
SEND_EMAIL = ["send-email", "--to", "recipient@test.com", "--subject", "Test", "--body", "Hello"]
SEND_NOTIFICATION = ["send-notification", "--to", "admin@test.com", "--subject", "Alert", "--message", "m"]


def _services(data: dict[str, Any], **overrides: Any) -> Callable[[], AppServices]:
    config = Config(data, {})

    def get_config(**_kwargs: Any) -> Config:
        return config

    def build() -> AppServices:
        return dataclasses.replace(build_testing(), get_config=get_config, **overrides)

    return build


def _failing_spy() -> EmailSpy:
    spy = EmailSpy()
    spy.should_fail = True
    return spy


def _raising(error: Exception) -> Callable[..., Any]:
    def raise_it(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return raise_it


@pytest.mark.os_agnostic
def test_send_email_without_smtp_hosts_exits_78_without_printing_systemexit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(SEND_EMAIL, services_factory=_services({}))

    err = capsys.readouterr().err
    assert exit_code == 78
    assert "No SMTP hosts configured" in err
    assert "SystemExit" not in err


@pytest.mark.os_agnostic
@pytest.mark.parametrize("args", [SEND_EMAIL, SEND_NOTIFICATION], ids=["send-email", "send-notification"])
def test_a_failed_send_exits_69_and_reports_it_once(capsys: pytest.CaptureFixture[str], args: list[str]) -> None:
    """click's Exit is a RuntimeError; the delivery handler must not re-handle it as a second failure."""
    spy = _failing_spy()
    exit_code = main(
        args,
        services_factory=_services(EMAIL, send_email=spy.send_email, send_notification=spy.send_notification),
    )

    err = capsys.readouterr().err
    assert exit_code == 69
    assert "sending failed" in err
    assert "SMTP delivery failed" not in err
    assert "Failed to send email" not in err
    assert "SystemExit" not in err


@pytest.mark.os_agnostic
def test_a_delivery_error_exits_69_without_printing_systemexit(capsys: pytest.CaptureFixture[str]) -> None:
    spy = EmailSpy()
    spy.raise_exception = RuntimeError("connection refused")
    exit_code = main(SEND_EMAIL, services_factory=_services(EMAIL, send_email=spy.send_email))

    err = capsys.readouterr().err
    assert exit_code == 69
    assert "connection refused" in err
    assert "SystemExit" not in err


@pytest.mark.os_agnostic
def test_a_config_display_error_exits_22_without_printing_systemexit(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["config"], services_factory=_services({}, display_config=_raising(ValueError("boom"))))

    err = capsys.readouterr().err
    assert exit_code == 22
    assert "boom" in err
    assert "SystemExit" not in err


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("error", "expected"),
    [(PermissionError("denied"), 13), (OSError("disk full"), 1)],
    ids=["permission-denied", "general-error"],
)
def test_a_deploy_failure_exits_with_its_code_without_printing_systemexit(
    capsys: pytest.CaptureFixture[str], error: Exception, expected: int
) -> None:
    services = _services({}, deploy_configuration=_raising(error))
    exit_code = main(["config-deploy", "--target", "user"], services_factory=services)

    err = capsys.readouterr().err
    assert exit_code == expected
    assert str(error) in err
    assert "SystemExit" not in err


@pytest.mark.os_agnostic
def test_a_deliberate_exit_inside_deploy_keeps_its_own_code(capsys: pytest.CaptureFixture[str]) -> None:
    """click's Exit is a RuntimeError; the deploy failure branch must let it through unrelabelled."""
    services = _services({}, deploy_configuration=_raising(click.exceptions.Exit(78)))
    exit_code = main(["config-deploy", "--target", "user"], services_factory=services)

    err = capsys.readouterr().err
    assert exit_code == 78
    assert "Failed to deploy configuration" not in err


@pytest.mark.os_agnostic
def test_a_generate_examples_failure_exits_1_without_printing_systemexit(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory", encoding="utf-8")

    exit_code = main(
        ["config-generate-examples", "--destination", str(blocker / "sub")], services_factory=_services({})
    )

    err = capsys.readouterr().err
    assert exit_code == 1
    assert "Error:" in err
    assert "SystemExit" not in err


@pytest.mark.os_agnostic
def test_a_successful_command_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["info"], services_factory=_services({}))

    assert exit_code == 0
    assert "Info for bmk" in capsys.readouterr().out


# Each stage command with the pipeline prefix it dispatches. The pipeline is replaced through a
# real [tool.bmk.pipelines] overlay by one stage that exits 3, so the command's own failure path
# runs end to end and nothing inside bmk is patched.
_STAGE_COMMANDS: list[tuple[list[str], str]] = [
    (["build"], "bld"),
    (["clean"], "clean"),
    (["clean-all"], "clean_all"),
    (["commit", "msg"], "commit"),
    (["cov"], "cov"),
    (["custom", "probepipe"], "probepipe"),
    (["dependencies"], "deps"),
    (["push", "msg"], "push"),
    (["release"], "rel"),
    (["run"], "run"),
    (["testintegration"], "test_integration"),
    (["test-all"], "test_all"),
    (["test"], "test"),
]


def _project_whose_pipeline_exits_3(project: Path, prefix: str) -> None:
    probe = project / "probe.py"
    probe.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    pipeline: dict[str, Any] = {}
    # TOML requires scalar values before tables, so 'remove' goes before 'add'.
    remove = [stage.name for stage in PIPELINES.get(prefix, ())]
    if remove:
        pipeline["remove"] = remove
    pipeline["add"] = [{"name": "probe", "order": 1, "argv": [sys.executable, str(probe)]}]
    overlay = {"tool": {"bmk": {"pipelines": {prefix: pipeline}}}}
    (project / "pyproject.toml").write_text(rtoml.dumps(overlay), encoding="utf-8")


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("args", "prefix"), _STAGE_COMMANDS, ids=[args[0] for args, _ in _STAGE_COMMANDS])
def test_a_failing_stage_command_keeps_its_code_without_printing_systemexit(
    args: list[str],
    prefix: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _project_whose_pipeline_exits_3(tmp_path, prefix)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BMK_NO_VENV_SYNC", "1")

    exit_code = main(args, services_factory=_services({}))

    err = capsys.readouterr().err
    assert exit_code == 3, err
    assert "SystemExit" not in err


@pytest.mark.os_agnostic
def test_a_custom_pipeline_nobody_defined_exits_file_not_found_without_printing_systemexit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = main(["custom", "nosuchpipeline"], services_factory=_services({}))

    err = capsys.readouterr().err
    assert exit_code == ExitCode.FILE_NOT_FOUND
    assert "no pipeline defined for 'nosuchpipeline'" in err
    assert "SystemExit" not in err


@pytest.mark.os_agnostic
def test_no_cli_module_raises_a_bare_systemexit() -> None:
    """Close the shape, not the instances: a new command copying the old pattern goes red here.

    A bare SystemExit falls into main()'s catch-all and prints "SystemExit: N"; a CliRunner test
    never sees that, because it skips main(). Engine helpers (stagerunner/helpers) are out of
    this scan on purpose: they must not import the CLI's click context.
    """
    cli_root = Path(bmk.adapters.cli.__file__).parent
    modules = sorted(cli_root.rglob("*.py"))
    offenders = [
        f"{module.relative_to(cli_root)}:{node.lineno}"
        for module in modules
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
        if isinstance(node, ast.Raise)
        and node.exc is not None
        and isinstance(call := node.exc, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "SystemExit"
    ]

    assert len(modules) > 20, f"scanned only {len(modules)} modules under {cli_root}"
    assert offenders == [], f"exit through get_current_context().exit(code) instead: {offenders}"
