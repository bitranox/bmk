# bmk

<!-- Badges -->
[![CI](https://github.com/bitranox/bmk/actions/workflows/default_cicd_public.yml/badge.svg)](https://github.com/bitranox/bmk/actions/workflows/default_cicd_public.yml)
[![CodeQL](https://github.com/bitranox/bmk/actions/workflows/codeql.yml/badge.svg)](https://github.com/bitranox/bmk/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Open in Codespaces](https://img.shields.io/badge/Codespaces-Open-blue?logo=github&logoColor=white&style=flat-square)](https://codespaces.new/bitranox/bmk?quickstart=1)
[![PyPI](https://img.shields.io/pypi/v/bmk.svg)](https://pypi.org/project/bmk/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/bmk.svg)](https://pypi.org/project/bmk/)
[![Code Style: Ruff](https://img.shields.io/badge/Code%20Style-Ruff-46A3FF?logo=ruff&labelColor=000)](https://docs.astral.sh/ruff/)
[![codecov](https://codecov.io/gh/bitranox/bmk/graph/badge.svg?token=UFBaUDIgRk)](https://codecov.io/gh/bitranox/bmk)
[![Maintainability](https://qlty.sh/badges/041ba2c1-37d6-40bb-85a0-ec5a8a0aca0c/maintainability.svg)](https://qlty.sh/gh/bitranox/projects/bmk)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)

Makefiles are great, and every tool that set out to replace them started by asking you to
stop using one. That is the tell. make is fifty years old, sits on every machine, and hands
a stranger exactly one thing to type. Whatever is wrong here, it is not make.

It is the shell inside it. A recipe is a string handed to bash, so your build logic is
stringly-typed and OS-specific, and your prose gets parsed as code. Ours once took a commit
message reading `fix(cli): tidy up`, handed it to bash, and bash did what bash does with a
parenthesis. It committed half the sentence and pushed it.

**bmk is a build, test and release runner for Python projects.** It keeps the Makefile and
throws out the bash. You still type `make test`; bmk reads your `pyproject.toml`, provisions
your venv with uv, and runs the gates. Every command is cross-OS Python with no shell
anywhere, so the same `make test` runs on Linux, macOS and Windows. We deleted all 78 of our
own `.sh` and `.ps1` files rather than keep two of everything.

```bash
uvx bmk install    # drops the Makefile in; installs nothing permanent
make test          # from here on, just make
```

Requires [uv](https://docs.astral.sh/uv/) (there is no pip fallback) and Python 3.10+.

## Key features

- **One Makefile, versioned, that updates itself.** Every project gets the same template,
  and it regenerates when bmk updates, so your repos cannot drift apart.
- **No shell, anywhere.** Every command is cross-OS Python, and every stage is an argv list
  rather than a shell string. Nothing gets handed to bash to re-parse, including your own
  stages and your commit messages.
- **Your dependencies and bmk's never mix.** bmk installs once per machine and holds its own
  toolchain and nothing of yours. Your packages live in the project's `.venv`, and that is
  the environment your tests, type-checker and audit all run against - the same one, so they
  cannot disagree.
- **Staged pipelines, parallel where it is safe.** Stages run in order; stages sharing an
  order run together. Extend any pipeline from your `pyproject.toml`: add, remove or replace
  stages in TOML.
- **Quiet until it matters.** JSON by default: tool output is captured and shown only when a
  stage fails, otherwise you get one summary line. Pass `--human` when you want the noise.
- **Batteries included.** Formatting and linting, type-checking, security and vulnerability
  audits, import-contract checks, tests with coverage, shell and PowerShell linting, version
  bumping, tagging, PyPI release, and Codecov upload.

## Documentation

| Page                                               | What is in it                                               |
|----------------------------------------------------|-------------------------------------------------------------|
| [Install](INSTALL.md)                              | uv, pipx, pip, Poetry/PDM, from git or from build artifacts |
| [make targets](docs/make-targets.md)               | every target and its aliases                                |
| [CLI reference](docs/cli-reference.md)             | every command, option and exit code                         |
| [pyproject reference](docs/pyproject-reference.md) | every `pyproject.toml` section bmk reads, with defaults     |
| [Pipelines and stages](docs/pipelines.md)          | what runs when, and how to change it                        |
| [Email](docs/email.md)                             | `send-email` and `send-notification`                        |
| [Concept](docs/concept.md)                         | the design                                                  |
| [ADRs](docs/adr/)                                  | the decisions, and why                                      |
| [Changelog](CHANGELOG.md)                          | what changed                                                |
| [Contributing](CONTRIBUTING.md)                    | how to work on bmk                                          |

## License

MIT - see [LICENSE](LICENSE).
