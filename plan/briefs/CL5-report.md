# CL5-report — radio handling + worker lifecycle (`fix/cl5-radio` @ c9246ef)

Written by the planner (Opus 5.5; Sonnet is not enabled for this org). Self-report only: the
cold re-audit `RA-CL5` decides. Base: `main` @ ef64fcd (CL1 + CL2).

## Findings

| ID | Claim | Where | Regression test (`tests/test_cl5_radio.py` unless noted) |
|---|---|---|---|
| A1 | Arbiter can **revoke**: asks the holder (`revoked` signal), holder stops its pipeline then releases; forced free after `REVOKE_TIMEOUT_S` | `palisade_qt/radio_arbiter.py` `revoke`/`_revoke_expired`; `panels.RadiosPanel._free_radio` | `test_a1_revoke_asks_the_holder_and_frees_on_its_release`, `test_a1_revoke_times_out_when_the_holder_never_answers`, `test_a1_lease_source_stops_its_pipeline_before_releasing`; `test_palisade_qt::test_overwatch_radio_director_tracks_arbiter_and_frees` |
| A2 | A worker that will not join is parked (kept referenced), never aborted/dropped | `palisade_qt/worker.py`, `app.py` | `test_a2_a_worker_that_will_not_join_is_parked_not_aborted`, `test_a2_stop_worker_helper_returns_true_when_it_joins` |
| A3 | FREE / ACQUIRING / HELD; `request()` never blocks on the slow lease (acquire on a thread, generation counter drops stale acquires) | `radio_arbiter.py` `request`/`_acquire` | `test_a3_request_never_blocks_on_a_slow_acquire`, `test_a3_release_during_acquire_releases_the_late_lease`, `test_a3_strip_shows_acquiring_then_held` |
| A4 | Decoders run as argv `Pipeline` (no shell); every stage leads its own session; terminate signals every group, waits, SIGKILLs, reaps | `palisade_qt/kit/procs.py`; `atlas.py`, `prism.py`, `prowl.py`, `babel.py`; `aprs.py`/`ais.py`/`nwr.py` argv builders | `test_a4_*` (4); `test_cl1_fix::test_decoder_pipelines_start_in_their_own_session` (updated) |
| A5 | Base-class lease path removed; `more.py` deleted | `app.py`; `more.py` gone | `test_a5_base_class_has_no_lease_path_and_more_py_is_gone` |
| A6 | Event bus copies events, is bounded, and resizes | `palisade_qt/eventbus.py` | `test_a6_bus_copies_bounds_and_resizes` |
| R1 | BABEL takes no radio until RUN, releases when hidden | `babel.py` `wants_radio`, RUN button | `test_r1_babel_takes_no_radio_until_run_and_releases_when_hidden`; `test_palisade_qt::test_babel_live_mode_acquires_and_releases_via_arbiter` (updated) |
| R2 | Early decoder exit = FAULT with backoff, lease kept (no 500 ms churn) | `babel.py` `_run_live` | `test_r2_early_decoder_exit_is_a_fault_with_backoff_and_no_lease_churn` |
| R3 | Dead NWR pipeline shows DOWN, not healthy | `nwr.py`, `prowl.py` | `test_r3_dead_nwr_pipeline_shows_down_not_healthy` |
| R4 | NWR retune waits for the old pipeline to exit | `prowl.py` | `test_r4_nwr_retune_waits_for_the_old_pipeline_to_exit` |
| R5 | SSTV recorder keeps a rolling window, writes under the cache dir | `sstv.py` | `test_r5_sstv_recorder_keeps_a_rolling_window_and_writes_under_cache` |
| E2 | Default scan bank is intermittent (GMRS/FRS), active dwell capped, SKIP locks out | `scanner.py`, `prowl.py` | `test_e2_default_bank_is_intermittent_and_active_dwell_is_capped`, `test_e2_skip_locks_out_the_current_channel` |
| E3 | BLE (Remote ID) scan passive, opt-in via the DRONES layer, failures surfaced | `atlas.py` `RidSource`, `AtlasLiveWorker` | `test_e3_ble_scan_is_passive_opt_in_and_surfaces_failures` |
| B1 | FM tuner keeps narrow channels | `prowl.py` | `test_b1_fm_tuner_keeps_narrow_channels` |
| B2 | Live squelch shows the engine's setting | `prowl.py` | `test_b2_live_squelch_is_the_engine_setting` |
| B3 | Hit times are epochs (midnight no longer sticks) | `prowl.py` | `test_b3_hit_times_are_epochs_so_midnight_does_not_stick` |
| §15.1 Workers | stop interrupts sleep, pause/resume, one fault after repeated failures, pause while page hidden | `worker.py` | `test_worker_*` (4), `test_workers_pause_while_their_page_is_hidden` |

