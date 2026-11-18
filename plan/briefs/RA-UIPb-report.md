# RA-UIPb — re-audit of the RA-UIP fixes (`fix/ui-polish`)

Auditor: fresh session, no prior context. Branch head audited: `be4221a` (fix commit `90ff886`;
diff `5aa0974..be4221a`, 9 files). Read: `CLAUDE.md`, `RA-UIP.md`, `RA-UIP-report.md`, the fix diff.
Container venv (Python 3.13, PySide6, pyqtgraph 0.13.7, numpy), offscreen/xvfb, no tkinter, 4 cores.
PoC scripts are summarised under each item.

**Verdict: MERGE** — H1 and M5 are closed with tests that pin them; M1–M4 are closed or fail safe.
The new findings are one Medium (imagery above 85.05° N/S is clamped, so a contact near the pole
is drawn over ground ~150–300 nm away; HOME has to be at about 75° or higher to see it) and Lows.
None is a gate or radio change. None draws a contact in the wrong place on the map.

## 1. Hard constraints

| Check | Result | Evidence |
|---|---|---|
| Gate files (`engagement.py`, `opprofile.py`, `txguard`, `executor.py`, `chain.py`, `rfemit.py`) | **Untouched** | `git diff --stat 5aa0974..be4221a`: only `atlas.py`, `kit/tiles.py`, `kit/tracksym.py`, `ops.py`, `panels.py`, `shell.py`, `system.py`, report and tests |
| Hidden background feed passive-only | **Holds.** The fix only adds a render skip (`atlas.py` `_render` early return) and a redraw on show; `AtlasLiveWorker.step` is unchanged | `test_u9_hidden_live_atlas_worker_runs_passive_feeds_only`, new `test_u9_hidden_background_worker_publishes_no_adsb_while_the_radio_is_held` |
| Data/decoding | **Additive only.** `adsb_to_contact` adds `emergency=` to the payload. Severity is still derived the same way. APRS/AIS decoders are not touched | diff `atlas.py:136-143` |
| HOME: SAVE is the only setter | **Holds.** `eventbus.set_home` is reached only from `system.py` `_save_settings` (`:353`). `_on_gps` fills the line edit only | grep + code read |

## 2. Per-finding table

