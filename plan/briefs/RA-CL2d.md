# RA-CL2d — scoped cold re-audit of CL2-fix3 (`fix/cl2-gates`, after 488f31e)

**Fresh session.** Auditor only, own worktree (`git worktree add ../wt-RA-CL2d origin/fix/cl2-gates`).
Read `RA-CL2c-report.md` and the "CL2-fix3" section at the end of `CL2-report.md`.
Token budget per `README.md`.

1. Attack C1 with real OpenSSH on the Mac (`ssh -G`, and the `-F` + `Match exec` marker test from
   RA-CL2c, target unreachable): any way for operator text in host or command to be parsed as an
   ssh option, or to run a program on this device. Try `--` tricks, `-` after whitespace, unicode
   dashes, a command of `--`, newline/CR inside the command, a host token with `%`, `@`, `:`.
2. Attack C2/C3: scoped own link-local by literal and by name; `::/96`, `::ffff:0:0:0/96`,
   `64:ff9b::/96` with loopback / own / foreign IPv4; `::ffff:127.0.0.1`; confirm a real NAT64
   remote passes. Verify `own_addresses()` on the Mac returns scoped and unscoped forms correctly.
3. Attack C4: control bytes anywhere in a Flipper payload; confirm plain reads are still non-RF.
4. Regression: run `tests/test_cl2_*.py` and the full suite once on Python 3.12; re-run the
   RA-CL2c PoC set; diff denial assertions vs `488f31e`.
5. Write `plan/briefs/RA-CL2d-report.md` on the branch, push, remove the worktree. One line:
   MERGE / DO NOT MERGE. Only a bypass to execution on this device or to emission, or a weakened
   denial, blocks; everything else is a follow-up.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