## Folded in from RA-MAIN-1 (owner said fold into CL5)

| ID | Result | Test |
|---|---|---|
| F1 strip headroom | 100–999 targets now read `N tgts`. Worst-case strip 1279 → 1269 px, measured the same on Linux and Mac with Plex loaded. The handoff's 1284 came from fallback fonts. | `test_cl1_fix3::test_strip_fits_1280_with_a_huge_scope` (now ≤ 1270 and includes a 10-char single target), `test_scope_summary_caps_the_target_count` |
| F2 fonts not loaded | **Not reproduced.** In `theme.py`, `_HERE` is the repo root, so `load_fonts` already reads `<repo>/fonts/`. Pinned. | `test_cl1_fix3::test_bundled_plex_fonts_are_loaded` |
| PERMITTED word | Owner: leave it for v0.1. | — |

## Suite (Linux, Python 3.13.18, PySide6 6.12.0, offscreen + xvfb; no tkinter in this container)

`1005 passed, 5 failed, 5 skipped, 7 errors` (full run on 478ecf8 plus the test updates). The CL1/CL5 files re-run on c9246ef gave 149 passed, 1 failed.
- Baseline on main: `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::…iss_passes…`.
- `test_cl1_screen::test_up_down_drive_the_list_and_the_detail_follows` fails on **main too** on Linux. This is CL1 debt, not caused by CL5.
- `test_cl1_fix2::test_ack_all_never_acks_an_alert_that_arrived_after_the_drawer_was_viewed` fails only in the full run and passes alone, so it is order-dependent.
- The 7 `test_shell.py` errors are from missing tkinter (env).
- pyflakes is clean on the touched files. The `test_palisade_qt.py` warnings were already there.

Python 3.12 was not run here. The auditor runs it.

## Renders (1280×720, live, dark + sun, before = main, after = branch)

`plan/briefs/CL5-renders/{before,after}/{prowl,babel,atlas,radios}_{dark,sun}_live_*.png`, script `render_cl5.py`.
Visible changes: PROWL defaults to the GMRS/FRS bank and the squelch shows the engine value (E2, B2); BABEL has a RUN button (R1). ATLAS and the RADIOS panel are unchanged in the idle state.

## Open for the owner
None new. PERMITTED stays for v0.1 (decided 2026-11-16).

---

# CL5-fix — the 12 RA-CL5 items (`fix/cl5-radio`, after `ed4694a`)

Written by the planner (Opus 5.5). Self-report; **RA-CL5b** decides. Regression tests are in
`tests/test_cl5_fix.py` (32 tests, real processes and real threads; only `_make_lease` patched).
31 of 32 fail on `ed4694a`; `fm-stop` already passed there.

