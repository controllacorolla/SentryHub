# RA-UIPe — cold re-audit of the RA-UIPd fixes (`fix/ui-polish`)

Auditor: fresh session, no prior context. Head audited: `90fe6b0` (the fix diff is
`c048fe6..90fe6b0 -- palisade_qt tests`). Read: `CLAUDE.md`, `device-notes.md`, `RA-UIP.md`,
`RA-UIPd.md`, `RA-UIPd-report.md`, the fix diff, `plan/audit/REAUDIT_PROMPT.md`. Container venv:
Python 3.13, PySide6, pyqtgraph, numpy, flask, no tkinter, no bleak. I checked the bleak strings
against the bleak 0.22.3 and 1.1.1 wheels, which I only read. The PoCs ran as a scratch pytest file
(`tests/test_zz_rauipe_poc.py`) built on the suite's helpers (`_big_hub`, `_atlas`, `_settings`,
`_fix`). That file is **not** committed. Its output is quoted below.

**Verdict: MERGE.** Every RA-UIPd finding is fixed and has a regression test. I re-ran the RA-UIPd
PoCs on the new head and none of them reproduces. I found no path where a GPS fix sets, relabels
or persists HOME, no High, and no regression of a CLOSED claim. What remains are two Mediums, both
fail-safe: a DRONES off/on inside one worker tick leaves "REMOTE-ID STARTING" up for good, and the
SONDE view says "reading the sonde decoder feed" for any `sondes.json`, even a dead one. There are
also four Lows. All are listed below as follow-ups.

## 1. Hard constraints

| Check | Result | Evidence |
|---|---|---|
| Gate files (`engagement.py`, `opprofile.py`, `txguard.py`, `executor.py`, `chain.py`, `rfemit.py`), `eventbus.py`, `suite.py`, `gpshome.py` | **Untouched** | `git diff --stat c048fe6..90fe6b0` lists only `atlas.py`, `kit/mappanel.py`, `kit/tiles.py`, `system.py`, `UIP-renders/render_views_live.py`, `tests/test_ui_polish.py` |
| Radio / lease / BLE | **Unchanged** | `atlas.py`: the needle table, the `_rid_state` bookkeeping in `_toggle` / `on_error` / `on_status`, `_view_empty`, and `_update_busy` moved earlier in `_render`. `RidSource._scan_ble`, `LeaseSource`, `AtlasLiveWorker` are byte-identical. `tiles.py` only adds the build HOME to the `ready` signal; it fetches nothing new |
| `pyflakes palisade_qt tests/test_ui_polish.py` | clean | |

## 2. Per-finding table (RA-UIPd)

