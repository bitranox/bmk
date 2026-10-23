"""Behaviour tests for makescripts._dependencies: version parsing, PyPI queries, and dependency management."""

# pyright: reportPrivateUsage=false, reportUnknownVariableType=false

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import httpx2
import orjson
import pytest
from packaging.specifiers import SpecifierSet

from bmk.adapters.stagerunner.helpers._dependencies import (
    DependencyInfo,
    DependencyStatus,
    PendingInstall,
    _build_updated_spec,
    _extract_all_dependencies,
    _extract_dependencies_from_list,
    _fetch_latest_version_within,
    _fetch_pypi_data,
    _find_packages_needing_install,
    _installed_versions,
    _run_pip_install,
    check_dependencies,
    compare_versions,
    fetch_latest_version,
    main,
    print_report,
    sync_installed_packages,
    update_dependencies,
)
from bmk.adapters.stagerunner.helpers._pypi_models import PypiDocument
from bmk.adapters.stagerunner.helpers._toml_config import PyprojectConfig

if TYPE_CHECKING:
    from pathlib import Path

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
    latest: str | None = "2.0.0",
    notes: tuple[str, ...] = (),
    status: DependencyStatus = DependencyStatus.OUTDATED,
    original_spec: str = "pkg>=1.0.0",
    upper_bound: str = "",
) -> DependencyInfo:
    """Build a DependencyInfo with sensible defaults; ``latest`` None is a package PyPI did not answer for."""
    return DependencyInfo(
        name=name,
        source=source,
        constraint=constraint,
        current_min=current_min,
        latest_version=latest,
        notes=notes,
        status=status,
        original_spec=original_spec,
        upper_bound=upper_bound,
    )


def _mock_httpx_stream(*, status_code: int = 200, content: bytes = b"{}") -> MagicMock:
    """Build a mock ``httpx2.stream`` context manager yielding a controllable response.

    ``_fetch_pypi_data`` streams the body (``with httpx2.stream(...) as response`` then
    ``response.iter_bytes()``), so the mock is the context manager; entering it returns the
    response whose ``iter_bytes`` yields ``content`` in a single chunk.
    """
    resp = MagicMock(spec=httpx2.Response)
    resp.status_code = status_code
    resp.iter_bytes = MagicMock(return_value=[content])
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        http_error = httpx2.HTTPStatusError(
            "error",
            request=MagicMock(spec=httpx2.Request),
            response=resp,
        )
        resp.raise_for_status.side_effect = http_error
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=resp)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# _parse_version_constraint - extras handling and fallback
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_parse_version_constraint_strips_extras() -> None:
    """Extras in brackets are removed before parsing the constraint."""
    from bmk.adapters.stagerunner.helpers._dependencies import _parse_version_constraint

    name, constraint, min_version, upper_bound = _parse_version_constraint("package[extra]>=1.0")

    assert name == "package"
    assert min_version == "1.0"
    assert constraint == ">=1.0"
    assert upper_bound == ""


@pytest.mark.os_agnostic
def test_parse_version_constraint_strips_multiple_extras() -> None:
    """Multiple extras in brackets are removed."""
    from bmk.adapters.stagerunner.helpers._dependencies import _parse_version_constraint

    name, _constraint, min_version, _ = _parse_version_constraint("pkg[foo,bar]>=2.0")

    assert name == "pkg"
    assert min_version == "2.0"


@pytest.mark.os_agnostic
def test_parse_version_constraint_fallback_for_unparseable_spec() -> None:
    """Unparseable spec falls back to returning the spec as name with empty fields."""
    from bmk.adapters.stagerunner.helpers._dependencies import _parse_version_constraint

    name, constraint, min_version, upper_bound = _parse_version_constraint("!!!invalid!!!")

    assert name == "!!!invalid!!!"
    assert constraint == ""
    assert min_version == ""
    assert upper_bound == ""


@pytest.mark.os_agnostic
def test_parse_version_constraint_empty_spec() -> None:
    """Empty spec returns all empty strings."""
    from bmk.adapters.stagerunner.helpers._dependencies import _parse_version_constraint

    assert _parse_version_constraint("") == ("", "", "", "")


@pytest.mark.os_agnostic
def test_parse_version_constraint_with_marker_and_extras() -> None:
    """Markers and extras are both stripped correctly."""
    from bmk.adapters.stagerunner.helpers._dependencies import _parse_version_constraint

    name, _constraint, min_version, _ = _parse_version_constraint("tomli[extra]>=2.0.0; python_version<'3.11'")

    assert name == "tomli"
    assert min_version == "2.0.0"


# ---------------------------------------------------------------------------
# _fetch_pypi_data - HTTP error cases
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.httpx2.stream")
def test_fetch_pypi_data_returns_none_on_404(mock_stream: MagicMock) -> None:
    """Returns None when PyPI responds with 404."""
    mock_stream.return_value = _mock_httpx_stream(status_code=404)

    result = _fetch_pypi_data("nonexistent-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.httpx2.stream")
def test_fetch_pypi_data_returns_none_on_connection_error(mock_stream: MagicMock) -> None:
    """Returns None when httpx2 raises a ConnectError."""
    mock_stream.side_effect = httpx2.ConnectError("connection refused")

    result = _fetch_pypi_data("some-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.httpx2.stream")
def test_fetch_pypi_data_returns_none_on_timeout(mock_stream: MagicMock) -> None:
    """Returns None when httpx2 raises a TimeoutException."""
    mock_stream.side_effect = httpx2.TimeoutException("read timeout")

    result = _fetch_pypi_data("some-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.httpx2.stream")
def test_fetch_pypi_data_returns_none_on_json_decode_error(mock_stream: MagicMock) -> None:
    """Returns None when response body is not valid JSON."""
    resp = _mock_httpx_stream(status_code=200, content=b"not json{{{")
    mock_stream.return_value = resp

    result = _fetch_pypi_data("some-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.httpx2.stream")
