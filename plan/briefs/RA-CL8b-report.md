# RA-CL8b — cold re-audit of CL8-fix (`fix/cl8-ship` @ 565ef4f, code `ccdbbed`)

Auditor: a fresh session working adversarially. Base `origin/main` = `1bc8ad1`. Environment: Python 3.13, PySide6, offscreen + xvfb, temp HOME.
I read `CL8-report.md` (CL8-fix section) only at step 3.

**Verdict: DO NOT MERGE.** Blockers 1, 2 and 4 are closed. Blocker 3 still reproduces: BABEL **ACARS**
holds the radio in a 1 Hz retry loop labelled "ACARS — no capture (offline)". It needs no malformed setting:
the shipped defaults trigger it (NEW-A). The CL8-fix "any start error is a FAULT, radio released" does not
cover this path, because `_run_acars` catches `FileNotFoundError` itself and returns without a process.

## Suite

`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q -p no:cacheprovider tests`:
**1592 passed, 7 skipped, 2 failed, 7 errors in 685 s**. All failures and errors are the known baseline:
`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`
and 7 × `test_shell` (no tkinter). `tests/test_cl8_ship.py` passes in full.
Test diff: `889b7ed..HEAD` only adds to `tests/test_cl8_ship.py` (+240, 0 deletions). Against
`1bc8ad1`, the changed assertions are the same set that RA-CL8 already justified. No new weakening.

## RA-CL8 findings

| RA-CL8 | Status | Evidence | Test |
|---|---|---|---|
| Blocker 1 (Scout `wifi_cmd`) | CLOSED | `scout.wifi_argv` (`scout.py:321-347`), `wifi_scan` (`:350`). Stub-nmcli PoC: `bash -c id>…` gives SETTINGS REFUSED and nothing runs; `nmcli dev wifi connect …`, `--ask`, `5` and `None` are refused. Residue (Low, no effect): option *values* are unchecked (`nmcli -f --ask dev wifi list`, `ifname -h` are accepted), but they stay nmcli read-only list arguments. Sweep of every `Popen`/`run`/`spawn` in Tk + Qt: no other settings value picks argv[0] or adds an option. A single-token option *value* remains for wxsat `--source`, wifisurvey/recon `iface` and canbus `iface`; the author lists these. | `test_ra_scout_wifi_cmd_…` |
| Blocker 2 (template egress) | CLOSED | `argsafe.template_argv` (`argsafe.py:71-145`), used by `signals.build_argv` (`signals.py:185`). Refused: `-F syslog/mqtt/http/json:file`, `-Fsyslog:` bundling, `-w -W -c -S -r -X --`, `-d rtl_tcp:host`, `-d driver=remote`, acarsdec `--output …udp`, `-j -n -l`, dumpvdl2 `--output …udp/zmq`, `--zmq`, `--iq-file`. When a value starts with `-` (`-M -F`, `--station-id --zmq`), it is consumed as the option's value, the same way getopt consumes it, so it is never parsed as an option. Residue (Low): `-d rtl_tcp` (localhost:1234) and `-d soapy` pass. rtl_433 also auto-loads `./rtl_433.conf` / `~/.config/rtl_433/rtl_433.conf` when no `-c` is given (see NEW-C). | `test_ra_decoder_templates_…` (22), `test_ra_shipped_and_old_default_templates_still_build` |
| Blocker 3 (radio held) | **OPEN** | Malformed types now refuse and release in POCSAG/AIS/RDS/TPMS (PoC: pager `freq:[1]`, `gain:{}`, ais `gain:[1]`, rds `freq:{}`, tpms `hop_s:"x"`, `freqs:[[1]]`, `gain:[1]` → SETTINGS REFUSED, lease made 1 / released 1). **ACARS holds the radio for every configuration: see NEW-A.** | `test_ra_malformed_setting_type_…` passes only because its ACARS cases refuse before the spawn |
| Blocker 4 (harden fails open) | CLOSED | EXIT trap `harden.sh:64-74`. With a stub sudo/ufw/ip state machine, I failed every sudo step in turn in `--field`, `--revert` and HOME: ufw ends enabled with inbound deny every time, and rc≠0. SIGTERM/SIGHUP/SIGINT after the reset also re-enable it. Residue (Low): if `ufw --force enable` fails *persistently*, ufw stays off and the only message is "turning the firewall back on, inbound denied". The result of the re-enable is never checked or reported. | `test_ra_harden_field_never_leaves_…` (2 of 4 steps) |
| NEW-5 proxy | CLOSED | `netpolicy._proxy_for`/`check` (`netpolicy.py:176-201`). PoC with `http_proxy=http://203.0.113.9:3128` in OFFLINE: 127.0.0.1 and localhost are both blocked "via proxy". Low: the opener's ProxyHandler is built once (`_install_opener`), so an env proxy that is *removed* at runtime would still be used after the check passes. | `test_ra_offline_loopback_through_a_remote_proxy_…` |
| NEW-6 DNS rebinding | OPEN (deferred by author, LAN opt-in) | unchanged | — |
| NEW-7 log clears unseen | **PARTIAL** | Opening the log scrolls to the *oldest* unseen fault, then `mark_seen()` marks *all* faults seen (`panels.py:670-683`). PoC at 1280×720: fault A, 40 NET rows, error B, 40 NET rows. After open, only A is among the 14 visible rows, yet `faults_unseen` goes 2→0. The header says "2 fault/error", so the count is visible. Separately, CAP=1000 eviction can remove an unseen fault (Low). | `test_ra_session_log_open_…` (single fault only) |
| NEW-8 Tk grid | CLOSED | `hub.visible_groups` (`hub.py:104-109`, applied at `:982`). Static check: 67 GROUPS launch keys; none is left without a CMD after filtering. MODS is filtered too. A key with no command now gives a message instead of a TypeError (`:800`). Not rendered (no tkinter). | `test_ra_tk_home_grid_…` |
| NEW-9 sky.desktop | CLOSED | `install_tail.sh:82` → `/usr/local/bin/sky`. The built installer passes `bash -n`. | `test_l6_*` (string) |
| NEW-10 B4 prepend | CLOSED (Low residue) | `kit/feed.py:118-119, 203-218`. Low: BABEL rows have no `_id`, so the content key can match a duplicate row. | `test_ra_prepended_rows_…` |
| NEW-11 doctor | CLOSED | With real libcrypt: yescrypt/sha512 "dragon" → flagged, a unique password → OK, `$9$` → "unavailable". | `test_ra_doctor_…`, `test_s4_*` |
| NEW-12 keymap | CLOSED | `panels.py:772` "1 – 7" | `test_ra_keymap_…` |

