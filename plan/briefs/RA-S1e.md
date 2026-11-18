# RA-S1e — targeted cold re-audit of the RA-S1d fix, branch `fix/shell-frame` (PR #33)

**FRESH session, Opus.** Auditor only: a report, not fixes. Own worktree off `origin/fix/shell-frame`.
Read `CLAUDE.md` and `plan/briefs/RA-S1d-report.md` (N12-N15) on that branch.
Scope: `git diff 337b91a..origin/fix/shell-frame -- palisade_qt tests` (`PageNotice.consider` and
`_show_keys`).

- **N12**: the notice only says what the page reports now. Re-run the RA-S1d PoCs live (RECON WIFI ->
  BLE sub-tab within 7 s; ATLAS NO FEED -> STALE; FIRST cleared when SECOND arrives). Does a line whose
  warning cleared go without a new warning arriving? Does the notice hide when nothing it showed is
  reported any more?
- **N13**: lines bounded by status keys.
- Regressions: F2 (ticking counter silent: note the text now updates in place, without a re-show or
  timer restart — is that right?), N1, N2 (panel hold-back + retry), N3/N10 (60 s reminder), N6
  (ATLAS layer counts), N8 (timers stop on close), `show_all` (page name click / palette) unaffected.
- UI-only; lifecycle.
Run `tests/test_shell_frame.py` and `tests/test_cl1_fix3.py`, one file per process
(`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q --timeout=240 --timeout-method=thread`).
No full suite.

Write `plan/briefs/RA-S1e-report.md` on `fix/shell-frame`: a table, new findings with severity and a
PoC, then MERGE / DO NOT MERGE. Only a Medium or worse blocks; list Lows that are judgement calls for
Dalton. Push (fetch + merge on reject, never force), remove the worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
