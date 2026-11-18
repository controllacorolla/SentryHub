# RA-UIPf — scoped cold re-audit of the RA-UIPe follow-ups (`fix/ui-polish`)

Auditor: fresh session, no prior context. Head audited: `86b1f93`. The scope is
`git diff 8b9fc42..86b1f93 -- palisade_qt tests` (`atlas.py`, `kit/mappanel.py`, `system.py`,
`tests/test_ui_polish.py`). I read `CLAUDE.md`, `RA-UIPf.md`, `RA-UIPe-report.md` (E1–E6), the diff
and `plan/audit/REAUDIT_PROMPT.md`. `RA-UIP.md` and `RA-UIPe.md` are not on the branch. Container
venv: Python 3.13, PySide6, pyqtgraph, numpy, flask. It has no tkinter and no bleak. The PoCs ran
as a scratch pytest file (`tests/test_zz_rauipf_poc.py`) built on the suite's helpers (`_big_hub`,
`_atlas`, `_settings`). That file is **not** committed. Its output is quoted below.

**Verdict: MERGE.** E1, E2, E3 and E4 are closed, each with a regression test. Both RA-UIPe PoCs
for E1 and E3 no longer reproduce through the real `_toggle`, worker and status path. E5 and E6 are
**PARTIAL**, and both are Low. (E5) A second SAVE after clearing the field writes the cleared typed
HOME back to disk when that HOME is still live. (E6b) With no settings store, SAVE still re-applies
an edit that was never persisted. Neither path persists, relabels or moves HOME from a GPS fix, so
neither fails unsafe. I found no High, no Critical and no regression.

## 1. Hard constraints

| Check | Result | Evidence |
|---|---|---|
| Gate files (`engagement.py`, `opprofile.py`, `txguard.py`, `executor.py`, `chain.py`, `rfemit.py`), `eventbus.py`, `suite.py`, `gpshome.py`, `shell.py`, `app.py` | **Untouched** | `git diff --stat 8b9fc42..86b1f93` lists only the 4 files above |
| Radio / lease / BLE behaviour | **Changed only in the DRONES restart, and acceptably** | `RidSource` is byte-identical, and so are the lease sources and `_publish_passive` / `balloon_contacts`. `_reconcile_rid` now stops the scan and starts a new one when the switch generation moved inside one tick. That is the E1 fix itself (the operator asked for a new scan). The scan stays passive and keeps its `or_patterns`. See N-f3 for the brief overlap of the two scans |
| `pyflakes palisade_qt tests/test_ui_polish.py` | clean | |

## 2. Per-item table (RA-UIPe follow-ups)

