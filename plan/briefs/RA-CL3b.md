# RA-CL3b — scoped cold re-audit of CL3-fix (`fix/cl3-evidence` @ 13c04a4+)

**Fresh session, Opus** (Mythos if available). Auditor only, own worktree. Token budget per
`README.md`. Read `RA-CL3-report.md` and the "CL3-fix" section of `CL3-report.md`.

1. Re-run your RA-CL3 PoC file (`plan/briefs/RA-CL3-poc/poc_ra_cl3.py`) against the new tip:
   every `test_DEFECT_*` for B1 B2 N1 N2 N3 N4 N5 N6 N7 N8 N10 and the H9 memory case must now
   be OK (update the file's expectations, keep it in the evidence dir).
2. Attack the new routing: a bound child across END/START/START; a child started before the
   engagement; a hub whose shared-state file names a chain id the child cannot open (must refuse,
   never fall back to a session chain for an engagement-gated action); `end()` while a child's
   process is running (kill/exit records in the right chain); two hubs' children on one DATA dir.
3. Attack the head MAC, id binding, rollback (fail the head write, fail the fsync, kill the
   writer mid-append with SIGKILL and reopen), reader/writer races with real processes.
4. H9 panel: tamper → NOT VERIFIED and rows cleared; stress rows (long targets) — is N11
   (h-scroll) acceptable as a follow-up or does it hide a state word? Render 1280×720 dark + sun.
5. Full suite once on 3.12; denial diff vs `13c04a4^`. Report on the branch as
   `RA-CL3b-report.md`, push, remove worktree. One line: MERGE / DO NOT MERGE.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