| ID | Status | Evidence | Test |
|---|---|---|---|
| **H1** one projection for imagery, rings and contacts | **CLOSED** (except the polar clamp, see N1) | `tiles.aeqd_inverse` matches `eventbus.to_xy` (same sphere `EARTH_NM`). `reproject` samples the Mercator canvas per output pixel; `_build` returns the AEQD rect. **PoC `reg.py`**: pixel-coded synthetic tiles through the real `TileLayer._build`, shown in a `pg.ImageItem(axisOrder="row-major")` with the global `imageAxisOrder` forced to **col-major**, probed at `mapFromView(to_xy(lat, lon))` and decoded back to lat/lon (great-circle error). HOMEs: Denver, Fairbanks, Sydney, 60°N/179.7°E, Fiji (−17.7, −179.9), Ushuaia, Alert (82.5°N). Ranges 0–600 nm × 8 bearings; views 1, 4, 20, 100, 400 and 1200 nm, centred on the contact and clamped to ±600. **Worst error ≤ 2.2 screen px for every HOME** (e.g. Fairbanks 600 nm, 20 nm view: 0.047 nm; Sydney, 1200 nm view: 1.7 px), except for contacts above 85.05° N (N1). **`tile_span`**: 0 cap violations (≤ MAX_TILES except the z3 floor) over about 2,400 views. The view is covered: imagery lay under every contact except across the antimeridian (N2: transparent, not wrong). **Cost**: synthetic `_build` median 0.43 s, max 0.85 s (x86-64 container, load from the suite running alongside); `reproject` 1350² 0.47 s with a 177 MB transient peak (tracemalloc), 2048² 0.90 s; `tint` on the GUI thread 30 ms. At ×2.5 for a Cortex-A76 that is ≈ 1–2 s per pan or zoom on the worker thread, and ≈ 75 ms on the GUI thread per new image. Acceptable, see L12. **Does the test fail on the old placement?** Yes: `tiles.py` from `5aa0974`, with only `aeqd_inverse`/`EARTH_NM`/`_placeholder` grafted in so that it imports, fails **7/7** cases (5 `best <= 3` assertions with errors of up to 420 tile px, 2 with no matching tile at all) | `test_u5_imagery_under_a_contact_is_the_contacts_own_ground` ×7, `test_u5_basemap_is_north_up…` (now probes `to_xy`) |
| **M5** eventFilter `TypeError` / fit test flake | **CLOSED** | Fit test **10/10 alone** at `be4221a`; it also passed in the full run. **Root cause, narrowed**: I instrumented the guard (pointer, `shiboken6.isValid`, stack). In 13 instrumented runs it fired 4 times, always `obj` = a `QWidgetItem` wrapper with `isValid=True`, event **`QEvent.Create` (15)**, raised from inside `QWidget.__init__` of a page that `open_callsign` was constructing (`app.py:201`). `QEvent.Create` is sent from inside the C++ widget constructor, before PySide has registered the new widget's own wrapper at that address, so it resolves to an older, stale `QWidgetItem` entry. **Not `ops.RailCard.clear_body`**: none of 138 logged `takeAt` pointers matched the stale pointers. `takeAt` items are not Python-owned (`shiboken6.ownedByPython` False), so their C++ objects leak instead of freeing an address. `ops.py` is the only Python-side producer of `QLayoutItem` wrappers on this path, so the stale entry comes from a QLayoutItem wrapper created inside PySide/shiboken, not by our code. The exact producer is still unpinned. **Can the guard swallow a real key?** No. The stale lookup happens only while the widget is being constructed; once the constructor returns, PySide registers the real wrapper. A `KeyPress` cannot be delivered to a widget that is still in its constructor. Before the fix the same object was already rejected by `_ours`/`_is_key_target` (both require a `QWidget`), so PANIC, 1–9, F and Esc behave exactly as before. The `try` wraps only `super().eventFilter`, the C++ base, which returns `false`. The hub's own handlers (`panic`, `handle_key`) are outside it, so their errors still surface | `test_cl1_screen::test_every_page_and_subtab_fits_1280x720` (10/10 + full run) |
| **M1** placeholder tile shown and cached | **CLOSED** for the bug; see N3 for real grey imagery | `tiles._placeholder` (≥ 97 % of pixels with R/G/B spread ≤ 4) runs before `_blank`; the cache file is unlinked. **Real tiles** (fetched for this audit, one tile per source per point): Esri's "Map data not yet available" (mid-Pacific z14/z16) → placeholder → falls through to EOX (blue). **Not** discarded: Salar de Uyuni (Esri z9–z15), Bonneville, White Sands, Svalbard, Everest, Antarctica (Esri), Denver, Sahara. **Discarded although real**: pure-white ice or salt tiles (Greenland interior from Esri and EOX at every zoom; EOX over Salar, Bonneville z14+, White Sands z15, Antarctica) → N3. **All sources placeholder** → the canvas stays zeros → transparent → the map well colour shows, never the grey stand-in | `test_u6_placeholder_tile_is_never_shown_or_kept` |
| **M2** MIL + emergency squawk loses red | **CLOSED** | `tracksym.color`: `emergency is True` → EMERGENCY before the MIL rule. `atlas.py` and `ops.py` copy `emergency`. `adsb_to_contact` is the only aircraft producer | `test_u10_emergency_squawk_is_red_on_military_aircraft_too` |
| **M3** junk silent fix blocks the right HOME | **CLOSED** | `_gps_last` is set only when `not auto` (USE GPS). The warning is confirmable: `_hemi_confirm` means a second SAVE of the same HOME saves it | `test_u7_a_silent_junk_fix_never_blocks_the_right_home`, `test_u7_no_fix_says_so…` (now asserts `_gps_last is None`) |
| **L5** equator band / bools | **CLOSED** | `HEMI_MARGIN = 2.0` on both values; `bool` rejected in `_on_gps` | `test_u7_hemisphere_warning_is_confirmable_and_ignores_the_equator_band` |
| **M4** hidden background ATLAS redraws | **CLOSED** | `_render` returns after pruning when `_background and not _active`. `set_active(True)` queues `_render` (only for the background page). A standalone ATLAS (`_background` False) is unchanged. `_active` defaults False (`app.py:210`), and `start_background_feeds` → `set_background` → `set_active(False)`, so `_ever_shown` stays False until the operator opens ATLAS | `test_u9_hidden_background_atlas_skips_the_map_redraw_until_shown` |
| **L10** BUSY alerts from an unopened ATLAS | **CLOSED** | `_update_busy` runs while hidden only once `_ever_shown` is set | covered by code read; no dedicated test (Low) |
| L1 / L2 OPS captions | **CLOSED** | "All feeds", "ALERTS · A = history + ack" | `test_ops_captions_fit_beside_the_page_rail_in_every_theme` |
| L6 hidden worker + held radio | **CLOSED** | — | `test_u9_hidden_background_worker_publishes_no_adsb_while_the_radio_is_held` |
| L8 `course` drawn; AIS 360/511 never a direction | **CLOSED** | `tracksym.heading` accepts only `0 <= v < 360`. ATLAS and OPS copy `course`. `aprs.py` already drops course 0 (unknown) and maps 360 to 0 | `test_u10_ship_and_aprs_course_draws_a_heading_and_not_available_does_not` |
| L9 key map "+ −" | **PARTIAL** (fixed, not pinned) | `panels.py:786` now reads "zoom in / out (ATLAS) · span (PRISM)"; no test asserts it | none |
| L3 stale basemap after a HOME change | OPEN, non-blocking | unchanged; one image at most, until the queued re-fetch lands | — |
| L4 worst-case fetch time | OPEN, non-blocking | unchanged. N3 makes it worse in pure-white areas: those tiles are re-fetched on every build | — |
| L7 rail headroom | OPEN, non-blocking | unchanged; nothing adds a 6th sub-tab in this branch | — |

