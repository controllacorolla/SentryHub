# RA-S1c — targeted cold re-audit of the RA-S1b fixes, branch `fix/shell-frame` (PR #33)

**FRESH session, Opus.** Auditor only: a report, not fixes. Own worktree off `origin/fix/shell-frame`.
Read `CLAUDE.md`, `plan/briefs/RA-S1b-report.md` (findings N1-N5 and the F-table) on that branch,
and the "Device run 2" section of `plan/briefs/device-notes.md` (Dalton's words: no permanent
bottom bar, "if you want a little message, not there").
Scope: `git diff c4ed94e..origin/fix/shell-frame -- palisade_qt tests`.

Decide fixed / partly / not fixed with evidence, and try to break each fix:
- **N1** `PageNotice._sig` = (state, text with digits replaced). A different message on the same key
  shows; a ticking counter does not; alert -> warn with the same message does not. Any warning text
  whose only difference is digits but which is a genuinely new warning (e.g. "CH 1" vs "CH 6")?
  Judge whether that matters for what Dalton will see.
- **N2** retry timer (700 ms, single-shot) when a panel holds a notice back. Does it ever loop
  forever, fire after close, or show a notice for a page no longer on screen?
- **N3** `forget(page)` on leaving a page. Does flipping pages quickly spam notices? Does it
  ever show on the wrong page?
- **N4** open nav key focus ring in DARK, LIGHT, SUN: render at 1280x720 and look; does the ring
  shift the key's text or size?
- **F10** remaining docstrings.
Lifecycle: the new QTimer is parented and stops with the window. UI-only.
Run `tests/test_shell_frame.py`, `tests/test_cl1_fix3.py` one file per process
(`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q --timeout=240 --timeout-method=thread`).
Do not run the full suite.

Write `plan/briefs/RA-S1c-report.md` on `fix/shell-frame`: a table per finding, new findings with
severity and a PoC, then MERGE / DO NOT MERGE. Push (fetch + merge on reject, never force), remove
the worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
