"""Poetry dependency tables carry their conditions and source into the PEP 508 strings bmk emits.

Every test feeds real ``[tool.poetry]`` TOML text through the public reader
(``load_pyproject_config``, which parses the file exactly as it parses a project's
``pyproject.toml``) and judges the emitted strings with ``packaging``, the same parser an
installer uses: a condition that is dropped makes a requirement unconditional, and a
git/path/url dependency rendered as a bare name is looked up on PyPI as a different package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx2
import pytest
from packaging.markers import Marker
from packaging.requirements import Requirement

from bmk.adapters.stagerunner.helpers import _dependencies
from bmk.adapters.stagerunner.helpers._dependencies import check_dependencies
from bmk.adapters.stagerunner.helpers._toml_config import PoetrySourceKind, PyprojectConfig, load_pyproject_config

if TYPE_CHECKING:
    from pathlib import Path


def _load(tmp_path: Path, toml_text: str) -> PyprojectConfig:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(toml_text, encoding="utf-8")
    return load_pyproject_config(pyproject)


def _main_requirements(tmp_path: Path, toml_text: str) -> list[str]:
    config = _load(tmp_path, toml_text)
    return [dep.to_requirement_string() for dep in config.tool.poetry.dependencies]


def _env(*, python: str, platform: str = "linux") -> dict[str, str]:
    """A marker environment; ``python`` is a full version such as ``3.12.4``."""
    minor = ".".join(python.split(".")[:2])
    return {"python_version": minor, "python_full_version": python, "sys_platform": platform}


def _applies(requirement: str, env: dict[str, str]) -> bool:
    marker = Requirement(requirement).marker
    return True if marker is None else marker.evaluate(env)


# ---------------------------------------------------------------------------
# Conditions: markers, python, platform
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_a_markers_key_survives_into_the_requirement(tmp_path: Path) -> None:
    """A win32-only dependency must not be demanded on Linux."""
    (req,) = _main_requirements(
        tmp_path,
        """
[tool.poetry.dependencies]
python = "^3.10"
pywin32 = { version = "^306", markers = "sys_platform == 'win32'" }
""",
    )

    parsed = Requirement(req)
    assert parsed.name == "pywin32"
    assert str(parsed.specifier) == ">=306"
    assert _applies(req, _env(python="3.12.4", platform="win32")) is True
    assert _applies(req, _env(python="3.12.4", platform="linux")) is False


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("python", "holds_on", "fails_on"),
    [
        ("<3.11", ["3.10.14"], ["3.11.0", "3.12.4"]),
        (">=3.8,<3.11", ["3.8.0", "3.10.14"], ["3.7.9", "3.11.0"]),
        ("^3.8", ["3.8.0", "3.13.1"], ["3.7.9"]),
        ("~3.9", ["3.9.0", "3.12.4"], ["3.8.18"]),
        ("3.9.*", ["3.9.0", "3.9.19"], ["3.10.0", "3.8.18"]),
        ("<3.11.2", ["3.11.1", "3.10.14"], ["3.11.2", "3.11.9"]),
        (">=2.7,<2.8 || >=3.4", ["2.7.18", "3.12.4"], ["3.0.1", "2.6.9"]),
        ("!=3.10.*", ["3.9.0", "3.11.0"], ["3.10.4"]),
    ],
)
def test_a_python_key_becomes_a_python_version_marker(
    tmp_path: Path, python: str, holds_on: list[str], fails_on: list[str]
) -> None:
    """Poetry's per-dependency ``python`` constraint limits which interpreters need the package.

    Caret and tilde follow the module's loose floor-only rule, so ``^3.8`` holds on 3.13 too.
    """
    (req,) = _main_requirements(
        tmp_path,
        f"""
[tool.poetry.dependencies]
tomli = {{ version = "^2", python = "{python}" }}
""",
    )

    assert Requirement(req).name == "tomli"
    for version in holds_on:
        assert _applies(req, _env(python=version)) is True, (req, version)
    for version in fails_on:
        assert _applies(req, _env(python=version)) is False, (req, version)


@pytest.mark.os_agnostic
def test_a_wildcard_python_key_adds_no_condition(tmp_path: Path) -> None:
    (req,) = _main_requirements(
        tmp_path,
        """
