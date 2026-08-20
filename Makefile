# bmk root Makefile — development workflow (installs from local source)
#
# Usage:
#   make test                        # run test suite
#   make test --verbose              # forward extra flags
#   make bump-patch                  # bump patch version
#   make push fix login bug          # push with commit message
#   make custom deploy                # run custom command
#   make custom deploy --dry-run
#
# bmk is installed from the local source tree into this project's own tool env
# (.venv-bmk) on every invocation, editable, so code changes are always live.
#
# Arguments after the target name are forwarded automatically.
# You can also use ARGS="..." explicitly if preferred.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# uv names the executable bmk.exe on Windows, and lays a tool env out like a venv, so its
# interpreter is under Scripts/ there and bin/ everywhere else.
ifeq ($(OS),Windows_NT)
  BMK_EXE := .exe
  BMK_ENV_BIN := Scripts
else
  BMK_EXE :=
  BMK_ENV_BIN := bin
endif

# This env stays PER-PROJECT, and here that is deliberate - do NOT "unify" it with the
# shipped template, which now installs the released bmk into uv's shared tool dir.
#
# The difference is what gets installed. The template installs bmk FROM PyPI, so one
# shared env serves every repo. This Makefile installs bmk from LOCAL SOURCE
# (`--editable ./`), because bmk is the project under development here. Putting that into
# uv's shared tool dir would replace the released bmk for EVERY other repo on this
# machine: every project's `make` would silently start running bmk straight out of this
# working tree, mid-edit. The isolation is the whole point.
#
# The shared/per-project question and the co-resolution question are separate: this env
# holds bmk alone too (bmk IS the project, so `--editable ./` brings only its own deps).
BMK_TOOL_DIR := $(CURDIR)/.venv-bmk
BMK := $(BMK_TOOL_DIR)/bin/bmk$(BMK_EXE)
ARGS ?=

# ──────────────────────────────────────────────────────────────
# Commit messages: MSG= is the safe channel, ARGS= is not
# ──────────────────────────────────────────────────────────────
# This block MIRRORS src/bmk/makefile/Makefile and must stay in step with it; a test
# (tests/test_makefile_template_integrity.py) asserts the two agree. This file is NOT
# generated from that template - it installs bmk from local source instead of from PyPI -
# so nothing copies fixes across, and it has already drifted once with real consequences:
# `make push MSG="..."` here silently ignored MSG and committed 909aa14 as "chores",
# discarding the message, because only the template had been fixed.
#
# Why it is needed at all: make expands $(ARGS) into the recipe text and hands the RESULT
# to the shell, which then parses free-form prose as code - "fix(cli): x" is a syntax
# error, "a; b" runs b, a backtick or $(...) EXECUTES, and a newline ends the recipe LINE,
# so make commits a truncated subject and runs the rest as a command. MSG= never touches a
# command line: make's `export` puts it straight into the child environment, and bmk reads
# args -> BMK_COMMIT_MESSAGE -> prompt (git_ops.resolve_message).
#
# $(value MSG) yields the UNEXPANDED value, so a literal $ survives; plain $(MSG) would
# make-expand it and turn $HOME into OME.
ifdef MSG
export BMK_COMMIT_MESSAGE := $(value MSG)
endif

# A newline in ARGS cannot be passed safely, so refuse it at parse time - before any
# recipe runs, so nothing is staged, committed or pushed.
define _BMK_NEWLINE


endef
ifneq (,$(findstring $(_BMK_NEWLINE),$(ARGS)))
  $(error ARGS contains a newline, which make cannot pass to a recipe safely. Use MSG="..." for a multi-line commit message)
endif

