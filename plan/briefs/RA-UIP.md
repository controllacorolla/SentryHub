# RA-UIP — cold audit of UIP (UI polish from the first device run), branch `fix/ui-polish`

**FRESH session, Opus.** Auditor only. Own worktree off `origin/fix/ui-polish`. Read first:
`plan/briefs/device-notes.md` (on `docs/briefs`: the owner's device notes this cluster answers),
`CLAUDE.md`, then the branch diff against its base `origin/fix/cl8-ship`
(`git diff origin/fix/cl8-ship...origin/fix/ui-polish`). Read `plan/briefs/UIP-report.md` on the
branch only at step 3.

This is a UI cluster, but it touches the shell, the ATLAS worker's hidden mode, the map tile
pipeline and the SETTINGS HOME path. Claims to falsify, item by item (IDs U1–U11 in the report):

1. **Hard constraints first.** UI-only changes must not alter data, decoding or radio behaviour;
   no gate (engagement.py, opprofile.py, txguard, executor.py, chain.py, rfemit.py) may be routed
   around or weakened. In particular:
   - `AtlasLiveWorker.step` while hidden now publishes "passive feeds". Prove or refute that this
     opens no radio, takes no arbiter lease, starts no BLE scan / subprocess, and never publishes
     ADS-B while a lease layer holds the dongle. `PalisadeHub.start_background_feeds` starts ATLAS's
     worker at launch: check every consequence (arbiter, PANIC, stop/close, page set_active,
     revoke while hidden, demo).
   - ASSISTANT / MESH pages: `MeshWorker` runs once (MESH page only), mesh send still gated
     exactly as before, nothing lost from SYSTEM that a gate or the session log depended on.
   - USE GPS / hemisphere check: SAVE is still the only thing that sets HOME; no path sets HOME
     from gpsd without the operator pressing SAVE; a gpsd that hangs or sends junk cannot block
     the GUI or set a wrong HOME. N26 (no range picture from a guessed origin) still holds,
     including on the new OPS basemap.
2. **The map.** U5: is the basemap north-up / east-right regardless of pyqtgraph's global
   `imageAxisOrder` and of which page opened first; is the Mercator row resample right (pick
   points near the view edge, high latitudes, the antimeridian, zoom levels 3–16); U6: pan/zoom
   limits, tile count cap, stale tiles after HOME changes or a fast zoom, NET OFFLINE still
   fetches nothing, per-source cache, blank-tile fallthrough. U10: glyph heading vs leader vs
   real ADS-B `track`; a contact with no heading never shows a direction; class colours
   (military = readsb dbFlags bit 0, helo = category A7) and the legend; CPU cost of a 200-contact
   redraw on the CM5 (estimate; state your method).
3. **Layout at 1280×720.** Render every page and sub-tab (dark, light, sun · live, demo) with the
   status strip at its widest; F (full map) on ATLAS and OPS and back; the nested sub-tabs in the
   left rail; 1–9 keys; key map; nothing clipped or overlapping, nothing under 16 px in chrome.
   Check every test this branch CHANGED (not just added): each change must follow an owner
   decision recorded in the report, not weaken an unrelated assertion.
4. `tests/test_ui_polish.py`, then the full suite once
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`).
   Known baseline failures (same on the base branch, env): `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
   `test_hwlab::test_doctor_hwbench_check`, `test_shell` errors without tkinter; the
   `test_cl1_fix2` ack-all alerts test is flaky on main too.
5. Write `plan/briefs/RA-UIP-report.md` on `fix/ui-polish`, push, remove the worktree. Table per
   U-item (CLOSED / OPEN / PARTIAL / REGRESSED · evidence · test), new findings with severity
   (Critical / High / Medium / Low as in `plan/audit/REAUDIT_PROMPT.md`), then MERGE / DO NOT
   MERGE. Blockers: any gate or radio behaviour change, any Critical/High, any map that draws a
   position in the wrong place.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
