# RA-CL8c — cold re-audit of CL8-fix2 (`fix/cl8-ship` @ c40ef8f)

Auditor: a fresh session working adversarially. Base `origin/main` = `1bc8ad1`. Environment: Python 3.13,
PySide6, offscreen + xvfb, temp HOME. Live decoder PoCs use fake binaries on a PATH that holds only
the fakes plus `sh`/`cat`/`sleep`/`echo`, `QT_QPA_PLATFORM=minimal`, and `radio_arbiter._make_lease`
stubbed to count leases. No real radio, sudo, ufw, ip or installer was run.
I read `CL8-report.md` ("CL8-fix2") only at step 3.

**Verdict: DO NOT MERGE.** Every RA-CL8b finding that CL8-fix2 claims is closed holds up: BABEL ACARS and
TPMS now start with the expected argv, a missing decoder is a FAULT with the radio released, restore is
limited to the files backup writes, and the session log marks only rows that are on screen. The brief also
asked for a check of every PROWL sub-mode against a binary that exits at once. That check fails: **PROWL FM
and PROWL SCAN keep the radio in a respawn loop and show no fault**. FM even shows "FM 97.3 ♪" as live
the whole time (NEW-G, NEW-H). This is blocker 3 (radio held, retry storm, false status), the same
blocker class RA-CL8b applied to NEW-A. The defect predates this branch and is the same on `1bc8ad1`.

## Suite

