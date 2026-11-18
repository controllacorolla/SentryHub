# RA-RADIOd — scoped cold re-audit of the RA-RADIOc follow-ups, branch `claude/project-thread-z1copz`

**FRESH session, Opus.** Auditor only. Own worktree off `origin/claude/project-thread-z1copz`.
Read `CLAUDE.md`, `plan/briefs/RA-RADIOc-report.md` on the branch (verdict MERGE, follow-ups
C1–C4, B6/B7 test pins), then the last table of `plan/briefs/RADIO-report.md`, then the diff since
that audit: `git diff 2f5347d..HEAD`. Scope is that diff only; keep it short.

1. Re-run `plan/briefs/RA-RADIOc-poc/` PoCs (and the mutation script) against the branch.
2. Try to break: `retry_now()` from the GUI thread vs the worker thread (any race that opens
   two sources or takes the radio while the page is hidden / held off); PROWL Enter order (held
   off, finished, faulted, hold); the re-queue rule (source failures only); cancel-path close.
   Confirm the B6 / B7 / C-tests fail with their fix removed.
3. `tests/test_radio_sdrpp.py` + `tests/test_cl5_*` once. Full suite only if the diff reaches
   beyond `palisade_qt/iqworker.py`, `prism.py`, `prowl.py`, `iqsource.py` and the tests.
4. Write `plan/briefs/RA-RADIOd-report.md` on the cluster branch, push (fetch + merge on reject,
   never force), remove the worktree. Table per item, new findings with severity, verdict line
   MERGE or DO NOT MERGE.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPiZZUCc2Ni2XZf5g6`
