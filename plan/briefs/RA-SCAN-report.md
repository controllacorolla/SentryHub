# RA-SCAN: cold audit of SCAN (live Wi-Fi, BLE and Remote-ID scans)

Auditor: Opus subagent, fresh context. Audited head **c2448c9** on `claude/project-thread-08f65f`
(diff against `origin/fix/cl8-ship`). Probes were run against fake `iw`, `nmcli` and
`bluetoothctl` binaries on PATH and a fake `bleak` module, with `recon._offscreen` patched off.
Probe scripts are not committed; each PoC is described inline so it can be re-run.

## Verdict table

| ID | State | Evidence | Test |
|---|---|---|---|
| SCAN-1 Wi-Fi nmcli fallback | **PARTIAL** | The path choice is right. iw refused, then nmcli; iw missing, then nmcli; both refused gives `WIFI SCAN FAILED — iw: exit 255 — … · nmcli: exit 8 — …`, with both reasons; neither installed gives STANDBY. Terse escapes `\:` and `\\`, non-ASCII SSIDs and hidden SSIDs all parse. NM's % is shown as `72%` in the SIG column and never as dBm. The bus `decode` carries no signal value. The argv is only `nmcli -t -f … device wifi list --rescan auto ifname wlan0`, with no settings input and no shell. **Open:** N1 (label says passive before the first scan), N2 (close leaves the thread and nmcli running), N5 (rc 0 with an empty list shows "0 AP" and no reason). | `test_scan1_*` (pass) |
| SCAN-2 BLE bleak / bluetoothctl | **PARTIAL** | No connect, pair, trust or GATT anywhere in the diff. The argv is `bluetoothctl --timeout N scan on`. Colour codes, the `\001/\002` readline markers, `[bluetooth]#` and `RSSI: 0x.. (-n)` all parse. Cached `[NEW]` lines before `Discovery started` are not counted as heard. Name-only and `Connected:` CHG lines are not counted as heard. NotAuthorized and NotReady give `BLE SCAN FAILED — <reason>` with a 15 s retry. A child that ignores SIGTERM is killpg'd 9 within 2.0 s and no process is left. Pause ends the window. Bus decodes go out once per address; a 20 000-device flood was handled (one decode each, table emits 1/s). The bleak callback and the drain run on the same loop thread, and the bluetoothctl reader uses a lock. bluez master `shell.c` calls `setlinebuf(stdout)`, so rows arrive live through the pipe. **Open:** N2b and N3 (stop can exceed the join budget), N6 (retry storm when bluetoothctl exits quickly), N7 (weak reason when bluetoothd is down). | `test_scan2_*` (pass) |
| SCAN-3 ATLAS Remote-ID active fallback | **CLOSED** (with N4) | `passive_unsupported` matches only bleak's `passive scanning on Linux requires BlueZ >= 5.56 with --experimental …`, which is raised from `RegisterMonitor` UnknownMethod (bleak 3.1.0 `manager.py:798`). The `or_patterns` error is raised in `__init__` and reaches the outer `except`, so it faults and does not fall back. Other start errors re-raise and fault. `stop()` → `while self._on` exits → `await scanner.stop()` stops the active scanner. The note says ACTIVE. | `test_scan3_*` |
| SCAN-4 installer rtl-sdr | **CLOSED** | `rtl-sdr` was added to both lists in `install_head.sh`, and the install loop uses `safe_apt` only. | `test_scan4_installer_installs_the_scan_tools` |
| doctor `chk_wifi_scan` / `chk_ble_scan` | **PARTIAL** | Report only: `fix` is text, nothing is executed, and no system change is made. Root, setcap (`getcap` on the realpath), no NM, no adapter, powered off and NotAuthorized are all reported honestly. **Open:** N8 (bluetoothd down gives a false all-clear), N9 (root euid). | `test_scan1_doctor_wifi_paths`, `test_scan2_doctor_ble`, `test_scan3_doctor_names_the_experimental_flag` |
| c2448c9 SPAWN_ALLOWLIST entry | **OK** (N10) | It is keyed to `(recon.py, _scan_bluetoothctl, subprocess.Popen)`, and that Popen's argv is fixed (`blescan.bluetoothctl_scan_argv`). Gates (engagement, opprofile, txguard) are untouched by the branch. | `test_cl2_gates -k one_gate` passes |

## New findings

**N1 · High: dishonest label (blocker).** `ReconApp._build_wifi` sets
`self.wifi_mode = micro(WIFI_MODE["iw"])` unconditionally. PoC: `ReconApp(demo=False).wifi_mode.text()` →
`WIFISURVEY · PASSIVE (IW, BEACONS ONLY) · NO DEAUTH/INJECT`. On the device (user `dragon`, no
CAP_NET_ADMIN) the first scan is always the nmcli **active** scan. The page reads "passive"
until that scan returns, which can take up to the 25 s timeout. If both paths fail it reads
"passive" next to SCAN FAILED. This is an active scan labelled passive. Fix: start neutral
("scan path: probing…"), or pick the label up front with the same logic as `doctor.chk_wifi_scan`.
It needs a test that asserts the live label before any row arrives.

