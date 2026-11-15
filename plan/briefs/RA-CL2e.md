# RA-CL2e — scoped cold re-audit of CL2-fix4 (`fix/cl2-gates`, after f44d1b7)

**Fresh session.** Auditor only, own worktree (`git worktree add ../wt-RA-CL2e origin/fix/cl2-gates`).
Read `RA-CL2d-report.md` and the "CL2-fix4" section at the end of `CL2-report.md`. Token budget per
`README.md`.

1. Attack D1: every way to get a shell metacharacter, quote, `$`, backtick, redirect, newline, or
   a 16+-char / non-interface scope id through `_self_target` → `authorize_ssh_host` → the
   terminal launch and `prepare_ssh`. Confirm `_terminal_argv` for xterm has argc > 1 after `-e`
   (so xterm execs ssh, no `$SHELL -c`), and that the lxterminal string survives
   `g_shell_parse_argv`-style splitting unchanged. If xterm can be installed on the Mac (brew),
   run the real RA PoC host against it; otherwise say it was not run.
2. D2/D3: `64:ff9b:1::/48` with loopback / own / foreign IPv4; `ssh -G` on a scoped HostName.
3. Regression: `tests/test_cl2_*.py` + full suite once on Python 3.12; re-run the RA-CL2c and
   RA-CL2d PoC sets; diff denial assertions vs `f44d1b7`.
4. Write `plan/briefs/RA-CL2e-report.md` on the branch, push, remove the worktree. One line:
   MERGE / DO NOT MERGE. Only a bypass to execution on this device or to emission, or a weakened
   denial, blocks.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
