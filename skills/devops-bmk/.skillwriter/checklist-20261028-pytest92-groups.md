# skill-writer checklist - devops-bmk (pytest 9.2.0 with pytest-xdist 3.8.0 drops every group)

Skill type: reference (a version interaction and what bmk does about it). Test approach:
application scenario (make test turns serial after a relock; a colleague proposes deleting the
marks or forcing `-n auto` in addopts), plus one quote-back on the final text.

- [x] Claim checked against real behaviour before writing it: scratch venvs with pytest 9.1.1
      and 9.2.0, both with pytest-xdist 3.8.0, three arms (conftest hook without `tryfirst`,
      with `tryfirst`, module `pytestmark`). On 9.2.0 every arm spread over gw0..gw3 with no
      `@<name>` suffix, `pytestmark` included; on 9.1.1 the `tryfirst` and `pytestmark` arms
      held the group. Cause read in the source: xdist `remote.py` assigns `item._nodeid`,
      pytest 9.2.0 builds `nodeid` from `_id`. The guard's probe was run against both venvs
      (local_only e2e test) and answers groups_ignored on 9.2.0 only.
- [x] RED, text check on the pre-edit text (`git show HEAD:skills/devops-bmk/SKILL.md`): 0 matches
      for `9.2` or `#1386`.
- [x] RED, behavioural, haiku, old paragraph, symptom given (module `pytestmark` spread over
      four workers on pytest 9.2.0): could not name a cause ("the excerpt names no cause"),
      suggested comparing venvs and reading changelogs.
- [x] GREEN, new paragraph, opus and haiku (2 tiers x 1 scenario): both kept the marks, rejected
      `-n auto` in addopts and named `pytest<9.2` or a fixed pytest-xdist release, quoting the
      new sentence; both checked the result by the `@db` node-id suffix.
- [x] Gaps closed: what bmk does with a project's own `-n` (both arms: NONE) - the text now says
      bmk adds `-n 0` over it, pinned by
      `test_a_dropped_group_overrides_the_projects_own_workers_with_n_0`; which release ends it
      and whether the cap is too broad (opus) - the text now says the check reads installed code,
      not versions, so a pytest-xdist release newer than 3.8.0 with the fix lifts it; "relock"
      added next to the dev-extra cap (haiku).
- [x] Gaps declined: whether a cap needs the user's sign-off and whether the project needs
      pytest 9.2 features (project decisions, not bmk's); the exact fixed xdist version (none is
      released; issue #1386 is named for tracking).
- [x] Quote-back on the final text, haiku: answered one process for a project `-n 4` (`-n 0`
      over it), no bmk setting change after a fixed xdist plus relock, keep the marks - each with
      the direct quote. Remaining gaps declined: which tests collide (the project's), the exact
      detection mechanism (a reader needs the outcome, not the probe). Gap closed: whether the
      stderr line shows in JSON mode - checked in `stagerunner/output.py`: the coverage stage is a
      subprocess ToolAction whose stdout and stderr go to `CapturingSink`, shown only on failure,
      so the text now says "(shown in JSON mode only when the stage fails)", the wording the
      install hint already uses.
- [x] No version-history phrasing in the added lines. ASCII only. No addresses or paths added.
      No table touched.
