# RA-CL5c — cold re-audit of CL5-fix2 (`fix/cl5-radio` @ f8172c7)

**Verdict: DO NOT MERGE.** CL5-fix2 closes the two blocking items from RA-CL5b. Hidden ATLAS now
acknowledges every revoke, forced free and PANIC. Sub-mode and decoder switches no longer block
the GUI thread and no longer abort the process. All RA-CL5 and RA-CL5b PoCs come out clean
against the tip.

Two blocking conditions remain:

1. **NWR can read LIVE · NO ALERTS while no audio reaches the decoder (N-d PARTIAL, new N-l).**
   The new heartbeat counts rtl_fm's `/proc/<pid>/io` **wchar**, which is *every* byte rtl_fm
   writes, including its stderr. It also counts bytes that only fill the pipe buffer, not bytes
   the decoder reads.
   - An rtl_fm that sends no samples but prints errors read **LIVE · NO ALERTS for the whole 25 s
     run (248/250 samples)**.
   - A multimon-ng that has stopped reading (stuck or SIGSTOPped) reads LIVE for about 3 s after
     every respawn. That is about 30 % of the time until the flap FAULT, which comes after about
     31 s.
2. **A revoke or "FREE THE RADIO" during a pending switch is lost (new N-k).** The retiring
   worker acknowledges and releases. Then `swap_worker` starts the new sub-mode, and it takes
   the radio again: PROWL-FM, or BABEL-SSTV with RUN still ticked. In steady state a revoke
   holds the page off until the operator resumes. PANIC has a `cancel_swap()`; a revoke has
   none. Per the brief this is a radio held after a revoke.

The details follow.

- Auditor: a fresh session, Opus 5.5, working in its own worktree (`origin/fix/cl5-radio`
  f8172c7). No subagents were used, so every stage ran on the session model.
- Environment: Linux, **Python 3.12.3** venv, PySide6 6.12.0, pyqtgraph, flask, numpy and
  tkinter.
- PoCs: run under `QT_QPA_PLATFORM=minimal` with real processes and real threads.
  - Only `radio_arbiter._make_lease` is patched, plus the fault injections each script names:
    fake binaries on PATH and one `NwrWorker._wchar → None` injection for "/proc unreadable".
  - Evidence is in `plan/briefs/RA-CL5c-evidence/`. Re-runs are in `rerun/` (driver:
    `rerun_all.sh`). The new PoCs are the `poc_c_*.py` files with their `.out` logs. Renders are
    in `renders/`.
  - Another audit's leftover fake `rtl_fm` processes were running on this machine. The new PoCs
    count only this process's own descendants.

## 1. Earlier PoCs against the tip (`rerun/`)

| PoC | RA-CL5b | Now |
|---|---|---|
| `poc_revoke` babel/sstv/scan/fm/nwr/prism | clean | clean |
| `poc_revoke` atlas | N/A (drives `AisSource` without `poll()`) | still N/A: the forced free there is the PoC's own design. Re-derived through the hub: `rerun/poc_atlas_hidden_revoke` "no", and `poc_c_atlas` hidden_revoke/forced/panic: 0 bad samples. |
| `poc_release_order` ×3 | clean | clean: `alive at release=[]` in every row (27 rows) |
| `poc_panic` babel, nwr | clean | clean |
| `poc_acquiring`, `poc_arbiter`, `poc_alert_drop`, `poc_eventbus`, `poc_pipeline`, `poc_workers`, `poc_hub_close` | clean | clean. Pipeline (d), the `setsid` grandchild, is the known Low. |
| `poc_gui_block` (BABEL hide/STOP/revoke) | 0.00 s | 0.00 s |
| `poc_babel` r1 / r2 | r2 REGRESSED (N-b) | **clean**. r2: "AIS decoder exited after 0.0s (×3): usb_claim_interface error -6". |
| `poc_e3_bleak` | needs device | needs device (no BlueZ here) |
| `poc_b2_retune` | clean | clean |
| `poc_atlas_hidden_revoke` | **forced free with rtl_ais alive** | **clean**: "radio FREE while rtl_ais alive: no" |
| `poc_gui_block_modeswitch` | 2.0–3.0 s | NWR→FM 0.00 s, FM→SCAN 0.00 s, AIS→SSTV 0.01 s. PANIC 1.03 s (`stop_tree`, accepted). |
| `poc_submode_drop` 3.5 / 2.2 trap / 1.0 trap | rc −6 (SIGABRT) | **rc 0** in all three |
| `poc_nwr_safety` (9 scenarios) | hung: LIVE forever | revoke, forced, panic, hide, submode, **hung**, stall and stall_revoke: 0 violations. decoder_dies: 1 of 80 (≤0.4 s detection latency). |
| `poc_panic_race` (9 holders ×12, plus hidden ATLAS ×8) | 0 violations | **0 violations** |
| `poc_sstv_stale_decode` | next decode after 2412 s | **12 s** |
| `poc_tk_sstv_rotation` | branch: "no SSTV header" | **DECODED PD120 496 lines**. Files: `['iss_pass.wav']` only, with no `.prev.wav` left. |

