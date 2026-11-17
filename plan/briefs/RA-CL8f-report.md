# RA-CL8f — cold re-audit of CL8-fix5 (`fix/cl8-ship` @ f8f542b)

Auditor: a fresh session, working adversarially. Base `origin/main` = `1bc8ad1`. Environment: Python 3.13, PySide6, offscreen + xvfb,
temp HOME. Live decoder PoCs use fake binaries in a fakebin. Each fake appends `"<name> <argv>"` to a marker file. PATH is the fakebin
plus `/usr/bin:/bin`, and no real SDR tool is installed. `QT_QPA_PLATFORM=minimal`, and `radio_arbiter._make_lease` is stubbed to record
leases. I ran the same scripts against a `1bc8ad1` worktree to decide "present on main". No real radio, sudo, ufw, ip or installer was run.
I read `CL8-report.md` ("CL8-fix5") only at step 3.

**Verdict: DO NOT MERGE.** CL8-fix5 closes three findings in full: NEW-T (SSTV exit loop), NEW-U (restore TX check) and the zero-byte
case of NEW-S. Every *exit* failure on every radio path is now caught, except one: an NFM-bank SCAN rtl_fm that dies after 1.0 s.
RA-CL8d's exact NEW-M PoC therefore still reproduces (12 spawns in 12 s, radio held, silent). The fix also leaves the *alive-but-silent*
(hung or stalled rtl_fm) class open on SCAN AM, SSTV, the BABEL decoders and ATLAS. NWR already detects a stall, so the class can be
detected. All of this is present on `1bc8ad1`. Under the blocker-3 standard used in RA-CL8 through RA-CL8e it still blocks. If the owner
accepts the author's CL5 follow-up (scan liveness and hang detection), nothing exit-based is left blocking. See "Owner ruling" below.

## Suite

`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q -p no:cacheprovider tests` (temp HOME):
**1621 passed, 7 skipped, 2 failed, 7 errors in 773 s**. The failures and errors are exactly the known baseline:
`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, and 7 × `test_shell` (no tkinter).
The flaky `test_cl1_fix2::test_ack_all_…` passed in this run. The 3 `test_ra8e_*` tests also pass on their own (22 s).

- `pyflakes`: `babel.py` 0, `scanner.py` 0, `suite.py` 18. Main gives the same counts.
- Test diff: `git diff 538601b..HEAD -- tests` adds 64 lines and removes **0**. Against `1bc8ad1`, the 12 deleted `assert` lines are the
  set RA-CL8 to RA-CL8e accepted (the callsign list without SWEEP, the OPSEC slot, plugins, the RID drone, legacy split). No denial or
  negative assertion was weakened.
- Fix5 touches only `palisade_qt/babel.py` (SSTV), `scanner.py` (one line) and `suite.py` (`_restores_tx_setting`).

## Step 1 — live PoCs at the branch head

### BABEL

| Mode | argv (recorded) | Failure cases |
|---|---|---|
| POCSAG | `rtl_fm -f 152.007M -M fm -s 22050 -E dc -` → `multimon-ng -t raw -a POCSAG512 -a POCSAG1200 -a POCSAG2400 -a FLEX /dev/stdin` | rtl_fm missing: `FAILED TO START`, released, 0 spawns. rtl_fm `exit 1` (multimon reading stdin): FAULT ×1/×2/×3, backoff 2/4/8 s (R2, lease kept). L4 `pager.json` freq `929.6M -M fm; id > /tmp/x #`: `SETTINGS REFUSED`, released, nothing spawned |
| AIS | `rtl_ais -n` | `exit 1`: FAULT with backoff |
| RDS | `rtl_fm -M fm -l 0 -A std -p 0 -s 171k -F 9 -f 100.3M` → `redsea -r 171000` | redsea missing: `STANDBY — no redsea`, no lease |
| ACARS | `acarsdec --output json:file:path=- --rtlsdr 0 -g 40 131.550 …` | — |
| ACARS (`signals.json` `source: vdl2`) | `dumpvdl2 --rtlsdr 0 --gain 40 --output decoded:json:file:path=- 136650000 …` | — |
| TPMS | `rtl_433 -F json -M level -f 315M -f 433.92M -H 30` | rtl_433 missing: `STANDBY`, no lease |
| **SSTV** | `rtl_fm -f 145.8000M -M fm -s 24000 -g 40 -E dc -` | see the table below |

