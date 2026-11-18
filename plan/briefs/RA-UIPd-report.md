# RA-UIPd — cold re-audit of the RA-UIPc fixes (`fix/ui-polish`)

Auditor: fresh session, no prior context. Head audited: `1e10cc1` (the fix commit; the diff is
`451e877..1e10cc1 -- palisade_qt tests`). Read: `CLAUDE.md`, `device-notes.md`, `RA-UIP.md`,
`RA-UIPc.md`, `RA-UIPc-report.md`, the fix diff, and `plan/audit/REAUDIT_PROMPT.md`. Container venv:
Python 3.13, PySide6, pyqtgraph, numpy, flask, no tkinter, no bleak. I checked the bleak strings
against the bleak 0.22.3 and 1.1.1 wheels, which I downloaded and only read. The PoCs ran as a
scratch pytest file (`tests/test_zz_rauipd_poc.py`), using the suite's own helpers (`_big_hub`,
`_settings`, `_atlas`, `_fix`). That file is **not** committed. Each PoC is summarised below with its
exact output.

**Verdict: DO NOT MERGE.** I found no path where a bad or stale **GPS** fix sets, relabels or
persists HOME. H1's core is fixed: the field is the typed HOME, and a GPS position is never written
as `home`. M2 and the L-items are closed. Two new Highs block the merge:

- **N1:** the L4 fix makes the DRONES view say **"WATCHING — no contacts · DRONES layer on —
  listening" while the Remote-ID scan is off**. That is the *default* state.
- **N2:** M4's "a build started before a HOME change is dropped, never drawn in the new frame" is
  falsified by a queued-signal race. The old image is labelled with the new HOME and drawn offset by
  the move.

## 1. Hard constraints

| Check | Result | Evidence |
|---|---|---|
| Gate files (`engagement.py`, `opprofile.py`, `txguard*`, `executor.py`, `chain.py`, `rfemit.py`), `eventbus.py`, `suite.py` | **Untouched** | `git diff --stat 451e877..1e10cc1` lists only `atlas.py`, `gpshome.py`, `kit/mappanel.py`, `kit/tiles.py`, `panels.py`, `shell.py`, `system.py`, `tests/test_ui_polish.py` |
| `gpshome.py` | **Holds** | The only change makes `usable()` stricter (L3). It still only reads gpsd and only calls `eventbus.set_home(ll, "gps")` |
| Radio / lease / BLE | **Unchanged** | `_toggle` adds two attribute resets before the existing `set_layer` call. `RidSource._scan_ble` is byte-identical apart from the needle table it consults. `tiles._work` only drops a result; it fetches nothing new |

## 2. Per-finding table (RA-UIPc)

