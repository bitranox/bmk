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
   working-looking env that fails much later, somewhere unrelated. It also must not
   REBUILD the env on the common path: that env is shared machine-wide, so an
   unconditional reinstall deletes it out from under a bmk running in another repo.
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

    These attempts are the REPAIR path, reached when the env is absent or damaged.
    `uv tool install` without `--reinstall` NO-OPS when the tool is already present,
    so a repair lacking it would repair nothing and hand back the same broken env.
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

    assert recipe.count("uv tool install") == 2, "expected exactly two identical repair attempts"
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
def test_the_common_path_upgrades_and_does_not_rebuild_the_env() -> None:
    """`uv tool upgrade` is the primary path; the reinstall is only a fallback.

    This is the fix for a cross-repo race, not a speed tweak. bmk's env is shared by
    every repo on the machine, so an unconditional `uv tool install --reinstall --force`
    before every target meant a make in one repo deleted the site-packages out from under
    a bmk still RUNNING in another, mid-test-suite. It surfaced as an ImportError inside
    bmk's own dependencies that cleared on a re-run, so it read as a flake.

    `uv tool upgrade` leaves the env byte-identical when bmk is already current (measured:
    "Nothing to upgrade", directory mtimes unchanged), so the destructive window shrinks
    from every make to an actual version change.
    """
    recipe = _install_recipe(_template_text())

    assert "uv tool upgrade bmk" in recipe, "the common path must upgrade, not reinstall"
    upgrade_at = recipe.index("uv tool upgrade bmk")
    install_at = recipe.index("uv tool install")
    assert upgrade_at < install_at, "the reinstall must be the FALLBACK, reached only after the upgrade path fails"


@pytest.mark.os_agnostic
def test_the_upgrade_carries_no_refresh_flag() -> None:
    """No --refresh/--refresh-package on the upgrade: uv rejects them outright (exit 2).

    The flag was required by the OLD recipe, because `uv tool install` re-resolves against
    uv's CACHED index and a release published minutes ago stayed invisible (measured: with
    3.8.0 already on PyPI, `uv tool install "bmk>=3.7.1"` still installed 3.7.1).

    `uv tool upgrade` does not need it: it revalidates pypi.org/simple/bmk/ on EVERY run
    with no freshness window (measured three times back to back, all revalidating). Adding
    the flag anyway would fail every make with an argument-parse error.
    """
    text = _template_text()
    recipe = _install_recipe(text)

    assert "--refresh" not in recipe, "uv tool upgrade REJECTS --refresh/--refresh-package (exit 2)"
    # Match the make ASSIGNMENT, not the bare name: both identifiers are discussed in the
    # comment block above the recipe, and that prose must stay writable.
    assert not re.search(r"^BMK_REFRESH :=", text, re.M), (
        "the refresh variable is obsolete; uv tool upgrade always revalidates"
    )
    assert not re.search(r"^\s*BMK_REFRESH\b.*:?=", text, re.M) and "$(BMK_REFRESH)" not in text, (
        "nothing may still reference the retired refresh variable"
    )
    assert not re.search(r"\$\(if \$\(UV_OFFLINE\)", text), (
        "the offline carve-out existed only to dodge uv refusing --refresh; "
        "UV_OFFLINE=1 uv tool upgrade bmk answers 'Nothing to upgrade' cleanly"
    )


@pytest.mark.os_agnostic
def test_a_damaged_env_is_detected_and_rebuilt() -> None:
    """An integrity check gates the upgrade, replacing a repair that used to be accidental.

    While every make rebuilt the env, a corrupted env silently fixed itself. Upgrading
    does not rebuild, so that free repair is gone and has to be earned back deliberately:
    `python -m bmk_selfcheck` compares every installed distribution's RECORD against the
    filesystem, and a miss falls through to the full reinstall.

    It must run the interpreter DIRECTLY, never `bmk --version`. An import probe costs
    1.3s - more than the 0.9s upgrade it guards - and would have missed the real failure
    anyway, because bmk's startup never imports pip_api, the package that was damaged.
    """
    text = _template_text()
    recipe = _install_recipe(text)

    assert "$(BMK_INTACT)" in recipe, "the upgrade must be gated on an integrity check"
    assert re.search(r"^BMK_INTACT := .*-m bmk_selfcheck", text, re.M), (
        "the check must run `python -m bmk_selfcheck` in bmk's own env"
    )
    assert "$(BMK) --version" not in recipe, (
        "an import probe is slower than the upgrade it guards and misses the failure it exists for"
    )
    assert re.search(r"^BMK_PY := ", text, re.M), "the check needs the interpreter inside bmk's env"


