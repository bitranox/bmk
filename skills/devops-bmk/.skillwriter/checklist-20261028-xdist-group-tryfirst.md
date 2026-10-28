# skill-writer checklist - devops-bmk (xdist_group from a conftest hook needs tryfirst)

Skill type: technique. Test approach: application scenario (write the conftest that keeps every
`pg_db` test on one worker and say how to confirm it), plus one quote-back.

- [x] Claim checked against real behaviour before writing it: a scratch project with 8 tests
      using one fixture, run `pytest -n 4 --dist loadgroup -v` with pytest-xdist 3.8. Hook
      without `tryfirst`: the tests ran on gw0, gw1, gw2 and gw3 with no `@g` suffix. Hook with
      `@pytest.hookimpl(tryfirst=True)`: all 8 on gw0, every node id ending in `@g`. Both runs
      green.
- [x] RED, text check on the pre-edit text (`git show HEAD:skills/devops-bmk/SKILL.md`): 0 matches
      for `tryfirst`, `hookimpl` or the `@<name>` check. Route: a text check against the skill
      file, plus one behavioural arm, because the rule is already written in this repo's own
      docs and handover, which a dispatched agent could inherit.
- [x] RED, behavioural, haiku, old paragraph: wrote `pytest_collection_modifyitems` WITHOUT
      `tryfirst` and confirmed grouping only by worker placement and a `-m xdist_group` count;
      its gaps list says "Guessed: that xdist_group markers added in
      pytest_collection_modifyitems reach xdist's scheduler".
- [x] GREEN, new paragraph, opus and haiku (2 tiers x 1 scenario): both wrote the hook with
      `@pytest.hookimpl(tryfirst=True)`, quoted the governing sentence, and checked the group
      by the `@pg_db` node-id suffix on one worker; both added a known-negative arm without
      `tryfirst`.
- [x] Gap closed: "never by a green run" next to "run `-n auto` several times" read as a
      contradiction (opus). The text now says those runs "hunt for order dependence, they never
      prove a group". Re-probe on the final text, haiku, quote-back: answered with the direct
      quote of both sentences; no new undecided gap.
- [x] Gaps declined: how `item.fixturenames` covers indirect fixture use, the fixture's scope,
      hook placement across conftest files, a test needing two groups, `--strict-markers` with
      xdist not installed (pytest and xdist behaviour, not bmk's; the paragraph is about
      ordering); how `-v` shows the worker (xdist prints `[gwN]` per line, and both GREEN arms
      read it correctly); `pytestmark` versus a hook (both are offered, the choice depends on
      the suite); a negative-control instruction (both GREEN arms added it unprompted).
- [x] GREEN against RED, both directions: RED haiku also told the reader to look for tests that
      reach the database without requesting the fixture; GREEN haiku did not. One run only, not
      re-run; the sentence that prompts it ("find those tests") is unchanged in both texts, so it
      is not displaced by this edit.
- [x] No version-history phrasing in the added lines. ASCII only. No addresses or paths added.
      No table touched.
