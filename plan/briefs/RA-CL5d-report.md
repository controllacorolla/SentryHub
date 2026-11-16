# RA-CL5d — cold re-audit of CL5-fix3 (`fix/cl5-radio` @ e2cfcb1)

**Verdict: MERGE.** None of the blocking conditions reproduce on the tip. A revoke, forced free or
PANIC landing in any phase of a switch leaves the arbiter FREE and keeps it FREE. Every phase
where a holder existed was tried, across PROWL, BABEL and both same-name chains. NWR no longer
reads LIVE on stderr chatter, a stuck or SIGSTOPped decoder, or an unreadable `/proc`. A healthy
receiver never dropped out of LIVE in 60 s, including under full CPU load. All RA-CL5,
RA-CL5b and RA-CL5c PoCs come out clean.

Two follow-ups remain, both Medium and not blocking:
- **N-m PARTIAL:** a late SSTV refinement still produces a duplicate decode event and frame
  count.
- **NWR has no audio-rate floor (new N-r).**

| Item | Detail |
|---|---|
| Auditor | Fresh session, Opus 5.5. No subagents, so every stage ran on the session model. |
| Worktree | `origin/fix/cl5-radio`, e2cfcb1 |
| Environment | Linux, **Python 3.12.3** venv, PySide6 6.12.0 |
| PoCs | Run under `QT_QPA_PLATFORM=minimal` with real processes and real threads. Only `radio_arbiter._make_lease` is patched, plus fake binaries on PATH. The SSTV PoC also uses the recorder and decoder seams, as RA-CL5c's did. |
| Evidence | `plan/briefs/RA-CL5d-evidence/` |

## 1. Earlier PoCs against the tip

- Driver: `rerun_all.sh`, output in `rerun/`.
- **Every PoC in RA-CL5, RA-CL5b and RA-CL5c comes out clean**, matching RA-CL5c §1. Run results:
  - `poc_release_order`: `alive at release=[]` in all 27 rows.
  - `poc_panic_race`: 0 violations on 9 holders × 12, and on hidden ATLAS × 8.
  - `poc_nwr_safety`: 0 violations in all 9 scenarios.
  - `poc_gui_block_modeswitch`: 0.00 s for every switch; PANIC 1.03 s (accepted).
  - `poc_submode_drop`: rc 0.
  - `poc_babel` r2: the stderr is shown.
  - `poc_tk_sstv_rotation`: DECODED PD120 496 lines.
  - `poc_c_swap`: revoke, babel_revoke, panic and babel_panic end FREE. `gui_block` stalls are
    ≤0.038 s.
- **`poc_c_atlas hidden_forced` (7 bad) and `toggle_panic` (2 of 10) in the batch were PoC
  artefacts.** Those PoCs count `rtl_ais` machine-wide, and my BABEL-AIS swap PoC was running at
  the same time. Run alone, both come out clean (0 and 0 of 10): `rerun/poc_c_atlas_isolated.out`.
- **`poc_c_nwr`:**
  - `io_unreadable` no longer injects anything: it patches `_wchar`, which is now `_rchar`.
    `poc_d_nwr` redoes it.
  - The violations in `sigstop` and `wedge_mid` (≤1.4 s) are this PoC's 1 s truth window plus
    batch load. Run alone with a primed truth (§3): ≤0.5 s.
- Known Low, unchanged: `poc_pipeline` (d), a `setsid` grandchild.

## 2. Per item