SSTV (`SstvWorker(demo=False)`, RUN on):

| rtl_fm fake | Branch | `1bc8ad1` |
|---|---|---|
| `exit 1` | 3 spawns, FAULT `SSTV rtl_fm exits at once (×3)`, released, `run_off`, 0 `live` | 6 spawns in 10 s, held, live/retrying flip |
| `sleep 1.5; exit 1` | 3 spawns, FAULT, released (not pinned by a test) | — |
| page level (`BabelApp`, SSTV, RUN, `exit 1`) | RUN unticked, owner None, busy `SSTV OFF — FAULT — rtl_fm exits at once`, session-log `fault/BABEL` | — |
| `sleep 6; exit 1` | respawn every ~7 s forever, held 100 %, status `starting rtl_fm` ↔ `(retrying)`, no fault (visible, Medium) | same loop |
| `exec sleep 1000` (hung, 0 bytes) | `SSTV — starting rtl_fm` forever, held, `live` never true, no fault | `capturing Ns` with `live: True` |
| `head -c 4800 /dev/zero; exec sleep 1000` (stall after audio) | **`capturing 1s … 11s (lvl 0)` with `live: True`, held, no fault (NEW-Y)** | same |
| ENOEXEC binary | base-worker FAULT `Exec format error (×3, backing off to 2 s)`, **held indefinitely** (visible, Medium, NEW-AA) | same |

Every `_open_pipe` / `Pipeline` call site still passes a list of argv lists (`babel.py:165,216,252,289,356`, `atlas.py:321,332`,
`prism.py:85`, `prowl.py:73`). The flat-argv guard is still in place.

### PROWL

