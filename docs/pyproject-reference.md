# What bmk reads from your `pyproject.toml`

bmk is configured almost entirely from your project's own `pyproject.toml`. This page lists
every section it reads, what it does with each, and the default when the key is absent.

Two rules before the tables:

- **Nothing here is required except `[project].name` and `[project].version`.** Every other
  key has a default, and a missing `pyproject.toml` never crashes bmk - it degrades.
- **Watch hyphens versus underscores.** `[tool.scripts.test]` uses hyphens
  (`pytest-verbosity`, `exclude-markers`); `[tool.coverage.report].fail_under` uses an
  underscore, because that is coverage's own key, not bmk's. A mix-up does not error. The
  key is simply never seen and you silently get the default.

## Required

| Key                                   | Type   | What bmk does                                                                                                                               | Missing?                                                                             |
|---------------------------------------|--------|---------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| `[project].name`                      | string | Derives the package name, which is what bandit scans (`bandit -r src/<package>`) and what coverage measures. See "Package name derivation". | `bmk run` fails with "Could not read project name"                                   |
| `[project].version`                   | string | Read by `bump` and `release`.                                                                                                               | `bump` and `release` abort                                                           |
| `[project.optional-dependencies].dev` | list   | bmk syncs `.[dev]` into your `.venv`, falling back to `.` if there is no `dev` extra.                                                       | Only the project itself is installed - so pytest is absent and `bmk test` cannot run |

`[dev]` is special: it is the only extra bmk installs by name. **Your test tooling
(`pytest`, `pytest-cov`) must be declared there**, because the suite runs in your venv, not
in bmk's. bmk's environment holds bmk's toolchain and nothing of yours.

## The Python version of your venv

| Key                                          | Type | What bmk does                                                                                                    | Missing?                                     |
|----------------------------------------------|------|------------------------------------------------------------------------------------------------------------------|----------------------------------------------|
| `[project].classifiers` (`:: Python :: X.Y`) | list | Picks the **highest** `X.Y` you declare, keeps it installed and on its latest patch, and builds `.venv` with it. | uv chooses the interpreter, as it always did |

bmk builds your `.venv` on the **newest Python your project says it supports**, at that
version's **latest patch**:

```toml
[project]
requires-python = ">=3.10"
classifiers = [
  "Programming Language :: Python :: 3",       # ignored: no minor
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.14",    # <- bmk builds .venv on 3.14, latest patch
]
```

**Why the classifiers and not `requires-python`.** `requires-python` is a floor. `>=3.10` says
nothing about the newest version you support, so it cannot answer "which Python should the venv
be". The classifiers are where you state that - and your CI workflow already builds its test
matrix from exactly these entries. Reading the same key keeps your venv and your CI matrix
agreeing about the newest supported Python instead of quietly drifting apart.

Only entries with a dotted `X.Y` count, so the conventional bare `:: Python :: 3` and
`:: Python :: 3 :: Only` are skipped. The highest is chosen numerically, so `3.14` beats `3.9`
(a lexical sort would get that backwards).

**What this costs, and when.** Before a command that touches the environment, bmk runs
`uv python install <X.Y>` and `uv python upgrade <X.Y>`. Both are needed: `install` fetches a
version you have just added to the classifiers, and `upgrade` is what moves an already-installed
minor onto a newer patch - `install` alone will not, it keeps the version it already has. When
you are current this costs about 0.1s and works offline.

**A new patch usually costs you nothing.** uv builds a venv against the minor alias, so
`uv python upgrade` moves your existing venv onto the new patch by itself - bmk checks the
interpreter, sees it is already current, and does nothing. (`pyvenv.cfg`'s `version_info` still
reports the old patch after such an upgrade; it is written once at creation. bmk asks the
interpreter, not that text, precisely so it does not rebuild a venv uv has already migrated.)

A **minor** change is the case that cannot be done in place - move `3.14` to `3.15` in your
classifiers and the venv is **rebuilt**. The path never changes, so nothing pointing at it breaks;
the cost is one full re-resolve. If uv cannot say what it would provide (offline with the version
absent, uv not installed), your existing venv is left exactly as it is: bmk never rebuilds on a
guess.

**Declaring nothing is a valid choice.** With no `:: Python :: X.Y` classifier, bmk picks no
version and uv's own default stands - bmk will not invent a version you never claimed to support.

### Package name derivation

Tried in order, first hit wins:

1. `[tool.hatch.build.targets.wheel].packages` - first entry, basename
2. `[project.scripts].<any>` - value split on `:` then `.`, first segment
3. `[project].name` - hyphens replaced with underscores

