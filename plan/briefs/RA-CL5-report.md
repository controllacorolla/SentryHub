# RA-CL5 — cold re-audit of CL5 (`fix/cl5-radio` @ 85335ea)

**Verdict: DO NOT MERGE.** Five of the brief's blocking conditions reproduce. A radio is released while its decoder still holds the dongle (SSTV, PROWL-SCAN, PROWL NWR/FM). PANIC leaves the radio HELD and the decoders respawn. GUI-thread blocks of 1–2 s remain. Pages claim radio states the arbiter does not hold (NWR reads MONITORING / NO ALERTS while the radio is FREE). BABEL's SSTV mode takes the radio with no RUN and keeps it while the page is hidden.

- Auditor: fresh session, Opus 5.5. Every stage ran on the session model. No subagents (the caller said not to spawn any). Worktree: the agent's own isolated worktree, detached at `origin/fix/cl5-radio` 85335ea.
- Env: Linux, **Python 3.12.3** venv (uv), PySide6 6.12.0, pyqtgraph, flask, numpy, tkinter present. bleak 3.1.0 was added for E3. Renders used `offscreen` with live paths enabled (`QT_QPA_PLATFORM=offscreen:freetype`). PoCs used `minimal`.
- Evidence: `plan/briefs/RA-CL5-evidence/`. It holds the PoC scripts, their `.out` files and `renders/` (1280×720). PoCs use real processes and real threads. Only `radio_arbiter._make_lease` is patched. Fake decoders are in `fakebin/`.
- **The brief got one detail wrong.** The CL5 report says "Base: main @ ef64fcd (CL1 + CL2)". The branch does not contain ef64fcd: its merge-base is `c00f57b` (CL1, before CL2). Because of that, I also built the merged tree `git merge-tree origin/main HEAD` (it merges with no conflicts) and ran the suite and the PANIC PoC on it. The results match the branch.

## Per ID

