"""Integrity guards for the bundled Makefile template that bmk deploys.

The template is shipped inside the package and copied into target repos by
`bmk install`, so a defect here reaches every bmk-managed repo and cannot be fixed
from those repos. Five invariants are guarded:

1. The header version equals the package version. `_sync_initconf.sync_makefile_version`
   patches it on every bump, so a mismatch means the template was edited and released
   without running the sync, and the published package carries a template labelled
   with the wrong version.
2. The install cannot silently degrade. It runs before every make invocation, and each
   way it can go wrong - no-opping on a stale env, swallowing the error - produces a
   working-looking env that fails much later, somewhere unrelated.
3. bmk's env holds bmk ALONE, and is therefore shared by every repo. The project's
   dependencies live in the project's own `.venv`. This is the load-bearing one: while
   the two resolved together, a project dependency could silently backtrack bmk to an
   ancient release, a yanked transitive dependency could make bmk uninstallable
   fleet-wide, and the tests ran in an env neither pyright nor pip-audit inspected.
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

# bmk's OWN Makefile. It is hand-authored, not generated from the template (it installs
# bmk from local source rather than from PyPI), so nothing propagates a template fix into
# it. That is not hypothetical drift: the commit-message hardening landed in the template
# only, and the very next `make push MSG="..."` in this repo silently ignored MSG and
# committed "chores", throwing the message away.
ROOT_MAKEFILE = PROJECT_DIR / "Makefile"


def _template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _root_makefile_text() -> str:
    return ROOT_MAKEFILE.read_text(encoding="utf-8")


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
def test_ensure_bmk_installs_bmk_alone() -> None:
    """The project is NOT installed into bmk's env - bmk is installed by itself.

    This is the invariant the whole design now rests on, and its absence caused every
    co-resolution bug: with the project's dependencies in bmk's env the two resolved
    TOGETHER, so a project dependency capping one of bmk's silently backtracked bmk to an
    ancient release (codecov-cli's click<8.3.0 pinned bmk at 3.1.7, no error), and a
    yanked transitive dependency made bmk itself uninstallable, bricking `make` fleet-wide.
    It also forced one ~300MB env per repo.

    A `--with` / `--with-editable` reappearing here reinstates all of it.
    """
    recipe = _install_recipe(_template_text())
    installs = re.findall(r"uv tool install[^|]*", recipe)

    assert installs, "the recipe must run `uv tool install`"
    for install in installs:
        assert "--with" not in install, (
            f"bmk's env must hold bmk ALONE; --with/--with-editable makes bmk and the "
            f"project resolve together: {install.strip()!r}"
        )


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


# --- ONE env per machine, not one per project -------------------------------


@pytest.mark.os_agnostic
def test_tool_env_is_shared_not_per_project() -> None:
    """The install does NOT redirect uv's tool dir into the project.

    A per-project env was only ever necessary because the env also carried the PROJECT's
    dependencies, so two projects fought over one env (measured: a `six` project and a
    `chardet` project overwrote each other). bmk's env now holds bmk alone, so it is
    identical for every repo and there is nothing to collide - and one shared env stops
    ~300MB, mostly pyright's bundled Node, from being copied into all ~46 repos.

    `--force` is still required: the entry point already exists in uv's bin dir.
    """
    recipe = _install_recipe(_template_text())

    for attempt in re.findall(r"uv tool install[^|]*", recipe):
        assert "--force" in attempt, "rebuilding over an existing entry point needs --force"
    assert "UV_TOOL_DIR" not in recipe, "the env must be uv's shared default, not per-project"
    assert "UV_TOOL_BIN_DIR" not in recipe, "the env must be uv's shared default, not per-project"


@pytest.mark.os_agnostic
def test_a_new_bmk_release_is_seen_immediately() -> None:
    """The install refreshes bmk's cached index metadata - and skips that when offline.

    `--reinstall` re-resolves, but against uv's CACHED index, so a release published
    minutes ago stays invisible: measured, with 3.8.0 already on PyPI,
    `uv tool install "bmk>=3.7.1"` still installed 3.7.1. That silently defeats the one
    thing running the install before EVERY target is meant to buy.

    The offline exemption is not optional politeness: uv REFUSES the combination ("the
    argument UV_OFFLINE cannot be used with --refresh"), so an unconditional flag would
    fail every make for an offline user, blaming an env var they never linked to it.
    """
    text = _template_text()

    assert re.search(r"^BMK_REFRESH := \$\(if \$\(UV_OFFLINE\),,--refresh-package bmk\)$", text, re.M), (
        "the refresh must be present, and must be omitted when UV_OFFLINE is set"
    )
    for attempt in re.findall(r"uv tool install[^|]*", _install_recipe(text)):
        assert "$(BMK_REFRESH)" in attempt, f"install attempt would use a stale index: {attempt.strip()!r}"


@pytest.mark.os_agnostic
def test_bmk_is_resolved_from_uvs_own_bin_dir() -> None:
    """bmk is invoked via the path uv reports, not a bare name and not a guessed one.

    `uv tool install` only WARNS when its bin dir is not on PATH - the default state on a
    fresh machine - so a bare `bmk` would fail with "command not found" from a Makefile
    that had just installed it. Hardcoding `$(HOME)/.local/bin` instead would be wrong on
    Windows. Asking uv is the only answer that holds on both.
    """
    text = _template_text()

    assert re.search(r"^BMK_BIN_DIR := \$\(shell uv tool dir --bin", text, re.M), (
        "the bin dir must come from `uv tool dir --bin`"
    )
    assert re.search(r"^BMK := \$\(if \$\(BMK_BIN_DIR\)", text, re.M), (
        "BMK must use the resolved bin dir, with a bare-name fallback"
    )
    assert "BMK_TOOL_DIR" not in text, "the per-project tool dir is gone"


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


# --- bmk's own Makefile must not drift from the template on safety -----------


@pytest.mark.os_agnostic
@pytest.mark.parametrize("target", ["commit", "c", "push", "psh p"])
def test_root_makefile_also_quotes_message_targets(target: str) -> None:
    """bmk's own Makefile quotes the message targets too.

    It is hand-authored and nothing syncs it, so the template's hardening does not
    reach it on its own. When it lagged, `make push MSG="..."` in this repo committed
    "chores" and discarded the message - the exact bug, in the tool that ships the fix.
    """
    for line in _recipe_lines(_root_makefile_text(), target):
        assert '"$(ARGS)"' in line, f"root Makefile {target!r} must quote ARGS like the template does: {line!r}"


@pytest.mark.os_agnostic
def test_root_makefile_supports_msg() -> None:
    """bmk's own Makefile exports MSG as BMK_COMMIT_MESSAGE, unexpanded, like the template.

    Without this block MSG= is not ignored loudly - it is ignored SILENTLY, and the
    commit falls back to the non-interactive default "chores".
    """
    text = _root_makefile_text()

    assert re.search(r"^export BMK_COMMIT_MESSAGE := \$\(value MSG\)$", text, re.M), (
        "root Makefile must export MSG as BMK_COMMIT_MESSAGE via $(value MSG), like the template"
    )


@pytest.mark.os_agnostic
def test_root_makefile_keeps_its_own_env_unlike_the_template() -> None:
    """bmk's own Makefile must NOT share uv's tool dir, even though the template now does.

    The two install different things. The template installs the RELEASED bmk from PyPI, so
    one shared env serves every repo. This Makefile installs bmk from LOCAL SOURCE
    (`--editable ./`) because bmk is the project under development. Sharing that would
    replace the released bmk for every other repo on the machine - each one's `make` would
    silently run bmk out of this working tree, mid-edit.

    So this asymmetry is intentional, and "unifying" the two files would be the bug.
    """
    recipe = _install_recipe(_root_makefile_text())

    assert "--editable ./" in recipe, "bmk's own Makefile installs bmk from local source"
    assert "UV_TOOL_DIR" in recipe, (
        "bmk's own dev env must stay per-project; sharing it would push bmk-from-source "
        "into every other repo's toolchain"
    )


@pytest.mark.os_agnostic
def test_root_makefile_refuses_a_newline_in_args() -> None:
    """bmk's own Makefile carries the newline guard too."""
    text = _root_makefile_text()

    assert re.search(r"^ifneq \(,\$\(findstring \$\(_BMK_NEWLINE\),\$\(ARGS\)\)\)$", text, re.M), (
        "root Makefile must refuse a newline in ARGS, like the template"
    )
    assert re.search(r"\$\(error [^)]*MSG[^)]*\)", text), "the guard must $(error) and name MSG"


@pytest.mark.os_agnostic
def test_windows_executable_suffix_is_handled() -> None:
    """uv names the entry point bmk.exe on Windows.

    Without the suffix the Makefile would point at a path that does not exist
    there, and every target would fail on Windows only.
    """
    text = _template_text()

    assert "ifeq ($(OS),Windows_NT)" in text
    assert "BMK_EXE := .exe" in text