| ID | Verdict | Evidence | Test |
|---|---|---|---|
| **N-k** revoke during a switch | **CLOSED** | `app.py` `_on_revoked_during_swap`. `poc_d_swap.out` and `poc_d_swap2.out` (TRAP stages, 3.5 s release), every phase where the old mode held the radio. Each run ends **FREE with no openers and no worker**, with RUN unticked on BABEL. **Results:** **(1)** revoke at 0, 0.05, 0.2 and 0.6 s: clean. **(2)** forced free (0.3 s timeout) at 0, 0.2 and 1.0 s: clean. **(3)** PANIC at 0, 0.05, 0.2, 0.6, 1, 2 and 4 s: clean. **(4)** revoke or PANIC the instant the **new** mode goes ACQUIRING: clean; the worker holds off with "press Enter to resume". **(5)** chains: SCAN→FM→SCAN with revoke or PANIC in the same GUI turn is clean, and so are BABEL AIS→SSTV→POCSAG with revoke or PANIC and BABEL revoke at 0, 0.2 and 1 s. **(6)** BABEL forced free at 0 and 0.2 s: clean. **(7)** ATLAS AIS ticked and hidden while PROWL is switching, then PANIC at 0, 0.2 and 1 s: FREE throughout, with the ATLAS layer unticked. **(8)** Another page (BABEL RUN) while PROWL is switching: BABEL gets the radio, and the hidden FM worker stays "OFF — page hidden". **(9)** The operator re-ticks RUN after the cancel: HELD BABEL-SSTV, as intended. Runs marked N/A (revoke at ≥1 s; chains with a 0.05 s gap): `revoke()` returned **None**. The old mode had already released, so nothing was held, and the new mode starting there is correct. No state is shown that the page does not have: RUN is never ticked without a worker, and "press Enter" never appears while HELD. | `test_nk_a_revoke_during_a_prowl_switch_sticks`, `test_nk_a_revoke_during_a_babel_switch_sticks_and_unticks_run` |
| **N-l** NWR heartbeat | **CLOSED** | `prowl.py` `_audio_flowing` reads the decoder's `rchar` (procs[-1] is multimon-ng, a direct exec, with no shell). `poc_d_nwr.out`, with the truth's history primed and each run on its own. Values are LIVE claims per sample. **(1)** **chatter: 0/250.** **(2)** **stuck multimon-ng: 0/250.** **(3)** **SIGSTOP:** 5 samples, longest 0.5 s. This is detection latency: AUDIO_GAP_S plus one 0.4 s poll. **(4)** **/proc unreadable** (`_rchar→None`): 0, NOT MONITORING. **(5)** wedged and wedge_mid: ≤0.2 s. **(6)** Decoders dying every 1, 3 or 5 s (both the sh fakes and a real reader that exits): LIVE only while it really reads, then FAULT and hold-down. The longest violation is 0.2 s, at death. **(7)** revoke, forced, panic, hide, retune, to_fm, from_fm and from_scan: 0. **No spurious drop:** at real rtl_fm cadence (5.7 kB per 129 ms) the receiver is never out of LIVE: 0 of 560 samples over 60 s, and 0 of 560 with 4 CPU burners. Bursty audio with gaps of 0.8 s reads LIVE; with gaps of 1.5 s it never reads LIVE (fails safe; see N-r). Render: `prowl_nwr_stderr_only_*`. | `test_nl_rtl_fm_that_only_writes_stderr_never_reads_live`, `test_nl_a_decoder_that_never_reads_never_reads_live` |
| weak-test note | **CLOSED** | `test_nl_flapping_decoder_never_reports_live` asserts `True not in lv` | same |
| **N-m** SSTV late frame | **PARTIAL (Medium, follow-up)** | **Shown: yes. Shown once: only if the decode lands within about 1 s of STOP.** `_stop_rec` sets `_stale_frame` from the live frame. But `step()` calls `_give_back` → `_stop_rec` again on **every 1 s step** while RUN is off. With `rec` now None, that resets `_stale_frame = None` (`babel.py` `_stop_rec`). A refinement that lands later is folded as a **new** frame: a second id, a **second decode event**, and the page count +1. `poc_d_sstv.out`, with real BabelApp and SstvWorker threads: **dup 3.0 s gives 2 events and ids [1, 2], "2 frames"**. **leak**, with RUN re-pressed 0.3 s after STOP: the new RUN reads "3 frames" for 2 real frames, and the inflated count carries into the next RUN. Control **dup 0.5 s: clean** (one id, one event). The decode clock does **not** leak. A real `sstvdec` decode of 120 s of audio takes 0.53 s on this x86 host, so a delay over 1 s on the CM5 is plausible. `test_nm_…` calls `_stop_rec` only once, so it misses this. Fix: keep `_stale_frame` when `rec is None`, and add a test with two `_stop_rec` calls before the late result. | `test_nm_a_frame_decoded_after_stop_is_still_shown_once` (insufficient) |
| **N-n** `_Relay` | **CLOSED** | `app.py` `_Relay`. **(1)** Pages that use `make_worker` get every row, status, error and fault through one GUI-thread QObject per worker, so per-sender order is preserved. The relay is cut only in `_retire`, so the current worker's signals are never dropped. **(2)** Nothing from a retired worker is applied: the `_on` flag drops queued arrivals. **(3)** Lifetime: the relay is a child of the page, and the worker keeps only a Python reference. When the page is deleted, Qt auto-disconnects. **(4)** FORGE, RECON, SWEEP, SYSTEM, OVERWATCH and BENCH connect their workers directly. None of them swaps workers, and their code is untouched by this diff, so nothing changes there. **(5)** One consequence: a retiring NWR worker's final `_drain()` rows (N-q) are cut on a **sub-mode switch**. The alert itself still reaches the event bus and OPS (`_emit_alert` publishes independently). On hide, revoke and PANIC the worker is not retired, so the row is delivered. | `test_nn_a_retired_workers_late_status_is_ignored` |
| N-n (b) `_emit_quiet` | **PARTIAL (Low)**: works, no test | No `RuntimeError` / "Signal source has been deleted" appears in any log, including parked-worker closes in `poc_d_swap*`. There is no regression test. | — |
| N-q NWR drain | **CLOSED** (the residual is noted under N-n) | `_kill` → `_drain()` | `test_nq_nwr_emits_alerts_parsed_before_a_stop` |
| N13 | OPEN (follow-up) | unchanged | — |
| N-o, N-p | OPEN (follow-up, pre-existing) | Not made worse: `_retain` still adds one QThread per switch, and the arbiter is unchanged | — |

