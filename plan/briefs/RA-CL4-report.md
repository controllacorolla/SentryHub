# RA-CL4 — cold re-audit of CL4 (`fix/cl4-honest-state` @ 461f5e2)

**Verdict: DO NOT MERGE.** One new High finding blocks the merge. When HOME is not set, the OPS PPI and the ATLAS map
draw live contacts on nm range rings centred on the *first contact heard*, and ATLAS fetches its basemap for 0°N 0°E
(**N26**). H5 is therefore PARTIAL. Two new Medium findings make the D4 empty state PARTIAL: the ENGAGEMENT trail says
"WATCHING — nothing authorized yet" over a tampered chain (**N27**), and it says "NO ENGAGEMENT" while an engagement is
active and its chain cannot be read (**N28**). The gate/evidence work holds. N20–N25, N12, N13, N15 and R1 are closed,
and every RA-CL3d DEFECT PoC now fails because the defect is gone.

Auditor: fresh session, Claude Opus 5.5. Every verdict came from the session model. No subagents were used.
Env: Linux, Python **3.12.3** venv (PySide6 6.12, pyqtgraph, flask, numpy), xvfb, Qt offscreen. I read the audit PDF
§§ H/E/D4/L5, RA-CL3d and the RA-CL3b/c rows for N11–N15/R1, and the diff `04a76ab..461f5e2`.
`CL4-report.md` was not read before the verdicts.

PoCs (new): `plan/briefs/RA-CL4-poc/poc_ra_cl4_gates.py` (22 passed) and `poc_ra_cl4_honest.py` (12 passed).
Run with `SUITE=<checkout> [QT_QPA_PLATFORM=offscreen xvfb-run -a] pytest -q <file>`. `FIXED_*`/`OK_*` means the fix
holds. `DEFECT_*` means the defect reproduces (the test passes when it does). Renders: `plan/briefs/RA-CL4-renders/`.

## Per ID

