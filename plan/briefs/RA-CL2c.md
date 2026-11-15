# RA-CL2c — final cold re-audit of CL2 (`fix/cl2-gates` @ 35ba0ef+)

**FRESH chat.** Mythos; on a safeguard block `/model claude-opus-5-5` and continue. Auditor only.
Own worktree (`git worktree add ../ra-cl2c origin/fix/cl2-gates`), never the shared checkout.
Token budget per `README.md`. Read `RA-CL2b-report.md` and `CL2-fix2.md`; don't read
`CL2-report.md` until step 3.

Owner decisions since the brief: digimodes stays refused until CL8 retires it; SSH without
ProxyJump is accepted for v0.1.

1. Attack R1 (program allowlist, shell/interpreter/wrapper refusal, path refusal, SSH self-target
   refusal after resolution incl. IPv6, IPv4-mapped, 0.0.0.0, link-local, a hostname that resolves
   to this device, a failed interface listing), R2 (17-test mutation catch), R4, R5 (label-only
   in trail + ticket + UI), R6 (frequency binding: every argv form you can think of).
2. Regression sweep across the whole CL2 surface: re-run the RA-CL2 and RA-CL2b PoC sets
   (`RA-CL2-evidence/`, `RA-CL2b` evidence); everything previously closed stays closed. Diff
   denial assertions vs `main` and vs `18770be`.
3. Read `CL2-report.md`; check every claim.
4. Write `plan/briefs/RA-CL2c-report.md` on the branch, commit, push, no PR. Table + one line
   MERGE / DO NOT MERGE. A bypass to emission or a weakened denial blocks; hygiene does not —
   list it as follow-up. Remove your worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