| ID | Status | Evidence | Test |
|---|---|---|---|
| **N1** honest empty state per view | **CLOSED** (follow-ups E1, E2, E3) | `atlas._view_empty` (`atlas.py:1278-1312`) keys on the view's primary layer, and on DRONES on `_rid_state`. PoC `n1_drones_states_via_real_toggle`, default live layers `['aircraft','balloon','df','operator']`, real `_toggle` and real status/error payloads. DRONES off → `DRONES LAYER OFF`. Toggle on → `REMOTE-ID STARTING · the BLE scan has not reported yet`. PASSIVE_NOTE → `no drones heard · passive BLE Remote-ID scan running`. ACTIVE_NOTE (str) → `…active BLE…`. Setup dict → `REMOTE-ID SETUP NEEDED`. `Remote-ID BLE scan failed: EIO` → `REMOTE-ID SCAN FAILED · …EIO`. A later `ADS-B engine unavailable` leaves the RID state alone. Off → `LAYER OFF`, on again → `STARTING` (no stale fault). DF → `NO DF SOURCE` (true: `df_contacts()` is a TODO stub). SONDE with no file → `NO SONDE FEED`. APRS/AIS: radio free → `APRS decoder on the SDR`; PRISM holds → `RADIO BUSY`; acquiring → `ACQUIRING THE SDR`; AIS while APRS holds → `RADIO BUSY`. Error prefixes: every `RidSource` fault (`_set_fault` ×2) and the worker's `Remote-ID (BLE) unavailable` start with "Remote-ID". The only other `error.emit`s (`ADS-B engine unavailable`, `<kind> source unavailable`) don't. **OPS alerts** with `_update_busy` moved up: 3 renders + `on_error` + 2 `on_status` with PRISM holding → exactly one alert each for AIRCRAFT and APRS. Release and retake → one more each. Edge-triggering on `_busy_shown` is unchanged, so there are no duplicates and none missed. The hidden-page branch still calls it only when `_ever_shown`. Live renders below agree | `test_uipd_n1_each_view_says_what_its_own_source_is_doing` (it sets `_rid_state = None` by hand instead of through `_toggle`, and stubs `_update_busy` for the APRS case; my PoC covers both through the real paths) |
| **N2** tiles placed by their own HOME | **CLOSED** | `tiles.py:216,248` emits the HOME captured before the build. `mappanel.BaseMap._on_tiles` (`mappanel.py:130-149`) places the build by that HOME. PoC `n2_queued_delivery_real_thread`: `TileLayer._work` on a real `threading.Thread` emits for A, the thread is joined, then the GUI thread calls `set_home(B)` (3 nm N) before the queued slot runs. Delivered rect `(-40.0, -43.002)` = expected `(-40 + dx, -40 + dy)` of `to_xy(A, home=B)`, `_built = A`. A later slide to C gives rect `(-40.0, -44.203)` = `to_xy(A, home=C)`, with `_built` still A: no compounding. A build for C delivered after a move back to B is placed at `to_xy(C, home=B)` and labelled C. Big move (33 nm) before delivery: `set_home` clears `_raw`; delivery leaves `_raw None`, the image empty and `_built` unchanged (the previous correctly-labelled build). The old image is not left mislabelled. `ready` has one consumer (`BaseMap`, shared by ATLAS `MapPanel` and OPS `ppi.py`); the root-level `tiles.TileLayer(on_ready=…)` callers are the separate Tk module. A torn read of `home_lat/home_lon` by the worker during `set_home` always fails the emit-time equality check, so it is dropped | `test_uipd_n2_a_build_delivered_after_home_moved_is_placed_by_its_own_home` |
| **N3** untouched HOME field | **CLOSED** (follow-ups E5, E6) | `system.py:198-200, 438-441, 483-484`. PoC `n3_cases`, store `[39.626134, -104.912345]`, HOME `gps` at (40.01, −105.27). Untouched SAVE while following: HOME unmoved, `gps`, persisted at full precision, message "HOME follows GPS: a confirmed fix replaces the typed HOME" with no "applied now: HOME". A second untouched SAVE gives the same. Outer whitespace only: unchanged. Follow ON→OFF, untouched → HOME = typed at full precision (39.626134, −104.912345), `settings`. USE GPS then SAVE → applied and persisted as typed (the explicit operator path RA-UIPd accepted; the message says so). A fresh SETTINGS build shows `39.6261, -104.9123`, and an untouched SAVE keeps 6 decimals. SETTINGS is the same object when re-opened, and its field keeps the text that was saved | `test_uipd_n3_an_untouched_field_never_moves_home_or_truncates_the_typed_home` |
| **N4** bleak "No powered Bluetooth adapters found." | **CLOSED** | `atlas.py:274-277`. The string is in bleak 0.22.3 `bluezdbus/manager.py:361` and 1.1.1 `:376`, raised from `get_default_adapter` (called from `scanner.start()`, not `passive_unsupported`, so it is re-raised into `setup_problem`). PoC → "adapter is off or blocked — run: rfkill unblock bluetooth, then bluetoothctl power on". The same holds when wrapped as `BleakError('…')`. It does not shadow "No Bluetooth adapters found." (→ "no Bluetooth adapter found") | `test_uipd_n4_setup_phrases[No powered…]` |
| **L-a** bare "rfkill" | **CLOSED** | `"failed to open /dev/rfkill: Permission denied"` → None (a fault). `"org.bluez.Error.Failed: Blocked through rfkill"` → blocked + fix. The near misses `rfkill unblock failed`, `adapter 'hci0' not found`, `org.bluez.Error.Busy`, `org.bluez.Error.Failed: Not Powered`, the dbus socket ENOENT and `Bleak requires BlueZ >= 5.55.` all stay faults. NotReady and ServiceUnknown still map correctly. Contrived only: `"Unblocked through rfkill"` and rfkill-list text `"Soft blocked: no"` would match. Neither is a bleak/BlueZ exception text, so this is not a finding | `test_uipd_n4_setup_phrases[…rfkill…]` ×2 |
| **L-b** dead `_typed_at_build` | **CLOSED** | `grep -rn _typed_at_build palisade_qt tests` finds nothing. Replaced by the live `_home_text_shown` | n/a |
| **L-c** tests for L4, L5, hidden-ATLAS deferral | **CLOSED** | L4 is covered by the N1 test. L5 and the deferral: `test_uipd_lc_setup_warning_logs_the_raw_error_and_hidden_atlas_defers_its_map` (session log gets `org.bluez.Error.NotReady`; hidden → 0 `map.set_home`, `set_active(True)` → exactly one, to the latest HOME) | that test |