## 2. Per item

| ID | Verdict | Evidence | Test |
|---|---|---|---|
| N-a hidden ATLAS ack | **CLOSED** | `atlas.py` `PAUSE_WHEN_HIDDEN=False`, `set_hidden`, `src.wake=self.poke`. `poc_c_atlas`: hidden_revoke, hidden_forced and hidden_panic each give 0 bad samples, with the call returning in ≤0.013 s. Hidden during ACQUIRING: rtl_ais starts once HELD while hidden (a lease layer, so allowed), and a revoke is then acknowledged in <0.1 s. Cost while hidden: no new ADS-B or RID source, and the thread count did not grow (4→3). | `test_na_*` (2) |
| N-b stderr tail | **CLOSED** | `babel.py` `_stop_proc` caches `err_tail`. `rerun/poc_babel.out` r2. | `test_nb_*` |
| N-c non-blocking switch | **CLOSED** | `app.py` `swap_worker` / `_retire` / `_on_retired`. `poc_c_swap gui_block` with SIGTERM-ignoring stages and a 3.5 s release: each call took 0.003 s, and the longest event-loop stall was 0.034 s, 0.014 s and 0.014 s. `submode_drop` rc 0. See §3 for the attack results. | `test_nc_*` (3) |
| N-d NWR liveness | **PARTIAL — blocking** | Wedged rtl_fm: 0 of 250 (fixed). /proc/io unreadable: 0 of 250 (fails safe, NOT MONITORING). A decoder dying every 1, 3 or 5 s escalates to "keeps failing … retry in 10s/30s". It reads LIVE only while the decoder process is alive (detection ≤0.4 s). **Still reproduces:** chatter (no samples, stderr spam), 248 of 250 LIVE; stuck_mm, 62 of 200; sigstop, 43 of 200; wedge mid-run, LIVE for up to 2.5 s after the wedge (AUDIO_STALL_S 3 s, by design). Truth in `poc_c_nwr` is the decoder's **rchar** growth with HELD. | `test_nd_*`. Weak: `test_nd_a_flapping…never_reads_live` never asserts on `live_st`. |
| N-e stale decode | **CLOSED**, but see N-m | `poc_sstv_stale_decode` 12 s. No deadlock: the lock is held only for clock writes and emits (all queued), and no GUI-thread path takes `_lock`. | `test_ne_*` |
| N-f Tk window | **CLOSED** | `sstv.py` `_write_last_window`. The ed4694a capture decodes 496 lines again. `.prev.wav` and `.tmp` are removed. Disk cost: the append stream plus **one** rewrite of ≤240 s (~10.6 MB) per recording that rotated. The Qt path passes `keep_last_window=False`. | `test_nf_*` (2), `test_r5` (restored to `3.5 <= secs`) |
| N-g | **CLOSED** | `set(...) & self._layers` | `test_ng_*` |
| N-h | **CLOSED** | Banners: "1 child process(es) stopped by their pages (verified gone) · radio released (was BABEL)", and during a switch "5 of 5 … (was PROWL WX)" | `test_nh_*` |
| N-i | **CLOSED** | The CL5-fix PNGs are committed. `test_cl5_fix2` on 510359e: **14 failed, 1 passed** (`test_nd_flowing_audio_reads_live`, the control), matching the report. | `fix2_tests_on_510359e.txt` |
| N-j | **CLOSED** | `atlas.py` `poll()` re-checks `held_by` after `_open_pipe` | `test_na_hidden_atlas_starts_its_decoder_once_held` |
| N11 | **CLOSED** | `transition` signal with the state captured at emit. RADIOS history after a hidden-ATLAS revoke reads RELEASE, HELD, ACQUIRING (render). It is emitted from worker and `radio-acquire` threads into QObject slots (queued), and the panel disconnects in `stop()`. | `test_n11_*` |
| N13 | PARTIAL (follow-up) | Tk `shell=True` is unchanged | — |
| N14 | **CLOSED** | The RELEASE REQUESTED assertion now reads the card's labels | `test_cl1_screen` |

### Re-rated from RA-CL5b