### Re-rated from RA-CL5c

| ID | RA-CL5c | RA-CL5d |
|---|---|---|
| A1 revoke | CLOSED, except a revoke during a pending switch (N-k) | **CLOSED**. Steady-state and mid-switch revokes all end FREE (§2 N-k, plus `poc_revoke` and `poc_c_swap`) |
| R3 NWR honest | PARTIAL | **CLOSED** for every case in the brief. The residual (no rate floor) is N-r, Medium. |

## 3. New findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| N-r | Medium | **NWR LIVE has no rate floor.** Any `rchar` growth with no gap over 1 s counts as audio. An rtl_fm that prints errors and dribbles 2 bytes every 0.5 s on stdout (`stderr_trickle`) reads **LIVE · NO ALERTS for 245 of 250 samples**. 64 B per 0.3 s (0.5 % of 44.1 kB/s, `trickle`) does the same. A real rtl_fm writes whole demod blocks (about 5.7 kB) or nothing, so this is contrived. It would still matter for a receiver losing most USB transfers. Not blocking. Suggested fix: require at least about 50 % of 44.1 kB/s over the settle window. The inverse case fails safe: audio arriving at full rate in 1.5 s bursts never reads LIVE. | `poc_d_nwr.out` stderr_trickle, trickle, bursty15 |
| N-s | Low | **The "SDR — switching modes" chip never clears** after a switch that a revoke or PANIC cancelled, in both PROWL and BABEL. It also stays after a same-name SCAN chain whose new ScanWorker is running and HELD. The radio claims are still right: the strip reads FREE (or the true holder), BABEL RUN is unticked, and PROWL says "radio off — press Enter to start". BABEL after a revoke-cancel gives no "press RUN" hint (busy is empty). The SSTV panel's static "listening…" placeholder is pre-existing, and it shows in every idle state. | renders `prowl_after_revoke_during_switch_*`, `babel_after_revoke_during_switch_*`; `poc_d_swap2.out` chain FINAL |
| N-t | Low | PROWL after a revoke-cancel resumes only on Enter. Re-fronting the page does not resume it, as it does in the steady-state revoke. The two paths are inconsistent, but this one fails safe. | code `_resume_radio` / `set_active` |

