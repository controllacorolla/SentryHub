# RA-S1d — targeted cold re-audit of the RA-S1c fixes, branch `fix/shell-frame` (PR #33)

**FRESH session, Opus.** Auditor only: a report, not fixes. Own worktree off `origin/fix/shell-frame`.
Read `CLAUDE.md`, `plan/briefs/RA-S1c-report.md` (N6-N11) on that branch, and the "Device run 2"
section of `plan/briefs/device-notes.md` (no permanent bottom bar; "if you want a little message,
not there").
Scope: `git diff 62a26df..origin/fix/shell-frame -- palisade_qt tests` (the `PageNotice` changes).

Decide fixed / partly / not fixed, with evidence, and try to break each:
- **N6** `_sig` = (state, alphabetic words of the text). Drive ATLAS's real `_layer_summary` in a live
  hub with no ADS-B feed while layer counts move: exactly one notice? RECON WIFI -> BLE STANDBY still
  shows (N1 must not regress)? A ticking counter still silent (F2)?
- **N7** (accepted Low): warnings differing only by a number merge. Any case where that hides
  something Dalton needs? Say so if yes.
- **N8** `PageNotice.stop()` from `closeEvent`: no timer fires after close.
- **N10** reminder only after `REMIND_S` (60 s) away; a quick flip does not repeat. Does a warning
  that clears and returns while away under 60 s get lost? Judge the severity for the operator.
- New: a second warning moments later joins the notice showing (`_page/_lines/_worst`). Can lines
  accumulate without bound, carry over from `show_all`, or carry over from another page?
UI-only; lifecycle. Run `tests/test_shell_frame.py` and `tests/test_cl1_fix3.py`, one file per
process (`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q --timeout=240
--timeout-method=thread`). No full suite.

Write `plan/briefs/RA-S1d-report.md` on `fix/shell-frame`: a table per finding, new findings with
severity and a PoC, then MERGE / DO NOT MERGE. A Low that is a judgement call for Dalton is not a
blocker: list it for him. Push (fetch + merge on reject, never force), remove the worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