| ID | RA-CL5b | RA-CL5c |
|---|---|---|
| A1 revoke | REGRESSED | **CLOSED for N-a.** A revoke during a pending switch is lost: see N-k. |
| R2 | REGRESSED (N-b) | **CLOSED** |
| R3 NWR honest | PARTIAL | **PARTIAL**: wedged rtl_fm is fixed, but the stderr and stuck-decoder cases remain (N-d / N-l) |
| R5 | PARTIAL / REGRESSED | **CLOSED** (Tk decodes again; Qt from memory) |
| Item 6 GUI blocks | OPEN | **CLOSED**: RUN, hide, revoke and mode switches take ≤0.034 s. PANIC takes 1.03 s (`stop_tree`, accepted). Page `stop()`/close still joins up to 3 s and then parks, unchanged and close-only (`poc_c_swap close`: 3.00 s, parked, rc 0, nothing left). |

## 3. Attacks on the fix (new PoCs)

**`swap_worker`** (`poc_c_swap.out`, `poc_c_swap2.out`; 3.5 s release, TRAP stages):
- Two workers on the dongle: never. The successor starts only after the old QThread's
  `finished`, and that comes after kill → wait → `lease.release()` (`ARBITER ACQUIRING PROWL-FM`
  1 ms after `LEASE.release … done`).
- Same lease name: SCAN→FM→SCAN within 0.1 s ends HELD(PROWL-SCAN) with one `rtl_power`. BABEL
  AIS→SSTV→POCSAG ends HELD(BABEL). The retiring worker never freed its successor's lease.
- QThread references: `_retain` plus `_retiring`. No SIGABRT in any run.
- `stop()` while retiring: close joins 3 s, parks, rc 0, arbiter FREE, no children.
- A worker that never finishes (lease release blocks 40 s): the page says "SCAN: waiting for the
  previous mode to give the radio back" with the chip "SDR — switching modes". Arbiter FREE,
  strip FREE. Honest.
- PANIC during a switch: PROWL and BABEL are FREE and stay FREE for 11.5 s, with no children
  and RUN unticked.
- **Revoke during a switch: FAIL (N-k).**

**NWR** (`poc_c_nwr.out`, 17 scenarios): see the N-d row. Revoke, forced, panic, hide,
NWR→FM, FM→NWR, SCAN→NWR and retune: 0 real violations. The 0.6–0.8 s rows in retune, from_*
and dies* are this PoC's own artefact. Its truth needs 1 s of rchar history on a new pid, and on
the `dies*` fakes rchar is taken from the `sh` wrapper.

**Arbiter.** `_release` now emits FREE before `lease.release()`. Only display slots (strip and
RADIOS) listen to `changed`/`transition`; no listener requests on FREE. Requests come only from
worker polls, and those could already be granted during `lease.release()`: owner was None before
the release at 510359e too. So nothing new is granted during a readsb restart. Inside one page,
a switch starts the new worker only after `lease.release()` returns. Across pages (PROWL hidden
→ BABEL RUN), BABEL was HELD at 2.95 s while the PROWL-SCAN release ran until 4.99 s. That is
pre-existing, and listed as follow-up N-o.

**ATLAS PANIC while ticking a layer** (`poc_c_atlas_toggle_panic.out`): 0 of 10.

