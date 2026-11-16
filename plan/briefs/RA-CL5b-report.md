# RA-CL5b — cold re-audit of CL5-fix (`fix/cl5-radio` @ 510359e)

**Verdict: DO NOT MERGE.** Most of the twelve fixes hold up under real processes and threads. PANIC is now clean for every holder: 116 raced iterations, 0 violations. NWR never read LIVE without a held radio and a running decoder. Kill → wait → release holds in every PROWL path, and decoders wait for HELD.

Three blocking conditions remain. Two of them are new: the fix introduced one and left the other in place.

1. **ATLAS: the radio is released while its decoder is still running.** CL5-fix 6 moved ATLAS's revoke acknowledgement into `LeaseSource.poll()` on the worker thread. `AtlasLiveWorker` keeps the default `PAUSE_WHEN_HIDDEN = True`. So once the operator leaves ATLAS with AIS or APRS on, a revoke (RADIOS › FREE THE RADIO, or any page asking for the radio) is never acknowledged. After 5 s the arbiter force-frees with rtl_ais still running. The next requester is granted while rtl_ais holds the dongle. The RADIOS panel says "FREE — any layer may acquire". rtl_ais keeps running until ATLAS is shown again. At `ed4694a` ATLAS acknowledged on the GUI thread, so this case worked there.
2. **PROWL sub-mode switch blocks the GUI thread and can abort the process.** `_switch_submode` runs `stop()`, then `wait(3000)` on the GUI thread, then `self._worker = None` even when the wait timed out. The GUI blocks for the full kill plus lease release (2.0–3.0 s). If that takes more than 3 s (a stage that ignores SIGTERM plus a 2.2 s `systemctl start readsb`), the running QThread is dropped and the hub dies with SIGABRT (`QThread: Destroyed while thread '' is still running`). The decoder-type switch in BABEL (text ↔ SSTV) also blocks for 3.0 s, but it parks the worker instead of dropping it.
3. **GUI-thread block** (brief rule): item 6 is closed for RUN, hide and revoke, but not for mode switches (item 2 above).

Details:

- Auditor: fresh session, Opus 5.5. Own worktree, detached at `origin/fix/cl5-radio` 510359e. No subagents.
- Environment: Linux, **Python 3.12.3** venv (uv), PySide6 6.12.0, pyqtgraph, flask, numpy, bleak, tkinter.
- PoCs: `QT_QPA_PLATFORM=minimal`, real processes and threads. Only `radio_arbiter._make_lease` is patched, apart from the fault injections named in each script. They use RA-CL5's fakes (`RA-CL5-evidence/fakebin`).
- Renders: `offscreen:freetype`, live seams open.
- Evidence: `plan/briefs/RA-CL5b-evidence/`. The re-runs of RA-CL5's PoCs are in `rerun/`. The new PoCs, their `.out` files and `renders/` are next to them.

## 1. RA-CL5 PoCs re-run against 510359e (`rerun/`)