| ID | Verdict | Evidence | Test |
|---|---|---|---|
| H1 | CLOSED | SWEEP shows one fixed row per detector (OFFLINE + reason, LEARNING/WATCHING + count + age). Findings show an OFFLINE empty state, "no findings does not mean all clear". Detector state no longer reaches the shared chip. `sweep.py:80-155`, `recon.py:245-260`. Render `sweep_*_live_ra.png` | `test_cl4_honest::test_h1_*` (3) |
| H2 | CLOSED | Real fake `rtl_power` on PATH. When it dies (exit 1, stderr), the chip reads "SDR FAULT — rtl_power exited (1): usb_claim_interface error -6". When it is silent, the chip reads "STALE — no sweep in 1s". LIVE never appears. `prism.py:194-207, 258-290` | `test_h2_*`, PoC `test_FIXED_h2_*` (2) |
| H3 | CLOSED (Low residual N30) | Real fake `iw`. Exit 240 gives "WIFI SCAN FAILED — exit 240 — …" with no rows. argv is `dev wlan0 scan passive`. While BLE is shown, 0 scans; RECON hidden pauses the scan. `recon.py:51-73, 175-188, 503-512` | `test_h3_*` (4), PoC `test_FIXED_h3_*`, `test_OK_h3_*` |
| H4 | CLOSED | A `RtlLease.acquire` that raises (real arbiter thread) gives transitions ACQUIRING→FAILED×3, never HELD, and the arbiter returns to FREE. PRISM says "RADIO FAILED — … (retry in Ns)" / "SDR OFF — radio acquire failed: …". It retries after the backoff without wedging. `radio_arbiter.py:33-52, 98-122` | `test_h4_*` (2), PoC `test_FIXED_h4_*` |
| H5 | **PARTIAL → N26 (High)** | There is no hard-coded HOME. Tables, OPS "nearest" and ATLAS RANGE/BEARING are suppressed, OVERWATCH predicts nothing, and SETTINGS shows NOT SET and applies changes live. However, the PPI and the map still plot contacts on 20/40/60 nm rings from a provisional origin, and the basemap is centred on (0, 0) | `test_h5_*` (4). PoC `test_DEFECT_atlas_without_home_*`, `test_DEFECT_ops_ppi_without_home_*`. Renders `stress_ops_home_unset_dark.png`, `stress_atlas_home_unset_dark.png` |
| H6 | CLOSED | The chip comes from the USB ID plus the bound driver (`radios.sdr_state`) and the arbiter. A bound DVB driver reads "SDR BLOCKED — dvb_usb_rtl28xxu bound". `ops.py:72-87` | `test_h6_*` (2) |
| H7 | CLOSED | Every event carries `demo` (default False). Workers default to `demo=False`. DEMO is a hatched border plus a strip slot, and pages can no longer overwrite it | `test_h7_*` (2), `test_palisade_qt::test_eventbus_typed_contract` |
| H8 | CLOSED | BENCH shows STARTING until the runner has been up 1 s, then KEYED. If it exits first, it shows FAILED TO KEY with the exit code. The power spinbox reaches `_settings()` | `test_h8_*` (2) |
| H10 | CLOSED | The chip is per layer ("ADS-B NO FEED · DF — · BALLOONS —"), and a live station can no longer hide a dead ADS-B feed | `test_h10_*` |
| H11 | CLOSED | The LEVEL column shows a unitless % on the channel being listened to and is blank elsewhere. No dBm, and no constant −100. The live squelch is unchanged (demo-only default) | `test_h11_*` |
| H12 | CLOSED | `peak_hold - 0.5` dB per sweep (`scope.py:96`) | `test_h12_*` |
| H13 | CLOSED | "PEAK · dB (relative)" / "dB rel" | `test_h13_*` |
| H14 | CLOSED | Real decode timestamps over the last 60 s ("N in the last min") | `test_h14_*` |
| H15 | CLOSED | The military count appears only in demo, marked "(demo)" | `test_h15_*` |
| H16 | CLOSED | AIS/ACARS/POCSAG/RDS publish `decode` from the live runners | `test_h16_*` |
| H17 | **PARTIAL → N29 (Med)** | There are now per-type logs and a contact store keyed by id. 40×30 aircraft no longer evict the alert, which stays in SITREP and the assistant until acknowledged. With no feed, SITREP says "No feed is running … not an all-clear". However, `bus.feeds()` counts any publisher as a feed (N29) | `test_h17_*` (5), PoC `test_OK_h17_thirty_aircraft_*`, `test_DEFECT_sitrep_calls_a_pass_prediction_*` |
| H18 | CLOSED | There is no default remote host. Free-form input returns NOT IMPLEMENTED, with no probe and no GUI-thread network call | `test_h18_*` (2) |
| H19 | CLOSED | `timebase.zulu` is used everywhere, with (Z) headers. The "record" marker is gone and the TLE age is shown, turning amber after 7 d | `test_h19_*` |
| E1 | CLOSED (Low residual) | A real hour-old `aircraft.json` reads `feed.status == "stale"`. ATLAS publishes nothing and reports `adsb.state = stale`. `sky_app.py:689-704`, `atlas.py:681-700`. Residual: a file with no `now` key is treated as live with age 0 (`sky_app.py:697`). readsb and dump1090-fa always write `now` | `test_e1_*`, PoC `test_FIXED_e1_l5_*` |
| E4 | CLOSED | BLE with bleak present, CAN with SocketCAN up, sensors with rtl_433 present, MESH and the detectors all say NOT IMPLEMENTED. Hardware is blamed only when it is absent | `test_e4_*` (3) |
| D4 | **PARTIAL → N27, N28 (Med)** | There is one EmptyState with three looks, and no feed table is blank in any render (dark + sun, 14 screens). However, the ENGAGEMENT trail empty state is wrong in two chain states | `test_d4_*` (5). PoC `test_DEFECT_engagement_*` (2). Render `stress_engagement_tampered_sun.png` |
| L5 | CLOSED | Remote Mode serves real ADS-B through `adsb_providers`. A stale feed gives 0 contacts and "ADS-B STALE (last data 3600s ago)". The dashboard builds cells with `textContent` and has no `innerHTML`. A hostile callsign goes back as JSON data | `test_l5_*` (3), PoC `test_FIXED_e1_l5_*` |
| N11 | CLOSED | The trail uses `fit_viewport`, with no h-scroll at 1280 (renders) | `test_n11_*` |
| **N20** | CLOSED | With real groups, the leader exits on SIGTERM and the member ignores it. END now SIGKILLs the member and records a verified kill (3.07 s). If the member survives SIGKILL (simulated), the record is `unconfirmed` "…a process in its group survived SIGKILL" and the row is UNCONFIRMED. The hub-owned kill behaves the same way (`executor.py:236-282, 346-367`, `chain.py:450`) | `test_n20_*` (5). PoC `test_FIXED_n20_*` (4). RA-CL3d `DEFECT_group_member…` / `PREEXISTING_…` now fail |
| N21 | CLOSED | Kill/exit are decided under one lock, and a signal exit after a kill keeps KILLED | `test_n21_*` (2). RA-CL3d `DEFECT_rollover…` now fails |
| N22 | CLOSED | A zombie orphan now records "is the process logged at launch but it had already exited (zombie…)" | `test_n22_*`. RA-CL3d `DEFECT_zombie…` now fails |
| N23 | CLOSED (info residual N32) | A forged keyed record naming the hub's pgrp leader or ppid gets no signal | `test_n23_*`, PoC `test_FIXED_n23_*`. RA-CL3d `DEFECT_own_process_group…` now fails |
| N24 | CLOSED | Four SIGTERM-ignoring orphans now take 3.11 s, down from 6.31 s: one TERM pass, one wait, one KILL pass | `test_n24_*` (2), PoC `test_OK_n24_*` |
| N25 | CLOSED (read + unit) | `p_stat` at offset 36 and `p_pid` at 40 are checked against the pid, and the layout is correct for 64-bit `extern_proc`. **Not run on a Mac** | `test_n25_*` (2) |
| N12 | CLOSED (gate). Display → N28 | Six malformed heads (binary, `1 2`, 20 digits, `-1`, non-ASCII digits, empty) and five hostile lines (`1`, `[]`, `null`, `"x"`, 50k-deep nesting) all raise ChainError. The gate fails closed and nothing raises raw | `test_n12_*` (3), PoC `test_FIXED_n12_*` (11). RA-CL3b `DEFECT_malformed…` now fails |
| N13 | CLOSED | A real `kill -9` between the line fsync and the head rename, then reopen, gives `verify` OK and the tail `note, recovered, note`. The engagement keeps authorizing. A directory-fsync failure no longer bricks the chain. Two unaccounted lines are still refused | `test_n13*` (4), PoC `test_FIXED_n13_*`. RA-CL3b `DEFECT_directory_fsync…` / `DEFECT_sigkill…` now fail |
| N15 | CLOSED | `issue` carries `auth_seq`, and the fold uses it (with N10 fallback) | `test_n15_*` (3) |
| R1 | CLOSED (documented limit) | A rollback while the hub has the chain open is refused ("has 1 records, but this session already saw 4"), and authorize refuses. After a restart a snapshot still verifies, which is the limit `chain.py:32-35` states. The docstring no longer overclaims | `test_r1_*` (2), PoC `test_FIXED_r1_*`. RA-CL3b `DEFECT_snapshot…` now fails in-process |