| Sub-mode | Case | Result |
|---|---|---|
| SCAN GMRS/FRS (default, NFM) | rtl_fm `exit 1` / `sleep 0.8; exit 1` | FAULT at 3.0 s / 5.4 s, released |
| **SCAN GMRS/FRS** | **rtl_fm `sleep 1.2; exit 1`** (RA-CL8d's PoC) | **12 spawns in 12 s, held 100 %, no status/fault/error, 0 hot rows. Same on `1bc8ad1`. NEW-M still reproduces** |
| SCAN NOAA Wx (NFM) | `sleep 1.2; exit 1` | same: 12 spawns, held, silent |
| SCAN GMRS/FRS | rtl_fm hung (`exec sleep 1000`) | 12 spawns, held, silent (the author's NFM limit) |
| SCAN Airband (AM) | hung, 0 bytes | 3 spawns, FAULT at 13.8 s, released. **Fixed (NEW-S zero-byte case)** |
| SCAN Airband | `sleep 1.2; exit 1` | FAULT at 6.6 s, released |
| **SCAN Airband** | **`head -c 4096 /dev/zero; exec sleep 1000`** (audio, then stall) | **37 spawns in 15 s, held 100 %, no fault, every channel quiet (NEW-X). Same on `1bc8ad1`** |
| FM | recording | `rtl_fm -d 0 -M fm -f 97.3000M -s 171000 -A std -F 9 -g 40 -` → `redsea -r 171000 -u -e` → `aplay -q -r 171000 -f S16_LE -t raw -c 1`, "FM 97.3 ♪" |
| FM | rtl_fm `exit 1` / aplay missing | FAULT ×3 / `cannot start the decoder: … 'aplay'`, released |
| FM | `sleep 4; exit 1` | respawn loop, "FM 97.3 ♪" (NEW-P, listed follow-up) |
| NWR | recording | `rtl_fm -f 162.400M -M fm -s 22050 -E dc -` → `multimon-ng -t raw -a EAS /dev/stdin` |
| NWR | both `exit 1` / multimon `exit 1` | DOWN ×3, then FAULT with a 10 s and then 30 s hold-down |
| NWR | rtl_fm hung | `no audio reaching the decoder (Ns)`, then STALLED, then FAULT `no audio, ×3 in 60s`. **The only path with a stall watchdog** (`prowl.py:600-648`, `:738`) |
| NWR | multimon-ng missing | `NWR STANDBY — no rtl_fm`: the wrong binary is named (NEW-P b, listed) |

### ATLAS / PRISM

| Path | Case | Result |
|---|---|---|
| APRS layer | normal | `rtl_fm -f 144.390M -M fm -s 22050 -E dc -` → `multimon-ng -t raw -a AFSK1200 -A /dev/stdin` |
| APRS | rtl_fm `exit 1` / `sleep 4; exit 1` / multimon-ng missing | given back at 0.1 s / 4.0 s / 0.0 s with `FAULT — …`, released |
| AIS layer | rtl_ais `exit 1` / missing | FAULT, released |
| APRS | rtl_fm hung | held 15 s, no fault (hang class, NEW-Z). Same on `1bc8ad1` |
| PRISM | rtl_power exit | fixed 5 s retry, visible (accepted in RA-CL8d). Code unchanged |

### Blockers 1 and 2, C1, L3 (re-run; the code is unchanged since RA-CL8e)

- Scout `wifi_scan("bash -c id>/tmp/ra8f_x")`: `SETTINGS REFUSED`, and no file is created.
- `signals.build_argv` refuses all 18 templates I tried, including new variants: `-F json:/tmp/out.json`, `-F csv:…`, `-F influx://`,
  `-W file`, `-r /etc/shadow`, `-E quit`, `-Fhttp`, acarsdec `--output json:file:path=/tmp/x`, dumpvdl2 `--output …file:path=~/.bashrc`,
  `--iq-file`, `--statsd`.
- C1: `make_app(token=None)` raises ValueError. `/`, `/api/status`, `/api/contacts`, `//api/status` return 401 and `/health` returns 200.
  A correct Bearer token returns 200.
- L3: the mode is OFFLINE. A public IP, a hostname, `file:` and `ftp:` all give NetBlocked (proxy env unset).

### Restore (NEW-C, NEW-J, NEW-Q, NEW-U)

The backup → restore round trip (temp HOME) restores these byte-identical: `fm.json`, a nested settings subdir, `operator.json`, Sky
`settings.json`, all three records files, both logbook files and both bingo files. These are not restored: `net.json` (intended), `mesh.json`
(it has `tx_enabled: false`; NEW-R, listed) and **`scanner.json` whose custom channel label is `ATX_TOWER` (NEW-AB, below)**.

NEW-U bypass attempts against `replay.json`:

| Member | Restored? | Result |
|---|---|---|
| 2 MiB padded `{"tx_enabled": true …}` | no | — |
| `{"TX_ENABLED": true}` | no | — |
| `{"tx_enabled": true, "tx_region": "EU"}` | no | caught by the parsed-key check |
| UTF-8 BOM + escaped key | yes | `load_json` → None: becomes `.corrupt`, harmless |
| UTF-16 | yes | `load_json` → None: becomes `.corrupt`, harmless |

No settings reader parses bytes with encoding auto-detection (grep). **NEW-U closed.**

## Step 2 — regressions

- Demo decode: AIS/ACARS/POCSAG/RDS/TPMS/CW/RTTY emit 4 rows in 2 s each, and SSTV emits its frame. PROWL SCAN/FM/NWR emit rows.
  0 spawns and 0 leases.
- Session log: the SSTV fault reaches it (`fault/BABEL`, page PoC above). The ATLAS fault path is unchanged. The MODE indicator, chrome
  and session-log code are untouched by fix5.
- `scanner.py` is shared with the Tk scanner. The new AM "never sent audio" branch posts `("status", …)` and sleeps 1 s. The Tk consumer
  handles `status`, so this is not a drift.

## Per-finding table

### RA-CL8e findings

| ID | Status | Evidence | Test |
|---|---|---|---|
| NEW-T SSTV exit loop | **CLOSED** | `babel.py:870` (t0), `:882-897` (3 quick exits → FAULT, `_give_back`, `run_off`), `:901-904` (not live before audio). Worker and page PoCs above. The `>5 s` slow loop remains (visible, Medium) | `test_ra8e_babel_sstv_rtl_fm_exiting_at_once_is_a_fault_and_gives_the_radio_back` (pins `exit 1` only; `sleep 1.5; exit 1` works but is not pinned) |
| NEW-S AM, rtl_fm alive but silent | **PARTIAL** | `scanner.py:209-211` fires only while `deadline is None`, i.e. before the first byte. After any audio, `:183-185` sets `deadline = now + dwell` and a stall reads as quiet. PoC NEW-X: 37 spawns in 15 s, held, silent | `test_ra8e_scan_am_rtl_fm_alive_but_silent_is_a_fault` (zero bytes only) |
| NEW-S NFM part / NEW-M remainder | **OPEN — author's design limit** (see "Owner ruling") | GMRS/FRS and NOAA `sleep 1.2; exit 1` and hung: 12 spawns, held, silent | `test_ra8d_prowl_scan_rtl_fm_dying_after_tuning_is_a_fault_too` (AM + NOAA 0.8 s only) |
| NEW-U restore TX check fails open | **CLOSED** | `suite.py:876-891`: reads the whole member, any `tx_` bytes → skip, `OSError` → skip, parsed `tx_*` key → skip | `test_ra8e_restore_tx_check_cannot_be_padded_past` |
| NEW-V flaky test | OPEN (Low, on main) | passed in this run | — |
| NEW-W SCAN HOLD silent | OPEN (Low, listed) | unchanged | — |

### RA-CL8d / RA-CL8c / RA-CL8b / RA-CL8 findings

| ID | Status | Test |
|---|---|---|
| RA-CL8d NEW-M | PARTIAL: fixed for AM and for instant exits on NFM, **open for NFM death after 1.0 s** | `test_ra8d_prowl_scan_rtl_fm_dying_after_tuning_is_a_fault_too` |
| RA-CL8d NEW-N (ATLAS dead/missing) | CLOSED (re-run) | `test_ra8d_atlas_layer_with_a_dead_decoder_…`, `…_missing_decoder_…` |
| RA-CL8d NEW-O (SCAN restart) | CLOSED (code unchanged) | `test_ra8d_prowl_enter_restarts_scan_after_a_fault` |
| RA-CL8d NEW-P | OPEN (Low, listed: FM >3 s loop, NWR label) | — |
| RA-CL8d NEW-Q | CLOSED (with NEW-U) | `test_ra8d_restore_never_switches_transmit_on`, `test_ra8e_restore_…` |
| RA-CL8d NEW-R | OPEN (Low, listed; see NEW-AB) | — |
| RA-CL8c NEW-G, NEW-I (FM) | CLOSED (re-run) | `test_ra8c_prowl_fm_…` |
| RA-CL8c NEW-H | superseded by NEW-M | `test_ra8c_prowl_scan_rtl_fm_exiting_at_once_…` |
| RA-CL8c NEW-J | CLOSED (`net.json` not restored) | `test_ra8c_restore_keeps_this_devices_…` |
| RA-CL8c NEW-K | PARTIAL (Low, listed; every call site correct) | `test_ra8c_open_pipe_refuses_a_flat_argv` |
| RA-CL8c NEW-D remainder | CLOSED | `test_ra8c_scan_checks_dwell_hold_and_max_active` |
| RA-CL8b NEW-A, B, E | CLOSED (argv table) | `test_ra8b_babel_*` |
| RA-CL8b NEW-C | CLOSED | `test_ra8b_restore_writes_only_suite_settings` |
| RA-CL8 blockers 1, 2, 4 | CLOSED | `test_ra_scout_wifi_cmd_…`, `test_ra_decoder_templates_…`, `test_ra_harden_…`, `test_ra8b_harden_…` |
| RA-CL8 blocker 3 / NEW-1 | CLOSED for settings. The liveness remainder is above | `test_ra_malformed_setting_type_…`, `test_ra8b_prowl_scan_refuses_…` |
| NEW-5 proxy | CLOSED | `test_ra_offline_loopback_through_a_remote_proxy_…` |
| NEW-6 LAN DNS rebinding | OPEN (deferred, listed) | — |
| NEW-7 C4 seen-per-row | CLOSED (code unchanged) | `test_ra8b_session_log_marks_only_rows_on_screen` |
| NEW-8 … NEW-12 | CLOSED | as RA-CL8b |

### Original IDs

| ID | Status | Evidence | Test |
|---|---|---|---|
| L4 | CLOSED for shell/argv. The radio-held consequence is closed for every exit path except NFM SCAN after 1.0 s. The hang class is open (NEW-X/Y/Z) | PoCs above | `test_l4_*`, `test_ra_*`, `test_ra8b…8e_*` |
| C1 | CLOSED | 401/200 matrix | `test_c1_*`, `test_headless` |
| L3 | PARTIAL (rebinding deferred) | NetBlocked | `test_l3_*`, `test_ra_offline_…` |
| L2 | CLOSED (unchanged) | — | `test_l2_*`, `test_ra_harden_…`, `test_ra8b_harden_…` |
| L6 | PARTIAL (documented: user-owned `$APP`) | unchanged | `test_l6_*` |
| S1 | CLOSED | unchanged | `test_s1_*` |
| S4 | CLOSED | unchanged | `test_s4_*`, `test_ra_doctor_…` |
| C4 | CLOSED (Low: CAP eviction, listed) | unchanged | `test_c4_*`, `test_ra8b_session_log_…` |
| C5 | PARTIAL (Low, listed: duplicate loaders) | unchanged | `test_c5_*` |
| P1, P2, P3, B5, E6 | CLOSED | unchanged | `test_p1_*`, `test_p2_*`, `test_p3_*`, `test_b5_*`, `test_e6_*` |
| B4 | CLOSED | unchanged | `test_b4_*`, `test_ra_prepended_…` |
| B6 | CLOSED | TPMS `-H 30` live | `test_b6_*`, `test_ra8b_babel_tpms_…` |
| v0.1 (SWEEP hidden, Tk gated tools retired) | CLOSED | unchanged | `test_v01_…`, `test_ra_tk_home_grid_…` |

## NEW findings (not in the 93 or RA-CL8 to RA-CL8e)

**NEW-X · High · blocker 3 under the RA standard (remainder of NEW-S). SCAN AM bank: a stall after the first audio reads as a quiet band.**
`listen_channel` sets `deadline = now + dwell` on the first chunk (`scanner.py:183-185`). Fix5's "silent rtl_fm" branch (`:209-211`)
fires only while `deadline is None`. An rtl_fm that sends a buffer and then stalls is killed at the dwell and reported quiet.
PoC: Airband, fake `rtl_fm` = `head -c 4096 /dev/zero; exec sleep 1000`, 15 s → **37 spawns, owner `PROWL-SCAN` 100 %, no status, fault
or error, 0 hot rows**. Same on `1bc8ad1`.
AM with `-l 0` streams without a break (12 kS/s), so this is *not* the NFM design limit. Fix: on a software-gate bank, treat "no bytes for
more than ~1 s after the first audio" as an early exit. Pin it with this fake.

**NEW-Y · High · blocker 3 under the RA standard (false live, radio held). SSTV: a stall after the first audio shows "capturing" live forever.**
`babel.py:901` checks only `total_samples() <= 0`. Once any audio has arrived, every step emits `capturing Ns (lvl …)` with `live: True`
(`:905-906`) even when the sample count has stopped growing. The level is frozen at its last value.
PoC: fake `rtl_fm` = `head -c 4800 /dev/zero; exec sleep 1000`, 15 s → **14 × `live: True`, `capturing 1s … 11s`, held, no fault**.
Same on `1bc8ad1`, where even a zero-byte hang showed live. Fix: track `total_samples()` between steps. No growth for more than ~3 s
should count as a dead rtl_fm, through the same 3-strike FAULT path.

**NEW-Z · Medium (radio held, status not false-clear but no fault). The hang class elsewhere.**
- BABEL decoders: a hung rtl_fm stage (POCSAG, multimon-ng reading stdin) shows `POCSAG LIVE` indefinitely and the lease is held.
- ATLAS APRS layer: a hung rtl_fm is held 15 s+ with no `given_back`.

Both are present on `1bc8ad1`. NWR alone has a watchdog (the `/proc/<pid>/io` byte counter, `prowl.py:600-648`), which shows a generic
fix is possible: a kit-level byte-counter watchdog on the first stage.

**NEW-AA · Medium (fails visible). SSTV holds the radio indefinitely when rtl_fm cannot be executed.**
For an ENOEXEC or EACCES binary, `sstv.Recorder` raises `OSError` from `step()`. The base worker reports `FAULT … (×3, backing off to 2 s)`
and keeps the lease forever. `DecoderWorker` instead releases on any start exception (`babel.py` "failed to start" branch). Same on
`1bc8ad1`. A related item: a slow death (`sleep 6; exit 1`) loops SSTV every ~7 s and BABEL RDS every ~6 s (the latter with `RDS LIVE`
and no fault, `babel.py:649`). This is the NEW-P class, also on main.

**NEW-AB · Low (fails safe; branch only). The restore TX check matches `tx_` anywhere in a file, not only in keys.**
`suite.py:885` (`b"tx_" in raw.lower()`). A `scanner.json` whose custom channel is labelled `ATX_TOWER` is silently not restored (PoC
above). Any free text containing `tx_` (labels, notes, channel names) drops the whole file. With NEW-R, nothing is printed. Main restores
it, because main has no check. Fix: drop the byte scan, parse as `load_json` does, and strip `tx_*` keys rather than skipping files.

**Test gaps (Low).** The NEW-T test pins only `exit 1`, not the `sleep 1.5; exit 1` case that RA-CL8e asked for (it does work). The NEW-S test
pins only the zero-byte hang.

## Owner ruling: is the NFM-scan limit real?

**I agree it is a limit of the current scan design, not of the hardware.**
- With `-l` power squelch, rtl_fm writes nothing on a closed channel, and `listen_channel` kills it itself at `t0 + TUNE_SETTLE + dwell`
  = 1.0 s (`scanner.py:153`). A death or hang after that is indistinguishable from a quiet channel.
- The common real failures are caught within ~3-5 s on NFM banks, because the next spawn exits at once: dongle busy
  (`usb_claim_interface`), unplugged, or failing to open. I verified `exit 1` → FAULT at 3.0 s and `sleep 0.8; exit 1` → FAULT at 5.4 s on
  GMRS/FRS.
- What remains is a dongle that opens and tunes and then dies or wedges on *every* spawn: undervoltage or a flaky USB link. That is rarer
  but real on a handheld.
- It is fixable without hardware changes: read rtl_fm's stderr (it prints `Failed to submit transfer` / `rtlsdr_demod_write` errors and
  "Tuned to" on a good open), or run rtl_fm with zero-padding (`-E pad`, check the device build) so a live rtl_fm always streams and
  silence means dead. That changes the scan engine (CL5 scope), so deferring it is reasonable *if the owner accepts it*.

**Does any other radio path still hold the radio on a dead, missing or silent decoder without a fault?**

| Case | Paths |
|---|---|
| Dead (exits at once) | No path. All of them fault and release, or back off visibly (BABEL R2, NWR, PRISM) |
| Dead (exits later) | NFM SCAN (silent). SSTV, BABEL and FM loop on a slow death, visibly or with a LIVE label (NEW-AA / NEW-P) |
| Missing | No path. All give FAILED TO START or STANDBY. NWR names the wrong binary (Low) |
| Silent / hung | **Yes: SCAN NFM (limit), SCAN AM after the first audio (NEW-X), SSTV after the first audio (NEW-Y, shows live), BABEL decoders (LIVE), ATLAS layers (NEW-Z)**. Only NWR detects it |

All of these are present on `1bc8ad1`. NEW-X and NEW-Y are not covered by the author's NFM argument: AM and SSTV `rtl_fm` stream
without a break, so silence is unambiguous there.

## Blocking list (RA-CL8 standard)

1. Settings → shell: closed.
2. OFFLINE egress via templates: closed (18 variants re-tried).
3. Radio held / retry / false status:
   - Closed for every exit path, except NFM SCAN after 1.0 s (NEW-M, author's limit).
   - Open for the stall class where the stream is unambiguous: **NEW-X (SCAN AM)** and **NEW-Y (SSTV, false live)**.
   - All predate the branch.
4. harden fails open: closed.

If the owner rules that NFM liveness *and* the hang/stall class (NEW-M remainder, NEW-X, NEW-Y, NEW-Z) are a CL5 follow-up, nothing
blocking remains and this branch is MERGE-able. Without that ruling, by the standard applied to NEW-G/H/M/N/T: **DO NOT MERGE.**

### Reproduce

The scratch scripts are not committed. Each imports a `common.py` that does the following: makes a temp HOME and a fakebin, sets PATH to
the fakebin plus `/usr/bin:/bin` and `QT_QPA_PLATFORM=minimal`, stubs `ra._make_lease`, and pumps Qt.
- `scan_run.py BANK SECS BODY`, e.g. `Airband 15 "head -c 4096 /dev/zero; exec sleep 1000"` (NEW-X) and `"GMRS/FRS" 12 "sleep 1.2; exit 1"`
  (NEW-M).
- `sstv_run.py BODY SECS`, e.g. `"head -c 4800 /dev/zero; exec sleep 1000" 15` (NEW-Y), `"exit 1" 20`, `ENOEXEC 20`.
- `babel_run.py MODE SECS name=body…`, `prowl_run.py FM|NWR SECS name=body…`, `atlas_run.py aprs|ais SECS name=body…`.
- `babel_page.py` (SSTV page fault), `restore_poc.py` (round trip + NEW-U bypasses + NEW-AB).

Set `WT=<main worktree>` to run the same scripts against `1bc8ad1`.

DO NOT MERGE