| ID | Verdict | Evidence | Test |
|---|---|---|---|
| A1 revoke | **OPEN** | The protocol is in `radio_arbiter.py:104-129`. Of 7 holders, 4 break it. **SSTV** has no `revoked` handler (`babel.py:612-750`): after 5 s the arbiter force-frees while rtl_fm still runs, and the next `request` is granted (`poc_revoke.out`, sstv). **PROWL-SCAN**: `_on_revoked` (`prowl.py:97`) does not break `listen_channel`. On an active channel it acks after up to `max_active` 20 s, so the radio is force-freed with rtl_fm alive (`poc_revoke.out`, scan). **PROWL NWR/FM**: `_ensure_lease` releases (`prowl.py:108`) *before* the caller kills the pipeline (`:339`, `:446`). In 3 of 3 runs, NWR on revoke, NWR on hide and FM on hide released with the decoder alive (`poc_release_order.out`). With a real lease that restarts readsb against a busy dongle, which is the original PoC. **ScanWorker.stop()** releases from the GUI thread (`prowl.py:302`) while `listen_channel`'s rtl_fm is alive (3 of 3). BABEL AIS, PRISM and ATLAS ack correctly. | `test_a1_*` cover only the arbiter and ATLAS with a fake pipe. No test for SSTV, SCAN or PROWL ordering. |
| A2 park | **CLOSED** | A worker stuck in an 8 s uninterruptible call is parked after 3 s. The process exits rc 0 with no "QThread destroyed" (`poc_workers.out`, stuck). Closing mid-sleep or mid-retry joins at once. Live hub with BABEL/PROWL/PRISM/ATLAS open: rc 0, empty stderr (`poc_hub_close.out`). Cost: `close()` blocks the GUI 3 s per stuck worker (accepted by design). | `test_a2_*` |
| A3 states | **REGRESSED** (see N1) | `owner()`/`state()` worst case is 0.8 ms during a 3 s acquire. Release during ACQUIRING drops the late lease. A revoke timer after a re-grant to B leaves B holding (`poc_arbiter.out` 1/2/4). **But** every holder treats `request()==True` as "radio is mine" and starts its decoder during ACQUIRING, while readsb is still being stopped (`poc_acquiring.out`: BABEL shows "AIS LIVE", NWR, PRISM and ATLAS-AIS all run their decoder through the 2 s ACQUIRING). Before CL5, `request()` returned only after the lease was held. | `test_a3_*` do not check that a holder waits for HELD |
| A4 Pipeline | **PARTIAL** | No shell in `palisade_qt/`. Groups are killed and stages reaped. A stage that ignores SIGTERM is killed after 1 s. Remaining (`poc_pipeline.out`): (a) a stage's child that ignores SIGTERM survives because SIGKILL is only sent if a *direct* stage outlives the grace period (`kit/procs.py:73`), and `terminate()` still returns True. (c) a stage that forks and exits: `_signal` skips groups whose leader has exited (`:89`), so the grandchild survives. (e) if stage N's binary is missing, stage 1 is left running (`:35`, no cleanup). (d) a `setsid` grandchild survives: a known limit, Low. | `test_a4_*` |
| A5 | **CLOSED** | `more.py` is gone. Nothing references `_acquire_lease`. | `test_a5_*`, `test_palisade_qt::test_base_class_never_touches_the_dongle` |
| A6 bus | **PARTIAL → new High (N5)** | A publisher mutating after publish no longer reaches the log. PySide hands each subscriber its own dict copy. `publish()`'s return value aliases the log entry (Low). The bounded backlog drops the **newest** events silently, and `test_a6` pins that drop (`dropped() >= 7`). | `test_a6_bus_copies_bounds_and_resizes` |
| R1 | **OPEN** | AIS/POCSAG and the other DecoderWorker modes now need RUN and release on hide (`poc_babel.out`, r1 AIS). **SSTV** (`SstvWorker` has no `set_running`/`set_active`) takes the radio with RUN off and keeps it while hidden. `PAUSE_WHEN_HIDDEN` pauses the worker, but `Recorder` keeps rtl_fm running (`poc_babel.out`, r1 SSTV; `renders/babel_stress_sstv_*`). | `test_r1_*` covers DecoderWorker only |
| R2 | **CLOSED** | A decoder that exits at once gives 1 acquire and 0 releases in 10 s. FAULT is shown with stderr ("usb_claim_interface error -6 — retry in 8s") (`poc_babel.out`, r2; `renders/babel_stress_fault_*`). | `test_r2_*` |
| R3 | **OPEN** | The poll catches a decoder that exits by itself. But after a revoke, or a forced free on timeout, the NWR page still reads **MONITORING**, the green chip "NWR WX2 162.400M" and **NO ALERTS**, with the SDR slot FREE and no decoder (`renders/prowl_stress_nwr_after_revoke_{dark,sun}_live.png`). A dead weather receiver looks healthy. There is no audio level meter. Last-heard age only appears after multimon output, which is silent in normal operation. | `test_r3_*` (death path only) |
| R4 | **CLOSED** (ordering vs release: see A1) | `_respawn` → `Pipeline.terminate` waits before the respawn. | `test_r4_*` |
| R5 | **PARTIAL** | File size is capped at 240 s and written under `CACHE`. The whole 240 s window (11.5 MB at 24 kHz) is still decoded every 12 s, not "only new audio". `flush()` (`sstv.py:134`) rewrites the full window every 5 s, about 2.3 MB/s or roughly 8 GB/h of flash writes, against 173 MB/h before (Medium, N9). The same frame is re-emitted on each pass while it stays in the window. | `test_r5_*` |
| E2 | **CLOSED** | Default bank is GMRS/FRS. `max_active` is 20 s. Skip/lockout works. | `test_e2_*` (2) |
| E3 | **PARTIAL** | Opt-in works: opening ATLAS starts no BLE scan. **Passive mode never runs on Linux.** bleak/BlueZ raises "passive scanning mode requires bluez or_patterns" (`poc_e3_bleak.out`, bleak 3.1.0), so DRONES can never scan on the uConsole. The fault reaches only stderr, because `AtlasApp` has no `on_error` and the base class prints. The test calls `_set_fault` by hand. | `test_e3_*` |
| B1 | **CLOSED** | 3 decimals and a step menu. | `test_b1_*` |
| B2 | **PARTIAL** | Live squelch is wired to the engine. Side effect: a squelch change returns `"retune"`, which `if result:` (`prowl.py:254`) records as a hit. An empty channel shows ACTIVE for 30 s, and the scanner moves on instead of re-listening (`poc_b2_retune.out`). | `test_b2_*` |
| B3 | **CLOSED** | Epoch seconds. | `test_b3_*` |
| §15.1 Workers | **CLOSED** | Wait is on a condition. Pause when hidden. Backoff with one fault. | `test_worker_*`, `test_workers_pause_while_their_page_is_hidden` |
| RA-MAIN-1 F1 | **CLOSED** | `test_strip_fits_1280_with_a_huge_scope` asserts ≤ 1270 in all modes and passes on Linux/FreeType with Plex loaded (py3.12, branch and merged). Renders show strip min 1078–1123 in normal states. | `test_cl1_fix3::test_strip_fits_*` |
| RA-MAIN-1 F2 | **CLOSED (claim refuted)** | `_HERE` in `theme.py:11` is the repo root, so `load_fonts` reads `<repo>/fonts/`. | `test_cl1_fix3::test_bundled_plex_fonts_are_loaded` |

