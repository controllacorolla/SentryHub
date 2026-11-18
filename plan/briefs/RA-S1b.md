# RA-S1b — cold re-audit of the RA-S1 fixes, branch `fix/shell-frame` (PR #33)

**FRESH session, Opus.** Auditor only: you write a report, not fixes. Own worktree off
`origin/fix/shell-frame`. Read `CLAUDE.md`, `plan/briefs/RA-S1-report.md` (on that branch: the
findings F0-F13), the "Device run 2" section of `plan/briefs/device-notes.md` (Dalton's own words),
and Stage 1 items 1-6 and 26 of `plan/briefs/device-fix-plan.md`.
Scope: `git diff 91275a1..origin/fix/shell-frame -- palisade_qt tests` (the fix commit), plus any
regression it causes elsewhere in the Stage 1 diff (`origin/fix/ui-polish..origin/fix/shell-frame`).

For each finding, decide fixed / partly / not fixed, with evidence, and try to break the fix:

- **F0** `test_eight_keys_in_order_with_function_labels` now expects SYSTEM last. Is the test still a
  real check (not just relaxed)?
- **F1** `LiveStatusWorker.PAUSE_WHEN_HIDDEN = False`: BAT and SDR presence update while OPS is off
  screen. Cost: does it now poll while the window is minimized or after close? Stopped on close?
- **F2/F4** `PageNotice` dedupes by (key, state), re-arms when a warning clears, escalation shows.
  Does a warning whose text carries a live counter still re-show every tick? Can two pages' notices
  pile up? Is a real new warning ever swallowed?
- **F3** notice hidden on page change; lines prefixed with the page name. Does returning to the
  page re-show a still-active warning, or is it lost until it clears and returns?
- **F5** SUN and DARK sub-tab focus rule and nav-key focus border. Render SUN, LIGHT, DARK at
  1280x720 and look: focus visible on open and closed tiles, nav key focus visible.
- **F7** disabled volume: dashed/transparent handle. Render it enabled vs disabled, confirm a visible
  difference.
- **F8** notice blocked while a drawer/palette/overlay is open (`_panel_open`). Every overlay kind?
  Does it show once the panel closes?
- **F9** palette command "Page messages". Reachable by keyboard only; lists the current page's
  messages; empty state honest.
- **F10** docstrings. **F11** dark `sub_bg` contrast: open vs closed vs page tile distinguishable?
- **F6** (BENCH TX not on `set_run`) and the ATLAS-views part of F11 are left for Dalton by design:
  confirm nothing changed there, do not fail on them.

Also: UI-only (no data, decoding or radio behaviour change); everything connected is disconnected on
close. Run `tests/test_shell_frame.py`, `tests/test_cl1_screen.py`, `tests/test_cl1_fix3.py`,
`tests/test_ui_polish.py` (`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q
--timeout=240 --timeout-method=thread`). Do not run the full suite; the thread does.

Write `plan/briefs/RA-S1b-report.md` on `fix/shell-frame`: a table per finding, new findings with
severity and a PoC, then MERGE / DO NOT MERGE. Push (fetch + merge on reject, never force), remove
the worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
