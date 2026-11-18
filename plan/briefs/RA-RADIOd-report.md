# RA-RADIOd: scoped cold re-audit of the RA-RADIOc follow-ups

Auditor: fresh session, audit only, no code changed. Branch `claude/project-thread-z1copz` at
`c8ed161`. Scope: `git diff 2f5347d..HEAD` (palisade_qt/iqworker.py, prism.py, prowl.py,
tests/fake_bin/rtl_tcp, tests/test_radio_sdrpp.py, RADIO-report.md). Inputs: CLAUDE.md,
`RA-RADIOc-report.md`, the last table of `RADIO-report.md`, the diff. The diff stays inside
iqworker / prism / prowl / tests, so the full suite was not run (brief step 3).
New PoCs are in `plan/briefs/RA-RADIOd-poc/`. Run each as `python3 <poc> <worktree> [args]` with
`QT_QPA_PLATFORM=offscreen`, from a scratch directory as cwd.

**Verdict: MERGE.** C3, C4, B6 and B7 are closed, and each is pinned by a test that fails when its
fix is removed. C1 and C2 work, and PoCs confirm it end to end. They are PARTIAL only because some
of their fix lines can be removed with every test still green: PRISM START and PROWL Enter calling
`retry_now()`, and the `on_source_closed` guard. Three new findings, all Low, all fail safe. None of
them leads to an emission, opens two sources, or takes the radio while the page is hidden or held off.

## RA-RADIOc PoCs re-run on `c8ed161`

| PoC | RA-RADIOc result | Now |
|---|---|---|
| poc_backoff_start (C1) | live only after the full back-off | Unchanged: 6.52 s with the scaled clock. Expected, because this PoC presses STOP/START by calling `hold_off`/`set_active` directly, which skips PRISM's `_set_running` where C1 is wired. Superseded by `RA-RADIOd-poc/poc_prism_start.py` below. |
| poc_teardown (C2) | `worker running: False`, `stopped: teardown bug` | **`worker running: True`, owner None, `SDR FAULT — [Errno 5] EIO · retry in 2s`** |
| poc_dropfuzz (B1) seed 1 | 0 misaligned | 4687 reads, 3072 drops, 621 with a carry, **0 misaligned** |

## Results by item

| ID | Result | Evidence | Test |
|---|---|---|---|
| C1 | **PARTIAL** (wiring not pinned) | `iqworker.py:80-84` `retry_now()` clears `_fault` and `_fault_n`, then pokes. Wired in `prism.py:1005-1006` (START, before `set_active`) and `prowl.py:1483-1485` (Enter, last branch). `_fault_text()` (`:304-307`) adds "retry in N s". **poc_prism_start** (real 5 s base, `_fault_n=6`, so a 60 s wait): (a) START from a visible page goes live **0.01 s** later, owner PRISM; (b) START with the page hidden makes **0 opens** in 3 s and the owner stays None; (c) STOP then START goes live 0.01 s later. **poc_prowl_enter**: Enter on a faulted, visible scanner makes 1 open right away. Mutation: M7 (`retry_now` no longer clears) and M12 (no countdown) fail test_c1. **M5 (PRISM `retry_now` call deleted) and M6 (PROWL faulted branch deleted) pass all tests.** test_c1 calls `w.retry_now()` itself, so no test checks that START or Enter call it. Also D2. | test_c1_start_and_enter_retry_a_faulted_worker_at_once_and_say_when (pins only the worker half) |
| C2 | **PARTIAL** (guard not pinned) | `iqworker.py:143-146` wraps `on_source_closed`, and poc_teardown now shows the thread alive. `prowl.py:1473-1478` checks `isFinished` before `held_off`. Mutation: M9 (old order) fails test_c2. **M8 (the `on_source_closed` try/except removed) passes all tests**, while poc_teardown run on the M8 tree shows `worker running: False … stopped: teardown bug`. Fix: make poc_teardown a test, with a `TunerWorker` whose recorder `close()` raises during `_block_fault`, asserting `isRunning()`. | test_c2_prowl_enter_restarts_a_finished_scanner_even_if_it_was_held_off (pins only the PROWL half) |
| C3 | **CLOSED** | `iqworker.py:287` reset. M3 fails test_c3. | test_c3_back_off_resets_after_a_good_block |
| C4 (a) | **CLOSED** | `iqworker.py:211-217`: the cancel return now closes `src` first. Other cancel paths are covered too. An abort from the revoke lambda while `_active` is still set is a SourceError, so it goes to the fault branch, which closes the source (`:220-223`). A successful open followed by a revoke closes it at `:233-236`. M10 fails test_c4. | test_c4_a_cancelled_start_closes_the_half_open_source |
| C4 (b) | **CLOSED** | `iqworker.py:262-268`: only SourceError and OSError are re-queued. The `_apply` paths were checked for an OSError that does not come from the source and would loop forever. IqRecorder and AudioRecorder OSErrors are caught inside `_apply`. `AudioOut()` catches its own `OSError`. None found. M11 (re-queue always) fails test_b7. See D3. | test_b7_settings_queued_when_the_source_fails_are_applied_after_the_reopen |
| B6 | **CLOSED** | The test now drives the real `RtlTcpSource.open()` through `tests/fake_bin/rtl_tcp` with `FAKE_GARBAGE` set. M2 (text-mode drain) fails test_b6. | test_b6_the_output_drain_survives_undecodable_bytes |
| B7 | **CLOSED** | The test now goes through `run()`. M1 (`self._requeue(p)` replaced by `pass`) fails test_b7. | test_b7_… (above) |
| N8 | reserved for owner | unchanged | — |

