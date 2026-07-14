"""Integrity guards for the bundled Makefile template that bmk deploys.

The template is shipped inside the package and copied into target repos by
`bmk install`, so a defect here reaches every bmk-managed repo and cannot be
fixed from those repos. Two invariants are guarded:

1. The header version equals the package version. `_sync_initconf.sync_makefile_version`
   patches it on every bump, so a mismatch means someone edited the template and
   released without running the sync - i.e. the published package would carry a
   template labelled with the wrong version.
2. `_ensure_bmk` cannot silently degrade. It is the target that runs before EVERY
   make invocation, and the ways it used to fail were all invisible.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import rtoml  # not stdlib tomllib: it does not exist on Python 3.10, this project's floor

PROJECT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT_DIR / "src" / "bmk" / "makefile" / "Makefile"


def _template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _ensure_bmk_recipe(text: str) -> str:
    """The recipe lines of the _ensure_bmk target (tab-indented, no comments)."""
    match = re.search(r"^_ensure_bmk:\n((?:\t.*\n)+)", text, re.M)
    assert match, "the template must define an _ensure_bmk target"
    return match.group(1)


# --- header version ---------------------------------------------------------


@pytest.mark.os_agnostic
def test_template_header_matches_package_version() -> None:
    """The template's version sentinel equals [project].version.

    `_sync_initconf.py` keeps these in lockstep. A drift means a release went out
    with the sync unrun, so target repos would compare against a wrong version when
    deciding whether to regenerate their Makefile.
    """
    version = rtoml.load(PROJECT_DIR / "pyproject.toml")["project"]["version"]
    header = _template_text().splitlines()[0]

    assert header == f"# BMK MAKEFILE {version}", (
        f"template header {header!r} does not match pyproject version {version!r}; "
        "run src/bmk/adapters/stagerunner/helpers/_sync_initconf.py"
    )


# --- _ensure_bmk cannot silently degrade ------------------------------------


@pytest.mark.os_agnostic
def test_ensure_bmk_never_suppresses_errors() -> None:
    """No 2>/dev/null.

    Suppressing the error is what turned a transient install failure into an
    invisible one: the run continued on a degraded env and failed much later,
    somewhere unrelated.
    """
    assert "2>/dev/null" not in _ensure_bmk_recipe(_template_text())


@pytest.mark.os_agnostic
def test_ensure_bmk_always_keeps_the_dev_extra() -> None:
    """Every install attempt carries `.[dev]`.

    A project with no [dev] extra does not fail - uv warns and installs the base
    deps - so a fallback that drops it is never needed and only ever produces a
    tool env missing the test deps, which surfaces as a baffling
    ModuleNotFoundError far from the cause.
    """
    recipe = _ensure_bmk_recipe(_template_text())
    installs = re.findall(r"uv tool install[^|]*", recipe)

    assert installs, "the recipe must run `uv tool install`"
    for install in installs:
        assert '".[dev]"' in install, f"install attempt drops the [dev] extra: {install.strip()!r}"


@pytest.mark.os_agnostic
def test_ensure_bmk_always_reinstalls() -> None:
    """Every install attempt carries `--reinstall`.

    `uv tool install` without it NO-OPS when the tool is already present, so a
    fallback lacking it silently keeps a STALE tool env - old pipeline code running
    against new sources while still reporting success.
    """
    recipe = _ensure_bmk_recipe(_template_text())
    installs = re.findall(r"uv tool install[^|]*", recipe)

    for install in installs:
        assert "--reinstall" in install, f"install attempt would no-op on an existing env: {install.strip()!r}"


@pytest.mark.os_agnostic
def test_ensure_bmk_retries_once() -> None:
    """There is a retry, for the transient __pycache__ removal race.

    `--reinstall` removes the old env first, and that removal can lose a race with
    a concurrent process writing a .pyc ("Directory not empty", os error 39). The
    same command succeeds on a second run.
    """
    recipe = _ensure_bmk_recipe(_template_text())

    assert recipe.count("uv tool install") == 2, "expected exactly two identical attempts"
    assert "||" in recipe