| PoC | RA-CL5 | Now |
|---|---|---|
| `poc_revoke` babel/sstv/scan/fm/nwr/prism | forced free with decoder alive (sstv, scan) | **clean**: every holder acknowledges, and no decoder is alive at release |
| `poc_revoke` atlas | clean (GUI-thread ack) | the PoC drives `AisSource` without `poll()`, so the new design never acknowledges there. Re-derived through the real hub as `poc_atlas_hidden_revoke` → **REGRESSED** (blocking 1) |
| `poc_release_order` (NWR hide/revoke, FM hide, SCAN stop, BABEL stop ×3) | release before kill, 3 of 3 runs | **clean** in all 15 runs: `alive at release=[]` |
| `poc_panic` babel, nwr | arbiter stayed HELD, decoders respawned | **clean**: FREE and stays FREE, no child processes |
| `poc_acquiring` | decoder ran during ACQUIRING | **clean**: no child until HELD; the chip reads "AIS ACQUIRING radio" |
| `poc_gui_block` (BABEL hide/STOP/revoke, stubborn stage) | 1.00 s each | **0.00 s** each; the release still waits for the stage |
| `poc_arbiter` 1–5 | 3 = code-level N12 | clean; 0 of 400 for N12; ATLAS revoke on the GUI thread takes 0.00 s |
| `poc_alert_drop` | TOR dropped | **clean**: `alert store has the TOR warning: True` |
| `poc_eventbus` | aliasing, newest dropped | clean: no aliasing; 1500 of 1500 alerts delivered after the stall |
| `poc_pipeline` a/b/c/e | survivors in a, c, e | **clean**. (d) a `setsid` grandchild still survives while `terminate()` returns True. This is a known limit (Low). |
| `poc_workers`, `poc_hub_close` | clean | clean. The stray `sleep` pid after the hub exits is the fake's 0.2 s sleep; it is the same at `ed4694a`. |
| `poc_babel` r1 | SSTV took the radio with RUN off and kept it while hidden | **clean**: FREE, "SSTV IDLE — press RUN" |
| `poc_babel` r2 | FAULT with stderr ("usb_claim_interface error -6") | **REGRESSED**: "AIS decoder exited after 0.0s (×3) — retry in 8s". The stderr tail is gone (N-b below). |
| `poc_b2_retune` | an empty channel was shown ACTIVE | **clean**: no row is emitted and the same channel is re-listened. The old script crashes on the empty row list, so a corrected copy is in `poc_b2_retune.py`. |
| `poc_e3_bleak` | passive refused on BlueZ | No BlueZ in this container (`[Errno 2]`). The fault is now surfaced. The kwargs are only verified by `test_fix10` against bleak; **this still needs validation on the device**. |

## 2. Per item

