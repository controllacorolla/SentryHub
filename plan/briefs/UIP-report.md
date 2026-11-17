# UIP — UI polish from the first device run (`fix/ui-polish`)

Source: Dalton's first hands-on run of `fix/cl8-ship` on the uConsole, 2026-11-16/17
(`plan/briefs/device-notes.md` on `docs/briefs`, plus his messages relayed into this thread).
Branched off `fix/cl8-ship` (PR #24 not merged yet); rebase onto `main` once #24 and #26 land.
Scope frozen 2026-11-17 05:43 (coordinator, agreed); later notes go to a follow-up cluster.

Regression tests: `tests/test_ui_polish.py` (U1–U11). Renders: `plan/briefs/UIP-renders/`
(`render_uip.py`; before = `fix/cl8-ship` head, after = this branch; 1280×720, dark + sun, live;
after-renders fetch real satellite tiles for a Denver HOME with NET=ONLINE).

## What changed, finding by finding

| ID | Device note | Change | Test |
|---|---|---|---|
| U1 (N-ui1) | Key strip labels run together ("4 PROWL5 RECON"), subtitles misaligned | Keys share reference-string baselines (`NavKey.REF_CALL/REF_LABEL`), SIDE 1→5. Then superseded by U8: the keys moved to a left rail | `test_u1_*` |
| U2 | SDR held / ENG active should read green; TX UNLOCKED stays red | `topbar.set_state`: HELD → `live`, ACTIVE → `live` (diamond shape kept); EXPIRED/UNKNOWN/ACQUIRING/TX unchanged. The ENGAGEMENT panel itself still uses amber (D9) — only the strip changed, as asked | `test_u2_*` |
| U3 | Maps too small | ATLAS side column fixed at `SIDE_W`=360 (legend chips 3 per row), map takes the rest; OPS caption moved onto the count row (+30 px scope height) | `test_u3_*`, `test_u4_f_hides_the_ops_rail…` |
| U4 | Menus collapsible on map screens | `PalisadeApp.make_collapsible / toggle_side`, `kit.components.SideToggle` (corner button "FULL MAP · F"), shell routes `F`. Hides the side column, the page's sub-tabs and the left page rail; layout only (workers/feeds untouched); stays above the HOME-NOT-SET cover | `test_u4_*` |
| U5 | Map "somewhere in a desert" | Root cause: the basemap `ImageItem` relied on pyqtgraph's global `imageAxisOrder`, which only PRISM's `ScopePanel` sets to row-major. Opened before PRISM, the tile canvas was read column-major = transposed (Front Range along the bottom). Fix: `ImageItem(axisOrder="row-major")` in `kit/mappanel.BaseMap`. Also: tile rows are now resampled from Web-Mercator to the flat nm frame (`tiles._mercator_rows`): a point 60 nm from HOME drew a neighbouring tile before | `test_u5_basemap_is_north_up…[col-major/row-major]`, `test_u5_atlas_opened_first…` |
| U6 | Can't pan / zoom | Mouse pan + wheel zoom (limits ±600 nm, ≥1 nm), `+`/`−` keys on ATLAS, corner − / + / HOME buttons. Tiles follow the view (`TileLayer.view`, `tiles.tile_span`, ≤ 48 tiles, zoom by screen px). Styles are now DARK SAT / LIGHT SAT (owner) = one satellite fetch, tinted. SAT sources per tile: Esri → USGS → EOX s2cloudless, blank tiles fall through; per-source cache dirs (old cached placeholders never read) | `test_u6_*`, `test_maps_are_dark_or_satellite_only` (updated to the owner's new rule) |
| U6b | OPS home should be dark satellite | `PpiScope` gets the same `BaseMap` (dark tint), centred on HOME; none without HOME (N26 kept) | `test_u5_atlas_opened_first…` (axis order on the OPS scope too) |
| U7 | Location should be automatic | Minimal GPS path only (rest of GPS-fed HOME stays CL6): SETTINGS "USE GPS" reads one gpsd TPV (`suite.gps_fix`, off the GUI thread) and fills the field; SAVE still applies it. With HOME unset (live, not offscreen) one automatic read pre-fills an empty field. A typed HOME in the other hemisphere from this session's fix is refused ("west is negative"). Manual entry unchanged | `test_u7_*` |
| U8 | Page keys stacked vertically on the left | `kit.topbar.NavRail` (128 px, 48 px keys); the strip keeps a "PALISADE · <page>" title + the status slots. 1–9 still switch pages. Each page's sub-tab list is nested under its key in the rail (one navigation column instead of page keys + sub-tab rail + content) | `test_u8_*` |
| U8b | ASSISTANT own page; MESH not buried in SYSTEM | `system.AssistantApp` (8) and `system.MeshApp` (9) — MoreApp showing one view each; only the MESH page runs `MeshWorker`. SYSTEM = SETTINGS, DOCTOR, SITREP, BENCH | `test_folded_pages_live_where_the_brief_put_them` (updated), suite |
| U9 | OPS map empty, even in demo | OPS only consumes ATLAS's bus events, and ATLAS's worker started only when ATLAS was opened. Shell starts ATLAS's worker in the background at launch (`start_background_feeds`, skipped under the offscreen seam). Hidden, `AtlasLiveWorker` now also publishes the PASSIVE feeds (readsb json, sonde cache, Kraken) — still no BLE scan, no lease. `AtlasDemoWorker` no longer pauses when hidden | `test_u9_*` |
| U10 | Planes should look like a C2 track display; colour by type + legend | `kit/tracksym.py`: heading-oriented glyphs (delta, helo, hull, quad, square, cross, ring), velocity leader (2 min at reported speed), 8-point trail, data block "UAL123 FL120". Colours by class: plane, helo (ADS-B category A7), military (readsb `dbFlags` bit 0 / demo `mil`), drone, ship, APRS, sonde, DF; emergency squawk red; unconfirmed RID amber. No heading → ring and no leader. Legend overlay on the map. ATLAS + OPS | `test_u10_*` |
| U11 | No vertical lines between status slots | `QFrame.slot` border removed; 12 px spacing | `test_u11_*` |

