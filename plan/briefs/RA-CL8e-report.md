# RA-CL8e — cold re-audit of CL8-fix4 (`fix/cl8-ship` @ 81b7528)

Auditor: a fresh session working adversarially. Base `origin/main` = `1bc8ad1`. Environment: Python 3.13, PySide6,
offscreen + xvfb, temp HOME. Live decoder PoCs use fake binaries on a PATH that holds only the fakes plus
`sh`/`cat`/`sleep`/`head`/`dd`/`yes`/`true`/`false`, `QT_QPA_PLATFORM=minimal`, and `radio_arbiter._make_lease`
stubbed to count leases. Every fake appends `"<name> <argv>"` to a marker file. The same scripts were run against a
`1bc8ad1` worktree to decide "present on main". No real radio, sudo, ufw, ip or installer was run. I read
`CL8-report.md` ("CL8-fix4") only at step 3.

**Verdict: DO NOT MERGE.** CL8-fix4 closes NEW-N (ATLAS) and NEW-O (SCAN restart) in full, and closes NEW-M for
AM banks. Two blocker-3 defects remain:
- **NEW-M is only partly fixed.** RA-CL8d's own PoC still reproduces exactly: default bank GMRS/FRS, rtl_fm
  `sleep 1.2; exit 1`. Result: 12 spawns in 12 s, the radio held, no fault, every channel shown quiet. The fix's
  test uses Airband (AM) for 1.2 s / 2.5 s and NOAA only for 0.8 s, so it does not pin the case that was reported.
  The author's stated limit for hardware-squelch banks is real for the current design, but it covers the default bank
  and every NFM bank. It is not inherent (see below).
- **NEW-T (new): BABEL SSTV.** When rtl_fm exits at once, SSTV respawns it every ~2 s for as long as RUN is on. The
  radio is held the whole time, there is no backoff and no fault, and the status flips between "capturing 0s"
  (live) and "retrying". This is the same pattern as NEW-G, which was blocking.

Both defects predate this branch and are present on `1bc8ad1`. That is the same standing NEW-G, NEW-H, NEW-M and
NEW-N had.

## Suite

`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q -p no:cacheprovider tests` (temp HOME):
**1617 passed, 7 skipped, 3 failed, 7 errors in 742 s**.
- Known baseline: `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`,
  and 7 × `test_shell` (no tkinter).
- The extra failure is `test_cl1_fix2::test_ack_all_never_acks_an_alert_that_arrived_after_the_drawer_was_viewed`.
  It is **flaky on main too**: run alone 3 times, it passes 3/3 on the branch and 1/3 on `1bc8ad1`. Fix4 touches
  no panel or shell code, so this is not a regression (Low, NEW-V).

`tests/test_cl8_ship.py` passes in full, including the 9 new `test_ra8d_*` tests. `pyflakes` shows the same count as
main on `atlas.py`, `prowl.py`, `scanner.py` (0) and `suite.py` (18).

Test diff: `git diff 88cd692..HEAD -- tests` adds 103 lines and removes 0. Against `1bc8ad1`, the deletions are the same
set that RA-CL8 to RA-CL8d accepted (callsign list without SWEEP, OPSEC slot, plugin tests, RID red drone, legacy
split). No assertion was weakened in this round.

## Step 1 — live PoCs at the branch head

### BABEL (recording fakes, default settings): unchanged since RA-CL8d, re-run

| Mode | argv | Result |
|---|---|---|
| POCSAG | `rtl_fm -f 152.007M -M fm -s 22050 -E dc -` → `multimon-ng -t raw -a POCSAG512 -a POCSAG1200 -a POCSAG2400 -a FLEX /dev/stdin` | LIVE, 1 lease, released on stop |
| AIS | `rtl_ais -n` | same |
| RDS | `rtl_fm -M fm -l 0 -A std -p 0 -s 171k -F 9 -f 100.3M` → `redsea -r 171000` | same |
| ACARS | `acarsdec --output json:file:path=- --rtlsdr 0 -g 40 131.550 …` | same |
| ACARS `source: vdl2` | `dumpvdl2 --rtlsdr 0 --gain 40 --output decoded:json:file:path=- 136650000 …` | same |
| TPMS | `rtl_433 -F json -M level -f 315M -f 433.92M -H 30` | same |
| **SSTV** | `rtl_fm -f 145.8000M -M fm -s 24000 -g 40 -E dc -` | **rtl_fm `exit 1`: 11 spawns in 20 s, lease held throughout, no fault (NEW-T)** |

