# RA-CL3d — scoped cold re-audit of CL3-fix3 (`fix/cl3-evidence`, @ e5a0e54)

**Fresh session, Opus.** Auditor only, own worktree. Token budget per `README.md`. Read
`RA-CL3c-report.md` and the "CL3-fix3" section of `CL3-report.md` on the branch. Do not read
anything else the planner wrote about this fix.

1. Re-run `plan/briefs/RA-CL3c-poc/poc_ra_cl3c.py` and `RA-CL3b-poc/poc_ra_cl3b.py` against the tip.
   N16/N17/N18/N19 `DEFECT_*` tests must now be fixed: update them in place to `FIXED_*` with the
   correct expectations. `test_OK_stopped_child_misses_rollover_…` changes by owner decision (END now
   kills a matching orphan, see the report): update it, and check the new trail is honest.
2. Attack the owner-decided orphan kill (`engagement._same_process`, `_kill_orphan`,
   `_settle_tickets`). Owner rule: kill ONLY when pid + start time match the spawn record; record
   `kill` "orphan at END" only when verified gone; otherwise `unconfirmed`, never KILLED.
   - recycled pid (start time differs), pid 0/1/own pid/own group, a forged or missing `pstart`,
     a non-int pid in the record: END must send no signal.
   - a record forged into the chain by someone WITH the key naming another of the user's processes
     with its real start time: what can END be made to kill? Rate it; say if the HMAC key
     boundary already covers it.
   - the orphan's group: gated processes lead their own group — does END ever signal a group it
     should not (the hub's own, a child's)?
   - a process that ignores SIGTERM, one that survives SIGKILL (stopped/uninterruptible), a
     zombie, a child that reports its exit during the kill: is every resulting record true?
   - END wall time with several orphans; END must still complete if any step raises.
   - macOS path (`_darwin_start`, `ps`-based zombie check): review by reading; say what you
     could not run.
3. `Chain.record(_only_if=…)`: predicate under `LOCK_EX`; can a skipped record, an exception in
   the predicate, or a concurrent writer break the chain or the rollback (N3) path?
4. `states()`: `unconfirmed` and the refusal-only-on-unused rule — can either hide a real outcome?
5. Full suite once on 3.12; denial diff `4954cdf..<tip> -- tests/` (no denial weakened);
   pyflakes on touched files. No renders needed.
6. Report `plan/briefs/RA-CL3d-report.md` on the cluster branch, PoCs in `plan/briefs/RA-CL3d-poc/`,
   push (on rejection: fetch + merge, never force), remove the worktree. Verdict line: MERGE or DO
   NOT MERGE. N12/N13/N15/R1/N11 remain known open follow-ups; re-rate only if changed.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPy8uUaNGft7CxVmcR`
