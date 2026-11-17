# RA-SCANb: cold re-audit of SCAN-fix (live Wi-Fi, BLE and Remote-ID scans)

Auditor: Opus subagent, fresh context. Audited head **3f1f3f7** on `claude/project-thread-08f65f`
(diff against `origin/fix/cl8-ship`; the SCAN-fix delta is `c4c888f..3f1f3f7`). Probes used fake
`iw`, `nmcli` and `bluetoothctl` binaries on PATH (each logs its PID and argv so orphans can be
checked with `kill(pid, 0)`), a fake `bleak` module, and `recon._offscreen` patched off. Probe
scripts are not committed; each PoC is described inline so it can be re-run.

## RA-SCAN round-1 findings

| ID | State | Evidence (PoC against 3f1f3f7) | Test |
|---|---|---|---|
| N1 dishonest Wi-Fi label | **CLOSED** | `ReconApp(demo=False).wifi_mode.text()` gives `WIFISURVEY · SCAN PATH NOT KNOWN YET · NO DEAUTH/INJECT` (recon.py:46, :720). It stays neutral while the nmcli scan runs (checked at 1 s into a 60 s hang). It becomes `ACTIVE scan (NetworkManager probes)` only once a row arrives with `path=nmcli`. A double failure resets it to neutral (recon.py:255, :837). It never reads "passive" unless iw itself returned rc 0. | `test_ra_n1_wifi_label_is_neutral_until_a_path_reports` |
| N2 thread + nmcli left on close | **CLOSED** | `_run_scan` now uses Popen with `start_new_session=True`, `worker.poll_process` (50 ms), and `_kill_group` (TERM, then KILL after 1 s) (recon.py:65-117). `ReconApp.stop` stops every worker first, then calls `stop_worker` (join, or park and alert) (recon.py:893-901). PoC: iw refused, nmcli `sleep 60`, `p.stop()` at 1 s returns in 0.00 s with no worker running, 0 parked and the nmcli PID gone. With an nmcli that ignores SIGTERM it takes 1.00 s, with the same result. iw hanging: 0.00 s, PID gone. | `test_ra_n2_run_scan_is_killed_on_stop`, `test_ra_n2_closing_recon_mid_nmcli_scan_joins_and_kills`, `test_ra_n2_a_worker_that_will_not_join_is_parked_not_dropped` |
| N2b bluetoothctl `devices` hang | **CLOSED** | A bounded, interruptible `bluetoothctl show` preflight (4 s) and `devices` (4 s), both through `_run_scan(worker=self)` (recon.py:415-428). PoC: a fake that sleeps 120 s on every command. Stopped at 1.5 s, it joins in 0.00 s and the PID is gone. Left to run, it reports `BLE SCAN FAILED — bluetoothd is not answering`. | `test_ra_n2b_n7_bluetoothd_down_is_named_and_stop_is_prompt` |
| N3 bleak start/stop unbounded | **CLOSED** (thin margin, see B2) | `bounded()` polls stop every 0.1 s and gives up after 10 s. `stop()` is wrapped in `wait_for(…, 2)` (recon.py:366-400). PoC with the production constants: a `start()` that hangs joins 0.10 s after `stop()`, and so does a `start()` shielded against cancel. A `stop()` that hangs joins in 2.0–2.99 s, depending on where in the 1 s emit tick `stop()` lands. | `test_ra_n3_bleak_start_hang_times_out_with_a_reason`, `test_ra_n3_bleak_hang_never_blocks_stop` |
| N4 Remote-ID note as a red fault | **PARTIAL** | The fault channel is fixed. The active fallback calls `on_note`, then `status{"rid_note"}`, then `set_chip("rid", …, "warn")` (atlas.py:298-303, :691-692, :931-932). PoC: `AtlasApp.on_status({"rid_note": ACTIVE_NOTE})` gives a warn chip, and `sessionlog.record` is never called. **Remains:** the chip is never cleared. See B1. The AtlasApp routing (`on_status` → chip) has no test. Only `RidSource` is tested. | `test_scan3_remote_id_falls_back_to_active_when_bluez_has_no_monitor` (asserts `faults == []`) |
| N5 "0 AP" without a reason | **PARTIAL** | Non-empty nmcli output that parses to nothing now fails as `output not understood` (recon.py:243-248). **Remains:** (a) nmcli rc 0 with *empty* output, which is what an unavailable device or a radio that is off can produce, still shows `0 AP · NM ACTIVE` / "WATCHING — no access points heard", and `iw_refused` is still emitted but never shown. (b) iw rc 0 with garbage output (`print('hello world garbage')`) shows `0 AP` / "no access points heard" with the **passive** label. Low: it fails safe. | `test_ra_n5_unreadable_nmcli_output_is_a_failure` (covers the nmcli non-empty case only) |
| N6 retry storm | **CLOSED** | A window shorter than 2 s that was not asked for, with nothing heard, is a failure. Any short window sleeps `RETRY_MS` (recon.py:503-505, :535-537). PoC: `scan on` exits at once with rc 0. Over 6 s there is 1 `scan on` and the status is `BLE SCAN FAILED — bluetoothctl exited at once (exit 0)`. Residual (not a storm): a `scan on` that prints `Discovery started` and exits after 2.5 s re-runs about every 3 s, with `show` and `devices` each time and no status (4 windows in 12 s). | `test_ra_n6_instant_exit_never_storms` |
| N7 weak reason when bluetoothd is down | **CLOSED** | The preflight names the problem: `bluetoothd is not answering` (show timed out), `no Bluetooth adapter` (`No default controller available`), `adapter is powered off`. PoC: all three reproduced with fakes. NotAuthorized on `scan on` still reads `not authorized by BlueZ (D-Bus policy)`. | `test_ra_n2b_n7_…`, `test_ra_n2b_powered_off_from_show` |
| N8 doctor false all-clear | **PARTIAL** | With bluetoothctl present: show timed out gives `(False, "bluetoothd is not answering")`, and no controller gives `(False, "BlueZ reports no controller …")` (doctor.py:549-554). **Remains:** bleak installed, no `bluetoothctl` on PATH (so BlueZ is not installed) and `pgrep bluetoothd` rc 1 gives `(True, "bleak on hci0 (active discovery, no connect/pair)", "")`, a false all-clear. The installer ships bluez, so this is Low on the target. A `bluetoothctl show` that fails for any other reason (e.g. `Permission denied`) is reported as "no controller". | `test_ra_n8_doctor_bluetoothd_down_is_not_all_clear` |
| N9 doctor as root | **CLOSED** | The euid shortcut is removed. The path is passive only if `getcap` on the realpath of iw shows `cap_net_admin` (doctor.py:504-510). PoC: euid 0 without the cap gives `ACTIVE scan via NetworkManager`. | `test_scan1_doctor_wifi_paths` (euid=0 case) |
| N10 allowlist / label wording / shared chip | **CLOSED** | The allowlist now reads "nmcli wifi list … no target contact; process group killed on stop" and "BlueZ active discovery: scan requests only, no connect/pair". `BLE_MODE = "BLESCAN · active discovery (scan requests) · no connect/pair"`, and doctor no longer says "listen only". The chip is kept per sub-tab (recon.py:818-842): rendered at 1280×720, WIFI shows `N AP · NM ACTIVE`, BLE shows `4 BLE`, and NET/RF show none. | `test_ra_n10_chip_belongs_to_the_tab_on_screen_and_labels_are_honest`, `test_cl2_gates::test_one_gate…` |
| N11 renders not on the branch | **CLOSED** | The four PNGs are force-added under `plan/briefs/SCAN-evidence/`. I re-rendered with `render.py` and the re-renders have the same file sizes as the committed PNGs. I also rendered the double-failure state (dark/light): the reason fills the table and the bottom row, and the label is neutral. | — (report hygiene) |