| # | Item | Status | Where | Test (`test_cl5_fix.py`) |
|---|---|---|---|---|
| 1 | Decoders start only on HELD; pages say ACQUIRING meanwhile (N1) | CLOSED | `radio_arbiter.held_by`; every holder: `prowl._RadioWorker._ensure_lease`, `babel.DecoderWorker._run_live` + `_adopt`, `SstvWorker._ensure_lease`, `prism.SweepWorker.step`, `atlas.LeaseSource.poll` | `test_fix1_no_decoder_starts_before_the_arbiter_says_held`, `test_fix1_every_other_holder_waits_for_held[nwr,fm,prism,atlas,sstv]` |
| 2 | Kill → wait → release in every PROWL path, incl. `ScanWorker.stop` (N4) | CLOSED | `prowl._RadioWorker._give_back` / `_finish`; `stop()` is flags-only, `run()` releases | `test_fix2_prowl_kills_and_waits_before_it_releases[nwr-hide,nwr-revoke,fm-hide,fm-stop]`, `test_fix2_scan_stop_never_releases_while_listen_channel_runs` |
| 3 | SSTV: RUN / hide / revoke; `PAUSE_WHEN_HIDDEN=False` (R1) | CLOSED | `babel.SstvWorker` `set_running`/`set_active`/`hold_off`/`_give_back` | `test_fix3_sstv_takes_the_radio_only_on_run_and_gives_it_back` |
| 4 | SCAN revoke breaks `listen_channel` | CLOSED | `ScanWorker._interrupt` (scan pause) | `test_fix4_scan_revoke_breaks_an_active_listen` (real `listen_channel`, loud fake rtl_fm) |
| 5 | PANIC frees the arbiter; nothing respawns (N3) | CLOSED | `shell.panic`: pages' `on_panic` hold off first, then the tree kill, then `arbiter.panic_free()`; the banner reports the arbiter's state after. BABEL unticks RUN; PROWL/PRISM stay off until Enter or re-opening; ATLAS unticks APRS/AIS | `test_fix5_panic_frees_the_radio_and_nothing_respawns` (real hub), `test_fix5_panic_holds_nwr_off_until_the_operator_resumes` |
| 6 | No GUI-thread blocks on revoke / RUN / hide / STOP | CLOSED | handlers set flags + `Worker.poke()`; `kit.procs.terminate_async`; ATLAS acks in `poll()` | `test_fix6_stop_hide_and_revoke_never_block_the_gui_thread` (SIGTERM-ignoring stage), `test_fix6_atlas_revoke_ack_is_off_the_gui_thread` |
| 7 | Honest give-back; NWR never MONITORING / no alerts without a live decoder (N2) | CLOSED | every give-back emits `off`; NWR "Receiver" reads LIVE only while `held_by("PROWL-NWR")` and a healthy status < 3 s old, else NOT MONITORING (alert colour), detail "NOT MONITORING"; 1 s watchdog timer | `test_fix7_nwr_never_reads_monitoring_after_the_radio_is_given_back`, `test_fix7_a_silent_or_forced_free_receiver_goes_not_monitoring`, `test_fix7_every_prowl_give_back_says_off[*]`, `test_fix7_prism_says_off_…` |
| 8 | Bus never drops alerts (N5) | CLOSED | `eventbus.publish`: the backlog cap applies to contact/decode only | `test_fix8_a_warning_during_a_gui_stall_reaches_the_alert_store` |
| 9 | Pipeline: SIGKILL any group survivor; signal groups whose leader exited; clean up a partial start (N7) | CLOSED (setsid grandchild remains a known limit) | `kit/procs.py` `_signal`, `_groups_alive`, `_done` guard against pgid reuse | `test_fix9_*` (3) |
| 10 | E3 passive on BlueZ; faults on the page (N8) | CLOSED | `RidSource.scanner_kwargs` adds `bluez.or_patterns` (AD 0x16, `FA FF`); `AtlasApp.on_error` → fault chip | `test_fix10_passive_ble_scan_has_bluez_or_patterns` (real bleak: refused without, accepted with), `test_fix10_atlas_shows_a_source_fault_on_the_page` |
| 11 | B2 retune is not a hit (N10) | CLOSED | `ScanWorker._run_live`: `"retune"` re-listens the same channel | `test_fix11_a_squelch_retune_is_not_a_hit` |
| 12 | SSTV: append, decode only new audio, one event per frame (N9) | CLOSED | `sstv.Recorder` appends (header patch only), rotates to `.prev.wav` at `window_s`; `sstvdec.decode_samples` (decode_wav's body, unchanged maths); `SstvWorker._decode_job`/`_fold_frame` | `test_fix12_sstv_decodes_only_new_audio_…`, `test_fix12_recorder_appends_and_never_rewrites` |

Also: N12 (forced release is generation-checked, `_release(name, gen)`); N13 partly (workers
disconnect `revoked` at the end of `run()`; `publish()` returns a copy). Not done: N6 (opening BABEL
briefly fronts PROWL SCAN), N11 (RADIOS history), N13 legacy Tk `shell=True`, N14 — follow-ups.

## Tests changed, and why (diff vs `ed4694a`)
- `test_cl5_radio`: `a1_lease_source` (ack now in the worker's `poll()`, kill-before-release asserted); `a6` (drops are now proven with contacts; alerts are never dropped — item 8); `r3`/`r4` (hold the radio for real instead of stubbing `_ensure_lease`: item 1); `r5` (rotation + `bytes_written`: item 12); `e3` (Linux kwargs include `bluez`: item 10).
- `test_palisade_qt`: PROWL/BABEL/SSTV tests wait for HELD, press RUN for SSTV, and finish via `run()` because `stop()` no longer releases on the GUI thread (items 1, 3, 6); the SSTV decode seam is now `_decode(x, fs)` (item 12). No assertion was removed; each now proves the same claim under the new ordering.
- Side fix: PROWL scan rows carry `_id` (the cursor follows a channel across refreshes) and a demo worker is not poked on page focus; this made `test_cl1_screen::test_up_down_…` deterministic (it failed 4/4 with the first draft of this fix).

## Suite (Linux, Python 3.12.3, PySide6 6.12.0, tkinter present, offscreen + xvfb)
`1050 passed, 3 failed, 3 skipped` — the 3 known baseline failures only (`test_audit_tiles::…undecodable…`, `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::…iss_passes…`). pyflakes on touched files: clean except the pre-existing unused `math` in `sstvdec.py`.

## Renders (1280×720, live, dark + sun)
`plan/briefs/CL5-fix-renders/`: `babel_acquiring_*` (chip "AIS ACQUIRING radio", no decoder), `prowl_nwr_live_*` (Receiver "LIVE · WX2 162.400"), `prowl_nwr_after_revoke_*` (NOT MONITORING in red, SDR FREE, no process), `babel_after_panic_*` (banner "radio released (was BABEL)", RUN unticked, FREE). Script `render_cl5fix.py`.

## For the owner
After PANIC (or a revoke), PROWL and PRISM stay off the radio until you press **Enter** on that page or re-open it; BABEL needs RUN again. NWR shows NOT MONITORING in red meanwhile.

---

# CL5-fix2 — the RA-CL5b findings (`fix/cl5-radio`, after `c4f5612`)

Written by the planner (Opus 5.5). Self-report; **RA-CL5c** decides. Regression tests are in
`tests/test_cl5_fix2.py` (15 tests, real processes and real threads; only `_make_lease` patched).
14 of 15 fail on `510359e` (the RA-CL5b tip, code unchanged in `c4f5612`), each on the behaviour
named, not on a missing name; `test_nd_flowing_audio_reads_live` is the control and passes there.

| ID | Finding | Status | Where | Test (`test_cl5_fix2.py`) |
|---|---|---|---|---|
| N-a | Hidden ATLAS never acked a revoke; forced free with rtl_ais on the dongle | CLOSED | `AtlasLiveWorker.PAUSE_WHEN_HIDDEN=False`; hidden it runs only the lease layers (`_step_leases`), nothing else; `LeaseSource.wake` pokes the worker on a revoke; `AtlasApp.set_active` → `set_hidden` | `test_na_hidden_atlas_answers_a_revoke_and_reaps_before_release` (real `AtlasApp`, fake rtl_ais, no FORCED FREE, nothing at release), `test_na_hidden_atlas_starts_its_decoder_once_held` |
| N-c | Sub-mode / decoder switch waited 3 s on the GUI thread, then dropped a running QThread (SIGABRT) | CLOSED | `PalisadeApp.swap_worker`: the old worker is told to stop (flags), its signals cut, kept referenced; the new one starts on the old one's `finished` (queued to the GUI thread). No overlap on the radio and no same-name release race. PANIC cancels a pending switch (`cancel_swap`); Enter starts the shown mode. The page chip says "SDR — switching modes" meanwhile. Used by `ProwlApp._switch_submode` and `BabelApp._rebuild_worker` | `test_nc_prowl_submode_switch_never_waits_on_the_gui_thread` (3.5 s release, GUI < 0.2 s, release with no decoder, no stale chip), `test_nc_panic_during_a_pending_switch_starts_nothing`, `test_nc_babel_decoder_switch_never_waits_on_the_gui_thread` (SIGTERM-ignoring stage + 2.2 s release) |
| N-b | FAULT lost the decoder's stderr (R2 regression) | CLOSED | `babel._stop_proc` keeps the tail (`proc.err_tail`) before closing the file; `_stderr_tail` returns it | `test_nb_decoder_fault_shows_its_stderr_through_the_real_runner` (real `_run_ais`) |
| N-e | A late SSTV decode wrote a stale clock into the next RUN | CLOSED | `SstvWorker._decode_job` writes the clock under `self._lock` only if `rec is self._rec`; `_stop_rec` swaps the recorder and resets the clock under the same lock | `test_ne_a_decode_that_outlives_its_recorder_cannot_stall_the_next_run` |
| N-f | Tk `sstv.py` lost frames that spanned a rotation | CLOSED | `Recorder(keep_last_window=True)` (default, the Tk app): at the end of a recording, if it rotated, the file becomes the last `window_s`, contiguous, and `.prev.wav` is removed — one rewrite per recording, not per flush. The Qt worker passes `False` (decodes from memory, deletes its files) | `test_nf_tk_recorder_leaves_one_contiguous_last_window` (sample-exact), `test_nf_qt_worker_does_not_pay_for_the_tk_rewrite`; `test_r5` restored to `3.5 <= secs <= 4.0` |
| N-d | NWR LIVE meant "process alive"; a wedged rtl_fm read LIVE · NO ALERTS; a flapping decoder never escalated (owner: fix now) | CLOSED | `NwrWorker`: LIVE needs rtl_fm's output counter (`/proc/<pid>/io` wchar) to have grown in the last 3 s — covers a wedged rtl_fm and a stuck multimon-ng (full pipe stops rtl_fm). An unreadable counter is "no audio". 10 s without audio → kill + respawn. 3 exits in 60 s → one FAULT and a hold-down (10/30/60 s), NOT MONITORING throughout | `test_nd_a_wedged_rtl_fm_never_reads_live` (sampled every 0.1 s: never LIVE, restarted), `test_nd_a_flapping_decoder_escalates_and_never_reads_live`, `test_nd_flowing_audio_reads_live` (control) |
| N-g | ATLAS `_update_busy` TypeError before the first status | CLOSED | `set(...) & self._layers` | `test_ng_atlas_busy_line_before_the_first_status` |
| N-h | PANIC banner understated what the pages stopped | CLOSED | `shell.panic` snapshots children and the radio owner before `on_panic`; the banner counts "stopped by their pages (verified gone)" and "radio released (was X)" | `test_nh_panic_banner_counts_what_the_pages_stopped` |
| N-i | Report count / renders not committed | CLOSED | the 31-of-32 line was over-stated: `test_fix6_stop_hide…` passes on `ed4694a` too, so 30 of 32 (RA-CL5b's count). PNGs are now committed (`git add -f`; `*.png` is ignored repo-wide) | — |
| N-j | ATLAS `poll()` had no `held_by` re-check after spawning | CLOSED | `LeaseSource.poll` reaps and gives back if it lost the radio while spawning | covered by `test_na_*` paths |
| N11 | RADIOS history logged HELD, HELD; no forced-free marker | CLOSED | `RadioArbiter.transition(event, owner, note)` emitted AT each transition; `RELEASE · FORCED FREE — holder did not acknowledge` / `RELEASE · PANIC` | `test_n11_radios_history_logs_each_transition_and_marks_a_forced_free` |
| N14 | Vacuous RADIOS assertion | CLOSED | `test_cl1_screen` now reads the card's labels | the test itself |
| N13 | Legacy Tk `shell=True` (`aprs.py`, `ais.py`, `nwr.py`) | OPEN (follow-up) | legacy Tk apps not wired to the Qt hub; changing them is outside CL5 | — |

Also found while rendering (not in RA-CL5b): during a switch the old sub-mode's green SDR chip
("NWR WX2 162.400M") stayed on the page, and the top strip kept the old holder for the whole slow
lease release. Both fixed: `swap_worker` replaces the chip; `RadioArbiter._release` announces
FREE (`transition` + `changed`) as soon as the state is FREE, before the slow `lease.release()`
(readsb restart). Asserted in `test_nc_prowl_submode_switch_…`.

## Tests changed, and why (diff vs `c4f5612`)
- `test_cl5_fix::test_fix12_…`: sets `w._rec = rec` — a decode now applies only to the live recorder (N-e). Same assertions.
- `test_cl5_radio::test_r5_…`: the RA-CL5 contract `3.5 <= secs <= 4.0` is back (N-f); adds rotation happened, no `.prev.wav` left, and `bytes_written` = every byte once + one last-window rewrite.
- `test_cl1_screen` RADIOS test: the vacuous `… if hasattr(…) else True` is now a real check (N14).

## Suite (Linux, Python 3.12.3, PySide6 6.12.0, tkinter present, offscreen + xvfb)
`1065 passed, 3 failed, 3 skipped` — the same 3 baseline failures only. Targeted
(`test_cl5_fix`, `test_cl5_radio`, `test_cl1_*`, `test_palisade_qt`): 302 passed, 1 skipped;
`test_cl5_fix2`: 15 passed. pyflakes on touched files: clean (bar the pre-existing `sstvdec.py` `math`).

## Renders (1280×720, live, dark + sun) — `plan/briefs/CL5-fix-renders/`
New: `radios_after_atlas_hidden_revoke_*` (ATLAS hidden with AIS on, FREE THE RADIO: history
ACQUIRING → HELD → RELEASE, no forced free, no rtl_ais), `prowl_switch_waiting_*` (NWR → FM with a
3.5 s release: GUI blocked 0.004 s, "FM: waiting for the previous mode to give the radio back",
chip "SDR — switching modes", strip FREE), `prowl_switch_done_*` (PROWL-FM HELD). The CL5-fix
PNGs are re-rendered and now committed.
