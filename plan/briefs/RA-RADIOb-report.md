# RA-RADIOb: scoped cold re-audit of the RA-RADIO fixes

Auditor: fresh session, audit only, no code changed. Branch `claude/project-thread-z1copz` at
`dc3eb44`. Scope: `git diff fe58b1e..HEAD` (iqsource.py, palisade_qt/iqworker.py, prism.py,
prowl.py, tests/fake_bin/rtl_tcp, tests/test_radio_sdrpp.py) and everything it calls. Inputs read:
CLAUDE.md, `plan/briefs/RA-RADIO.md`, `plan/briefs/RA-RADIO-report.md`, the "RA-RADIO fixes" table
in `plan/briefs/RADIO-report.md`, the diff, and `kit/procs.py` and `radio_arbiter.py` where the
diff relies on them. New PoCs are in `plan/briefs/RA-RADIOb-poc/`. Run each one as
`python3 <poc> <worktree>` with `QT_QPA_PLATFORM=offscreen`.

**Verdict: DO NOT MERGE.** N1, N3, N4, N5, N6, N7, N9, N10 and N11 are closed, and every
RA-RADIO PoC now passes. Two problems remain. (1) The new `drop_buffered()` (the "device risk"
fix) can drop an odd number of bytes and clears the carry byte. When that happens, I and Q swap for
every read until the next retune, so the spectrum is mirrored and the demodulator hears the mirror
frequency, with no warning (B1, High, a regression introduced by this diff). (2) N2 is only
partly fixed. A non-`SourceError` in `_open` or `_apply` still kills the worker thread. After that,
PRISM START turns the button green on a dead worker. A fault loop also keeps the radio held while
the worker is faulted, and it cycles the lease every 5 s.

## Prior PoCs re-run on `dc3eb44`

| PoC | Before (RA-RADIO) | Now |
|---|---|---|
| poc_stdout | retunes froze after ~3,400 | 1000 to 6000 retunes all `match=True`, alive |
| poc_oserror | thread dead, no status | `SourceError rtl_tcp control socket: timed out`; thread running, FAULT emitted, rtl_tcp terminated |
| poc_detour | IndexError | `no crash; listen= None` |
| poc_maxhold (NOAA, 1 window) | `162.4 × 9` | 162.4 / 162.475 alternate, B heard |
| poc_maxhold_air | `124.35 × 5` | 124.35 / 124.6 alternate |
| poc_revoke_open | FORCED FREE +5.01, terminate +5.42 | terminate +0.10, then RELEASE +0.10 |
| poc_rec | same path, overwritten | `share a path: False`, size 4000 kept |
| poc_revoke / poc_dsp / poc_pass / poc_badjson | pass | unchanged (pass; pass_s 3.00) |

## Results by finding

