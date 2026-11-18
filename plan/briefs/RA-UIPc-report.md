# RA-UIPc — cold audit of UIP round 2 + backcheck fixes (`fix/ui-polish`)

Auditor: fresh session, no prior context. Branch head audited: `8a6f3ae`. The code under audit is
`97c2898` (backcheck), `e07de17` (round 2) and `3b6abe9` (pass re-predict throttle), i.e.
`git diff e7cdf0b..8a6f3ae -- palisade_qt tests`. The `origin/main` merge `e7cdf0b` (PRs #24/#25/#26)
was skipped as instructed. Read: `CLAUDE.md`, `device-notes.md`, `RA-UIP.md`, `RA-UIPb-report.md`,
then the diff. I read `UIP-report.md` only at step 6. Container venv: Python 3.13, PySide6,
pyqtgraph, numpy, no tkinter. PoCs ran as a scratch pytest file using the suite's own helpers
(`_big_hub`, `_settings`, `_atlas`, `_fix`). The file is **not** committed. Each PoC is summarised
below with its exact result.

**Verdict: DO NOT MERGE.** One High (H1): with HOME following GPS, SYSTEM › SETTINGS › SAVE puts
HOME back on a **stale GPS position** (wherever the vehicle was when SETTINGS was first opened). It
labels that position the typed HOME and **persists it**. The common "turn follow OFF, SAVE" flow
then leaves range and bearing measured from a place the operator left miles ago, across restarts.
This falsifies the claim "the GPS HOME is never persisted" (claim 1). I found no path where a *bad*
fix sets HOME (0/0, bools, NaN, mode < 2, large epx/epy and single jumps are all refused). Gate
files are untouched.

## 1. Hard constraints

| Check | Result | Evidence |
|---|---|---|
| Gate files (`engagement.py`, `opprofile.py`, `txguard*`, `executor.py`, `chain.py`, `rfemit.py`), `eventbus.py`, `suite.py` | **Untouched** | `git diff --stat e7cdf0b..HEAD` on those paths is empty |
| `gpshome.py` only reads gpsd and only calls the existing `eventbus.set_home` | **Holds** | Its only side effect is `eventbus.set_home(ll, "gps")` (`gpshome.py:156`). It reads through `suite.gps_fix(timeout=3.0)` (read-only socket). There is no subprocess and no file write |
| No gpsd read on the GUI thread, none in demo, none under the offscreen seam | **Holds** | `GpsHome.poll` reads on a daemon `threading.Thread` and comes back through a queued `_fix_read` signal. `shell.py:170` starts it only when `not demo and not offscreen()`. SETTINGS' auto USE GPS now also skips when follow is checked |
| Radio / lease / BLE behaviour | **Unchanged** except Remote-ID notes | `RidSource` keeps the PR #25 passive → active fallback byte for byte. It only adds a PASSIVE note and reclassifies some exceptions as setup notes (claim 3) |

## 2. Per-claim table

| # | Claim | Status | Evidence | Test |
|---|---|---|---|---|
| 1a | HOME never set from an untrustworthy fix (0/0, bools, NaN, mode < 2, big epx/epy, single jump; first fix of a run and any jump > JUMP_NM need a second agreeing fix) | **CLOSED** | `gpshome.usable` + `_on_fix`. **PoC `jump_then_return`**: following HOME at 39.70/−104.90. Sequence 45/−100 (jump) → 39.7001 → 45/−100 → no fix → 45/−100. HOME never moves, and each lone jump reads "confirming". `suite.gps_fix` also returns only TPVs with integer mode ≥ 2. Minor gaps in L3 | `test_u12_untrustworthy_fixes_never_set_home` ×8, `test_u12_a_single_jump_does_not_drag_a_following_home`, `test_u12_home_follows_a_confirmed_gps_fix…` |
| 1b | A lost fix holds the last HOME and says so | **CLOSED** | `_on_fix` with `usable() is None` → "GPS: no fix — HOME held at the last fix (Ns ago)", warn | `test_u12_home_follows…` |
| 1c | Typed HOME is the fallback, loaded at start; **GPS HOME never persisted** | **REGRESSED → H1** | `system.py:193-195` prefills the HOME field from `eventbus.home()` whatever its source, including `"gps"`. `_save_settings` then calls `set_home(field, "settings")` and persists it (`system.py:411, 432`). See H1 for the three PoCs | none (no test pins non-persistence through SETTINGS) |
| 1d | Follow OFF never touches HOME | **CLOSED (literally), see L2** | `set_enabled(False)` changes only the status. But the GPS HOME stays HOME (source `"gps"`) while the status reads "HOME: manual (GPS follow off)", and the typed fallback is not restored | `test_u12_follow_off_never_touches_home_and_the_choice_is_saved` |
| 1e | HOME consumers on a moving HOME | **PARTIAL → M4** | ATLAS `_on_home_changed` re-projects from stored lat/lon and restarts trails. OPS re-projects on the next tick when `eventbus.home()` changes. OVERWATCH re-predicts only after 5 nm from the last predicted origin for `gps`, and always for a typed HOME. N26 covers key on `home_set()` and still hold. The hemisphere check uses only `_gps_last` from USE GPS, so it is unaffected. No sitrep / other HOME consumer exists in `palisade_qt` (grep). **Cost**: every re-home ≥ 0.25 nm runs `BaseMap.set_home`, which *clears the image* and refetches + reprojects on ATLAS **and** OPS, even when ATLAS has never been opened (M4) | `test_u12_atlas_and_ops_keep_their_contacts_when_home_moves`, `test_u12_small_gps_moves_do_not_repredict_satellite_passes` |
| 2a | A view is a display filter only | **CLOSED** | `set_view` → `setVisible` on layer chips, `feed.set_columns`, `_render`. `_render` touches no `set_layer`, `_layers`, worker, arbiter, BLE or subprocess (code read, full path) | `test_u13_atlas_views_split_the_layers_without_touching_layers_or_radios` |
| 2b | Per-view columns, honest empty states | **CLOSED, see L4** | Renders and probe confirm the columns: AIR FLIGHT/NM/FL/KT, SEA VESSEL/NM/KT/COG, APRS STATION/NM/BRG, DRONES REMOTE-ID/NM/ALT, DF EMITTER/BRG/NM, SONDE SONDE/NM/ALT. "X LAYER OFF" when the view's layer is off. When the layer is on, the empty state still keys on **ADS-B** health (L4) | `test_u13_a_view_with_its_layer_off_says_so` |
| 2c | Selection / detail across views | **CLOSED** | A selected contact that falls out of the view clears the card; LOST only when it is gone from `_contacts` (RA-CL1c F4 holds) | `test_u13_contact_card_clears…` |
| 2d | Keyboard: V cycles views | **OPEN → M2** | **PoC `v_key_through_the_hub`**: a real `QKeyEvent('v')` sent to the focused ATLAS map through the hub leaves the view at `ALL`. The control PoC with `'f'` on the same path toggles the side panel, so the method is valid. `PalisadeHub.handle_key` (`shell.py:522-602`) routes only `[]+-=_`, space, `/ ? r e a m f` to pages; `v` falls through and returns False. The test calls `atlas.handle_key("v")` directly (`test_ui_polish.py:1230`), so it passes. V is also missing from `panels.KEYMAP` (L8) | test does not cover the real path |
| 2e | 1280×720 fit of the side column, every view and theme | **CLOSED** | 42 ATLAS renders (7 views × dark/light/sun × demo/live). In ALL the feed viewport is 176–196 px (≈ 4.4–4.9 rows of 40 px) under the 2-row view bar + 3-row chips. Other views 222–239 px. Side `sizeHint` ≤ side height in every case. No clipping seen | renders below |
| 3a | Setup problems → WARN chip + full text in DRONES + session-log `warn`, never `error`/`fault` | **CLOSED** for the listed cases | `_set_setup` → `on_note` dict → `on_status` sets chip `rid` warn, `_rid_note` shown in full in the DRONES view (render), `sessionlog.record("warn", …)`. `on_error` is not called | `test_u14_bluetooth_setup_problems_are_named_with_their_fix` ×N, `test_u14_a_setup_problem_is_a_warning_in_full…` |
| 3b | An unknown failure is still a fault with full text | **CLOSED** | `_set_fault("Remote-ID BLE scan failed: " + whole text)` → `on_error` → session log `error` (full) + chip truncated at 90 with the full text in the tooltip | same |
| 3c | Needle lists: no false matches | **OPEN → M3** | **PoC `setup_needles`**: `"[org.bluez.Error.Failed] Operation blocked by an ongoing connection"` → "Bluetooth is blocked — run: rfkill unblock bluetooth". `"BleakError: scanner is not ready to be stopped"` → "adapter is off — run: bluetoothctl power on". `"…passive scanning callback raised KeyError"` → "BlueZ refused passive and active scans". Correctly left as faults: `org.bluez.Error.InProgress`, `DBus.Error.AccessDenied` | none |
| 3d | Passive/active fallback from PR #25 unchanged | **CLOSED** | Diff of `_scan_ble` adds only the PASSIVE note after start. `passive_unsupported` and the active retry are unchanged | `test_scan_live` (full suite green) |
| 4a | OPS legend placement at every scope size and with F | **CLOSED** | `PpiScope.resizeEvent` puts it bottom-left. Render: scope 564² → legend (10, 464, 188×90); with F, scope 1252×564 → same corner, nothing over the rings' centre | renders |
| 4b | Data block: aircraft only, KT, bool/NaN refused | **CLOSED (map), see L7 (list)** | `tracksym.data_block` + `_num` | `test_ui_polish` backcheck tests |
| 4c | B6 → drone glyph + colour; balloon glyph | **CLOSED** | `classify` B6 → `drone`; `glyph` maps `drone`; balloon path cached as its own key. Renders show both | `test_u14_balloon_has_its_own_icon`, backcheck B6 test |
| 4d | Contact card clears when hidden, LOST only when gone | **CLOSED** | see 2c | `test_u13_contact_card_clears…` |

## 3. Findings

**H1 — High — SETTINGS SAVE pins HOME to a stale GPS position, labels it typed and persists it.**
`MoreApp` prefills the HOME field once, when the SETTINGS page is built, from `eventbus.home()`
whatever its source (`system.py:193-195`). `_save_settings` then applies the field as
`set_home(home, "settings")` and writes it to `palisade_ui.json` (`system.py:411, 432`). Three PoCs:
- `settings_save_persists_gps_home`: typed HOME 39.70/−104.90, GPS HOME Boulder 40.015/−105.2705,
  SETTINGS opened, SAVE (e.g. to change the theme) → persisted `home = [40.015, -105.2705]`. The
  typed HOME is overwritten on disk.
- `save_while_moving_snaps_home_back`: SETTINGS opened at 39.700, the GPS HOME moved on to 39.725
  (1.5 nm). SAVE → HOME = 39.700, source `settings`. HOME stays on the old spot until the follower
  confirms two new fixes (≥ 10–20 s).
- `follow_off_save_pins_a_stale_gps_home` (the flow `test_u12_follow_off…` exercises): typed T
  39.70/−104.90; GPS G1 Boulder; SETTINGS opened; drive to G2 40.215/−105.1905; uncheck "HOME
  follows GPS", SAVE. Result: HOME = **G1** (≈ 12.6 nm behind the operator, ≈ 21 nm from T), source
  `settings`, persisted `[40.015, -105.2705]`. The message reads "applied now: HOME". Follow is
  off, so it never self-corrects, and after a restart `load_home` loads G1 as the typed HOME.

Every range and bearing on ATLAS and OPS, and the OVERWATCH pass predictions, are then measured from
a place the operator is not, under a label ("typed HOME") that tells them it is theirs. Fix: keep the
field on the *typed* HOME, read from the store and not from `eventbus.home()` when `HOME_SOURCE ==
"gps"`. Only call `set_home(..., "settings")` when the field was edited, or when follow is off and
HOME is not already from GPS. Never write a GPS-sourced HOME to `"home"`. Add a regression test with
all three PoCs.

**M2 — Medium — `V` (cycle ATLAS views) does nothing in the real app.** The hub's key filter
never passes `v` to the page (`shell.py:522-602`; see 2d). The view buttons carry the tooltip "V
cycles the views", but only a direct `atlas.handle_key("v")` works, and that is what the test calls.
Fix: route `v` in `PalisadeHub.handle_key` like `f`, add it to `KEYMAP`, and test it through a real
`QKeyEvent` on the hub.

**M3 — Medium — Setup-needle false matches turn a real fault into a warning with the wrong fix.**
`"blocked"` and `"not ready"` are generic substrings, and `"passive scanning"` matches any
exception text that contains it (see 3c). When one of them matches: MODE does not go red; the
session log gets the *mapped* advice at `warn` and drops the raw error (L5); the raw text survives
only in the chip tooltip. The operator is told to run `rfkill unblock` or `bluetoothctl power on` for
an unrelated failure. Fix: match BlueZ/D-Bus error names (`org.bluez.Error.NotReady`,
`org.bluez.Error.Blocked`/rfkill, `org.freedesktop.DBus.Error.ServiceUnknown`, …) or bleak's exact
messages, not free words. Log the raw detail with the warn. Add negative tests (the three strings
above must stay faults).

**M4 — Medium — Every GPS re-home blanks and refetches the basemap on ATLAS and OPS.**
`BaseMap.set_home` runs `img.clear()` and then `refresh()`. HOME moves at ≥ MOVE_NM = 0.25 nm, i.e.
about every 30 s at 30 kt and every ≈ 17 s at 52 kt (60 mph). Each move blanks both maps for one
build (RA-UIPb L12 measured ≈ 1–2 s on a CM5 from cache, plus network time, and ≈ 180 MB transient
per build). There are two builds per move. ATLAS runs as OPS's hidden background feed, so it refetches even if the operator never
opened it. This fails safe (no imagery is drawn in the wrong place), but on the move the operator
sees the basemap flicker off repeatedly, and the CM5 spends a large share of a core on it. Fix:
keep the old image until the new one is ready (reproject by offset), re-home the imagery only past a
larger threshold (for example 10 % of the view span), and skip the hidden background ATLAS.

**L1 — Low — The "REMOTE-ID: PASSIVE BLE SCAN" chip (state ok) stays after DRONES is turned off.**
PoC `rid_passive_chip_stays_after_layer_off`: after `_toggle("drone", False)` the chip still reads
`{'text': 'REMOTE-ID: PASSIVE BLE SCAN', 'state': 'ok'}`, so it claims a scan that has stopped.
`_toggle` / `_render` never clear chip `rid`. The warn variant (from PR #25) has the same problem.

**L2 — Low — Follow OFF keeps the GPS HOME (source `gps`) while the status reads "HOME: manual
(GPS follow off)".** PoC `follow_off_keeps_gps_home`. The typed fallback is not restored. The
claim's own wording ("never touches HOME") is met, but the status misleads. This compounds H1.

**L3 — Low — `usable()` accepts `epx`/`epy` = NaN or a string (the check is skipped) and accepts
`mode` 2.0.** gpsd emits numbers, so this is latent. The `(0.0, 0.5)` case is accepted by design
(only |lat| and |lon| both < 0.01 count as null island).

**L4 — Low — In SEA / APRS / DRONES / DF / SONDE with the layer on and no rows, the empty state
follows ADS-B health.** With ADS-B down it shows "NO LIVE LAYER" while AIS or BLE are live. With
ADS-B up and the Remote-ID scan in a setup failure it shows "watching / no contacts". The DRONES
notice still shows the setup text.

**L5 — Low — Setup warnings log the mapped advice only.** `sessionlog.record("warn", "ATLAS", text)`
drops `detail`, the raw exception.

**L6 — Low — `setup_problem` does `.replace(" ", " ")`, which replaces a plain space with a plain
space (no NBSP in the source; checked with `cat -A`).** It is dead code.

**L7 — Low — The ATLAS list's KT / FL / ALT cells call `round()` and `%d` on NaN.** PoC: an aircraft
contact with `spd=NaN` in AIR raises `ValueError` in `_render` (`atlas.py:1209`). `adsb_to_contact`
already calls `int(spd)`, so ADS-B cannot produce it today, which makes this latent. It is
inconsistent with `tracksym._num`.

**L8 — Low — `V` is missing from the key map (`panels.KEYMAP`).** It goes with M2.

**L9 — Low — The `"passive scanning"` setup message says "BlueZ refused passive and active
scans".** It is reached only when the passive error was *not* handed to the active fallback, so in
that case the active half of the text is false.

Carried over, not re-tested: RA-UIPb N1, N2, N3 and L3 / L4 / L7 / L12.

## 4. Suite

- `pyflakes palisade_qt tests/test_ui_polish.py`: clean.
- `tests/test_ui_polish.py`: **83 passed** (77 s).
- Full suite once at `8a6f3ae`, `QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q tests`:
  **1787 passed, 2 failed, 7 skipped, 7 errors** (36 min 55 s). All of these are the container
  baseline: `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
  `test_hwlab::test_doctor_hwbench_check`, and `test_shell.py` ×7 errors (no tkinter). The known
  flakes all passed this run.

## 5. Renders (1280×720, `QT_QPA_PLATFORM=xcb`, NET OFFLINE)

ATLAS in ALL / AIR / SEA / APRS / DRONES / DF / SONDE × dark / light / sun × demo / live (live with
five injected contacts, HOME from `gps`); OPS in each theme and mode, plus OPS with F; SETTINGS in each.
I inspected them; they are not committed (`*.png` is gitignored). Observations: the view bar and
chips fit, the DRONES setup notice wraps in full, the OPS legend sits bottom-left on both plates,
and the B6 / balloon glyphs draw. The **live SETTINGS render shows the GPS HOME in the typed HOME
field**: that is H1 on screen.

## 6. Recommended fixes before merge
H1 (blocking), then M2, M3, M4. Then L1, L2 and L7.

**Verdict: DO NOT MERGE**
