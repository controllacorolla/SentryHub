# RA-UIPc — cold audit of UIP round 2 + the backcheck fixes, branch `fix/ui-polish`

**FRESH session, Opus.** Auditor only. Own worktree off `origin/fix/ui-polish`. Read first:
`CLAUDE.md`, `plan/briefs/device-notes.md` (on `docs/briefs`: the owner's notes),
`plan/briefs/RA-UIP.md` (hard constraints and blockers still apply), then
`plan/briefs/RA-UIPb-report.md` on the branch, then the diff since that audit:
`git diff 97dc1cc..origin/fix/ui-polish -- palisade_qt tests` (97dc1cc = RA-UIPb report; the
`origin/main` merge e7cdf0b in between brings PRs #24/#25/#26, already audited — skip their files
unless UIP code touches them). Read `plan/briefs/UIP-report.md` only at step 6.

Owner, 2026-11-17: "If I asked for it, then do it." Round 2 pulls into v0.1: HOME follows GPS;
Remote-ID BLE setup handled cleanly; ATLAS split into views. Plus backcheck fixes (OPS legend,
aircraft data block speed, ADS-B B6 = drone, balloon icon, contact card no longer LOST when its
layer is turned off, full Remote-ID error text). Claims to falsify:

1. **HOME follows GPS** (`palisade_qt/gpshome.py`, shell `start_gps_home`, SETTINGS checkbox and
   status, `_save_settings`). HOME must never be set from an untrustworthy fix: 0/0, bools, NaN,
   mode < 2, big epx/epy, a single jump (first fix of a run and any jump > JUMP_NM need a second
   agreeing fix). A lost fix holds the last HOME and says so. The typed HOME remains the fallback
   and is loaded at start; the GPS HOME is never persisted. Follow OFF never touches HOME. No gpsd
   read on the GUI thread, none in demo or under the offscreen seam. Check every HOME consumer
   (ATLAS, OPS, OVERWATCH, SKY passes, sitrep, the hemisphere check, N26 covers) for what a moving
   HOME does: ATLAS/OPS now re-project contacts instead of clearing them; tiles refetch; anything
   that caches a HOME-relative value and goes stale? Is a re-home every MOVE_NM acceptable on the
   CM5 (tile refetch cost)?
2. **ATLAS views** (`atlas.VIEWS`, `set_view`, `_in_view`, `FeedTable.set_columns`). A view is a
   display filter only: prove no view switch calls `set_layer`, changes `_layers`, starts/stops a
   lease, the arbiter, BLE or a subprocess. Per-view columns correct; empty states honest (layer off
   vs no contacts); selection/detail behaviour across views; keyboard (V, arrows, focus); 1280x720
   fit of the side column in every view and theme (list still usable in ALL with the view bar + 3
   rows of chips).
3. **Remote-ID setup** (`RidSource.setup_problem`, `_set_setup`, PASSIVE_NOTE, ATLAS `on_status`
   rid_note handling, `set_chip(tip=)`). Setup problems become a WARN chip + full text in the DRONES
   view + a session-log `warn`, never `error`/`fault` (so the strip's MODE does not go red); a real
   unknown failure is still a fault with its full text available. The passive/active fallback from
   PR #25 is unchanged. Check the needle lists for false matches (e.g. "blocked" in an unrelated
   error turning a fault into a warning).
4. **Backcheck fixes:** OPS legend placement at every scope size and with F; data block
   (aircraft only, speed in KT, bool/NaN refused); B6 → drone glyph + colour; balloon glyph; the
   contact card clears when hidden, LOST only when the contact is gone (RA-CL1c F4 still holds).
5. Hard constraints as in RA-UIP §1. Gate files untouched; UI-only except `gpshome.py` reading gpsd
   (no writes) and `eventbus.set_home` (existing API).
6. `tests/test_ui_polish.py`, then the full suite once. Baseline: container failures as in
   RA-UIP §4; known flakes `test_cl1_fix2` ack-all, `test_cl4_gates::test_n21…`,
   `test_cl1_screen::test_up_down…`, `test_cl5_fix2::test_nh_panic_banner…`.
7. Renders at 1280x720 (dark, light, sun · live, demo) of ATLAS in every view, OPS, SETTINGS.
8. Write `plan/briefs/RA-UIPc-report.md` on `fix/ui-polish`, push, remove the worktree. Table per
   claim (CLOSED / OPEN / PARTIAL / REGRESSED · evidence · test), new findings with severity, then
   MERGE / DO NOT MERGE. Blockers as in RA-UIP, plus: any path where a bad GPS fix sets HOME.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
