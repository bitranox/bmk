"""A passing JSON-mode run prints no per-request lines from bmk's HTTP client.

``init_logging`` bridges the stdlib root logger into lib_log_rich at the console level (INFO by
default), and httpx2 logs every request at INFO on its own stdlib logger. Unquieted, the
dependency stage of a passing ``make test`` printed one ``HTTP Request: GET .../json`` line per
PyPI document, straight to the console and past the stage's capture sink - the opposite of the
JSON-mode contract that a passing run prints only its result envelope.

These tests drive the path the real run takes: the production ``init_logging`` with the shipped
logging defaults, then the registered ``deps`` pipeline in JSON mode. PyPI is the only stand-in,
replaced at the network edge by ``pypi_stub``.

Imported helpers by bare module name: ``tests/`` has no ``__init__.py`` (see ``uv_stub.py``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import httpx2
import lib_log_rich.runtime
import orjson
import pytest
import rtoml
from lib_layered_config import Config
from pypi_stub import serve_pypi

import bmk.adapters.config
from bmk.adapters.logging.setup import InvalidLoggingConfigError, init_logging
from bmk.adapters.stagerunner import registry
from bmk.adapters.stagerunner.context import build_context
from bmk.adapters.stagerunner.engine import run_pipeline
from bmk.domain.enums import ToolOutputFormat

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The HTTP client's loggers bmk wires into the console; httpx2 logs requests, httpcore2 connections.
_HTTP_LOGGERS = ("httpx2", "httpcore2")

_SHIPPED_LOGGING_DEFAULTS = Path(bmk.adapters.config.__file__).parent / "defaultconfig.d" / "90-logging.toml"


@pytest.fixture(autouse=True)
def _restore_http_logger_levels() -> Iterator[None]:
    """Put the HTTP client's logger levels back: they are process-global and init_logging sets them.

    The shared ``isolated_logging_state`` fixture restores only the root logger.
    """
    saved = {name: logging.getLogger(name).level for name in _HTTP_LOGGERS}
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def _shipped_logging_config() -> Config:
    """The shipped ``[lib_log_rich]`` defaults, without colour so the captured text is plain.

    Read from the packaged file rather than through ``get_config``, so a config deployed on the
    machine running the tests cannot change the console level under test.
    """
    data = rtoml.loads(_SHIPPED_LOGGING_DEFAULTS.read_text(encoding="utf-8"))
    section = dict(data["lib_log_rich"])
    section["no_color"] = True
    section["force_color"] = False
    return Config({"lib_log_rich": section}, {})


def _project_with_one_current_dependency(tmp_path: Path) -> Path:
    """A project whose single dependency is already at PyPI's latest release, so the check passes."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["widget>=1.0"]\n',
        encoding="utf-8",
    )
    return tmp_path


def _serve_widget_current(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """PyPI answers that widget 1.0 is the latest release; returns the URLs asked for."""
    asked: list[str] = []
    document = orjson.dumps({"info": {"version": "1.0"}, "releases": {"1.0": [{"yanked": False}]}})

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(str(request.url))
        return httpx2.Response(200, content=document)

    serve_pypi(monkeypatch, handler)
    return asked


@pytest.mark.os_agnostic
def test_passing_json_mode_deps_stage_prints_no_http_request_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """The deps pipeline in JSON mode, under the production logging, prints only its envelope."""
    project = _project_with_one_current_dependency(tmp_path)
    asked = _serve_widget_current(monkeypatch)
    init_logging(_shipped_logging_config())
    ctx = build_context(project, (), command_prefix="deps", output_format=ToolOutputFormat.JSON, show_warnings=False)

    exit_code = run_pipeline(list(registry.PIPELINES["deps"]), ctx)
    # The console is fed from a queue worker; shutting down drains it before the output is read.
    lib_log_rich.runtime.shutdown()
    captured = capfd.readouterr()

    assert asked, "the stage never reached PyPI, so it proves nothing about the request log"
    assert exit_code == 0, captured.out + captured.err
    assert "HTTP Request" not in captured.out + captured.err
    assert '"result":"pass"' in captured.out


@pytest.mark.os_agnostic
def test_http_client_warnings_still_reach_the_console(capfd: pytest.CaptureFixture[str]) -> None:
    """Quieting the per-request INFO lines must not hide the HTTP client's warnings."""
    init_logging(_shipped_logging_config())

    logging.getLogger("httpx2").warning("probe warning from httpx2")
    logging.getLogger("httpcore2.connection").warning("probe warning from httpcore2")
    lib_log_rich.runtime.shutdown()
    err = capfd.readouterr().err

    assert "probe warning from httpx2" in err
    assert "probe warning from httpcore2" in err


@pytest.mark.os_agnostic
def test_http_client_info_lines_do_not_reach_the_console(capfd: pytest.CaptureFixture[str]) -> None:
    """The per-request and per-connection INFO records stay off the console at the shipped INFO level."""
    init_logging(_shipped_logging_config())

    logging.getLogger("httpx2").info("HTTP Request: GET probe")
    logging.getLogger("httpcore2.connection").info("connect_tcp.started probe")
    logging.getLogger("bmk.probe").info("bmk's own info line")
    lib_log_rich.runtime.shutdown()
    err = capfd.readouterr().err

    assert "HTTP Request" not in err
    assert "connect_tcp.started probe" not in err
    # A control: the console is live at INFO, so an absent line means filtered, not unprinted.
    assert "bmk's own info line" in err


@pytest.mark.os_agnostic
def test_http_client_info_lines_stay_quiet_when_the_logging_config_is_refused(
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A refused ``[lib_log_rich]`` section starts the default logging; that path is quieted too."""
    with pytest.raises(InvalidLoggingConfigError):
        init_logging(Config({"lib_log_rich": {"rate_limit": "100:60", "no_color": True}}, {}))

    logging.getLogger("httpx2").info("HTTP Request: GET probe")
    logging.getLogger("bmk.probe").info("bmk's own info line")
    lib_log_rich.runtime.shutdown()
    err = capfd.readouterr().err

    assert "HTTP Request" not in err
    # A control: the default logging is live at INFO, so an absent line means filtered, not unprinted.
    assert "bmk's own info line" in err
