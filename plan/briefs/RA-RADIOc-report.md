# RA-RADIOc: scoped cold re-audit of the RA-RADIOb fixes

Auditor: fresh session, audit only, no code changed. Branch `claude/project-thread-z1copz` at
`02444e3`. Scope: `git diff 77f9783..HEAD` (iqsource.py, palisade_qt/iqworker.py, prism.py,
prowl.py, tests/test_radio_sdrpp.py, RADIO-report.md) and the code it calls. Inputs read: CLAUDE.md,
`plan/briefs/RA-RADIO.md`, `plan/briefs/RA-RADIOb-report.md`, the "RA-RADIOb fixes" table in
`plan/briefs/RADIO-report.md`, the diff, and `radio_arbiter.py`, `kit/procs.py` and the
`AudioOut` / `IqRecorder` / `AudioRecorder` teardown code where the diff relies on them. The new
PoCs are in `plan/briefs/RA-RADIOc-poc/`. Run each one as `python3 <poc> <worktree> [args]` with
`QT_QPA_PLATFORM=offscreen`.

**Verdict: MERGE.** All four items on the RA-RADIOb fix bar are closed and pinned by tests that
fail on `77f9783`: B1 (High, I/Q swap), B2, B3/N2 and B4. Every PoC from RA-RADIO and RA-RADIOb now
passes. A 3-seed fuzz of random odd TCP splits and drops found no misaligned read, where the old
code misread about half of all reads. The code for B5, B6 and B7 is correct. B6 and B7 are still
PARTIAL because their tests do not fail when the fix line is removed (mutation check). Both are Low
and were not on the fix bar. Four new findings, all Low, are follow-ups. None of them reaches an
emission, a false all-clear, or a radio held while idle.

## Prior PoCs re-run on `02444e3`

| PoC | RA-RADIOb result | Now |
|---|---|---|
| RA-RADIO poc_stdout | pass | 6000/6000 retunes `match=True`, IQ still flowing |
| RA-RADIO poc_oserror | pass | `SourceError … timed out`; thread running, owner None, rtl_tcp terminated 1, FAULT emitted |
| RA-RADIO poc_detour / poc_maxhold / poc_maxhold_air | pass | no crash; 162.4/162.475 alternate; 124.35/124.6 alternate |
| RA-RADIO poc_revoke / poc_revoke_open | pass | terminate +0.003 s then RELEASE; terminate +0.10 then RELEASE +0.10 |
| RA-RADIO poc_rec / poc_dsp / poc_pass / poc_badjson | pass | unchanged (`share a path: False`; pass_s 3.00; all OK) |
| RA-RADIOb poc_dropalign_det (B1) | `+200 kHz seen at -200 kHz` | **`seen at +200 kHz`** |
| RA-RADIOb poc_dropalign (B1, lag 0 and 0.03 s, 4 runs) | 1/300 retunes swapped in 2 of 4 runs | **0/300 swapped, 0/1200 blocks, all runs** |
| RA-RADIOb poc_faultloop (B2) | 3 opens, 11 transitions, held idle **67 %** | 2 opens (1.4 s, 7.9 s), 6 transitions, held idle **2 %** (just the HELD→open gap) |
| RA-RADIOb poc_filedie (B3) | thread dead; START → green on dead worker | **thread running = True**, FileNotFoundError shown as FAULT; START → STOP/on with worker running |
| RA-RADIOb poc_drainexit (N1/B6) | 0 threads left | 0 threads left after SIGKILL and after close |

## Results by finding

