# Installation Guide

> The CLI stack uses `rich-click`, which bundles `rich` styling on top of click-style ergonomics.

This guide collects every supported method to install `bmk`, including
isolated environments and system package managers. Pick the option that matches your workflow.


## We recommend `uv` to install the package

### `uv` = Ultra-fast Python package manager

> lightning-fast replacement for `pip`, `venv`, `pip-tools`, and `poetry`
written in Rust, compatible with PEP 621 (`pyproject.toml`)


## Install uv (if not already installed)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Recommended: persistent tool install

bmk is installed once per machine as a persistent `uv tool`, on its own. Your project
is deliberately not part of that install: your dependencies live in the project's own
`.venv`, and that is where pytest, pyright and pip-audit run.

```bash
# Drop the Makefile in; it installs bmk (once per machine) and builds the
# project's own .venv, re-resolving bmk on every make.
uvx bmk install
make test

# Reinstall by hand to pick up a new bmk release (make already does this)
uv tool install --reinstall bmk
```

`make` builds ONE directory in the project: `.venv`, the project's own venv, which bmk
syncs to `pyproject.toml`. It is gitignored and disposable. bmk itself lives outside the
project, in uv's tool dir (`uv tool dir`), shared by every repo - it can be shared
precisely because it holds none of your packages.

Do not add `--with .` / `--with-editable ".[dev]"` to that install. It is what made bmk
and your project resolve TOGETHER, and every consequence was a bug: one of your
dependencies capping one of bmk's silently backtracked bmk to an ancient release; a
yanked transitive dependency made bmk uninstallable outright; and the tests ran in that
co-resolved env while pyright and pip-audit inspected your real `.venv`, so the suite and
the audit described different environments.

### Via the Makefile (automatic)

The bundled Makefile handles installation automatically on every target.
Nothing needs installing by hand, before or after:

```bash
# One-time: install the Makefile (installs nothing permanently)
uvx bmk install

# From now on, just use make - bmk + deps are re-resolved every time
make test
```

Behind the scenes, the Makefile runs before every target:
```bash
uv tool install --reinstall bmk --with .
```

### Private repository dependencies

For projects with private GitHub dependencies, configure git URL rewriting
before installing:

```bash
git config --global url."https://<TOKEN>@github.com/<ORG>/".insteadOf "https://github.com/<ORG>/"
make test   # the Makefile syncs the project's deps into its own .venv
```

PEP 440 direct references in `[project.dependencies]` are resolved through
the rewritten URLs.

## Verify installation

After any install method, confirm the CLI is available:

```bash
bmk --version
```

---

## Installation via pip

```bash
# optional, install in a venv (recommended)
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
# install from PyPI
pip install bmk
# optional install from GitHub
pip install "git+https://github.com/bitranox/bmk"
# optional development install from local
pip install -e "."
# optional install from local runtime only:
pip install .
```

## Per-User Installation (No Virtualenv) - from local

```bash
# install from PyPI
pip install --user bmk
# optional install from GitHub
pip install --user "git+https://github.com/bitranox/bmk"
# optional install from local
pip install --user .
```

> Note: This respects PEP 668. Avoid using it on system Python builds marked as
> "externally managed". Ensure `~/.local/bin` (POSIX) is on your PATH so the CLI is available.

## pipx (Isolated CLI-Friendly Environment)

```bash
# install pipx via pip
python -m pip install pipx
# optional install pipx via apt
sudo apt install python-pipx
# install via pipx from PyPI
pipx install bmk
# optional install via pipx from GitHub
pipx install "git+https://github.com/bitranox/bmk"
# optional install from local
pipx install .
pipx upgrade bmk
# install from Git tag
pipx install "git+https://github.com/bitranox/bmk@v1.1.0"
```

## From Build Artifacts

```bash
python -m build
pip install dist/bmk-*.whl
pip install dist/bmk-*.tar.gz   # sdist
```

## Poetry or PDM Managed Environments

```bash
# Poetry
poetry add bmk     # as dependency
poetry install                          # for local dev

# PDM
pdm add bmk
pdm install
```

## Install Directly from Git

```bash
pip install "git+https://github.com/bitranox/bmk"
```

## System Package Managers (Optional Distribution Channels)

- Use [fpm](https://fpm.readthedocs.io/) to repackage the Python wheel into `.deb` or `.rpm` for distribution via `apt` or `yum`/`dnf`.

All methods register the `bmk` command on your PATH.