| ID | Result | Evidence | Test |
|---|---|---|---|
| N1 | **CLOSED** | `iqsource.py:117` merges rtl_tcp stdout and stderr into one pipe (`stderr_last=STDOUT`), and `_read_err` (`:167`) drains it for the life of the process. poc_stdout: 6000/6000 retunes applied. `poc_drainexit.py`: the drain thread ends when rtl_tcp is SIGKILLed and on a normal `close()` (0 threads left). Only `RtlTcpSource` spawns rtl_tcp (`radio.rtl_tcp_server_argv` is used only by a test). Residual hygiene in B6. | test_n1_rtl_tcp_output_is_drained_so_retunes_keep_applying |
| N2 | **PARTIAL** | Fixed: `_send` maps OSError to SourceError (`iqsource.py:194-199`). `run()` catches SourceError, OSError and any exception from `process_block` per block (`iqworker.py:223-245`) and calls `_block_fault` (`:258`). PRISM `_faulted` turns the button red on fault, off or standby (`prism.py:1134-1138`). poc_oserror passes. **Still open:** (a) `_open` catches only SourceError, and `_apply`'s try catches only SourceError/OSError. Any other exception (for example `FileNotFoundError` from `FileSource.open`, a Popen OSError, or a ValueError in `_apply`/`on_source_opened`) reaches the `BaseException` handler, and the thread dies. (b) In PRISM, START on that dead worker sets `_faulted=False`. The button shows **STOP / green** while nothing runs, and nothing restarts a finished worker. `poc_filedie.py`: `thread running = False`, then `PRISM button after START: STOP on \| worker running: False`. The fix bar was "Enter restarts it", which is not met. PROWL `_resume_radio` still restarts only a finished `ScanWorker`, not a `FastScanWorker`. (c) The fault loop holds the radio (B2). (d) The N2 test is flaky (B4). | test_n2_a_dead_control_socket…, test_n2_worker_survives…, test_n2_prism_run_button_goes_red_on_a_fault. No test covers (a) or (b). |
| N3 | **CLOSED** | `_reset_plan` clears `_detour` and `_return_win` (`iqworker.py:616-617`), and `_resume_listen` bounds-checks its indexes (`:729`). poc_detour: no crash. A priority-only change keeps the channel list, so a pending detour stays valid. | test_n3_changing_the_bank_during_a_priority_check_does_not_crash |
| N4 | **CLOSED** | `_skip_until[MHz] = now + max(5, max_hold)` on stream time (`:866-870`), checked by `_eligible` (`:760`). Both PoCs alternate strong/weak. Semantics checked: the bench applies to the priority channel too, because `_eligible(pri)` is checked in both priority paths, so a continuous priority carrier gets max_hold/(max_hold+bench) of the time. Lockouts are unaffected. HOLD returns before the max-hold check. A detour keeps `_t_listen`. A bench outlives a bank change by at most max(5 s, max_hold), which is harmless. The old `or len(hits)==1` escape is gone. | test_n4_max_hold_lets_weaker_channels…[NOAA/AIR], test_max_hold… |
| N5 | **CLOSED** | `open(abort=)` polls during connect (`iqsource.py:123`) and during the header read (`:146`, 0.2 s socket timeout). `_open` passes stop / inactive / not-held (`iqworker.py:185-188`) and treats a cancel as not-a-fault. poc_revoke_open: terminate +0.10 s before RELEASE. FileSource and SynthSource still call `open()` with no argument (`:190`, gated on `kind == "rtl"`), and the file and demo tests pass. Hygiene in B5. | test_n5_a_revoke_while_rtl_tcp_starts… |
| N6 | **CLOSED** | `_unique()` (`iqsource.py:542`) checks every extension (.cu8 and .json, or .wav). poc_rec: different paths, 4000 bytes kept. | test_n6_two_recordings_in_the_same_second… |
| N7 | **CLOSED** | — | test_n7_recording_stops_itself_when_the_disk_is_nearly_full |
| N8 | reserved for owner | unchanged | — |
| N9 | **CLOSED** | `prism.py:452-456`, with an item tooltip and a combo tooltip | test_n9_raw_is_labelled_mono_in_the_ui |
| N10 | **CLOSED** | RADIO-report now says ~3 s, which matches poc_pass 3.00 s | (doc) |
| N11 | **CLOSED** | `lockout_add` ends the listen only when it names the channel being heard (`iqworker.py:631-636`). PROWL keeps `_fast_hold`, and `_held()` resets it to False for a new worker (`prowl.py:1726`), which matches a new FastScanWorker's `hold=False`. Engine switch, worker swap and fault-reopen (where `hold` survives on both sides) all stay consistent. `skip_current()` still reads `_listen` on the GUI thread, but a stale index is now harmless. | test_n11_locking_out…, test_n11_prowl_hold… |

`drop_buffered` (the device-risk fix): it never blocks. It is non-blocking, capped at 8 MiB, and
restores the 0.5 s timeout. It does not discard data the scanner needed, because it runs only inside
`set_freq` and every caller then settles or flushes anyway. **But it breaks I/Q alignment (B1).**
It also cannot reach rtl_tcp's own userspace queue or the USB buffers, so the residual device risk
from RA-RADIO stays open until `device_check_radio.py` runs on the uConsole.

## New findings

