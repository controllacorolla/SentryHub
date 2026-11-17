# RA-CL8d — cold re-audit of CL8-fix3 (`fix/cl8-ship` @ 063efe8)

Auditor: a fresh session working adversarially. Base `origin/main` = `1bc8ad1`. Environment: Python 3.13, PySide6,
offscreen + xvfb, temp HOME. Live decoder PoCs use fake binaries on a PATH that holds only the fakes plus
`sh`/`cat`/`sleep`/`echo`/`true`/`false`/`head`, `QT_QPA_PLATFORM=minimal`, and `radio_arbiter._make_lease` stubbed to
count leases. Every fake appends `"<name> <argv>"` to a marker file. No real radio, sudo, ufw, ip or installer was run.
I read `CL8-report.md` ("CL8-fix3") only at step 3.

**Verdict: DO NOT MERGE.** Each RA-CL8c case that CL8-fix3 claims to close passes when the decoder exits *at
once*: FM and SCAN now raise a FAULT, give the radio back and stop. The brief also asked whether any other
PROWL/BABEL/ATLAS/PRISM path still holds the radio silently. Two do, and both are blocker 3 (radio held,
retry, false status):
- **NEW-M (PROWL SCAN).** When rtl_fm dies 1.0 s or more after it starts, the NEW-H symptom comes back in full:
  about one spawn per second on a held radio, no fault, and every channel shown quiet. SCAN still relies on
  the engine's 1.0 s window, while the branch's own constant says a decoder that dies within 3 s
  "did not really run" (FM 3 s, BABEL 5 s).
- **NEW-N (ATLAS APRS/AIS layer).** If the decoder dies at once or `multimon-ng` is missing, the layer keeps
  the radio for good. readsb stays paused, the layer shows "APRS —", and no fault is raised.

Both defects predate this branch and behave the same on `1bc8ad1`. That is the same standing NEW-G/NEW-H had
in RA-CL8c.

## Suite

`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q -p no:cacheprovider tests` (temp HOME):
**1609 passed, 7 skipped, 2 failed, 7 errors in 707 s**. Every failure and error is on the known baseline list:
`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, and 7 × `test_shell`
(no tkinter). `tests/test_cl8_ship.py` passes in full, including the 7 new `test_ra8c_*` tests. `pyflakes` reports
nothing new on `prowl.py`, `babel.py` or `suite.py` (18 warnings in `suite.py`, the same as main).

Test diff: `git diff c40ef8f..HEAD -- tests` adds 135 lines and removes 0. Against `1bc8ad1`, the deletions are
the same set that RA-CL8, b and c already accepted as justified. No assertion was weakened in this round.

## Step 1 — live PoCs at the branch head

### BABEL (recording fakes, default settings)

| Mode | argv | Result |
|---|---|---|
| POCSAG | `rtl_fm -f 152.007M -M fm -s 22050 -E dc -` → `multimon-ng -t raw -a POCSAG512 -a POCSAG1200 -a POCSAG2400 -a FLEX /dev/stdin` | LIVE, 1 lease, released on stop |
| AIS | `rtl_ais -n` | same |
| RDS | `rtl_fm -M fm -l 0 -A std -p 0 -s 171k -F 9 -f 100.3M` → `redsea -r 171000` | same |
| ACARS (default) | `acarsdec --output json:file:path=- --rtlsdr 0 -g 40 131.550 …` | same |
| ACARS `source: vdl2` | `dumpvdl2 --rtlsdr 0 --gain 40 --output decoded:json:file:path=- 136650000 …` | same |
| TPMS | `rtl_433 -F json -M level -f 315M -f 433.92M -H 30` | same |

Failure cases:
- Decoder exits at once (POCSAG multimon, AIS, TPMS, ACARS, RDS rtl_fm): `FAULT … exited after 0.0s (×n) — retry
  in 2s/4s/8s`. The backoff is visible and bounded, and the lease is held during it (R2 design).
- rtl_fm missing (POCSAG), or dumpvdl2 missing with `source: vdl2`: `FAULT — FAILED TO START`, the lease is
  released, and no retry follows.
- L4 `pager.json` `929.6M -M fm; id > /tmp/x #`, `acars_freqs: 5`, `tpms freqs: 5`: `SETTINGS REFUSED`, the lease
  is released, and nothing is spawned.

