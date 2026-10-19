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
| `[project].version`                   | string | Read by `bump` and `release`. Any canonical PEP 440 version, not only `X.Y.Z` - see "Version format" below.                                 | `bump` and `release` abort                                                           |
| `[project.optional-dependencies].dev` | list   | bmk syncs `.[dev]` into your `.venv`, falling back to `.` if there is no `dev` extra.                                                       | Only the project itself is installed - so pytest is absent and `bmk test` cannot run |

`[dev]` is special: it is the only extra bmk installs by name. **Your test tooling
(`pytest`, `pytest-cov`) must be declared there**, because the suite runs in your venv, not
in bmk's. bmk's environment holds bmk's toolchain and nothing of yours.

### Version format

`[project].version` may be any **canonical** PEP 440 version. Pre-releases, dev releases,
post releases, a short release segment and an epoch are all fine, because that is what
hatchling builds and PyPI accepts:

```toml
version = "1.2.3"       # ok        version = "1.2.3.dev4"   # ok
version = "1.2.3rc1"    # ok        version = "1.2.3.post1"  # ok
version = "1.0"         # ok        version = "1!2.0.0"      # ok
```

Two shapes are refused, each with the fix in the message:

| Written as                         | Refused because                                                                                                                                                                                                                              |
|------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `v1.0.0`, `1.0.0-beta`, `1.2.3RC1` | Not canonical. `packaging` parses these but normalises them, so the release tag (`v` + this string) and the artifact hatchling uploads would disagree, and a `v` prefix would tag `vv1.0.0`. Write the canonical spelling the message names. |
| `1.2.3+local`                      | A local version. It would tag fine and then fail in CI, because PyPI rejects a local version on upload.                                                                                                                                      |

**What a bump produces.** `bump` always lands on a plain three-part release, and a
non-final version is FINALIZED rather than stepped past, so the release an rc was
rehearsing stays reachable:

| current       | `bump patch` | `bump minor` | `bump major` |
|---------------|--------------|--------------|--------------|
| `1.2.3`       | `1.2.4`      | `1.3.0`      | `2.0.0`      |
| `1.2.3rc1`    | `1.2.3`      | `1.3.0`      | `2.0.0`      |
| `1.3.0b2`     | `1.3.0`      | `1.3.0`      | `2.0.0`      |
| `1.2.3.dev4`  | `1.2.3`      | `1.3.0`      | `2.0.0`      |
| `1.2.3.post1` | `1.2.4`      | `1.3.0`      | `2.0.0`      |
| `2.0.0rc1`    | `2.0.0`      | `2.0.0`      | `2.0.0`      |

A post release is final, hence `1.2.3.post1 -> 1.2.4`. The epoch survives a bump; any
pre, dev, post or local segment is dropped. `bmk` has no command that CREATES a
pre-release: write one into `pyproject.toml` yourself, then bump to finalize it.

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

The same classifiers drive **`make test-all`**: it provisions one `.venv-<minor>` per declared
version and runs pytest + pyright in each, in parallel, so you can reproduce CI's version matrix
locally before you push. Plain `make test` stays on the newest version only. With no classifier,
`test-all` tests the default interpreter once and warns.

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

| Key                                        | Type   | Default           | Effect                                                                                                                                                              |
|--------------------------------------------|--------|-------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `[tool.scripts.test].pytest-verbosity`     | string | `"-v"`            | Passed to pytest                                                                                                                                                    |
| `[tool.scripts.test].exclude-markers`      | string | `"integration"`   | `make test` and every `make test-all` cell run pytest with `-m "not <value>"`, unless integration tests were explicitly requested. A single marker name, not a list |
| `[tool.scripts.test].coverage-report-file` | string | `"coverage.xml"`  | Where the XML report is written                                                                                                                                     |
| `[tool.scripts.test].src-path`             | string | `"src"`           | Prepended to `PYTHONPATH` for the test run                                                                                                                          |
| `[tool.coverage.report].fail_under`        | int    | `80`              | `coverage report --fail-under=<value>`                                                                                                                              |
| `[tool.coverage.run].source`               | list   | `["src"]`         | `coverage run --source=<...>`                                                                                                                                       |
| `[tool.pip-audit].ignore-vulns`            | list   | `[]`              | Each id becomes `--ignore-vuln=<id>`                                                                                                                                |
| `[tool.bandit].skips`                      | list   | none              | Read by **bandit itself** (bmk passes `-c pyproject.toml`), never by bmk                                                                                            |
| `[tool.bashate].max-line-length`           | int    | `120`             | Line limit for `.sh` linting                                                                                                                                        |
| `[tool.bashate].ignores`                   | list   | `["E003"]`        | Ignored bashate codes                                                                                                                                               |
| `[tool.psscriptanalyzer].exclude-rules`    | list   | 3 built-ins       | Excluded PSScriptAnalyzer rules for `.ps1`                                                                                                                          |
| `[tool.clean].patterns`                    | list   | 19 built-in globs | What `bmk clean` removes                                                                                                                                            |
| `[tool.git].default-remote`                | string | `"origin"`        | Remote that `release` pushes to                                                                                                                                     |
| `[tool.scripts.test-all].workers`          | int    | parallel          | Caps how many `test-all` version cells run at once. See "test-all: capping the matrix" below                                                                        |

`ignore-vulns` and `skips` are **different vocabularies and neither tool reads the other's
table**. `[tool.pip-audit].ignore-vulns` takes PYSEC / GHSA / CVE ids. `[tool.bandit].skips`
takes bandit check ids (`B101`, `B603`). A CVE id in `[tool.bandit].skips` is silently
inert: it looks like protection and does nothing.

