# RA-SCAN — cold audit of SCAN (live Wi-Fi / BLE / Remote-ID scans)

**FRESH session, Opus.** Auditor only. Own worktree off `origin/claude/project-thread-08f65f`
(based on `fix/cl8-ship`). Read `plan/briefs/device-notes.md` (RECON + General) on docs/briefs,
then the diff `git diff origin/fix/cl8-ship...origin/claude/project-thread-08f65f`. Read
`plan/briefs/SCAN-report.md` on the branch only at step 3.

Owner requirement: every passive scan does a real live scan on the device as installed (Debian 13,
user `dragon`, NetworkManager, bluez, bleak via pip, no root). No stubs, no permission dead ends.
Hard rules: no system changes made by the app; gates (engagement/opprofile/txguard) untouched;
labels honest (an active scan is never called passive); UI-only changes do not alter decoding.

1. Wi-Fi (RECON › WIFI): with fake `iw` / `nmcli` binaries on PATH (refused / ok / missing / hang /
   garbage / SSIDs with `:` `\` and non-ASCII / duplicate BSSIDs): right path chosen? both
   reasons on double failure? any path that shows "0 AP" or an empty table without a reason? Is
   NM's % ever shown or published as dBm? Does the nmcli argv ever do anything but list (no
   connect/rescan-only abuse via settings)? Timeouts vs the worker stop/join budget.
2. BLE (RECON › BLE): fake `bluetoothctl` (real formats incl. colour codes, `RSSI: 0x.. (-n)`,
   cached-device NEW lines before discovery, NotReady/NotAuthorized, bluetoothd down, a process
   that never exits) and a fake `bleak` module. Check: no connect/pair/trust/GATT anywhere;
   cached-unheard devices never shown as heard; stop/pause/close end the scan and kill the
   process group promptly (no orphan bluetoothctl, no QThread left running — Worker contract);
   no retry storm; bus flood; thread-safety of the bleak callback and the reader thread.
3. ATLAS Remote-ID fallback: only the "--experimental" refusal triggers active mode; any other
   error still faults; the note is honest; RidSource stop still stops the scan.
4. doctor `chk_wifi_scan` / `chk_ble_scan`: never change the system; honest on root / setcap /
   no NM / no adapter / powered off. Installer: `rtl-sdr` added via safe_apt only.
5. `tests/test_scan_live.py`, then the full suite once
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`). Known baseline failures:
   `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`,
   `test_shell` errors without tkinter, flaky `test_cl1_fix2` ack_all.
6. Write `plan/briefs/RA-SCAN-report.md` on `claude/project-thread-08f65f`, push, remove the
   worktree. Table per SCAN-1..4 + doctor (CLOSED / PARTIAL / OPEN), new findings with severity,
   then one line: MERGE or DO NOT MERGE. Blockers: a dishonest label, a gate or system change, a
   scan that leaves a process/thread behind, a regression in an existing test.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALNorGhgTua8bre8zdF`
