"""Tests for pyproject-derived data used to build tool argv (package name, pip-audit ignores)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bmk.adapters.stagerunner.project import derive_package_name, pip_audit_ignore_flags

if TYPE_CHECKING:
    from pathlib import Path


def test_derive_package_name_from_hatch_wheel_packages(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.hatch.build.targets.wheel]\npackages = ["src/my_pkg"]\n', encoding="utf-8"
    )
    assert derive_package_name(tmp_path / "pyproject.toml") == "my_pkg"


def test_derive_package_name_from_scripts_entrypoint(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project.scripts]\nfoo = "acme.cli:main"\n', encoding="utf-8")
    assert derive_package_name(tmp_path / "pyproject.toml") == "acme"


def test_derive_package_name_fallback_to_project_name(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-tool"\n', encoding="utf-8")
    assert derive_package_name(tmp_path / "pyproject.toml") == "my_tool"


def test_derive_package_name_none_when_missing(tmp_path: Path) -> None:
    assert derive_package_name(tmp_path / "pyproject.toml") is None


def test_pip_audit_ignore_flags(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pip-audit]\nignore-vulns = ["GHSA-aaa", "PYSEC-bbb"]\n', encoding="utf-8"
    )
    assert pip_audit_ignore_flags(tmp_path / "pyproject.toml") == [
        "--ignore-vuln=GHSA-aaa",
        "--ignore-vuln=PYSEC-bbb",
    ]


def test_pip_audit_ignore_flags_empty_when_absent(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert pip_audit_ignore_flags(tmp_path / "pyproject.toml") == []


def test_pip_audit_ignore_flags_skips_non_string_ids_and_a_non_array(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.pip-audit]\nignore-vulns = ["GHSA-aaa", 7, "PYSEC-bbb"]\n', encoding="utf-8")
    assert pip_audit_ignore_flags(pyproject) == ["--ignore-vuln=GHSA-aaa", "--ignore-vuln=PYSEC-bbb"]

    pyproject.write_text('[tool.pip-audit]\nignore-vulns = "GHSA-aaa"\n', encoding="utf-8")
    assert pip_audit_ignore_flags(pyproject) == []


def test_a_misshapen_table_degrades_instead_of_raising(tmp_path: Path) -> None:
    # A wrong-shaped table reads as "not configured", like every other pyproject reader.
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "a-b"\nscripts = ["x:y"]\n[tool.hatch]\nbuild = 1\n', encoding="utf-8")
    assert derive_package_name(pyproject) == "a_b"

    pyproject.write_text("tool = 3\n", encoding="utf-8")
    assert (derive_package_name(pyproject), pip_audit_ignore_flags(pyproject)) == (None, [])


def test_derive_package_name_ignores_a_non_string_name(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 5\n", encoding="utf-8")
    assert derive_package_name(tmp_path / "pyproject.toml") is None
