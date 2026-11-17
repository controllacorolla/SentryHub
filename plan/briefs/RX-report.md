# RX — RECON NET (nmap) + RECON Wi-Fi execution (v0.1 pull-forward)

Owner decision 2026-11-17 (Dalton, "yes"): pull active-tool execution for RECON NET and RECON
Wi-Fi forward from CL6/v0.2 into v0.1. Scope narrowed to NET + Wi-Fi; BLE, PASSAUDIT and FORGE
stay authorize-only (v0.2). Feature-gaps item 1.

Branch `claude/project-thread-st3z1x` (off main 01afe7b). PR #24 (fix/cl8-ship) has not merged
yet; merge main into this branch when it does (no shared hunks: CL8 touches recon.py lines 1-6 only).

## What changed

| # | Change | File | Test |
|---|---|---|---|
| RX1 | Authorized NETPENT / WIFIPENT tickets now run: the card hands the ticket to `executor.start()` through a new `RunPane` (output pane: streamed output, ANSI stripped, real exit code, STOP). Before: "nothing is spawned here". | `palisade_qt/runpane.py` (new), `palisade_qt/recon.py` GatedTool `_authorize`, `_net_page`, `_wifi_page` | `test_rx_in_scope_nmap_runs_streams_output_and_records_spawn_and_exit`, `test_rx_a_failing_tool_shows_its_real_exit_code`, `test_rx_wifi_handshake_runs_with_the_card_inputs_and_a_capture_path_under_data` |
| RX2 | Out-of-scope target / no engagement / ended engagement: refused with nothing spawned. | unchanged gate; tests only | `test_rx_out_of_scope_nmap_target_is_refused_and_nothing_is_spawned`, `test_rx_out_of_scope_bssid_is_refused_and_nothing_is_spawned`, `test_rx_without_an_engagement_nothing_is_spawned`, `test_rx_a_ticket_whose_engagement_ended_before_run_is_refused_at_spawn` |
| RX3 | END / PANIC / STOP / closing RECON kill the process group; kill + exit recorded in the engagement chain before `engagement.close`. | `recon.py` `stop()`; executor/engagement unchanged | `test_rx_end_kills_…`, `test_rx_panic_kills_…` (real hub PANIC), `test_rx_stop_button_kills_and_records_it`, `test_rx_closing_recon_kills_the_running_tool` |
| RX4 | Unprivileged portscan uses `-sT` (connect) instead of `-sS`, which nmap refuses without root. `syn=` override kept. | `netpent.py` `prepare(syn=None)`, `_is_root()` | `test_rx_unprivileged_portscan_is_a_connect_scan`; `test_netpent.py` now passes `syn=True` explicitly (same assertion, root-independent) |
| RX5 | wifipent refuses an interface name that is not one (leading `-`, path, space, empty) and a capture path starting with `-` — both are argv tokens now actually executed. | `wifipent.py` `prepare` | `test_rx_wifi_iface_that_looks_like_an_option_is_refused_by_the_engine` |
| RX6 | Missing binary: not spawned, ticket not redeemed, pane says NOT INSTALLED (no phantom spawn in the trail). | `runpane.py` `run` | `test_rx_a_missing_tool_is_not_spawned_and_says_so` |
| RX7 | Wi-Fi card: IFACE (defaults to an interface already in monitor mode, else `wlan0mon`), CH, CLIENT fields; a survey row click fills BSSID + channel; honest "NO MONITOR-MODE INTERFACE" note. Captures go to `<DATA>/captures/wifi-<action>-<UTC>`. | `recon.py` | `test_rx_wifi_handshake_…`, `test_rx_wifi_deauth_still_needs_a_client_and_the_tx_gate` |
| RX8 | One process per card; action buttons disabled while it runs. | `recon.py` GatedTool.refresh | `test_rx_one_process_per_card` |
| RX9 | Installer installs `arp-scan` (named in `netpent.ALLOWED_PROGRAMS`), `tcpdump`, `nbtscan`, `netdiscover` (coordinator scope addition). `tshark` left out: its debconf question cannot be answered unattended; tcpdump covers pcap. | `install_head.sh` | built installer `bash -n` OK |
| — | BLEPENT / PASSAUDIT unchanged (authorize-only, text now says execution is v0.2). | `recon.py` | `test_rx_blepent_and_passaudit_stay_authorize_only` |
| — | Offscreen seam: without a test spawner, RECON never spawns under offscreen (same seam as BENCH). | `recon.py` `_spawner` | `test_rx_offscreen_default_never_spawns` |

