# RA-S2c — targeted cold re-audit of the RA-S2b fixes, branch `fix/ops-maps` (PR #34)

**FRESH session, Opus.** Auditor only. Own worktree off `origin/fix/ops-maps`. Read `CLAUDE.md` and
`plan/briefs/RA-S2b-report.md` (N8-N11) on that branch. Scope: `git diff 3516932..origin/fix/ops-maps
-- . ':!plan'`.
- **N8**: tapping the strip folds it to a "NO IMAGERY ▸" chip (tap to unfold); never hidden for the
  session. Re-run your PoC (tap, then HOME to an uncached area; zoom): is there always a visible reason
  and a way back to DOWNLOAD MAP? Render OPS and ATLAS folded and unfolded in DARK/LIGHT/SUN.
- **N9**: an old OVERWATCH alert is used only while OVERWATCH has no prediction state of its own.
  HOME cleared after an alert -> "HOME NOT SET"? An alert pass that started -> "NOW"?
- **N10**: refused grants logged as blocked; https only; the lint test limits `granted=`/`allow_grant(`
  to `netpolicy.py` and `palisade_qt/kit/tiles.py` — can it be fooled easily?
- Regressions on N1-N7.
Run `tests/test_ops_maps.py`, `tests/test_cl8_ship.py`, one file per process
(`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q --timeout=240 --timeout-method=thread`).
Write `plan/briefs/RA-S2c-report.md` on `fix/ops-maps`: a table, new findings with severity and a PoC,
MERGE / DO NOT MERGE (only Medium or worse blocks; list Lows for Dalton). Push (fetch + merge on
reject, never force), remove the worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