@pytest.mark.os_agnostic
def test_a_fresh_machine_does_not_report_a_missing_env_as_an_error() -> None:
    """The check is skipped when there is no tool env yet, rather than failing loudly.

    A first-ever make has nothing installed. Running the interpreter anyway would print a
    "no such file" error before the very install that fixes it, which reads as a broken
    setup. `test -x` short-circuits instead, and the recipe proceeds to the install.
    """
    text = _template_text()
    match = re.search(r"^BMK_INTACT := (.*)$", text, re.M)

    assert match, "the template must define BMK_INTACT"
    assert 'test -x "$(BMK_PY)"' in match.group(1), "an absent interpreter must short-circuit, not error"
    assert match.group(1).endswith(",false)"), "an unresolvable tool dir must fall through to the install"


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
@pytest.mark.parametrize("target", ["test-all", "clean-all"])
def test_matrix_and_purge_targets_call_bmk(target: str) -> None:
    """The matrix (`test-all`) and purge (`clean-all`) targets must reach bmk, and ride
    _ensure_bmk like every other target so bmk is installed first."""
    text = _template_text()
    assert f"{target}: _ensure_bmk" in text, f"{target} must depend on _ensure_bmk"
    assert any(f"$(BMK) {target}" in line for line in _recipe_lines(text, target)), (
        f"{target} must invoke `$(BMK) {target}`"
    )
    assert target in text.split("_BMK_TARGETS :=", 1)[1].split("\n\n", 1)[0], (
        f"{target} must be in _BMK_TARGETS so trailing words forward as $(ARGS)"
    )


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
def test_root_makefile_does_not_rebuild_its_env_on_every_make() -> None:
    """bmk's own Makefile installs CONDITIONALLY, for the same reason the template upgrades.

    `--reinstall` tears the env down and rebuilds it. Running that before every target
    deleted the site-packages out from under a bmk still RUNNING out of the same env -
    here, a subagent and the main agent both running make in this repo - and surfaced as an
    ImportError inside bmk's own dependencies that read as a real test failure.

    Skipping is safe only because the install is EDITABLE: a source edit is already live
    without reinstalling. So the guard checks the three things that CAN invalidate the env,
    and nothing else: it is damaged, its dependencies changed, or it was never installed.
    """
    text = _root_makefile_text()
    recipe = _install_recipe(text)

    assert "$(BMK_INTACT)" in recipe, "a damaged env must still be rebuilt"
    assert "$(BMK_STAMP)" in recipe, "the install must be gated, not unconditional"
    assert "pyproject.toml -nt" in recipe, "a dependency or entry-point change must reinstall"
    assert re.search(r"^BMK_INTACT := .*-m bmk_selfcheck", text, re.M), (
        "the damage check must be the same RECORD-vs-disk probe the template uses"
    )