| ID | Status | Evidence | Test |
|---|---|---|---|
| **H1** typed vs GPS HOME | **PARTIAL** | Field = `_typed_home()` (store, else a `settings` HOME), never `eventbus.home()` (`system.py:193-198, 314-325`). SAVE while following leaves HOME on GPS when the field equals the typed HOME (`system.py:433-441`). `"home"` is persisted only from the field or the typed HOME (`system.py:474`). Re-ran the three RA-UIPc PoCs: the persisted value stays typed, HOME stays `gps`, follow-off goes back to the typed HOME. **But** "unchanged" is decided by comparing floats: the field shows `%.4f` and the store keeps whatever was typed. With a typed HOME of 6 decimals, an *untouched* field differs, so SAVE snaps HOME back to the typed HOME. See **N3** | `test_uipc_h1_save_never_pins_a_gps_position_as_the_typed_home`, `test_uipc_h1_follow_off_with_nothing_typed_keeps_the_fix_and_says_so` |
| **L2** follow-off status | **CLOSED** | Follow ON→OFF with a GPS HOME: `set_home(field, "settings")`, status "HOME: typed (GPS follow off)". With nothing typed: the fix is kept, `home` is persisted as `None`, and the status and message say "last GPS fix … (not saved)". PoC `h1_follow_off_already_off_gps_home` (follower already disabled, HOME `gps`): back to typed, `settings`, persisted typed | same two tests; `test_u12_follow_off…` (assertion updated to "follow off", matches the new text) |
| **M2** V through the hub | **CLOSED** | `shell.py:602-603`. PoC `m2_v_key_real_events`, real `QKeyEvent` sent to the focused ATLAS map plot: ALL→AIR, `V` (shift)→SEA. In the SETTINGS HOME `QLineEdit` the `v` is typed into the field and the view does not change (`typing` guard, `shell.py:533-551`). On OPS / PRISM / PROWL / RECON, `hub.handle_key(v)` returns False and does nothing (no page `handle_key` acts on `v`: `app.py:285`, `prism.py:319`, `prowl.py:909`) | `test_uipc_m2_v_key_cycles_atlas_views_through_the_hub` |
| **L8** V in KEYMAP | **CLOSED** | `panels.py:794` | same test |
| **M3** needle false matches | **CLOSED** (for the three RA-UIPc strings), see **N4 / L-a** | Exact phrases (`atlas.py:267-276`). PoC `m3_needles`: the three RA-UIPc strings, `org.bluez.Error.Busy/InProgress/NotSupported`, `DBus.Error.AccessDenied/NoReply/UnknownObject` and "Bleak requires BlueZ >= 5.55." all stay faults. NotReady, "No Bluetooth adapters found.", ServiceUnknown/"org.bluez was not provided", "soft blocked" and "Blocked through rfkill" map to the right fix text. **Missed:** bleak's real adapter-off/rfkilled text, "No powered Bluetooth adapters found." (N4). **Near miss:** "failed to open /dev/rfkill: permission denied" → "run: rfkill unblock" (L-a). "passive needs --experimental" is still handled by the PR #25 active fallback (`passive_unsupported`, unchanged) → ACTIVE_NOTE warn | `test_uipc_m3_unrelated_errors_stay_faults` ×4, `test_u14_bluetooth_setup_problems_are_named_with_their_fix` ×4 |
| **L5** raw error in log | **PARTIAL (no test)** | `atlas.py:1133-1136`. PoC `l5_raw_detail_in_log`: the session log reads `"Remote-ID: Bluetooth adapter is off — run: x — [org.bluez.Error.NotReady] Resource Not Ready"`. Correct, but no suite test pins it | none |
| **L6** no-op replace | **CLOSED** | removed (`atlas.py:282`) | n/a (dead code) |
| **L9** "passive scanning" message | **CLOSED** | Needle and message removed. A passive error that is not handed to the fallback is now a fault with its full text | `test_uipc_m3_unrelated_errors_stay_faults[passive scanning failed: EIO]` |
| **M4** moving HOME cost | **PARTIAL → N2** | Slide: `mappanel.py:100-127`. PoC + test: a 0.3 nm move keeps the image, translates the rect by `to_xy(built, new)`, no refetch while `_covers`; a 12 nm move rebuilds. **Geometry** (`geom.py`, worst point on the view edge, 4.99 nm shift, 3 shift bearings, error = drawn vs `to_xy` of the true ground point): default view ±80 nm: **0.14 nm** at 39.6° N (≈0.6 px), 0.30 nm at 60°, 0.47 nm at 70°. Widest (MAX_NM ±600): **1.10 nm** at 39.6° (≈1 px at ~1.3 nm/px), 2.2 nm at 60°, 3.5 nm at 70°, i.e. 0.18 %–0.6 % of the half-span. Acceptable. **Hidden ATLAS:** PoC `m4_hidden_atlas_defers` (real `start_background_feeds`, OPS open): 5 GPS moves → **0** `map.set_home` calls while hidden; opening ATLAS → exactly one, to the latest HOME. **Zoom after a slide:** PoC: `+` → 1 refetch (sigRangeChanged timer), correct. **Stale build:** `tiles._work` drops a result whose HOME changed *before emit*, but `_on_tiles` stamps `_built` from the HOME current at *delivery*, so a build emitted before a move but delivered after it is drawn in the new frame (N2) | `test_uipc_m4_a_small_home_move_slides…`, `test_uipc_m4_a_tile_build_for_a_home_that_moved_is_dropped` (covers the pre-emit drop only); **no test** for the hidden-ATLAS deferral (`_home_pending`) |
| **L1** RID chip after DRONES off | **CLOSED** | `atlas.py:1033-1035` clears chip `rid` and `_rid_note` (ok and warn variants alike) | `test_uipc_lows_gps_error_fields_drone_chip_and_nan_speed` |
| **L3** epx/epy NaN / str | **CLOSED** | `gpshome.py:59-65` | same test |
| **L4** honest empty state per view | **REGRESSED → N1** | `atlas.py:1249-1252`: any non-ADS-B view whose `off` test fails now says "<LAYER> layer on — listening". DRONES's kinds are `("drone", "operator")`, and the OPERATOR layer is on by default, so with the DRONES (BLE scan) layer **off** the view says it is on and listening. DF and SONDE also say "listening" while the same screen's status line reads "DF — · BALLOONS —" | **no test** for L4 |
| **L7** NaN speed | **CLOSED** | `atlas.py:1224-1226` | same lows test |