| ID | Sev | Finding | PoC / evidence | Where |
|---|---|---|---|---|
| B1 | **High** | **`drop_buffered()` can swap I and Q, which mirrors the spectrum until the next retune.** It discards however many bytes are queued, which can be an odd number because TCP may split a sample across segments, and it sets `_carry = b""`. Before this diff, `read_bytes` kept the byte stream aligned through `_carry`. Now, if the bytes received at the moment of the drop are odd in total, every later read starts on a Q byte. IQ is conjugated, so a tone at +f shows at −f. In PRISM the waterfall is mirrored and the VFO demodulates the mirror frequency, which can last minutes because PRISM retunes rarely. In FAST scan, a window reports a carrier on the mirror channel: a false hit, labelled with another channel's frequency. Nothing indicates it. Fix: keep the parity. Count the bytes dropped, and if `len(carry) + n` is odd, read or keep one more byte so the next read starts on an I byte. Add a test with a half-arrived sample. | `poc_dropalign_det.py` (deterministic, a sample half-arrived at the retune): `tone sent at +200 kHz, receiver sees it at -200 kHz`. `poc_dropalign.py` (real-time 2.048 Msps stand-in, 256 KiB sends, reader lagging 30 ms/block): 1 in 300 retunes left I/Q swapped, in 2 of 4 runs. | `iqsource.py:206-230` |
| B2 | Medium | **A fault loop holds the radio and cycles the lease, so the radio is not "given back while faulted".** `_block_fault` and `_open` release, then the next loop's `_ensure_radio` asks for the radio again within 200 ms and holds it idle for the rest of `FAULT_RETRY_S`. A persistent fault (a deterministic bug, or a dongle that rtl_tcp cannot open) produces RELEASE→ACQUIRING→HELD every ~5 s, which means a readsb restart and stop every 5 s on the device. Other tools cannot get the radio. This fails safe (nothing transmits, and FAULT shows), but the docstring and the fixes table claim the radio is released. It existed before for open faults and now applies to block faults too. | `poc_faultloop.py` (process_block always raises, 16 s): 3 opens, 11 transitions, `RELEASE`/`ACQUIRING` at the same timestamp each time, radio HELD with no source **67 %** of the time. | `palisade_qt/iqworker.py:142-172`, `:258-268` |
| B3 | Medium | **N2 residual: a non-SourceError outside `process_block` still kills the thread, and PRISM START then shows green on the dead worker.** See N2 (a) and (b). This is the same false-green that N2 was about, now on a narrower trigger, for example a recording deleted or unreadable (SD/USB removed) before playback opens. | `poc_filedie.py` | `iqworker.py:174-200`, `:223-226`; `prism.py:994-1003`; `prowl.py:1477` |
| B4 | Low | `test_n2_worker_survives…` is flaky. `_block_fault` emits the FAULT status before `_close_source()`, so the test can read `procs[0].terminated == 0`. It failed 1 of 12 isolated runs and 1 of 3 `test_radio_sdrpp + test_cl5_*` runs. Either emit the status after teardown or wait for `terminated` in the test. | `assert 0 >= 1` at `tests/test_radio_sdrpp.py:1167` | `iqworker.py:258-268` |
| B5 | Low | If the header read sees EOF (rtl_tcp accepts and then closes), `_recv_exact` returns `b""` at once, and the `while len(hdr) < 12` loop spins one CPU for up to 2 s. | code read | `iqsource.py:143-147` |
| B6 | Low | The drain thread is text-mode (`Pipeline text=True`, strict decoding) and exits silently on any exception. One undecodable byte from rtl_tcp would stop the drain and bring N1 back. This is unlikely, because librtlsdr ASCII-fies USB strings. Open the pipe binary, or use `errors="replace"`, and keep reading. | code read | `iqsource.py:167-180`, `kit/procs.py:32` |
| B7 | Low | When `_apply` faults part-way, the rest of the queued settings are lost, because `_take_pending()` has already emptied them. For example, a bank change queued with a gain change while the control socket dies: after the reopen, FAST keeps scanning the old bank while the page shows the new one. This needs the change and the fault to happen together. | code read | `iqworker.py:224`, `:620-650` |

## Tests

- `tests/test_radio_sdrpp.py` + `tests/test_cl5_*`: 174 passed, 1 skipped (2 of 3 runs). One run
  had the B4 flake.
- The `-k test_n` set: 13 passed, ×4.
- Full suite (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests --timeout=120
  --timeout-method=thread`): **1878 passed, 9 skipped, 3 failed, 7 errors in 13:19**. All failures
  and errors are the container baseline listed in RA-RADIO: test_audit_tiles undecodable tile,
  test_hwlab doctor_hwbench, test_sstvdec ISS TLE, and 7 × test_shell with no tkinter. There are no
  new failures.
- pyflakes is clean on every touched file.
- Not re-rendered. The UI change is a tooltip plus run-state logic, which the tests cover. The
  RA-RADIO renders still apply.

## Fix bar before merge
- B1: keep I/Q byte parity across `drop_buffered()`, with a regression test that drops at an odd
  byte position and asserts a +f tone stays at +f.
- B3 / N2: `_open` and `_apply` treat any exception like `_block_fault` does. PRISM START (and PROWL
  Enter for FastScan) restarts a finished worker or refuses to show green, with a test.
- B2: hold off `_ensure_radio` while `_fault` is younger than `FAULT_RETRY_S`, so the radio really
  stays free, with a test that the arbiter stays FREE during the retry wait.
- B4: fix the ordering or the test.

Verdict: **DO NOT MERGE**
