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

## Recommended: persistent tool install with project deps

bmk is installed as a persistent `uv tool` together with the current
project's dependencies. This ensures tools like pyright, pytest and
pip-audit can resolve the full dependency tree.

```bash
# Drop the Makefile in; it builds the project's own .venv-bmk on first use
# and re-resolves bmk and the project deps on every make.
uvx bmk install
make test

# Reinstall to pick up changed project deps (e.g. after editing pyproject.toml)
uv tool install --reinstall bmk --with .
```

`make` builds two directories in the project: `.venv-bmk` (bmk plus this project's
dependencies, the env bmk's tools run in) and `.venv` (the project's own venv, which
bmk syncs to pyproject.toml). Both belong to this repo alone, so projects cannot
overwrite each other's dependencies, and both are gitignored and disposable.

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
make test   # the Makefile installs bmk + the project deps into .venv-bmk
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