[tool.poetry.dependencies]
tomli = { version = "^2", python = "*" }
""",
    )

    assert req == "tomli>=2"


@pytest.mark.os_agnostic
def test_a_platform_key_becomes_a_sys_platform_marker(tmp_path: Path) -> None:
    (req,) = _main_requirements(
        tmp_path,
        """
[tool.poetry.dependencies]
uvloop = { version = "^0.19", platform = "linux" }
""",
    )

    assert req == 'uvloop>=0.19; sys_platform == "linux"'
    assert _applies(req, _env(python="3.12.4", platform="linux")) is True
    assert _applies(req, _env(python="3.12.4", platform="darwin")) is False


@pytest.mark.os_agnostic
def test_all_three_conditions_combine_and_an_or_is_parenthesised(tmp_path: Path) -> None:
    """Without the parentheses ``a or b and c`` would read as ``a or (b and c)``."""
    (req,) = _main_requirements(
        tmp_path,
        """
[tool.poetry.dependencies]
foo = { version = ">=1", markers = "implementation_name == 'cpython' or implementation_name == 'pypy'", python = "<3.11", platform = "linux" }
""",
    )

    assert req == (
        "foo>=1; (implementation_name == 'cpython' or implementation_name == 'pypy')"
        ' and (python_version < "3.11") and (sys_platform == "linux")'
    )
    pypy_on_312 = {**_env(python="3.12.4"), "implementation_name": "pypy"}
    pypy_on_310 = {**_env(python="3.10.14"), "implementation_name": "pypy"}
    assert _applies(req, pypy_on_312) is False
    assert _applies(req, pypy_on_310) is True


# ---------------------------------------------------------------------------
# Multiple-constraint (list) form
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_the_list_form_emits_one_requirement_per_constraint(tmp_path: Path) -> None:
    reqs = _main_requirements(
        tmp_path,
        """
[tool.poetry.dependencies]
foo = [
    { version = "<=1.9", python = ">=3.6,<3.8" },
    { version = "^2.0", python = ">=3.8" },
]
""",
    )

    assert len(reqs) == 2
    on_37 = [r for r in reqs if _applies(r, _env(python="3.7.17"))]
    on_312 = [r for r in reqs if _applies(r, _env(python="3.12.4"))]
    assert [str(Requirement(r).specifier) for r in on_37] == ["<=1.9"]
    assert [str(Requirement(r).specifier) for r in on_312] == [">=2.0"]


# ---------------------------------------------------------------------------
# Source kind: git / url / path are direct references, a named source is not PyPI
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("table", "kind", "url"),
    [
        ('{ git = "https://github.com/org/foo.git" }', PoetrySourceKind.GIT, "git+https://github.com/org/foo.git"),
        (
            '{ git = "https://github.com/org/foo.git", tag = "v1.2", subdirectory = "pkg" }',
            PoetrySourceKind.GIT,
            "git+https://github.com/org/foo.git@v1.2#subdirectory=pkg",
        ),
        (
            '{ git = "git@github.com:org/foo.git", branch = "main" }',
            PoetrySourceKind.GIT,
            "git+git@github.com:org/foo.git@main",
        ),
        ('{ path = "../foo", develop = true }', PoetrySourceKind.PATH, "../foo"),
        (
            '{ url = "https://example.com/foo-1.0-py3-none-any.whl" }',
            PoetrySourceKind.URL,
            "https://example.com/foo-1.0-py3-none-any.whl",
        ),
    ],
)
def test_a_git_path_or_url_dependency_is_a_direct_reference(
    tmp_path: Path, table: str, kind: PoetrySourceKind, url: str
) -> None:
    """A direct reference carries ' @ ', which the dependency stage skips rather than asking PyPI."""
    config = _load(tmp_path, f"[tool.poetry.dependencies]\nfoo = {table}\n")
    (dep,) = config.tool.poetry.dependencies

    req = dep.to_requirement_string()

    assert dep.source_kind is kind
    assert " @ " in req
    assert Requirement(req).name == "foo"
    assert Requirement(req).url == url


@pytest.mark.os_agnostic
def test_a_direct_reference_keeps_its_condition(tmp_path: Path) -> None:
    (req,) = _main_requirements(
        tmp_path,
        """