### test-all: capping the matrix

`bmk test-all` runs the test suite and type-check in EVERY declared `.venv-<minor>` at
once (one worker per version, capped at the CPU count). That is fine for most projects, but
a suite that binds fixed `127.0.0.1` ports or shares one test database cannot pass this way:
the cells run each other's tests concurrently against the same port or database and break
each other, even though every cell passes when run alone.

Such a project sets `workers = 1` once, in its own `pyproject.toml`:

```toml
[tool.scripts.test-all]
workers = 1
```

- **Default**: unset. Current behaviour - one worker per declared version, capped at the
  CPU count.
- **Env override**: `BMK_TEST_ALL_WORKERS` (e.g. `BMK_TEST_ALL_WORKERS=1 bmk test-all`),
  for a one-off run without touching `pyproject.toml`. It beats the pyproject setting when
  both are present.
- A configured value is capped at the number of declared versions (asking for more workers
  than there are cells buys nothing) but never raised on its own.
- A value below 1 is refused with a clear error and a non-zero exit; a value that is not an
  integer at all is silently ignored in `pyproject.toml` (same leniency every other
  `[tool.*]` key here has for a malformed value) but is an error from the environment
  variable, since that one has no "unset" reading to fall back to.

## The keys bmk writes back

| Key                               | Behaviour                                                                                                                                                       |
|-----------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `[tool.pyright].exclude`          | If present (and `[tool.pyright].include` is not), bmk appends the venv directories it creates and **rewrites your `pyproject.toml`**.                           |
| `[tool.uv].exclude-newer`         | Written by `make test` / `deps update` when absent, from `[bmk.supply_chain].cooldown` (default `"7 days"`). Never overwritten.                                 |
| `[tool.uv].exclude-newer-package` | bmk adds `<own-package> = false` for every own package the project reaches, and keeps its own floor pins current (see below). Entries the project set are kept. |

This exists because pyright's `exclude` **replaces** its built-in defaults rather than
extending them. The moment you list any exclude of your own, you lose `**/.*` - the rule
that was keeping bmk's venvs out of the walk - and a strict run starts crawling
site-packages. That is not hypothetical: one such run spun for 6h20m at 78% CPU across 21
repos before this was added. bmk leaves the file alone when the key is absent (pyright's
defaults already cover it) or when `include` narrows the scope.

### The supply-chain cooldown (`[tool.uv]`)

A malicious release is usually found and pulled within days. uv refuses every file uploaded
after `exclude-newer`, for the whole dependency tree including transitive packages, so a
project with `exclude-newer = "7 days"` never installs a release younger than seven days.
bmk judges floors against the cutoff uv itself resolved, read back from `uv.lock`, and follows it:

- A third-party floor rises only to the newest release older than the cooldown. A newer
  release still inside the cooldown is not "outdated", so the `deps` gate does not fail on it.
- A floor that is itself younger than the cooldown is never lowered: lowering would drop the
  fixes it was raised for. When no release the floor admits is outside the cooldown yet,
  `make test` / `deps update` gives the floor a per-package cutoff one second after the newest file
  of the satisfying release uploaded FIRST, among those that install on the oldest Python the
  project supports (`exclude-newer-package`, `pydantic = "2026-10-11T18:37:56Z"`), so it admits no
  more than the floor asked for. That release's own requirements are walked the same way, as are
  the releases an exempt package's floor brings in - every requirement `uv lock` can need, since it
  resolves for all platforms and Pythons at once: any marker that can hold for some value of the
  variables it names (judged on every value it compares against, never the host's own), on any
  Python from the oldest supported up, and behind the extras requested. bmk recognises
  its own entries by their value (one second after one of the release's files), drops each once the
  cooldown admits its release, and never touches an entry the project set itself. A
  `[tool.uv.exclude-newer-package]` table keeps its form and its comments. A bare `deps` check (no
  update) reports such a floor as an error, floor kept, and FAILS: `uv lock` cannot satisfy it.
- A package listed under `exclude-newer-package` follows its own value: `false` for no
  cooldown (our own packages), or a shorter duration or a date to admit a young security fix.
- Our own packages must be exempt **transitively**: an exempt package whose newest release
  needs a newer release of another own package resolves to an OLDER release unless that one is
  exempt too. bmk walks the own packages' requirements on PyPI and adds every one it reaches. If
  PyPI does not answer for one of them, bmk leaves `[tool.uv]` as it is and says so, rather than
  write a list that misses whatever sits behind it.
- An exempt package's floor rises only to the newest release `uv lock` can resolve: one whose
  own requirements each have a release the cooldown admits. Our libs' newest release can need a
  third-party release younger than the cooldown, and a floor on it makes the lock unsatisfiable
  until the lib is re-released with cooled floors.

bmk does not parse uv's input grammar. It reads the cutoff uv resolved from `uv.lock`'s
`[options]`, so the two can never disagree about what `"14 Days"` or a bare date means. uv only
warns about a value it cannot read and then ignores the whole `[tool.uv]` block; bmk sees the
missing cutoff in the lock and stops the check, naming the value.

`update_deps` locks before judging, re-locks with `uv lock --upgrade` afterwards (every package at
its newest admitted release), and syncs the project venv from that lock. The `uv_lock` stage that
follows only runs `uv lock --check`, so the gates test exactly the tree the committed `uv.lock`
pins with hashes.

Every venv bmk provisions (`.venv`, `.venv-win`, the `test-all` matrix) is built from `uv.lock`
with `uv sync --locked`. Only when no lock can be made does bmk fall back to installing from
`pyproject.toml`, and it says so on stderr.

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
