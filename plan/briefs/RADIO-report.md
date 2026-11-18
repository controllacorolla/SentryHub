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
| Full airband 118–137 | implemented (760 ch; FAST pass ≈ 1.5 s, 12 retunes) | banks.py, iqworker.plan_windows | test_full_airband_pass_takes_seconds… |
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
