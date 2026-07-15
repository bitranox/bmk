# make targets

The Makefile bmk installs is a thin wrapper: each target calls the bmk command of the
same name. See [cli-reference.md](cli-reference.md) for the options each accepts.

| Command                           | Options / Subcommands                                                                       | Description                                          |
|-----------------------------------|---------------------------------------------------------------------------------------------|------------------------------------------------------|
| `make test\|t`                    | `[--human]`                                                                                 | Run test suite (lint, format, type-check, pytest)    |
| `make test-human\|th`             |                                                                                             | Run test suite with human-readable output            |
| `make testintegration\|testi\|ti` | `[--human]`                                                                                 | Run integration tests only (`pytest -m integration`) |
| `make testintegration-human\|tih` |                                                                                             | Run integration tests with human-readable output     |
| `make codecov\|coverage\|cov`     |                                                                                             | Upload coverage report to Codecov                    |
| `make build\|bld`                 |                                                                                             | Build wheel and sdist artifacts                      |
| `make clean\|cln\|cl`             |                                                                                             | Remove build artifacts and caches                    |
| `make run`                        |                                                                                             | Run the project CLI                                  |
| `make bump-patch`                 |                                                                                             | Bump patch version X.Y.(Z+1)                         |
| `make bump-minor`                 |                                                                                             | Bump minor version X.(Y+1).0                         |
| `make bump-major`                 |                                                                                             | Bump major version (X+1).0.0                         |
| `make bump\|bmp\|b`               | subcommands: `[major\|ma]` `[minor\|m]` `[patch\|p]`                                        | Bump patch version (default)                         |
| `make commit\|c`                  | `[MESSAGE...]` or `MSG="..."`; env: `BMK_COMMIT_MESSAGE`                                    | Create a git commit with timestamped message         |
| `make push\|psh\|p`               | `[MESSAGE...]` or `MSG="..."`; env: `BMK_GIT_REMOTE` (=origin), `BMK_GIT_BRANCH` (=current) | Run tests, commit, and push to remote                |
| `make release\|rel\|r`            |                                                                                             | Tag vX.Y.Z, push, create GitHub release via `gh`     |
| `make dependencies\|deps\|d`      | `[--update\|-u]`; subcommands: `[update\|u]`                                                | Check and list project dependencies                  |
| `make dependencies-update`        |                                                                                             | Update dependencies to latest versions               |
| `make config`                     | `[--format {human\|json}]` `[--section SECTION]`                                            | Show current merged configuration                    |
| `make config-deploy`              | `[--target {app\|host\|user}]` `[--force]` `[--[no-]permissions]`                           | Deploy configuration to system/user directories      |
| `make config-generate-examples`   | `[--destination PATH]` `[--force]`                                                          | Generate example configuration files                 |
| `make send-email`                 | `[--subject]` `[--body\|--body-html]` `[--to]` `[--attachment]`                             | Send an email via configured SMTP                    |
| `make send-notification`          | `[--subject]` `[--message]` `[--to]` `[--from]`                                             | Send a plain-text notification email                 |
| `make custom`                     | `<name> [args...]`                                                                          | Run a user-defined pipeline                          |
| `bmk install`                     |                                                                                             | Install or update the bmk Makefile in cwd            |
| `make ensure`                     | `[--dry-run]` `[--strict]`                                                                  | Install missing external tools for this OS           |
| `make info`                       |                                                                                             | Print resolved package metadata                      |
| `make version-current`            |                                                                                             | Print current version                                |
| `make dev`                        |                                                                                             | Install package with dev extras (editable)           |
| `make install`                    |                                                                                             | Editable install (no dev extras)                     |