@pytest.mark.os_agnostic
def test_only_the_root_makefile_uses_a_stamp() -> None:
    """The stamp is right here and wrong in the template, so it must not spread.

    This Makefile installs from LOCAL SOURCE: there is no release to discover, and the
    source is already live in an editable install. The template installs a RELEASE from
    PyPI, so a stamp would make make skip the upgrade and the env would silently pin
    itself to whatever bmk it first saw.
    """
    assert "BMK_STAMP" in _root_makefile_text(), "bmk's own Makefile gates its editable install"
    assert "BMK_STAMP" not in _template_text(), (
        "a stamp in the template would stop uv from ever seeing a new bmk release"
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


@pytest.mark.os_agnostic
def test_every_top_level_module_the_makefile_runs_is_in_the_wheel() -> None:
    """`_ensure_bmk` runs two top-level modules; both must actually ship.

    `packages = ["src/bmk"]` does NOT carry a lone module, so each one needs its own
    `only-include` entry. If one is missing, the deployed Makefile runs
    `python -m <module>` against a module that is not installed, both guarded attempts
    fail, and EVERY make in EVERY repo falls through to a full `--reinstall` of the shared
    environment - forever, and self-perpetuating, since the reinstall cannot add a file the
    wheel does not contain. That is the fleet-wide brick ADR 0002 exists to prevent.
    """
    config = rtoml.loads(PROJECT_DIR.joinpath("pyproject.toml").read_text(encoding="utf-8"))
    only_include = config["tool"]["hatch"]["build"]["targets"]["wheel"]["only-include"]

    for module in ("src/bmk_selfcheck.py", "src/bmk_toollock.py"):
        assert module in only_include, f"{module} is run by the Makefile but is not in the wheel"


@pytest.mark.os_agnostic
def test_the_upgrade_waits_for_bmk_processes_running_out_of_the_shared_env() -> None:
    """The mutation must be serialised against every bmk running out of that env.

    The environment is shared by every repo on the machine. Unguarded, a `make` here
    deleted the site-packages out from under a bmk minutes into a test suite in an
    unrelated repo, surfacing as an ImportError in bmk's OWN dependencies that cleared on
    a re-run and so read as a flake.
    """
    text = _template_text()
    recipe = _install_recipe(text)
    upgrade_line = next(line for line in recipe.splitlines() if "uv tool upgrade" in line)

    assert "$(BMK_LOCK)" in upgrade_line, "the upgrade is unguarded"
    guard = next(line for line in text.splitlines() if line.startswith("BMK_LOCK :="))
    assert "-m bmk_toollock" in guard, "the guard variable does not run the lock module"
    assert "--exclusive" in guard, "the guard must exclude the shared readers, not join them"


@pytest.mark.os_agnostic
def test_the_guard_runs_on_the_tool_envs_own_interpreter() -> None:
    """It must be `$(BMK_PY)`, not `$(BMK)`.

    `$(BMK)` is the bmk entry point, which imports the package whose environment is being
    guarded. `$(BMK_PY)` is the env's interpreter, and it is a SYMLINK to a base
    interpreter outside the tool dir, so the stdlib the guard runs on is not part of the
    tree uv replaces.
    """
    text = _template_text()
    guard_lines = [line for line in text.splitlines() if "bmk_toollock" in line and ":=" in line]

    assert guard_lines, "no guard variable defined"
    for line in guard_lines:
        assert "$(BMK_PY)" in line, f"the guard must run on the env's own interpreter: {line}"
        assert "$(BMK)" not in line.replace("$(BMK_PY)", ""), f"must not go through the bmk CLI: {line}"


@pytest.mark.os_agnostic
def test_the_upgrade_wait_is_bounded_and_skippable() -> None:
    """An unbounded wait would serialise every repo's make behind the longest gate.

    A SKIPPED upgrade costs nothing - the next make picks it up - so the upgrade skips
    rather than blocking or failing.
    """
    text = _template_text()
    upgrade_guard = next(line for line in text.splitlines() if "BMK_LOCK :=" in line)

    assert "--timeout" in upgrade_guard, "an unbounded wait can stall every repo on the machine"
    assert "--on-timeout skip" in upgrade_guard, "a deferred upgrade is free; blocking is not"


@pytest.mark.os_agnostic
def test_the_repair_may_not_silently_skip() -> None:
    """Skipping a REPAIR would proceed on a damaged environment.

    It fails instead, and the recipe falls through to the unguarded last resort.
    """
    text = _template_text()
    repair_guard = next(line for line in text.splitlines() if "BMK_LOCK_REPAIR :=" in line)

    assert "--on-timeout fail" in repair_guard, "a skipped repair leaves the env damaged"


@pytest.mark.os_agnostic
def test_the_last_repair_attempt_is_deliberately_unguarded() -> None:
    """Pins a LIMITATION so nobody "completes" it later and bricks `make` fleet-wide.

    The guard lives inside the environment being repaired. On the path where that
    environment is absent or broken, the guard may be broken too - an unguarded last resort
    is what stops a defective guard from making `make` unrunnable everywhere.
    """
    recipe = _install_recipe(_template_text())
    attempts = [line for line in recipe.splitlines() if "uv tool install" in line]

    assert len(attempts) == 2, f"expected exactly two install attempts, got {len(attempts)}"
    assert "$(BMK_LOCK" not in attempts[-1], "the last resort must stay unguarded"
    assert "$(BMK_LOCK_REPAIR)" in attempts[0], "the first repair attempt must be guarded"


@pytest.mark.os_agnostic
def test_a_machine_with_no_tool_env_yet_runs_the_install_bare() -> None:
    """On a first-ever make there is no interpreter to run the guard with.

    `$(wildcard ...)` expands to nothing there, so both wrappers vanish and the install
    runs bare rather than failing on a missing module.
    """
    text = _template_text()
    guard_lines = [line for line in text.splitlines() if "bmk_toollock" in line and ":=" in line]

    assert guard_lines, "no guard variable defined, so this test would assert nothing"
    for line in guard_lines:
        assert "$(wildcard $(BMK_PY))" in line, f"guard must vanish when there is no tool env: {line}"


@pytest.mark.os_agnostic
def test_the_root_makefile_guards_its_rebuild_too() -> None:
    """bmk's own Makefile is hand-authored and nothing copies fixes into it.

    Its stamp makes the rebuild rare, not safe: when it does fire, it tears the env down,
    and its own comment names the case - a subagent and the main agent both running make in
    this repo. So it takes the same exclusive lock, and must not drift back.
    """
    recipe = _install_recipe(_root_makefile_text())

    assert "$(BMK_LOCK_REPAIR)" in recipe, "bmk's own rebuild is unguarded"
    assert "--on-timeout fail" in _root_makefile_text(), "a repair may not silently skip"