None of L3, L4 or L7 has to block: each fails safe or is latent.

## 3. New findings

**N1 — Medium — Imagery north of 85.05° N (or south of 85.05° S) is the clamped edge row, so a
contact there sits over ground 150–300 nm away.** `reproject` clips `lat` to ±85.05 before
converting to a Mercator row (`tiles.py` `reproject`), so every output pixel past that latitude
samples the top or bottom row of the mosaic. PoC (`reg2.py`, HOME Alert 82.5° N, −62.3°): contact
300 nm / 000° (87.5° N) → shown ground 147 nm away; 450 nm / 000° (89.99° N) → 297 nm away, at
every zoom. This is reachable only with a HOME at about 75° or higher (for example Pituffik at
76.5° N reaches 85° within 600 nm). There the ground is pack ice either way, so an operator is
unlikely to rely on it. The contact and the rings are still placed correctly. Fix: make pixels with
`|lat| > 85.05` transparent (`ok &= np.abs(lat) <= 85.05`), and add a probe at 87° N to the H1 test.

**N2 — Low — No imagery across the antimeridian.** `_view_bbox` clips the unwrapped longitudes to
[−180, 179.999], so the tile range stops at 180° and the far side of the view stays transparent. PoC:
HOME 60° N 179.7° E, every contact east of 180° (51 cases) has nothing under it; the same happens
for Fiji to the west. Fails safe (no wrong ground). The pre-fix placement clipped the same way.

**N3 — Low — Pure-white real imagery (ice sheet, salt flat, bright snow) counts as a placeholder,
is never drawn, and its cache file is deleted, so it is re-downloaded on every build.** Greenland
interior: Esri and EOX give pure-white tiles at z5–z12 (USGS has no coverage past z7), so above z7
nothing is drawn there. Before the fix these were `_blank`, kept as the fallback and drawn white.
Fails safe (map well, no wrong ground), but it costs bandwidth on every pan in polar or salt-flat
areas. Fix: test `_blank` (uniform) before `_placeholder`, so a uniform tile stays the fallback, or
require some mid-grey text contrast for a placeholder.

**L11 — Low — Pre-existing flake seen in the full run:**
`test_cl4_gates::test_n21_stop_after_the_exit_is_recorded_writes_no_kill` (`evs[-1] == 'spawn'`, not
`'exit'`). It failed 1/5 alone while my PoCs loaded the host, then 0/15 on this branch and 0/15 on
`origin/fix/cl8-ship`. This branch does not touch the test, `executor.py` or `netpent.py`. It looks
like an ordering race in the executor audit log under load. Log it separately (it is gate-adjacent);
it does not block this cluster.

**L12 — Low (CM5 cost note) — Reprojection runs in float64 on 1–4 M pixels per pan or zoom,
≈ 1–2 s and ≈ 180 MB transient on a CM5.** It runs on the tile thread (numpy releases the GIL in
the ufuncs), so the GUI stays responsive. A float32 grid, or `OUT_SCALE` 0.75, would roughly halve
both.

## 4. Suite

- `tests/test_ui_polish.py`: **60 passed** (64 s).
- `pyflakes palisade_qt tests/test_ui_polish.py`: clean.
- `test_cl1_screen::test_every_page_and_subtab_fits_1280x720`: **10/10** alone, and passed in the full run.
- Full suite once at `be4221a`, `QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q tests`:
  **1687 passed, 3 failed, 7 skipped, 7 errors** (31 min 46 s; my PoCs shared the 4-core host for part of the run).
  - Baseline: `test_shell.py` ×7 errors (no tkinter), `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
    `test_hwlab::test_doctor_hwbench_check`.
  - `test_cl4_gates::test_n21_…`: pre-existing, load-dependent flake (L11), not this branch.
  - The known flakes (`test_cl1_fix2` ack-all, `test_cl1_screen::test_up_down…`, `test_cl5_fix2::test_nh_panic_banner…`)
    all passed in this run.

## 5. Recommended follow-ups (not blocking)
N1 (transparent past ±85.05°, plus a polar probe in the H1 test), N3 (keep uniform tiles as the fallback), a test for L9,
then L3, N2 and L4.

**Verdict: MERGE**