[tool.poetry.dependencies]
foo = { git = "https://github.com/org/foo.git", python = "<3.11" }
""",
    )

    assert req == 'foo @ git+https://github.com/org/foo.git ; python_version < "3.11"'


@pytest.mark.os_agnostic
def test_a_dependency_from_a_named_private_source_is_not_offered_to_pypi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same name on PyPI may be someone else's package, so the dependency stage never asks PyPI about it."""
    asked: list[str] = []

    def unreachable_pypi(method: str, url: str, **_: object) -> object:
        asked.append(url)
        raise httpx2.ConnectError(f"{method} {url}: offline")

    # PyPI is the one external edge of the dependency check; the test must not touch the network.
    monkeypatch.setattr(_dependencies.httpx2, "stream", unreachable_pypi)
    config = _load(
        tmp_path,
        """
[tool.poetry.dependencies]
internal-lib = { version = "^1.0", source = "corp" }
requests = "^2.31"
""",
    )
    internal, _requests = config.tool.poetry.dependencies

    assert internal.source_kind is PoetrySourceKind.PRIVATE_INDEX
    assert internal.to_requirement_string() == "internal-lib>=1.0"
    checked = [dep.name for dep in check_dependencies(tmp_path / "pyproject.toml")]
    assert "requests" in checked
    assert "internal-lib" not in checked
    assert any("/requests/" in url for url in asked)
    assert not any("internal-lib" in url for url in asked)


@pytest.mark.os_agnostic
def test_an_explicit_pypi_source_stays_a_registry_requirement(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
[tool.poetry.dependencies]
requests = { version = "^2.31", source = "PyPI" }
""",
    )
    (dep,) = config.tool.poetry.dependencies

    assert dep.source_kind is PoetrySourceKind.REGISTRY
    assert dep.to_requirement_string() == "requests>=2.31"


# ---------------------------------------------------------------------------
# Version text and extras
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2.13.0", "requests==2.13.0"),
        ("~=2.13", "requests~=2.13"),
        ("^2.13,<2.20", "requests>=2.13,<2.20"),
        (">= 2.13, < 3", "requests>=2.13,<3"),
        ("2.13.*", "requests==2.13.*"),
    ],
)
def test_version_text_becomes_a_valid_specifier(tmp_path: Path, version: str, expected: str) -> None:
    """A bare Poetry version is an exact pin; '~=' is PEP 440's operator, not Poetry's tilde."""
    (req,) = _main_requirements(tmp_path, f'[tool.poetry.dependencies]\nrequests = "{version}"\n')

    assert req == expected
    assert Requirement(req).name == "requests"


@pytest.mark.os_agnostic
def test_extras_are_carried_into_the_requirement(tmp_path: Path) -> None:
    (req,) = _main_requirements(
        tmp_path,
        """
[tool.poetry.dependencies]
black = { version = "^23.1", extras = ["d", "jupyter"] }
""",
    )

    assert req == "black[d,jupyter]>=23.1"
    assert Requirement(req).extras == {"d", "jupyter"}


# ---------------------------------------------------------------------------
# Dev and group tables take the same path
# ---------------------------------------------------------------------------


@pytest.mark.os_agnostic
def test_dev_and_group_tables_carry_their_conditions(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
[tool.poetry.dev-dependencies]
pywin32 = { version = "^306", markers = "sys_platform == 'win32'" }

[tool.poetry.group.docs.dependencies]
tomli = { version = "^2", python = "<3.11" }
""",
    )

    (dev,) = [d.to_requirement_string() for d in config.tool.poetry.dev_dependencies]
    (docs,) = [d.to_requirement_string() for d in config.tool.poetry.group_dependencies["docs"]]
    assert _applies(dev, _env(python="3.12.4", platform="linux")) is False
    assert _applies(docs, _env(python="3.12.4")) is False


