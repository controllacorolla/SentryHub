# RA-RADIO — cold audit of the radio cluster (PRISM SDR++ receiver + PROWL scanner)

**FRESH session, Opus.** Auditor only. Own worktree off `origin/claude/project-thread-z1copz`.
Read `CLAUDE.md`, `plan/briefs/device-fix-plan.md` items 14 and 15, `plan/briefs/device-notes.md`
sections PRISM and PROWL, then `plan/briefs/RADIO-report.md` on the branch, then the diff:
`git diff origin/main...origin/claude/project-thread-z1copz`.

Try to break each claim; the report's coverage table is the implementer's view, not evidence.
1. **Radio ownership.** `palisade_qt/iqworker.py` `IqWorker._ensure_radio` / `_open` / close path vs
   `palisade_qt/radio_arbiter.py` and the existing SDR workers. rtl_tcp must start only when HELD,
   give-back must kill rtl_tcp before release, revoke mid-read must not leave a process or a lease.
   File / demo sources must not take the radio. Arbiter tests in `tests/test_cl5_*` still pass.
2. **rtl_tcp safety.** `iqsource.rtl_tcp_argv` binds 127.0.0.1 only; no shell; a dead rtl_tcp is a
   SourceError, not a hang; the socket reader cannot block the GUI thread.
3. **DSP honesty.** Every mode in `dsp.MODES` really demodulates (re-run
   `test_every_demod_mode_recovers_the_audio`, and try an off-centre SSB pair); squelch level is
   channel power; bandwidth clamps; RAW is described as mono.
4. **Scanner.** `FastScanWorker`: stream-time clock, resume delay, max hold, lockouts never stop,
   priority preempts, HOLD freezes, live changes from the page reach the worker. CLASSIC engine
   (`ScanWorker`) behaviour unchanged except the bank / timing / lockout inputs.
5. **UI.** PRISM and PROWL pages at 1280×720 (fit inside the content area with a 128 px left rail),
   dark + sun. START/STOP and SCAN/HOLD run-state colours. Bookmarks, settings and per-bank values
   persist under `uconsole-suite` only. Bad JSON in `prism.json` / `prowl_scan.json` cannot crash.
6. **Recording.** Paths under `suite.DATA/recordings`, free-space guard, files valid, IQ plays back.
7. `tests/test_radio_sdrpp.py`, then the full suite once
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`). Baseline failures in this
   container: test_shell (no tkinter), test_audit_tiles, test_hwlab doctor, flaky
   test_cl1_fix2 ack_all, test_sstvdec (skyfield).
8. Write `plan/briefs/RA-RADIO-report.md` on the cluster branch, push (fetch + merge on reject,
   never force), remove the worktree. Table per area, new findings with severity, verdict line
   MERGE or DO NOT MERGE.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPiZZUCc2Ni2XZf5g6`