| ID | Result | Evidence | Test |
|---|---|---|---|
| B1 High | **CLOSED** | `iqsource.py:231-236`: the carry plus every dropped byte is the stream consumed so far. If that total is odd, the last dropped byte is an unpaired I and becomes the carry; otherwise the carry is cleared. With n=0 and a carry, the carry is kept. Every recv adds to `n` and `last`, so the parity holds at the 8 MiB cap too. No other path drops bytes on a live socket: `_recv_exact` only reads the 12-byte header and never reads more than asked; `flush()` is `read_bytes`, which keeps the carry; a recv error in `read_bytes` raises SourceError and the source is closed. **New fuzz** `RA-RADIOc-poc/poc_dropfuzz.py` (real TCP, TCP_NODELAY, random 1/3/7/1001/4097/65537/random-byte sends, random even reads of 2 B to 100 kB, 35 % retunes, about 460 of them with a carry pending): seeds 1-3, **0 misaligned reads** out of about 3,500 each. On `77f9783`: 1,731 and 1,784 misaligned. | test_b1_dropping_stale_iq_keeps_i_and_q_aligned[100000..100003] (the 100001 and 100003 cases fail on 77f9783) |
| B2 Med | **CLOSED** | `iqworker.py:154-159`: while `_fault` is younger than `_retry_s()` and the radio is not held, `_ensure_radio` returns before `arb.request`. Every fault path releases first: `_open` `:209-212` and `_block_fault` `:305-308`. "Stream stopped" and "no samples" faults now go through `_block_fault` (`:261-266`), so they release too. poc_faultloop: held idle 67 % → 2 %. PANIC or revoke during back-off: the worker is not the holder, so `panic_free` returns None. `PrismApp.on_panic` → `hold_off` → `_active=False`, and the worker stays off until START (checked by code read). Back-off is 5/10/20/40/60 s. `_fault_n` is reset only at `:270` after `process_block` succeeds. `_open` succeeding does not reset it, which is correct: open-then-no-data still backs off. Residuals: C1, C3. | test_b2_a_repeating_fault_leaves_the_radio_free_and_backs_off (fails on 77f9783). The reset is not pinned (C3). |
| B3 / N2 | **CLOSED** | `_open` catches `Exception` (`:199`), closes a half-open source, counts the fault and releases. `on_source_opened` is wrapped (`:227-231`). `_apply` and `read` are wrapped separately in `run` (`:243-257`). poc_filedie: the thread lives. PRISM `_running` treats a finished worker as off (`prism.py:993`), and START on a finished worker calls `swap_worker()` (`:999-1002`). Old and new workers never overlap, because the old one has finished. PROWL `_resume_radio` restarts a finished `FastScanWorker` (`prowl.py:1478`). Mutation: removing the `isFinished` clause in `_running` fails the test. A thread can still die from an exception during teardown, but it fails safe (C2). | test_b3_a_missing_iq_file_is_a_fault_and_start_restarts, test_b3_prowl_enter_restarts_a_finished_fast_scanner (both fail on 77f9783), plus the N2 tests |
| B4 Low | **CLOSED** | `_block_fault` now closes the source and releases the radio (`:306-308`) before it emits FAULT, and `_open` does the same (`:205-212`). test_n2_worker_survives… ran green 6/6 isolated (`-k "test_n2 or test_b"`), in 2/2 runs of `test_radio_sdrpp + test_cl5_*`, and in the full suite. | test_n2_worker_survives_a_broken_pipe_and_a_bug_and_shows_the_fault |
| B5 Low | **CLOSED** | `_recv_exact` raises SourceError on EOF (`iqsource.py:189-190`). Its only caller is the header loop, which turns that into `close()` + SourceError. | test_b5_rtl_tcp_closing_during_the_header_is_an_error_not_a_spin (fails on 77f9783) |
| B6 Low | **PARTIAL** (test only) | The fix is right: `open()` uses `Pipeline(..., text=False, bufsize=0)` (`iqsource.py:117`), and `_read_err` decodes with `replace`. poc_drainexit: 0 threads left. **The test does not pin it.** test_b6 builds its own `Pipeline(text=False)` and calls `_read_err`, which already handled bytes on 77f9783. The test passes on 77f9783, and it passes when `open()` goes back to text mode (`mutate.sh` M2: 101 passed). Fix: let the test drive `RtlTcpSource.open()` with a fake rtl_tcp script that prints `\xff`, then keep printing, and assert the drain reaches the end. | test_b6_the_output_drain_survives_undecodable_bytes (does not pin) |
| B7 Low | **PARTIAL** (test only) | The fix is right: `run()` re-queues on any `_apply` failure (`iqworker.py:246-249`), and `_requeue` lets newer queued values win (`:287-292`). **The test does not pin `run()`.** test_b7 calls `w._requeue(p)` by hand. It fails on 77f9783 only with AttributeError, and it passes with the `self._requeue(p)` call deleted from `run()` (`mutate.sh` M1: 101 passed). Fix: drive a running worker whose `set_gain` raises once, queue gain + channels, and assert the channels are applied after the reopen. See also C4. | test_b7_settings_queued_when_the_source_fails_are_kept_for_the_reopen (does not pin run()) |
| N8 | reserved for owner | unchanged | — |

## New findings