# ──────────────────────────────────────────────────────────────
# Ensure bmk is installed from local source into this project's tool env
# ──────────────────────────────────────────────────────────────
# `--editable ./` installs bmk from the local source tree, so `make` here always runs
# the working copy: the env imports bmk straight out of src/, and a source edit is live
# with no reinstall. A non-editable `--from ./` would install a SNAPSHOT, and `make`
# would keep running the previous build of the very thing under development while
# reporting pass, which is the worst way to be wrong.
#
# No `--with .`: bmk IS this project, so installing it brings its dependencies, and bmk
# ships no [dev] extra (its tooling is declared as runtime deps).
#
# --reinstall is on BOTH attempts: plain `uv tool install` NO-OPS when the tool is
# already present, keeping a stale env. The retry covers the transient __pycache__
# removal race ("Directory not empty", os error 39); if both fail, make fails loudly,
# because a stale env is not a safe state to continue from.
#
# It is CONDITIONAL, for the same reason the template upgrades instead of reinstalling:
# `--reinstall` tears the env down and rebuilds it, so running it before every target
# deleted the site-packages out from under a bmk still RUNNING out of the same env - here
# that is a subagent and the main agent both running make in this repo, which has produced
# ImportErrors inside bmk's own dependencies that looked like real test failures.
#
# Skipping it is safe precisely because the install is EDITABLE: source edits are already
# live with no reinstall (see above), so only three things can invalidate the env, and each
# is checked below.
#
#   * the env is damaged or absent  -> `python -m bmk_selfcheck`, the same RECORD-vs-disk
#     check the template uses (bmk ships it; a fresh tree has no env, so `test -x` keeps
#     that quiet rather than erroring before the very install that fixes it).
#   * dependencies or entry points changed -> pyproject.toml newer than the stamp.
#   * no stamp yet -> never installed by this recipe.
#
# A stamp is wrong in the TEMPLATE (make would skip the install and uv would never see a
# new bmk RELEASE, silently pinning the env) and right here: there is no release to pick
# up, the source is the env's input and it is already live.
BMK_PY := $(BMK_TOOL_DIR)/bmk/$(BMK_ENV_BIN)/python$(BMK_EXE)
BMK_STAMP := $(BMK_TOOL_DIR)/.bmk-editable-install
BMK_INTACT := test -x "$(BMK_PY)" && "$(BMK_PY)" -m bmk_selfcheck

# The stamp makes the rebuild RARE; it does not make it SAFE. When it does fire - a changed
# pyproject.toml, a damaged env - it still tears the env down, and the scenario named above
# (a subagent and the main agent both running make in this repo) is exactly two processes
# reaching that point together. So the rebuild takes the same exclusive lock the template
# uses, and every bmk running out of this env holds it shared for its lifetime.
#
# `tool_env_root()` resolves this to .venv-bmk on its own: uv writes a uv-receipt.toml into
# .venv-bmk/bmk, so the lock lands at .venv-bmk/.bmk-tool.lock and is per-project here,
# machine-wide for the template, with no branch in the code to say so.
#
# `--on-timeout fail` because this path is a REPAIR: skipping it would continue on a stale
# or damaged env. It drops through to the deliberately unguarded second attempt, for the
# same reason the template's does. $(wildcard) makes both vanish on a fresh clone.
BMK_LOCK_REPAIR := $(if $(wildcard $(BMK_PY)),"$(BMK_PY)" -m bmk_toollock --exclusive --timeout 60 --on-timeout fail --,)

.PHONY: _ensure_bmk
_ensure_bmk:
	@if $(BMK_INTACT) && [ -f "$(BMK_STAMP)" ] && [ ! pyproject.toml -nt "$(BMK_STAMP)" ]; then exit 0; fi; \
	  { UV_TOOL_DIR="$(BMK_TOOL_DIR)" UV_TOOL_BIN_DIR="$(BMK_TOOL_DIR)/bin" \
	      $(BMK_LOCK_REPAIR) uv tool install --reinstall --force --editable ./ \
	    || UV_TOOL_DIR="$(BMK_TOOL_DIR)" UV_TOOL_BIN_DIR="$(BMK_TOOL_DIR)/bin" \
	      uv tool install --reinstall --force --editable ./; } \
	  && touch "$(BMK_STAMP)"

# ──────────────────────────────────────────────────────────────
# Argument forwarding via MAKECMDGOALS
# ──────────────────────────────────────────────────────────────
# Allows natural argument passing: make push fix login bug
# instead of: make push ARGS="fix login bug"

