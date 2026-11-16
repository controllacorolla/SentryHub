# RA-CL3c — scoped cold re-audit of CL3-fix2 (`fix/cl3-evidence`, @ 4995c5c)

**Fresh session, Opus.** Auditor only, own worktree. Token budget per `README.md`. Read
`RA-CL3b-report.md` and the "CL3-fix2" section of `CL3-report.md` on the branch. Do not read
anything else the planner wrote about this fix.

1. Re-run `plan/briefs/RA-CL3b-poc/poc_ra_cl3b.py` against the new tip. B3 and N14 must now be
   fixed: update those two `DEFECT_*` tests in place to `FIXED_*` with the correct expectations
   (kill + exit with a real exit code in the engagement chain, before `engagement.close`, row
   KILLED, no session chain; N14 exit stays in the session chain). Every other test must hold.
2. Attack END (`engagement.end` → `_settle_tickets`), the core of this fix:
   - END with N bound children each running a process (one ignores SIGTERM): no engagement ticket
     row may be RUNNING or ISSUED at `engagement.close`; nothing lands in a session chain; END's
     wall time stays bounded.
   - a child SIGKILLed after spawn (never reports): END must write a `kill` (by=end) before close,
     and nothing false for tickets that did report.
   - a child redeeming a ticket at the same moment END voids it: is the final trail honest?
   - a txguard bench ticket running across END: END must not claim it killed it.
   - END while the chain cannot be verified / written: END must still complete (it is the kill path).
3. Attack the ticket→chain binding (`executor.record(chain_id=…)`, entry `"chain"`): END/START
   rollover inside the ticket TTL with the same scope (alpha ticket redeemed or still running
   under bravo); bound chain deleted or unopenable at kill/exit time (must not misfile into any
   other chain); two hubs on one DATA dir; ticket issued in a child before START.
4. `states()` change: a `refuse_ticket` for a known ticket now folds into that action's row.
   Check it cannot hide a later RUNNING/EXECUTED, and that redeem refusals stay visible.
5. Full suite once on 3.12; denial diff `ab209b7..<tip> -- tests/` (no denial weakened);
   pyflakes on touched files. No renders needed (no UI change).
6. Report `plan/briefs/RA-CL3c-report.md` on the cluster branch, PoCs in `plan/briefs/RA-CL3c-poc/`,
   push, remove the worktree. Verdict line: MERGE or DO NOT MERGE. N12/N13/N15/R1/N11 are known
   open follow-ups from RA-CL3b; re-rate them only if this fix changed them.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPy8uUaNGft7CxVmcR`