| ID | Verdict | Evidence | Test |
|---|---|---|---|
| 1 HELD before decode (N1) | **CLOSED** | `poc_acquiring` clean. `poc_panic_race`: 28 of 108 iterations hit ACQUIRING, 0 violations. Every holder checks `held_by` after spawning, except ATLAS (`atlas.py` `LeaseSource.poll`: there is no re-check after `_open_pipe`, so a revoke or PANIC landing between `state()` and `Popen` leaves rtl_ais running until the next poll). That is code-level only, Low. | `test_fix1_*` (6) |
| 2 kill→wait→release, PROWL (N4) | **CLOSED** | `poc_release_order` 15 of 15 clean. `prowl.py` `_give_back` / `_finish`. | `test_fix2_*` (5) |
| 3 SSTV RUN / hide / revoke (R1) | **CLOSED** | `poc_revoke sstv` clean; `poc_babel r1` clean; `poc_panic_race sstv` 12 of 12 clean | `test_fix3_*` |
| 4 SCAN revoke | **CLOSED** | `poc_revoke scan` clean | `test_fix4_*` |
| 5 PANIC (N3) | **CLOSED** | `poc_panic_race`: babel_ais, babel_pocsag, sstv, nwr, fm, scan, prism, atlas_ais, atlas_aprs × 12, plus hidden ATLAS × 8. The acquire took a random 0–0.6 s and PANIC landed at a random 0–1.2 s. **0 violations**: the arbiter was FREE and no child or zombie remained for 2.5 s after. Hygiene (Low): the banner says "no child processes were running" when the page's own `terminate_async` (fired from `on_panic`) reaped the decoder before the tree scan (`renders/babel_after_panic_*`). | `test_fix5_*` (2) |
| 6 GUI-thread blocks | **OPEN** | RUN, hide and revoke take 0.00 s (`poc_gui_block`). **Mode switches still block**: PROWL NWR→FM blocks 2.02 s and FM→SCAN 2.01 s (with a 2 s release), and BABEL AIS→SSTV blocks 3.01 s and parks the worker (`poc_gui_block_modeswitch.out`). Past 3 s the PROWL switch **aborts the process** (`poc_submode_drop.out`: rc −6 with a 3.5 s release, and rc −6 with a SIGTERM-ignoring multimon plus a 2.2 s release). PANIC blocks 1.03 s (stop_tree), which is accepted for an emergency stop. Moving ATLAS's acknowledgement off the GUI thread broke A1 (row A1). `test_fix6_stop_hide_and_revoke_never_block_the_gui_thread` **passes on `ed4694a`** in 4 of 5 runs here, so it does not pin the fix. `test_fix6_atlas_revoke_ack_is_off_the_gui_thread` calls `poll()` by hand, so it cannot see a paused worker. | weak |
| 7 honest give-back / NWR (N2) | **CLOSED** (see R3) | `poc_nwr_safety`, 10 scenarios through the real hub, sampled every 0.1 s: revoke, forced, panic, hide, submode, stall and stall_revoke (the holder never acknowledges, so the free is forced). **0 samples** read LIVE or NO ALERTS without HELD(PROWL-NWR) and a live decoder. The stalled worker reads NOT MONITORING after 3 s, before the forced free. decoder_dies: 2 of 80 samples read LIVE in the ≤ 0.5 s between a stage exit and the next 400 ms step (detection latency, Low). Renders `prowl_nwr_live_*` and `prowl_nwr_after_revoke_*` are honest. | `test_fix7_*` (6) |
| 8 bus alerts (N5) | **CLOSED** | `poc_alert_drop` TOR delivered; `poc_eventbus` 1500 of 1500 alerts. Alert-only traffic is not bounded during a GUI stall. That is by design and Low. A throwing subscriber is a separate queued slot invocation, so it does not stop delivery. | `test_fix8_*` |
| 9 Pipeline (N7) | **CLOSED** (known limit) | `poc_pipeline` a, b, c, e clean. Two Low items remain: (d) `setsid` survives while `terminate()` returns True, and `_signal` keeps signalling `sids` whose leaders were reaped by an earlier `poll()` until `_done` (a pgid-reuse window between a stage exiting by itself and `terminate()`; code-level). Concurrent `terminate()` (GUI `terminate_async` plus the worker) was exercised in every BABEL run without error. | `test_fix9_*` (3) |
| 10 E3 BlueZ (N8) | **CLOSED pending device** | The or_patterns kwargs are present. The fault chip appears on the page. This container has no BlueZ, so the real scan was not run. | `test_fix10_*` (2) |
| 11 B2 retune (N10) | **CLOSED** | `poc_b2_retune.out` (corrected copy) | `test_fix11_*` |
| 12 SSTV new audio (N9) | **PARTIAL** | Append-only (48 kB/s, about 173 MB/h, against about 8 GB/h before) and a new-audio window: both true. **But** (a) a decode that finishes after `_stop_rec()` writes the old recorder's sample clock back. The next RUN then does not decode until it has recorded as long as the previous session plus 12 s (`poc_sstv_stale_decode.out`: 2412 s instead of 12 s) (Medium). (b) It **regresses the Tk `sstv.py` app**, which decodes `r.path` on stop. A PD120 frame recorded across the 240 s rotation is split between `.prev.wav` (148 lines) and `.wav` ("no SSTV header"). The same capture decodes all 496 lines at `ed4694a` (`poc_tk_sstv_rotation.out`) (Medium). (c) "found a header but no usable line syncs" does not advance `_scan_from`, so a false VIS lets the window grow back to 240 s per decode (Low). | `test_fix12_*` (2) |
| N1 / N2 / N3 / N4 / N5 / N10 | CLOSED | = items 1 / 7 / 5 / 2 / 8 / 11 | |
| N7 | CLOSED (known limit) | = item 9 | |
| N8 | CLOSED pending device | = item 10 | |
| N9 | PARTIAL | = item 12 | |
| N11 | OPEN (follow-up) | RADIOS history still logs HELD, HELD; it shows no forced-free marker (`renders/radios_after_atlas_hidden_revoke_*`) | — |
| N12 | CLOSED | `_release(name, gen)`; `poc_arbiter` 3: 0 of 400 | covered by `test_a3_*` and `poc_arbiter` |
| N13 | PARTIAL | `publish()` returns a copy, and workers disconnect at the end of `run()`. Tk `shell=True` remains. | — |
| N14 | OPEN (follow-up) | The vacuous assertion is unchanged | — |

### Re-rated from RA-CL5's table