### Regression sweep of RA-UIPc CLOSED claims

| Claim | Status | Note |
|---|---|---|
| 1a untrustworthy fixes refused | CLOSED (stricter) | `test_u12_untrustworthy…` ×8 green |
| 1b lost fix holds | CLOSED | green |
| 2a view = display filter | CLOSED | `set_view`/`_render` unchanged in that respect |
| 2b honest empty states | **REGRESSED (DRONES)** | N1 |
| 2c selection across views | CLOSED | green |
| 3a / 3b setup warn vs fault | CLOSED | see M3; N4 is a coverage gap, not a regression (the old needles did not match it either) |
| 4a–4e | CLOSED | OPS legend bottom-left in the renders; backcheck tests green |

## 3. New findings

**N1 — High — DRONES view claims "DRONES layer on — listening" while the Remote-ID scan is off
(the default).** `off = not any(k in self._layers for k in kinds)` (`atlas.py:1244`). For DRONES the
kinds are `("drone", "operator")`, and `"operator"` is on by default. OPERATOR contacts only come from
Remote-ID tracks (`atlas.py:112, 214`), so with DRONES off they cannot appear. Before 1e10cc1 the
wrong `off` fell through to the ADS-B text, which was wrong but pessimistic. The new L4 branch turns
it into a positive claim. PoC `l4_sea_view_empty_states`, default layers
`['aircraft', 'balloon', 'df', 'operator']`: DRONES → `WATCHING — no contacts · DRONES layer on —
listening`. The live render `atlas_drones_dark_live` shows the DRONES chip unticked directly above
that text. An operator checking "any drones near me?" gets an all-clear from a scan that is not
running. DF and SONDE say "listening" with no feed ("DF — · BALLOONS —" on the same screen), which is
lesser but the same kind of problem.
Fix: key `off` on the view's *primary* layer (`kinds[0]`), and add a test for each view with that
layer off. Say "listening" only when the layer's source is actually running (RID state `scanning`, a
DF/sonde feed seen); otherwise show its state.

**N2 — High — A tile build emitted before a HOME move but delivered after it is drawn in the new
frame (the M4 claim, falsified).** `TileLayer._work` compares HOME at emit time (`tiles.py:241-245`).
`ready` is a queued cross-thread signal, and `BaseMap._on_tiles` then records
`_built = (tiles.home_lat, tiles.home_lon)`, the HOME at *delivery* (`mappanel.py:129-133`). PoC
`m4_race_ready_after_home_move`: build for A emitted, then `set_home(B)` (3 nm N, a slide, so the rect
becomes y0 −28.0), then the queued A build is delivered. Result: `_built = B`,
`rect = (-25, -25, 50, 50)`. The A imagery is drawn as if centred on B, **3 nm off**. In the slide
path nothing re-fetches (the stale image "covers" the view), so it stays until the next pan, zoom or
rebuild, and later slides compound from the wrong `_built`. A typed-HOME SAVE far away (rebuild path)
shows the old area's imagery under the new frame until the new build lands. The window is the
GUI-thread latency between the worker's check and the slot, so it is rare per build. But GPS moves,
pans and zooms all trigger builds, and the effect is imagery under the contacts in the wrong place,
which is an RA-UIP blocker.
Fix: emit the build's HOME with the array (`ready(arr, x0, y0, x1, y1, hlat, hlon)`), use that for
`_built`, and in `_on_tiles` drop the build, or slide it, when it differs from the current HOME. Add a
test that delivers a queued build after a `set_home`.

