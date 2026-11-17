# SCAN — "everything needs to be scanable" (Wi-Fi, BLE, Remote-ID, installer)

Branch `claude/project-thread-08f65f`, based on `fix/cl8-ship` (PR #24, the build on the device).
Source: owner device test 2026-11-17 (`plan/briefs/device-notes.md` RECON + General).

## Findings

| ID | Sev | Finding (device) | State | Fix | Regression tests (`tests/test_scan_live.py`) |
|---|---|---|---|---|---|
| SCAN-1 | High | RECON WIFI empty as shipped: `iw dev wlan0 scan passive` → `Operation not permitted (-1)` for user `dragon` (needs CAP_NET_ADMIN). | CLOSED | `palisade_qt/recon.py` `WifiScanWorker.step`: iw first; on any non-offline failure run `nmcli -t -f SSID,BSSID,CHAN,SIGNAL,SECURITY device wifi list --rescan auto ifname wlan0` (`wifisurvey.nmcli_scan_argv/parse_nmcli/nm_security`). Row carries `path`; page label + chip say **ACTIVE (NetworkManager probes)**, never passive. NM SIGNAL shown as `%` (NM quality), never as dBm. Both failing → `WIFI SCAN FAILED — iw: … · nmcli: …`. | `test_scan1_*` (10) |
| SCAN-2 | High | RECON BLE: "BLE NOT IMPLEMENTED" / "bleak is not installed" (E4 stub). | CLOSED | `BleScanWorker` rewritten: bleak (BlueZ D-Bus, `scanning_mode="active"`) when importable, else `bluetoothctl --timeout 30 scan on` (`blescan.parse_bluetoothctl_line/_devices`). Table (address, name, vendor, kind, RSSI) re-emitted every 1 s; devices age out after 60 s; cached-but-unheard BlueZ devices are not shown. Listen only: no connect / pair / trust / GATT. Paused (window ends at once) when the BLE sub-tab is off screen. Adapter off / no adapter / D-Bus refusal → `BLE SCAN FAILED — <reason>`, retry every 15 s. Bus decode once per device, not per second. | `test_scan2_*` (25) |
| SCAN-3 | Med | Owner saw "requires BlueZ … passive scanning" although bluez is installed. It is bleak's refusal from **ATLAS Remote-ID** (`RidSource`, passive mode): `passive scanning on Linux requires BlueZ >= 5.56 with --experimental enabled`. Debian's `bluetoothd` runs without `--experimental`, so BlueZ has no advertisement-monitor API. The check was right about the API, wrong to blame the package. | CLOSED (in-app) | `palisade_qt/atlas.py` `RidSource._scan_ble`: on that specific refusal, fall back to BlueZ's normal (active) discovery, which also hears ODID broadcasts; `mode="active"` and one note via the fault channel: "Remote-ID: ACTIVE BLE scan … needs bluetoothd --experimental (owner decision)". Any other bleak error still faults. | `test_scan3_*` (3) |
| SCAN-4 | Med | PRISM sweep / PROWL scan need `rtl_power` / `rtl_fm`; the installer only *checked* for them at the end (install memo gap). | CLOSED | `install_head.sh`: `rtl-sdr` added to both apt lists (safe_apt: skipped if apt would remove/change anything). | `test_scan4_installer_installs_the_scan_tools` |
| doctor | — | No way to see which scan path is live. | CLOSED | `doctor.chk_wifi_scan` (passive iw if root or iw has cap_net_admin; else NM ACTIVE, warn; else fail) and `doctor.chk_ble_scan` (backend, adapter, powered, `--experimental`). Report only; fixes are text. | `test_scan1_doctor_wifi_paths`, `test_scan2_doctor_ble`, `test_scan3_doctor_names_the_experimental_flag`, `test_doctor_lists_both_scan_checks` |

Superseded test: `test_cl4_honest.py::test_e4_ble_with_bleak_says_not_implemented` → `test_e4_ble_no_backend_says_what_is_missing` (the feature is now wired; E4's rule — never blame hardware for an unwired feature — still holds for the no-backend case).

## Honesty of the labels (owner should know)
- NetworkManager and BlueZ discovery are **active** scans (probe requests / scan requests). No
  deauth, no injection, no connect, no pair. The UI says ACTIVE on both paths.
- RSSI may show `—` for a device until BlueZ reports an RSSI change (bluetoothctl prints the
  first RSSI only inside the NEW event). The bleak path always has RSSI.

## System changes NOT made (owner decisions)
1. **Passive Wi-Fi** (beacons only, no probes): `sudo setcap cap_net_admin+ep /usr/sbin/iw`.
   Effect: RECON uses `iw scan passive` again. Side effect: every local user can reconfigure
   Wi-Fi interfaces through `iw` (monitor mode, interface type, regdomain requests).
2. **Passive Remote-ID**: run `bluetoothd --experimental` (systemd override of
   `bluetooth.service` ExecStart). Effect: ATLAS Remote-ID scans passively (no scan requests).
   Side effect: enables other experimental BlueZ D-Bus interfaces.
Neither is needed for scans to work; both only make them passive.

## Inventory — other passive scan surfaces still placeholders on the device (not in this PR)
| Screen | Surface | Shows on device | Needs |
|---|---|---|---|
| SWEEP | bugsweep, jammer | NOT IMPLEMENTED (no live feed) | `rtl_power` sweep through the radio arbiter (SDR lease, liveness watchdog) |
| SWEEP | gnss jamming | NOT IMPLEMENTED | gpsd SKY C/N0 feed (gpsd is running on the device) |
| SWEEP | imsicatch | NOT IMPLEMENTED | a cellular modem cell feed (no modem fitted) |
| FORGE | SENSORS (rtl_433) | NOT IMPLEMENTED | rtl_433 JSON stream through the radio arbiter |
| FORGE | CAN | NO DEVICE / NOT IMPLEMENTED | SocketCAN hardware (none fitted) |
| RECON › RF | RFFINGER | static note | IQ capture feed from PRISM |
| RECON › RF | SCOUT | static note | `scout.py` already has nmcli + nmap own-subnet discovery; not wired into Qt |
PRISM (rtl_power sweep), PROWL (rtl_fm scan/FM/NWR), BABEL, ATLAS ADS-B are live (STANDBY only when the binary is missing — SCAN-4 installs it).
Recommended next cluster: SWEEP gnss (gpsd) + SCOUT (no SDR, small), then SDR-backed SWEEP/SENSORS together with the CL8 decoder-liveness follow-up.

## Suite / lint
- `pyflakes palisade_qt/recon.py palisade_qt/atlas.py blescan.py wifisurvey.py tests/test_scan_live.py`: clean (doctor.py: 4 pre-existing unused-import warnings, unchanged).
- Targeted: `tests/test_scan_live.py tests/test_cl4_honest.py tests/test_wifisurvey.py tests/test_blescan.py` pass.
- Full suite (8bc2dad, py3.13, PySide6 6.8.2.1): `4 failed, 1677 passed, 6 skipped, 7 errors`.
  Baseline: `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`,
  7 `test_shell` errors (no tkinter). `test_cl1_screen::test_up_down_drive_the_list_and_the_detail_follows`
  is flaky on `fix/cl8-ship` too (1 of 3 runs failed there, 3/3 passed here: PROWL demo rows reorder
  between keypresses). New and fixed: `test_cl2_gates::test_one_gate_no_spawn_or_device_write_outside_the_executor`
  flagged the bluetoothctl `Popen`; added a justified SPAWN_ALLOWLIST entry (fixed argv, listen only,
  killed on stop) — `test_cl2_gates -k one_gate` 2 passed.

## Renders (1280×720, live, dark + sun)
`plan/briefs/SCAN-evidence/recon-wifi-nmcli-{dark,sun}.png`, `recon-ble-live-{dark,sun}.png` (script `render.py` beside them). ReconApp minimum width 969 px (was 1139 with the first label draft).

## Models
Implementation, tests, report: Opus (this thread). Cold audit: Opus subagent (RA-SCAN).

## SCAN-fix (RA-SCAN: DO NOT MERGE → fixes)
| RA-SCAN | Sev | Fix | Regression test |
|---|---|---|---|
| N1 | High | Wi-Fi label starts neutral ("scan path not known yet") and is set only from the path a scan actually used; a failure resets it. | `test_ra_n1_wifi_label_is_neutral_until_a_path_reports` |
| N2 | High | `recon._run_scan` spawns in its own process group and, given the worker, polls interruptibly; stop or timeout kills the group. Wi-Fi iw + nmcli pass the worker. `ReconApp.stop` stops all workers, then `stop_worker` (joins or parks + alerts). | `test_ra_n2_run_scan_is_killed_on_stop`, `test_ra_n2_closing_recon_mid_nmcli_scan_joins_and_kills`, `test_ra_n2_a_worker_that_will_not_join_is_parked_not_dropped` |
| N2b / N7 | Med / Low | bluetoothctl path: bounded, interruptible `bluetoothctl show` preflight (4 s) names "bluetoothd is not answering" / "no Bluetooth adapter" / "powered off"; `devices` the same way. | `test_ra_n2b_n7_bluetoothd_down_is_named_and_stop_is_prompt`, `test_ra_n2b_powered_off_from_show` |
| N3 | Med | bleak `start()` polled every 0.1 s for stop, abandoned after 10 s with "BlueZ did not answer start"; `stop()` bounded to 2 s. | `test_ra_n3_bleak_start_hang_times_out_with_a_reason`, `test_ra_n3_bleak_hang_never_blocks_stop` |
| N4 | Med | Remote-ID active fallback goes out as a status note (`rid_note` → warn chip), not an error/fault. | `test_scan3_remote_id_falls_back_to_active_when_bluez_has_no_monitor` (asserts no fault) |
| N5 | Low | nmcli output that parses to nothing but is not empty → SCAN FAILED "output not understood"; empty output stays "no access points heard". | `test_ra_n5_unreadable_nmcli_output_is_a_failure` |
| N6 | Low | A bluetoothctl window that ends in < 2 s having heard nothing is a failure; any short window sleeps RETRY_MS before the next. | `test_ra_n6_instant_exit_never_storms` |
| N8 | Med | doctor BLE: a timed-out or controller-less `bluetoothctl show` is a failure, not all-clear. | `test_ra_n8_doctor_bluetoothd_down_is_not_all_clear` |
| N9 | Low | doctor Wi-Fi ignores the doctor's own euid (the app runs as the desktop user): passive only when iw has cap_net_admin. | `test_scan1_doctor_wifi_paths` |
| N10 | Low | Allowlist + BLE label + doctor wording: "active discovery (scan requests), no connect/pair" (no "listen only"/"passive"). The status chip is kept per sub-tab (AP count on WIFI, BLE count on BLE, none on NET/RF). | `test_ra_n10_chip_belongs_to_the_tab_on_screen_and_labels_are_honest` |
| N11 | Low | Renders force-added (`*.png` is gitignored). | — |