Failure cases:
- multimon-ng, rtl_ais or rtl_433 exiting at once: `FAULT … exited after 0.0s (×n) — retry in 2s/4s`. The backoff is
  visible and the lease is kept by design (R2).
- rtl_fm missing: `FAULT — FAILED TO START`, the lease is released, no retry.
- L4 `pager.json` frequency `929.6M -M fm; id > /tmp/x #`: `SETTINGS REFUSED`, the lease is released, nothing spawned.
- Every `_open_pipe` call site still passes a list of argv lists, and the flat-argv guard is still in place.

### PROWL

| Sub-mode | Case | Result |
|---|---|---|
| SCAN Airband (AM, software gate) | rtl_fm `sleep 1.2; exit 1` | 3 spawns, `FAULT: SCAN rtl_fm exits at once (×3)` at 6.6 s, released. **Closed for AM** |
| SCAN GMRS/FRS (NFM, hw squelch) | rtl_fm `exit 1` | 3 spawns, FAULT at 3.0 s, released |
| **SCAN GMRS/FRS (default bank)** | **rtl_fm `sleep 1.2; exit 1`** (RA-CL8d's PoC) | **12 spawns in 12 s, owner `PROWL-SCAN` 100 % of samples, no status, fault or error, 0 hot rows.** Page level (`ProwlApp(demo=False)`): 8 spawns in 7 s, chip `22 CH`, busy line empty. **Still reproduces (NEW-M)** |
| SCAN NOAA Wx (NFM) | rtl_fm `sleep 1.2; exit 1` | same as GMRS: 12 spawns, held, silent |
| **SCAN Airband** | **rtl_fm hung (alive, never writes)** `exec sleep 1000` | **5 spawns in 15 s, held 100 %, silent, every channel quiet (NEW-S)** |
| SCAN Airband | rtl_fm streams 400 kB, then exits | 3 spawns, FAULT, released |
| SCAN page, after a FAULT | Enter (`primary_action`) | Restarts: 3 more spawns, then FAULT again, then 0 spawns in the next 4 s. **NEW-O closed.** The busy line and chip still read "SCAN OFF — stopped" over the fault; only the `fault` chip keeps it (Low remainder) |
| FM | recording | `rtl_fm -d 0 -M fm -f 97.3000M -s 171000 -A std -F 9 -g 40 -` → `redsea -r 171000 -u -e` → `aplay …`, "FM 97.3 ♪" |
| FM | rtl_fm `exit 1` | 3 spawns, FAULT, released |
| FM | aplay missing | FAULT "cannot start the decoder: … 'aplay'", released |
| NWR | recording | `rtl_fm -f 162.400M -M fm -s 22050 -E dc -` → `multimon-ng -t raw -a EAS /dev/stdin` |
| NWR | both `exit 1` | DOWN ×3, then FAULT with a 10 s and then 30 s hold-down. Correct |
| NWR | multimon-ng missing | "NWR STANDBY — no rtl_fm": wrong binary named (NEW-P b, a listed follow-up) |

### ATLAS / PRISM

| Path | Case | Result |
|---|---|---|
| APRS layer | normal | `rtl_fm -f 144.390M -M fm -s 22050 -E dc -` → `multimon-ng -t raw -a AFSK1200 -A /dev/stdin`, held |
| APRS layer | rtl_fm `exit 1` / multimon-ng `exit 1` / rtl_fm dies at 4 s | given back at 0.2 s / 0.2 s / 4.0 s, "FAULT — decoder exited", session-log fault, released. **Closed** |
| APRS layer | multimon-ng missing | "FAULT — cannot start: no multimon-ng", released, 0 spawns. **Closed** (the lease is taken and released once first: a one-off readsb pause, Low) |
| AIS layer | rtl_ais `exit 1` / missing | FAULT, released. **Closed** |
| ATLAS page (`AtlasApp(demo=False)`, STATION clicked) | rtl_fm `exit 1` | button unticks, owner None, chip `layer: APRS OFF — FAULT — decoder exited — is the SDR free?` |
| PRISM | rtl_power `exit 1` | `SDR FAULT — rtl_power exited (1)`, a fixed 5 s retry, held. Visible, accepted in RA-CL8d |

### Blockers 1 and 2, C1, L3 (re-run)

- Scout `wifi_scan('bash -c id>…')`: SETTINGS REFUSED, and no file is written.
- `signals.build_argv` refuses every one of these: `rtl_433 -F syslog:`, `-F mqtt://`, `-F http`, `-w`,
  `-d rtl_tcp:`, `-c /tmp/evil.conf`; acarsdec `--output …udp`, `-j`; dumpvdl2 `--output …zmq`, `--soapysdr
  driver=remote`; and `bash -c id`.
- C1: `make_app(token=None)` raises ValueError. `/`, `/api/status`, `/api/contacts` return 401 with no token or a
  wrong token and 200 with the right one. `//api/status` returns 401/401/404. `/health` returns 200.
- L3 OFFLINE: a public IP, a hostname, `file:` and `ftp:` all give NetBlocked.

### NEW-Q restore (CL8-fix4)

`_restores_tx_setting` (`suite.py:876-885`) **fails open**. It reads only the first 1 MiB (`f.read(1 << 20)`), and any
`ValueError` returns False, which means "restore it". PoC: an archive member `.config/uconsole-suite/replay.json` =
`{"tx_enabled": true, "tx_region": "EU", "tx_gain": 0` + 1 MiB of spaces + `}`.
- `restore_configs` restores it.
- `load_json` parses it.
- `txguard.tx_locked(d) == (False, '')`, `region_of(d) == 'EU'`.
- `classify(866e6) == 'ism'` and `classify(433.92e6) == 'ism'`.

That is exactly the RA-CL8d NEW-Q state. Arm and per-session unlock are still needed, so it still fails safe
(Medium, not blocking). A UTF-8-BOM file also passes the check, but `load_json` cannot parse it either, so it
ends up as `.corrupt` and is harmless.

### NEW-C restore, NEW-D, NEW-E, C4

Code unchanged since RA-CL8d apart from the NEW-Q check. Backup → restore round trip (temp HOME) restores these
byte-identical: `fm.json`, a nested settings subdir, `operator.json`, Sky settings, all three records files, the nested
logbook and both bingo files. **Not restored:** `net.json` (intended, NEW-J), and now also every settings file that has
*any* `tx_*` key, even `tx_enabled: false`. That means `mesh.json` (host/port/serial/LoRa region), `cw.json` (wpm,
freq), `rtty.json`, `digimodes.json`, `replay.json` and `bench.json` are all dropped from the operator's own backup,
silently. `skipped_tx` is collected and never returned or printed (`hub --restore` prints "Restored 15 files").
This is Low (NEW-R widened), and the CL8 report lists it as by design.

## Step 2 — regressions

- Demo decode: BABEL AIS/ACARS/POCSAG/RDS/TPMS/SSTV/CW/RTTY each emit 5 rows in 2.5 s. PROWL SCAN/FM/NWR emit rows.
  No lease is taken and nothing is spawned.
- Session log: the ATLAS fault reaches it (`sessionlog` level `fault`, source `ATLAS`). SCAN, FM and NWR faults reach
  the page `fault` chip. The MODE indicator and chrome code are unchanged since RA-CL8d.
- `scanner.py` is shared with the Tk scanner: it now posts `("status", …)` and sleeps 1 s on any rtl_fm self-exit.
  The Tk consumer handles `"status"` (`scanner.py:577`). This is a deliberate fix, not a drift.

## RA-CL8d findings

| RA-CL8d | Status | Evidence | Test |
|---|---|---|---|
| NEW-M SCAN rtl_fm dying after 1 s | **PARTIAL — BLOCKING** | `scanner.py:176-178` counts any self-exit, but on an NFM (hardware-squelch) bank `listen_channel` kills rtl_fm itself at `t0 + TUNE_SETTLE + dwell` = 1.0 s (`scanner.py:153`, `:207-208`), before a 1.2 s death. RA-CL8d's exact PoC (GMRS/FRS default, 1.2 s) still gives 12 spawns in 12 s, held, silent. Fixed for AM banks only | `test_ra8d_prowl_scan_rtl_fm_dying_after_tuning_is_a_fault_too` (Airband 1.2/2.5, NOAA **0.8** only. It does not pin the reported case) |
| NEW-N ATLAS dead/missing decoder | CLOSED | `atlas.py:475-480` (dead pipe → `_fault`), `:482-487` (open raises → `_fault`), `:316-318`, `:329` (missing binary raises), `:499-507`; the page unticks it (`:883-893`) | `test_ra8d_atlas_layer_with_a_dead_decoder_…` ×3, `test_ra8d_atlas_layer_with_a_missing_decoder_…` |
| NEW-O SCAN restart | CLOSED (Low remainder: the "SCAN OFF — stopped" text covers the FAULT on the busy line and chip) | `prowl.py:1225-1229`; page PoC above | `test_ra8d_prowl_enter_restarts_scan_after_a_fault` (monkeypatched `swap_worker`; my page-level PoC is real) |
| NEW-P Lows | OPEN (listed follow-ups) | FM >3 s loop, NWR label, BABEL text | — |
| NEW-Q restore tx_* | **PARTIAL (Medium)** | `suite.py:876-885`, `:912-914`. It fails open on a file over 1 MiB (PoC above) | `test_ra8d_restore_never_switches_transmit_on` (small files only) |
| NEW-R silent skip | OPEN (Low, listed; now wider, see above) | — | — |

## RA-CL8c / RA-CL8b / RA-CL8 findings

| Finding | Status | Test |
|---|---|---|
| RA-CL8c NEW-G (FM respawn loop), NEW-I (FM missing sink) | CLOSED (re-run) | `test_ra8c_prowl_fm_…` |
| RA-CL8c NEW-H (SCAN early exit) | Superseded by NEW-M (PARTIAL above) | `test_ra8c_prowl_scan_rtl_fm_exiting_at_once_…` |
| RA-CL8c NEW-J (restore net/headless) | CLOSED | `test_ra8c_restore_keeps_this_devices_…` |
| RA-CL8c NEW-K (flat argv) | PARTIAL (Low, listed: `kit.procs.Pipeline` accepts a flat argv; every call site is correct) | `test_ra8c_open_pipe_refuses_a_flat_argv` |
| RA-CL8c NEW-D remainder | CLOSED | `test_ra8c_scan_checks_dwell_hold_and_max_active` |
| RA-CL8 blockers 1 (Scout shell), 2 (template egress), 4 (harden fails open) | CLOSED (1 and 2 re-run above; harden code unchanged) | `test_ra_scout_wifi_cmd_…`, `test_ra_decoder_templates_…`, `test_ra_harden_…`, `test_ra8b_harden_…` |
| RA-CL8 blocker 3 / NEW-1 (malformed settings) | CLOSED for BABEL and the PROWL settings paths | `test_ra_malformed_setting_type_…`, `test_ra8b_prowl_scan_refuses_…` |
| RA-CL8b NEW-A, NEW-B, NEW-E | CLOSED | `test_ra8b_babel_*` |
| RA-CL8b NEW-C (restore scope) | CLOSED (see NEW-Q) | `test_ra8b_restore_writes_only_suite_settings` |
| NEW-5 proxy | CLOSED | `test_ra_offline_loopback_through_a_remote_proxy_…` |
| NEW-6 LAN DNS rebinding | OPEN (deferred, listed) | — |
| NEW-7 C4 seen-per-row | CLOSED | `test_ra8b_session_log_marks_only_rows_on_screen` |
| NEW-8 to NEW-12 | CLOSED | as RA-CL8b |

## Original IDs

| ID | Status | Evidence | Test |
|---|---|---|---|
| L4 | CLOSED for shell/argv. The radio-held consequence is closed in BABEL decoders, FM, NWR and ATLAS; **open in SCAN NFM banks (NEW-M) and in SSTV (NEW-T)** | PoCs above | `test_l4_*`, `test_ra_*`, `test_ra8b_*`, `test_ra8c_*`, `test_ra8d_*` |
| C1 | CLOSED | 401/200 matrix | `test_c1_*`, `test_headless` |
| L3 | PARTIAL (rebinding deferred) | OFFLINE NetBlocked | `test_l3_*`, `test_ra_offline_…` |
| L2 | CLOSED (unchanged) | — | `test_l2_*`, `test_ra_harden_…`, `test_ra8b_harden_…` |
| L6 | PARTIAL (documented: user-owned `$APP`) | unchanged | `test_l6_*` |
| S1 | CLOSED | unchanged | `test_s1_*` |
| S4 | CLOSED | unchanged | `test_s4_*`, `test_ra_doctor_…` |
| C4 | CLOSED (Low: CAP eviction, listed) | unchanged | `test_c4_*`, `test_ra8b_session_log_…` |
| C5 | PARTIAL (Low, listed: duplicate loaders) | unchanged | `test_c5_*` |
| P1, P2, P3, B5, E6 | CLOSED | unchanged | `test_p1_*`, `test_p2_*`, `test_p3_*`, `test_b5_*`, `test_e6_*` |
| B4 | CLOSED | unchanged | `test_b4_*`, `test_ra_prepended_…` |
| B6 | CLOSED | TPMS `-H 30` live | `test_b6_*`, `test_ra8b_babel_tpms_…` |
| v0.1 SWEEP hidden / Tk retired | CLOSED | unchanged | `test_v01_…`, `test_ra_tk_home_grid_…` |

## NEW findings (not in the 93 or RA-CL8 to RA-CL8d)

**NEW-T · High · BLOCKING (blocker 3, the NEW-G pattern). BABEL SSTV respawns rtl_fm on a held radio with no
backoff and no fault.** `SstvWorker.step` (`babel.py:878-881`): `if rec.err: self._stop_rec(); status("SSTV — … (retrying)");
return`. The next step (`interval_ms=1000`, `:773`) makes a new `sstv.Recorder`, which spawns rtl_fm again (`:864-869`),
and then emits `"SSTV — capturing 0s"` with `live: True` (`:883-884`). Nothing counts the exits. There is no `fault`
signal, no session-log entry and no lease release.
PoC (`SstvWorker(demo=False)`, `set_running(True)`, fake `rtl_fm` = `exit 1`, 20 s): **11 rtl_fm spawns, owner
`BABEL-SSTV` at the end, statuses alternate `capturing 0s` / `rtl_fm stopped - is the SDR free? (retrying)` every
second, no fault.** Present on `1bc8ad1` (6 spawns in 10 s, same alternation).
Fix: the same rule as FM/SCAN. Count exits within `EARLY_EXIT_S`, and after 3 in a row emit FAULT, give the lease back
and untick RUN. Never emit `live: True` for a recorder younger than the early-exit window. Pin it with an `exit 1` fake
and a `sleep 1.5; exit 1` fake.

**NEW-S · High · BLOCKING with NEW-M (blocker 3: radio held, false "all quiet").** If rtl_fm stays alive but never
writes a byte (a wedged dongle or USB transfer), SCAN treats every channel as quiet. On an AM / software-gate bank the
engine knows this happened: the `elif deadline is None and now - t0 > TUNE_SETTLE + 3.0: break  # software gate, but
rtl_fm never sent audio` branch (`scanner.py:209-210`) returns `False`, the same as a quiet channel, with no
`status` post. PoC: Airband, fake `rtl_fm` = `exec sleep 1000`, 15 s → 5 spawns, owner `PROWL-SCAN` 100 %, no fault,
0 hits. Present on `1bc8ad1` (4 spawns in 12 s, held). On NFM banks the same hang is the author's "limit" case.
Fix: on a software-gate bank, treat "rtl_fm never sent audio" as an early exit (post `status`). For NFM banks, see
the NEW-M note.

**NEW-M note: is the author's hardware-squelch limit real?** As the scanner is built today, yes. With `-l` power
squelch, rtl_fm writes nothing on a closed channel, and `listen_channel` kills it at 1.0 s, so a death or hang after
that looks exactly like a quiet channel. But it is a design choice, not a hardware limit:
- rtl_fm's stderr goes to `DEVNULL` (`scanner.py:142`). It reports the failures that matter (`usb_claim_interface
  error`, `Failed to submit transfer`, `Failed to open rtlsdr device`), and a stderr reader could flag them.
- rtl_fm can pad squelch gaps with zeros (`-E pad` in the osmocom build; check it on the device). That makes a live
  rtl_fm on a closed channel distinguishable from a dead or hung one.

The limit also applies to the **default bank** and every NFM bank (GMRS/FRS, MURS, NOAA, …). RA-CL8d's exact PoC is
therefore unfixed. By the standard applied to NEW-G, NEW-H, NEW-M and NEW-N, it still blocks. If the owner rules
that the NFM/hang residue belongs to a CL5 follow-up, NEW-M and NEW-S are not blocking, but NEW-T still is.

**NEW-U · Medium (fails safe). NEW-Q check fails open.** See the PoC above: a settings file over 1 MiB, or any
parse error, makes `_restores_tx_setting` return False, so the file is restored. Fix: fail closed (skip on any error
or size over the cap), or better, parse the restored file the way `load_json` does and drop `tx_*` keys rather than
whole files. That would also fix the NEW-R widening.
Main has no tx check at all (the RA-CL8d NEW-Q state).

**NEW-V · Low. A flaky test on main as well.** `test_cl1_fix2::test_ack_all_never_acks_an_alert_that_arrived_after_the_drawer_was_viewed`
fails 2 of 3 times alone on `1bc8ad1`, 0 of 3 on the branch, and failed once in this branch's full run.

**NEW-W · Low (out of CL8 scope, on main).** SCAN HOLD (`prowl.py:351-354`) keeps the lease but runs no rtl_fm, so a
held channel is silent. Noted only because Enter on a running SCAN takes this path.

## Blocking list (RA-CL8 standard, as applied in RA-CL8b, c and d)

1. Settings → shell: closed.
2. OFFLINE egress via templates: closed.
3. Radio held / retry / false status: BABEL decoders, FM, NWR and ATLAS are closed. **SCAN on NFM banks (including the
   default bank) still holds the radio silently when rtl_fm dies after 1.0 s or hangs (NEW-M PARTIAL, NEW-S). BABEL
   SSTV loops rtl_fm on a held radio with no backoff or fault (NEW-T).** All of these predate the branch.
4. harden fails open: closed.

### Reproduce

The scratch scripts (not committed) all import a `common.py`. It builds a temp HOME, a fakebin and a tools PATH, sets
`QT_QPA_PLATFORM=minimal`, stubs `ra._make_lease`, and pumps the Qt loop.
- `scan_run.py BANK SECS BODY`: e.g. `"GMRS/FRS" 12 "sleep 1.2; exit 1"` and `Airband 15 "exec sleep 1000"`.
- `sstv_run.py "exit 1" 20`.
- `atlas_run.py aprs 4 "rtl_fm=exit 1"`.
- `prowl_page.py "exit 1"` (NEW-O) and `prowl_page.py "sleep 1.2; exit 1"` (NEW-M at page level).
- `restore_poc.py` (NEW-U).

Set `WT=<main worktree>` to run the same scripts against `1bc8ad1`.

DO NOT MERGE