## Blocking (per the brief)

1. **Radio released while the decoder still holds the dongle** (A1 above): SSTV, PROWL-SCAN, PROWL NWR/FM. Evidence: `poc_revoke.out`, `poc_release_order.out`.
2. **PANIC leaves the radio held, and decoders come back.** `hub.panic()` reports "2 of 2 child process(es) stopped (verified gone)". The arbiter stays `HELD`. BABEL respawns rtl_ais about 2 s later and NWR about 0.5 s later. Reproduced on the branch and on the merged main+CL5 tree (`poc_panic.out`). PANIC never revokes or releases the arbiter.
3. **GUI-thread blocks.** ATLAS acks a revoke synchronously on the GUI thread (`atlas.py:386`): `Pipeline.terminate` plus the lease release took 2.00 s with a 2 s release, which stands in for `sudo systemctl start readsb`. BABEL hide, STOP and revoke each block the GUI thread for 1.00 s when a stage ignores SIGTERM (`babel.py:386-402` → `Pipeline.terminate`) (`poc_gui_block.out`, `poc_arbiter.out` 5).
4. **Pages claim states the arbiter does not hold.**
   - N1: BABEL shows LIVE and STOP with decodes while the arbiter is ACQUIRING (`renders/babel_stress_acquiring_*`).
   - PROWL NWR, FM, SCAN and PRISM emit no status after a revoke, so they keep "NWR … ok / FM 97.3 ♪ / SDR PRISM" with the radio FREE (`renders/prowl_stress_nwr_after_revoke_*`).
   - SSTV keeps "capturing" after a forced free (`renders/babel_stress_sstv_after_forced_free_*`).
5. **R1: the radio is taken with RUN off and held while hidden** (SSTV).

## New findings (not in the 93)

| # | Sev | Finding | Evidence |
|---|---|---|---|
| N1 | **High** | A3 regression: every holder starts its decoder during ACQUIRING and says LIVE. On the device, `RtlLease.acquire` kills `RTL_USERS` (`suite.py:483-489`), which includes `rtl_fm`/`rtl_433`/`acarsdec`. So the acquire can kill the holder's own just-spawned decoder, and the decoder opens the dongle while readsb is still being stopped. Holders must wait for `state()==HELD`. | `poc_acquiring.out`, renders |
| N2 | **Critical** | NWR reads MONITORING / NO ALERTS with a green chip after revoke or forced free. This is a false all-clear on the safety use. | `renders/prowl_stress_nwr_after_revoke_*` |
| N3 | High | PANIC does not release the arbiter, and pages respawn decoders after it (item 2 above). | `poc_panic.out` |
| N4 | High | Release before kill in `_RadioWorker._ensure_lease` (`prowl.py:104-109`) and in `ScanWorker.stop` (`:302`). | `poc_release_order.out` |
| N5 | **High** | The EventBus backlog cap drops the newest events silently, and nothing reads `dropped()`. A Tornado Warning published during a 3.6 s GUI stall with 300 contacts/s never reaches the AlertStore or drawer (`store has TOR: False`). It is only in the log. This breaks CL1's "an unacknowledged alert is never discarded". | `poc_alert_drop.out` |
| N6 | Medium | Opening BABEL (folded under PROWL) briefly fronts PROWL SCAN, which requests and releases the radio. On the device that is a spurious readsb stop/start. | `poc_babel.out` (PROWL-SCAN acquire/release at 1.06/1.13 s); RADIOS history in `renders/radios_stress_revoke_pending_sun_live.png` |
| N7 | Medium | Pipeline: `terminate()` returns True with survivors. Group signalling is skipped after the leader exits. A failed later stage leaks stage 1 (A4 row). | `poc_pipeline.out` |
| N8 | Medium | E3 passive mode fails on BlueZ, so Remote-ID never scans on the device. Failures reach stderr only. | `poc_e3_bleak.out` |
| N9 | Medium | SSTV rewrites the full 11.5 MB window every 5 s (about 8 GB/h of flash writes) and re-decodes it every 12 s, with duplicate frames and events. | `sstv.py:118-148` |
| N10 | Medium | A B2 squelch change fabricates an ACTIVE hit. | `poc_b2_retune.out` |
| N11 | Low | The RADIOS history logs `state()` when the queued slot runs, so a fast acquire logs HELD, HELD instead of ACQUIRING, HELD. | render above |
| N12 | Low | `_revoke_expired` → `release(holder)` is not generation-checked. A same-name re-grant inside that window could be freed. Not reproduced in 400 runs; code-level only (`radio_arbiter.py:121-129`). | `poc_arbiter.out` 3 |
| N13 | Low | Workers never disconnect `arbiter.revoked`, and they are retained forever, so connections accumulate. `publish()` returns the logged dict (aliasing). Legacy Tk paths still use `shell=True` (`aprs.py:705`, `ais.py:312`, `nwr.py:180`). | grep |
| N14 | Low | A test has a vacuous assertion: `"RELEASE REQUESTED" in … if hasattr(holder, "rows_text") else True` (`test_cl1_screen.py`, radios panel test). `rows_text` does not exist, so the check is always True. | grep |

