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

## RX-fix (after RA-RX: DO NOT MERGE)

| ID | Sev | Fix | File | Test |
|---|---|---|---|---|
| H1 | High | nmap is only ever given address / network literals: `ip:`/`host:` prefixes stripped, an a-b range becomes its exact CIDR cover (each block re-checked in scope via `also=`), anything else refused; `-n` on every nmap command so nmap never resolves. | `netpent.py` `_literal_targets`, builders | `test_rx_h1_nmap_only_ever_gets_address_literals_and_never_resolves` (7 targets × 3 actions), `test_rx_h1_a_range_becomes_exactly_its_cidr_cover`, `test_rx_h1_out_of_scope_range_and_prefixed_targets_are_still_refused`; `test_netpent` exact argv now includes `-n` |
| M1 | Med | **Gate-adjacent (executor.py):** the reader takes at most `LINE_MAX` = 4096 chars per piece (`_lines()`), so a never-ending line cannot grow unbounded. Recording, kill and redeem logic untouched. RunPane: reader thread only appends to a bounded deque; the GUI drains it on the 200 ms poll; each line shown truncated to 1000 chars. | `executor.py`, `palisade_qt/runpane.py` | `test_rx_m1_an_endless_line_is_read_in_bounded_pieces`, `test_rx_m1_the_pane_batches_and_truncates_a_flood` |
| L1 | Low | Accepted: STOP/END block ~1 s on a SIGTERM-ignoring child (executor's existing grace; the 2 s END wait is an owner-accepted decision). | — | — |
| L2 | Low | Monitor-mode note re-read on WIFI tab show and before each action. | `recon.py` | `test_rx_l2_the_monitor_note_follows_the_adapter` |
| L3 | Low | Pane title/state spacing; CLIENT placeholder shortened. | `runpane.py`, `recon.py` | render |
| L4 | Low | Captures dir created only after the gate passed (`prepare_run`). | `recon.py` | `test_rx_l4_a_refused_capture_creates_no_directory` |
| Flag | Owner | DEAUTH: unchanged, still flagged for Dalton. | — | — |

RX-fix full suite at 2ffb2da: `3 failed, 1520 passed, 7 skipped, 7 errors in 674.75s` —
test_audit_tiles, test_hwlab doctor, 7 test_shell errors (baseline), and
test_cl1_screen::test_up_down_drive_the_list_and_the_detail_follows (order-dependent; passes in
its own file; RA-RX also saw it and attributed it to PROWL, untouched by RX).

## RX-fix2 (planner backcheck before Dalton's device test; after merging main @ c911825)

Real nmap 7.94 run here through the real RECON path (real executor spawner): discover / portscan /
services DONE · exit 0, chain `authorize → issue → spawn → exit` for each. The backcheck found:

| ID | Sev | Gap | Fix | Test |
|---|---|---|---|---|
| X1 | Med | Scan results lived only in the pane (lost on close; nothing in the evidence) | `netpent.prepare(out=)` adds `-oN <DATA>/captures/nmap-<action>-<UTC>.txt` (path in the chained argv); pane ends with `[results saved: …]` or `[results file NOT written: …]`; out path starting with `-` refused | `test_rx_fix2_scan_results_are_saved_…`, `…_wrote_no_results_says_so`, `…_out_path_cannot_be_an_option` |
| X2 | Med | RA-RXb N1: IPv6 without `-6` scanned nothing, said DONE | `-6` when every address is IPv6; a target mixing families refused, naming the addresses | `test_rx_fix2_ipv6_targets_get_dash_6`, `…_ipv4_targets_never_get_dash_6`, `…_dual_stack_name_is_refused_…` |
| X3 | Low | Single-word names (`router`, `localhost`) refused with a false "not a hostname" | Honest refusal: not looked up (search-domain dependent), use the IP or a full name | `test_rx_fix2_a_single_word_name_gets_an_honest_refusal` |
| X4 | Low | nmap exits 0 when it scanned nothing (`No targets were specified`) → pane said DONE | State `NOTHING SCANNED · exit 0` | `test_rx_fix2_nmap_that_scanned_nothing_is_not_done` |
| — | note | main's new `netpent.catalog_prepare` (#28 toolkit) still passes non-literal targets verbatim (the H1 pattern) | Not wired to any UI → no execution path; follow-up for whoever wires the catalog | — |
| — | note | RX's installer loop dropped: main's toolkit list already installs arp-scan/tcpdump/nbtscan/netdiscover | — | built installer `bash -n` OK |

RX-fix2 full suite at e3d9545 (+ NOTHING SCANNED test): `2 failed, 1829 passed, 7 skipped, 7 errors
in 919.70s` — test_audit_tiles, test_hwlab doctor, 7 test_shell errors (no tkinter): all baseline.

## RX-fix3 (after RA-RXc: MERGE with N4-N6)

| ID | Fix | Test |
|---|---|---|
| N4 Med | Results / capture paths get UTC time + 6-hex random suffix (`recon._unique`) — two runs in one second never share a file | `test_rx_n4_two_scans_in_one_second_never_share_a_results_file` |
| N5 Low | `netpent.prepare(out=)` accepts only a file directly in `<DATA>/captures` (realpath) | `test_rx_n5_results_path_must_be_in_the_captures_folder` |
| N6 Low | NOTHING SCANNED prints `[nothing scanned — no results in …]`, never "results saved"; `RunPane.saved` reset per run | `test_rx_n6_nothing_scanned_never_claims_results_saved` |
| RXb N2 Low | `_literal_targets` comment corrected (literals stop forward lookups; -n stops reverse) | — |
| N3 | Open (wording in engagement.py, a gate file) — follow-up | — |

## RX-fix4 — Wi-Fi select-and-act (device ask 2026-11-17: "select the Wi-Fi network and do what I want with it")

A new entry point in RECON › WIFI: select a network, then **ACT ON SELECTED ▾** (or right-click the
row) opens one menu for that BSSID. Every item routes through the SAME engagement gate as the
WIFIPENT card — no new ungated path.

| Item | Behaviour | File | Test |
|---|---|---|---|
| Header | SSID · BSSID · channel · signal · security of the selected AP (details), disabled | `recon._build_wifi_menu` | render |
| Port-scan the gateway | Enabled only when this BSSID is the associated AP (`iw dev … link`, seam) and a default gateway exists; runs on the NET card so the engine still scope-checks the gateway (out of scope → DENIED, nothing spawned) | `recon._associated_bssid/_default_gateway/_scan_gateway` | `…gateway_scan_only_when_associated`, `…runs_on_net_and_is_scope_checked`, `…out_of_scope_is_refused` |
| Capture WPA handshake / PMKID | Enabled only with an open, in-scope engagement AND a monitor-mode interface; otherwise greyed with the gate's own reason (`engagement.check`) or "no monitor-mode interface" | `recon._build_wifi_menu/_run_wifi_action` | `…greys_gated_items…no_engagement`, `…out_of_scope`, `…no_monitor_interface`, `…handshake_runs_through_the_gate` |
| Deauth a client… | Same gating; prompts for the client MAC; routes through the deauth gate (client-in-scope, no broadcast — and #30's group/self refusal once stacked) | `recon._deauth_prompt` | covered by the gated-grey tests |
| ACT button | Enabled only when a row is selected | `recon._wifi_pick` | `…act_button_enables_only_with_a_selection` |

8 tests in `tests/test_rx_recon_exec.py` (`-k "wifi_act or wifi_menu"`). Render:
`plan/briefs/rx/after-wifi-menu.png` (ACT ON SELECTED button; gated items greyed with reasons).

**NOT in scope here (owned by the UI thread "Polish the UI from device testing"):** RECON right-panel
font sizing, a collapsible panel, tile styling, and the module-number/legend/OPS items from Dalton's
device note. This change touches only the Wi-Fi action menu + its seams, not the panel layout, to
avoid colliding with that thread.
