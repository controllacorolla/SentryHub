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