## SCAN-1..4 and doctor (whole cluster, fresh)

| Item | State | Evidence |
|---|---|---|
| SCAN-1 Wi-Fi | **CLOSED** (N5 residual Low) | iw refused gives nmcli; iw missing gives nmcli; both refused gives `WIFI SCAN FAILED — iw: exit 255 — command failed: Operation not permitted (-1) · nmcli: exit 8 — Error: …`; neither installed gives STANDBY with the apt hint. `\:` and `\\` escapes and non-ASCII (`Café ☕`) parse. NM's value shows as `72%` and is never shown or published as dBm. The argv is fixed, `nmcli -t -f SSID,BSSID,CHAN,SIGNAL,SECURITY device wifi list --rescan auto ifname wlan0` (no settings input, no shell, list only). The worst-case stop is 1 s (TERM ignored) against a 3 s join budget. |
| SCAN-2 BLE | **CLOSED** | No connect, pair, trust or GATT call anywhere in the diff. The argv is `bluetoothctl --timeout N scan on`. Colour-coded `[NEW]`/`[CHG]`, `RSSI: 0x… (-n)` and a cached `[NEW]` before `Discovery started` parse, and the cached device is never shown as heard (PoC: only `AA:BB:CC:00:00:01 Fitbit -58` is listed, and `…:09 Cached` is not). A `scan on` that ignores SIGTERM and has a grandchild that ignores SIGTERM: stop takes 2.0 s, the group is killpg'd 9, and there are 0 orphans. bleak callback and drain run on one loop thread, and the bluetoothctl reader runs under a lock. |
| SCAN-3 Remote-ID fallback | **CLOSED** (B1 open) | `passive_unsupported` matches only the bleak `passive scanning … requires BlueZ … --experimental` text. `NotReady` and other errors re-raise and fault (`test_scan3_other_bleak_errors_still_fault`). `stop()` makes `while self._on` exit and then `scanner.stop()` runs. The note says ACTIVE and names `--experimental` as an owner decision. |
| SCAN-4 installer | **CLOSED** | `rtl-sdr` is in both `for pkg` lists, and the install loop runs `safe_apt` only. |
| doctor chk_wifi_scan / chk_ble_scan | **CLOSED** (N8 residual Low) | The checks run only `getcap`, `nmcli -t -f RUNNING general`, `bluetoothctl show` and `pgrep -a bluetoothd`. Every "fix" is text, and nothing in it changes the system. Root, setcap, no NM, no adapter, powered off and Access denied are all reported honestly (PoC table in the probe). |
| Gates / system | **OK** | No change to `engagement.py`, `opprofile.py`, `txguard.py`, `palisade_qt/app.py`, `worker.py` or `kit/`. The SPAWN_ALLOWLIST keys moved to `_run_scan / subprocess.Popen` (fixed argvs only). The app makes no system change. |

