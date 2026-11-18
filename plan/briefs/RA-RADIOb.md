# RA-RADIOb — scoped cold re-audit of the RA-RADIO fixes, branch `claude/project-thread-z1copz`

**FRESH session, Opus.** Auditor only. Own worktree off `origin/claude/project-thread-z1copz`.
Read `CLAUDE.md`, `plan/briefs/RA-RADIO.md`, then `plan/briefs/RA-RADIO-report.md` on the branch
(verdict DO NOT MERGE, findings N1–N11), then the "RA-RADIO fixes" table at the end of
`plan/briefs/RADIO-report.md`, then the diff since the audit: `git diff fe58b1e..HEAD`.
Scope is that diff plus anything it touches.

1. Re-run every PoC in `plan/briefs/RA-RADIO-poc/` against the branch (`python3 <poc> <worktree>`).
2. Try to break each fix: N1 (does anything else spawn rtl_tcp with an undrained pipe? does the
   drain thread end when rtl_tcp exits?), N2 (every exception path in `IqWorker.run`: does the
   radio always go back, does the page always show red, does a fault loop spin the CPU or the
   arbiter?), N3, N4 (max-hold cooldown semantics vs the priority channel and lockouts), N5
   (abort during connect and during header read; FileSource / SynthSource unaffected), N6, N11
   (HOLD flag after a worker swap / engine switch), and `RtlTcpSource.drop_buffered` (can it
   discard data the scanner needed, or block?).
3. `tests/test_radio_sdrpp.py` + `tests/test_cl5_*`, then the full suite once (baseline as RA-RADIO).
4. Write `plan/briefs/RA-RADIOb-report.md` on the cluster branch, push (fetch + merge on reject,
   never force), remove the worktree. Table per N-item (CLOSED / PARTIAL / OPEN / REGRESSED),
   new findings with severity, verdict line MERGE or DO NOT MERGE. N8 is reserved for the owner.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPiZZUCc2Ni2XZf5g6`