**N3 — Medium — SAVE with follow ON and an *unchanged* field snaps HOME back to the typed HOME when
the typed HOME has more than 4 decimals.** `home != typed_before` (`system.py:440`) compares the
`%.4f`-rounded field with the stored value. PoC `h1_unchanged_field_with_more_decimals_snaps_home_back`:
stored `[39.626134, -104.968021]`, HOME `gps` at Boulder, SAVE without touching the field. Result:
HOME `(39.6261, -104.968)`, source `settings`, persisted `[39.6261, -104.968]`, message "applied now:
HOME". HOME sits on the typed spot until the follower confirms two fixes (10–20 s at POLL_S 10), and
the operator's saved precision is truncated without notice. Coordinates copied from a map usually
carry 5–7 decimals. It is labelled `settings`, not GPS, so this is not the RA-UIPc blocker, but it
breaks "an unchanged field must not move HOME".
Fix: compare against the text the field was filled with (`_typed_at_build` is set and never used),
or `QLineEdit.isModified()`, not floats. Show and store the same precision.

**N4 — Medium — bleak's real "adapter off / rfkilled" error is still a fault (MODE red).** bleak
0.22.3 and 1.1.1 `get_default_adapter` raise `"No powered Bluetooth adapters found."`
(`bluezdbus/manager.py:361` / `:376`) when the adapter is powered off or soft-blocked (rfkill clears
`Powered`). None of the needles match it: `"no bluetooth adapters found"` is not a substring. So the
most common setup case on the device turns the strip's MODE red, which is the device-notes complaint
this round set out to fix. It fails safe (a fault, with the full text), hence Medium. The RA-UIPc
needles missed it too. Fix: add `"no powered bluetooth adapters found"` →
"adapter is off or blocked — run: rfkill unblock bluetooth; bluetoothctl power on", with a test.

**L-a — Low — `"rfkill"` is still a bare word.** `"failed to open /dev/rfkill: permission denied"`
→ "Bluetooth is blocked — run: rfkill unblock bluetooth" (wrong advice). Prefer
`"blocked through rfkill"` / `"rfkill"` together with `"block"`.

**L-b — Low — `MoreApp._typed_at_build` is assigned and never read** (`system.py:198`).

**L-c — Low — L4, L5 and the M4 hidden-ATLAS deferral have no regression test.** Per CLAUDE.md, "a
fix with no regression test is not a fix". The PoCs here show L5 and the deferral work today.

Checked and fine (no finding): USE GPS + SAVE persists a GPS position as the typed HOME, but only
after the operator presses USE GPS and SAVE, with "press SAVE SETTINGS to use it" on screen. The
silent launch auto-read runs only when follow is off and HOME is unset, fills only an empty field,
and never saves. The hemisphere check reads only `_gps_last` from USE GPS. Restart with a saved HOME
and no fix → `load_home` → typed HOME, `settings` (PoC `restart`). Demo SAVE with an empty field
leaves the demo HOME alone and persists `None` (PoC `demo`). Editing the field while following:
applied and persisted as typed, the message says "a confirmed fix replaces the typed HOME", and the
follower retakes HOME after two agreeing fixes (PoC `h1_edit_while_following`: confirming → `gps`).
That is what the UI tells the operator.

## 4. Suite

- `pyflakes palisade_qt tests/test_ui_polish.py`: clean.
- `tests/test_ui_polish.py`: **93 passed** (83 s).
- Full suite once at `1e10cc1`: `QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q tests`: **1797 passed, 2 failed, 7 skipped, 7 errors** (38 min 08 s). All container baseline: `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, `test_shell.py` ×7 errors (no tkinter). The known flakes passed this run.

## 5. Renders (1280×720, `QT_QPA_PLATFORM=xcb`, NET OFFLINE)

SETTINGS (follow on; follow off → SAVE, live), ATLAS AIR and DRONES, and OPS, each in dark and light,
live and demo. Live runs used a typed HOME of 39.6261/−104.968 in the store, HOME from `gps` at
39.7001/−104.9002, and the follower running. I inspected them; they are not committed (`*.png` is
gitignored). What they show:
- **SETTINGS follow on:** the field shows the **typed** HOME (39.6261, −104.9680) and the status line
  shows "HOME: GPS 3D fix 39.7001, −104.9002", so the RA-UIPc H1 on-screen symptom is gone.
- **Follow off → SAVE:** "HOME: typed (GPS follow off)", and HOME is back on the typed point.
- **ATLAS DRONES live:** the DRONES chip is unticked while the list says "WATCHING — no contacts ·
  DRONES layer on — listening" (N1).
- **ATLAS AIR / OPS, demo:** glyphs, data blocks and the legend draw as in RA-UIPc. Nothing is clipped.

## 6. Before merge
N1 and N2 (blocking), then N3 and N4, then tests for L4, L5 and the hidden-ATLAS deferral.

**Verdict: DO NOT MERGE**
