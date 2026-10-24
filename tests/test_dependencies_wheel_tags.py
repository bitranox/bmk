"""Whether a release installs on a Python, judged per file: Requires-Python, then a wheel's own tags.

A release whose files carry no Requires-Python is not therefore installable everywhere: a wheel-only
release installs only where one of its wheels' interpreter tags runs. The records here are shaped as
``https://pypi.org/pypi/<name>/<version>/json`` lists them; the platform is never judged.
"""

from __future__ import annotations

from typing import Any

import pytest

from bmk.adapters.stagerunner.helpers._dependencies import installs_on
from bmk.adapters.stagerunner.helpers._pypi_models import PypiFile


def _record(filename: str, packagetype: str, *, requires_python: str | None = None) -> dict[str, Any]:
    return {
        "filename": filename,
        "packagetype": packagetype,
        # PyPI's own summary of the file; the check does not read it, the filename carries the tags.
        "python_version": "source" if packagetype == "sdist" else "cp313",
        "requires_python": requires_python,
        "yanked": False,
        "upload_time_iso_8601": "2025-03-17T00:55:38.177173Z",
    }


def _wheels(name: str, *tags: str, requires_python: str | None = None) -> tuple[PypiFile, ...]:
    return tuple(
        PypiFile.model_validate(_record(f"{name}-1.0-{tag}.whl", "bdist_wheel", requires_python=requires_python))
        for tag in tags
    )


# pywin32 310 exactly as PyPI lists it: cp38 to cp313 wheels, no sdist, no Requires-Python.
_PYWIN32_310_TAGS = (
    "cp310-cp310-win32",
    "cp310-cp310-win_amd64",
    "cp310-cp310-win_arm64",
    "cp311-cp311-win32",
    "cp311-cp311-win_amd64",
    "cp311-cp311-win_arm64",
    "cp312-cp312-win32",
    "cp312-cp312-win_amd64",
    "cp312-cp312-win_arm64",
    "cp313-cp313-win32",
    "cp313-cp313-win_amd64",
    "cp313-cp313-win_arm64",
    "cp38-cp38-win32",
    "cp38-cp38-win_amd64",
    "cp39-cp39-win32",
    "cp39-cp39-win_amd64",
)
_PYWIN32_310 = tuple(
    PypiFile.model_validate(_record(f"pywin32-310-{tag}.whl", "bdist_wheel")) for tag in _PYWIN32_310_TAGS
)


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("python", "expected"), [("3.14.0", False), ("3.13.0", True), ("3.8.0", True), ("3.7.0", False)]
)
def test_a_wheel_only_release_installs_only_where_one_of_its_wheels_runs(python: str, expected: bool) -> None:
    assert installs_on(_PYWIN32_310, python) is expected


@pytest.mark.os_agnostic
def test_an_sdist_beside_the_wheels_installs_wherever_its_requires_python_admits() -> None:
    sdist = PypiFile.model_validate(_record("pywin32-310.tar.gz", "sdist"))

    assert installs_on((*_PYWIN32_310, sdist), "3.14.0") is True


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("tag", "python", "expected"),
    [
        # A cpXY wheel built for one interpreter ABI serves exactly that minor.
        ("cp313-cp313-manylinux_2_17_x86_64", "3.13.0", True),
        ("cp313-cp313-manylinux_2_17_x86_64", "3.14.0", False),
        ("cp313-none-any", "3.14.0", False),
        ("cp37-cp37m-win_amd64", "3.7.0", True),
        # The stable ABI serves the minor it names and every later 3.x.
        ("cp39-abi3-manylinux_2_17_x86_64", "3.14.0", True),
        ("cp39-abi3-manylinux_2_17_x86_64", "3.8.0", False),
        # Pure wheels: pyX for the whole major, pyXY for that minor and later.
        ("py3-none-any", "3.14.0", True),
        ("py2.py3-none-any", "3.14.0", True),
        ("py2-none-any", "3.14.0", False),
        ("py36-none-any", "3.12.0", True),
        ("py313-none-any", "3.12.0", False),
        # A free-threaded build's wheel is not one the default build installs.
        ("cp313-cp313t-win_amd64", "3.13.0", False),
        # Another implementation's wheel is not one CPython installs.
        ("pp310-pypy310_pp73-manylinux_2_17_x86_64", "3.10.0", False),
    ],
)
def test_a_wheel_installs_where_its_interpreter_tag_runs_whatever_its_platform(
    tag: str, python: str, expected: bool
) -> None:
    assert installs_on(_wheels("demo", tag), python) is expected


@pytest.mark.os_agnostic
def test_a_wheel_still_needs_its_requires_python_to_admit_the_python() -> None:
    assert installs_on(_wheels("demo", "py3-none-any", requires_python="<3.14"), "3.14.0") is False


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "raw",
    [
        # A wheel whose name cannot be parsed is judged by Requires-Python alone, never refused.
        _record("demo.whl", "bdist_wheel"),
        _record("demo-1.x-py3-none-any.whl", "bdist_wheel"),
        # Kinds whose tags the check does not read keep the Requires-Python reading.
        _record("demo-1.0-py2.7.egg", "bdist_egg"),
        _record("demo-1.0.win32.exe", "bdist_wininst"),
        {"filename": "demo-1.0-cp27-cp27m-win32.whl", "requires_python": None},
    ],
)
def test_a_file_whose_tags_cannot_be_read_installs_by_requires_python_alone(raw: dict[str, Any]) -> None:
    assert installs_on((PypiFile.model_validate(raw),), "3.14.0") is True


@pytest.mark.os_agnostic
def test_no_python_to_judge_admits_any_file() -> None:
    assert installs_on(_PYWIN32_310, None) is True
