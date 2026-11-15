# RA-CL1c — final cold re-audit of PR #19 (`fix/cl1-screen-structure` @ c97a05b+)

**FRESH chat, Opus 5.5.** Auditor only. Own worktree
(`git worktree add ../ra-cl1c origin/fix/cl1-screen-structure`), never the shared checkout.
Token budget per `README.md`. Read `RA-CL1b-report.md` and `CL1-fix2.md`; don't read
`CL1-report.md` until step 3.

1. Re-derive and attack each CL1-fix2 item: ATLAS fits 1280×720 with no h-scroll and no clipped
   number (6-digit alt, long callsign, long ID); selection follows the item across re-sort /
   removal; PANIC unchecks BENCH ack and the TX slot/banner match the gate; PANIC tests fail when
   SIGKILL fallback / killpg are removed; every nav key shows callsign + label as visible text
   ≥16 px; RADIOS/ENGAGEMENT panels show UNKNOWN on a raising reader; ACK ALL SEEN never acks an
   alert that arrived after the drawer opened; ENG "1 target" case.
2. Regression sweep: render every page at 1280×720 dark + sun, live, plus one stress pass (DEMO,
   longest slot states). Measure rendered font sizes on the strip and ATLAS. The strip has ~1 px
   spare: confirm nothing overflows in any theme/state, including with an alert badge showing.
3. Read `CL1-report.md`; check each claim. Confirm the two retired/updated tests match owner
   decisions and nothing else was weakened.
4. Write `plan/briefs/RA-CL1c-report.md` on the branch, commit, push, no PR. Table + one line:
   MERGE / DO NOT MERGE. Medium-or-lower findings that don't affect what an operator reads
   should be listed as follow-ups, not blockers. Remove your worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
