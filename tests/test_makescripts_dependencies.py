"""Behaviour tests for makescripts._dependencies: version parsing, PyPI queries, and dependency management."""

# pyright: reportPrivateUsage=false, reportUnknownVariableType=false

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import orjson
import pytest

from bmk.makescripts._dependencies import (
    DependencyInfo,
    _build_updated_spec,
    _extract_all_dependencies,
    _extract_dependencies_from_list,
    _fetch_latest_version_below,
    _fetch_pypi_data,
    _find_packages_needing_install,
    _get_installed_version,
    _run_pip_install,
    check_dependencies,
    compare_versions,
    fetch_latest_version,
    main,
    print_report,
    sync_installed_packages,
    update_dependencies,
)
from bmk.makescripts._toml_config import PyprojectConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completed(returncode: int, *, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """Build a CompletedProcess stub for subprocess mocking."""
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _make_config(raw_data: dict[str, Any]) -> PyprojectConfig:
    """Build a PyprojectConfig from a raw dict."""
    return PyprojectConfig.from_dict(raw_data)


def _make_dep(
    *,
    name: str = "pkg",
    source: str = "[project].dependencies",
    constraint: str = ">=1.0.0",
    current_min: str = "1.0.0",
    latest: str = "2.0.0",
    status: str = "outdated",
    original_spec: str = "pkg>=1.0.0",
    upper_bound: str = "",
) -> DependencyInfo:
    """Build a DependencyInfo with sensible defaults."""
    return DependencyInfo(
        name=name,
        source=source,
        constraint=constraint,
        current_min=current_min,
        latest=latest,
        status=status,
        original_spec=original_spec,
        upper_bound=upper_bound,
    )


def _mock_httpx_response(*, status_code: int = 200, content: bytes = b"{}") -> MagicMock:
    """Build a mock httpx.Response with controllable status and content."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.content = content
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        http_error = httpx.HTTPStatusError(
            "error",
            request=MagicMock(spec=httpx.Request),
            response=resp,
        )
        resp.raise_for_status.side_effect = http_error
    return resp


# ---------------------------------------------------------------------------
# _parse_version_constraint — extras handling and fallback
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_parse_version_constraint_strips_extras() -> None:
    """Extras in brackets are removed before parsing the constraint."""
    from bmk.makescripts._dependencies import _parse_version_constraint

    name, constraint, min_version, upper_bound = _parse_version_constraint("package[extra]>=1.0")

    assert name == "package"
    assert min_version == "1.0"
    assert constraint == ">=1.0"
    assert upper_bound == ""


@pytest.mark.os_agnostic
def test_parse_version_constraint_strips_multiple_extras() -> None:
    """Multiple extras in brackets are removed."""
    from bmk.makescripts._dependencies import _parse_version_constraint

    name, _constraint, min_version, _ = _parse_version_constraint("pkg[foo,bar]>=2.0")

    assert name == "pkg"
    assert min_version == "2.0"


@pytest.mark.os_agnostic
def test_parse_version_constraint_fallback_for_unparseable_spec() -> None:
    """Unparseable spec falls back to returning the spec as name with empty fields."""
    from bmk.makescripts._dependencies import _parse_version_constraint

    name, constraint, min_version, upper_bound = _parse_version_constraint("!!!invalid!!!")

    assert name == "!!!invalid!!!"
    assert constraint == ""
    assert min_version == ""
    assert upper_bound == ""


@pytest.mark.os_agnostic
def test_parse_version_constraint_empty_spec() -> None:
    """Empty spec returns all empty strings."""
    from bmk.makescripts._dependencies import _parse_version_constraint

    assert _parse_version_constraint("") == ("", "", "", "")


@pytest.mark.os_agnostic
def test_parse_version_constraint_with_marker_and_extras() -> None:
    """Markers and extras are both stripped correctly."""
    from bmk.makescripts._dependencies import _parse_version_constraint

    name, _constraint, min_version, _ = _parse_version_constraint("tomli[extra]>=2.0.0; python_version<'3.11'")

    assert name == "tomli"
    assert min_version == "2.0.0"


# ---------------------------------------------------------------------------
# _fetch_pypi_data — HTTP error cases
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.httpx.get")
def test_fetch_pypi_data_returns_none_on_404(mock_get: MagicMock) -> None:
    """Returns None when PyPI responds with 404."""
    mock_get.return_value = _mock_httpx_response(status_code=404)

    result = _fetch_pypi_data("nonexistent-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.httpx.get")
def test_fetch_pypi_data_returns_none_on_connection_error(mock_get: MagicMock) -> None:
    """Returns None when httpx raises a ConnectError."""
    mock_get.side_effect = httpx.ConnectError("connection refused")

    result = _fetch_pypi_data("some-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.httpx.get")
def test_fetch_pypi_data_returns_none_on_timeout(mock_get: MagicMock) -> None:
    """Returns None when httpx raises a TimeoutException."""
    mock_get.side_effect = httpx.TimeoutException("read timeout")

    result = _fetch_pypi_data("some-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.httpx.get")
def test_fetch_pypi_data_returns_none_on_json_decode_error(mock_get: MagicMock) -> None:
    """Returns None when response body is not valid JSON."""
    resp = _mock_httpx_response(status_code=200, content=b"not json{{{")
    mock_get.return_value = resp

    result = _fetch_pypi_data("some-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.httpx.get")
def test_fetch_pypi_data_returns_parsed_json_on_success(mock_get: MagicMock) -> None:
    """Returns parsed dict on successful response."""
    payload = {"info": {"version": "3.0.0"}}
    resp = _mock_httpx_response(status_code=200, content=orjson.dumps(payload))
    mock_get.return_value = resp

    result = _fetch_pypi_data("some-pkg")

    assert result == payload


# ---------------------------------------------------------------------------
# fetch_latest_version — success path, None path, non-dict info
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_returns_version_string(mock_pypi: MagicMock) -> None:
    """Returns the version string from PyPI info on success."""
    mock_pypi.return_value = {"info": {"version": "4.1.2"}}

    result = fetch_latest_version("requests")

    assert result == "4.1.2"


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_returns_none_when_pypi_fails(mock_pypi: MagicMock) -> None:
    """Returns None when PyPI data is unavailable."""
    mock_pypi.return_value = None

    result = fetch_latest_version("nonexistent-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_returns_empty_when_info_not_dict(mock_pypi: MagicMock) -> None:
    """Returns empty string when info field is not a dict."""
    mock_pypi.return_value = {"info": "not-a-dict"}

    result = fetch_latest_version("some-pkg")

    assert result == ""


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_returns_empty_when_version_missing(mock_pypi: MagicMock) -> None:
    """Returns empty string when version key is absent from info."""
    mock_pypi.return_value = {"info": {"name": "pkg"}}

    result = fetch_latest_version("some-pkg")

    assert result == ""


# ---------------------------------------------------------------------------
# _fetch_latest_version_below — filtering, prerelease skip, sorting, empty
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_below_returns_highest_within_bound(mock_pypi: MagicMock) -> None:
    """Returns the highest version below the upper bound."""
    mock_pypi.return_value = {
        "releases": {
            "7.0.0": [],
            "8.0.0": [],
            "8.5.0": [],
            "9.0.0": [],
            "10.0.0": [],
        }
    }

    result = _fetch_latest_version_below("pytest", "9")

    assert result == "8.5.0"


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_below_skips_prereleases(mock_pypi: MagicMock) -> None:
    """Prerelease versions (alpha, beta, rc, dev) are excluded."""
    mock_pypi.return_value = {
        "releases": {
            "8.0.0": [],
            "8.1.0a1": [],
            "8.2.0b2": [],
            "8.3.0rc1": [],
            "8.4.0dev1": [],
            "9.0.0": [],
        }
    }

    result = _fetch_latest_version_below("pytest", "9")

    assert result == "8.0.0"


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_below_returns_none_when_pypi_fails(mock_pypi: MagicMock) -> None:
    """Returns None when PyPI data is unavailable."""
    mock_pypi.return_value = None

    result = _fetch_latest_version_below("pytest", "9")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_below_returns_none_when_no_releases(mock_pypi: MagicMock) -> None:
    """Returns None when releases dict is empty."""
    mock_pypi.return_value = {"releases": {}}

    result = _fetch_latest_version_below("pytest", "9")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_below_returns_none_when_all_above_bound(mock_pypi: MagicMock) -> None:
    """Returns None when all versions are at or above the upper bound."""
    mock_pypi.return_value = {
        "releases": {
            "9.0.0": [],
            "10.0.0": [],
        }
    }

    result = _fetch_latest_version_below("pytest", "9")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_below_returns_none_when_releases_not_dict(mock_pypi: MagicMock) -> None:
    """Returns None when releases field is not a dict."""
    mock_pypi.return_value = {"releases": "not-a-dict"}

    result = _fetch_latest_version_below("pytest", "9")

    assert result is None


# ---------------------------------------------------------------------------
# _extract_dependencies_from_list — empty dep skip, pinned within range
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version")
def test_extract_dependencies_skips_empty_strings(mock_latest: MagicMock) -> None:
    """Empty strings in the dependency list are silently skipped."""
    mock_latest.return_value = "1.0.0"

    results = _extract_dependencies_from_list(["", "pkg>=1.0.0", ""], "test-source")

    assert len(results) == 1
    assert results[0].name == "pkg"


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version")
def test_extract_dependencies_skips_direct_url_references(mock_latest: MagicMock) -> None:
    """PEP 440 direct URL references (pkg @ git+https://...) are skipped — not on PyPI."""
    mock_latest.return_value = "1.0.0"

    results = _extract_dependencies_from_list(
        [
            "thumbmaker_lib @ git+https://github.com/MyOrg/thumbmaker_lib.git",
            "normal_pkg>=1.0.0",
            "another @ git+https://github.com/MyOrg/another.git",
        ],
        "test-source",
    )

    assert len(results) == 1
    assert results[0].name == "normal_pkg"
    mock_latest.assert_called_once()


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_latest_version_below")
@patch("bmk.makescripts._dependencies.fetch_latest_version")
def test_extract_dependencies_detects_pinned_within_range(mock_latest: MagicMock, mock_below: MagicMock) -> None:
    """When min_version equals latest-in-range, status is pinned."""
    mock_latest.return_value = "10.0.0"  # Exceeds upper bound
    mock_below.return_value = "8.4.2"  # Latest within range, same as current_min

    results = _extract_dependencies_from_list(["pytest>=8.4.2,<9"], "test-source")

    assert len(results) == 1
    assert results[0].status == "pinned"
    assert "pinned <9" in results[0].latest


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_latest_version_below")
@patch("bmk.makescripts._dependencies.fetch_latest_version")
def test_extract_dependencies_detects_outdated_within_range(mock_latest: MagicMock, mock_below: MagicMock) -> None:
    """When a newer version exists within the allowed range, status is outdated."""
    mock_latest.return_value = "10.0.0"
    mock_below.return_value = "8.5.0"

    results = _extract_dependencies_from_list(["pytest>=8.4.2,<9"], "test-source")

    assert len(results) == 1
    assert results[0].status == "outdated"
    assert "8.5.0" in results[0].latest


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_latest_version_below")
@patch("bmk.makescripts._dependencies.fetch_latest_version")
def test_extract_dependencies_pinned_when_below_returns_none(mock_latest: MagicMock, mock_below: MagicMock) -> None:
    """When no version within range is found, status is pinned."""
    mock_latest.return_value = "10.0.0"
    mock_below.return_value = None

    results = _extract_dependencies_from_list(["pytest>=8.4.2,<9"], "test-source")

    assert len(results) == 1
    assert results[0].status == "pinned"


# ---------------------------------------------------------------------------
# _extract_all_dependencies — optional deps, build system, poetry, pdm, uv
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.makescripts._dependencies._fetch_latest_version_below", return_value=None)
def test_extract_all_dependencies_project_dependencies(mock_below: MagicMock, mock_latest: MagicMock) -> None:
    """Extracts dependencies from [project].dependencies."""
    config = _make_config(
        {
            "project": {
                "name": "test",
                "version": "1.0.0",
                "dependencies": ["requests>=1.0.0"],
            }
        }
    )

    results = _extract_all_dependencies(config)

    names = [d.name for d in results]
    assert "requests" in names


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.makescripts._dependencies._fetch_latest_version_below", return_value=None)
def test_extract_all_dependencies_optional_dependencies(mock_below: MagicMock, mock_latest: MagicMock) -> None:
    """Extracts dependencies from [project.optional-dependencies]."""
    config = _make_config(
        {
            "project": {
                "name": "test",
                "version": "1.0.0",
                "optional-dependencies": {
                    "dev": ["pytest>=7.0.0"],
                },
            }
        }
    )

    results = _extract_all_dependencies(config)

    assert any(d.name == "pytest" for d in results)
    assert any("[project.optional-dependencies].dev" in d.source for d in results)


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.makescripts._dependencies._fetch_latest_version_below", return_value=None)
def test_extract_all_dependencies_build_system(mock_below: MagicMock, mock_latest: MagicMock) -> None:
    """Extracts dependencies from [build-system].requires."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "build-system": {"requires": ["hatchling>=1.27.0"]},
        }
    )

    results = _extract_all_dependencies(config)

    assert any(d.name == "hatchling" for d in results)
    assert any("[build-system].requires" in d.source for d in results)


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.makescripts._dependencies._fetch_latest_version_below", return_value=None)
def test_extract_all_dependencies_dependency_groups(mock_below: MagicMock, mock_latest: MagicMock) -> None:
    """Extracts dependencies from [dependency-groups] (PEP 735)."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "dependency-groups": {
                "test": ["hypothesis>=6.0.0"],
            },
        }
    )

    results = _extract_all_dependencies(config)

    assert any(d.name == "hypothesis" for d in results)
    assert any("[dependency-groups].test" in d.source for d in results)


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.makescripts._dependencies._fetch_latest_version_below", return_value=None)
def test_extract_all_dependencies_pdm_dev_dependencies(mock_below: MagicMock, mock_latest: MagicMock) -> None:
    """Extracts dependencies from [tool.pdm.dev-dependencies]."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {
                "pdm": {
                    "dev-dependencies": {
                        "dev": ["ruff>=0.5.0"],
                    },
                },
            },
        }
    )

    results = _extract_all_dependencies(config)

    assert any(d.name == "ruff" for d in results)
    assert any("[tool.pdm.dev-dependencies].dev" in d.source for d in results)


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.makescripts._dependencies._fetch_latest_version_below", return_value=None)
def test_extract_all_dependencies_poetry_dependencies(mock_below: MagicMock, mock_latest: MagicMock) -> None:
    """Extracts dependencies from [tool.poetry.dependencies]."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {
                "poetry": {
                    "dependencies": {
                        "click": "^8.0",
                    },
                },
            },
        }
    )

    results = _extract_all_dependencies(config)

    assert any(d.name == "click" for d in results)
    assert any("[tool.poetry.dependencies]" in d.source for d in results)


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.makescripts._dependencies._fetch_latest_version_below", return_value=None)
def test_extract_all_dependencies_poetry_dev_dependencies(mock_below: MagicMock, mock_latest: MagicMock) -> None:
    """Extracts dependencies from [tool.poetry.dev-dependencies]."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {
                "poetry": {
                    "dev-dependencies": {
                        "mypy": "^1.0",
                    },
                },
            },
        }
    )

    results = _extract_all_dependencies(config)

    assert any(d.name == "mypy" for d in results)
    assert any("[tool.poetry.dev-dependencies]" in d.source for d in results)


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.makescripts._dependencies._fetch_latest_version_below", return_value=None)
def test_extract_all_dependencies_poetry_group_dependencies(mock_below: MagicMock, mock_latest: MagicMock) -> None:
    """Extracts dependencies from [tool.poetry.group.*.dependencies]."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {
                "poetry": {
                    "group": {
                        "docs": {
                            "dependencies": {
                                "sphinx": "^5.0",
                            },
                        },
                    },
                },
            },
        }
    )

    results = _extract_all_dependencies(config)

    assert any(d.name == "sphinx" for d in results)
    assert any("[tool.poetry.group.docs.dependencies]" in d.source for d in results)


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.makescripts._dependencies._fetch_latest_version_below", return_value=None)
def test_extract_all_dependencies_uv_dev_dependencies(mock_below: MagicMock, mock_latest: MagicMock) -> None:
    """Extracts dependencies from [tool.uv.dev-dependencies]."""
    config = _make_config(
        {
            "project": {"name": "test", "version": "1.0.0"},
            "tool": {
                "uv": {
                    "dev-dependencies": ["black>=24.0.0"],
                },
            },
        }
    )

    results = _extract_all_dependencies(config)

    assert any(d.name == "black" for d in results)
    assert any("[tool.uv.dev-dependencies]" in d.source for d in results)