## Gate-adjacent changes, explained

- **No gate code changed.** `engagement.py`, `executor.py`, `chain.py`, `txguard.py`, `rfemit.py`,
  `opprofile.py` are untouched. RECON calls the same `prepare()` → `engagement.issue()` → executor
  ticket path BENCH uses; the executor re-runs the engagement recheck at redeem and on every sweep.
- **Where the scope refusal happens:** in the engine (`netpent.prepare` → `engagement.pin_host` /
  `engagement.issue` → `check`), before a ticket exists. The UI cannot reach `executor.start` without
  a ticket, and the executor refuses any ticket it did not issue or whose argv was altered.
- **N16 orphan rule** applies unchanged: RECON processes are registered executor Handles in the hub
  process, so END's executor sweep kills them (`kill` reason "gate closed: …", then `exit`), and
  `engagement._settle_tickets` handles any unreported ticket by pid + start time (spawn records
  `pstart`; checked by the spawn test).
- `netpent.prepare(syn=None)`: only chooses `-sS` vs `-sT`; the target / scope path is identical.
- `wifipent.prepare`: adds two refusals (iface, capture path); it never widens what is allowed.

## What stays dead on the device (honest)

- **Wi-Fi active tools cannot run on the uConsole as installed.** The CM5 onboard radio
  (brcmfmac) has no monitor mode, and airodump-ng / hcxdumptool / aireplay-ng need root or
  `cap_net_raw,cap_net_admin`. PALISADE does neither (no system changes). The card now says so
  ("NO MONITOR-MODE INTERFACE …"), refuses to authorize when the chosen interface is absent, and a
  tool that fails shows its real exit code and error. Needs: a monitor-capable USB adapter, and an
  owner decision on granting capabilities to the capture tools (a system change).
- aircrack-ng / hcxdumptool are not in the installer (coordinator: leave for now).
- **NET works unprivileged** for discover (`-sn`), portscan (`-sT`) and services (`-sV`).
  arp-scan is installed but no RECON action uses it yet (ALLOWED, not wired; needs root anyway).

## Flag for the owner (not resolved here)

- **Deauth guardrail conflict.** `wifipent.py` authorizes a targeted `aireplay-ng --deauth`
  (capped at 10 frames, one in-scope AP + one in-scope client, txguard armed + unlocked). Project
  rules elsewhere forbid deauth/jamming. RX does not change this: deauth runs only through the
  existing gates, and on this device it cannot run anyway (no monitor interface). Dalton has been
  asked to decide; until then the DEAUTH button behaves as the engine already allowed.

## Renders (1280×720, dark, live, engagement open)

`plan/briefs/rx/before-recon-net.png`, `after-recon-net.png` (nmap output in the pane, DONE · exit 0),
`before-recon-wifi.png`, `after-recon-wifi.png` (IFACE/CH/CLIENT, monitor note, output pane).

## Suite

Full suite at 6ac1b89 (PySide6 6.8.2.1, Python 3.13, xvfb offscreen):
`4 failed, 1506 passed, 7 skipped, 7 errors in 696.56s`.
- Baseline (same on main): `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
  `test_hwlab::test_doctor_hwbench_check`, 7 `test_shell.py` errors (no tkinter).
- `test_cl1_screen::test_up_down_drive_the_list_and_the_detail_follows`: order-dependent; passes
  alone and in a full `tests/test_cl1_screen.py` run (51 passed). Not touched by RX.
- `test_palisade_qt::test_recon_gate_authorizes_in_scope_denies_out_of_scope`: **RX regression,
  fixed** in the next commit: the card again shows the authorized command (`$ airodump-ng --bssid …`)
  above RUNNING / NOT RUN, so the G5 assertion holds unchanged. Re-run: `tests/test_palisade_qt.py`
  + `tests/test_rx_recon_exec.py` 139 passed.
pyflakes: clean on every touched file.
