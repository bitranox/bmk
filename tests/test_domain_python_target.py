"""A Python build to test on: a minor plus its variant, read from and written as uv's request."""

from __future__ import annotations

import pytest

from bmk.domain.enums import PythonVariant
from bmk.domain.python_target import PythonTarget

# "3.15" in Arabic-Indic digits: str.isdigit() accepts them, int() reads them as 3 and 15.
_ARABIC_INDIC_3_15 = chr(0x663) + "." + chr(0x661) + chr(0x665)


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("request_text", "minor", "variant"),
    [
        ("3.15", "3.15", PythonVariant.DEFAULT),
        ("3.15t", "3.15", PythonVariant.FREETHREADED),
        ("3.9", "3.9", PythonVariant.DEFAULT),
        ("10.0t", "10.0", PythonVariant.FREETHREADED),
    ],
)
def test_a_request_names_its_minor_and_variant(request_text: str, minor: str, variant: PythonVariant) -> None:
    target = PythonTarget.from_request(request_text)

    assert target is not None
    assert target == PythonTarget(minor, variant)
    assert target.request == request_text


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "request_text",
    ["3", "3.15.0", "3.15tt", "3.15T", " 3.15", "3.15\n", "3.x", "pypy@3.15", "", _ARABIC_INDIC_3_15],
    ids=[
        "no-minor",
        "patch",
        "double-t",
        "capital-t",
        "leading-space",
        "trailing-newline",
        "letter",
        "implementation",
        "empty",
        "arabic-indic-digits",
    ],
)
def test_anything_but_x_y_or_x_y_t_is_no_target(request_text: str) -> None:
    """uv reads other spellings too, but a target is only what a classifier and its ``t`` can name."""
    assert PythonTarget.from_request(request_text) is None


@pytest.mark.os_agnostic
def test_the_default_variant_is_the_plain_minor() -> None:
    assert PythonTarget("3.14").request == "3.14"