# All targets that accept trailing arguments
_BMK_TARGETS := test t test-human th testintegration testi ti testintegration-human tih \
	codecov coverage cov \
	build bld clean cln cl run ensure \
	bump-major bump-minor bump-patch bump \
	commit c push psh p release rel r \
	dependencies deps d dependencies-update \
	config config-deploy config-generate-examples \
	send-email send-notification custom \
	info logdemo

ifneq (,$(filter $(_BMK_TARGETS),$(firstword $(MAKECMDGOALS))))
  # Capture everything after the first word as extra arguments
  _EXTRA := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  # Append to ARGS (so explicit ARGS="..." still works alongside)
  override ARGS += $(_EXTRA)
endif

# ──────────────────────────────────────────────────────────────
# Test & Quality
# ──────────────────────────────────────────────────────────────

.PHONY: test t
test: _ensure_bmk  ## Run test suite [alias: t]
	$(BMK) test $(ARGS)
t: _ensure_bmk
	$(BMK) test $(ARGS)

.PHONY: test-all
test-all: _ensure_bmk  ## Run pytest + pyright on every declared Python version (matrix)
	$(BMK) test-all $(ARGS)

.PHONY: test-human th
test-human: _ensure_bmk  ## Run test suite with human-readable output [alias: th]
	$(BMK) test --human $(ARGS)
th: _ensure_bmk
	$(BMK) test --human $(ARGS)

.PHONY: testintegration testi ti
testintegration: _ensure_bmk  ## Run integration tests only [aliases: testi, ti]
	$(BMK) testintegration $(ARGS)
testi ti: _ensure_bmk
	$(BMK) testintegration $(ARGS)

.PHONY: testintegration-human tih
testintegration-human: _ensure_bmk  ## Run integration tests with human-readable output [alias: tih]
	$(BMK) testintegration --human $(ARGS)
tih: _ensure_bmk
	$(BMK) testintegration --human $(ARGS)

.PHONY: codecov coverage cov
codecov: _ensure_bmk  ## Upload coverage report to Codecov [aliases: coverage, cov]
	$(BMK) codecov $(ARGS)
coverage cov: _ensure_bmk
	$(BMK) codecov $(ARGS)

# ──────────────────────────────────────────────────────────────
# Build & Clean
# ──────────────────────────────────────────────────────────────

.PHONY: build bld
build: _ensure_bmk  ## Build wheel and sdist artifacts [alias: bld]
	$(BMK) build $(ARGS)
bld: _ensure_bmk
	$(BMK) build $(ARGS)

.PHONY: clean cln cl
clean: _ensure_bmk  ## Remove build artifacts and caches [aliases: cln, cl]
	$(BMK) clean $(ARGS)
cln cl: _ensure_bmk
	$(BMK) clean $(ARGS)

.PHONY: clean-all
clean-all: _ensure_bmk  ## Remove build artifacts, caches AND every virtual environment (.venv*)
	$(BMK) clean-all $(ARGS)

# ──────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────

.PHONY: run
run: _ensure_bmk  ## Run the project CLI
	$(BMK) run $(ARGS)

.PHONY: ensure
ensure: _ensure_bmk  ## Install missing external tools for this OS
	$(BMK) ensure $(ARGS)

# ──────────────────────────────────────────────────────────────
# Version Bumping
# ──────────────────────────────────────────────────────────────

.PHONY: bump-major
bump-major: _ensure_bmk  ## Bump major version (X+1).0.0
	$(BMK) bump major $(ARGS)

.PHONY: bump-minor
bump-minor: _ensure_bmk  ## Bump minor version X.(Y+1).0
	$(BMK) bump minor $(ARGS)

.PHONY: bump-patch
bump-patch: _ensure_bmk  ## Bump patch version X.Y.(Z+1)
	$(BMK) bump patch $(ARGS)

.PHONY: bump
bump: bump-patch  ## Bump patch version (default for bump)

# ──────────────────────────────────────────────────────────────
# Git Operations
# ──────────────────────────────────────────────────────────────

