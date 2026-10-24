"""The PyPI boundary: what a malformed field or entry reads as, and what refuses a whole document.

The check degrades field by field, so one bad file record never hides every release of a package;
these pin each degrade so the typed models keep the reading the dependency check relies on.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pydantic
import pytest

from bmk.adapters.stagerunner.helpers._pypi_models import PackageType, PypiDocument, PypiFile, parse_moment


@pytest.mark.os_agnostic
def test_a_release_keeps_its_version_when_its_files_are_not_a_list() -> None:
    document = PypiDocument.model_validate({"releases": {"1.0": "broken", "2.0": [{}, "junk", 7]}})

    assert document.releases == {"1.0": (), "2.0": (PypiFile(),)}


@pytest.mark.os_agnostic
def test_info_and_releases_that_are_not_objects_read_as_absent() -> None:
    document = PypiDocument.model_validate({"info": "not-a-dict", "releases": ["1.0"]})

    assert document.info is None
    assert document.releases is None


@pytest.mark.os_agnostic
def test_a_document_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(pydantic.ValidationError):
        PypiDocument.model_validate(["not", "a", "document"])


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"yanked": True}, PypiFile(yanked=True)),
        ({"yanked": "withdrawn"}, PypiFile(yanked=True)),
        ({"yanked": None, "requires_python": ""}, PypiFile()),
        ({"requires_python": 3}, PypiFile(requires_python="3")),
        ({"upload_time_iso_8601": 12}, PypiFile()),
        ({"upload_time_iso_8601": "2026-10-12T00:15:37"}, PypiFile()),
        ({"filename": 7, "packagetype": None}, PypiFile()),
        ({"packagetype": "bdist_egg"}, PypiFile()),
        ({"packagetype": 3}, PypiFile()),
        ({"packagetype": "bdist_wheel"}, PypiFile(packagetype=PackageType.BDIST_WHEEL)),
        (
            {"packagetype": "sdist", "filename": "demo-1.0.tar.gz"},
            PypiFile(packagetype=PackageType.SDIST, filename="demo-1.0.tar.gz"),
        ),
    ],
)
def test_a_file_record_reads_each_field_leniently(raw: dict[str, object], expected: PypiFile) -> None:
    assert PypiFile.model_validate(raw) == expected


@pytest.mark.os_agnostic
def test_an_upload_time_with_more_than_six_fraction_digits_is_read() -> None:
    record = PypiFile.model_validate({"upload_time_iso_8601": "2026-10-12T00:15:37.7212281Z"})

    assert record.uploaded == datetime(2026, 10, 12, 0, 15, 37, 721228, tzinfo=timezone.utc)
    assert record.uploaded == parse_moment("2026-10-12T00:15:37.721228Z")


@pytest.mark.os_agnostic
def test_info_reads_a_missing_version_as_empty_and_null_requirements_as_none() -> None:
    document = PypiDocument.model_validate({"info": {"version": None, "requires_dist": None}})

    assert document.info is not None
    assert document.info.version == ""
    assert document.info.requires_dist == ()
