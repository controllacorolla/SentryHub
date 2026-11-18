# RA-S1 — cold audit of device-run-2 Stage 1 (frame and shell), branch `fix/shell-frame` (PR #33)

**FRESH session, Opus.** Auditor only: you write a report, not fixes. Own worktree off
`origin/fix/shell-frame`. Read `CLAUDE.md`, then `plan/briefs/device-fix-plan.md` (Stage 1 items 1–6
and 26) and the "Device run 2" section of `plan/briefs/device-notes.md` (Dalton's own words).
Scope: `git diff origin/fix/ui-polish..origin/fix/shell-frame -- palisade_qt tests`.

The bar is Dalton's notes, not the plan's wording. For each item, decide whether what he will see on
a 1280x720 uConsole screen answers what he wrote. Try to break each item:

1. **Window (1).** `shell.PageStack` and `show_fitted`. Can any page, sub-tab, the F toggle (ATLAS,
   OPS, MESH), a side panel, a long label, a notice or a drawer still push the window past 1280x720
   or knock it out of maximized? Check the case where the screen is NOT the uConsole's
   (`show_fitted` "window" path), and that a page whose minimum is larger than the stack is clipped,
   not broken (is anything unreachable at 1280x720 now?).
2. **Rail (2).** No digits on keys. Keys spread evenly to just above the bottom. SYSTEM is last.
   Digit hotkeys match the new order everywhere (palette, keymap panel, tooltips, docs strings).
   Hidden pages (release.HIDDEN_PAGES, e.g. SWEEP) leave no gap or mismatched number.
3. **Tiles (3).** Purple page tiles and light-purple sub-page tiles in DARK, LIGHT and SUN. Check
   contrast (text on tile, open vs closed), focus cue, and that every page's sub-tabs actually use
   the subtab tile (not a few still flat).
4. **Strip (4).** UTC caption, BAT slot (telemetry, None, low states), ALERTS caption, OPS
   "CONTACTS ON MAP". Is the "power in a random spot" gone everywhere (no second power chip,
   footer, card)? The eliding `TitleLabel`: does `text()` returning the full title break anything
   (QSS, accessibility, tests)? Does the worst-case strip fit 1280 in all themes, live and demo?
5. **Run state (5).** `set_run` + QSS. Where it is applied in this PR (BABEL). Are there other
   start/stop/scan controls in pages this PR owns that were missed? (PROWL/PRISM belong to the
   radio thread, RECON to the RECON thread: list them as not in scope, don't fail on them.)
6. **Volume (6).** Real travel and step; disabled state (no sink) still reads as disabled.
7. **No bottom bar (26).** No page shows a bottom status row. Every status a page reported is still
   reachable: SDR presence in the strip, warnings as the `PageNotice`, all of it on a click of the
   page name. Does the notice ever cover the strip or rail, repeat, pile up, or steal focus? Does a
   page that is NOT on screen raise a notice? Is any warning now silently lost?
8. Lifecycle: anything new connected to the bus / netpolicy / telemetry is disconnected on close.
   UI-only: no data, decoding or radio behaviour changed.
9. Run `tests/test_shell_frame.py`, `tests/test_cl1_fix3.py`, `tests/test_cl1_screen.py`,
   `tests/test_ui_polish.py`. The thread runs the full suite separately: do not run it.
10. Write `plan/briefs/RA-S1-report.md` on `fix/shell-frame`: a table per item (answers Dalton's note:
   yes/partly/no, with evidence), new findings with severity and a PoC, then MERGE / DO NOT MERGE.
   Push (fetch + merge on reject, never force), remove the worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