Override it with `BMK___BMK__PACKAGE_NAME` (or `package_name` in bmk's own config) when the
import package does not match the distribution name. A wrong name does not fail loudly: it
narrows what bandit scans and what coverage measures, and still reports success.

## Gates

| Key                                        | Type   | Default           | Effect                                                                                                                    |
|--------------------------------------------|--------|-------------------|---------------------------------------------------------------------------------------------------------------------------|
| `[tool.scripts.test].pytest-verbosity`     | string | `"-v"`            | Passed to pytest                                                                                                          |
| `[tool.scripts.test].exclude-markers`      | string | `"integration"`   | Runs pytest with `-m "not <value>"`, unless integration tests were explicitly requested. A single marker name, not a list |
| `[tool.scripts.test].coverage-report-file` | string | `"coverage.xml"`  | Where the XML report is written                                                                                           |
| `[tool.scripts.test].src-path`             | string | `"src"`           | Prepended to `PYTHONPATH` for the test run                                                                                |
| `[tool.coverage.report].fail_under`        | int    | `80`              | `coverage report --fail-under=<value>`                                                                                    |
| `[tool.coverage.run].source`               | list   | `["src"]`         | `coverage run --source=<...>`                                                                                             |
| `[tool.pip-audit].ignore-vulns`            | list   | `[]`              | Each id becomes `--ignore-vuln=<id>`                                                                                      |
| `[tool.bandit].skips`                      | list   | none              | Read by **bandit itself** (bmk passes `-c pyproject.toml`), never by bmk                                                  |
| `[tool.bashate].max-line-length`           | int    | `120`             | Line limit for `.sh` linting                                                                                              |
| `[tool.bashate].ignores`                   | list   | `["E003"]`        | Ignored bashate codes                                                                                                     |
| `[tool.psscriptanalyzer].exclude-rules`    | list   | 3 built-ins       | Excluded PSScriptAnalyzer rules for `.ps1`                                                                                |
| `[tool.clean].patterns`                    | list   | 19 built-in globs | What `bmk clean` removes                                                                                                  |
| `[tool.git].default-remote`                | string | `"origin"`        | Remote that `release` pushes to                                                                                           |

`ignore-vulns` and `skips` are **different vocabularies and neither tool reads the other's
table**. `[tool.pip-audit].ignore-vulns` takes PYSEC / GHSA / CVE ids. `[tool.bandit].skips`
takes bandit check ids (`B101`, `B603`). A CVE id in `[tool.bandit].skips` is silently
inert: it looks like protection and does nothing.

## The one key bmk writes back

| Key                      | Behaviour                                                                                                                             |
|--------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| `[tool.pyright].exclude` | If present (and `[tool.pyright].include` is not), bmk appends the venv directories it creates and **rewrites your `pyproject.toml`**. |

This exists because pyright's `exclude` **replaces** its built-in defaults rather than
extending them. The moment you list any exclude of your own, you lose `**/.*` - the rule
that was keeping bmk's venvs out of the walk - and a strict run starts crawling
site-packages. That is not hypothetical: one such run spun for 6h20m at 78% CPU across 21
repos before this was added. bmk leaves the file alone when the key is absent (pyright's
defaults already cover it) or when `include` narrows the scope.

## Extending a pipeline

Add, remove or replace stages of any pipeline (`test`, `push`, `release`, or your own
`bmk custom <name>`):

```toml
[tool.bmk.pipelines.test]
add     = [{ name = "licence-check", order = 45, argv = ["reuse", "lint"] }]
remove  = ["bandit"]
replace = [{ name = "ruff", order = 40, argv = ["ruff", "check", "--fix", "."] }]
```

| Key       | Type                            |
|-----------|---------------------------------|
| `add`     | list of `{ name, order, argv }` |
| `remove`  | list of stage names             |
| `replace` | list of `{ name, order, argv }` |

`argv` is a **list, never a shell string**, so your own stages get the same guarantee as
the built-in ones: nothing is handed to a shell to re-parse. Stages run in `order`; stages
sharing an order run in parallel.

A `bmk_makescripts/stages.toml` with `[pipelines.<prefix>]` wins over `pyproject.toml`.

This is the one section that fails loudly: an invalid overlay raises
`invalid [tool.bmk.pipelines.<prefix>] overlay: ...` rather than being ignored, because it
is pipeline logic you wrote on purpose.

## Dependency tables scanned by `deps`

All of these are scanned and concatenated. There is **no precedence and no
de-duplication** - a package listed twice appears twice, under each source label.

`[project].dependencies`, `[project.optional-dependencies].<group>`,
`[build-system].requires`, `[dependency-groups].<group>` (PEP 735),
`[tool.pdm].dev-dependencies.<group>`, `[tool.poetry].dependencies`,
`[tool.poetry].dev-dependencies`, `[tool.poetry.group.<name>].dependencies`,
`[tool.uv].dev-dependencies`.

Poetry version syntax is approximated: `^1.2` and `~1.2` both become `>=1.2`. The
caret/tilde upper bound is **not** reproduced.

## Missing or malformed file

A missing `pyproject.toml` never crashes bmk. Readers guard on the file's existence and
return defaults; the commands that genuinely need a value (`bump`, `release`, `run`) then
report a clear "could not find" error. A malformed file additionally prints
`Warning: Failed to parse ...` and takes the same degraded path. Venv provisioning is
skipped entirely when the file is absent.