## 4. New findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| N-k | **High, blocking** | A revoke ("FREE THE RADIO", or a page asking) that lands while a switch is pending is acknowledged by the retiring worker. Then `_finish_swap` starts the new sub-mode, which takes the radio straight back. The steady-state rule is that a revoke holds the page off until the operator resumes; it is bypassed. PROWL NWR→FM plus revoke ends HELD(PROWL-FM). BABEL AIS→SSTV plus revoke ends HELD(BABEL-SSTV) with RUN still ticked: the retiring worker's `run_off` status was disconnected, so the page never unticked. Fix: treat a `revoked` for the page's lease while `swapping()` like PANIC (`cancel_swap`, untick RUN). | `poc_c_swap.out` revoke and babel_revoke |
| N-l | **High, blocking** (N-d residual) | The heartbeat is rtl_fm's **wchar**: all writes, including stderr to DEVNULL, and pipe-buffer fills. An rtl_fm that stalls while printing errors reads LIVE · NO ALERTS indefinitely. A decoder that stops reading reads LIVE for about 3 s per 10 s respawn cycle until the flap FAULT (about 31 s), and again after each hold-down. Use the decoder's input instead (multimon-ng **rchar**, or `/proc/<pid>/fdinfo` pipe position), or count stdout bytes through a relay. | `poc_c_nwr.out` chatter, stuck_mm, sigstop |
| N-m | Medium | **Dropped SSTV frame.** `_decode_job` discards a finished decode when `rec is not self._rec`. A complete PD120 frame from audio captured before the operator pressed STOP (or hid BABEL, or a revoke) is never shown. At 510359e it was shown. | `poc_c_sstv_drop.out` (tip: DROPPED; 510359e: shown) |
| N-n | Low | Qt delivers queued signals posted before `_disconnect`, as verified with PySide6 6.12. A retiring worker's last status can therefore overwrite "SDR — switching modes" with its old chip for one event-loop turn. Also, a parked worker that finishes after its page is deleted raises `RuntimeError: Signal source has been deleted` from the `finished` lambda (stderr of `render_racl5c.out`). | code, `render_racl5c.out` |
| N-o | Medium (pre-existing, follow-up) | Cross-page grant during `RtlLease.release()`. The arbiter is FREE before readsb restarts, so another page's `RtlLease.acquire` can run concurrently with `systemctl start readsb`. `release()` then writes `owner=None` over the new holder in the lease file. This is code-level and was not introduced here. | `poc_c_swap.out` babel_* (HELD BABEL 2.95 s, SCAN release done 4.99 s) |
| N-p | Low | `_RETAINED` grows by one QThread per mode switch, for the life of the process | `app.py` `_retire` |
| N-q | Low | A retiring NWR worker does not `_drain()` its parsed SAME queue on stop, so an alert parsed in the last ≤400 ms before a switch, hide or revoke is not emitted. This is pre-existing. SAME headers repeat three times, so the risk of losing all three is low. Flag for CL-NWR. | code (`NwrWorker.run` → `_finish`) |

## 5. Regression

- Targeted tests (`test_cl5_fix2`, `test_cl5_fix`, `test_cl5_radio`, `test_cl1_*`,
  `test_palisade_qt`), Python 3.12.3: **317 passed, 1 skipped** (`targeted_py312.txt`).
- Full suite, Python 3.12.3 (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`):
  see `suite_py312.txt`. Result: **3 failed, 1065 passed, 3 skipped**. The 3 failures are the known baseline (`test_audit_tiles::…undecodable…`, `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::…iss_passes…`), the same as RA-CL5b.
- `test_cl5_fix2` on 510359e: 14 of 15 fail. The control passes.
- Assertions changed against c4f5612:
  - `test_cl1_screen`: N14 made real (stronger).
  - `test_cl5_fix` fix12: `w._rec = rec` is the seam for the N-e identity check (justified).
  - `test_r5`: back to `3.5 <= secs`, plus rotation and no `.prev.wav`. `bytes_written` now
    allows one last-window rewrite (justified by N-f).
  - No denial or negative assertion was weakened.
- pyflakes on the touched files: clean (`pyflakes.txt`).
- Demo mode, CL1 keyboard, OVERWATCH director and RADIOS: the targeted and full suites pass.
  The RADIOS render shows correct transitions. BABEL's fault banner shows the stderr again.

## 6. Renders (1280×720, live, dark + sun) — `renders/`

| Render | Shows |
|---|---|
| `prowl_nwr_wedged_*` | "NOT MONITORING — NWR — waiting for audio" in the alert colour, SAME ALERT "NOT MONITORING". Strip "PROWL WX" (held, true). Honest. |
| `prowl_slow_switch_*` | FM page, "FM: waiting for the previous mode to give the radio back", chip "SDR — switching modes", strip FREE (arbiter FREE, readsb restarting). Honest. |
| `radios_after_atlas_hidden_revoke_*` | FREE, no rtl_ais; history RELEASE, HELD, ACQUIRING. Honest. |
| `babel_after_panic_*` | FREE, RUN unticked, banner "1 child process(es) stopped by their pages (verified gone) · radio released (was BABEL)". Honest. |

Script: `render_racl5c.py`, output in `render_racl5c.out`. The chatter case (N-l) was not
rendered: the PoC log already shows the label text "LIVE · WX2 162.400" / "NO ALERTS".

## 7. Fix list for CL5-fix3

1. N-k: a revoke for the page's lease during `swapping()` cancels the swap, and BABEL unticks
   RUN. Add a test: revoke 0.2 s into a switch with a 3.5 s release, then assert the arbiter
   stays FREE.
2. N-l: the NWR heartbeat must measure audio the decoder consumed (multimon-ng rchar or the
   pipe read position), not rtl_fm's wchar. Add tests with an rtl_fm that writes stderr only,
   and with a multimon-ng that never reads.
3. N-m: fold or emit a finished frame from a superseded recorder; only the clock write must be
   dropped.
4. Low and follow-up: N-n, N-o, N-p, N-q, N13. Make `test_nd_a_flapping…` assert on `live`.

**DO NOT MERGE**
