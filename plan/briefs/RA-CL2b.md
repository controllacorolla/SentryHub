# RA-CL2b — cold re-audit of CL2-fix (`fix/cl2-gates` @ 2e83105+)

**FRESH chat, Opus 5.5.** Auditor only, no fixes. Work in **your own git worktree**
(`git worktree add ../ra-cl2b origin/fix/cl2-gates`) — never the shared checkout (CL1-fix2 is
using it). Token budget per `README.md`. Don't read `CL2-report.md` until step 3.

1. Read `plan/briefs/RA-CL2-report.md` (N1–N9) and `plan/briefs/CL2-fix.md`.
2. Re-derive every N1–N9 PoC yourself and try to break each fix:
   - **N1** get an SDR transmitter ticket from any non-txguard gate: aliases, symlinks, `env`,
     `python -c`, `bash -c` with quoting, unicode look-alikes, a renamed binary path, payload
     tickets to a serial device that runs a TX command.
   - **N2** every emitter class refused at issue and at spawn under `SUITE_TX_LOCK` and disarm;
     disarm kills a running one; find an RF emitter `rfemit.py` misses (default is non-RF for
     unknown programs: list any real emitter that slips through).
   - **N3** recycled pid, crash-stale file, other hub, forged nonce; read the Linux start-time
     path (`/proc/<pid>/stat`) by code review and say plainly it is unverified on Linux.
   - **N4** + the Proxmark `;` command-injection fix: out-of-scope emulated ID, chained commands.
   - **N5 N6 N8 N9a** as stated.
3. Read `CL2-report.md`; check every claim; confirm no denial assertion was weakened vs `main`
   and vs `211fa0c` (the tests that now arm first: check each still asserts the refusal path).
4. Write `plan/briefs/RA-CL2b-report.md` on `fix/cl2-gates`, commit, push, no PR. Table per item,
   new findings by severity, one line MERGE / DO NOT MERGE. Remove your worktree after.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