Every `_open_pipe` call site passes a list of argv lists (`babel.py:165, 216, 252, 289, 356`). `_open_pipe` now
raises `TypeError` on a flat argv (`babel.py:53-55`).

### PROWL

| Sub-mode | Case | Result |
|---|---|---|
| SCAN | recording rtl_fm | `rtl_fm -f 162.4000M -M fm -s 12000 -g 40 -l 50 -`, the channels step, the lease is released on stop |
| SCAN | rtl_fm `exit 1` | 3 spawns, then `FAULT: SCAN rtl_fm exits at once (×3)` at 3.3 s and the radio is released. **Closed** |
| SCAN | **rtl_fm `sleep 1.2; exit 1`** | **12 spawns in 12 s. The lease is held the whole time. No status, fault or error. Page chip "22 CH", busy line empty** (NEW-M) |
| SCAN | `dwell: "x"` | SCAN FAULT — SETTINGS REFUSED, no lease. **Closed** |
| FM | rtl_fm + redsea + aplay recording | `rtl_fm -d 0 -M fm -f 97.3000M -s 171000 -A std -F 9 -g 40 -` → `redsea -r 171000 -u -e` → aplay; "FM 97.3" then "♪" after 1 s |
| FM | rtl_fm / redsea / aplay `exit 1` | 3 spawns, `FM FAULT — decoder exits at once (×3)` at 1.8 s, radio released, no respawn for the next 4.5 s, never ♪. **Closed** |
| FM | no aplay/pacat | `FM FAULT — cannot start the decoder: … 'aplay'`, the lease is released at once. **Closed** |
| FM | rtl_fm `sleep 3.5; exit 1` | A respawn every 3.5 s for as long as it runs, ♪ for about 2.5 s of each cycle, no fault (Low, NEW-P) |
| NWR | recording | `rtl_fm -f 162.400M -M fm -s 22050 -E dc -` → `multimon-ng -t raw -a EAS /dev/stdin`, "waiting for audio" |
| NWR | both `exit 1` | DOWN ×3, then `NWR FAULT … retry in 10s`, then `… retry in 30s`. Visible hold-down. Correct |
| NWR | multimon-ng missing | "NWR STANDBY — no rtl_fm" (wrong binary named, no lease; Low, NEW-P) |

### ATLAS / PRISM (other paths on a held radio)

| Path | Case | Result |
|---|---|---|
| ATLAS APRS layer | rtl_fm + multimon-ng `exit 1` | 1 spawn. **Lease held until the layer is turned off**: owner `ATLAS-APRS` at 5 s, no fault, no status (NEW-N) |
| ATLAS APRS layer | multimon-ng missing | **Lease held, nothing spawned, no fault** (NEW-N) |
| ATLAS AIS layer | rtl_ais `exit 1` | **Lease held, no fault** (NEW-N) |
| PRISM | rtl_power dies | `SDR FAULT — rtl_power exited …`, retried every 5 s (`prism.py:259-271`). Visible, so not blocking |

The same NEW-M and NEW-N runs against a `1bc8ad1` worktree give the same results (SCAN 1.2 s: 10 spawns in 10 s, silent;
APRS: lease held). Neither is a regression.

### NEW-C restore, NEW-D, NEW-E, C4

- NEW-C / NEW-J: `net.json` and `headless.json` are skipped by exact path after `normpath` (`suite.py:897-898`).
  These spellings are all caught: `./net.json`, `//`, `./.config/…`, `x/../net.json`, and `headless.json/`. A bad
  member is skipped and the rest restores (`suite.py:903-909`). Remainder: see NEW-Q.
- NEW-D: `dwell`/`hold`/`max_active` checked (`prowl.py:316`). A pre-existing `scanner.json` without those keys still
  works, because `_load_scanner_settings` merges the defaults (`prowl.py:866-867`).
- NEW-E: ACARS never runs rtl_433, whether `source` is unset, `sensors` or `acars`.
- C4: `panels.py` and `sessionlog.py` have not changed since RA-CL8c verified seen-per-row, and
  `test_ra8b_session_log_marks_only_rows_on_screen` passes.