| ID | RA-CL5 | RA-CL5b |
|---|---|---|
| A1 revoke | OPEN | **REGRESSED**: hidden ATLAS never acknowledges and is force-freed with rtl_ais alive (`poc_atlas_hidden_revoke.out`). Every other holder is clean. |
| A3 states | REGRESSED | **CLOSED** (item 1) |
| A4 Pipeline | PARTIAL | **CLOSED** (setsid limit, Low) |
| A6 bus | PARTIAL | **CLOSED** |
| R1 | OPEN | **CLOSED** |
| R2 (not on the list; re-run anyway) | CLOSED | **REGRESSED** (N-b): the FAULT no longer shows the decoder's stderr |
| R3 | OPEN | **PARTIAL**: honest on revoke, forced free, PANIC, hide, stall and death. A wedged rtl_fm (alive, no samples) reads LIVE · NO ALERTS indefinitely. A decoder that dies every 2 s never escalates (`_down` resets on each respawn) and reads LIVE about 80 % of the time (N-d). |
| R5 | PARTIAL | **PARTIAL / REGRESSED** for the Tk app (item 12 b) |
| E3 | PARTIAL | **CLOSED pending device** |
| B2 | PARTIAL | **CLOSED** |

## 3. New findings (not in RA-CL5)

| # | Sev | Finding | Evidence |
|---|---|---|---|
| N-a | **High, blocking** | Hidden ATLAS never acknowledges a revoke. `AtlasLiveWorker` is paused when hidden (it keeps `PAUSE_WHEN_HIDDEN = True`, and its acknowledgement now lives in `LeaseSource.poll()`). The forced free leaves rtl_ais on the dongle. The next `request` is granted. RADIOS reads "FREE — any layer may acquire" while rtl_ais runs. Related: ATLAS hidden before HELD keeps the radio HELD (readsb paused) with no decoder until it is fronted (`poc_panic_race` atlas_ais_hidden, iter 0). | `poc_atlas_hidden_revoke.out`, `renders/radios_after_atlas_hidden_revoke_{dark,sun}_live.png` |
| N-c | **High, blocking** | `ProwlApp._switch_submode` waits `wait(3000)` on the GUI thread, then drops the worker reference even if the wait timed out. GUI freeze = kill + release. Past 3 s the process aborts with SIGABRT, so the hub dies and readsb may be left paused. BABEL `_rebuild_worker` blocks 3 s but parks. Pre-existing code, but the brief lists mode switch, and RA-CL5 item 6 did not cover it. | `poc_gui_block_modeswitch.out`, `poc_submode_drop.out` |
| N-b | Medium | R2 regression. `_stop_proc` now always calls `terminate()` and **closes `errfile`**. Every runner calls it in `finally` before `_run_live` reads `_stderr_tail(self._proc)`, so the tail is always "". The FAULT banner lost its reason. The R2 unit test's fake runner never calls `_stop_proc`, so it cannot catch this. | `rerun/poc_babel.out` r2, compared with `RA-CL5-evidence/poc_babel.out` |
| N-d | High (owner decision; not a literal brief violation) | NWR liveness means "process alive", not "audio flowing". A wedged rtl_fm reads LIVE · NO ALERTS for as long as it hangs. A decoder that keeps dying never reaches the `_down >= 3` back-off and mostly reads LIVE. A false all-clear on the safety use needs an audio-level or sample-count heartbeat from stage 1. | `poc_nwr_safety.out` hung, decoder_dies |
| N-e | Medium | SSTV stale decode state after `_stop_rec()` | `poc_sstv_stale_decode.out` |
| N-f | Medium | Tk `sstv.py` loses frames that span a rotation (item 12 b). The weakened `test_r5` assertion (`3.5 <= secs` → `0 < secs`) is what lets it through. | `poc_tk_sstv_rotation.out` |
| N-g | Low | `AtlasApp._update_busy`: `getattr(self, "_acquiring", ()) & self._layers` raises TypeError (tuple & set) on every `_render` until the worker's first `acquiring_layers` status, which includes the first layer toggle. A traceback goes to stderr and the busy line is not updated. | stderr of `poc_atlas_hidden_revoke` and `poc_panic_race` |
| N-h | Low | PANIC banner understates: "no child processes were running" or "radio was free" when the page's own kill or release won the race. The banner should count the page-level stops too. | `renders/babel_after_panic_*`, `rerun/poc_panic.out` nwr |
| N-i | Low | Report and tests. The CL5-report says "31 of 32 fail on `ed4694a`"; here it was 30 of 32 in 4 of 5 runs (`test_fix6_stop_hide…` passes on the old code). `plan/briefs/CL5-fix-renders/` contains only the script; the PNGs the report cites are not committed. | runs listed in §4 |
| N-j | Low | ATLAS `poll()` has no `held_by` re-check after spawning (item 1 row). It also has no RADIOS forced-free marker (N11). | code |