## Original IDs

| ID | Status | Evidence | Test |
|---|---|---|---|
| L4 | **PARTIAL** | Shell/argv[0]/option injection closed (blockers 1–2). The radio-held consequence remains in ACARS (NEW-A). The L4 threat model ("a restored backup writes settings") is undercut by NEW-C. | `test_l4_*`, `test_ra_*` |
| C1 | CLOSED | Unchanged since RA-CL8 (all routes 401 without the token). | `test_c1_*`, `test_headless` |
| L3 | PARTIAL | Template egress and env proxy closed. LAN rebinding and mode-blind DNS are deferred (not blocking: OFFLINE never resolves). | `test_l3_*`, `test_ra_offline_…` |
| L2 | CLOSED | See blocker 4. The HOME profile still never resets old-subnet allows (Low, pre-existing). | `test_l2_*`, `test_ra_harden_…` |
| L6 | PARTIAL (documented) | Root-owned launchers still run user-owned `$APP`. The author documents this as a limit. | `test_l6_*` |
| S1 | CLOSED | Installer builds and passes `bash -n`. The Qt payload ships. | `test_s1_*` |
| S4 | CLOSED | See NEW-11. | `test_s4_*` |
| C4 | PARTIAL | See NEW-7. | `test_c4_*`, `test_ra_session_log_…` |
| C5 | PARTIAL (Low) | Duplicate settings loaders remain (author lists this). | `test_c5_*` |
| P1, P2, P3, B5, E6 | CLOSED | Unchanged since RA-CL8. | `test_p1_*`, `test_p2_*`, `test_p3_*`, `test_b5_*`, `test_e6_*` |
| B4 | CLOSED | See NEW-10. | `test_b4_*`, `test_ra_prepended_…` |
| B6 | **PARTIAL** | `tpms_argv` is right (`-f 315M -f 433.92M -H 30`), but live BABEL TPMS never starts: `_run_tpms` passes a flat argv to `_open_pipe`, which treats each string as a stage, so it spawns `['r','t','l',…]` (`babel.py:350`, `:53`). PoC with fake `rtl_433` on PATH: "TPMS FAULT — FAILED TO START: FileNotFoundError: 'r'". The hop never reaches rtl_433. Since CL8-fix the radio is at least released; on main it was held. The test mocks `_open_pipe` (`test_palisade_qt.py:995`), so the bug is invisible to the suite. | `test_b6_*` (argv only) |
| v0.1 SWEEP hidden | CLOSED | Unchanged. | `test_v01_…` |
| v0.1 Tk retired | CLOSED | See NEW-8. | `test_ra_tk_home_grid_…` |

