# RA-RXd — narrow cold audit of RX-fix3 (`claude/project-thread-st3z1x`)

**FRESH session, Opus.** Auditor only. Own worktree (`git worktree add ../wt-RA-RXd
origin/claude/project-thread-st3z1x`); commit only there. Scope is ONLY the diff since RA-RXc:
`git diff 62c938a..HEAD -- netpent.py palisade_qt/recon.py palisade_qt/runpane.py tests/`.
Read `plan/briefs/RA-RXc-report.md` (on the branch) first.

1. Verify RA-RXc N4, N5, N6 and RA-RXb N2 are CLOSED (or not) with evidence; each needs its
   regression test.
2. Attack the diff: can the N5 captures check be bypassed (symlinks in DATA/captures, `..`,
   relative paths, trailing slash, a captures dir that is itself a symlink) or refuse the paths
   RECON really builds? Does `_unique` keep the old naming readable? Did anything in the diff change
   which program runs, the scope check, or a kill/record path? Gate files must still be
   byte-identical to main (executor.py: only the bounded reader).
3. Run `tests/test_rx_recon_exec.py tests/test_netpent.py tests/test_palisade_qt.py`, then the full
   suite once (baseline: test_audit_tiles, test_hwlab doctor, test_shell without tkinter).
   With /usr/bin/nmap, run the real RECON path against loopback once and confirm the results file.
4. Write `plan/briefs/RA-RXd-report.md` on the branch, push at once, remove the worktree. Table,
   findings with severity, then MERGE / DO NOT MERGE.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPJu1qqfsrSC3ybghd`
