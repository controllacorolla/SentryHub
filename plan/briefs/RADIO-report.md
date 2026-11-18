# RADIO — PRISM SDR++ receiver + PROWL scanner (device-fix plan items 14, 15)

Branch `claude/project-thread-z1copz` · commits 5236dbe, 859b8bf (+ this report).

## What changed
- `dsp.py` (new): IQ DSP. Demods NFM / WFM / AM / USB / LSB / CW / RAW, per-mode bandwidth limits,
  squelch on channel power with 2 dB hysteresis, audio AGC, WFM de-emphasis, Spectrum (Blackman,
  log-power), noise floor, per-channel levels.
- `iqsource.py` (new): `RtlTcpSource` (rtl_tcp bound to 127.0.0.1, retune / rate / gain / PPM /
  RTL-AGC over the socket, no restart), `FileSource` (.cu8 + SDR++ WAV baseband, sidecar / WAV /
  filename metadata), `SynthSource` (demo), IQ + audio recorders (`suite.DATA/recordings`, free-space
  guard), non-blocking `AudioOut`, `parse_freq` / `fmt_freq`.
- `banks.py` (new): full preset channel plans in Dalton's order: airband first (full 118–136.975
  every 25 kHz = 760 ch, common, 8.33, mil UHF), then ham (2m, 70cm, 1.25m, 6m, 10m FM), NOAA Wx,
  FRS/GMRS, MURS, marine, public safety VHF/UHF, railroad, CB, ADS-B/APRS/AIS, ISM.
- `palisade_qt/iqworker.py` (new): `TunerWorker` (PRISM) and `FastScanWorker` (PROWL FAST): radio
  ownership through `radio_arbiter` exactly like the other SDR workers (source opens only when HELD,
  give-back closes rtl_tcp then releases).
- `palisade_qt/kit/tuner.py` (new): `TunerScope` spectrum + waterfall, `FreqEdit`.
- `palisade_qt/prism.py`: new receiver page; the old wide sweep stays as source "Wide sweep".
- `palisade_qt/prowl.py`: SCAN page rebuilt (FAST engine, banks, all scanner adjustments),
  CLASSIC engine kept and fed the same bank / timing / lockouts. FM tab gains `am`.
