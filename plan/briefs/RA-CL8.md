# RA-CL8 — cold re-audit of CL8 (`fix/cl8-ship`)

**FRESH session, Opus.** Auditor only. Own worktree
(`git worktree add ../wt-RA-CL8 origin/fix/cl8-ship`). Read the audit PDF §§ for L4, C1, L3, L2,
L6, S1, S4, C4, C5, P1, P2, P3, B4, B5, B6, E6 first (`plan/audit/PALISADE_full_audit_report_2026-11-15.pdf`,
`plan/audit/AUDIT_INDEX.md`). Read `plan/briefs/CL8-report.md` only at step 4.

IDs: L4 C1 L3 L2 L6 S1 S4 C4 C5 P1 P2 P3 B4 B5 B6 E6 · v0.1 line (SWEEP hidden; Tk gated tools
retired from the Tk hub: cw rtty digimodes replay proxmark wifipent blepent zigbee zwave usbhid).

1. Re-derive every audit PoC against the branch:
   - L4: `pager.json` frequency `929.6M -M fm; id > /tmp/x #` in Qt BABEL and the Tk app; every
     other settings value that reaches argv (rds, nwr, aprs, ais, signals templates, TPMS, FM,
     waterfall/specan/canbus). Any `shell=True`, `sh -c`, `bash -c`, `os.system` left anywhere?
     Argument injection through a pinned program (rtl_433 `-w`, acarsdec `--output`)?
   - C1: every Remote Mode route without / with a wrong token; token storage; XSS via contact fields.
   - L3: is there ANY outbound request not through `netpolicy`? DNS in OFFLINE? A LAN name that
     resolves to a public address? Redirect from a LAN host to the internet? Non-http schemes?
   - L2: run `harden.sh` ONLY with `sudo`/`ufw`/`ip` stubbed on PATH (never for real). Does any
     path disable the firewall or leave inbound open in `--field`/`--revert`?
   - L6/S1: build the installer (`build_installer.sh /tmp/x.sh`), inspect payload and tail. Do
     NOT run the installer.
   - S4: doctor on Python 3.13 (no `crypt`/`spwd`).
   - C4: errors/faults from workers, serial, the arbiter, uncaught exceptions: logged and visible?
     Can the fault indicator be cleared without the operator seeing the fault?
   - P1/P2/P3/B4/B5/B6/E6 as in the PDF.
2. Attack the design:
   - `argsafe.PipeGroup` with real processes: one group, every stage killed by `stop_group`, no
     orphan when stage 2 fails to start.
   - BABEL/PROWL with refused settings: is the radio ever held after a refusal? retry storm?
   - The strip: worst case ≤ 1270 px in every theme, live and demo (NET slot added, OPSEC
     placeholder removed, SWEEP hidden). Keys 1–7 and the palette: can SWEEP still be reached?
   - Remote ID: can one spoofed advert still produce a red drone or an OPS alert anywhere?
   - netpolicy listener / session log across threads: any GUI-thread network call, any Qt object
     touched off its thread?
3. UI-only rule: no data/decoding/radio behaviour change beyond what the findings require (AIS
   checksum refusal, TPMS `-H`, argv validation are required; check nothing else moved).
   Render at 1280×720 dark + sun, live: OPS, ATLAS, RECON, PROWL, SYSTEM, the SESSION LOG panel.
4. Regression: `tests/test_cl8_ship.py`, then the full suite once on Python 3.12+
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`). Diff denial/negative
   assertions in `tests/` against `1bc8ad1` (main). Every weakened assertion must be justified
   by a CL8 semantic change (listed in the report), or it is a finding.
5. Write `plan/briefs/RA-CL8-report.md` on `fix/cl8-ship`, push it, remove the worktree. Table
   per ID, then new findings, then one line: MERGE / DO NOT MERGE. These block: a settings value
   that reaches a shell or an unchecked argv; an unauthenticated Remote Mode route; an outbound
   request in OFFLINE; a harden profile that leaves inbound open or disables the firewall; a
   radio held after a refusal; a strip wider than 1270 px; a red drone from one advert.
   Hygiene is a follow-up.

Known baseline failures (same on main, env): `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
`test_hwlab::test_doctor_hwbench_check`, `test_shell` errors without tkinter.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALQMMsmycF1AqRUye2B`