# The "$(ARGS)" quoting is LOAD-BEARING - see the commit-message block at the top, and keep
# it identical to src/bmk/makefile/Makefile. commit/push take a MESSAGE and nothing else
# (nargs=-1, no options), so one quoted word costs nothing: bmk re-joins args with spaces,
# and empty ARGS still yields "" and falls through to BMK_COMMIT_MESSAGE / the prompt.
# Flag-taking targets (test, run, custom) must stay UNQUOTED.
.PHONY: commit c
commit: _ensure_bmk  ## Create a git commit with timestamped message [alias: c]
	$(BMK) commit "$(ARGS)"
c: _ensure_bmk
	$(BMK) commit "$(ARGS)"

.PHONY: push psh p
push: _ensure_bmk  ## Run tests, commit, and push to remote [aliases: psh, p]
	$(BMK) push "$(ARGS)"
psh p: _ensure_bmk
	$(BMK) push "$(ARGS)"

.PHONY: release rel r
release: _ensure_bmk  ## Create a versioned release (tag + GitHub release) [aliases: rel, r]
	$(BMK) release $(ARGS)
rel r: _ensure_bmk
	$(BMK) release $(ARGS)

# ──────────────────────────────────────────────────────────────
# Dependencies
# ──────────────────────────────────────────────────────────────

.PHONY: dependencies deps d
dependencies: _ensure_bmk  ## Check and list project dependencies [aliases: deps, d]
	$(BMK) dependencies $(ARGS)
deps d: _ensure_bmk
	$(BMK) dependencies $(ARGS)

.PHONY: dependencies-update
dependencies-update: _ensure_bmk  ## Update dependencies to latest versions
	$(BMK) dependencies update $(ARGS)

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

.PHONY: config
config: _ensure_bmk  ## Show current merged configuration
	$(BMK) config $(ARGS)

.PHONY: config-deploy
config-deploy: _ensure_bmk  ## Deploy configuration to system/user directories
	$(BMK) config-deploy $(ARGS)

.PHONY: config-generate-examples
config-generate-examples: _ensure_bmk  ## Generate example configuration files
	$(BMK) config-generate-examples $(ARGS)

# ──────────────────────────────────────────────────────────────
# Email
# ──────────────────────────────────────────────────────────────

.PHONY: send-email
send-email: _ensure_bmk  ## Send an email via configured SMTP
	$(BMK) send-email $(ARGS)

.PHONY: send-notification
send-notification: _ensure_bmk  ## Send a plain-text notification email
	$(BMK) send-notification $(ARGS)

# ──────────────────────────────────────────────────────────────
# Custom Commands
# ──────────────────────────────────────────────────────────────

.PHONY: custom
custom: _ensure_bmk  ## Run a custom command (make custom <name> [args...])
	$(BMK) custom $(ARGS)

# ──────────────────────────────────────────────────────────────
# Info & Demos
# ──────────────────────────────────────────────────────────────

.PHONY: info
info: _ensure_bmk  ## Print resolved package metadata
	$(BMK) info $(ARGS)

.PHONY: logdemo
logdemo: _ensure_bmk  ## Run logging demonstration
	$(BMK) logdemo $(ARGS)

.PHONY: version-current
version-current: _ensure_bmk  ## Print current version
	$(BMK) --version

# ──────────────────────────────────────────────────────────────
# Development
# ──────────────────────────────────────────────────────────────

.PHONY: dev
dev:  ## Install package with dev extras (editable)
	uv pip install -e ".[dev]"

.PHONY: install
install:  ## Editable install (no dev extras)
	uv pip install -e .

# ──────────────────────────────────────────────────────────────
# Help
# ──────────────────────────────────────────────────────────────

.PHONY: help
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}' | \
		sort

# ──────────────────────────────────────────────────────────────
# No-op overrides for trailing argument words (MUST be last)
# ──────────────────────────────────────────────────────────────
# Placed after all real target definitions so the no-op recipes
# override them.  This prevents "make push codecov fix" from
# executing the real codecov target — "codecov" is an argument
# to push, not a separate command.
ifneq (,$(_EXTRA))
$(_EXTRA):
	@:
endif