- `fm.py`: `am` pipeline (rtl_fm -M am). `theme.py` + `kit/components.py`: shared run-state QSS
  and `set_run(btn, on)` (same text as the UI thread's `fix/shell-frame`; drop one copy on merge).

## Coverage vs Dalton's notes (device-notes.md PRISM / PROWL + plan items 14, 15)

| Item (his words / plan) | Status | Where | Test |
|---|---|---|---|
| Click / drag to tune on FFT and waterfall | implemented | kit/tuner.py `_View`, `_clicked` | test_prism_click_drag_and_wheel_move_the_vfo |
| Wheel / keys fine + coarse steps | implemented ([ ] keys, wheel = step, 12 step sizes) | prism.py `_step_vfo`, `handle_key` | same + test_prism_mode_bandwidth_zoom_levels_and_keys |
| Direct frequency entry | implemented (121.5 / 446M / 7030k / Hz) | prism.py `_typed_freq`, iqsource.parse_freq | test_prism_typed_frequency_recentres… |
| Digit-by-digit tuning | implemented (wheel over a digit) | kit/tuner.py `FreqEdit`, `digit_step_hz` | test_prism_wheel_over_a_frequency_digit… |
| Visible filter bandwidth you can drag | implemented (edge drag symmetric, USB/LSB one-sided, body drag = VFO) | kit/tuner.py `_band_dragged` | test_prism_dragging_a_passband_edge… |
| NFM / WFM / AM / USB / LSB / CW with live audio | implemented | dsp.Demodulator | test_every_demod_mode_recovers_the_audio[*] |
| RAW | partial: mono (I channel); SDR++ RAW is stereo I/Q | dsp.py `_demod` | test_every_demod_mode…[RAW] |
| Squelch | implemented (dBFS, line on spectrum) | prism.py RADIO | test_squelch_mutes_noise… |
| Gain manual + AGC, PPM | implemented (tuner gain steps, auto, RTL AGC, audio AGC, PPM) | prism.py GAIN / SOURCE | test_rtl_tcp_source_retunes_and_sets_gain… |
| Sample rate / span, zoom | implemented (250k–2.4M, zoom 1–32× at full FFT resolution) | prism.py, tuner.py | test_prism_zoom_shows_the_vfo_neighbourhood… |
| FFT size, averaging, waterfall min/max | implemented (2k–32k, smoothing off/light/medium/heavy, floor/top + AUTO) | prism.py DISPLAY | test_prism_fft_smoothing…, test_prism_mode_bandwidth… |
| Bookmarks / frequency manager | implemented (add/del/tune, saved; preset banks browsable and tunable with their mode) | prism.py BOOKMARKS·BANKS | test_prism_bookmarks_are_saved… |
| Recording audio + IQ | implemented (WAV, .cu8 + json; plays back as source "IQ file") | iqworker.py, iqsource.py | test_recording_from_the_worker…, test_iq_recording_plays_back… |
| START / STOP red / green (PRISM) | implemented | prism.py run_btn, set_run | test_prism_start_stop_button_is_green… |
| Preset banks, airband first then ham | implemented (19 banks) | banks.py | test_banks_follow_the_owner_priority… |
| Full airband 118–137 | implemented (760 ch; FAST pass ≈ 3 s live, 12 retunes; RA-RADIO N10 corrected the 1.5 s claim) | banks.py, iqworker.plan_windows | test_full_airband_pass_takes_seconds… |
| Local ATC (tower / approach / ATIS) by HOME from FAA data | **missing**: needs an FAA frequency dataset; the full 760-channel airband bank hears them all meanwhile | — | — |
| Local public safety by HOME | **missing** (same: needs RadioReference-style data). Generic VHF/UHF public-safety bank ships; P25/DMR not decoded | banks.py | — |
| Dwell / hold | implemented (dwell, HOLD button + Space, max hold) | prowl.py TIMING | test_hold_freezes…, test_max_hold… |
| Resume delay | implemented | same | test_scanner_stops_on_activity…resume… |
| Step | implemented (5–200 kHz incl. 8.33) | prowl.py step_combo | test_prowl_banks_list_airband_first… |
| Lockouts | implemented (S key, list, remove, clear, persisted) | prowl.py LOCKOUTS | test_lockout_is_never_stopped_on… |
| Priority channel | implemented (checked every N s, preempts) | iqworker FastScanWorker | test_priority_channel_preempts… |
| Per-bank squelch | implemented (saved per bank) | prowl.py `_fast_sq_changed` | test_prowl_per_bank_squelch… |
| Range scan | implemented (any 24–1766 MHz, ≤ 20 000 ch) | prowl.py RANGE SCAN | test_prowl_banks_list…range |
| Scan my own bookmarks | implemented (bank "My bookmarks" = PRISM's) | prowl.py `prism_bookmarks` | test_prowl_scans_the_prism_bookmarks |
| SCAN green when on, red when stopped | implemented | prowl.py hold_btn, set_run | test_prowl_scan_button_green_scanning_red_hold |
| Direct AM tune for any airband frequency | implemented (PRISM AM; PROWL FM tab `am`) | prism.py, fm.py | test_prowl_fm_tab_tunes_am… |

Other partials, stated plainly: WFM is mono (no stereo pilot decode); PRISM releases the radio when
its page is hidden (existing arbiter rule, unchanged); CLASSIC engine maps non-AM modes to NFM.

## Backcheck (real live path, not just unit tests)
`python3 plan/briefs/RADIO-renders/backcheck_run.py` drives the real PRISM / PROWL pages and workers
against `tests/rtltcp_fake.py`, a protocol-faithful rtl_tcp (12-byte header, 5-byte commands,
IQ synthesised for the tuned frequency). Result: `BACKCHECK RADIO: PASS (15/15)`.
On the device: `python3 plan/briefs/device_check_radio.py` (close PALISADE first) against the real
dongle: FM band sweep, 5 s of the strongest station on the speaker + WAV, timed airband pass.

## Suite / lint
- `tests/test_radio_sdrpp.py` + `tests/test_cl1_screen.py`: 128 passed.
- Full suite (`QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests`): 1861 passed, 18 skipped,
  4 failed. Three are this container's baseline (test_audit_tiles undecodable tile,
  test_hwlab doctor_hwbench, test_sstvdec ISS TLE / skyfield). The fourth,
  `test_cl4_honest::test_h13_prism_readout_is_relative`, was mine: the peak readout lost its
  "dB rel" unit. Fixed (sweep reads "dB rel", IQ receiver reads "dBFS") and re-run: passes.
  pyflakes clean on every touched file.
- `tests/test_cl1_screen.py::test_band_and_span_keys_in_prism` changed on purpose: `[ ] + -` step
  the band / span on the wide-sweep source; on the receiver they step the VFO / zoom.

## Screenshots (1280×720, gitignored PNGs, regenerate with backcheck_run.py)
`plan/briefs/RADIO-renders/after_prism_live.png`, `after_prism_file.png`,
`after_prowl_fast_scan.png`, `after_prowl_fast_listen.png`.

## Owner questions
- Local ATC / public-safety by HOME needs a frequency dataset (FAA NASR for airports is public).
  Worth a follow-up cluster?

## RA-RADIO fixes (audit verdict DO NOT MERGE, 4 High)

| ID | Fix | Where | Regression test |
|---|---|---|---|
| N1 High | rtl_tcp stdout+stderr merged into one pipe, always drained by a thread | iqsource.py `RtlTcpSource.open`, `_read_err` | test_n1_rtl_tcp_output_is_drained_so_retunes_keep_applying (tests/fake_bin/rtl_tcp prints per retune like the real one) |
| N2 High | control-socket OSError -> SourceError; worker catches source errors AND bugs per block: FAULT status, rtl_tcp closed, radio released, retried; PRISM run button red on fault / off / standby | iqsource.py `_send`, iqworker.py `run`, `_block_fault`, prism.py `_running`, `on_status` | test_n2_a_dead_control_socket…, test_n2_worker_survives_a_broken_pipe_and_a_bug…, test_n2_prism_run_button_goes_red_on_a_fault, test_prism_standby_without_a_radio_tool_is_red… |
| N3 High | a new plan clears the saved priority detour / return window; resume guards its indexes | iqworker.py `_reset_plan`, `_resume_listen` | test_n3_changing_the_bank_during_a_priority_check… |
| N4 High | max hold benches the channel for max(5 s, max hold) of stream time instead of "until the pass wraps" | iqworker.py `_skip_until`, `_eligible`, `_listen_block` | test_n4_max_hold_lets_weaker_channels…[NOAA, AIR]; the old max-hold test no longer accepts "only one hit" |
| N5 Med | `RtlTcpSource.open(abort=)` polls stop / page hidden / revoke during connect and header wait | iqsource.py, iqworker.py `_open` | test_n5_a_revoke_while_rtl_tcp_starts… |
| N6 Med | unique recording names (-2, -3 … when the second is taken) | iqsource.py `_unique` | test_n6_two_recordings_in_the_same_second… |
| N7 Low | free-space guard tested | — | test_n7_recording_stops_itself… |
| N8 Low | sun theme run colours both black | **owner call**, unchanged | — |
| N9 Low | RAW item tooltip + mode tooltip say mono | prism.py | test_n9_raw_is_labelled_mono_in_the_ui |
| N10 Low | pass-time claim corrected to ~3 s | this report | — |
| N11 Low | lockout ends the listen only if it names the channel being heard; PROWL keeps its own HOLD flag, worker's written only on its thread | iqworker.py `_apply`, prowl.py `_toggle_hold`, `_held` | test_n11_* |
| device risk | after every retune, IQ already buffered in the socket (old frequency) is dropped before the settle count starts | iqsource.py `drop_buffered` | covered by the live backcheck; confirm on the uConsole with device_check_radio.py |

## RA-RADIOb fixes (re-audit verdict DO NOT MERGE: B1 High, N2 partial)

| ID | Fix | Where | Regression test |
|---|---|---|---|
| B1 High | `drop_buffered` keeps I/Q byte pairs aligned (carry + dropped bytes parity) | iqsource.py `drop_buffered` | test_b1_dropping_stale_iq_keeps_i_and_q_aligned[4 splits] (fails on the old code: 2 of 4) |
| B2 Med | while faulted the radio is not re-requested until the retry is due; retry backs off 5, 10, 20, 40, 60 s, reset by any good block; no-data / stream-ended faults also release | iqworker.py `_ensure_radio`, `_retry_s`, `run` | test_b2_a_repeating_fault_leaves_the_radio_free_and_backs_off |
| B3 / N2 | any exception opening the source, in `on_source_opened`, applying settings or reading is a FAULT (thread lives); PRISM shows a finished worker red and START builds a new one; PROWL Enter restarts a finished FAST scanner | iqworker.py `_open`, `run`; prism.py `_running`, `_set_running`; prowl.py `_resume_radio` | test_b3_a_missing_iq_file…, test_b3_prowl_enter_restarts… |
| B4 Low | source closed and radio released before the FAULT is announced | iqworker.py `_block_fault`, `_open` | test_n2_worker_survives… (was flaky) |
| B5 Low | peer closing during the header is a SourceError, no spin | iqsource.py `_recv_exact` | test_b5_… |
| B6 Low | rtl_tcp output drained in bytes mode, decoded with replace | iqsource.py `open` | test_b6_… |
| B7 Low | settings that failed to apply are re-queued (newer values win) | iqworker.py `_requeue` | test_b7_… |

After the RA-RADIOb fixes: full suite 1887 passed, 17 skipped, 3 failed (the container baseline:
test_audit_tiles, test_hwlab doctor, test_sstvdec). pyflakes clean.

## RA-RADIOc (verdict MERGE) follow-ups, done before handing to the owner

| ID | Fix | Regression test |
|---|---|---|
| C1 | `IqWorker.retry_now()`: PRISM START and PROWL Enter on a faulted worker skip the back-off; FAULT text ends "retry in N s" | test_c1_start_and_enter_retry… |
| C2 | `on_source_closed` errors can't end the thread; PROWL Enter checks "finished" before "held off" | test_c2_prowl_enter_restarts… |
| C3 | back-off reset after a good block is tested | test_c3_back_off_resets… |
| C4 | a cancelled start closes the half-open source; a setting whose value raises is dropped, only source failures re-queue | test_c4_a_cancelled_start…, test_b7_… (now through run()) |
| B6 / B7 pins | B6 test now drives the real `open()` with a fake rtl_tcp printing non-UTF-8; B7 test goes through `run()`. Both fail with their fix removed. | test_b6_…, test_b7_… |

## RA-RADIOd (verdict MERGE) follow-ups

| ID | Fix | Regression test (fails with the fix removed) |
|---|---|---|
| D1 | `_ensure_radio` / `_open` read `_fault` once into a local, so `retry_now()` from the GUI thread can't race them | test_d1_retry_now_clearing_the_fault_mid_check_is_safe |
| D2 | PROWL Enter on a held-off AND faulted scanner resumes and retries in one press | test_d2_prism_start_and_prowl_enter_wire_the_retry (also pins PRISM START → retry_now, M5/M6) |
| D3a | teardown guard pinned (M8) | test_d3_a_teardown_error_never_ends_the_worker |
| D3b | one bad queued value drops the keys queued with it: left as is (no UI path produces one), noted | — |

Radio + CL5 tests after these: 191 passed, 1 skipped.