| ID | Sev | Finding | PoC / evidence | Where |
|---|---|---|---|---|
| C1 | Low | **START during the back-off does not retry. The wait reaches 60 s and the FAULT line never says when the retry comes.** After 5 faults in a row (for example, the dongle unplugged for about 75 s), `_retry_s()` is 60 s. The operator replugs and presses STOP/START. `_set_running(True)` → `w.set_active(True)` does not touch `_fault`, so nothing runs for up to 60 s. Meanwhile the button flips green and then red again at the next FAULT status, about 200 ms later. Before the diff the worst case was 5 s. This fails safe, because no radio is held and FAULT is shown, but it reads like a dead app. Fix: have an explicit operator START (and Enter) clear `_fault` and `_fault_n` (a queued flag the worker reads), and add "retry in N s" to the FAULT text. | `RA-RADIOc-poc/poc_backoff_start.py` (FAULT_RETRY_S scaled to 0.2 s): 7 faults, then replug + STOP/START, then live only after the full back-off wait. In real time that is min(60, 5·2^(n-1)) = 60 s. | `iqworker.py:154-159`, `:294-298`; `prism.py:1003-1007` |
| C2 | Low | **An exception during teardown still ends the thread.** `_block_fault` → `_close_source` → `on_source_closed()` is not guarded: `_close_source` catches only `src.close()`. A raise there (in a recorder or audio close) escapes the `except` handler, reaches `BaseException`, and the thread dies. This fails safe: the `finally` calls `_close_source` again, and since the recorder or audio objects have already nulled their handles, the arbiter is released. The status is OFF/red, and PRISM START or PROWL Enter rebuilds the worker. No current close path was found that raises on a real I/O error: `/dev/full` closes cleanly after a failed write, and AudioOut.close swallows. So this only matters for a future bug. A PROWL FAST worker that dies this way while held off goes to the `held_off` branch of `_resume_radio` (`prowl.py:1472`) before the `isFinished` branch. Enter then calls `set_active` on a dead thread and clears the busy line. Fix: wrap `on_source_closed` in `_close_source`, and check `isFinished` before `held_off` in `_resume_radio`. | `RA-RADIOc-poc/poc_teardown.py`: `worker running: False \| arbiter owner: None \| last status: SDR OFF — stopped: teardown bug` | `iqworker.py:126-133`, `:302-308`; `prowl.py:1472-1480` |
| C3 | Low | **The back-off reset after a good block has no test.** Deleting `self._fault_n = 0` (`iqworker.py:270`) leaves all 101 radio tests green (`mutate.sh` M3). Without the reset, one bad stretch would make every later fault wait 60 s for the rest of the session. Fix: in test_b2, let process_block succeed after two faults and assert `_retry_s() == 5`. | `mutate.sh` M3 | `iqworker.py:270`, `tests/test_radio_sdrpp.py:1374` |
| C4 | Low | **The cancel path in `_open` still skips closing a half-open source, and B7 re-queues a poison setting forever.** (a) The diff added `src.close()` to the fault branch only. The early `if self._stop or not self._active: return False` (`:200-201`) comes first. If `RtlTcpSource.open()` fails after the header (a `_send` in `set_rate`/`set_freq`/…, which does not self-close) in the same instant as a page hide or stop, `src` is never kept in `self._src`, so no later `_release` can close it. rtl_tcp would keep the dongle while the arbiter says FREE. The window is very narrow. Move the `src.close()` above the cancel return. (b) `_requeue` brings a failed setting back after every reopen. A value that makes `_apply` raise every time (a bug or a bad value) is now a permanent fault loop at 60 s back-off. Before, it was dropped once. No UI path that produces such a value was found, because the combos and spinners clamp. This fails safe (FAULT is shown). Consider dropping keys that fail twice in a row with an internal error (not SourceError). | code read | `iqworker.py:199-212`, `:243-249` |

## Tests

- `tests/test_radio_sdrpp.py + tests/test_cl5_*.py`: **184 passed, 1 skipped**, 2 of 2 runs.
- `-k "test_n2 or test_b"`: 21 passed, 6 of 6 runs (B4 flake not seen).
- The RA-RADIOb tests against the `77f9783` code (`iqsource.py`, `iqworker.py`, `prism.py`, `prowl.py`
  from 77f9783): 7 failed (b1[100001], b1[100003], b2, b3 ×2, b5, b7), and b6 passes. Mutation
  check (`RA-RADIOc-poc/mutate.sh`): M1 (B7 requeue) passes, M2 (B6 text mode) passes, M3 (back-off
  reset) passes, M4 (PRISM finished check) fails. That gives B6 and B7 PARTIAL and C3.
- Full suite (`QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests --timeout=120
  --timeout-method=thread`): **1886 passed, 18 skipped, 3 failed in 13:28.** The 3 failures are
  the container baseline from RA-RADIO / RA-RADIOb: test_audit_tiles undecodable tile, test_hwlab
  doctor_hwbench, test_sstvdec ISS TLE. There are no new failures. (RADIO-report says 1887/17; the
  skip count depends on the environment.)
- pyflakes is clean on iqsource.py, iqworker.py, prism.py, prowl.py and test_radio_sdrpp.py.
- Not re-rendered: the UI change is run-button state logic (red on a finished worker, START
  rebuilds it), which test_b3 covers. The RA-RADIO renders still apply.

## Follow-ups (not blocking)
C1 (START clears the back-off, plus "retry in N s"), C2 (guard `on_source_closed`; check
`isFinished` before `held_off` in PROWL), C3 + B6 + B7 (tests that pin the real code path), C4
(close before the cancel return; drop a setting that keeps failing). N8 stays with the owner.

Verdict: **MERGE**
