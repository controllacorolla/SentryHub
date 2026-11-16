# RA-CL8b — cold re-audit of CL8-fix (`fix/cl8-ship`)

**FRESH session, Opus.** Auditor only. Own worktree off `origin/fix/cl8-ship`. Read first:
`plan/briefs/RA-CL8.md` (the brief), `plan/briefs/RA-CL8-report.md` (DO NOT MERGE, 4 blockers),
then the audit PDF §§ it cites. Read `plan/briefs/CL8-report.md` (section "CL8-fix") only at step 3.

1. Re-run every RA-CL8 PoC against the branch head:
   - Blocker 1: `scout.wifi_scan('bash -c id>…')` and any other way a settings value picks a
     program. Sweep every Tk and Qt module for a settings value that reaches argv[0] or adds
     options (not only `sh -c`).
   - Blocker 2: every template in `signals` (rtl_433, acarsdec, dumpvdl2): any output to a host,
     a file, a config file, a remote device (`-d rtl_tcp:`, soapy `driver=remote`)? Check the
     real option sets of those programs (man pages / `--help` text), not only the PoCs.
   - Blocker 3: malformed types in every settings file BABEL/PROWL read (signals, tpms, pager,
     rds, ais, nwr, fm): is the radio ever held, any retry storm, any silent "offline"?
   - Blocker 4: `harden.sh` with stubs only (never for real): fail every sudo step in turn in
     `--field`, `--revert` and HOME. Can ufw end up off or inbound open?
   - The non-blocking RA-CL8 items listed as fixed in the CL8-fix table.
2. Regressions: the shipped default templates and the old-default migration must still build;
   BABEL/PROWL still decode in demo; session log/indicator; Tk hub grid (no dead tiles).
3. `tests/test_cl8_ship.py`, then the full suite once (`QT_QPA_PLATFORM=offscreen xvfb-run -a
   python3 -m pytest -q tests`). Diff denial/negative assertions vs `1bc8ad1`.
4. Write `plan/briefs/RA-CL8b-report.md` on `fix/cl8-ship`, push, remove the worktree. Table per
   RA-CL8 finding + the original IDs (L4 C1 L3 L2 L6 S1 S4 C4 C5 P1 P2 P3 B4 B5 B6 E6), new
   findings, then MERGE / DO NOT MERGE. Same blockers as RA-CL8. The follow-ups the CL8 report
   lists as not fixed are not blockers unless they reach one of those.

Known baseline failures (same on main, env): `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
`test_hwlab::test_doctor_hwbench_check`, `test_shell` errors without tkinter.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALQMMsmycF1AqRUye2B`