| ID | Status | Evidence | Test |
|---|---|---|---|
| **E1** DRONES off→on inside one tick | **CLOSED** | The worker's `set_layer(gen=)` (`atlas.py:786-796`) records the app's switch count. `_reconcile_rid` (`:798-819`) stops and restarts the scan when `_rid_live_gen != _rid_gen`. PoC `e1_e3_real_toggle_and_worker` used the real hub, the real `AtlasApp._toggle` and the real `AtlasLiveWorker` thread, with a fake `RidSource` that records starts. Steps: on, then 1.5 s, gave 1 scan. The scan faulted (`EIO`), which gave `_rid_state=fault` and the fault chip `Remote-ID BLE scan failed: EIO`, and the session log printed `[ATLAS] Remote-ID BLE scan failed: EIO`. Off and on back to back (no tick between) cleared the fault chip and set `starting`. 1.5 s later there were **2 scans and the first was stopped**. A late note and a late fault from the old scan both left the view at `starting`, with no `rid` and no `fault` chip. The new scan's PASSIVE note then gave `passive`. The GUI-thread write of `_rid_gen`/`_wanted` racing the worker's read can only cause one extra restart on the next tick, which fixes itself. It can never leave a stale generation running | `test_uipe_e1_drones_off_and_on_inside_one_tick_restarts_the_scan` |
| **E3** old scan's notes/faults | **CLOSED** | `on_status` returns early on `rid_gen != self._rid_gen` (`atlas.py:1183-1184`). That check comes after `layer_off`, `acquiring_layers` and `adsb`, so those keys are never dropped, and the RID emits carry no other keys. `_toggle` bumps the generation on every switch (`:1087`). PoC above, plus the RA-UIPe sequence: off, then a late PASSIVE from the old generation, gives no green chip. On, PASSIVE(new), then a fault from the old generation leaves `passive`. A fault from the new generation gives `fault` and `page_status()['fault']`. **Is anything else fed from `worker.error`?** The relay (`app.py:_Relay`) wires `error` only to `page.on_error`. The fault now arrives as `status.rid_fault` and goes to the same `on_error` (`:1185-1186`), which still calls `super().on_error`: session log `error` (the strip's LIVE ▲ fault mark, visible in the renders) and stderr. The OPS composite reads `page_status()`, and the chip is set the same way as before. `test_cl5_fix::test_fix10…` (direct `on_error`) and `test_cl5_radio::test_e3…` still pass. **Fault chip on DRONES off:** cleared only if its `tip` starts with "Remote-ID" (`:1082-1084`). PoC: after an RID fault, `on_error("ADS-B engine unavailable: x")`, then DRONES off, the ADS-B fault stays. The strip label really goes (checked on the host's `_status_labels` and in the renders below) | `test_uipe_e3_an_old_scans_note_or_fault_is_ignored`, `test_uipd_n1_…` (now through `rid_fault`) |
| **E2** SONDE honest empty state | **CLOSED** (see N-f1, N-f2) | `sonde_feed_state` (`atlas.py:488-502`) and `_view_empty` (`:1362-1371`). PoC: no file gives `none` (`NO SONDE FEED · nothing from the sonde decoder (auto_rx) yet`). `garbage`, empty file, `[]` and `"x"` give `bad` (`SONDE FEED UNREADABLE`). A file 301 s old gives `stale`. A 72 h old file gives `NO SONDE FEED · the sonde decoder file was last written 72h ago — is auto_rx running?`. A fresh file gives `no sondes · sonde decoder feed updated 0s ago`. A future mtime (clock skew) gives fresh with "0s". `_ago` boundaries: 59s, 119s, 2m, 119m, 2h, 72h. Balloons writes the file atomically (`os.replace`), so `bad` is never a torn read. Rendered at 1280×720 in dark and light: the text fits in the empty panel without clipping, and the strip's `BALLOONS —` agrees | `test_uipe_e2_sonde_view_reads_only_a_fresh_parseable_file`, `test_uipd_n1_…` (`UPDATED 0S AGO`) |
| **E4** one rebuild on a raced big move | **CLOSED** | `mappanel.py:141-144`: a stale delivery more than 5 nm from the current HOME refreshes only when `_raw is not None`. Can a stale delivery arrive with `_raw is None` and no fetch for the current HOME? Every write of `tiles.home_lat/lon` is in `BaseMap.set_home` (`mappanel.py:106`, plus the constructor). In `set_home`, every path that leaves `_raw None` calls `refresh()` first. `TileLayer.fetch` either starts a build or parks the request in `_pending`, and `_work`'s `finally` runs `_pending`. So a build for the current HOME is always running or queued. The emit-time HOME check in `_work` drops builds whose HOME moved before the emit. There is no case with no refetch. The test asserts `refreshes == [1]` | `test_uipe_e4_e5_e6_home_field_values_clearing_and_one_rebuild` |
| **E5** clearing the HOME field | **PARTIAL** (N-f4) | `system.py:445, 486-488`. While following with HOME = gps: clear and SAVE gives store `None`, HOME stays at the GPS fix labelled `gps`. Then follow OFF and SAVE gives "HOME stays at the last GPS fix until you type one (not saved)", which is now **true** (store `None`). A third SAVE keeps `None`. **Fails when the typed HOME is the live one (follow off, or following with no fix yet):** clear and SAVE gives store `None` with the live HOME untouched, as designed. A **second SAVE** (any reason, e.g. a theme change) gives store `[39.626134, -104.912345]` again, because `_typed_home()` falls back to the live `settings` HOME. The message never says the typed HOME was unset | E5 half of `test_uipe_e4_e5_e6_…` (following case only) |
| **E6** change judged by value | **PARTIAL** (N-f5) | (a) **Closed:** `39.6261,-104.9123`, ` 39.62610 , -104.91230 ` and `39.6261, -104.9123` each leave HOME at the GPS fix labelled `gps`, with the store at full precision `[39.626134, -104.912345]`. (b) **Open, not addressed:** with no settings store, typing `39.5, -104.8` and pressing SAVE applies it. When the follower retakes HOME (gps) and the operator presses SAVE for something else, HOME goes back to `(39.5, -104.8)` labelled `settings`. `_home_text_shown` still advances only on a successful persist (`system.py:491-492`) | E6 half of `test_uipe_e4_e5_e6_…` (case a only) |

### "No path persists, relabels or moves HOME from a GPS fix"

I checked this against the diff and found it holds. In the `field_changed` / `cleared` logic, the
persisted HOME is always the parsed field, the stored typed HOME, or `None`. It is never
`eventbus.home()` while the source is `gps`. `_typed_home()` returns the live HOME only when its
source is `settings`. USE GPS + SAVE is still an edit: the field gets `40.0500, -105.2000`, and SAVE
gives `(40.05, -105.2)` labelled `settings`, persisted, with the message "applied now: HOME". That is
the explicit operator path RA-UIPd accepted. One pre-existing path, outside this diff and unchanged
by it: with no HOME and follow off, the launch auto-read fills the field ("press SAVE SETTINGS to use
it"), so the next SAVE persists that fix as typed. The operator was told and pressed SAVE, as in
RA-UIPd. It is not a new finding.

## 3. New findings

**N-f1 — Medium (pre-existing, out of this UI cluster's scope, flagged as asked) — stale sondes
are shown as live contacts.** `balloon_contacts()` (`atlas.py:505-526`) republishes every sonde in
`sondes.json` every second, whatever the file's age. PoC: a file with one sonde and mtime 1970 gives
`balloon_contacts` → 1 contact, while `sonde_feed_state` says `stale`. The E2 honesty therefore
covers only the empty view. The common case is worse: Balloons writes only sondes heard in the last
hour (`balloons.py:169-178`), so the file usually holds the last flight's sondes, and they then sit
on ATLAS/OPS as current contacts indefinitely after auto_rx stops. Balloons are not safety-critical,
so Medium. Changing what is published is a data-behaviour change, so it was rightly left out of a
UI-only cluster. **Recommendation:** a separate data ticket. Skip sondes whose `t` (or the file `t`)
is older than `SONDE_FRESH_S`, or mark them stale. `sonde_feed_state` already gives the age to use.

**N-f2 — Low — "NO SONDE FEED" for a decoder that is running but quiet.** Balloons dumps the file
only when a frame changed something (`balloons.py:529-532`). With auto_rx running and no sonde
airborne (most of the day, since launches are about every 12 h), the mtime stays old. The view then
says "NO SONDE FEED · … last written 5h ago — is auto_rx running?". It errs toward saying less, and
the second line is a question, so this is fail-safe. A softer title (`SONDE FEED QUIET`) or a
heartbeat write from Balloons would make it exact.

**N-f3 — Low (unverified on device) — a restart inside one tick overlaps two BLE scans for up to
0.5 s.** `RidSource.stop()` only clears `_on`. The old thread notices within its 0.5 s sleep and
then awaits `scanner.stop()`, while the new `RidSource` is already calling `scanner.start()`. In
bleak each thread has its own loop and BlueZ manager, so these are two D-Bus discovery clients or
monitors. BlueZ allows that, so I expect no error. If the device reports `org.bluez.Error.InProgress`
on a fast off/on, the operator sees `REMOTE-ID SCAN FAILED` (honest, and fail-safe). Check this on
the uConsole.

**N-f4 — Low — E5 remainder: a cleared typed HOME comes back on the next SAVE when it is the live
HOME.** PoC (`e5_clear_then_second_save_repersists`): store `[39.626134, -104.912345]`, HOME
`settings`, follow off. Clear the field and SAVE: the store becomes `None`. The message, "applied
now: event-bus retention · … · persisted: theme, location source", does not say the typed HOME was
unset or that the live HOME stays until restart. SAVE again: the store is
`[39.626134, -104.912345]` again. Cause: `_typed_home()` falls back to
`eventbus.home()` while `HOME_SOURCE == "settings"`, and the second SAVE has `shown == ""`, so it is
not `cleared`. The value is the operator's own old typed HOME, not a GPS fix, so it fails safe.
**Fix:** remember the clear (for example `self._typed_cleared = True` until a value is typed) and
make `_typed_home()` return `None` when it is set, or persist `None` whenever the field is empty and
the store is `None`. Say "typed HOME cleared — the current HOME stays until restart". Add the follow-off
case to the test.

**N-f5 — Low — E6(b) is not addressed.** It is not in the commit and not tested. PoC
(`e6b_no_store`) is as in RA-UIPe: an edit applied with no store, the follower retakes HOME, then any
SAVE gives `(39.5, -104.8)` labelled `settings` again. It happens only on a host with no settings
store (a dev host). It needs an operator edit and is labelled correctly. **Fix:** advance
`_home_text_shown` after the edit is applied, whether or not the persist succeeded. The "NOT
persisted" message already tells the operator.

## 4. Suite

- `pyflakes palisade_qt tests/test_ui_polish.py`: clean.
- Targeted: `tests/test_ui_polish.py tests/test_cl5_fix.py tests/test_cl5_radio.py tests/test_scan_live.py`: **228 passed, 1 skipped** (151 s); `test_ui_polish.py` includes the 4 new RA-UIPe tests.
- Full suite on `86b1f93` (the run in the main checkout, same head, `QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q -p no:cacheprovider tests`): **1808 passed, 2 failed, 7 skipped, 7 errors** (37 min 51 s). That is RA-UIPe's 1804 plus the 4 new RA-UIPe tests. Every failure is container baseline: `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, and 7 errors in `test_shell.py` (no tkinter). The scratch PoC file was not on that run's tree.

## 5. Renders (1280×720, `QT_QPA_PLATFORM=xcb`, LIVE, `PALISADE_OFFLINE=1`, dark and light)

I rendered ATLAS › SONDE with no file, an unreadable file, a file 72 h old and a fresh file, then
DRONES on with a current-generation fault, then DRONES off and on. I inspected them. They are not
committed (`*.png` is gitignored). The SONDE texts are as quoted in §2 and fit the panel in both
themes. The fault render shows `REMOTE-ID SCAN FAILED · Remote-ID BLE scan failed: [Errno 5]
Input/output error`, the red fault chip on the strip and LIVE ▲. After off and on the view shows
`REMOTE-ID STARTING` and the strip shows no fault chip. Harness note: with `processEvents()` alone, a
`deleteLater()`'d strip label stays painted. The renders pump `DeferredDelete`, which matches the
real event loop. The offscreen PoC confirms the label is removed from the host's `_status_labels`.

## 6. Before the next round (not blocking)
N-f4 and N-f5 (Low, each with a regression test). N-f1 goes in a separate data ticket. N-f2 and
N-f3 need a device check.

**Verdict: MERGE**