## New findings

**B1 · Medium (fails safe): the Remote-ID "ACTIVE BLE scan" chip goes stale.** `AtlasApp.on_status`
sets `rid` once and nothing ever clears it. PoC: `p.on_status({"rid_note": ACTIVE_NOTE});
p._toggle("drone", True); p._toggle("drone", False)`. `page_status()["rid"]` still reads `Remote-ID:
ACTIVE BLE scan (scan requests) — …` after the DRONES layer is off and `RidSource` is stopped. The
chip claims an emitting scan that is no longer running. That is the safe direction, but the label
is still wrong. The chip text is also cut at 90 characters (`…bluetoothd --exp`). Fix: clear `rid`
when the DRONES layer goes off or the worker stops, and add a test of the AtlasApp routing. (This
also covers the missing N4 test.)

**B2 · Low: the bleak stop-hang path joins at the edge of the budget.** In the window loop,
`asyncio.sleep(EMIT_MS/1000)` (1 s) cannot be interrupted. After it, `wait_for(scanner.stop(), 2)`
runs. Measured worst case: 2.99 s against `JOIN_GRACE_MS = 3000`. On the CM5 this can tip into
`stop_worker`'s park and alert path. That path is not silent, and the thread ends a few ms later,
so this is not a blocker. Fix: sleep in 0.1 s steps that check stop, or `BLEAK_STOP_S = 1`. The test
only covers `BLEAK_STOP_S = 0.3`.

**B3 · Low: a cancelled bleak `start()` never gets `stop()`.** When `bounded()` cancels a hung
`start()` (on stop or after 10 s), `run()` returns without `scanner.stop()`. If BlueZ had already
accepted StartDiscovery, discovery ends only when bleak's D-Bus connection is collected. I could not
verify this without real BlueZ. Calling `stop()` (bounded) after a cancelled start would be the
honest close.

**B4 · Low: duplicate BSSIDs are counted twice.** If nmcli (or iw) lists one BSSID twice, the table
shows two rows and the chip says `4 AP` for 3 radios. The parsers do not de-duplicate (seen with
`MyNet:x / aa:bb:cc:00:00:01` at 72 % and 75 %). Keep the strongest row per BSSID.

**B5 · Low: no "scanning…" state.** For the whole first nmcli scan (up to 25 s) the WIFI table shows
the kit default "NO DATA YET — nothing has arrived on this feed" and the chip `SDR —`. That is
honest, but it reads like a dead feed. A "scanning (NetworkManager)…" empty state would help the
owner's "is it scanning?" question.

**B6 · Low: RidSource start is still unbounded (pre-existing, same class as N3).** `RidSource.stop()`
only clears `_on`. A `scanner.start()` that hangs (passive or the active fallback) leaves its daemon
`threading.Thread` waiting. If DRONES is toggled again, a second RidSource is created. No QThread is
involved, and this is outside the SCAN-fix delta, but N3's `bounded()` pattern applies here too.

**B7 · Low (doctor wording):** `chk_wifi_scan` says "NetworkManager not running" when `nmcli` is not
installed, and says "iw scan needs CAP_NET_ADMIN" when `getcap` is missing and the cap is simply
unknown.

## Suite
- `tests/test_scan_live.py`: **64 passed** (31.6 s).
- Full suite, run once (3f1f3f7, py3.13, PySide6 6.8.2.1, `QT_QPA_PLATFORM=offscreen xvfb-run -a`):
  `3 failed, 1690 passed, 6 skipped, 7 errors` (679.8 s). The failures are the 2 known baselines
  (`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`),
  the 7 `test_shell` errors (no tkinter), and `test_cl1_screen::test_up_down_drive_the_list_and_the_detail_follows`.
  That last one is PROWL demo key navigation, which the branch does not touch. It failed while another
  session's suite was running on the same host. Re-run on its own it passes, and the whole
  `test_cl1_screen.py` passes (51 passed), so it is a load-timing flake. Up 12 passes on round 1
  (1678 → 1690, the new SCAN-fix tests). No regression.
- pyflakes on the touched files (blescan, doctor, atlas, recon, wifisurvey, the three test files):
  clean, apart from the 4 unused imports in doctor.py that were already there (lines 313/326/331/348).

## Verdict
All blocker classes from round 1 are closed and pinned by tests. The live Wi-Fi label is
never "passive" for the nmcli path. Close, stop and pause end every scan within the join budget,
with the process group killed and no orphan or running QThread. The bleak hangs are bounded.
No gate or system change, and no new regression in the suite. What remains is fail-safe or hygiene:
B1 (stale ACTIVE chip, Medium), the N5/N8 residuals and B2–B7. Fold B1 into the next ATLAS pass.

MERGE