RA-CL3d PoCs rerun (`poc_ra_cl3d.py`): 20 passed and 6 failed. The 6 failures are the five DEFECT/PREEXISTING tests,
which now fail because the defects are gone, and `test_OK_end_completes_when_a_step_raises`. That test monkeypatches
`_kill_orphan`, which END no longer calls (it batches through `_kill_orphans`), so the brief says it no longer
applies. `poc_ra_cl3c.py` gave 13 passed. `poc_ra_cl3b.py` gave 12 passed and 4 failed; all 4 are DEFECT tests
(R1 in-process, N13a, N13b, N12), now fixed. **None still reproduces.**

## Design attacks (step 2), other results

- **END identity:** no path signals a non-matching pid. A signal goes out only on an `_identity == "match"` or to a group with live members after the leader exited. A pgid with live members cannot be reused, so that is safe.
- **Worker resume:** a resumed worker steps once at once. `step()` is synchronous, so tab-flapping costs one step per show and causes no storm. No page relied on the old delay.
- **GUI-thread network:** none found. The assistant probe is removed. Tiles and the Remote Mode feed run on threads.
- **UI-only rule:** every non-UI change traces to a finding. That covers `iw … passive`, the 15 s Wi-Fi interval (H3), the arbiter refusal (H4), executor/END group kills (N20/N24), the rtl_power stderr pipe (drained by `_read_err`, H2), clearing aircraft when no source answers (E1), and the BLE/CAN/sensor/mesh/detector workers stopping after one honest standby (E4). The demo-only PROWL squelch default is not used live.
- **Top strip:** worst case is `hub.minimumSizeHint` = **1250 (dark) / 1257 (sun) ≤ 1270** on every page (DEMO, PROWL SC, PERMITTED, 10-char scope, 99+), the same as main.

## New findings