## 4. Regression

- **Targeted tests** on Python 3.12.3 (`test_cl5_fix3`, `test_cl5_fix2`, `test_cl5_fix`,
  `test_cl5_radio`, `test_cl1_*`, `test_palisade_qt`): **325 passed, 1 skipped**
  (`targeted_py312.txt`).
- **Full suite** on Python 3.12.3 (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q
  tests`): **3 failed, 1073 passed, 3 skipped** (`suite_py312.txt`). The 3 failures are the
  known baseline: `test_audit_tiles::…undecodable…`, `test_hwlab::test_doctor_hwbench_check` and
  `test_sstvdec::…iss_passes…`.
- **`test_cl5_fix3` on f8172c7:** **8 of 8 fail** (`fix3_tests_on_f8172c7.txt`).
- **Assertions changed against 9b2f940:** none. `git diff 9b2f940 HEAD -- tests` adds only
  `test_cl5_fix3.py`.
  - No existing test references `_wchar`. The only NWR monkeypatch is `AUDIO_RESPAWN_S`, which
    still exists.
  - There is no test for "/proc unreadable" after the switch to `_rchar`, but the PoC passes.
    Low: add one.
- **pyflakes** on `app.py`, `babel.py`, `prowl.py` and `test_cl5_fix3.py`: clean (`pyflakes.txt`).
- **Elsewhere:**
  - Demo mode, the CL1 keyboard tests, the OVERWATCH director, the RADIOS panel and the BABEL
    fault banner are green in the targeted and full suites.
  - `poc_babel` r2 shows the stderr in the fault banner.
  - No GUI-thread block: switches stall ≤0.038 s.
  - No zombies or surviving decoders after any of my runs: every `END` line reads `children=[]`.

## 5. Renders (1280×720, live, dark + sun): `renders/`

Script: `render_racl5d.py`. The arbiter states are in `render_racl5d.out`.

| Render | Shows | Honest? |
|---|---|---|
| `prowl_nwr_stderr_only_*` | RECEIVER "NOT MONITORING — NWR — no audio reaching the decoder (5s)", SAME ALERT "NOT MONITORING". The strip reads PROWL WX, which is true: the radio is held. | yes |
| `prowl_revoke_mid_switch_*` | Revoke 0.2 s into NWR→FM with TRAP stages; the revoke returned PROWL-NWR. "FM: waiting for the previous mode…", strip FREE | yes |
| `prowl_after_revoke_during_switch_*` | FREE, no worker, no openers, "FM: radio off — press Enter to start". The status chip still reads "switching modes" (N-s). | yes (chip Low) |
| `babel_after_revoke_during_switch_*` | FREE, RUN unticked, no worker. The chip reads "switching modes" and there is no RUN hint (N-s). | yes (chip Low) |
| `babel_after_panic_*` | FREE, RUN unticked, banner "1 child process(es) stopped by their pages (verified gone) · radio released (was BABEL)" | yes |

## 6. Follow-ups (not blocking)

1. N-m: keep `_stale_frame` across repeated `_stop_rec()` calls while `rec is None`. Add a test
   with a late result after two stops.
2. N-r: an audio-rate floor for NWR LIVE, plus a test.
3. N-s and N-t: clear the swap chip in `on_swapped`/`_finish_swap`; BABEL should say "press RUN"
   after a cancel.
4. N-n (b): add a test. Add a `_rchar`-unreadable test.
5. Carried over: N-o, N-p, N13, and `poc_pipeline` (d).

**MERGE**