## Decisions taken here (flag if wrong)
- **ENG green on the strip** overrides the RA-CL1 amber choice, on the owner's explicit ask; the
  ENGAGEMENT panel keeps amber.
- **"Plane" icon style** is an original delta glyph, not any vendor's symbology.
- **Background feeds:** live ATLAS now reads readsb / sonde / Kraken files while hidden. No radio,
  no lease, no BLE. Auditor: check this is passive-only.
- **SAT sources:** EOX s2cloudless is CC BY-NC-SA 4.0 (non-commercial); attribution is in the map
  style tooltip. Esri stays first because it is serving imagery to the device again.

## Not done (follow-ups)
- Full GPS-fed HOME (live re-centring, source = gps): CL6.
- Which other "lumped" apps to split: waiting on Dalton.
- Device check of everything above on the uConsole (fonts, touch drag, tile speed on the CM5).

## Suite result
Full run, `fix/ui-polish` @ e314abf, container venv (Python 3.13, PySide6 6.8.2.1, pyqtgraph 0.13.7, no tkinter):
`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q tests` -> **1671 passed, 4 failed, 7 skipped, 7 errors** (27 min).
- `test_shell.py` 7 errors, `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`: container baseline (no tkinter / no hw), same on `fix/cl8-ship`.
- `test_cl1_screen::test_up_down_drive_the_list_and_the_detail_follows`: fails the same way on `fix/cl8-ship` head d8149b6 when run alone (3/3; demo PROWL rows reorder between key presses). Passed in the previous full run here. Pre-existing timing flake, not this branch.
- `test_cl5_fix2::test_nh_panic_banner_counts_what_the_pages_stopped`: order-dependent; passes alone on this branch (2/2). Passed in the previous full run.
- `pyflakes palisade_qt`: clean.