| # | Sev | Finding | Fix direction |
|---|---|---|---|
| **N26** | **HIGH** | HOME unset (live): `eventbus.frame_origin` latches the **first contact** as origin. The OPS PPI then draws every contact on its range rings with that aircraft dead centre, where the operator's own position should be. The ATLAS map draws them inside rings labelled 20/40/60 nm. `AtlasApp` builds the MapPanel and requests tiles for **(0.0, 0.0)** (`atlas.py:736-738`), so on device real aircraft sit over the Gulf of Guinea. Only the table and the sub-line are suppressed. This is a range picture from a guessed origin, which is what H5 forbids | With HOME unset, show the PPI and map as an OFFLINE empty state "HOME NOT SET" (or hide the rings, ring labels, basemap and centre marker, and say "relative positions only"). Never request tiles for a placeholder origin |
| N27 | MED | ENGAGEMENT trail over a **tampered** chain: `chain_states()` returns `[]` on a failed verify, and `render_actions` sets the green "WATCHING — nothing authorized yet" under the "NOT VERIFIED" caption (`panels.py:440-447`). The trail claims something it cannot know. Before CL4 the table was blank. The gate itself fails closed | When `info["verified"]` is False, use the STALE/OFFLINE look, e.g. "TRAIL UNREADABLE — chain failed verification" |
| N28 | MED | Active engagement whose chain cannot be opened (malformed head, N12): `_active_chain()` → None → `chain_info()` None. The panel then says "Evidence chain — none open" and OFFLINE "NO ENGAGEMENT", while the strip shows ENG ◆ active and the detail card shows the engagement. The gate is closed, which is correct | Separate "no engagement" from "engagement active, chain unreadable" (`engagement.chain_status()` returning the reason), and show the reason |
| N29 | MED | `bus.feeds()` counts **any** source that published anything in 2 min. With no sensor running, an acknowledged OVERWATCH "next pass" alert makes SITREP say "Watching OVERWATCH: no contacts, decodes, or open alerts." That is all-clear phrasing backed by a TLE prediction. SPEAK reads it aloud. ATLAS's RADIO BUSY alert does the same for ATLAS | Count only contact/decode publishers (non-telemetry) as feeds, or have each receiver publish an explicit heartbeat |
| N30 | LOW | Start/pause race: `_spawn` starts the Wi-Fi worker before `_sync_scan_pause` pauses it. A RECON started while hidden or on BLE ran one `iw scan passive` in **14 of 30** trials. The scan is passive | Pause before `start()` (pass `paused=True` to the worker) |
| N31 | LOW | An orphan that exits on its own between `_settle_tickets`' match and `_kill_orphans`' re-check is recorded `kill` "orphan at END" `verified_gone` although END sent **no signal**. The process is gone, so this never gives a false KILLED for a survivor | Have `_kill_orphans` return `(True, "exited")` when nothing was signalled and record `exit`-unknown, not `kill` |
| N32 | LOW (info) | N23 excludes pid/ppid/pgrp but not `getsid()` or other ancestors. A **keyed** forgery naming the session leader gets TERM+KILL to its group. The key is the boundary, the same as N23 | Optionally also refuse `os.getsid(0)` and the ancestor chain, or require `wpid` to be a known bound child |
| N33 | LOW | A torn partial last line (power loss before the line's fsync) still refuses the chain. It fails closed but stays bricked. This is outside N13, which covers a complete line plus a missing head | On an exclusive open, truncate a final line that does not parse when the head counts exactly the records before it, then record `recovered` |
| N34 | LOW | Sun mode, 1280: the ENGAGEMENT caption "NOT VERIFIED: chain …" is clipped at the panel edge (`stress_engagement_tampered_sun.png`) | Elide with a tooltip |
| — | LOW | E1 residual: an `aircraft.json` with no `now` (or a future `now`) is live forever (`sky_app.py:697`) | Fall back to the file mtime, and treat a `now` in the future as stale |

## Regression

- Full suite on **Python 3.12.3** (`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q tests`): **1476 passed, 3 failed, 6 skipped** in 667 s. The 3 failures are the known baseline set (`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::…iss_passes…`). `test_cl4_gates.py`, `test_cl4_honest.py`, `test_cl1_*`, `test_cl5_radio.py` and `test_palisade_qt.py` are all green inside that run.
- **Denial diff** `04a76ab..461f5e2 -- tests/`: three existing files changed.
  - `test_cl2_gates.py`: an allowlist key was renamed from `_run_cmd` to `_run_scan`. It is the same `subprocess.run` with the same justification.
  - `test_wifisurvey.py`: argv gained `passive` (H3).
  - `test_palisade_qt.py`: the event contract gained `demo` (H7). The assistant test moved from "offline" to "NOT IMPLEMENTED" (H18), and its alert assertion is now stricter ("1 unacknowledged"). The SITREP "All quiet" assertion is inverted to `not in` plus "No feed is running" (H17).
  - Every change is justified by a CL4 semantic change, and no negative assertion was weakened.
- pyflakes: the changed files and the PoCs are clean. The `test_palisade_qt.py` warnings are pre-existing (3 on main).
- Renders at 1280×720, live, dark + sun: OPS, SWEEP, PRISM, PROWL, ATLAS, OVERWATCH, RECON, FORGE, BENCH, SYSTEM (settings, assistant, sitrep, mesh) and ENGAGEMENT (`*_live_ra.png`, 28 files). Stress pass: `stress_*`, `strip_worst_*`. No table is blank.

## Stage → model
All stages ran on the session model (Opus 5.5). No subagents were used.