### Regression sweep of RA-UIPd CLOSED claims

| Claim | Status | Note |
|---|---|---|
| H1 (core) / L2 typed vs GPS HOME | CLOSED | `test_uipc_h1_*` green. PoC above: no GPS position is persisted or labelled `settings` without an operator edit or USE GPS |
| M2 / L8 V through the hub | CLOSED | `test_uipc_m2_*` green; `shell.py` / `panels.py` are not in the diff |
| M3 / L9 needles | CLOSED | `test_uipc_m3_*` ×4, `test_u14_*` ×4 green |
| M4 slide / hidden deferral | CLOSED | `test_uipc_m4_*` green; N2 PoC above |
| L1 RID chip cleared with the layer | CLOSED (via `_toggle`); see E3 for a pre-existing race | `test_uipc_lows_*` green |
| L3, L7 | CLOSED | `gpshome.py` untouched; NaN speed path unchanged |
| RA-UIPc 1a–4e | CLOSED | `tests/test_ui_polish.py` 100 passed |

## 3. New findings

**E1 — Medium — DRONES off→on inside one worker tick: the scan is never restarted, and the view
says "REMOTE-ID STARTING" indefinitely.** `_toggle` now resets `_rid_state = "starting"` on every
DRONES-on (`atlas.py:1042`). `AtlasLiveWorker.set_layer` only edits `_wanted`, and `_reconcile_rid`
runs once a step (1 s, `set_layer` does not `poke()`). If off and on both land between two steps,
`want and self._rid is None` is false and the old `RidSource` stays as it is. PoC
`n1_quick_off_on_between_worker_steps` (fake `RidSource` that faults on start): `scans started: 1`.
Two outcomes, both stuck on "STARTING — the BLE scan has not reported yet": (a) the old scan had
**faulted**, the operator's retry gesture silently does nothing, and the fault text that was on
screen is replaced by a "starting" that never resolves; (b) the old scan is running, but no new
note is sent. Neither says "listening" falsely, so it fails safe. Fix: have the worker restart the
scan on a DRONES off→on edge (a generation counter set in `set_layer`, compared in
`_reconcile_rid`), or tag notes/faults with the scan generation and only reset the UI state when a
new scan is actually started.