## RA-UIP fix-up (commit 90ff886)
RA-UIP: DO NOT MERGE (H1 + M1–M5). Fixed: H1 imagery resampled per pixel into `eventbus.to_xy`'s
AEQD frame (`tiles.aeqd_inverse` / `reproject`), pixel-coded registration test at 60–400 nm, Denver /
Fairbanks / Sydney; M1 `tiles._placeholder` (never drawn, cache file removed); M2 `emergency` flag →
red on MIL; M3/L5 only USE GPS arms the sign check, second SAVE confirms, 2° band, bools refused;
M4/L10 hidden background ATLAS prunes only, draws on show, BUSY alerts once ATLAS was opened; M5
event-filter guard (fit test 0/10 failures, was 2/8; root cause not pinned: `ops.clear_body` takeAt
ruled out); L1/L2 OPS captions shortened; L6 test; L8 `course` drawn, AIS 360/511 ignored; L9 key
map. Open: L3, L4, L7.

Full suite at 90ff886: **1687 passed, 3 failed, 7 skipped, 7 errors** (30 min). Failures: the
container baseline (`test_audit_tiles` undecodable tile, `test_hwlab` doctor, `test_shell` ×7 errors)
and the known `test_cl1_fix2` ack-all flake (flaky on main).

## Round 2 (owner 2026-11-17: "If I asked for it, then do it.") — e07de17, 3b6abe9
Backcheck against `device-notes.md` found 6 partials; all are now in, plus three owner calls:
- **U12 HOME follows GPS** (`gpshome.py`): default ON, SETTINGS checkbox + live status; confirmed
  fixes only (two agreeing fixes for a new run or a > 5 nm jump; 0/0, bools, NaN, mode < 2,
  epx/epy > 250 m refused); re-home at ≥ 0.25 nm; lost fix holds HOME; typed HOME is the fallback;
  GPS HOME never persisted. ATLAS/OPS re-project contacts on a move (no blink); OVERWATCH
  re-predicts passes only after 5 nm.
- **U13 ATLAS views** ALL / AIR / SEA / APRS / DRONES / DF / SONDE: display filter only (no layer,
  lease, BLE or radio change), per-view columns and layer switch, `V` cycles, honest "LAYER OFF".
- **U14 Remote-ID BLE:** setup problems (adapter off, rfkill, no adapter, bluetoothd down, bleak
  missing) are a WARN chip + full text in the DRONES view + session-log warn, never a MODE fault;
  PASSIVE scan reported once `bluetoothd --experimental` is on (device command posted to the owner);
  fault text kept whole (tooltip). Contact card clears when its layer goes off (LOST only when the
  contact is gone). Balloon icon. OPS legend; aircraft data block "CALL FL120 450KT"; ADS-B B6 = drone.

Full suite at e07de17: **1786 passed, 2 failed, 7 skipped, 7 errors** (36 min) — container baseline
only (`test_audit_tiles` undecodable tile, `test_hwlab` doctor, `test_shell` ×7 without tkinter).
3b6abe9 (pass re-predict throttle) adds one test; overwatch tests 23 passed.
Renders: `UIP-renders/views_*_dark_after.png`, `settings_location_dark_after.png`.

## Round 2 fix-up (RA-UIPc → 1e10cc1)

H1/L2 typed vs GPS HOME, M2/L8 V through the hub, M3/L5/L6/L9 exact Remote-ID setup phrases with the
raw error logged, M4 slide-on-small-move + stale-build drop + hidden-ATLAS defer, L1, L3, L4, L7.
Regression tests `test_uipc_*` in `tests/test_ui_polish.py`; pyflakes clean.

Full suite at 1e10cc1: **1797 passed, 7 skipped, 2 failed, 7 errors (38 min)**. All baseline:
`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`,
`test_shell` ×7 (no tkinter in the container). Re-audit: `RA-UIPd`.