- Re-run blockers 1 and 2: Scout `bash -c id` gives SettingsRefused. `rtl_433 -F syslog:…`, `-w x.cu8`, acarsdec
  `--output …udp`, dumpvdl2 `--output …udp` and `bash -c id` in the templates all give SettingsRefused. C1: `/`,
  `/api/status`, `/api/contacts` and `//api/status` return 401 with no token or a wrong token, 200 with the right one,
  and `/health` returns 200. `make_app(token=None)` raises ValueError. L3 OFFLINE: public IP and `file:` give NetBlocked.

## Step 2 — regressions

- Demo decode: BABEL AIS/ACARS/POCSAG/RDS/TPMS/CW/RTTY and PROWL SCAN/FM/NWR all emit rows. No lease is taken.
- Backup → restore round trip (temp HOME): settings (including a nested subdir), Sky settings, all three records
  files, a nested logbook, and both bingo files are restored byte-identical. `net.json` and `headless.json` are now
  **not** restored from the operator's own backup. This is intended (NEW-J), but restore does not say what it skipped
  (Low, NEW-R).
- Session log + MODE: a SCAN/FM stall puts the FAULT in the session log and on the page `fault` chip.

## RA-CL8c findings

| RA-CL8c | Status | Evidence | Test |
|---|---|---|---|
| NEW-G FM respawn loop | CLOSED | `prowl.py:493-500` counts exits within 3 s, and 3 in a row go to `_stall` (`:187-197`). ♪ shows only for a pipeline up ≥ 1 s (`:508`). PoC above: 3 spawns, FAULT, released | `test_ra8c_prowl_fm_decoder_that_exits_at_once_…[rtl_fm/redsea]` |
| NEW-H SCAN early exit | **PARTIAL → NEW-M** | `"status"` is now handled (`prowl.py:411-413`), and 3 in a row → `_stall` (`:375-380`). Fixed for an exit under 1.0 s only, because detection is the engine's `early_exit = not got and now - t0 < 1.0` (`scanner.py:176`). At 1.2 s, the loop is silent and the radio is held | `test_ra8c_prowl_scan_rtl_fm_exiting_at_once_…` (instant `exit 1` only) |
| NEW-I FM missing sink | CLOSED | `prowl.py:523-527`. The started rtl_fm is stopped by `fm.Pipe.__init__` (`fm.py:79-83`) | `test_ra8c_prowl_fm_missing_audio_sink_…` (monkeypatched Pipe; my PoC used a real missing aplay) |
| NEW-J restore net/headless | CLOSED (Medium remainder NEW-Q) | `suite.py:897-898`, `:903-909` | `test_ra8c_restore_keeps_this_devices_…` |
| NEW-K flat argv | PARTIAL (Low) | Guarded in `babel._open_pipe` only. `kit.procs.Pipeline`, which ATLAS/PRISM/NWR call directly, still turns a flat argv into one stage per string. Every current call site is correct | `test_ra8c_open_pipe_refuses_a_flat_argv` |
| NEW-L Lows | OPEN (listed follow-ups) | unchanged | — |
| NEW-D remainder | CLOSED | `prowl.py:316` | `test_ra8c_scan_checks_dwell_hold_and_max_active` |

## RA-CL8 / RA-CL8b findings (code unchanged since RA-CL8c except `babel.py`, `prowl.py` and `suite.py`)

| Finding | Status | Test |
|---|---|---|
| RA-CL8 blockers 1 (Scout shell), 2 (template egress), 4 (harden fails open) | CLOSED (PoCs 1 and 2 re-run; harden through the stubbed-PATH tests) | `test_ra_scout_wifi_cmd_…`, `test_ra_decoder_templates_…`, `test_ra_harden_…`, `test_ra8b_harden_…` |
| RA-CL8 blocker 3 / NEW-1 (malformed setting holds the radio) | CLOSED for BABEL and the PROWL settings paths | `test_ra_malformed_setting_type_…`, `test_ra8b_prowl_scan_refuses_…` |
| RA-CL8b NEW-A (ACARS), NEW-B (TPMS), NEW-E | CLOSED | `test_ra8b_babel_*` |
| RA-CL8b NEW-C restore | CLOSED (see NEW-Q) | `test_ra8b_restore_writes_only_suite_settings` |
| NEW-5 proxy | CLOSED | `test_ra_offline_loopback_through_a_remote_proxy_…` |
| NEW-6 LAN DNS rebinding | OPEN (deferred, LAN opt-in, listed) | — |
| NEW-7 C4 seen-per-row | CLOSED | `test_ra8b_session_log_marks_only_rows_on_screen` |
| NEW-8 to NEW-12 | CLOSED | as RA-CL8b |

