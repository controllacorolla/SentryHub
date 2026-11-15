# CL2-fix2 — close RA-CL2b

**Branch:** `fix/cl2-gates` @ `18770be`. Own worktree (`git worktree add ../cl2fix2 origin/fix/cl2-gates`),
never the shared checkout. Read `plan/briefs/RA-CL2b-report.md`. Token budget per `README.md`.
Same rules: fail closed, PoC test fails first, no real emission, never loosen a gate.

## Owner decisions (2026-11-15)

- **R1 — replace the transmitter blocklist with an allowlist.** Each engagement-gated module
  declares the exact programs it may run (`ALLOWED_PROGRAMS`, basename, argv[0] only). The
  engagement gate refuses any argv whose argv[0] is not in the caller's set, and any argv[0]
  that is a shell, interpreter or wrapper (`sh bash zsh dash env sudo doas python* perl ruby
  node busybox xargs nohup timeout stdbuf`). `rfemit.is_sdr_tx` stays as defence in depth.
- **R1 — DEVTERM SSH remote commands** are remote execution on another host: allowed, label-only,
  NOT subject to the suite's hard lock (the suite's radios are not involved). But **refuse any
  SSH target that is this device**: loopback (127.0.0.0/8, ::1), `localhost`, and every address
  on this device's own interfaces, checked after resolution. Test: the RA PoC
  (`127.0.0.1` + `hackrf_trans''fer`) is refused at issue.
- **R5 — keep** the three unbindable Proxmark writes allowed and marked label-only (consistent
  with G5). No change beyond confirming the label in UI + trail.

## Fix

- **R1** as above. Tests: every RA bypass (quoting, globs, `${var}`, `python -c`, renamed
  binary, `tune`, `tx_waveforms`, `urh_cli`) refused through the engagement gate; each shipped
  module's real commands still issue.
- **R2** restore the 4 weakened tests: arm + unlock first, then assert the **scope** refusal
  reason. Re-run the RA mutation (everything in scope) and show it is caught by ≥ 17 tests.
- **R4** Flipper `input` (and any verb that can drive a radio app: `input`, `loader`, `js`,
  `subghz`, `nfc`, `rfid`, `bt`) is an emitter under the hard lock. Remove `input` from
  `FLIPPER_NON_RF`. Test.
- **R6** `txguard.issue_ticket` checks that the argv's frequency (`-f` for hackrf_transfer, and
  the equivalent for each TX tool it issues for) equals the authorized `freq_hz`; refuse
  otherwise, and refuse when it cannot parse it. Test with the RA PoC (1090 argv vs 915 auth).
- Report: correct the false "no denial weakened" line in `CL2-report.md`.

## Done means

Suite + pyflakes pasted for real, `CL2-report.md` appended, pushed, no PR, worktree removed.
Stop: RA-CL2c (fresh chat, scoped to R1 R2 R4 R6) decides the merge.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
