# RA-UIP — cold re-audit of UIP (`fix/ui-polish`)

Auditor: fresh session, no prior context. Branch head audited: `a485de9` (base `origin/fix/cl8-ship`).
Method: read `device-notes.md`, `CLAUDE.md`, the full diff `origin/fix/cl8-ship...origin/fix/ui-polish`
(27 files), then the UIP report. Every claim below was re-derived from code and, where marked, a PoC
run in the container venv (Python 3.13, PySide6, pyqtgraph 0.13.7, offscreen/xvfb, no tkinter).
PoC scripts are inlined in short form under each finding.

**Verdict: DO NOT MERGE** — one High (the basemap and the contacts use two different projections;
with this branch's pan/zoom a contact is drawn over the wrong ground). Everything else is Medium/Low
and could follow in a fix-up.

## 1. Hard constraints (gates, radio)

| Check | Result | Evidence |
|---|---|---|
| Gate files touched? | **No.** `engagement.py`, `opprofile.py`, `txguard`, `executor.py`, `chain.py`, `rfemit.py` are not in the diff. | `git diff --stat` |
| `AtlasLiveWorker.step` hidden + background opens no radio, takes no lease, no BLE, no subprocess | **Holds.** Hidden path calls `_ensure_sources` (constructs `sky_app.AdsbFeed`: a thread reading `/run/readsb*` files / `127.0.0.1` HTTP through `netpolicy`) and `_publish_passive` (readsb json, `sondes.json`, Kraken output). `_reconcile_rid` is not called while hidden; `_reconcile_leases` runs as before CL5-fix2 and only acts on `_wanted`, which only the ATLAS layer chips set (all lease/BLE layers default OFF in live). | PoC `hidden.py`: real readsb-style `aircraft.json`, `subprocess.Popen`, arbiter `request/acquire` and `RidSource` instrumented; two hidden+background steps → aircraft published, **0 Popen, 0 arbiter calls, 0 RID**. `test_u9_hidden_live_atlas_worker_runs_passive_feeds_only` |
| No ADS-B while a lease layer holds the dongle | **Holds.** `_publish_passive` keeps the `arbiter.owner() is None` guard. | PoC: arbiter `_owner="PRISM"`, fresh json → **0 events**. (No test pins this on the hidden path — see L6.) |
| `start_background_feeds` consequences | **OK.** Builds the ATLAS composite into the stack (so `closeEvent` stops it, PANIC's `on_panic` reaches its lease layers as before); `start()` is idempotent, so opening ATLAS later does not start a 2nd worker; `show_page` skips the `ATLAS:inner` alias (`stack.indexOf < 0`) so the inner app is never wrongly set inactive; skipped under the offscreen seam and for a release-hidden ATLAS; demo: only `AtlasDemoWorker` is un-paused. Revoke-while-hidden path unchanged. | code read `shell.py:158-222`, `app.py:416`, `atlas.py:905-931` |
| ASSISTANT / MESH pages | **OK.** `MeshWorker` starts only where `"MESH" in SUBTABS` (MESH page). Mesh send is unchanged (local echo, "NOT IMPLEMENTED — not transmitted" in live; no TX path exists to gate). SYSTEM lost no gate/session-log hook: `_meshw` is referenced only in `start()`. | `system.py:590-602`, `:508` |
| USE GPS / HOME | **SAVE is still the only setter.** `_on_gps` only fills the line edit; `eventbus.set_home` is reached only from `_save_settings`. gpsd read is on a daemon thread (`suite.gps_fix`, socket timeouts) → a hung gpsd cannot block the GUI; NaN/inf/out-of-range lat/lon are refused. **But** a junk fix can block a correct HOME — see M3. | `system.py:233-296`, `test_u7_*` |
| N26 (no range picture from a guessed origin) incl. OPS basemap | **Holds.** OPS calls `ppi.set_home` only when HOME is set (or demo HOME); ATLAS/OPS `BaseMap` has `can_fetch=False` until a real HOME. | `ops.py:340-346`, `mappanel.py:52-54`, `test_n26_*` |
| Any gate or radio behaviour change | **None found.** | |

## 2. Per-item table

| ID | Status | Evidence | Test |
|---|---|---|---|
| U1 nav-key baselines / gap | CLOSED | Keys moved to the left rail (U8); my 156-render sweep found no overlap/clip in the rail | `test_u1_*` |
| U2 SDR held / ENG active green, TX red | CLOSED | `topbar.py:472,500`; owner decision recorded in the report (overrides RA-CL1 amber) | `test_u2_*`, `test_armed_tx_is_never_green_and_active_engagement_is_green` |
| U3 bigger map | CLOSED (with L1/L2) | ATLAS side column fixed 360 px. Regressions on OPS from the narrower page: L1, L2 | `test_u3_*` |
| U4 F / collapsible panels | CLOSED | Renders `*_ATLAS_FULL`, `*_OPS_FULL` in all 6 theme×mode combos; F inert in text fields and non-map tabs | `test_u4_*` |
| U5 north-up regardless of global `imageAxisOrder`; Mercator row resample | CLOSED (orientation + resample) | PoC `merc.py`: global forced to **col-major**, pixel-coded synthetic tiles, 5 HOMEs (Denver, 70°N, Sydney, 60°N/179.7°E antimeridian, 0/0) × views ±600…±0.6 nm (z4–z16) × 15 points incl. 98 % to the view edge: the image pixel under every point depicts that point to ≤ 0.18 % of the view width (≈1 px). No point fell outside the image. **But** see H1: the image is registered to an equirectangular frame and the contacts are not. | `test_u5_*` (tautological w.r.t. H1: it computes the point with the same `_nm_from_home` the image uses) |
| U6 pan/zoom, view-following tiles, sources | PARTIAL | Limits ±600 nm / ≥1 nm ok; `tile_span` ≤ 48 tiles except z3 floor (≤ 64 by construction); fast zoom collapses to one pending fetch which reads the latest view; NET OFFLINE: every fetch goes through `netpolicy.urlopen` (cache read only); per-source cache dirs; blank fallthrough works. Open: H1 (exposed by this item), M1 (Esri placeholder still cached and shown), L3 (stale image after HOME change), L4 (worst-case fetch time) | `test_u6_*` |
| U6b OPS dark satellite | CLOSED | `PpiScope` + `BaseMap(dark_sat)`, no HOME → none | `test_u5_atlas_opened_first…` |
| U7 USE GPS / hemisphere check | PARTIAL | Fill-only, threaded: ok. M3: a junk/foreign fix silently arms a refusal of the correct HOME; L5: false refusal within 0.5–~1° of the equator / prime meridian; `bool` lat/lon accepted | `test_u7_*` |
| U8 left page rail + nested sub-tabs, 1–9 | CLOSED | No RAIL-OVERFLOW/OVERLAP, no chrome text < 16 px in 156 renders; FORGE (5 sub-tabs) leaves ≈ 10 px spare, so a 6th sub-tab on any page will overflow (L7) | `test_u8_*`, changed `test_one_top_strip_one_left_page_rail_no_footer` |
| U8b ASSISTANT / MESH pages | CLOSED | see §1 | `test_folded_pages_live_where_the_brief_put_them` (changed) |
| U9 OPS fed from launch | CLOSED (with M4 cost) | see §1 | `test_u9_*` |
| U10 C2 track symbols, colour by type, legend | PARTIAL | Glyph nose and leader agree (crops of `dark_demo_ATLAS_MAP`; `test_u10_aircraft_glyph_points…` at 0/90/180/270). No heading → ring, no leader: holds. readsb `dbFlags` bit 0 = military and category `A7` = rotorcraft are right and survive `sky_app.clean_aircraft`. Open: M2 (military + emergency squawk loses red), L8 (live AIS/APRS headings never drawn: they arrive as `course`, ATLAS/OPS copy only `track`) | `test_u10_*` |
| U11 no slot dividers | CLOSED | QSS rule + painted check | `test_u11_*` |

### Changed (not added) tests
All seven changed files were read hunk by hunk. Each change follows an owner decision recorded in
`UIP-report.md` (left rail = U8; ASSISTANT/MESH pages = U8b; ENG green = U2; DARK SAT/LIGHT SAT =
U6; 9 keys) or is a signature follow-up (`test_cl4_honest` lambda takes `**_kw`). The D9 test still
pins TX ARMED/UNLOCKED red and never green. No unrelated assertion was weakened.

## 3. New findings

**H1 — High — Basemap and contacts are drawn in two different projections; with UIP's pan/zoom a
contact sits over the wrong ground.** Contacts are placed with `eventbus.to_xy` (azimuthal
equidistant: true great-circle range and bearing). The basemap is placed with
`tiles._nm_from_home` (equirectangular: `dx = Δlon·60·cos(HOME lat)`, `dy = Δlat·60`). The two
diverge with range. At the old fixed ±80 nm view this was ≈ 0.9 nm at the outer ring (≈ 4 px); UIP
lets the operator zoom to a 1 nm view and pan to 600 nm, where it is the whole screen.
PoC `registration.py` (pixel-coded synthetic tiles through the real `TileLayer._build` + `BaseMap`,
view centred on the contact as an operator zoomed on it would be): ground actually drawn under the
contact vs. its true position —

| HOME | contact | view | error | of view |
|---|---|---|---|---|
| Denver 39.6°N | 60 nm / 045° | 2 nm (z14) | 0.48 nm | 24 % |
| Denver | 80 nm / 315° | 4 nm (z13) | 0.85 nm | 21 % |
| Denver | 200 nm / 300° | 10 nm (z12) | 5.5 nm | 55 % |
| Denver | 400 nm / 315° | 40 nm (z10) | 22 nm | 55 % |
| Fairbanks 64.8°N | 80 nm / 315° | 4 nm (z12) | 2.2 nm | 55 % |
| Fairbanks | 200 nm / 300° | 10 nm (z11) | 14 nm | 141 % (off screen) |

The range rings are in the AEQD frame too, so the rings are also misregistered against the imagery.
`test_u5_basemap_is_north_up…` cannot see this: it computes the probe point with `_nm_from_home`,
the same formula the image uses. Fix direction: one projection for both (e.g. resample the tile
canvas per pixel from the AEQD frame via an inverse `to_xy`, or project contacts/rings with the
basemap's formula and accept the range error — but then range/bearing labels must come from
`to_xy`), plus a test that probes the image at `eventbus.to_xy(lat, lon)` for points at 60/200 nm and
a high latitude. Blocker per the brief ("any map that draws a position in the wrong place").

**M1 — Medium — An Esri "API KEY REQUIRED" placeholder is still accepted and cached forever.**
Esri stays first in `SAT_SOURCES`; `_blank()` only rejects near-uniform or transparent tiles. A
grey tile with the placeholder text has RGB std ≈ 10.6 → `_blank` False (PoC) → it is used, written
to `~/.cache/palisade/tiles/satellite/esri/<z>/`, and served from cache from then on, ahead of USGS/EOX.
The per-source dir only hides placeholders cached *before* this branch. The device bug recurs the
next time Esri serves one. Fix: detect the placeholder (size/hash, or Esri's
`Content-Type`/header), never cache a fallthrough-worthy tile, or put Esri last.

**M2 — Medium — A military aircraft squawking 7500/7600/7700 is drawn MIL orange, not emergency
red.** `tracksym.color`: `severity == "alert" … and not is_military(c)` → EMERGENCY. The exclusion
exists because demo marks every MIL track `alert`; for live ADS-B, `severity="alert"` means only an
emergency squawk (`adsb_to_contact`). Before UIP the map dot and the OPS scope dot were red for any
`alert`. An operator loses the emergency cue exactly for military traffic. Fix: key the red on the
emergency itself (carry `emergency`/`squawk` in the payload) rather than on severity-minus-military.

**M3 — Medium — A junk or foreign GPS fix silently blocks saving the correct HOME.**
The automatic read at launch (HOME unset, live) stores `_gps_last` even when it does not fill the
field (`system.py:283`), and nothing clears it for the session. `_hemisphere_mismatch` then refuses
SAVE of any HOME whose sign differs ("nothing saved"), with no override. A cold-start or misconfigured
receiver reporting e.g. `(0.9, 0.9)` mode 2 makes a correct Denver HOME unsaveable until restart; the
operator saw no GPS message at all (the auto read is silent). The brief's rule was "gpsd junk cannot set
a wrong HOME"; here it prevents the right one. Fix: only arm the check from a fix the operator
requested (USE GPS), show it, and let a second SAVE confirm.

**M4 — Medium (CM5 cost) — The ATLAS page is now always built at launch and redraws every 700 ms
while hidden.** `AtlasApp._timer` → `_render` → `MapPanel.set_tracks` is not gated on visibility.
Method: offscreen, x86-64 container, 200 contacts (150 aircraft) with 8-point trails, mean of 10
redraws incl. `processEvents`: `set_tracks` 94 ms (25 ms without the data-block labels; the old dot
path with labels was 87–103 ms, so the glyphs themselves are not the cost), OPS
`PpiScope.set_contacts` 15–19 ms. Scaling by ≈ 2.5× for a Cortex-A76 @ 2.4 GHz vs this host gives
≈ 230 ms per ATLAS redraw → ≈ 30 % of the GUI thread continuously, on a page the operator may never
open. Fix: skip `_render` (or the map part) while the page is not active; render once on show.

**M5 — Medium — New intermittent `TypeError` in the hub's app-wide `eventFilter`; the suite is
not green.** `test_cl1_screen::test_every_page_and_subtab_fits_1280x720` failed in the full run
(`[False-sun]`) and, run alone, fails in 4 of 10 runs on this branch (various params) vs 0 of 4 on
`fix/cl8-ship`. Trace: while `open_callsign` constructs a page (`app.py:201` `QWidget.__init__`),
the hub filter is called with `obj` = a stale `QWidgetItem` wrapper (an address reused after a
deleted object) and `super().eventFilter(obj, ev)` (`shell.py:475`) raises "called with wrong argument
types". In the field PySide prints the traceback and the event continues, so it fails open, but it is
a branch-introduced flake in the very layout test this cluster relies on. Likely trigger: the
nested sub-tab rails reparented into `NavRail` (`attach_sub`) or the extra pages built at launch.
Fix: guard the filter (`if not isinstance(obj, QtCore.QObject): return False`) and find the reparent
that leaves the stale item.

**L1 — Low — OPS sub-line clipped in LIGHT and SUN demo:** "1 military (demo) · nearest 6 NM"
needs 307 px, gets 278–279 → the unit "NM" is cut (base: 307/307). Cause: U3 moved the "SITUATION ·
ALL FEEDS" caption onto that row, and the U8 rail took 128 px.
**L2 — Low — OPS alerts header runs into the count:** "ALERTS · PRESS A FOR HISTORY + ACKNOWLEDGE"
(445 px) gets ≈ 366 px and collides with "5 unacknowledged" (render `sun_demo_OPS_-`). Fit in base.
**L3 — Low — Stale basemap after a HOME change:** a `ready` emitted by an in-flight build (bounds
computed against the old HOME) and delivered after `BaseMap.set_home` cleared the image is shown
misplaced by the HOME delta until the queued re-fetch lands. Needs a generation token on `ready`.
**L4 — Low — Worst-case fetch latency:** each tile tries up to 3 sources sequentially with an 8 s
timeout, up to 48 (z3: 64) tiles per build, one build at a time; on a black-holing network a view
change can take minutes to show imagery. Fails safe (old image stays).
**L5 — Low — Hemisphere check false refusals / junk types:** fixes and HOMEs 0.5–~1° either side of
the equator or prime meridian (legitimately ~60–120 nm apart) are refused; `True`/`False` pass the
`isinstance(…, (int, float))` check as 1/0.
**L6 — Low — Test gap:** no test pins "hidden background worker publishes no ADS-B while the arbiter
is held" (the guard holds today — PoC — but `test_u9_hidden…` only runs with the arbiter free).
**L7 — Low — Rail headroom:** with FORGE's 5 nested sub-tabs the last key ("9 MESH") ends ≈ 10 px
above the window bottom; any page with a 6th sub-tab overflows at 720 px. No test guards it.
**L8 — Low — Live vessels/APRS never show a heading:** `ais_vessel_contacts` and
`aprs_station_contacts` publish `course=`, ATLAS/OPS `_on_event` copy only `track` → always the ring,
no leader (fails safe; only demo vessels are oriented).
**L9 — Low — Key map:** "+ −" still reads "span wider / narrower (PRISM)"; ATLAS now zooms on them.
**L10 — Low (behaviour note) — "AIRCRAFT RADIO BUSY" alerts now appear on OPS whenever PRISM/PROWL
take the radio**, from an ATLAS page the operator never opened (true, but new noise).

## 4. Layout at 1280×720
156 renders: every page and sub-tab (OPS, ATLAS MAP/SKY DOME/PASSES, PRISM, PROWL ×4, RECON ×4,
FORGE ×5, SYSTEM ×4, ASSISTANT, MESH) × dark/light/sun × live/demo, status strip forced to its widest
(`LIVE · SDR OVERWTCH · TX UNLOCKED · ENG 192.168.100.0/24 · 99+`), plus F on ATLAS and OPS and back,
plus the key map. Automated checks on every visible widget: single-line text wider than its box,
chrome (strip + rail) text < 16 px, widgets outside the window, rail children overlapping or past
its bottom, strip minimum width > window. Results: no chrome text < 16 px, no strip overflow, no rail
overlap/overflow; the only clips are L1 and L2 (OPS, light/sun demo). Map glyph/leader orientation
checked on enlarged crops.

## 5. Suite
`tests/test_ui_polish.py`: **45 passed** (49 s).
Full suite, once, `QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q tests` at `a485de9`:
**1672 passed, 3 failed, 7 skipped, 7 errors** (28 min 08 s).
- Baseline (container, same on `fix/cl8-ship`): `test_shell.py` ×7 errors (no tkinter),
  `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`.
- **Not baseline:** `test_cl1_screen::test_every_page_and_subtab_fits_1280x720[False-sun]` → M5
  (reproduced alone 4/10 on the branch, 0/4 on the base).
- The `test_cl1_fix2` ack-all flake did not trip this run. Note: my render PoCs ran concurrently on
  the same 4-core host during part of the run.

## 6. What must change before MERGE
1. H1 (one projection for imagery, rings and contacts; a test that probes the image at
   `eventbus.to_xy`).
2. M5 (filter guard + root cause; the fit test green 10/10).
3. Recommended in the same fix-up: M1, M2, M3, M4. Lows can follow.

**Verdict: DO NOT MERGE**
