"""Tests for the _sync_initconf helper (version sync into __init__conf__.py + Makefile)."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from bmk.adapters.stagerunner.helpers import _sync_initconf
from bmk.adapters.stagerunner.helpers._sync_initconf import (
    derive_package_name,
    main,
    sync_initconf_version,
    sync_makefile_version,
    sync_plugin_version,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_project(tmp_path: Path, *, version: str = "2.0.0", pkg: str = "my_pkg") -> Path:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{pkg}"\nversion = "{version}"\n\n'
        f'[tool.hatch.build.targets.wheel]\npackages = ["src/{pkg}"]\n',
        encoding="utf-8",
    )
    return tmp_path


# --- derive_package_name ----------------------------------------------------


@pytest.mark.os_agnostic
def test_derive_package_name_from_hatch_wheel(tmp_path: Path) -> None:
    _write_project(tmp_path, pkg="acme_tool")
    assert derive_package_name(tmp_path) == "acme_tool"


@pytest.mark.os_agnostic
def test_derive_package_name_from_scripts_entrypoint(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n\n[project.scripts]\nfoo = "acme.cli:main"\n', encoding="utf-8"
    )
    assert derive_package_name(tmp_path) == "acme"


@pytest.mark.os_agnostic
def test_derive_package_name_fallback_to_project_name(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-tool"\n', encoding="utf-8")
    assert derive_package_name(tmp_path) == "my_tool"


@pytest.mark.os_agnostic
def test_derive_package_name_raises_when_undeterminable(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="derive package name"):
        derive_package_name(tmp_path)


# --- sync_initconf_version --------------------------------------------------


@pytest.mark.os_agnostic
def test_sync_initconf_version_updates_and_reports_change(tmp_path: Path) -> None:
    _write_project(tmp_path, version="2.0.0")
    initconf = tmp_path / "src" / "my_pkg" / "__init__conf__.py"
    initconf.parent.mkdir(parents=True)
    initconf.write_text('name = "my_pkg"\nversion = "1.0.0"\n', encoding="utf-8")

    assert sync_initconf_version(tmp_path) is True
    assert 'version = "2.0.0"' in initconf.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_sync_initconf_version_noop_when_already_in_sync(tmp_path: Path) -> None:
    _write_project(tmp_path, version="2.0.0")
    initconf = tmp_path / "src" / "my_pkg" / "__init__conf__.py"
    initconf.parent.mkdir(parents=True)
    initconf.write_text('version = "2.0.0"\n', encoding="utf-8")

    assert sync_initconf_version(tmp_path) is False


@pytest.mark.os_agnostic
def test_sync_initconf_version_false_when_file_missing(tmp_path: Path) -> None:
    _write_project(tmp_path, version="2.0.0")
    assert sync_initconf_version(tmp_path) is False


@pytest.mark.os_agnostic
def test_sync_initconf_version_warns_and_false_when_no_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No [project].version key at all -> ProjectSection.version defaults to "", which
    # is the same falsy value the guard checks for a present-but-empty `version = ""`.
    # The guard fires before package-name derivation, so no package layout is needed.
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my_pkg"\n', encoding="utf-8")

    assert sync_initconf_version(tmp_path) is False
    assert "Warning: no [project].version in pyproject.toml" in capsys.readouterr().err


# --- sync_makefile_version --------------------------------------------------


@pytest.mark.os_agnostic
def test_sync_makefile_version_updates_sentinel(tmp_path: Path) -> None:
    _write_project(tmp_path, version="2.0.0")
    makefile = tmp_path / "src" / "my_pkg" / "makefile" / "Makefile"
    makefile.parent.mkdir(parents=True)
    makefile.write_text("# BMK MAKEFILE 1.0.0\nall:\n\techo hi\n", encoding="utf-8")

    assert sync_makefile_version(tmp_path) is True
    assert makefile.read_text(encoding="utf-8").startswith("# BMK MAKEFILE 2.0.0")


@pytest.mark.os_agnostic
def test_sync_makefile_version_updates_bmk_min_sentinel(tmp_path: Path) -> None:
    # test_sync_makefile_version_updates_sentinel's fixture has no BMK_MIN line, so the
    # _MAKEFILE_MIN_RE substitution never actually runs there. This fixture carries one,
    # so the BMK_MIN update itself is exercised.
    _write_project(tmp_path, version="2.0.0")
    makefile = tmp_path / "src" / "my_pkg" / "makefile" / "Makefile"
    makefile.parent.mkdir(parents=True)
    makefile.write_text("# BMK MAKEFILE 1.0.0\nBMK_MIN := 1.0.0\nall:\n\techo hi\n", encoding="utf-8")

    assert sync_makefile_version(tmp_path) is True
    assert "BMK_MIN := 2.0.0" in makefile.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_sync_makefile_version_warns_and_false_when_no_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my_pkg"\n', encoding="utf-8")

    assert sync_makefile_version(tmp_path) is False
    assert "Warning: no [project].version in pyproject.toml" in capsys.readouterr().err


@pytest.mark.os_agnostic
def test_sync_makefile_version_false_when_missing(tmp_path: Path) -> None:
    _write_project(tmp_path, version="2.0.0")
    assert sync_makefile_version(tmp_path) is False


# --- main -------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_main_syncs_both_and_returns_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_project(tmp_path, version="3.1.0")
    initconf = tmp_path / "src" / "my_pkg" / "__init__conf__.py"
    initconf.parent.mkdir(parents=True)
    initconf.write_text('version = "0.0.0"\n', encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["_sync_initconf.py", "--project-dir", str(tmp_path)])
    assert main() == 0
    assert 'version = "3.1.0"' in initconf.read_text(encoding="utf-8")


@pytest.mark.os_agnostic
def test_main_returns_one_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # pyproject with no name/scripts/packages -> derive_package_name raises ValueError.
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n', encoding="utf-8")
    (tmp_path / "src").mkdir()
    monkeypatch.setattr(sys, "argv", ["_sync_initconf.py", "--project-dir", str(tmp_path)])
    assert main() == 1


def test_module_importable() -> None:
    assert _sync_initconf.__name__.endswith("_sync_initconf")


# ---------------------------------------------------------------------------
# The shipped-skill plugin version: slaved to the package, never lowered
# ---------------------------------------------------------------------------


def _write_plugin(project: Path, version: str) -> Path:
    manifest = project / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": "thing", "version": version}) + "\n", encoding="utf-8")
    return manifest


@pytest.mark.os_agnostic
def test_plugin_version_follows_the_package_version_upward(tmp_path: Path) -> None:
    project = _write_project(tmp_path, version="2.0.0")
    manifest = _write_plugin(project, "1.0.3")

    assert sync_plugin_version(project) is True
    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == "2.0.0"


@pytest.mark.os_agnostic
def test_a_plugin_version_ahead_of_the_package_is_never_lowered(tmp_path: Path) -> None:
    # A skill legitimately ships more often than the package it documents, so the
    # plugin version can be ahead. Writing the package version there would move an
    # install BACKWARD to a version it already had.
    project = _write_project(tmp_path, version="1.1.0")
    manifest = _write_plugin(project, "1.2.0")

    assert sync_plugin_version(project) is False
    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == "1.2.0"


@pytest.mark.os_agnostic
def test_equal_versions_are_left_alone(tmp_path: Path) -> None:
    project = _write_project(tmp_path, version="1.2.0")
    manifest = _write_plugin(project, "1.2.0")

    assert sync_plugin_version(project) is False
    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == "1.2.0"


@pytest.mark.os_agnostic
def test_a_repo_without_a_plugin_manifest_is_untouched(tmp_path: Path) -> None:
    assert sync_plugin_version(_write_project(tmp_path)) is False


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("package", "plugin"),
    [("1.2.0rc1", "1.0.0"), ("1.2.0", "2026.07.30-1"), ("1.2.0", ""), ("3.0.0", "1!0.9.0")],
)
def test_the_manifest_is_left_alone_when_the_sync_cannot_honestly_raise_it(
    tmp_path: Path, package: str, plugin: str
) -> None:
    # Four distinct reasons, all ending in "do not write":
    #   1.2.0rc1 -> the PACKAGE is non-final, and a Claude Code plugin version is read by
    #               the marketplace machinery, which is only ever seen carrying a plain
    #               X.Y.Z. bmk will not be the first to write a pre-release there.
    #   2026.07.30-1 -> parses as 2026.7.30.post1, which is ABOVE 1.2.0; never lower a
    #               manifest, an install would move backward.
    #   ""       -> not a version at all; nothing to order against.
    #   1!0.9.0  -> an EPOCH outranks the release segment, so this sits above 3.0.0
    #               however small it looks. Comparing the digits would lower it.
    project = _write_project(tmp_path, version=package)
    manifest = _write_plugin(project, plugin)

    assert sync_plugin_version(project) is False
    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == plugin


@pytest.mark.os_agnostic
@pytest.mark.parametrize("plugin", ["1.0", "1.0.0rc1", "2.9.0.post3", "3.0.0.dev1"])
def test_a_manifest_version_bmk_could_not_previously_read_is_still_raised(tmp_path: Path, plugin: str) -> None:
    # The old three-part regex dropped these on the floor and skipped the sync, leaving a
    # skill edit to ship unannounced. PEP 440 orders every one of them below 3.0.0.
    project = _write_project(tmp_path, version="3.0.0")
    manifest = _write_plugin(project, plugin)

    assert sync_plugin_version(project) is True
    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == "3.0.0"


@pytest.mark.os_agnostic
def test_the_manifest_keeps_its_other_fields_and_stays_valid_json(tmp_path: Path) -> None:
    project = _write_project(tmp_path, version="3.0.0")
    manifest = project / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"name": "thing", "version": "1.0.0", "author": {"name": "bitranox"}}, indent=2) + "\n",
        encoding="utf-8",
    )

    assert sync_plugin_version(project) is True
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert (data["version"], data["author"]["name"]) == ("3.0.0", "bitranox")
