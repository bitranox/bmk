"""Integrity guards for the bundled Makefile template that bmk deploys.

The template is shipped inside the package and copied into target repos by
`bmk install`, so a defect here reaches every bmk-managed repo and cannot be fixed
from those repos. Five invariants are guarded:

1. The header version equals the package version. `_sync_initconf.sync_makefile_version`
   patches it on every bump, so a mismatch means the template was edited and released
   without running the sync, and the published package carries a template labelled
   with the wrong version.
2. The install cannot silently degrade. It runs before every make invocation, and each
   way it can go wrong - dropping the `[dev]` extra, no-opping on a stale env,
   swallowing the error - produces a working-looking env that fails much later,
   somewhere unrelated.
3. The env belongs to this project alone (`.venv-bmk` inside the repo), so two repos
   cannot overwrite each other's dependencies.
4. The install runs before every target, so a new bmk release and any dependency
   change are picked up without anyone remembering to do anything.
5. A commit message stays DATA. make expands $(ARGS) into the recipe and hands the
   result to bash, so an unquoted message is parsed as code: `fix(cli): x` is a
   syntax error, `a; b` runs `b`, and a newline commits a truncated subject and then
   runs the rest as a command. That last one is silent until after the bad message is
   pushed, and it has happened more than once.
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


def _install_recipe(text: str) -> str:
    """The tab-indented recipe lines of the _ensure_bmk target."""
    match = re.search(r"^_ensure_bmk:\n((?:\t.*\n)+)", text, re.M)
    assert match, "the template must define an _ensure_bmk recipe"
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
    """No 2>/dev/null in the install recipe.

    Suppressing the error is what turned a transient install failure into an
    invisible one: the run continued on a degraded env and failed much later,
    somewhere unrelated.
    """
    assert "2>/dev/null" not in _install_recipe(_template_text())


@pytest.mark.os_agnostic
def test_ensure_bmk_always_keeps_the_dev_extra() -> None:
    """Every install attempt carries `.[dev]`.

    A project with no [dev] extra does not fail - uv warns and installs the base
    deps - so a fallback that drops it is never needed and only ever produces a
    tool env missing the test deps, which surfaces as a baffling
    ModuleNotFoundError far from the cause.
    """
    recipe = _install_recipe(_template_text())
    installs = re.findall(r"uv tool install[^|]*", recipe)

    assert installs, "the recipe must run `uv tool install`"
    for install in installs:
        assert '".[dev]"' in install, f"install attempt drops the [dev] extra: {install.strip()!r}"


@pytest.mark.os_agnostic
def test_project_is_installed_editable() -> None:
    """The project goes in editable, so its code in the env IS the working tree.

    This is what makes gating the stamp on pyproject.toml alone correct: only the
    project's DEPENDENCIES can go stale, and they change only when pyproject.toml
    does. A non-editable `--with .` installs a snapshot; it happens to work because
    tools run with cwd=<project>, whose source shadows the snapshot on sys.path, but
    that is an accident of import order and would serve stale code to anything
    running from another directory.
    """
    recipe = _install_recipe(_template_text())

    for attempt in re.findall(r"uv tool install[^|]*", recipe):
        assert "--with-editable" in attempt, f"project must be installed editable: {attempt.strip()!r}"


@pytest.mark.os_agnostic
def test_ensure_bmk_always_reinstalls() -> None:
    """Every install attempt carries `--reinstall`.

    `uv tool install` without it NO-OPS when the tool is already present, so a
    fallback lacking it silently keeps a STALE tool env - old pipeline code running
    against new sources while still reporting success.
    """
    recipe = _install_recipe(_template_text())
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
    recipe = _install_recipe(_template_text())

    assert recipe.count("uv tool install") == 2, "expected exactly two identical attempts"
    assert "||" in recipe


# --- the env is this project's alone ----------------------------------------


@pytest.mark.os_agnostic
def test_tool_env_is_per_project() -> None:
    """Both the env AND the entry points are redirected into the project.

    The tool env carries the project's own dependencies, so a
    machine-wide env cannot serve two projects: whichever ran make last wins and
    the other silently gets the wrong dependency tree - measured, not theoretical.
    Redirecting UV_TOOL_DIR alone is not enough: uv still writes the entry points
    to the shared bin dir and fails with "Executables already exist".
    """
    recipe = _install_recipe(_template_text())

    for attempt in re.findall(r"uv tool install[^|]*", recipe):
        assert "--force" in attempt, "rebuilding over existing entry points needs --force"
    assert 'UV_TOOL_DIR="$(BMK_TOOL_DIR)"' in recipe
    assert 'UV_TOOL_BIN_DIR="$(BMK_TOOL_DIR)/bin"' in recipe


@pytest.mark.os_agnostic
def test_tool_dir_is_inside_the_project() -> None:
    """BMK_TOOL_DIR resolves under the project, and bmk is run from it.

    Invoking a bare `bmk` from PATH would reach whatever machine-wide install
    happens to exist, defeating the isolation.
    """
    text = _template_text()

    assert re.search(r"^BMK_TOOL_DIR := \$\(CURDIR\)/\.venv-bmk$", text, re.M)
    assert re.search(r"^BMK := \$\(BMK_TOOL_DIR\)/bin/bmk\$\(BMK_EXE\)$", text, re.M)
    assert "$(HOME)/.local/bin/bmk" not in text, "must not fall back to the machine-wide bmk"


@pytest.mark.os_agnostic
def test_install_runs_before_every_target() -> None:
    """_ensure_bmk is .PHONY and carries the install, so it runs every time.

    That is what keeps bmk and the dependency tree current: `uv tool install
    --reinstall bmk` re-resolves the unpinned spec against PyPI on each make, before
    bmk starts. Gating it behind a stamp file would make make skip the install, and
    uv would then never see a new release - the env would silently pin itself.
    """
    text = _template_text()

    assert re.search(r"^\.PHONY: _ensure_bmk\n_ensure_bmk:\n\t", text, re.M), (
        "_ensure_bmk must be .PHONY and own the recipe, so it is never skipped"
    )
    assert "BMK_STAMP" not in text, "a stamp would stop uv from ever seeing a new bmk release"


@pytest.mark.os_agnostic
def test_bmk_is_installed_with_a_version_floor() -> None:
    """Every install attempt pins `bmk>=$(BMK_MIN)`, never a bare `bmk`.

    bmk and the project's dependencies resolve TOGETHER, so a project dependency
    that caps something bmk requires does not fail - uv backtracks BMK to an older
    release that fits, silently. Real case: codecov-cli caps click<8.3.0 while bmk
    requires click>=8.4.2, so an unpinned `bmk` resolves to 3.1.7 and that repo
    never sees another bmk update, with no error at all. The floor turns that into
    an unsatisfiable-requirements error naming the offending package.
    """
    recipe = _install_recipe(_template_text())
    installs = re.findall(r"uv tool install[^|]*", recipe)

    assert installs
    for attempt in installs:
        assert '"bmk>=$(BMK_MIN)"' in attempt, f"install attempt has no version floor: {attempt.strip()!r}"


@pytest.mark.os_agnostic
def test_bmk_min_matches_the_package_version() -> None:
    """BMK_MIN equals [project].version, so the floor cannot lag the release.

    `_sync_initconf.py` patches it on every bump. A floor left behind would let uv
    backtrack bmk past this release again - the very thing it exists to prevent.
    """
    version = rtoml.load(PROJECT_DIR / "pyproject.toml")["project"]["version"]
    match = re.search(r"^BMK_MIN := (\S+)$", _template_text(), re.M)

    assert match, "the template must define BMK_MIN"
    assert match.group(1) == version, (
        f"BMK_MIN {match.group(1)!r} does not match pyproject version {version!r}; "
        "run src/bmk/adapters/stagerunner/helpers/_sync_initconf.py"
    )


# --- a commit message is data, never code -----------------------------------


def _recipe_lines(text: str, target: str) -> list[str]:
    """The tab-indented recipe lines of a target.

    The target name must be followed directly by the colon: a looser pattern makes
    the alias `c` match the `codecov coverage cov:` rule instead.
    """
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t.*\n)+)", text, re.M)
    assert match, f"the template must define a {target} recipe"
    return [line.strip() for line in match.group(1).splitlines()]


@pytest.mark.os_agnostic
@pytest.mark.parametrize("target", ["commit", "c", "push", "psh p"])
def test_message_targets_quote_args(target: str) -> None:
    """commit/push pass "$(ARGS)" quoted, so bash cannot parse the message as code.

    make expands $(ARGS) into the recipe and hands the RESULT to bash, which then
    applies its full grammar to prose that was never escaped for it. Unquoted, a
    real commit message breaks or executes: `fix(cli): x` is a syntax error, `a; b`
    runs `b`, a backtick or $(...) EXECUTES, and `*` globs. Quoting costs nothing
    here because both CLIs take only a message (nargs=-1) and bmk re-joins the args
    with spaces, so a single quoted word round-trips unchanged.
    """
    for line in _recipe_lines(_template_text(), target):
        assert '"$(ARGS)"' in line, f"{target!r} must quote ARGS, else bash parses the commit message as code: {line!r}"
        assert not re.search(r"(?<!\")\$\(ARGS\)(?!\")", line), f"{target!r} has an unquoted $(ARGS): {line!r}"


@pytest.mark.os_agnostic
@pytest.mark.parametrize("target", ["test", "run", "custom"])
def test_flag_targets_do_not_quote_args(target: str) -> None:
    """Flag-taking targets keep ARGS unquoted, so multiple flags stay separate words.

    The mirror image of the rule above: quoting here would collapse
    `--human -k foo` into ONE argv element and break the target. Only targets whose
    ARGS is always prose may be quoted.
    """
    for line in _recipe_lines(_template_text(), target):
        assert '"$(ARGS)"' not in line, (
            f"{target!r} takes flags; quoting ARGS would collapse them into one word: {line!r}"
        )


@pytest.mark.os_agnostic
def test_msg_is_exported_unexpanded_as_the_commit_message() -> None:
    """MSG reaches bmk through the environment, and `value` keeps it unexpanded.

    The environment is the only channel that survives a message intact: it is not
    word-split and never reaches a shell command line, so punctuation and newlines
    arrive byte for byte. `$(value MSG)` is required over a plain `$(MSG)`: make
    expands the latter first, so a literal $HOME in a message silently becomes OME.
    """
    text = _template_text()

    assert re.search(r"^export BMK_COMMIT_MESSAGE := \$\(value MSG\)$", text, re.M), (
        "MSG must be exported as BMK_COMMIT_MESSAGE using $(value MSG); "
        "a plain $(MSG) would make-expand a literal $ in the message"
    )


@pytest.mark.os_agnostic
def test_a_newline_in_args_is_refused() -> None:
    """A newline in ARGS is a hard error, raised while parsing, before any recipe runs.

    This is the one case quoting cannot save: make expands ARGS into the recipe
    TEXT, so a newline becomes a recipe LINE BREAK. make then runs line 1 - which
    commits a truncated subject - and line 2 as a separate command. The failure is
    silent where it matters (a wrong commit message is pushed) and loud only
    afterwards, so it has already shipped bad commits more than once. $(error)
    fires at parse time, so nothing is staged, committed or pushed.
    """
    text = _template_text()

    assert re.search(r"^define _BMK_NEWLINE$", text, re.M), "the newline sentinel must exist"
    assert re.search(r"^ifneq \(,\$\(findstring \$\(_BMK_NEWLINE\),\$\(ARGS\)\)\)$", text, re.M), (
        "ARGS must be checked for a newline"
    )
    guard = re.search(r"\$\(error ([^)]*)\)", text)
    assert guard, "the newline check must raise $(error), not merely warn"
    assert "MSG" in guard.group(1), "the error must name MSG as the way to pass a multi-line message"


@pytest.mark.os_agnostic
def test_windows_executable_suffix_is_handled() -> None:
    """uv names the entry point bmk.exe on Windows.

    Without the suffix the Makefile would point at a path that does not exist
    there, and every target would fail on Windows only.
    """
    text = _template_text()

    assert "ifeq ($(OS),Windows_NT)" in text
    assert "BMK_EXE := .exe" in text