## Attack results (brief step 2)

- **Can `retry_now()` open two sources?** No. Only the worker thread calls `_make_source` or `_open`. `retry_now` only clears two fields and pokes.
- **Can it take the radio while the page is hidden or held off?** No. `_ensure_radio` returns at `if not self._active` before it reaches the fault gate or `arb.request` (`:162-164`). PRISM calls `set_active(self._active)` after `retry_now`. PROWL's `retry_now` branch requires `self._active` and comes after the held-off branch. poc_prism_start (b): 0 opens, owner None.
- **Thread-safety race: see D1.** `retry_now` is the first GUI-thread writer of `_fault`. The worker reads `self._fault` more than once per check.
- **PROWL Enter order:** finished → swap (also when held off; pinned by test_c2). Held off → resume. Faulted → retry. PANIC → cancel the swap, then resume. Held off and faulted at once → see D2.
- **Re-queue rule and cancel-path close:** as in the C4 rows above.

## New findings

| ID | Sev | Finding | PoC / evidence | Where |
|---|---|---|---|---|
| D1 | Low | **`retry_now()` from the GUI thread can end the worker thread.** The worker checks `self._fault is not None and time.monotonic() - self._fault[1] < …`, then calls `_fault_text()` and reads `fault=self._fault[0]`. These run in `_ensure_radio` and at the top of `_open`, both outside run()'s per-block `try`. If `retry_now()` sets `_fault = None` between two of those reads, a `TypeError` reaches the `BaseException` handler and the thread ends. Before this diff only the worker thread wrote `_fault`, so this race is new. It fails safe: the `finally` releases the radio, the status shows `SDR OFF — stopped: 'NoneType' object is not subscriptable`, and PRISM shows red, so a second START (or PROWL Enter) rebuilds the worker. The operator still sees their START produce an OFF error. The window is a few bytecodes. 15 s of hammering with `sys.setswitchinterval(1e-6)` did not hit it naturally (6 runs, up to 108k calls). A forced interleaving reproduces it every time. Fix: read the fault once into a local (`f = self._fault; if f is not None and now - f[1] < …`) and pass `f` into `_fault_text`/`_status`. Alternatively, have `retry_now` set a flag that the worker consumes. | `RA-RADIOd-poc/poc_retry_race_det.py` (rtl and file): `worker running: False \| owner: None \| last: SDR OFF — stopped: 'NoneType' object is not subscriptable`. `poc_retry_race.py`: no natural hit. | `iqworker.py:166-170`, `:194-196`, `:304-307` |
| D2 | Low | **PROWL Enter on a FAST scanner that is both held off and faulted resumes it but does not skip the back-off.** The held-off branch (`prowl.py:1479-1482`) returns before the `retry_now` branch. After a PANIC or revoke during a fault, the first Enter makes 0 opens and the scanner waits out the rest of the back-off (up to 60 s, with "retry in N s" shown). A second Enter retries. PRISM START does both at once. Fix: call `retry_now()` in the held-off branch too when `w.faulted`. | `RA-RADIOd-poc/poc_prowl_enter.py`: `faulted + held off (PANIC) Enter->True \| opens in 1.2s: 0`, then `second Enter … opens: 1` | `prowl.py:1479-1485` |
| D3 | Low | **Tests are missing for part of C1 and C2, and C4b drops the whole bundle.** (a) M5, M6 and M8 survive, as described in the C1 and C2 rows. Fix: drive test_c1 through `PrismApp._set_running(True)` / `run_btn.click()` and `ProwlApp.primary_action()`, and add the teardown test. (b) When one queued value raises a non-source error, the whole `p` is dropped. Keys applied before the bad one stay applied. Keys after it are lost silently: in FastScanWorker `_apply` that includes `channels`, so the UI could show a bank the worker is not scanning. As in RA-RADIOc C4, no UI path produces such a value, because the inputs clamp. Consider re-queuing the keys that were not reached, or applying them key by key. | `mutate2.py` M5/M6/M8: `100% passed`; code read `iqworker.py:684-713` | `tests/test_radio_sdrpp.py` test_c1 / test_c2; `iqworker.py:262-268` |

## Tests

- `tests/test_radio_sdrpp.py tests/test_cl5_*.py`: **188 passed, 1 skipped** in 139 s.
- Mutation run (`RA-RADIOd-poc/mutate2.py`). Each mutation is applied to a `git archive` copy, never to the worktree, and then `tests/test_radio_sdrpp.py` runs in full. Failing (pinned): M1 B7, M2 B6, M3 C3, M7 C1 worker, M9 C2 PROWL order, M10 C4a, M11 C4b, M12 countdown. Passing (not pinned): **M5** PRISM START `retry_now`, **M6** PROWL Enter `retry_now`, **M8** `on_source_closed` guard.
- pyflakes is clean on iqworker.py, prism.py, prowl.py, iqsource.py and test_radio_sdrpp.py.
- Full suite not run, because the diff is inside the scope the brief allows.
- Not re-rendered: the only UI-visible change is the " · retry in N s" suffix on the FAULT line. The cap went from 90 characters to 80 plus the suffix (at most about 95), and test_c1 checks the text.

## Follow-ups (not blocking)
D1: read `_fault` once per check. D2: retry in PROWL's held-off branch when the worker is faulted.
D3: pin the START/Enter wiring and the teardown guard with tests, and handle the keys after a bad one.
N8 stays with the owner.

Verdict: **MERGE**