## Original IDs

| ID | Status | Evidence | Test |
|---|---|---|---|
| L4 | CLOSED (shell/argv); the radio-held consequence is closed in BABEL and FM, open in SCAN for exits after 1 s (NEW-M) | PoCs above | `test_l4_*`, `test_ra_*`, `test_ra8b_*`, `test_ra8c_*` |
| C1 | CLOSED | 401/200 matrix above | `test_c1_*`, `test_headless` |
| L3 | PARTIAL (rebinding deferred) | OFFLINE NetBlocked | `test_l3_*`, `test_ra_offline_…` |
| L2 | CLOSED | unchanged | `test_l2_*`, `test_ra_harden_…`, `test_ra8b_harden_…` |
| L6 | PARTIAL (documented: user-owned `$APP`) | unchanged | `test_l6_*` |
| S1 | CLOSED | unchanged | `test_s1_*` |
| S4 | CLOSED | unchanged | `test_s4_*`, `test_ra_doctor_…` |
| C4 | CLOSED (Low: CAP eviction, listed) | unchanged | `test_c4_*`, `test_ra8b_session_log_…` |
| C5 | PARTIAL (Low, listed: duplicate loaders) | unchanged | `test_c5_*` |
| P1, P2, P3, B5, E6 | CLOSED | unchanged | `test_p1_*`, `test_p2_*`, `test_p3_*`, `test_b5_*`, `test_e6_*` |
| B4 | CLOSED | unchanged | `test_b4_*`, `test_ra_prepended_…` |
| B6 | CLOSED | TPMS argv `-H 30` live | `test_b6_*`, `test_ra8b_babel_tpms_…` |
| v0.1 SWEEP hidden / Tk retired | CLOSED | unchanged | `test_v01_…`, `test_ra_tk_home_grid_…` |

## NEW findings (not in the 93, RA-CL8, b or c)

**NEW-M · High · BLOCKING (blocker 3: radio held, retry loop, false "quiet").** NEW-H is fixed only for an rtl_fm that
dies within 1.0 s. `ScanWorker` counts an exit as early only when `listen_channel` posts `"status"`, and the engine posts
that only if `not got and now - t0 < 1.0` (`scanner.py:176, 216-220`). The engine itself allows `TUNE_SETTLE = 0.6 s`
just for rtl_fm to open and tune (`scanner.py:114`), and the branch's own rule is that a decoder that dies within 3 s
"did not really run" (`prowl.py:184`; BABEL uses 5 s). An rtl_fm that claims the dongle, inits the tuner, then fails
to stream ("Failed to submit transfer", a weak or under-volted USB port) exits after more than 1 s.
PoC (`page_scan.py`, a real `ProwlApp` live in SCAN): fake `rtl_fm` = `sleep 1.2; exit 1`, 12 s →
**12 rtl_fm spawns, `arbiter.owner() == "PROWL-SCAN"`, `worker_running=True`, page chips `{'sdr': '22 CH'}`, busy line
empty, no fault**. Every channel is shown quiet. The same on `1bc8ad1`. Fix: time the exit in `ScanWorker` (or pass
`EARLY_EXIT_S` into the engine), treating an rtl_fm that ends before its dwell/settle as an early exit, not as a listen.
Pin it with a 1.2 s / 2.5 s fake.

