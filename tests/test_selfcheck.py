"""Tests for the environment integrity check that gates bmk's Makefile upgrade path.

The deployed Makefile upgrades bmk in place rather than rebuilding its environment on
every target, because that environment is shared machine-wide and rebuilding it raced
with bmk runs in other repos. Rebuilding also repaired a damaged environment as a side
effect, so this module is what earns that repair back deliberately: a non-zero exit is
the only signal that makes the Makefile fall through to a full reinstall.

Both directions therefore matter. A miss that goes unreported leaves a broken env in
place with a confusing ImportError deep in bmk's own dependencies; a false alarm rebuilds
a healthy ~300MB environment on every single make.
"""

# The Makefile contract is an exit code, but the useful assertions are on the internals it
# is built from, so this file reaches for _site_packages and _MAX_REPORTED deliberately.
# pyright: reportPrivateUsage=false
from __future__ import annotations

import csv
from pathlib import Path

import pytest

import bmk_selfcheck


def _install_dist(site_packages: Path, name: str, files: dict[str, str]) -> Path:
    """Create a fake installed distribution and the RECORD that lists its files.

    Returns the ``.dist-info`` directory, so a test can damage the RECORD itself.
    """
    dist_info = site_packages / f"{name}-1.0.dist-info"
    dist_info.mkdir(parents=True)

    rows: list[list[str]] = []
    for relative, content in files.items():
        target = site_packages / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        rows.append([relative, "", ""])

    record = dist_info / "RECORD"
    with record.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)
    return dist_info


@pytest.fixture
def site_packages(tmp_path: Path) -> Path:
    """A site-packages directory holding one intact distribution."""
    directory = tmp_path / "site-packages"
    directory.mkdir()
    _install_dist(directory, "pip_api", {"pip_api/__init__.py": "", "pip_api/_hash.py": ""})
    return directory


@pytest.mark.os_agnostic
def test_an_intact_environment_reports_nothing(site_packages: Path) -> None:
    """Every recorded file present means no findings, hence no rebuild."""
    assert bmk_selfcheck.missing_files(site_packages) == []


@pytest.mark.os_agnostic
def test_a_partially_written_package_is_detected(site_packages: Path) -> None:
    """A file listed in RECORD but absent on disk is reported.

    This is the real failure, reproduced: uv's copy fallback across a filesystem it
    cannot hardlink over left `pip_api/_hash.py` unwritten, and every bmk gate then died
    with `ModuleNotFoundError: No module named 'pip_api._hash'` from inside bmk's own
    dependencies rather than from project code. That flavour does NOT clear on a re-run.
    """
    (site_packages / "pip_api" / "_hash.py").unlink()

    assert bmk_selfcheck.missing_files(site_packages) == ["pip_api/_hash.py"]


@pytest.mark.os_agnostic
def test_cleaned_bytecode_is_not_damage(site_packages: Path) -> None:
    """Absent .pyc files are ignored, because removing them is routine and harmless.

    `make clean` and any cache purge delete them, and the interpreter regenerates them on
    demand. Counting them would report a healthy env as broken after every clean, so the
    Makefile would rebuild the whole environment on the next make, forever.
    """
    _install_dist(
        site_packages,
        "cached",
        {"cached/__init__.py": "", "cached/__pycache__/__init__.cpython-312.pyc": ""},
    )
    (site_packages / "cached" / "__pycache__" / "__init__.cpython-312.pyc").unlink()

    assert bmk_selfcheck.missing_files(site_packages) == []


@pytest.mark.os_agnostic
def test_an_unreadable_record_is_skipped_not_reported(site_packages: Path) -> None:
    """A RECORD that cannot be parsed yields no findings.

    The caller rebuilds the environment on any finding, so a metadata quirk must never be
    reported as corruption: that would rebuild a healthy env on every invocation.
    """
    dist_info = _install_dist(site_packages, "odd", {"odd/__init__.py": ""})
    (dist_info / "RECORD").write_bytes(b"\xff\xfe not valid utf-8 \x00")

    assert bmk_selfcheck.missing_files(site_packages) == []


@pytest.mark.os_agnostic
def test_main_exits_zero_when_the_layout_cannot_be_inspected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised interpreter layout reports SUCCESS, never failure.

    Answering "broken" whenever the check cannot tell would make the Makefile rebuild the
    environment on every make, on any layout this module does not recognise.
    """
    monkeypatch.setattr(bmk_selfcheck, "_site_packages", lambda: None)

    assert bmk_selfcheck.main() == 0


@pytest.mark.os_agnostic
def test_main_exit_code_distinguishes_intact_from_damaged(
    site_packages: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The exit code is the whole contract with the Makefile: 0 upgrades, 1 rebuilds."""
    monkeypatch.setattr(bmk_selfcheck, "_site_packages", lambda: site_packages)
    assert bmk_selfcheck.main() == 0

    (site_packages / "pip_api" / "_hash.py").unlink()
    assert bmk_selfcheck.main() == 1
    assert "pip_api/_hash.py" in capsys.readouterr().err, "the reason for the rebuild must be visible"


@pytest.mark.os_agnostic
def test_a_flood_of_missing_files_is_summarised(
    site_packages: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wholly-missing package prints a few names and a count, not thousands of lines.

    The Makefile rebuilds on ANY miss, so the full list adds nothing and would bury the
    install output that follows it.
    """
    monkeypatch.setattr(bmk_selfcheck, "_site_packages", lambda: site_packages)
    names = {f"wide/mod{index}.py": "" for index in range(40)}
    _install_dist(site_packages, "wide", names)
    for relative in names:
        (site_packages / relative).unlink()

    assert bmk_selfcheck.main() == 1
    stderr = capsys.readouterr().err
    assert stderr.count("missing from its environment") == bmk_selfcheck._MAX_REPORTED
    assert f"and {40 - bmk_selfcheck._MAX_REPORTED} more" in stderr