# ---------------------------------------------------------------------------
# check_dependencies — basic invocation
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.makescripts._dependencies._fetch_latest_version_below", return_value=None)
def test_check_dependencies_reads_pyproject(mock_below: MagicMock, mock_latest: MagicMock, tmp_path: Path) -> None:
    """check_dependencies reads a pyproject.toml and returns DependencyInfo list."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\ndependencies = ["requests>=1.0.0"]\n')

    results = check_dependencies(pyproject)

    assert isinstance(results, list)
    assert any(d.name == "requests" for d in results)


# ---------------------------------------------------------------------------
# print_report — error count increment
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_print_report_counts_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """Error status dependencies are counted in the summary."""
    deps = [
        _make_dep(name="broken-pkg", status="error", latest="not found"),
    ]

    exit_code = print_report(deps, verbose=True)

    captured = capsys.readouterr()
    assert "Errors:     1" in captured.out
    assert exit_code == 0  # Only outdated triggers non-zero


@pytest.mark.os_agnostic
def test_print_report_returns_one_when_outdated(capsys: pytest.CaptureFixture[str]) -> None:
    """Returns exit code 1 when any dependency is outdated."""
    deps = [
        _make_dep(name="old-pkg", status="outdated"),
    ]

    exit_code = print_report(deps, verbose=True)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Outdated:   1" in captured.out


@pytest.mark.os_agnostic
def test_print_report_returns_zero_when_all_up_to_date(capsys: pytest.CaptureFixture[str]) -> None:
    """Returns exit code 0 when all dependencies are up-to-date."""
    deps = [
        _make_dep(name="good-pkg", status="up-to-date", latest="1.0.0"),
    ]

    exit_code = print_report(deps, verbose=True)

    assert exit_code == 0


@pytest.mark.os_agnostic
def test_print_report_empty_deps(capsys: pytest.CaptureFixture[str]) -> None:
    """Prints a message and returns 0 when no dependencies are found."""
    exit_code = print_report([])

    captured = capsys.readouterr()
    assert "No dependencies found" in captured.out
    assert exit_code == 0


# ---------------------------------------------------------------------------
# _build_updated_spec — markers, extras, no constraint, extras re-add
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_build_updated_spec_preserves_marker() -> None:
    """Environment markers are preserved in the updated spec."""
    dep = _make_dep(
        original_spec="tomli>=1.0.0; python_version<'3.11'",
        latest="2.0.0",
    )

    result = _build_updated_spec(dep)

    assert "; python_version<'3.11'" in result
    assert ">=2.0.0" in result


@pytest.mark.os_agnostic
def test_build_updated_spec_preserves_extras() -> None:
    """Extras brackets are preserved in the updated spec."""
    dep = _make_dep(
        original_spec="pyright[nodejs]>=1.0.0",
        latest="2.0.0",
    )

    result = _build_updated_spec(dep)

    assert "[nodejs]" in result
    assert ">=2.0.0" in result


@pytest.mark.os_agnostic
def test_build_updated_spec_adds_constraint_when_none() -> None:
    """Adds >=latest when the original spec has no version constraint."""
    dep = _make_dep(
        original_spec="requests",
        latest="2.31.0",
    )

    result = _build_updated_spec(dep)

    assert result == "requests>=2.31.0"


@pytest.mark.os_agnostic
def test_build_updated_spec_adds_constraint_with_extras_when_none() -> None:
    """Adds >=latest preserving extras when no constraint exists."""
    dep = _make_dep(
        original_spec="pyright[nodejs]",
        latest="1.5.0",
    )

    result = _build_updated_spec(dep)

    assert "[nodejs]" in result
    assert ">=1.5.0" in result


@pytest.mark.os_agnostic
def test_build_updated_spec_returns_original_when_latest_not_found() -> None:
    """Returns the original spec unchanged when latest is 'not found'."""
    dep = _make_dep(
        original_spec="unknown-pkg>=1.0.0",
        latest="not found",
    )

    result = _build_updated_spec(dep)

    assert result == "unknown-pkg>=1.0.0"


@pytest.mark.os_agnostic
def test_build_updated_spec_returns_original_when_empty_latest() -> None:
    """Returns the original spec unchanged when latest is empty."""
    dep = _make_dep(
        original_spec="pkg>=1.0.0",
        latest="",
    )

    result = _build_updated_spec(dep)

    assert result == "pkg>=1.0.0"


@pytest.mark.os_agnostic
def test_build_updated_spec_re_adds_extras_when_stripped() -> None:
    """Extras are re-added if regex substitution accidentally strips them."""
    dep = _make_dep(
        original_spec="pkg[extra]>=1.0.0",
        latest="3.0.0",
    )

    result = _build_updated_spec(dep)

    assert "[extra]" in result
    assert "3.0.0" in result


@pytest.mark.os_agnostic
def test_build_updated_spec_strips_display_annotations_from_latest() -> None:
    """Display annotations like '(max <1.3, absolute: 1.3.0)' must not leak into the spec."""
    dep = _make_dep(
        original_spec="pytest-asyncio>=1.1.0",
        latest="1.2.0 (max <1.3, absolute: 1.3.0)",
    )

    result = _build_updated_spec(dep)

    assert result == "pytest-asyncio>=1.2.0"
    assert "(max" not in result
    assert "absolute" not in result


@pytest.mark.os_agnostic
def test_build_updated_spec_preserves_upper_bound() -> None:
    """Upper-bound constraints (<X.Y) must be preserved, only lower bound is updated."""
    dep = _make_dep(
        original_spec="pytest-asyncio>=1.1.0,<1.3; python_version<'3.10'",
        latest="1.2.0 (max <1.3, absolute: 1.3.0)",
        upper_bound="1.3",
    )

    result = _build_updated_spec(dep)

    assert result == "pytest-asyncio>=1.2.0,<1.3; python_version<'3.10'"


# ---------------------------------------------------------------------------
# _get_installed_version — found and not found
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_get_installed_version_returns_version_for_installed_package() -> None:
    """Returns the installed version of a known package."""
    version = _get_installed_version("pip")

    assert version is not None
    assert len(version) > 0


@pytest.mark.os_agnostic
def test_get_installed_version_returns_none_for_missing_package() -> None:
    """Returns None for a package that is not installed."""
    version = _get_installed_version("nonexistent-fake-package-xyz-12345")

    assert version is None


# ---------------------------------------------------------------------------
# _find_packages_needing_install — installed None, outdated
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._get_installed_version")
def test_find_packages_needing_install_not_installed(mock_installed: MagicMock) -> None:
    """Packages not installed are included in the results."""
    mock_installed.return_value = None
    deps = [_make_dep(name="missing-pkg", current_min="1.0.0")]

    results = _find_packages_needing_install(deps)

    assert len(results) == 1
    assert results[0] == ("missing-pkg", None, "1.0.0")


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._get_installed_version")
def test_find_packages_needing_install_outdated(mock_installed: MagicMock) -> None:
    """Packages with an installed version below the required minimum are included."""
    mock_installed.return_value = "0.9.0"
    deps = [_make_dep(name="old-pkg", current_min="1.0.0")]

    results = _find_packages_needing_install(deps)

    assert len(results) == 1
    assert results[0] == ("old-pkg", "0.9.0", "1.0.0")


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._get_installed_version")
def test_find_packages_needing_install_up_to_date(mock_installed: MagicMock) -> None:
    """Up-to-date packages are not included."""
    mock_installed.return_value = "2.0.0"
    deps = [_make_dep(name="good-pkg", current_min="1.0.0")]

    results = _find_packages_needing_install(deps)

    assert len(results) == 0


@pytest.mark.os_agnostic
def test_find_packages_needing_install_skips_no_min_version() -> None:
    """Dependencies without a current_min are skipped."""
    deps = [_make_dep(name="bare-pkg", current_min="")]

    results = _find_packages_needing_install(deps)

    assert len(results) == 0


# ---------------------------------------------------------------------------
# _run_pip_install — subprocess invocation, EXTERNALLY-MANAGED detection
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_run_pip_install_builds_pip_command(mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Builds a pip install command with --upgrade and package specs."""
    mock_run.return_value = _make_completed(0)
    monkeypatch.setattr("sys.platform", "win32")  # Avoid EXTERNALLY-MANAGED check

    needs: list[tuple[str, str | None, str]] = [("requests", None, "2.31.0"), ("click", "8.0.0", "8.1.0")]

    exit_code = _run_pip_install(needs)

    assert exit_code == 0
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "--upgrade" in cmd
    assert "requests>=2.31.0" in cmd
    assert "click>=8.1.0" in cmd


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_run_pip_install_adds_break_system_packages_on_linux(
    mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Adds --break-system-packages when EXTERNALLY-MANAGED marker exists on Linux."""
    mock_run.return_value = _make_completed(0)
    monkeypatch.setattr("sys.platform", "linux")

    # Create the EXTERNALLY-MANAGED marker at sys.prefix
    marker = tmp_path / "EXTERNALLY-MANAGED"
    marker.write_text("This installation is externally managed")
    monkeypatch.setattr("sys.prefix", str(tmp_path))

    needs: list[tuple[str, str | None, str]] = [("requests", None, "1.0.0")]

    _run_pip_install(needs)

    cmd = mock_run.call_args[0][0]
    assert "--break-system-packages" in cmd


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_run_pip_install_no_break_system_packages_without_marker(
    mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Does not add --break-system-packages when no EXTERNALLY-MANAGED marker on Linux."""
    mock_run.return_value = _make_completed(0)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.prefix", str(tmp_path))

    # Also mock the lib path to avoid finding it there
    monkeypatch.setattr("sys.version_info", type("vi", (), {"major": 3, "minor": 99})())

    needs: list[tuple[str, str | None, str]] = [("requests", None, "1.0.0")]

    _run_pip_install(needs)

    cmd = mock_run.call_args[0][0]
    assert "--break-system-packages" not in cmd


# ---------------------------------------------------------------------------
# sync_installed_packages — dry run, actual run, no updates
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._run_pip_install")
@patch("bmk.makescripts._dependencies._find_packages_needing_install")
def test_sync_installed_packages_dry_run(
    mock_find: MagicMock, mock_pip: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dry run shows what would be installed but does not run pip."""
    mock_find.return_value = [("requests", None, "2.31.0")]

    result = sync_installed_packages([], dry_run=True)

    assert result == 1
    mock_pip.assert_not_called()
    captured = capsys.readouterr()
    assert "[DRY RUN]" in captured.out


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._run_pip_install", return_value=0)
@patch("bmk.makescripts._dependencies._find_packages_needing_install")
def test_sync_installed_packages_actual_run(
    mock_find: MagicMock, mock_pip: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Actual run calls pip install and reports success."""
    mock_find.return_value = [("requests", "1.0.0", "2.31.0")]

    result = sync_installed_packages([])

    assert result == 1
    mock_pip.assert_called_once()
    captured = capsys.readouterr()
    assert "Successfully installed/updated" in captured.out


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._run_pip_install", return_value=1)
@patch("bmk.makescripts._dependencies._find_packages_needing_install")
def test_sync_installed_packages_reports_pip_failure(
    mock_find: MagicMock, mock_pip: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reports pip failure when exit code is non-zero."""
    mock_find.return_value = [("requests", None, "2.31.0")]

    sync_installed_packages([])

    captured = capsys.readouterr()
    assert "pip install failed" in captured.err


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._find_packages_needing_install")
def test_sync_installed_packages_no_updates_needed(mock_find: MagicMock, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 0 when all installed packages match requirements."""
    mock_find.return_value = []

    result = sync_installed_packages([])

    assert result == 0
    captured = capsys.readouterr()
    assert "All installed packages match" in captured.out


# ---------------------------------------------------------------------------
# update_dependencies — dry run, actual update, not found in file
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_update_dependencies_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Dry run shows what would change without modifying the file."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = [\n    "requests>=1.0.0",\n]\n')

    deps = [
        _make_dep(
            name="requests",
            status="outdated",
            original_spec="requests>=1.0.0",
            latest="2.31.0",
        ),
    ]

    count = update_dependencies(deps, pyproject, dry_run=True)

    assert count == 1
    # File should not be modified
    content = pyproject.read_text()
    assert "requests>=1.0.0" in content
    captured = capsys.readouterr()
    assert "[DRY RUN]" in captured.out


@pytest.mark.os_agnostic
def test_update_dependencies_actual_update(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Actual update modifies the pyproject.toml file."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = [\n    "requests>=1.0.0",\n]\n')

    deps = [
        _make_dep(
            name="requests",
            status="outdated",
            original_spec="requests>=1.0.0",
            latest="2.31.0",
        ),
    ]

    count = update_dependencies(deps, pyproject)

    assert count == 1
    content = pyproject.read_text()
    assert "requests>=2.31.0" in content
    captured = capsys.readouterr()
    assert "Updated 1 dependencies" in captured.out


@pytest.mark.os_agnostic
def test_update_dependencies_not_found_in_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Reports manual update needed when spec cannot be located in the file."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\ndependencies = []\n")

    deps = [
        _make_dep(
            name="phantom",
            status="outdated",
            original_spec="phantom>=1.0.0",
            latest="2.0.0",
        ),
    ]

    count = update_dependencies(deps, pyproject)

    assert count == 0
    captured = capsys.readouterr()
    assert "Could not locate in file" in captured.out


@pytest.mark.os_agnostic
def test_update_dependencies_no_outdated(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Returns 0 and prints message when nothing is outdated."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["requests>=2.31.0"]\n')

    deps = [
        _make_dep(name="requests", status="up-to-date"),
    ]

    count = update_dependencies(deps, pyproject)

    assert count == 0
    captured = capsys.readouterr()
    assert "All dependencies are up-to-date" in captured.out


@pytest.mark.os_agnostic
def test_update_dependencies_with_single_quoted_spec(tmp_path: Path) -> None:
    """Updates specs enclosed in single quotes."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\ndependencies = [\n    'click>=7.0.0',\n]\n")

    deps = [
        _make_dep(
            name="click",
            status="outdated",
            original_spec="click>=7.0.0",
            latest="8.1.0",
        ),
    ]

    count = update_dependencies(deps, pyproject)

    assert count == 1
    content = pyproject.read_text()
    assert "click>=8.1.0" in content


# ---------------------------------------------------------------------------
# main — with update flag, without
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.sync_installed_packages", return_value=0)
@patch("bmk.makescripts._dependencies.update_dependencies", return_value=0)
@patch("bmk.makescripts._dependencies.print_report", return_value=0)
@patch("bmk.makescripts._dependencies.check_dependencies")
def test_main_without_update(
    mock_check: MagicMock,
    mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --update, reports but does not update."""
    mock_check.return_value = [_make_dep(status="up-to-date")]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    exit_code = main(pyproject=pyproject)

    assert exit_code == 0
    mock_update.assert_not_called()
    mock_sync.assert_not_called()


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.sync_installed_packages", return_value=0)
@patch("bmk.makescripts._dependencies.update_dependencies", return_value=1)
@patch("bmk.makescripts._dependencies.print_report", return_value=1)
@patch("bmk.makescripts._dependencies.check_dependencies")
def test_main_with_update(
    mock_check: MagicMock,
    mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With --update, calls update_dependencies and sync_installed_packages."""
    mock_check.return_value = [_make_dep(status="outdated")]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    exit_code = main(update=True, pyproject=pyproject)

    assert exit_code == 0
    mock_update.assert_called_once()
    mock_sync.assert_called_once()


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.sync_installed_packages", return_value=0)
@patch("bmk.makescripts._dependencies.update_dependencies", return_value=2)
@patch("bmk.makescripts._dependencies.print_report", return_value=1)
@patch("bmk.makescripts._dependencies.check_dependencies")
def test_main_with_update_re_checks_after_changes(
    mock_check: MagicMock,
    mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """After updating pyproject.toml, re-checks dependencies."""
    mock_check.return_value = [_make_dep(status="outdated")]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    main(update=True, pyproject=pyproject)

    # check_dependencies called twice: initial and re-check
    assert mock_check.call_count == 2


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.sync_installed_packages", return_value=0)
@patch("bmk.makescripts._dependencies.update_dependencies", return_value=2)
@patch("bmk.makescripts._dependencies.print_report", return_value=1)
@patch("bmk.makescripts._dependencies.check_dependencies")
def test_main_with_update_dry_run_does_not_recheck(
    mock_check: MagicMock,
    mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dry run with update does not re-check dependencies after update."""
    mock_check.return_value = [_make_dep(status="outdated")]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    main(update=True, dry_run=True, pyproject=pyproject)

    # check_dependencies called only once (no re-check in dry run)
    assert mock_check.call_count == 1


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.sync_installed_packages", return_value=0)
@patch("bmk.makescripts._dependencies.update_dependencies", return_value=0)
@patch("bmk.makescripts._dependencies.print_report", return_value=1)
@patch("bmk.makescripts._dependencies.check_dependencies")
def test_main_returns_report_exit_code_without_update(
    mock_check: MagicMock,
    mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --update, returns the exit code from print_report."""
    mock_check.return_value = [_make_dep(status="outdated")]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    exit_code = main(pyproject=pyproject)

    assert exit_code == 1


# ---------------------------------------------------------------------------
# compare_versions — basic checks
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_compare_versions_up_to_date() -> None:
    """Returns up-to-date when current matches or exceeds latest."""
    assert compare_versions("2.0.0", "1.0.0") == "up-to-date"
    assert compare_versions("1.0.0", "1.0.0") == "up-to-date"


@pytest.mark.os_agnostic
def test_compare_versions_outdated() -> None:
    """Returns outdated when current is below latest."""
    assert compare_versions("1.0.0", "2.0.0") == "outdated"


@pytest.mark.os_agnostic
def test_compare_versions_unknown_on_empty() -> None:
    """Returns unknown when either version is empty."""
    assert compare_versions("", "2.0.0") == "unknown"
    assert compare_versions("1.0.0", "") == "unknown"


# ---------------------------------------------------------------------------
# Remaining branch coverage — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_parse_version_constraint_unclosed_bracket() -> None:
    """Unclosed bracket in extras is left as-is (bracket found, no close bracket)."""
    from bmk.makescripts._dependencies import _parse_version_constraint

    name, _constraint, _min_version, _ = _parse_version_constraint("pkg[extra>=1.0")

    # The bracket is not stripped because close_bracket == -1
    # The regex still parses what it can
    assert name is not None


@pytest.mark.os_agnostic
def test_parse_version_constraint_only_upper_bound() -> None:
    """Constraint with only upper bound (no >=) leaves min_version empty."""
    from bmk.makescripts._dependencies import _parse_version_constraint

    name, constraint, min_version, upper_bound = _parse_version_constraint("pkg<2.0.0")

    assert name == "pkg"
    assert constraint == "<2.0.0"
    assert min_version == ""
    assert upper_bound == "2.0.0"


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.httpx.get")
def test_fetch_pypi_data_returns_none_on_non_404_http_error(mock_get: MagicMock) -> None:
    """Returns None on non-404 HTTP errors (e.g. 500 server error)."""
    mock_get.return_value = _mock_httpx_response(status_code=500)

    result = _fetch_pypi_data("some-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies._fetch_pypi_data")
def test_fetch_latest_version_below_skips_unparseable_versions(mock_pypi: MagicMock) -> None:
    """Versions that don't parse to numeric tuples are skipped."""
    mock_pypi.return_value = {
        "releases": {
            "abc": [],  # Unparseable
            "2.0.0": [],
        }
    }

    result = _fetch_latest_version_below("pkg", "9")

    assert result == "2.0.0"


@pytest.mark.os_agnostic
@patch("bmk.makescripts._dependencies.fetch_latest_version")
def test_extract_dependencies_skips_empty_name_after_parsing(mock_latest: MagicMock) -> None:
    """Dependencies that parse to empty name are skipped."""
    mock_latest.return_value = "1.0.0"

    # A whitespace-only dep will have empty name after strip
    results = _extract_dependencies_from_list(["   ", "pkg>=1.0.0"], "test-source")

    assert len(results) == 1
    assert results[0].name == "pkg"


@pytest.mark.os_agnostic
def test_update_dependencies_skips_empty_original_spec(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Dependencies with empty original_spec are skipped during update."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["requests>=1.0.0"]\n')

    deps = [
        _make_dep(name="ghost", status="outdated", original_spec="", latest="2.0.0"),
    ]

    count = update_dependencies(deps, pyproject)

    assert count == 0


@pytest.mark.os_agnostic
def test_update_dependencies_skips_when_spec_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Dependencies where built spec equals original are skipped."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["requests>=2.0.0"]\n')

    deps = [
        _make_dep(
            name="requests",
            status="outdated",
            original_spec="requests>=2.0.0",
            latest="not found",  # _build_updated_spec returns original when latest="not found"
        ),
    ]

    count = update_dependencies(deps, pyproject)

    assert count == 0