## 4. Regression and tests

- Targeted suites (`test_cl5_fix`, `test_cl5_radio`, `test_cl1_*`, `test_palisade_qt`), Python 3.12.3, offscreen + xvfb: **302 passed, 1 skipped**.
- Full suite, Python 3.12.3 (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`): see `RA-CL5b-evidence/suite_py312.txt`. Result: **3 failed, 1050 passed, 3 skipped**. The 3 failures are the known baseline: `test_audit_tiles::…undecodable…`, `test_hwlab::test_doctor_hwbench_check` and `test_sstvdec::…iss_passes…`. This matches the CL5-report.
- `test_cl5_fix.py` on `ed4694a` (copied into a worktree at `ed4694a`, five runs): 30 failed / 2 passed in four runs, 31 / 1 in one. The tests that pass there are `test_fix2[fm-stop]` (as reported) and `test_fix6_stop_hide_and_revoke_never_block_the_gui_thread` (flaky; it does not pin item 6).
- Assertions changed against `ed4694a`. All of them are justified by a CL5-fix semantic that the report lists:
  - `a1_lease_source`: the acknowledgement moved to `poll()`, and kill before release is asserted.
  - `a6`: contacts are dropped, alerts never.
  - `r3` / `r4`: they now hold for real.
  - `e3`: platform kwargs.
  - The PROWL, BABEL and SSTV qt tests wait for HELD.
  - **Exception:** `test_r5` weakened `3.5 <= secs <= 4.0` to `0 < secs <= 4.0`. That is justified by rotation, but rotation itself is the Tk regression N-f.
  - The removed `pid = 2147483646 # poll()=0 makes _stop_proc early-return` stub marks exactly the `_stop_proc` change behind N-b.
- pyflakes on the touched files: only the pre-existing warnings (`sstvdec.py` unused `math`, and three in `test_palisade_qt.py`, identical at `ed4694a`).
- Demo mode, the CL1 keyboard tests and the OVERWATCH/RADIOS director tests pass. The RADIOS panel was rendered under the N-a fault.

## 5. Renders (1280×720, live, dark + sun) — `renders/`

| Render | What it shows |
|---|---|
| `babel_acquiring_*` | "AIS ACQUIRING radio", no decoder, strip "ACQUIR…": honest |
| `prowl_nwr_live_*` | "LIVE · WX2 162.400" |
| `prowl_nwr_after_revoke_*` | NOT MONITORING in the alert colour, SDR FREE, no process: honest |
| `babel_after_panic_*` | FREE, RUN unticked. The banner says "no child processes were running" (N-h). |
| `atlas_ais_live_*` | ATLAS with the AIS layer on, radio held |
| `radios_after_atlas_hidden_revoke_*` | **SDR FREE, "any layer may acquire", while rtl_ais holds the dongle** (N-a) |

Script: `render_racl5b.py` (the planner's `render_cl5fix.py` plus the ATLAS case).

## 6. Fix list for CL5-fix2

1. N-a: ATLAS must acknowledge a revoke while hidden. Either `PAUSE_WHEN_HIDDEN = False` for `AtlasLiveWorker`, or have `pause()` and `poke()` service `_revoke_req`. Add a regression test through the real hub with the page hidden.
2. N-c: no `wait()` on the GUI thread in `ProwlApp._switch_submode` or `BabelApp._rebuild_worker`. Stop the old worker asynchronously (`stop_worker` without a join, or join on a helper thread). The new worker's `request()` already waits for the arbiter. Never drop a running QThread reference. Add a test with a release that takes 3.5 s.
3. N-b: read the stderr tail before `_stop_proc` closes it, or close `errfile` only in `_kill_proc`. Add a test using the real `_run_ais` and a fake that exits at once.
4. N-e: `_decode_job` must drop its result if the recorder it decoded is no longer `self._rec` (compare by identity).
5. N-f: keep a contiguous last window for the Tk app (decode `.prev.wav` + `.wav`), or let the Tk path keep the R5 behaviour.
6. N-d (owner decision): an NWR liveness heartbeat from rtl_fm's samples, and escalate a flapping decoder.
7. Low items: N-g, N-h, N-i, N-j, N11, N13, N14.

**DO NOT MERGE**