# ---------------------------------------------------------------------------
# Every emitted string is a requirement an installer accepts
# ---------------------------------------------------------------------------

_MIXED_POETRY = """
[tool.poetry.dependencies]
python = "^3.10"
requests = "^2.31"
pinned = "1.2.3"
compat = "~=1.4"
starred = "*"
pywin32 = { version = "^306", markers = "sys_platform == 'win32'" }
tomli = { version = ">=2", python = ">=3.8,<3.11" }
uvloop = { version = "^0.19", platform = "linux", optional = true }
black = { version = "^23.1", extras = ["d"], allow-prereleases = true }
foo = [
    { version = "<=1.9", python = ">=3.6,<3.8" },
    { version = "^2.0", python = ">=3.8 || <3.0" },
]
gitdep = { git = "https://github.com/org/gitdep.git", rev = "abc123", markers = "os_name == 'posix'" }
pathdep = { path = "./libs/pathdep" }
urldep = { url = "https://example.com/urldep-1.0.tar.gz", python = "3.12.*" }
"""


@pytest.mark.os_agnostic
def test_every_emitted_string_parses_as_a_pep508_requirement(tmp_path: Path) -> None:
    reqs = _main_requirements(tmp_path, _MIXED_POETRY)

    assert len(reqs) == 13
    for req in reqs:
        parsed = Requirement(req)
        if parsed.marker is not None:
            Marker(str(parsed.marker)).evaluate(_env(python="3.12.4"))


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    "markers",
    [
        '(sys_platform == "win32")or(sys_platform == "cygwin")',
        'sys_platform == "win32"\tor sys_platform == "cygwin"',
        'sys_platform == "win32" or sys_platform == "cygwin"',
    ],
)
def test_an_or_in_markers_stays_inside_the_and_whatever_its_spacing(tmp_path: Path, markers: str) -> None:
    """``and`` binds tighter than ``or``: an unwrapped ``or`` would admit win32 on any Python."""
    (req,) = _main_requirements(
        tmp_path,
        f"""
[tool.poetry.dependencies]
x = {{ version = ">=1", markers = '{markers}', python = "<3.11" }}
""",
    )

    assert _applies(req, _env(python="3.10.4", platform="win32")) is True
    assert _applies(req, _env(python="3.12.4", platform="win32")) is False
    assert _applies(req, _env(python="3.10.4", platform="linux")) is False


@pytest.mark.os_agnostic
@pytest.mark.parametrize(
    ("platform", "admitted", "refused"),
    [
        ("linux", ["linux"], ["darwin", "win32"]),
        ("linux || darwin", ["linux", "darwin"], ["win32"]),
        ("!=win32", ["linux", "darwin"], ["win32"]),
        ("!=win32,!=cygwin", ["linux"], ["win32", "cygwin"]),
    ],
)
def test_a_platform_constraint_is_read_like_poetry_reads_it(
    tmp_path: Path, platform: str, admitted: list[str], refused: list[str]
) -> None:
    """Poetry's ``platform`` takes alternatives and negations, not only a bare name."""
    (req,) = _main_requirements(
        tmp_path,
        f"""
[tool.poetry.dependencies]
x = {{ version = ">=1", platform = "{platform}" }}
""",
    )

    for name in admitted:
        assert _applies(req, _env(python="3.12.4", platform=name)) is True, (req, name)
    for name in refused:
        assert _applies(req, _env(python="3.12.4", platform=name)) is False, (req, name)


@pytest.mark.os_agnostic
def test_a_platform_value_the_grammar_cannot_read_adds_no_condition(tmp_path: Path) -> None:
    (req,) = _main_requirements(
        tmp_path,
        """
[tool.poetry.dependencies]
x = { version = ">=1", platform = "linux and darwin" }
""",
    )

    assert req == "x>=1"