**NEW-N · High · BLOCKING (blocker 3: radio held with no decoder, silent).** ATLAS lease layers (`LeaseSource.poll`,
`atlas.py:474-484`) start the pipe once. If the decoder dies, `_read` returns and `_thread` stays a dead Thread. If a
binary is missing, `_open_*_pipe` returns None and `_thread = False`. Either way the layer never respawns, never
reports, and **keeps the lease until the operator turns the layer off**. readsb stays paused, so the page says
"ADS-B paused — radio held by ATLAS-APRS" while the held radio decodes nothing, and the layer shows "APRS —"
(no stations heard). PoC (`AprsSource().start()` and `poll()` every 200 ms): (a) rtl_fm/multimon-ng `exit 1`: 1 spawn,
owner `ATLAS-APRS` at 5 s, no fault; (b) multimon-ng absent: owner `ATLAS-APRS`, 0 spawns; (c) AIS `rtl_ais` `exit 1`:
owner `ATLAS-AIS`. The same on `1bc8ad1`. Fix: check `proc.poll()` in `poll()`, raise a FAULT and give the radio back
(or use the BABEL R2 backoff), and do not take the lease when the binary is missing.

**NEW-O · Medium (fails safe).** After a SCAN stall or a SCAN settings refusal, `run()` ends and `_finish` emits
"SCAN OFF — stopped" (`prowl.py:274`), which replaces the FAULT on the busy line. The `fault` chip keeps it.
After that, nothing on the page restarts SCAN. Enter → `primary_action` → `_toggle_hold` on the dead worker flips the
HOLD/SCAN label and does nothing (PoC: 0 spawns in 4 s after Enter). The only restart is to switch sub-mode and back.
The `_stall` docstring promises "no retry until the operator retunes/restarts", but SCAN has no such path.

**NEW-P · Low.** (a) FM: a pipeline that dies after more than 3 s respawns every cycle with no fault or backoff,
and shows ♪ for most of each cycle (PoC: `sleep 3.5; exit 1`, 5 spawns in 16 s). (b) NWR with multimon-ng missing says
"STANDBY — no rtl_fm". (c) BABEL "FAULT — FAILED TO START" / "SETTINGS REFUSED" is replaced on the busy line about
0.5 s later by "<MODE> IDLE — press RUN" (`babel.py:554`). The session log and RUN unticking still show it.

**NEW-Q · Medium (NEW-J remainder; owner decision).** The fix is a two-file denylist. Restore still writes every
other gate-relevant settings file. PoC: an archive with `replay.json {"tx_enabled": true, "tx_region": "EU"}` and
`operator.json` is restored. After that, `txguard.tx_locked(s)` = `(False, '')` (the "deliberate opt-in" kill switch is
off), and `txguard.classify` puts 433.92 MHz and **866 MHz** in `ism` instead of `ham` / `other`. 866 MHz is US
800 MHz public-safety/SMR spectrum and is not in `PROTECTED`. Arm and per-session unlock are still needed, so there is
no emission from the archive alone. Suggest: do not restore `tx_*` keys (or reset them to locked), and list what was
restored or skipped.

**NEW-R · Low.** Restoring the operator's own backup on a new device silently drops their network mode and Remote
Mode token/port/webhook (`headless.json`). It should say it skipped them.

## Blocking list (RA-CL8 standard, as applied in RA-CL8b/c)

1. Settings → shell: closed.
2. OFFLINE egress via templates: closed.
3. Radio held / retry / false status: BABEL closed; PROWL FM and NWR closed. **PROWL SCAN open for exits after 1.0 s
   (NEW-M); ATLAS APRS/AIS layers hold the radio with a dead or missing decoder (NEW-N).** Both predate this branch.
4. harden fails open: closed.

If the owner rules that NEW-M and NEW-N belong to a CL5 follow-up, everything CL8 and its three fix rounds claim is
closed with a test, apart from the listed PARTIALs and follow-ups. As written, the blocker-3 standard that was applied
to NEW-A, NEW-G and NEW-H applies here too.

### Reproduce

`harness.py` (scratch, not committed): builds a temp HOME and a fakebin PATH, stubs `ra._make_lease`, and runs
`DecoderWorker` / `ScanWorker` / `FmWorker` / `NwrWorker` / `AprsSource` for N s under `QT_QPA_PLATFORM=minimal`. It
prints the lease made/released counts, the owner near the end, the spawn counts and argv, and the status, fault and
error log. For NEW-M at page level: `ProwlApp(demo=False)`, `set_active(True)`, `start()`, fake
`rtl_fm` = `#!/bin/sh\necho rtl_fm >> $MARK\nsleep 1.2; exit 1`, pump 12 s, then read `arbiter.owner()`,
`p.page_status()` and `p.busy.text()`.

DO NOT MERGE
