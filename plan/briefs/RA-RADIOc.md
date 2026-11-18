# RA-RADIOc — scoped cold re-audit of the RA-RADIOb fixes, branch `claude/project-thread-z1copz`

**FRESH session, Opus.** Auditor only. Own worktree off `origin/claude/project-thread-z1copz`.
Read `CLAUDE.md`, `plan/briefs/RA-RADIO.md`, then `plan/briefs/RA-RADIOb-report.md` on the branch
(verdict DO NOT MERGE, findings B1–B7 and N2 partial), then the "RA-RADIOb fixes" table at the end of
`plan/briefs/RADIO-report.md`, then the diff since the audit: `git diff 77f9783..HEAD`.
Scope is that diff plus anything it touches.

1. Re-run every PoC in `plan/briefs/RA-RADIO-poc/` and `plan/briefs/RA-RADIOb-poc/` against the branch (`python3 <poc> <worktree>`).
2. Try to break each fix: B1 (I/Q alignment after `drop_buffered` with any carry / split /
   partial recv; any other path that drops bytes), B2 (radio never held while faulted and idle;
   back-off resets only after a good block; PANIC / revoke during back-off), B3 / N2 (every
   exception path in `IqWorker._open` / `run` / `on_source_opened` / `_apply`; PRISM START on a
   finished worker; PROWL Enter on a finished FAST scanner; no double worker on the radio), B4–B7.
3. `tests/test_radio_sdrpp.py` + `tests/test_cl5_*`, then the full suite once (baseline as RA-RADIO).
4. Write `plan/briefs/RA-RADIOc-report.md` on the cluster branch, push (fetch + merge on reject,
   never force), remove the worktree. Table per B-item and N2 (CLOSED / PARTIAL / OPEN / REGRESSED),
   new findings with severity, verdict line MERGE or DO NOT MERGE. N8 is reserved for the owner.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPiZZUCc2Ni2XZf5g6`
