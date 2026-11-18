# RA-S2b — targeted cold re-audit of the RA-S2 fixes, branch `fix/ops-maps` (PR #34)

**FRESH session, Opus.** Auditor only: a report, not fixes. Own worktree off `origin/fix/ops-maps`.
Read `CLAUDE.md`, `plan/briefs/RA-S2-report.md` (N1-N7 and the Lows) on that branch, and the
"Device run 2" section of `plan/briefs/device-notes.md` on `origin/docs/briefs`.
Scope: `git diff 516a56c..origin/fix/ops-maps -- . ':!plan'`.

Decide fixed / partly / not fixed, with evidence, and try to break each:
- **N1** OPS NEXT PASS from OVERWATCH's own pass list (`shell._next_pass`, `ops.next_pass`): earliest
  pass not over; "SAT NOW" during a pass; "none in 24 h" only when the list really has none. Re-run
  your RA-S2 PoC. Does the card refresh often enough to move on when a pass ends?
- **N2/N3** the imagery note is now one line in a free corner (`BaseMap._place_banner` scans the top
  and bottom 30 % bands, right then left, avoiding `_overlay_rects()`), tap to put away until the
  state changes. Render OPS and ATLAS at 1280x720 in DARK, LIGHT, SUN, with FULL MAP on and off and
  the side panels shown and hidden: never over the centre, never over the map's own controls,
  readable, button reachable. Does putting it away hide a NEW problem? Is anything left that covers
  contacts near HOME?
- **N4** `netpolicy.GRANTABLE` / `allow_grant`: a grant to a non-tile host is refused (NetBlocked,
  nothing sent); tile hosts still work; NET stays OFFLINE. Any way to register a host from outside?
- **N6** RETRY after a failed download; raw error in the tooltip only.
- **N7** SKY DOME table heading.
- N5 and the RA-S2 Lows were not changed: confirm, and list them for Dalton.
UI-only apart from the netpolicy grant restriction; lifecycle.
Run `tests/test_ops_maps.py`, `tests/test_cl8_ship.py`, one file per process
(`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q --timeout=240 --timeout-method=thread`).
No full suite.

Write `plan/briefs/RA-S2b-report.md` on `fix/ops-maps`: a table, new findings with severity and a
PoC, then MERGE / DO NOT MERGE (only Medium or worse blocks). Push (fetch + merge on reject, never
force), remove the worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