## NEW findings (not in the 93, not in RA-CL8)

**NEW-A · High · BLOCKING (blocker 3: radio held, retry loop, false "offline").** BABEL ACARS can never
start a decoder, and it holds the SDR (readsb paused, so ATLAS loses ADS-B) in a 1 Hz loop.
`_run_acars` calls `_open_pipe(argv, …)` with a flat argv (`babel.py:207`). `_open_pipe` does
`[list(x) for x in cmd]` (`babel.py:53`), so stage 1 is `['a','c','a','r','s',…]` and `Popen` raises
`FileNotFoundError: 'a'` (or `'r'` / `'d'`). `_run_acars` catches that, emits "acarsdec not found", and
returns with `_proc=None` (`babel.py:208-210`). `_run_live` then takes the "no capture (offline)" branch
and keeps the lease, retrying every 1 s (`babel.py:624-630`). The same path follows a genuinely missing
dumpvdl2/rtl_433 when `source` is vdl2/sensors. PoC (`DecoderWorker(demo=False, mode="ACARS")`, fake
`acarsdec`/`rtl_433`/`dumpvdl2` on PATH, `QT_QPA_PLATFORM=minimal`, `radio_arbiter._make_lease` stubbed):
no settings file, `{"source":"acars"}`, `{"source":"vdl2"}`, `{"source":"sensors"}` and a list-valued
signals.json all give lease made 1 / **released 0**, owner `BABEL` after 3.5 s, no binary run, 4 errors
"acarsdec not found — install it or use --demo", and status "ACARS — no capture (offline)". The same happens
on `1bc8ad1` (pre-existing since CL5), but this is the exact symptom NEW-1 / blocker 3 required fixed. Fix:
pass `[argv]` and make a spawn failure a FAULT that releases. Add a test with a real `_open_pipe` and fake
binaries.

**NEW-B · Medium.** BABEL TPMS live never starts (same flat-argv bug, `babel.py:350`). Since CL8-fix it
fails safe, with FAULT + release. This makes B6 inert.

**NEW-C · High (pre-existing, not blocking per the RA-CL8 list).** `hub --restore` (`suite.restore_configs`,
`suite.py:876-894`) extracts **any** member under HOME, not only the settings dirs that `backup_configs`
writes. PoC: an archive with `.bashrc`, `.config/rtl_433/rtl_433.conf` (`output syslog:203.0.113.5:514`)
and `uconsole-suite/hub.py` was fully restored into a temp HOME. This undercuts the whole L4 premise:
a restored backup gets code execution at the next login, and rtl_433 auto-loads that conf when no `-c`
is given, which sends decoded data off-device in OFFLINE. Fix: restore only the members whose paths
`backup_configs` produces.

**NEW-D · Medium (fails safe).** PROWL SCAN with malformed `scanner.json` (`gain:"x"`, `gain:[1]`,
`custom:5`) kills the worker thread with an uncaught exception. The radio is released, but the page shows
only "SCAN OFF — stopped": no SETTINGS REFUSED and no fault signal, unlike FM/NWR/BABEL
(`scanner.rtl_cmd` `int(gain)` at `scanner.py:109`, `parse_custom` at `:235`).

**NEW-E · Medium.** With the default `signals.json` (`source: "sensors"`), BABEL's ACARS mode builds
`rtl_433 … -F json` and parses it with `parse_acars` (`babel.py:201-204`). Once NEW-A is fixed, ACARS will
show "ACARS LIVE" while running a 433 MHz sensor decoder and never decode ACARS.

**NEW-F · Low.** harden.sh: the trap's re-enable result is not checked, so a persistent `ufw enable`
failure leaves ufw off under a message saying it was turned back on. In the session log, CAP eviction
can drop an unseen fault. Opening the log marks unseen faults that are off screen as seen (NEW-7 remainder).

## Regressions (step 2)

The shipped default templates and the old acarsdec default build, and `migrate` still replaces it.
POCSAG/AIS/RDS spawn with fake binaries. BABEL/PROWL demo pass in the suite. The session log indicator
works. The Tk hub grid has no dead keys (static). A hand-edited template using a now-unlisted option
(for example `-X` flex decoders) is refused with a message; that fails safe and is acceptable.

## Blocking list

1. Settings → shell: closed.
2. OFFLINE egress via templates: closed.
3. **Radio held / retry / false offline: OPEN (NEW-A, BABEL ACARS, every configuration).**
4. harden fails open: closed.

DO NOT MERGE
