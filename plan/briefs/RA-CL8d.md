# RA-CL8d — cold re-audit of CL8-fix3 (`fix/cl8-ship`)

**FRESH session, Opus.** Auditor only. Own worktree off `origin/fix/cl8-ship`. Read first:
`plan/briefs/RA-CL8.md`, `RA-CL8b.md`, `RA-CL8c.md` (the briefs), then `plan/briefs/RA-CL8-report.md` and
`RA-CL8b-report.md`, `RA-CL8c-report.md` on the branch. Read `plan/briefs/CL8-report.md` (sections "CL8-fix", "CL8-fix2", "CL8-fix3") only at step 3.

1. Re-run every RA-CL8, RA-CL8b and RA-CL8c PoC against the branch head. In particular:
   - Blocker 3 / NEW-A: every BABEL mode (POCSAG, AIS, RDS, ACARS, TPMS) and every PROWL sub-mode
     (SCAN, FM, NWR) live, with fake decoder binaries on PATH that record their argv: does the
     decoder start with the expected argv? With malformed settings, missing binaries, a binary
     that exits at once: is the radio ever held without a decoder, any retry storm, any silent
     "offline"? Check every `_open_pipe` / spawn call site for the stage shape.
   - NEW-C restore, NEW-D scanner, NEW-E ACARS source, C4 seen-per-row.
   - RA-CL8c NEW-G (FM respawn loop), NEW-H (SCAN early exit), NEW-I (FM missing sink), NEW-J
     (restore of net.json/headless.json), NEW-K (flat argv). Also NWR: a decoder that exits at
     once — radio held? retry storm? Any other PROWL/BABEL/ATLAS/PRISM path that respawns on a
     held radio without backing off and saying so.
2. Regressions: demo decode on every BABEL/PROWL mode; backup → restore round trip keeps
   settings, records, logbook, bingo; session log + MODE indicator.
3. `tests/test_cl8_ship.py`, then the full suite once. Diff denial/negative assertions vs `1bc8ad1`.
4. Write `plan/briefs/RA-CL8d-report.md` on `fix/cl8-ship`, push, remove the worktree. Table per
   RA-CL8 / b / c finding + the original IDs, new findings, then MERGE / DO NOT MERGE. Same
   blockers as RA-CL8. Items the CL8 report lists as follow-ups are not blockers unless they
   reach one of those.

Known baseline failures (same on main, env): `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
`test_hwlab::test_doctor_hwbench_check`, `test_shell` errors without tkinter.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALQMMsmycF1AqRUye2B`