def test_fetch_pypi_data_returns_none_when_the_json_is_not_a_document(mock_stream: MagicMock) -> None:
    """JSON that is not an object is no PyPI document: the package reads as unavailable."""
    mock_stream.return_value = _mock_httpx_stream(status_code=200, content=b'["not", "a", "document"]')

    assert _fetch_pypi_data("some-pkg") is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.httpx2.stream")
def test_fetch_pypi_data_returns_parsed_json_on_success(mock_stream: MagicMock) -> None:
    """Returns the validated document on a successful response."""
    payload = {"info": {"version": "3.0.0"}}
    resp = _mock_httpx_stream(status_code=200, content=orjson.dumps(payload))
    mock_stream.return_value = resp

    result = _fetch_pypi_data("some-pkg")

    assert result == PypiDocument.model_validate(payload)
    assert result is not None
    assert result.info is not None
    assert result.info.version == "3.0.0"


# ---------------------------------------------------------------------------
# fetch_latest_version - success path, None path, non-dict info
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_returns_version_string(mock_pypi: MagicMock) -> None:
    """Returns the version string from PyPI info on success."""
    mock_pypi.return_value = PypiDocument.model_validate({"info": {"version": "4.1.2"}})

    result = fetch_latest_version("requests")

    assert result == "4.1.2"


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_returns_none_when_pypi_fails(mock_pypi: MagicMock) -> None:
    """Returns None when PyPI data is unavailable."""
    mock_pypi.return_value = None

    result = fetch_latest_version("nonexistent-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_returns_empty_when_info_not_dict(mock_pypi: MagicMock) -> None:
    """Returns empty string when info field is not a dict."""
    mock_pypi.return_value = PypiDocument.model_validate({"info": "not-a-dict"})

    result = fetch_latest_version("some-pkg")

    assert result == ""


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_returns_empty_when_version_missing(mock_pypi: MagicMock) -> None:
    """Returns empty string when version key is absent from info."""
    mock_pypi.return_value = PypiDocument.model_validate({"info": {"name": "pkg"}})

    result = fetch_latest_version("some-pkg")

    assert result == ""


# ---------------------------------------------------------------------------
# _fetch_latest_version_within - filtering, prerelease skip, sorting, empty
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_within_returns_highest_within_bound(mock_pypi: MagicMock) -> None:
    """Returns the highest version below the upper bound."""
    mock_pypi.return_value = PypiDocument.model_validate(
        {
            "releases": {
                "7.0.0": [],
                "8.0.0": [],
                "8.5.0": [],
                "9.0.0": [],
                "10.0.0": [],
            }
        }
    )

    result = _fetch_latest_version_within("pytest", SpecifierSet("<9"))

    assert result == "8.5.0"


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_within_skips_prereleases(mock_pypi: MagicMock) -> None:
    """Prerelease versions (alpha, beta, rc, dev) are excluded."""
    mock_pypi.return_value = PypiDocument.model_validate(
        {
            "releases": {
                "8.0.0": [],
                "8.1.0a1": [],
                "8.2.0b2": [],
                "8.3.0rc1": [],
                "8.4.0dev1": [],
                "9.0.0": [],
            }
        }
    )

    result = _fetch_latest_version_within("pytest", SpecifierSet("<9"))

    assert result == "8.0.0"


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_within_returns_none_when_pypi_fails(mock_pypi: MagicMock) -> None:
    """Returns None when PyPI data is unavailable."""
    mock_pypi.return_value = None

    result = _fetch_latest_version_within("pytest", SpecifierSet("<9"))

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_within_returns_none_when_no_releases(mock_pypi: MagicMock) -> None:
    """Returns None when releases dict is empty."""
    mock_pypi.return_value = PypiDocument.model_validate({"releases": {}})

    result = _fetch_latest_version_within("pytest", SpecifierSet("<9"))

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_within_returns_none_when_all_above_bound(mock_pypi: MagicMock) -> None:
    """Returns None when all versions are at or above the upper bound."""
    mock_pypi.return_value = PypiDocument.model_validate(
        {
            "releases": {
                "9.0.0": [],
                "10.0.0": [],
            }
        }
    )

    result = _fetch_latest_version_within("pytest", SpecifierSet("<9"))

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_within_returns_none_when_releases_not_dict(mock_pypi: MagicMock) -> None:
    """Returns None when releases field is not a dict."""
    mock_pypi.return_value = PypiDocument.model_validate({"releases": "not-a-dict"})

    result = _fetch_latest_version_within("pytest", SpecifierSet("<9"))

    assert result is None


# ---------------------------------------------------------------------------
# _extract_dependencies_from_list - empty dep skip, pinned within range
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version")
def test_extract_dependencies_skips_empty_strings(mock_latest: MagicMock) -> None:
    """Empty strings in the dependency list are silently skipped."""
    mock_latest.return_value = "1.0.0"

    results = _extract_dependencies_from_list(["", "pkg>=1.0.0", ""], "test-source")

    assert len(results) == 1
    assert results[0].name == "pkg"


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version")
def test_extract_dependencies_skips_direct_url_references(mock_latest: MagicMock) -> None:
    """PEP 440 direct URL references (pkg @ git+https://...) are skipped - not on PyPI."""
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
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within")
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version")
def test_extract_dependencies_detects_pinned_within_range(mock_latest: MagicMock, mock_below: MagicMock) -> None:
    """When min_version equals latest-in-range, status is pinned."""
    mock_latest.return_value = "10.0.0"  # Exceeds upper bound
    mock_below.return_value = "8.4.2"  # Latest within range, same as current_min

    results = _extract_dependencies_from_list(["pytest>=8.4.2,<9"], "test-source")

    assert len(results) == 1
    assert results[0].status == DependencyStatus.PINNED
    assert "pinned <9" in results[0].latest_display


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within")
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version")
def test_extract_dependencies_detects_outdated_within_range(mock_latest: MagicMock, mock_below: MagicMock) -> None:
    """When a newer version exists within the allowed range, status is outdated."""
    mock_latest.return_value = "10.0.0"
    mock_below.return_value = "8.5.0"

    results = _extract_dependencies_from_list(["pytest>=8.4.2,<9"], "test-source")

    assert len(results) == 1
    assert results[0].status == DependencyStatus.OUTDATED
    assert "8.5.0" in results[0].latest_display


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within")
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version")
def test_extract_dependencies_pinned_when_below_returns_none(mock_latest: MagicMock, mock_below: MagicMock) -> None:
    """When no version within range is found, status is pinned."""
    mock_latest.return_value = "10.0.0"
    mock_below.return_value = None

    results = _extract_dependencies_from_list(["pytest>=8.4.2,<9"], "test-source")

    assert len(results) == 1
    assert results[0].status == DependencyStatus.PINNED


# ---------------------------------------------------------------------------
# _extract_all_dependencies - optional deps, build system, poetry, pdm, uv
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within", return_value=None)
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
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within", return_value=None)
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
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within", return_value=None)
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
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within", return_value=None)
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
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within", return_value=None)
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
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within", return_value=None)
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
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within", return_value=None)
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
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within", return_value=None)
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
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within", return_value=None)
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
# check_dependencies - basic invocation
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version", return_value="2.0.0")
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_latest_version_within", return_value=None)
def test_check_dependencies_reads_pyproject(mock_below: MagicMock, mock_latest: MagicMock, tmp_path: Path) -> None:
    """check_dependencies reads a pyproject.toml and returns DependencyInfo list."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\ndependencies = ["requests>=1.0.0"]\n')

    results = check_dependencies(pyproject)

    assert isinstance(results, list)
    assert any(d.name == "requests" for d in results)


# ---------------------------------------------------------------------------
# print_report - error count increment
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_print_report_counts_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """Error status dependencies are counted in the summary."""
    deps = [
        _make_dep(name="broken-pkg", status=DependencyStatus.ERROR, latest=None),
    ]

    exit_code = print_report(deps, verbose=True)

    captured = capsys.readouterr()
    assert "Errors:     1" in captured.out
    assert exit_code == 0  # Only outdated triggers non-zero


@pytest.mark.os_agnostic
def test_print_report_rows_show_the_release_its_notes_and_the_status_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A row reads the same on every Python: the status by its value, never ``DependencyStatus.X``.

    f-string interpolation of a ``str, Enum`` member gives its value on 3.10 and its qualified name
    on 3.11+, so the row must name the value explicitly.
    """
    deps = [
        _make_dep(name="capped", latest="1.2", notes=("max <2", "exact pin ==1.0"), status=DependencyStatus.PINNED),
        _make_dep(name="gone", latest=None, status=DependencyStatus.ERROR),
    ]

    print_report(deps, verbose=True)

    out = capsys.readouterr().out
    assert "  [==] capped  >=1.0.0  -> 1.2 (max <2) (exact pin ==1.0)  [pinned]\n" in out
    assert "  [XX] gone    >=1.0.0  -> not found                       [error]\n" in out


@pytest.mark.os_agnostic
def test_print_report_returns_one_when_outdated(capsys: pytest.CaptureFixture[str]) -> None:
    """Returns exit code 1 when any dependency is outdated."""
    deps = [
        _make_dep(name="old-pkg", status=DependencyStatus.OUTDATED),
    ]

    exit_code = print_report(deps, verbose=True)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Outdated:   1" in captured.out


@pytest.mark.os_agnostic
def test_print_report_returns_zero_when_all_up_to_date(capsys: pytest.CaptureFixture[str]) -> None:
    """Returns exit code 0 when all dependencies are up-to-date."""
    deps = [
        _make_dep(name="good-pkg", status=DependencyStatus.UP_TO_DATE, latest="1.0.0"),
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
# _build_updated_spec - markers, extras, no constraint, extras re-add
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
    """Returns the original spec unchanged when PyPI did not answer (no latest version)."""
    dep = _make_dep(
        original_spec="unknown-pkg>=1.0.0",
        latest=None,
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
    """A report note like 'max <1.3, absolute: 1.3.0' must not leak into the spec."""
    dep = _make_dep(
        original_spec="pytest-asyncio>=1.1.0",
        latest="1.2.0",
        notes=("max <1.3, absolute: 1.3.0",),
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
        latest="1.2.0",
        notes=("max <1.3, absolute: 1.3.0",),
        upper_bound="1.3",
    )

    result = _build_updated_spec(dep)

    assert result == "pytest-asyncio>=1.2.0,<1.3; python_version<'3.10'"


# ---------------------------------------------------------------------------
# _installed_versions - reads the TARGET environment, not this process
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_installed_versions_queries_the_given_interpreter(mock_run: MagicMock) -> None:
    """Asks uv about the passed interpreter, not the running one."""
    mock_run.return_value = _make_completed(0, stdout='[{"name":"click","version":"8.2.1"}]')

    result = _installed_versions("/proj/.venv/bin/python")

    assert result == {"click": "8.2.1"}
    cmd = mock_run.call_args[0][0]
    assert cmd[:3] == ["uv", "pip", "list"]
    assert cmd[cmd.index("--python") + 1] == "/proj/.venv/bin/python"
    assert sys.executable not in cmd


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_installed_versions_normalizes_names(mock_run: MagicMock) -> None:
    """Keys are PEP 503 normalized so lookups match pyproject spellings."""
    mock_run.return_value = _make_completed(0, stdout='[{"name":"Lib_Shopware6.Api","version":"6.0.3"}]')

    assert _installed_versions("/p/bin/python") == {"lib-shopware6-api": "6.0.3"}


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [(1, ""), (0, "not json"), (0, "[{}]")],
    ids=["uv-failed", "bad-json", "missing-keys"],
)
@patch("subprocess.run")
def test_installed_versions_degrades_to_empty(mock_run: MagicMock, returncode: int, stdout: str) -> None:
    """An unreadable environment yields an empty map rather than raising."""
    mock_run.return_value = _make_completed(returncode, stdout=stdout)

    assert _installed_versions("/p/bin/python") == {}


@pytest.mark.os_agnostic
@patch("subprocess.run", side_effect=OSError("uv not found"))
def test_installed_versions_handles_missing_uv(_mock_run: MagicMock) -> None:
    """Returns an empty map rather than raising when uv is absent."""
    assert _installed_versions("/p/bin/python") == {}


# ---------------------------------------------------------------------------
# _find_packages_needing_install - installed None, outdated
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_find_packages_needing_install_not_installed() -> None:
    """Packages not installed are included in the results."""
    deps = [_make_dep(name="missing-pkg", current_min="1.0.0")]

    results = _find_packages_needing_install(deps, {})

    assert len(results) == 1
    assert results[0] == PendingInstall("missing-pkg", None, "1.0.0", "")


@pytest.mark.os_agnostic
def test_find_packages_needing_install_outdated() -> None:
    """Packages with an installed version below the required minimum are included."""
    deps = [_make_dep(name="old-pkg", current_min="1.0.0")]

    results = _find_packages_needing_install(deps, {"old-pkg": "0.9.0"})

    assert len(results) == 1
    assert results[0] == PendingInstall("old-pkg", "0.9.0", "1.0.0", "")


@pytest.mark.os_agnostic
def test_find_packages_needing_install_up_to_date() -> None:
    """Up-to-date packages are not included."""
    deps = [_make_dep(name="good-pkg", current_min="1.0.0")]

    results = _find_packages_needing_install(deps, {"good-pkg": "2.0.0"})

    assert len(results) == 0


@pytest.mark.os_agnostic
def test_find_packages_needing_install_skips_no_min_version() -> None:
    """Dependencies without a current_min are skipped."""
    deps = [_make_dep(name="bare-pkg", current_min="")]

    results = _find_packages_needing_install(deps, {})

    assert len(results) == 0


@pytest.mark.os_agnostic
def test_find_packages_needing_install_preserves_extras() -> None:
    """Extras survive into the install spec.

    Extras change what gets installed (pyright[nodejs] pulls a bundled Node), so
    rebuilding the spec from the extras-stripped name installs the wrong thing.
    """
    deps = [_make_dep(name="pyright", current_min="1.1.411", original_spec="pyright[nodejs]>=1.1.400")]

    results = _find_packages_needing_install(deps, {"pyright": "1.1.400"})

    assert results[0].spec_name == "pyright[nodejs]"


@pytest.mark.os_agnostic
def test_find_packages_needing_install_preserves_environment_marker() -> None:
    """An environment marker survives into the install spec.

    Without it a platform-specific dependency is demanded on EVERY platform, and
    the install cannot succeed: a win32-only package is never installed on Linux,
    so it always looks missing, and `uv pip install pywin32>=312` then dies with
    "no wheels with a matching platform tag" - taking the whole `make test` down
    in any cross-platform project. Real case: pwshpy on Linux.
    """
    deps = [
        _make_dep(
            name="pywin32",
            current_min="312",
            original_spec="pywin32>=312; sys_platform == 'win32'",
        )
    ]

    results = _find_packages_needing_install(deps, {})

    assert results[0] == PendingInstall("pywin32", None, "312", "; sys_platform == 'win32'")


@pytest.mark.os_agnostic
def test_find_packages_needing_install_keeps_extras_and_marker_together() -> None:
    """A spec carrying both an extra and a marker keeps both, each in its own field."""
    deps = [
        _make_dep(
            name="lib_registry",
            current_min="3.1.3",
            original_spec="lib_registry[fake]>=3.1.3; sys_platform == 'win32'",
        )
    ]

    results = _find_packages_needing_install(deps, {})

    assert results[0].spec_name == "lib_registry[fake]"
    assert results[0].marker == "; sys_platform == 'win32'"


# ---------------------------------------------------------------------------
# _run_pip_install - install target isolation
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_run_pip_install_builds_uv_command(mock_run: MagicMock) -> None:
    """Builds a uv pip install command with --upgrade and package specs."""
    mock_run.return_value = _make_completed(0)

    needs = [PendingInstall("requests", None, "2.31.0", ""), PendingInstall("click", "8.0.0", "8.1.0", "")]

    exit_code = _run_pip_install(needs, "/proj/.venv/bin/python")

    assert exit_code == 0
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[:3] == ["uv", "pip", "install"]
    assert "--upgrade" in cmd
    assert "requests>=2.31.0" in cmd
    assert "click>=8.1.0" in cmd


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_run_pip_install_appends_marker_after_the_version(mock_run: MagicMock) -> None:
    """The marker follows the version, producing a valid PEP 508 requirement.

    Order is not cosmetic: "pywin32>=312; sys_platform == 'win32'" is valid and lets
    uv skip the package off-platform, while "pywin32; sys_platform == 'win32'>=312"
    is not a requirement at all. Verified against real uv: the marked form exits 0 on
    Linux, the bare form fails to resolve.
    """
    mock_run.return_value = _make_completed(0)

    needs = [PendingInstall("pywin32", None, "312", "; sys_platform == 'win32'")]

    _run_pip_install(needs, "/proj/.venv/bin/python")

    cmd = mock_run.call_args[0][0]
    assert "pywin32>=312; sys_platform == 'win32'" in cmd


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_run_pip_install_targets_the_given_interpreter(mock_run: MagicMock) -> None:
    """Installs into the interpreter it is handed, via --python."""
    mock_run.return_value = _make_completed(0)

    _run_pip_install([PendingInstall("requests", None, "1.0.0", "")], "/proj/.venv/bin/python")

    cmd = mock_run.call_args[0][0]
    assert "--python" in cmd
    assert cmd[cmd.index("--python") + 1] == "/proj/.venv/bin/python"


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_run_pip_install_never_targets_the_ambient_interpreter(mock_run: MagicMock) -> None:
    """Never installs into sys.executable.

    Regression guard for the defect this replaced: the helper runs in-process, so
    sys.executable is whatever launched bmk (a shared editor venv, or a system
    Python). Installing there let any project inflate an environment it did not
    own. No input may put sys.executable in the argv.
    """
    mock_run.return_value = _make_completed(0)

    _run_pip_install([PendingInstall("requests", None, "1.0.0", "")], "/proj/.venv/bin/python")

    cmd = mock_run.call_args[0][0]
    assert sys.executable not in cmd
    assert "-m" not in cmd, "must not shell out to `<python> -m pip`"


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_run_pip_install_never_breaks_system_packages(mock_run: MagicMock) -> None:
    """Never passes --break-system-packages.

    With an explicit venv target there is no externally-managed environment to
    override, and the flag exists only to force-write a system interpreter.
    """
    mock_run.return_value = _make_completed(0)

    _run_pip_install([PendingInstall("requests", None, "1.0.0", "")], "/proj/.venv/bin/python")

    assert "--break-system-packages" not in mock_run.call_args[0][0]


@pytest.mark.os_agnostic
@patch("subprocess.run")
def test_run_pip_install_reports_failure(mock_run: MagicMock) -> None:
    """Propagates a non-zero install exit code."""
    mock_run.return_value = _make_completed(1)

    assert _run_pip_install([PendingInstall("requests", None, "1.0.0", "")], "/proj/.venv/bin/python") == 1


@pytest.mark.os_agnostic
@patch("subprocess.run", side_effect=OSError("uv not found"))
def test_run_pip_install_handles_missing_uv(_mock_run: MagicMock) -> None:
    """Returns non-zero rather than raising when uv is absent from PATH."""
    assert _run_pip_install([PendingInstall("requests", None, "1.0.0", "")], "/proj/.venv/bin/python") == 1


# ---------------------------------------------------------------------------
# sync_installed_packages - dry run, actual run, no updates
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._installed_versions", return_value={})
@patch("bmk.adapters.stagerunner.helpers._dependencies._run_pip_install")
@patch("bmk.adapters.stagerunner.helpers._dependencies._find_packages_needing_install")
def test_sync_installed_packages_dry_run(
    mock_find: MagicMock, mock_pip: MagicMock, _mock_versions: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dry run shows what would be installed but does not install."""
    mock_find.return_value = [PendingInstall("requests", None, "2.31.0", "")]

    count, code = sync_installed_packages([], python="/p/bin/python", dry_run=True)

    assert (count, code) == (1, 0)
    mock_pip.assert_not_called()
    captured = capsys.readouterr()
    assert "[DRY RUN]" in captured.out


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._installed_versions", return_value={})
@patch("bmk.adapters.stagerunner.helpers._dependencies._run_pip_install", return_value=0)
@patch("bmk.adapters.stagerunner.helpers._dependencies._find_packages_needing_install")
def test_sync_installed_packages_actual_run(
    mock_find: MagicMock, mock_pip: MagicMock, _mock_versions: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Actual run installs and reports success."""
    mock_find.return_value = [PendingInstall("requests", "1.0.0", "2.31.0", "")]

    count, code = sync_installed_packages([], python="/p/bin/python")

    assert (count, code) == (1, 0)
    mock_pip.assert_called_once()
    captured = capsys.readouterr()
    assert "Successfully installed/updated" in captured.out


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._installed_versions", return_value={})
@patch("bmk.adapters.stagerunner.helpers._dependencies._run_pip_install", return_value=0)
@patch("bmk.adapters.stagerunner.helpers._dependencies._find_packages_needing_install")
def test_sync_installed_packages_targets_the_given_interpreter(
    mock_find: MagicMock, mock_pip: MagicMock, mock_versions: MagicMock
) -> None:
    """Both the inspection and the install use the interpreter passed in."""
    mock_find.return_value = [PendingInstall("requests", None, "2.31.0", "")]

    sync_installed_packages([], python="/proj/.venv/bin/python")

    mock_versions.assert_called_once_with("/proj/.venv/bin/python")
    assert mock_pip.call_args[0][1] == "/proj/.venv/bin/python"


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._installed_versions", return_value={})
@patch("bmk.adapters.stagerunner.helpers._dependencies._run_pip_install", return_value=1)
@patch("bmk.adapters.stagerunner.helpers._dependencies._find_packages_needing_install")
def test_sync_installed_packages_reports_install_failure(
    mock_find: MagicMock, mock_pip: MagicMock, _mock_versions: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Returns and reports a non-zero install exit code."""
    mock_find.return_value = [PendingInstall("requests", None, "2.31.0", "")]

    _count, code = sync_installed_packages([], python="/p/bin/python")

    assert code == 1
    captured = capsys.readouterr()
    assert "install failed" in captured.err


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._installed_versions", return_value={})
@patch("bmk.adapters.stagerunner.helpers._dependencies._find_packages_needing_install")
def test_sync_installed_packages_no_updates_needed(
    mock_find: MagicMock, _mock_versions: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Returns 0 when all installed packages match requirements."""
    mock_find.return_value = []

    assert sync_installed_packages([], python="/p/bin/python") == (0, 0)
    captured = capsys.readouterr()
    assert "All installed packages match" in captured.out


# ---------------------------------------------------------------------------
# update_dependencies - round-trip fidelity
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_update_dependencies_preserves_comments_and_formatting(tmp_path: Path) -> None:
    """An update leaves comments, spacing and unrelated entries byte-identical.

    A pin is often accompanied by a comment explaining why it exists; losing that
    on an automated bump destroys the reason and invites the pin's removal.
    """
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "demo"\n'
        "dependencies = [\n"
        '    "rich-click>=1.9.8",\n'
        "    # codecov-cli is disabled, not dropped: it requires click<8.3.0,\n"
        "    # which drags click back to a version with a known CVE.\n"
        '    # "codecov-cli>=11.3.1",\n'
        '    "requests>=1.0.0",  # trailing note\n'
        "]\n"
    )
    deps = [
        _make_dep(
            name="requests",
            status=DependencyStatus.OUTDATED,
            current_min="1.0.0",
            latest="2.0.0",
            original_spec="requests>=1.0.0",
        )
    ]

    update_dependencies(deps, pyproject, quiet=True)

    content = pyproject.read_text()
    assert "requests>=2.0.0" in content
    assert "# codecov-cli is disabled, not dropped" in content
    assert '# "codecov-cli>=11.3.1",' in content
    assert "# trailing note" in content
    assert '"rich-click>=1.9.8"' in content


@pytest.mark.os_agnostic
def test_update_dependencies_ignores_matching_text_in_comments(tmp_path: Path) -> None:
    """A spec that appears only inside a comment is not treated as a dependency.

    Structural editing distinguishes a live array entry from the same characters
    in a comment; text substitution cannot.
    """
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\ndependencies = [\n    # "ghost>=1.0.0",\n]\n')
    deps = [
        _make_dep(
            name="ghost",
            status=DependencyStatus.OUTDATED,
            current_min="1.0.0",
            latest="2.0.0",
            original_spec="ghost>=1.0.0",
        )
    ]

    updated = update_dependencies(deps, pyproject, quiet=True)

    assert updated == 0
    assert '# "ghost>=1.0.0",' in pyproject.read_text()


# ---------------------------------------------------------------------------
# update_dependencies - dry run, actual update, not found in file
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_update_dependencies_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Dry run shows what would change without modifying the file."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = [\n    "requests>=1.0.0",\n]\n')

    deps = [
        _make_dep(
            name="requests",
            status=DependencyStatus.OUTDATED,
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
            status=DependencyStatus.OUTDATED,
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
            status=DependencyStatus.OUTDATED,
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
        _make_dep(name="requests", status=DependencyStatus.UP_TO_DATE),
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
            status=DependencyStatus.OUTDATED,
            original_spec="click>=7.0.0",
            latest="8.1.0",
        ),
    ]

    count = update_dependencies(deps, pyproject)

    assert count == 1
    content = pyproject.read_text()
    assert "click>=8.1.0" in content


# ---------------------------------------------------------------------------
# main - with update flag, without
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.sync_installed_packages", return_value=(0, 0))
@patch("bmk.adapters.stagerunner.helpers._dependencies.update_dependencies", return_value=0)
@patch("bmk.adapters.stagerunner.helpers._dependencies.print_report", return_value=0)
@patch("bmk.adapters.stagerunner.helpers._dependencies.check_dependencies")
def test_main_without_update(
    mock_check: MagicMock,
    mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --update, reports but does not update."""
    mock_check.return_value = [_make_dep(status=DependencyStatus.UP_TO_DATE)]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    exit_code = main(pyproject=pyproject)

    assert exit_code == 0
    mock_update.assert_not_called()
    mock_sync.assert_not_called()


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.sync_installed_packages", return_value=(0, 0))
@patch("bmk.adapters.stagerunner.helpers._dependencies.update_dependencies", return_value=1)
@patch("bmk.adapters.stagerunner.helpers._dependencies.print_report", return_value=1)
@patch("bmk.adapters.stagerunner.helpers._dependencies.check_dependencies")
def test_main_with_update(
    mock_check: MagicMock,
    mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With --update, calls update_dependencies and sync_installed_packages."""
    mock_check.return_value = [_make_dep(status=DependencyStatus.OUTDATED)]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    exit_code = main(update=True, pyproject=pyproject, python="/p/bin/python")

    assert exit_code == 0
    mock_update.assert_called_once()
    mock_sync.assert_called_once()
    assert mock_sync.call_args.kwargs["python"] == "/p/bin/python"


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.sync_installed_packages", return_value=(0, 0))
@patch("bmk.adapters.stagerunner.helpers._dependencies.update_dependencies", return_value=1)
@patch("bmk.adapters.stagerunner.helpers._dependencies.print_report", return_value=1)
@patch("bmk.adapters.stagerunner.helpers._dependencies.check_dependencies")
def test_main_with_update_skips_sync_without_a_target(
    mock_check: MagicMock,
    _mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
) -> None:
    """Without a resolved interpreter, updates pyproject but installs nothing.

    Installing has no safe fallback: defaulting to the ambient interpreter is how
    a project ended up inflating a shared environment it did not own.
    """
    mock_check.return_value = [_make_dep(status=DependencyStatus.OUTDATED)]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    exit_code = main(update=True, pyproject=pyproject, python=None)

    assert exit_code == 0
    mock_update.assert_called_once()
    mock_sync.assert_not_called()


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.sync_installed_packages", return_value=(1, 1))
@patch("bmk.adapters.stagerunner.helpers._dependencies.update_dependencies", return_value=1)
@patch("bmk.adapters.stagerunner.helpers._dependencies.print_report", return_value=1)
@patch("bmk.adapters.stagerunner.helpers._dependencies.check_dependencies")
def test_main_with_update_propagates_install_failure(
    mock_check: MagicMock,
    _mock_report: MagicMock,
    _mock_update: MagicMock,
    _mock_sync: MagicMock,
    tmp_path: Path,
) -> None:
    """A failed install is reported, not swallowed as success."""
    mock_check.return_value = [_make_dep(status=DependencyStatus.OUTDATED)]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    assert main(update=True, pyproject=pyproject, python="/p/bin/python") == 1


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.sync_installed_packages", return_value=(0, 0))
@patch("bmk.adapters.stagerunner.helpers._dependencies.update_dependencies", return_value=2)
@patch("bmk.adapters.stagerunner.helpers._dependencies.print_report", return_value=1)
@patch("bmk.adapters.stagerunner.helpers._dependencies.check_dependencies")
def test_main_with_update_re_checks_after_changes(
    mock_check: MagicMock,
    mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """After updating pyproject.toml, re-checks dependencies."""
    mock_check.return_value = [_make_dep(status=DependencyStatus.OUTDATED)]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    main(update=True, pyproject=pyproject, python="/p/bin/python")

    # check_dependencies called twice: initial and re-check
    assert mock_check.call_count == 2


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.sync_installed_packages", return_value=(0, 0))
@patch("bmk.adapters.stagerunner.helpers._dependencies.update_dependencies", return_value=2)
@patch("bmk.adapters.stagerunner.helpers._dependencies.print_report", return_value=1)
@patch("bmk.adapters.stagerunner.helpers._dependencies.check_dependencies")
def test_main_with_update_dry_run_does_not_recheck(
    mock_check: MagicMock,
    mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dry run with update does not re-check dependencies after update."""
    mock_check.return_value = [_make_dep(status=DependencyStatus.OUTDATED)]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    main(update=True, dry_run=True, pyproject=pyproject, python="/p/bin/python")

    # check_dependencies called only once (no re-check in dry run)
    assert mock_check.call_count == 1


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.sync_installed_packages", return_value=(0, 0))
@patch("bmk.adapters.stagerunner.helpers._dependencies.update_dependencies", return_value=0)
@patch("bmk.adapters.stagerunner.helpers._dependencies.print_report", return_value=1)
@patch("bmk.adapters.stagerunner.helpers._dependencies.check_dependencies")
def test_main_returns_report_exit_code_without_update(
    mock_check: MagicMock,
    mock_report: MagicMock,
    mock_update: MagicMock,
    mock_sync: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --update, returns the exit code from print_report."""
    mock_check.return_value = [_make_dep(status=DependencyStatus.OUTDATED)]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nversion = "1.0.0"\n')

    exit_code = main(pyproject=pyproject)

    assert exit_code == 1


# ---------------------------------------------------------------------------
# compare_versions - basic checks
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
# Remaining branch coverage - edge cases
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_parse_version_constraint_unclosed_bracket() -> None:
    """Unclosed bracket in extras is left as-is (bracket found, no close bracket)."""
    from bmk.adapters.stagerunner.helpers._dependencies import _parse_version_constraint

    name, _constraint, _min_version, _ = _parse_version_constraint("pkg[extra>=1.0")

    # The bracket is not stripped because close_bracket == -1
    # The regex still parses what it can
    assert name is not None


@pytest.mark.os_agnostic
def test_parse_version_constraint_only_upper_bound() -> None:
    """Constraint with only upper bound (no >=) leaves min_version empty."""
    from bmk.adapters.stagerunner.helpers._dependencies import _parse_version_constraint

    name, constraint, min_version, upper_bound = _parse_version_constraint("pkg<2.0.0")

    assert name == "pkg"
    assert constraint == "<2.0.0"
    assert min_version == ""
    assert upper_bound == "2.0.0"


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.httpx2.stream")
def test_fetch_pypi_data_returns_none_on_non_404_http_error(mock_stream: MagicMock) -> None:
    """Returns None on non-404 HTTP errors (e.g. 500 server error)."""
    mock_stream.return_value = _mock_httpx_stream(status_code=500)

    result = _fetch_pypi_data("some-pkg")

    assert result is None


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies._fetch_pypi_data")
def test_fetch_latest_version_within_skips_unparseable_versions(mock_pypi: MagicMock) -> None:
    """Versions that don't parse to numeric tuples are skipped."""
    mock_pypi.return_value = PypiDocument.model_validate(
        {
            "releases": {
                "abc": [],  # Unparseable
                "2.0.0": [],
            }
        }
    )

    result = _fetch_latest_version_within("pkg", SpecifierSet("<9"))

    assert result == "2.0.0"


@pytest.mark.os_agnostic
@patch("bmk.adapters.stagerunner.helpers._dependencies.fetch_latest_version")
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
        _make_dep(name="ghost", status=DependencyStatus.OUTDATED, original_spec="", latest="2.0.0"),
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
            status=DependencyStatus.OUTDATED,
            original_spec="requests>=2.0.0",
            latest=None,  # _build_updated_spec returns the original when there is no latest version
        ),
    ]

    count = update_dependencies(deps, pyproject)

    assert count == 0


# ---------------------------------------------------------------------------
# _build_updated_spec and update_dependencies - exact output, every branch
# ---------------------------------------------------------------------------
# These pin whole strings rather than substrings: the two functions are split into helpers,
# and a substring check would let a reordered extras/marker splice or a changed message pass.


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("original_spec", "latest", "expected"),
    [
        ("pkg>=1.0", "2.0", "pkg>=2.0"),
        ("pkg[x]>=1.0", "2.0", "pkg[x]>=2.0"),
        ("pkg[x,y]>=1.0,<3; python_version<'3.11'", "2.0", "pkg[x,y]>=2.0,<3; python_version<'3.11'"),
        ("pkg>1.0", "2.0", "pkg>=2.0"),
        ("pkg==8.0.*", "8.1.post1", "pkg==8.1.*"),
        ("pkg!=1.5,>=1.0", "2.0", "pkg!=1.5,>=2.0"),
        ("pkg; sys_platform == 'win32'", "2.0", "pkg>=2.0; sys_platform == 'win32'"),
        ("pkg[x]; sys_platform == 'win32'", "2.0", "pkg[x]>=2.0; sys_platform == 'win32'"),
        ("pkg==*", "2.0", "pkg==*"),
        ("", "2.0", ""),
        # An unclosed bracket carries no extras, so the bare-name branch drops it.
        ("pkg[x", "2.0", "pkg>=2.0"),
        ("pkg[x>=1.0", "2.0", "pkg[x>=2.0"),
        # No package name at the start: the floor is appended to the spec as written.
        ("*weird", "2.0", "*weird>=2.0"),
        ("[x]", "2.0", "[x]>=2.0"),
        # A constraint INSIDE the brackets is rewritten by the substitution, which is the only
        # way the extras re-add branch runs; the result is garbage that update_dependencies
        # refuses to write, but the exact text is what its stderr line shows.
        ("pkg[a>=1]>=0.5", "2.0", "pkg[a>=1][a>=2.0]>=2.0"),
        ("pkg[a>=1]", "2.0", "pkg[a>=1][a>=2.0]"),
        ("[a>=1]>=0.5", "2.0", "[a>=2.0]>=2.0"),
    ],
)
def test_build_updated_spec_exact_output(original_spec: str, latest: str, expected: str) -> None:
    """Every branch of the rewrite produces exactly the spec it produced before the split."""
    dep = _make_dep(original_spec=original_spec, latest=latest)

    assert _build_updated_spec(dep) == expected


_MIXED_PYPROJECT = '[project]\ndependencies = [\n    "alpha>=1.0",  # keep\n    "pkg[a>=1]>=0.5",\n]\n'
_REFUSED_LINE = "  pkg: pkg[a>=1]>=0.5 -> pkg[a>=1][a>=2.0]>=2.0 is not a valid requirement, not written\n"


def _mixed_deps() -> list[DependencyInfo]:
    """One dependency per outcome: written, not located, refused, empty, unchanged, current."""
    return [
        _make_dep(name="alpha", original_spec="alpha>=1.0", latest="2.0"),
        _make_dep(name="ghost", original_spec="ghost>=1.0", latest="2.0"),
        _make_dep(name="pkg", original_spec="pkg[a>=1]>=0.5", latest="2.0"),
        _make_dep(name="empty", original_spec="", latest="2.0"),
        _make_dep(name="same", original_spec="same>=1.0", latest=None),
        _make_dep(name="fresh", original_spec="fresh>=1.0", latest="1.0", status=DependencyStatus.UP_TO_DATE),
    ]


@pytest.mark.os_agnostic
def test_update_dependencies_mixed_run_exact_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A real update prints each outcome on its stream and writes only the valid spec."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_MIXED_PYPROJECT, encoding="utf-8")

    count = update_dependencies(_mixed_deps(), pyproject)

    captured = capsys.readouterr()
    assert count == 1
    assert captured.out == (
        "\nUpdating 5 dependencies:\n\n"
        "  alpha: alpha>=1.0 -> alpha>=2.0\n"
        "  ghost: Could not locate in file (manual update needed)\n"
        f"\nUpdated 1 dependencies in {pyproject}\n"
    )
    assert captured.err == _REFUSED_LINE
    assert pyproject.read_text(encoding="utf-8") == _MIXED_PYPROJECT.replace("alpha>=1.0", "alpha>=2.0")


@pytest.mark.os_agnostic
def test_update_dependencies_mixed_dry_run_exact_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A dry run prints the same outcomes under a DRY RUN banner and leaves the file alone."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_MIXED_PYPROJECT, encoding="utf-8")

    count = update_dependencies(_mixed_deps(), pyproject, dry_run=True)

    captured = capsys.readouterr()
    assert count == 1
    assert captured.out == (
        "\n[DRY RUN] Updating 5 dependencies:\n\n"
        "  alpha: alpha>=1.0 -> alpha>=2.0\n"
        "  ghost: Could not locate in file (manual update needed)\n"
        "\n[DRY RUN] Would update 1 dependencies\n"
    )
    assert captured.err == _REFUSED_LINE
    assert pyproject.read_text(encoding="utf-8") == _MIXED_PYPROJECT


@pytest.mark.os_agnostic
@pytest.mark.parametrize("dry_run", [False, True])
def test_update_dependencies_quiet_prints_only_the_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *, dry_run: bool
) -> None:
    """Quiet silences stdout in both modes; the refused spec still reaches stderr."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_MIXED_PYPROJECT, encoding="utf-8")

    count = update_dependencies(_mixed_deps(), pyproject, dry_run=dry_run, quiet=True)

    captured = capsys.readouterr()
    assert count == 1
    assert captured.out == ""
    assert captured.err == _REFUSED_LINE
    expected = _MIXED_PYPROJECT if dry_run else _MIXED_PYPROJECT.replace("alpha>=1.0", "alpha>=2.0")
    assert pyproject.read_text(encoding="utf-8") == expected


@pytest.mark.os_agnostic
def test_update_dependencies_dry_run_quiet_without_refusals_is_silent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A quiet dry run with a writable update prints nothing and changes nothing."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["alpha>=1.0"]\n', encoding="utf-8")

    count = update_dependencies(
        [_make_dep(name="alpha", original_spec="alpha>=1.0", latest="2.0")], pyproject, dry_run=True, quiet=True
    )

    captured = capsys.readouterr()
    assert count == 1
    assert (captured.out, captured.err) == ("", "")
    assert pyproject.read_text(encoding="utf-8") == '[project]\ndependencies = ["alpha>=1.0"]\n'


@pytest.mark.os_agnostic
def test_update_dependencies_nothing_written_exact_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """When no outdated spec could be written the run says so and leaves the file alone."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_MIXED_PYPROJECT, encoding="utf-8")

    count = update_dependencies([_make_dep(name="ghost", original_spec="ghost>=1.0", latest="2.0")], pyproject)

    captured = capsys.readouterr()
    assert count == 0
    assert captured.out == (
        "\nUpdating 1 dependencies:\n\n"
        "  ghost: Could not locate in file (manual update needed)\n"
        "\nNo dependencies were updated\n"
    )
    assert captured.err == ""
    assert pyproject.read_text(encoding="utf-8") == _MIXED_PYPROJECT
