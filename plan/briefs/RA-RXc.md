# RA-RXc — cold audit of RX round 3 (`claude/project-thread-st3z1x`)

**FRESH session, Opus.** Auditor only. Own worktree
(`git worktree add ../wt-RA-RXc origin/claude/project-thread-st3z1x`) — do NOT commit from any
other checkout. Token budget per `README.md`. Context: `plan/briefs/RA-RX.md` (scope, owner
decision) and `plan/briefs/RA-RXb-report.md` on the branch (round 2: MERGE with N1-N3).

Since RA-RXb (da8cdd4): main (CL8, SCAN, toolkit #28) was merged in, then RX-fix2 (e3d9545+):
nmap results saved via `-oN` under `<DATA>/captures`, IPv6 `-6`, mixed-family refusal, single-word
name refusal text, NOTHING SCANNED state. Read `plan/briefs/RX-report.md` (RX-fix2 section) only at
step 4.

1. Merge sanity: `git diff origin/main...HEAD` must contain only RX's files. engagement.py,
   chain.py, txguard.py, rfemit.py, opprofile.py byte-identical to main; executor.py differs only in
   the bounded output reader. Did the merge drop or duplicate anything in recon.py (SCAN's live
   Wi-Fi/BLE scans must still work) or install_head.sh?
2. Attack RX-fix2: can the `-oN` path, its directory, or the `-6`/family logic inject an option,
   write outside `<DATA>/captures`, change which program runs, or let an out-of-scope address
   through (dual-stack names, IPv4-mapped IPv6 `::ffff:a.b.c.d`, scoped `fe80::1%wlan0`, v6 ranges)?
   Is the saved-file claim honest (file exists, is the one nmap wrote)?
3. Re-verify RA-RXb N1 (IPv6) and the round-1/2 CLOSED items still hold after the main merge (H1,
   M1, kill paths END/PANIC/STOP/close with chain records, out-of-scope refusal before spawn).
   If nmap is installable here, run the real RECON path against loopback once.
4. Regression: `tests/test_rx_recon_exec.py`, then the full suite once. Known baseline failures:
   test_audit_tiles, test_hwlab doctor, test_shell (no tkinter), order-dependent
   test_cl1_screen up/down. Diff assertions in tests/ against main; justify any weakened one.
5. Write `plan/briefs/RA-RXc-report.md` on the branch, push as soon as written (the container can
   restart), remove your worktree. Table per check, findings with severity, then MERGE / DO NOT
   MERGE. Blockers: gate weakened, out-of-scope spawn, unrecorded kill, a write outside captures,
   SCAN or toolkit behaviour from main lost in the merge.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPJu1qqfsrSC3ybghd`