## Test assertions vs main

- The CL5 test changes, diffed against the merge-base `c00f57b`, are the 3 announced rewrites plus F1/F2.
  - `test_decoder_pipelines_start_in_their_own_session` still proves its claim for `Pipeline` users.
  - `test_babel_live_mode_…` proves ownership but not HELD-before-run (N1).
  - `test_overwatch_radio_director_…` now proves only the forced-timeout path.
- `test_cl1_fix3` "999 targets" → "999 tgts" is justified by F1.
- `test_a6` newly pins silent dropping (N5).
- Diffed against `ef64fcd`, the CL2 tests look deleted. They are not: the branch predates CL2. The merged tree keeps them, and they pass.

## Suite and lint (Python 3.12.3)

- Branch: **4 failed, 1017 passed, 3 skipped** (`suite_py312_branch.txt`).
- Merged main+CL5: **4 failed, 1279 passed, 5 skipped** (`suite_py312_merged_main.txt`).
- The same 4 fail in both: the 3 known baseline failures plus `test_cl1_screen::test_up_down_…`. That last one also fails on main (ef64fcd) when its file runs in order, so it is pre-existing and order-dependent.
- pyflakes: the touched files are clean except 2 old warnings in `aprs.py` (also on base).

## Renders

`plan/briefs/RA-CL5-evidence/renders/`, all 1280×720, live, dark and sun:
- idle: prowl, babel, atlas, radios
- stress: `babel_stress_acquiring`, `radios_stress_acquiring`, `radios_stress_revoke_pending`, `radios_stress_forced_free`, `babel_stress_sstv_after_forced_free`, `babel_stress_fault`, `prowl_stress_nwr_after_revoke`

The script is `render_racl5.py`.

## Fix list for CL5-fix

1. Holders start the decoder only on HELD and show ACQUIRING until then.
2. Kill, then wait, then release in every PROWL path, including `ScanWorker.stop`.
3. SSTV gets `revoked`/RUN/hide handling.
4. SCAN's revoke breaks `listen_channel`.
5. PANIC revokes or releases the arbiter and stops pages from respawning (e.g. clear RUN/active).
6. Move the revoke ack and `_kill_proc` off the GUI thread.
7. Every holder emits a FREE/STOPPED status on give-back; NWR never shows MONITORING / NO ALERTS without a live decoder.
8. The bus never drops `alert` events (bound contacts only, or catch up from the log).
9. Pipeline: SIGKILL the groups after grace whenever any group member remains; clean up on a partial start.
10. E3: pass `bluez={"or_patterns": …}` for passive mode, and show faults in the UI.
11. Treat B2 `"retune"` as not-a-hit.
12. SSTV: decode only new audio and append rather than rewrite.

Each fix needs a regression test from the matching PoC above.

**DO NOT MERGE**
