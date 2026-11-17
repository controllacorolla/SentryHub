# RA-RXb — cold audit of RX (RECON NET + Wi-Fi execution), branch `claude/project-thread-st3z1x`

**FRESH session, Opus.** Auditor only. Own worktree
(`git worktree add ../wt-RA-RXb origin/claude/project-thread-st3z1x`). Token budget per `README.md`.
Read `plan/briefs/RX-report.md` on the branch only at step 4. This is round 2: first re-verify every finding of `plan/briefs/RA-RX-report.md` (on the branch) — H1 (nmap given non-literal targets / resolving), M1 (unbounded line growth, GUI freeze), L1-L4 — as CLOSED / OPEN / PARTIAL with evidence, then run the checks below fresh.

Owner decision 2026-11-17: authorized RECON NET (netpent/nmap) and RECON Wi-Fi (wifipent) actions
must really run, through executor.py, with output in a pane on the RECON page, spawn/exit in the
evidence chain, END/PANIC kill under the N16 orphan rule (pid+start-time match only; mismatch =
UNCONFIRMED). Everything stays behind engagement.py / opprofile.py scope checks. BLEPENT, PASSAUDIT,
FORGE stay authorize-only. TX / txguard must not be touched.

Scope: diff `origin/main...origin/claude/project-thread-st3z1x` (palisade_qt/runpane.py new,
palisade_qt/recon.py, netpent.py, wifipent.py, executor.py (RX-fix M1: `_lines()` bounded reader only), install_head.sh, tests/test_rx_recon_exec.py,
tests/test_netpent.py). engagement.py, chain.py, txguard.py, rfemit.py, opprofile.py
must be byte-identical to main; executor.py may differ ONLY in the bounded output reader (verify that).

1. Reproduce on main: open an engagement, authorize a NETPENT portscan in RECON → nothing spawns.
   On the branch → the (substituted) process spawns, output streams, chain has spawn + exit.
2. Attack the gate path:
   - Can any RECON path reach `executor.start` / `subprocess` without a ticket from `prepare()`,
     or with a target outside scope (CIDR edges, hostnames that resolve partly out of scope, IPv6,
     ranges, leading `-`, whitespace)? Is the refusal before any spawn and before any `issue`?
   - Can the new IFACE / CH / CLIENT / capture-path inputs inject an option or path into argv, or
     change which program runs? Does the `-sT`/`-sS` choice alter anything but the scan type?
   - Does a ticket from one engagement run under another (END + START between authorize and run)?
   - BLEPENT / PASSAUDIT: can either now spawn anything?
3. Kill + evidence: with a long-running process started from RECON, check END, PANIC (real hub
   `panic()`), STOP and closing RECON each kill the whole process group (including a child that
   ignores SIGTERM) and record kill/exit (or UNCONFIRMED) in the engagement chain before
   `engagement.close`. Check a process whose output never ends a line, and one that floods output,
   does not freeze the GUI thread or lose the exit. Check the reader-thread → GUI handoff is a
   queued signal (no widget touched off the GUI thread).
4. Honesty: missing binary, absent interface, non-root failure — does the UI say exactly what
   happened (no RUNNING after exit, no phantom spawn record)? Render RECON NET and WIFI at
   1280×720, dark + sun, live.
5. Regression: `tests/test_rx_recon_exec.py`, then the full suite once
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`). Known baseline failures:
   see PLANNER-HANDOFF (no tkinter → test_shell errors; test_audit_tiles, test_hwlab doctor, flaky
   test_cl1_fix2 alerts). Diff assertions in `tests/` against main; justify any weakened one.
6. Write `plan/briefs/RA-RXb-report.md` on `claude/project-thread-st3z1x`, push, remove the
   worktree. Table per check, new findings with severity, then one line: MERGE / DO NOT MERGE.
   Blockers: any gate weakened or bypassed, an out-of-scope spawn, a kill not recorded, a gate file
   changed, BLE/PASSAUDIT/FORGE executing.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPJu1qqfsrSC3ybghd`