`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q -p no:cacheprovider tests` (temp HOME):
**1602 passed, 7 skipped, 2 failed, 7 errors in 722 s**. All failures and errors are the known baseline:
`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, 7 × `test_shell`
(no tkinter). `tests/test_cl8_ship.py` passes in full, including the 10 `test_ra8b_*` tests.
Restore PoC (step 1) also confirmed: the archive's `net.json` → `netpolicy.mode()` = ONLINE after restore; a file
member `.local/share/uconsole-suite/logbook` raises `NotADirectoryError` partway through the restore.

## Step 1 — live PoCs at the branch head

Harness: `DecoderWorker(demo=False, mode=…)` / `ScanWorker` / `FmWorker` / `NwrWorker`, RUN on, 3–8 s.
Each run records the lease count, the owner at the end, the release count, the spawned argv and the status
texts.

### BABEL, recording fakes, default settings

| Mode | argv spawned | Status | Lease |
|---|---|---|---|
| POCSAG | `rtl_fm -f 152.007M -M fm -s 22050 -E dc -` → `multimon-ng -t raw -a POCSAG512 -a POCSAG1200 -a POCSAG2400 -a FLEX /dev/stdin` | POCSAG LIVE | 1 made, released on stop |
| AIS | `rtl_ais -n` | AIS LIVE | same |
| RDS | `rtl_fm -M fm -l 0 -A std -p 0 -s 171k -F 9 -f 100.3M` → `redsea -r 171000` | RDS LIVE | same |
| TPMS | `rtl_433 -F json -M level -f 315M -f 433.92M -H 30` | TPMS LIVE | same |
| ACARS (no file, `source` acars / sensors / `5`, `[1,2]` file) | `acarsdec --output json:file:path=- --rtlsdr 0 -g 40 131.550 …` | ACARS LIVE | same |
| ACARS `source: vdl2` | `dumpvdl2 --rtlsdr 0 --gain 40 --output decoded:json:file:path=- 136650000 …` | ACARS LIVE | same |

Every `_open_pipe` / `Pipeline` call site now passes a list of argv lists: `babel.py:162` (AIS:
`ais.pipeline_argv` returns `[argv]`), `:213` (`[argv]`), `:249`, `:286`, `:353` (`[argv]`),
`atlas.py:320,331`, `prism.py:85`, `prowl.py:73`. `Pipeline` itself still accepts a flat argv without
complaint (see NEW-K).

### BABEL, failure cases

| Case | Result |
|---|---|
| ACARS `source: vdl2`, dumpvdl2 missing | ACARS FAULT — FAILED TO START (`FileNotFoundError: 'dumpvdl2'`). Lease made 1, released, 0 spawns, no retry |
| POCSAG / RDS with rtl_fm missing (decoder present) | FAULT — FAILED TO START, released, no retry |
| ACARS acarsdec missing, `source: vdl2`, dumpvdl2 present | ACARS STANDBY — no acarsdec. No lease. Wrong reason, but fails safe (Low, NEW-L) |
| ACARS/AIS/TPMS/POCSAG decoder exits at once (either stage) | `FAULT: … exited after 0.0s (×1) — retry in 2s`, then ×2 → 4 s and so on (2/4/8/16/30/60). The lease is held during the backoff, which is the R2 design: visible FAULT, bounded backoff. Each respawn briefly emits "<MODE> LIVE" before the next FAULT (Low) |
| `acars_cmd: 5`, `vdl2_cmd: 5`, `gain: "x"`, `gain: [1]`, bad template frequency | SETTINGS REFUSED, released, 0 spawns |
| L4 PoC `pager.json freq "929.6M -M fm; id > /tmp/x #"` | POCSAG FAULT — SETTINGS REFUSED, released, 0 spawns |

### PROWL

| Sub-mode | Case | Result |
|---|---|---|
| SCAN | recording rtl_fm | `rtl_fm -f 162.4000M -M fm -s 12000 -g 40 -l 50 -`, lease released on stop |
| SCAN | **rtl_fm exits at once** | **8 spawns in 8 s. The lease is held throughout. Status, fault and error signals are all empty; the only status is "SCAN OFF — stopped" at the end. Channels are listed as quiet (NEW-H)** |
| SCAN | `dwell: "x"` | worker thread dies (`TypeError` in `scanner.listen_channel:153`). Radio released; page says only "SCAN OFF — stopped" (NEW-D remainder) |
| SCAN | `gain: "auto"`, `gain: "x"`, `custom: 5` … | SCAN FAULT — SETTINGS REFUSED, no lease |
| FM | rtl_fm + aplay | `rtl_fm -d 0 -M wbfm -f 97.3000M -s 200000 -r 48000 -g 40 -E deemp -`; with redsea `… -s 171000 -A std -F 9 …` → `redsea -r 171000 -u -e` |
| FM | **rtl_fm exits at once** | **24 spawns in 6 s (~4/s). Status "FM 97.3 ♪" with `live: True, ok: True` for the whole run. No fault, no error. Lease held (NEW-G)** |
| FM | **redsea exits at once** | **30 spawns in 5 s. Same "FM 97.3 ♪" live claim, no fault** |
| FM | no aplay/pacat | `FileNotFoundError: 'aplay'` raised out of `step()`. Worker error, then FAULT ×3 with backoff. Lease **held** while no decoder can start (Medium, NEW-I) |
| NWR | recording fakes | `rtl_fm -f 162.400M -M fm -s 22050 -E dc -` → multimon-ng; "NWR — waiting for audio" (correct: the fakes send none) |
| NWR | both exit at once | NWR DOWN ×1..3, then NWR FAULT "keeps failing … retry in 10s": a visible FAULT and a hold-down. Correct |

The same SCAN and FM runs against a `1bc8ad1` worktree give identical numbers (8 spawns silent / 24 spawns
"FM 97.3 ♪"). Neither is a regression; both are pre-existing.

### NEW-C restore, NEW-D, NEW-E, C4

- NEW-C: `suite.restore_configs` (`suite.py:876-907`) restores only members under `.config/uconsole-suite/`,
  `.config/sky-app/`, `.local/share/uconsole-suite/logbook/` and the named data files, and only regular files
  and dirs. My PoC confirms it: `.bashrc`, `.config/rtl_433/rtl_433.conf`,
  `.local/share/uconsole-suite/app/...` (outside the allow list), `../` and `./` spellings, symlinks and
  hardlinks are all skipped. The app lives at `~/.local/share/uconsole-suite/app`, which is not restorable.
  Residue: see NEW-J.
- NEW-D: gain/squelch/nfm_squelch/custom are checked (`prowl.py:296-307`); `dwell`, `hold`, `max_active`
  are not (PARTIAL; it fails safe).
- NEW-E: `_run_acars` forces `source: acars` unless it is `acars`/`vdl2` (`babel.py:203-206`). No rtl_433
  under the ACARS label in any configuration I tried. CLOSED.
- C4 / NEW-7: real `PalisadeHub` at 1280×720 dark, log panel 1000×560 (10 rows on screen). Fault A, 40 NET,
  error B, 40 NET → open: only fault A is on screen and the unseen count goes 2→1 (tooltip "1 unseen fault").
  With three faults spread out, the count goes 3→2. Scrolling marks the rest. CLOSED. The CAP=1000 eviction residue
  remains Low (listed by the author).

## Step 2 — regressions

- Demo decode: `DecoderWorker(demo=True)` emits rows for AIS, ACARS, POCSAG, RDS, TPMS, CW and RTTY (15 each in 1.5 s at
  100 ms). PROWL SCAN/FM/NWR demo emit rows. No lease is taken in demo.
- Backup → restore round trip (`backup_configs` then wipe then `restore_configs`, temp HOME): settings (including a
  nested subdir), `headless.json` mode 0600 kept, `sky_records/coverage/types.json`, logbook (including a nested
  subdir), both bingo files. 16/16 members restored, byte-identical. Same on `1bc8ad1`.
- Session log + MODE indicator: the strip glyph/tooltip track unseen faults (PoC above, `test_c4_*`).
- Decoder device check (`argsafe._device`, `argsafe.py:92-96`) now refuses a bare serial for
  acarsdec/dumpvdl2 `--rtlsdr 00000002` (Low usability regression, fails safe with SETTINGS REFUSED;
  NEW-L).

## Step 3 — tests

`git diff dcb4c6e..HEAD -- tests`: 137 additions, 1 deletion in `tests/test_cl8_ship.py`. The one changed
line swaps an ACARS malformed-settings case from `source: sensors, rtl433_cmd: …` to `source: acars,
acars_cmd: "acarsdec {gain[0]} {freqs}"`. This is justified by NEW-E (ACARS never runs the rtl_433
template now), and the refusal is still asserted. Against `1bc8ad1`, no new weakening beyond the set RA-CL8
already justified.

## RA-CL8b findings

| RA-CL8b | Status | Evidence | Test |
|---|---|---|---|
| NEW-A (blocker 3, ACARS held) | CLOSED | `babel.py:213` one stage; the `FileNotFoundError` catch is gone. PoC: every source gives the expected acarsdec/dumpvdl2 argv. A missing dumpvdl2 gives FAULT + release, no retry | `test_ra8b_babel_acars_starts_acarsdec_never_the_sensor_decoder[None/sensors/acars]` (real `_open_pipe`, argv checked). Gap: no test drives a *missing* decoder through the real `_open_pipe`; only the generic `test_ra_unexpected_start_error_is_a_fault_and_releases_the_radio` (RuntimeError) covers it |
| NEW-B (TPMS) | CLOSED | `babel.py:353`; PoC argv `-f 315M -f 433.92M -H 30` | `test_ra8b_babel_tpms_runs_rtl_433_with_the_hop` |
| NEW-C (restore) | CLOSED (Medium residue NEW-J) | `suite.py:883-896` | `test_ra8b_restore_writes_only_suite_settings` |
| NEW-D (SCAN malformed) | PARTIAL | `dwell`/`hold`/`max_active` unchecked: `{"dwell":"x"}` kills the worker, "SCAN OFF — stopped" only. Fails safe | `test_ra8b_prowl_scan_refuses_malformed_scanner_settings` (5 cases, none of these keys) |
| NEW-E (ACARS ran rtl_433) | CLOSED | `babel.py:203-206` | `test_ra8b_babel_acars_…[None/sensors]` |
| NEW-F (Lows) | CLOSED | harden trap reports COULD NOT (`harden.sh:68-69`); `_device` digits/`:serial` | `test_ra8b_harden_says_so_…`, `test_ra_decoder_templates_…` (`-d soapy` added) |
| NEW-7 / C4 seen-per-row | CLOSED | `panels.py:640-653, 690-691`; `sessionlog.py:107-124` | `test_ra8b_session_log_marks_only_rows_on_screen` |
| Blockers 1, 2, 4 (RA-CL8) | CLOSED | Unchanged since RA-CL8b; L4 PoC and Scout `bash -c id` re-run: refused | `test_l4_*`, `test_ra_scout_wifi_cmd_…`, `test_ra_decoder_templates_…`, `test_ra_harden_…` |
| NEW-5 proxy | CLOSED | unchanged | `test_ra_offline_loopback_through_a_remote_proxy_…` |
| NEW-6 DNS rebinding | OPEN (deferred, LAN opt-in) | unchanged | — |
| NEW-8 to NEW-12 | CLOSED | unchanged | as RA-CL8b |

## Original IDs

| ID | Status | Evidence | Test |
|---|---|---|---|
| L4 | CLOSED for shell/argv injection; radio-held consequence closed in BABEL | PoC refused; every BABEL mode spawns the checked argv | `test_l4_*`, `test_ra_*`, `test_ra8b_*` |
| C1 | CLOSED | `/`, `/api/status`, `/api/contacts`: 401 with no token or a wrong token; `/health` 200; empty token refused by `make_app` | `test_c1_*`, `test_headless` |
| L3 | PARTIAL (non-blocking) | OFFLINE: public IP, a public name, `file:`, `ftp:` all NetBlocked. Rebinding deferred | `test_l3_*`, `test_ra_offline_…` |
| L2 | CLOSED | unchanged + trap message | `test_l2_*`, `test_ra_harden_…`, `test_ra8b_harden_…` |
| L6 | PARTIAL (documented) | unchanged | `test_l6_*` |
| S1 | CLOSED | unchanged | `test_s1_*` |
| S4 | CLOSED | `doctor` imports on 3.13.18 | `test_s4_*`, `test_ra_doctor_…` |
| C4 | CLOSED (Low: CAP eviction) | see above | `test_c4_*`, `test_ra8b_session_log_…` |
| C5 | PARTIAL (Low, listed) | duplicate settings loaders remain | `test_c5_*` |
| P1, P2, P3, B5, E6 | CLOSED | unchanged since RA-CL8 | `test_p1_*`, `test_p2_*`, `test_p3_*`, `test_b5_*`, `test_e6_*` |
| B4 | CLOSED | unchanged | `test_b4_*`, `test_ra_prepended_…` |
| B6 | CLOSED | rtl_433 now really gets `-H 30` | `test_b6_*`, `test_ra8b_babel_tpms_…` |
| v0.1 SWEEP hidden / Tk retired | CLOSED | unchanged | `test_v01_…`, `test_ra_tk_home_grid_…` |

## NEW findings (not in the 93, RA-CL8 or RA-CL8b)

**NEW-G · High · BLOCKING (blocker 3: radio held, retry storm, false live).** PROWL FM: when rtl_fm (or redsea, or
the sink) exits at once, `FmWorker.step` respawns the whole pipeline every 500 ms step. It does this while
holding the lease, with no early-exit detection, no fault and no backoff (`prowl.py:462-463`). It then
reports `audio = self._pipe is not None` → "FM 97.3 ♪", `live: True, ok: True` (`prowl.py:468-473`).
The real trigger is an unplugged or busy dongle: rtl_fm prints "No supported devices" and exits.
PoC: fake `rtl_fm` = `exit 1`, `aplay` = `cat`, FmWorker live 6 s → 24 rtl_fm spawns, 12 "FM 97.3 ♪"
live statuses, 0 faults, lease held until stop. With `redsea` = `exit 1`: 30 spawns in 5 s. Same on `1bc8ad1`.
Fix: treat an exit within N s of spawn as a FAULT with backoff (the BABEL R2 pattern or NWR's flap
hold-down), and claim ♪ only while audio actually flows.

**NEW-H · High · BLOCKING (blocker 3: radio held, retry loop, silent).** PROWL SCAN: when rtl_fm exits at once,
`scanner.listen_channel` posts `("status", "rtl_fm exited at once - is the SDR free?")` (`scanner.py:216-220`),
but `ScanWorker._make_post` handles only `"hit"` and `"fatal"` (`prowl.py:371-385`), so the message is dropped.
The worker keeps the lease and spawns rtl_fm about once a second on channel after channel. The page shows every
channel quiet, which is a false negative for a scanner. PoC: fake `rtl_fm` = `exit 1`, 8 s → 8 spawns, lease held,
no status, fault or error until "SCAN OFF — stopped". Same on `1bc8ad1`. Fix: surface `"status"` as a FAULT,
back off, and release after repeated early exits.

**NEW-I · Medium (visible, holds radio).** PROWL FM with no `aplay`/`pacat`: `fm.Pipe` raises `FileNotFoundError`
out of `FmWorker._spawn` (`prowl.py:476-483` catches only `fm.pipeline` errors). Worker.run backs it off
as a generic error and FAULT, but `_has_radio` stays true, so readsb stays paused while no decoder can
ever start.

**NEW-J · Medium (pre-existing semantics, follow-up).** Restore is now limited to suite files, but within
`.config/uconsole-suite/` it restores everything, including `net.json` (`{"mode":"ONLINE"}` overrides the
OFFLINE default) and `headless.json` (`host`, `token`). An untrusted archive can therefore set the network
mode and plant a Remote Mode token and bind address that the attacker knows, which take effect the next time
the operator starts Remote Mode. That is the L4 threat model ("restored backup archives write those files")
applied to the L3/C1 settings. Suggest: do not restore `net.json`/`headless.json` (or reset the token and
bind address on restore), and show what was restored. A regular-file member named `.config/uconsole-suite` or
`.local/share/uconsole-suite/logbook` (both on the allow list as files) aborts or corrupts the restore (Low).

**NEW-K · Low (hygiene).** `kit.procs.Pipeline` / `babel._open_pipe` accept a flat argv and turn each
string into a "stage" (`list("rtl_433")`). NEW-A and NEW-B were this exact bug. A one-line type check
(each stage is a list of str) would make it impossible to reintroduce.

**NEW-L · Low.** (a) `argsafe._device` refuses a bare RTL serial (`--rtlsdr 00000002`) for acarsdec/dumpvdl2,
which accept one. It fails safe (SETTINGS REFUSED). (b) ACARS `source: vdl2` with dumpvdl2 present but
acarsdec absent shows "STANDBY — no acarsdec" (`_MODE_BINARY` is per mode, `babel.py:144`). (c) BABEL
emits "<MODE> LIVE" (ok) on each respawn during an R2 fault backoff, so the chip alternates
LIVE/FAULT. (d) Each `_open_pipe` that fails in `Pipeline` leaks its stderr temp file. (e) NEW-D remainder:
`dwell`/`hold`/`max_active` unchecked.

## Blocking list

1. Settings → shell: closed.
2. OFFLINE egress via templates: closed.
3. Radio held / retry / false status: **BABEL closed; PROWL FM (NEW-G) and SCAN (NEW-H) open**, both pre-existing
   on `1bc8ad1`, both reproduced with the binary-that-exits-at-once case the brief asked for.
4. harden fails open: closed.

If the owner decides that NEW-G/NEW-H belong to a CL5 follow-up rather than CL8, everything CL8 and its two
fix rounds claim is closed with a test, apart from the listed PARTIALs and follow-ups. As written, the blocker
3 standard used for NEW-A applies here too.

DO NOT MERGE