**E2 — Medium — SONDE says "WATCHING — no sondes · reading the sonde decoder feed" for any
`sondes.json`, even one that is unparseable or decades old.** `_view_empty` tests only
`os.path.exists(_SONDES_PATH)` (`atlas.py:1309`). The cache is written by the Balloons app's
auto_rx listener and stays on disk after auto_rx stops, so the common device state is "file
present, decoder not running". PoC: a file holding `garbage` → `WATCHING — no sondes | reading the
sonde decoder feed`. A valid file with mtime 1970 gives the same. This is the class RA-UIPd N1 named
for SONDE ("listening" with no source), now in "watching / reading" form. Balloons are not
safety-critical, so Medium. Fix: say what the file shows, e.g. `SONDE CACHE STALE — last written
3 d ago` past an age limit, or `SONDE FEED UNREADABLE` when it fails to parse; "reading" only while
it parses and is fresh. Pre-existing, outside this cluster's diff: `balloon_contacts()` republishes
every sonde in the file regardless of age.

**E3 — Low — notes and faults from a stopped Remote-ID scan are applied to the current state.**
`on_status` / `on_error` act on any `rid_note` / "Remote-ID…" error, with no generation and no
`"drone" in self._layers` check. PoC: toggle DRONES off, then a late PASSIVE_NOTE (the old thread's
`scanner.start()` was still awaiting when `stop()` ran) → `_last_status` gets the green
"REMOTE-ID: PASSIVE BLE SCAN" chip while DRONES is off and nothing scans. Also: on again, the new
scan reports passive, then the old thread's late fault → `REMOTE-ID SCAN FAILED` over a running
scan. The window is narrow (BlueZ start latency vs a 1 s step), and the view itself is right while
the layer is off. The chip race predates 90fe6b0. The same generation tag as E1 fixes it.

**E4 — Low — a big HOME move that races a delivery builds the tiles twice.** `set_home` (rebuild
path) calls `refresh()`, and the stale delivery calls `refresh()` again (`mappanel.py:142`). The
first starts a build and the second is queued as `_pending`, so a full second stitch runs (PoC:
`refreshes+ 2`). Hygiene, CPU only. Skip the refresh in `_on_tiles` when `_raw is None` and a fetch
is in flight, or let `TileLayer.fetch` drop a pending request equal to the running one.

**E5 — Low — clearing the HOME field keeps the typed HOME on disk without saying so, and the
follow-off message then contradicts the store.** PoC (following, field cleared, SAVE): HOME stays
`gps`, `home` is persisted as the old typed `[39.626134, -104.912345]`, and the message only says
"persisted: theme, location source". Then follow OFF + SAVE: "HOME stays at the last GPS fix until
you type one (not saved)", although a typed HOME is saved and becomes HOME at the next restart.
There is no way to unset the typed HOME from the UI. This predates 90fe6b0 (the persist line is
from 1e10cc1), but it sits on the same path. Fix: an empty field either clears the typed HOME
(persist `None`) or says "typed HOME kept: 39.6261, −104.9123".

**E6 — Low — "changed" means a different string, not a different value.** (a) A reformat with the
same value (`39.6261,-104.9123`, no space) counts as an edit: HOME leaves GPS for the 4-decimal
point and the store is truncated to `[39.6261, -104.9123]`. (b) After a failed persist,
`_home_text_shown` is not advanced, so on a host with no settings store every later SAVE (for
theme or retention) re-applies the un-persisted edit over a GPS HOME. PoC: `(39.5, -104.8)`
`settings` after the follower had retaken HOME. Both need an operator edit, so this fails safe.
Compare the parsed value with the parsed shown text (and keep the stored precision when they are
equal), not the strings.

## 4. Suite

- `pyflakes palisade_qt tests/test_ui_polish.py`: clean.
- `tests/test_ui_polish.py`: **100 passed** (104 s).
- Full suite once at `90fe6b0`: `QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q -p no:cacheprovider tests`: **1804 passed, 2 failed, 7 skipped, 7 errors** (42 min 01 s). That is RA-UIPd's 1797 plus the 7 new RA-UIPd tests (the scratch PoC file was not collected). All failures are container baseline: `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, `test_shell.py` ×7 errors (no tkinter). The known flakes passed this run.

## 5. Renders (1280×720, `QT_QPA_PLATFORM=xcb`, LIVE, `PALISADE_OFFLINE=1` so NET is offline and no BLE scan opens)

ATLAS DRONES / DF / SONDE / SEA at default layers, then DRONES on (no report yet), DRONES with a
setup note, SEA with VESSELS on, then SETTINGS. Each in dark and light. I inspected them; they are
not committed (`*.png` is gitignored). What they show:
- **DRONES, default:** the DRONES chip is unticked and the list says `DRONES LAYER OFF · switch it on
  above to listen for it`. The RA-UIPd N1 screen is gone.
- **DRONES on:** `REMOTE-ID STARTING · the BLE scan has not reported yet`. Offline, the seam opens no
  scan, so this is the honest state. **Setup:** the full fix text wraps above the list, the list
  says `REMOTE-ID SETUP NEEDED · see the note above`, and the strip says `REMOTE-ID: SETUP NEEDED`
  (warn, not a red fault).
- **DF:** `NO DF SOURCE · direction finding needs a KrakenSDR array — not wired in this build`.
  **SONDE (no file):** `NO SONDE FEED`. The status line still reads "DF — · BALLOONS —", which now
  agrees.
- **SEA, VESSELS on:** `ACQUIRING THE SDR · pausing readsb for VESSELS` with the busy label above
  it ("ADS-B paused — radio held by AIS"). The OPS alert count is 1.
- **SETTINGS:** the field shows the typed HOME `39.7000, -104.9000`, follow on, "GPS follow: not
  running". Nothing is clipped in either theme.

## 6. Before the next round (not blocking)
E1 and E2 (Medium), then E3–E6. Each needs a regression test with its fix.

**Verdict: MERGE**