**N2 · High: scan leaves a thread and a process behind on close (blocker).** `_run_scan` uses an
uninterruptible `subprocess.run(timeout=25)` for nmcli. `ReconApp.stop()` (recon.py ~777) does
`w.wait(3000)` and then `_retain(w)`, with no park, no alert and no kill. PoC: fake `nmcli` that
sleeps 8 s, open RECON live, `p.stop()` after 1 s. `stop()` returns after 3.00 s with
`WifiScanWorker` still `isRunning()` and the nmcli PID still alive, and `app.parked()` is empty.
With a 60 s hang, the worker joined only after about 24 s. An NM rescan takes several seconds on
real hardware, so closing RECON or the hub mid-scan hits this regularly. The GUI also blocks 3 s
per stuck worker. The iw path had the same shape before this branch (12 s), but on the device iw
failed in milliseconds. nmcli makes it the normal path. Fix: Popen + `self.poll_process()`, killpg
on stop. Use the A2 `stop_worker` park path rather than a silent wait.
- **N2b · Medium (same class):** `_scan_bluetoothctl` first runs `_run_scan(["bluetoothctl","devices"], timeout=5)`.
  With bluetoothd down, bluetoothctl waits for the daemon indefinitely. PoC: a fake that sleeps
  30 s on `devices` → `stop()` gives `joined=False` after 3.00 s, with the process still alive.
  This only applies when bleak is absent.

**N3 · Medium: bleak start/stop have no timeout.** Fake `BleakScanner.start()` (or `stop()`) that
awaits 120 s → `w.stop(); w.wait(3000)` gives False. The window/stop check only runs after
`start()` returns. Wrap both in `asyncio.wait_for(…, 10)`. bleak is the device's primary backend.

**N4 · Medium: honest note, wrong channel.** `RidSource` sends `ACTIVE_NOTE` through `on_fault` →
`AtlasApp.error.emit` → `on_error`. That writes `sessionlog.record("error", …)` and
`set_chip("fault", …, state="alert")`, so a working active scan shows as a red fault. That is
the "red ▲ LIVE fault" the owner already reported. The text is honest, but the severity is not.
Route it as a status or mode chip.

**N5 · Low: "0 AP" without a reason.** If nmcli exits 0 with empty or unparseable output (for example
the Wi-Fi radio is off or the device is unavailable), the page shows `0 AP · NM ACTIVE` with
"no access points heard" and drops the iw reason (`iw_refused` is emitted but never shown).
The same happens for iw rc 0 with garbage output.

**N6 · Low: retry storm.** If `bluetoothctl scan on` exits right away with rc 0 (or after
`Discovery started` with any rc), `step()` returns None and the worker re-runs every 500 ms.
PoC: 5 `scan on` spawns, plus 5 `devices` calls, in 3 s, with no status. Treat "window ended
early with nothing heard" as a failure, or apply `RETRY_MS`.

**N7 · Low: weak reason when bluetoothd is down (bluetoothctl path).** In non-interactive mode, bluez
`shell.c` drops every `bt_shell_printf` until `client_ready` attaches stdin. So "Waiting to connect
to bluetoothd" is never printed, and the `_DEV`/`!` parse for it is dead code. The user sees
"no BLE devices heard yet" for 30 s and then `bluetoothctl exit 1`. If the worker's window timer
fires first (rc −15), nothing is shown at all.

**N8 · Medium: doctor false all-clear.** In `chk_ble_scan`, when bluetoothd is down `bluetoothctl show`
times out (`(1, "…timed out")`) and `pgrep` gives rc 1. The check then returns
`(True, "bleak on hci0 (active discovery, listen only)", "")`. Reproduced with stub `run`/`which`.
It should report "bluetoothd not running".

**N9 · Low: doctor run as root.** `chk_wifi_scan` with euid 0 says "passive scan (iw)", but the app runs
as `dragon` and will use the nmcli active path. Report the path for the desktop user.

**N10 · Low: allowlist wording.** The new entry and the existing `_run_scan` entry describe "listen
only / passive survey commands / no target contact". `_run_scan` now also runs the active NM
probe scan, and BlueZ discovery sends SCAN_REQs. Reword them to "active discovery, no connect".
The BLE page label "active discovery · listen only" has the same mixed wording. Related: the
shared `sdr` chip still shows `4 AP · NM ACTIVE` on the BLE tab (seen in the render).

**N11 · Low (report hygiene):** SCAN-report.md cites `plan/briefs/SCAN-evidence/*.png`, but `*.png`
is gitignored, so only `render.py` is on the branch. I re-rendered at 1280×720 (dark and sun);
the layout is fine apart from N10's chip.

## Suite
- `tests/test_scan_live.py`: 52 passed. At c2448c9, `test_cl2_gates.py` + `test_scan_live.py` +
  `test_cl4_honest.py`: 194 passed.
- Full suite, run once (8bc2dad, py3.13, PySide6 6.8.2.1, offscreen + xvfb):
  `3 failed, 1678 passed, 6 skipped, 7 errors`. The failures are the 2 known baselines
  (`test_audit_tiles::test_undecodable_tile_is_marked_failed`,
  `test_hwlab::test_doctor_hwbench_check`), the 7 `test_shell` errors (no tkinter), and
  `test_cl2_gates::test_one_gate_…`. That last one is fixed by c2448c9, which changes only a
  test and the report, and it passes there. No other regressions.
- pyflakes on the touched files: clean, apart from 4 doctor.py unused imports that were already there.

## Verdict
Two blocker classes from the brief remain. A live active scan is labelled passive (N1). Closing
RECON during a scan leaves the worker QThread and the nmcli process running past the join budget,
silently (N2, N2b, N3). Fix N1, N2/N2b/N3 with regression tests, ideally with N4 and N8, then
re-audit.

DO NOT MERGE
