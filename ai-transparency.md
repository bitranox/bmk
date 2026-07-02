# AI transparency

The author and owner of this project is the human, [@bitranox](https://github.com/bitranox).
Every design and engineering decision is theirs, and they answer for everything published here.
An AI assistant (Claude, run through the Claude Code CLI) was used as a tool along the way,
mostly for the typing and the legwork under that direction. This page says where, plainly, so
you can weigh the work on its merits. The reasoning behind working this way is in
[ai-stance.md](ai-stance.md).

## The human's work

The shape of this software is the human's, start to finish. They set the problem, made every
call, and own the result.

- The problem is theirs: a stack of sibling Python projects that each carried their own
  bespoke build, test and release scripts, in a bash-and-PowerShell pair that drifted apart and
  went untested. bmk replaces that with one cross-OS tool a project drops in and calls.
- Every design and architecture decision was the human's: the clean-architecture split
  (domain / application / adapters / composition) with import-linter contracts that fail the
  build if a dependency points the wrong way; the in-process Python stage runner that replaced
  the shell scripts, running stages in ordered batches with the ones sharing an order in
  parallel and the pipeline failing fast; capturing each stage's output and showing it only when
  that stage fails, so a green run is quiet; JSON output by default for machine consumers, text
  on request; the decision that a project customises a pipeline only through a TOML overlay
  (`[tool.bmk.pipelines]`), and that the old per-script shell override goes away with it (the
  breaking change behind 3.0.0); classifying the linters, type checker and test tools as runtime
  dependencies rather than dev extras, because bmk's whole job is to run them; and bmk installing
  itself as a `uv` tool alongside a project's own dependencies so the tools resolve the real
  dependency tree. Where there were options, the human picked.
- The `bmk ensure` command (release 3.1.0) was the human's call too: that bmk should be able to
  install the external tools it needs per operating system, that it should do so best-effort and
  report rather than fail on a platform where a tool has no installer, and that the linters go in
  via pip while git and pwsh go through the system package manager. The AI proposed the shape and
  asked the open questions; the human chose the answers.
- The human reviewed and corrected the work at each step; what ships is what they signed off on.
- Every commit and every release went out under the human's name and authority, with no AI
  co-author line. The human is responsible for what is published to PyPI and GitHub.

## Where the AI was used

As a tool, under the human's direction, it did the mechanical parts: reading and tracing the
existing scripts to find what each stage actually did before porting it; writing the domain
model, the stage-runner engine, the CLI commands, the in-process helpers, these docs and the
tests to the human's design; laying out the options at each fork for the human to choose from;
and grinding through the cross-OS edge cases that a single code path has to get right (path
separators, platform-guarded signal handling, the `Scripts\python.exe` versus `bin/python` split,
tools that only exist on one operating system). It ran the full gate over and over while
iterating, and fixed the lint, type-check and test failures it surfaced. It wrote the README,
the changelog entries and the module reference to the human's structure. None of the decisions,
and none of the accountability, were the AI's -- the human directed and approved every action
and owns the result.

## What's been checked, and what hasn't

The gate bmk runs on itself is the same one it runs for other projects. `make test` runs ruff
(lint and format), pyright in strict mode, bandit, the import-linter architecture contracts,
the test suite under coverage, and pip-audit. The run is honest about being self-hosted: bmk
reinstalls itself from the working tree as a `uv` tool and then runs that freshly built bmk
against its own suite, so the tool that grades the code is the code. It runs green in CI across a
matrix of Linux, macOS and Windows on Python 3.10 through 3.14, which is where the cross-OS
claims actually get tested rather than assumed.

What hasn't been exercised in CI, by design, is the set of integration tests that need outside
resources (an SMTP server for the mail commands); those are marked local-only and run on the
author's own machine. The published releases on PyPI (the 3.x line; see the
[changelog](CHANGELOG.md)) are what the gate signed off on.

## Checking it yourself

You don't have to take any of this on faith.

- The source is on [GitHub](https://github.com/bitranox/bmk), and so is the history: the
  shell-to-Python migration, the follow-up fixes and the feature releases show up as commits you
  can read in order.
- The tests live in the repository and need nothing exotic to run: `make test`, or `pytest` if
  you would rather drive it yourself.
- The architecture is not a matter of trust either. `lint-imports` enforces the layer
  boundaries, so a claim that the domain layer has no I/O is something the build checks, not
  something you have to believe.
- The pipelines are declared in one place (the stage registry), so you can see exactly which
  tool each stage runs and in what order.

If something does not line up, open an issue. That is what they are for.

## What this isn't

It isn't the tools it orchestrates, and none of them have reviewed or endorsed it: bmk drives
ruff, pyright, pytest, bandit, uv, twine and the rest, but it is a conductor, not a replacement
for any of them, and their behaviour is theirs. It isn't a hosted service or a product with a
support desk; it is a personal tool published in the open under a permissive license. And it
isn't a way to avoid understanding your own build: if you adopt it, read the bundled Makefile and
the pipeline registry so you know what runs on your code and why.

## License and attribution

The text and code here are under the MIT License (see [`LICENSE`](LICENSE)). Anthropic's terms
put ownership of model output with the user, so the human owns this and answers for it. Under the
MIT License, anyone who passes it on keeps the copyright and license notice; beyond that you are
free to use, change and redistribute it.
