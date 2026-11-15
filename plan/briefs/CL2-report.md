# CL2 — Gate integrity — implementer report

**Branch:** `fix/cl2-gates`, cut from `fix/cl1-screen-structure` @ `a716e2f`. PR #19 had not merged
(`origin/main` is still `e6184c6`), so the brief's fallback applied. No rebase was pre-empted.
**Commits:** code `02e1b16`, report `this commit` (see `git log fix/cl2-gates`). No PR opened.
**IDs:** G1 G2 G3 G4 G5 G8 G9 G10 G11 G12 G13 L1 S2 S3. G6 / G7 not touched; `evidence.py` unchanged.
The single evidence hook is `executor.record()` (`executor.py:39`), a no-op stub marked `# CL3`.

Verdicts below are the implementer's. They close nothing: the cold re-audit does.

## Method: PoC first

`tests/test_cl2_gates.py` was written before any fix and run on the branch tip `a716e2f`:
**67 failed, 6 passed** (`plan/briefs/CL2-evidence/before_tip_a716e2f.txt`). The 6 that passed are
the guards against over-correction: `SUITE_TX_LOCK=1` already locked, and the 5 explicitly falsy
values (`""`, `0`, `false`, `no`, `off`) must not lock. After the fix: **all pass**
(`plan/briefs/CL2-evidence/after.txt`, 73 there; 2 more tests were added later, also passing).

## Per finding

| ID | Verdict | Fix (file:line) | Regression test(s) — failed before → passed after |
|---|---|---|---|
| **G1** BENCH | CLOSED | `bench_app.py:35` 121.5 preset removed; `bench_app.py:140-160` reads the SAVED `tx_enabled` (`bench.saved_settings`, default off, `is True`), never forces it. `bench.py:85-150`: one chain `txguard.authorize("bench")` (arm + unlock + tx_enabled + ack + band); run in the executor as a registered process group (`start_transmit`), real exit code returned (`transmit`). UI button becomes STOP while keyed; disarm / PANIC kill it. Protected bands denied even conducted (`txguard.py:37`). | `test_g1_bench_checkbox_alone_does_not_enable_tx_poc`, `test_g1_bench_has_no_121_5_preset`, `test_g1_bench_conducted_protected_band_is_denied_strict_default`, `test_g1_bench_needs_arm_unlock_and_reports_real_exit_code`, `test_g1_bench_run_is_registered_and_stoppable`, `test_g1_bench_ui_reads_saved_settings_and_wording` |
| **G2** SERIAL | CLOSED | Device identified by USB VID:PID from sysfs (`flipper.py:66`, Flipper trusted only with "flipper" in the product string). One serial write path, `hwlab.gated_send` (`hwlab.py:261`) → `flipper.prepare_command` → `executor.write`, which logs every line sent to `serial_tx.jsonl` (`executor.py:295`). The Qt SERIAL tab (`forge.py:192`) and both Tk send sites (`hwlab.py` `send_text` / `do_send`) use it. ESP32 / slcan / unknown devices are read-only until an engagement names the device (`usb:vvvv:pppp` / `port:name`). | `test_g2_unknown_and_emitter_devices_are_read_only_until_engagement`, `test_g2_device_identified_by_usb_vid_pid`, `test_g2_qt_serial_tab_never_writes_ungated_poc`, `test_g2_every_sent_line_is_logged`, `test_g2_tk_hwlab_send_goes_through_the_gate` |
| **G3** classifier | CLOSED | Allowlist `flipper.py:24` (`READ_ALLOW` with an argument count per entry). Everything else is emit. Any control character (CR, LF, ETX …) → emit, and `prepare_command` refuses it outright, even with an engagement. | `test_g3_flipper_classifier_is_an_allowlist_poc` (every PDF PoC string), `test_g3_emit_pocs_refused_without_engagement`, `test_g3_cr_lf_refused_even_with_engagement`, `test_g3_allowlisted_read_passes_and_emit_is_label_only_with_engagement` |
| **G4** scope | CLOSED | Typed scope entries `engagement.py:151` (`parse_entry`) / `:228` (`parse_scope`): ip (address, strict network with prefix ≥ /8, `a-b` range), host (resolved and pinned at start), mac / OUI, can, pan, uid, device, label. Globs, bare `*`, a string scope, `/0`-style masks and malformed ranges are refused. Target check `engagement.py:315`: interval containment via `ipaddress`; a hostname is resolved and every address must be in scope. | `test_g4_glob_and_wildcard_scope_rejected_poc`, `test_g4_string_scope_does_not_become_characters_poc`, `test_g4_netpent_poc_targets_out_of_scope` (all PDF targets), `test_g4_ip_range_and_host_scope_entries` |
| **G5** binding | CLOSED (scope bound where possible; label-only stated where not) | Wi-Fi `wifipent.py:37-100`: PMKID capture gets `--filterlist_ap=<file> --filtermode=2`, and the filter file is part of the ticket (written by the executor). Deauth requires a client and scope-checks it; no broadcast form exists. CAN `canbus.py:201`: scope is interface + ID range. Zigbee `zigbee.py:36`: PAN @ channel (discover binds the channel). Proxmark `proxmark.py:59`: the card's UID is read back and compared before any active op; no read-back = refused. USB-HID, flash/JTAG, Flipper/serial, Z-Wave and passaudit labels report **"label-only authorization"** in the reason, `ticket.binding`, and the trail record. | `test_g5_pmkid_command_carries_the_bssid_filter_poc`, `test_g5_deauth_requires_and_scope_checks_the_client_poc`, `test_g5_can_scope_is_interface_plus_id_range`, `test_g5_zigbee_scope_is_pan_and_channel`, `test_g5_proxmark_reads_back_uid_before_write`, `test_g5_unbindable_tools_say_label_only` |
| **G8** one gate | CLOSED | `decide()` removed; band logic is the private `_decide` (`txguard.py:176`). One public chain, `authorize` (`txguard.py:355`), used by bench, replay, digimodes, loopback, `radio.TxRequest` and Meshtastic send (`mesh_dash.authorize_send`, `mesh_dash.py:48`). No service is exempt (`EXEMPT_SERVICES = ()`, consulted at `txguard.py` `authorize`). Unlock control: the new **TX panel** (`panels.py:177`), opened from the TX slot, the palette, or the shell, with ARM/DISARM and UNLOCK/LOCK calling `txguard.arm` / `unlock_session`. | `test_g8_decide_is_private_and_lora_never_bypasses_poc`, `test_g8_every_public_tx_entry_refuses_when_disarmed`, `test_g8_unlock_is_a_real_ui_control` |
| **G9** power / gain | CLOSED | `txguard.py:324` `gain_for_power` (conservative: assumes the HackRF's top +15 dBm at gain 47), `:334` `check_gain` (gain above the authorized power is clamped down; non-integer / non-finite / negative is denied). `authorize` rejects non-finite power, power below −60 dBm, non-finite or non-positive frequency, and sample rates outside 2–20 Msps. Replay and bench derive gain from the authorized power. | `test_g9_replay_gain_is_derived_and_clamped_poc` (`-x 47` / `-x 999` under the 10 dBm replay cap → clamped to 42), `test_g9_nonfinite_power_and_bad_sample_rate_denied` |
| **G10** fail-open | CLOSED | `tx_locked` requires `tx_enabled is True` (`txguard.py:165`). `env_locked` (`:157`) locks on any value except an explicit falsy one. Region-aware band tables `ISM_BY_REGION` (`:62`): 433.05–434.79 MHz is licence-free only in EU. In the US it classifies as amateur, which is checked first (`classify`, `:144`). Unknown or missing region → strict US table. | `test_g10_tx_enabled_must_be_exactly_true_poc`, `test_g10_any_truthy_tx_lock_locks_poc[*]`, `test_g10_falsy_tx_lock_does_not_lock[*]`, `test_g10_433_is_amateur_in_us_and_ism_elsewhere_poc` |
| **G11** capability | CLOSED | New `executor.py`. Tickets are immutable, single-use, expire after 120 s, and are bound to a SHA-256 of argv (or payload) plus files, held in the executor's own table (`_redeem`, `:144`). Only `txguard` / `engagement` / `flipper` may issue (`ISSUERS`, `:118`, runtime + static check). At spawn the executor re-runs the gate, starts the process in its own process group, registers it, streams its output and returns the exit code. While a process runs, every txguard / engagement change and a 0.25 s monitor re-check its gate and kill the group when it fails (END, disarm, expiry, hub state lost). All gated argv builders are private (`_replay_argv`, `_tx_argv`, `_cansend_argv` …). | `test_g11_ticket_is_single_use`, `test_g11_altered_argv_refused`, `test_g11_forged_ticket_refused`, `test_g11_expired_ticket_refused`, `test_g11_gate_rechecked_at_spawn`, `test_g11_end_engagement_kills_running_process`, `test_g11_disarm_kills_running_process`, `test_g11_exit_code_goes_to_the_cl3_record_hook`, `test_g11_argv_builders_are_private`, `test_g11_only_a_gate_may_issue_a_ticket` |
| **G12** UI follows engine | CLOSED | `txguard.subscribe` / `engagement.subscribe`; `chrome.GateSignals` (`chrome.py:27`) bridges them into one queued Qt signal. Subscribers: TX / ENGAGE slots (new words UNLOCKED, EXPIRED), FORGE engagement cards, the replay banner, RECON gated tools, BENCH, and the TX / ENGAGEMENT panels. The replay banner is **the engine's own `authorize()` answer** for its frequency (`forge.py:401`), so it cannot disagree with the engine. | `test_g12_engagement_and_txguard_emit_change_signals`, `test_g12_forge_cards_follow_end_without_a_manual_refresh_poc`, `test_g12_replay_banner_agrees_with_engine_poc` (all arm / unlock combos plus a refused band), `test_g12_topbar_tx_slot_is_driven_by_the_engine_not_a_poll` (poll timer stopped) |
| **G13** lifecycle | CLOSED | `engagement.start` (`:433`): refused while one is open (first and its trail kept). Expiry `ENGAGEMENT_HOURS_DEFAULT = 8`, configurable up to 24 h, enforced in `check()` and by the executor monitor. Operator = profile identity (`opprofile.operator_identity`); a different typed operator is refused, and no profile → refused. Panel: operator read-only from the profile, authorization **not** pre-filled (`panels.py:259`). | `test_g13_second_start_refused_first_kept_poc`, `test_g13_expired_engagement_denies`, `test_g13_expiry_is_configurable_but_bounded`, `test_g13_operator_comes_from_the_profile`, `test_g13_panel_operator_is_read_only_and_auth_not_prefilled` |
| **L1** one state | CLOSED (see "brief / audit got wrong" #1) | New `gatestate.py`. The Tk hub is the publisher (`hub.py:1031`); arm / unlock / engagement go to a 0600 session file in `$XDG_RUNTIME_DIR/uconsole-suite/`, republished on every engine change (kill switch and power auto-disarm included) and removed on exit (`hub.py:1410` + atexit). Children get `child_env()` (`hub.py:793`, `818`): bound to the file, plus `SUITE_TX_LOCK=1` whenever disarmed. A bound child cannot arm, unlock or open an engagement. A missing, foreign, world-writable or dead-hub file → STALE → denied. | `test_l1_child_sees_parent_arm_and_disarm`, `test_l1_real_child_process_follows_the_hub` (a real child process), `test_l1_stale_state_from_dead_hub_fails_closed`, `test_l1_tk_hub_kill_switch_and_power_disarm_publish` |
| **S2** Scout / devterm | CLOSED | `scout.scan_network` (`scout.py:121`): real netmask from `ip -o -4 addr` (`network_from_ip_addr`, never an assumed /24) → `netpent.prepare("survey")` → executor. Without nmap, the built-in connect scanner sits behind the same gate and its `ping` subprocess sweep is replaced by TCP probes of the authorized hosts. devterm: BLE connect, MQTT publish, SSH open and SSH run are gated (`devterm.py:123-150`); SSH run goes through an executor ticket. | `test_s2_scout_starts_no_scan_without_engagement_poc`, `test_s2_scout_uses_real_netmask_and_netpent_gate`, `test_s2_devterm_ble_mqtt_ssh_are_gated` |
| **S3** Tk USB-HID | PARTIAL (by design) | The false "sent" is fixed: `usbhid.run_payload` (`usbhid.py:94`) writes reports through an executor ticket one 8-byte report at a time and reports exactly what was written. "NOT SENT" covers no gadget, a failed write and 0 bytes accepted. **Retire-or-keep the Tk gated tools is the owner's decision** (open question 4). | `test_s3_usbhid_never_claims_sent_without_writes_poc`, `test_s3_usbhid_no_engagement_no_writes` |

**One-gate proof:** `test_one_gate_no_spawn_or_device_write_outside_the_executor` parses 31 gated modules
(AST) and fails on any `subprocess.*`, `os.system`/`popen`/`exec*`, `S.run` / `S.spawn`,
`__import__("subprocess")` or `.write(` that is not `executor.*` and not on a reviewed allowlist.
Each allowlist entry carries a justification, and `test_one_gate_allowlist_entries_have_justifications_and_exist`
fails on a stale entry. Remaining allowlisted spawns are all passive or local: candump, `ip neigh` /
`ip addr`, nmcli, rtl_power RX sweep, harden `--dry-run`, SDR enumeration, RECON passive survey,
and devterm's interactive terminal (gated before launch).

**Owner-decision constants** (strict, named, and actually consulted — `test_owner_decision_constants_are_strict_and_wired`):
`txguard.CONDUCTED_PROTECTED_ALLOWED = False`, `txguard.EXEMPT_SERVICES = ()`, `opprofile.CALLSIGN_ENABLES_TX = False`.

## Existing tests changed (policy, not regressions)

These tests encoded the old fail-open policy; each now asserts the strict behaviour:
`test_txguard.py` (public `decide()` → `authorize()`; the LoRa bypass test inverted; mesh default),
`test_bench.py` (the conducted 1090 MHz key-up is now refused; real exit code; arm/unlock),
`test_opprofile.py` (callsign alone no longer enables TX), `test_engagement.py` (globs refused),
`test_replay.py` / `test_loopback.py` (433.92 MHz is amateur in the US; ISM test moved to 915 MHz /
EU region), and the tool tests (`argv` → `ticket.argv`, typed scopes). `test_audit_scout.py`
(stop reaches the executor handle). `test_cl1_screen.py` / `test_palisade_qt.py`: scopes typed, and
BENCH needs the saved opt-in + arm + unlock to show PERMITTED. `conftest.py` now pins the
operator profile to `KD0ABC` for tests, so a developer's real profile can't change results.

## What the brief / audit got wrong

1. **L1 premise.** The audit says every Tk TX/gated app "runs as a separate process". In this code the
   Tk hub runs every tile except SDR++ **in-process** (`hub.py` `Shell.MODS` / `Shell.open`), so the
   kill switch already reached them via the shared `txguard._STATE`. The cross-process gap was real only
   for SDR++, standalone launches and future children. The session file is implemented anyway, as the
   brief asks, and is tested with a real child process.
2. **G1 "rename TX SAFE · conducted".** Already done by CL1 (`▲ TX PERMITTED · conducted`). Nothing to do.
3. **G5 PMKID filter.** `--filterlist_ap` / `--filtermode` is the hcxdumptool **6.2** interface. 6.3+
   replaced it with BPF filters. Verify the installed version on the uConsole. If it is 6.3+, the argv
   must change (the gate and ticket structure stay the same).
4. **G8 "unlock control in SYSTEM or the TX slot's panel".** Done in the Qt TX panel. The **Tk** hub
   still has only an arm toggle and no unlock, so Tk TX tools (CW, RTTY, digital modes, replay, Mesh
   send) still cannot key. Not changed (S3 / retire decision).

## Found, not in the audit

| Sev | Finding | State |
|---|---|---|
| Medium | TX slot kept **PERMITTED after disarm**. The shell repainted before BENCH withdrew its permit, and nothing re-polled. | Fixed: `chrome.report_tx_permit` re-fires the gate signal on change. Pinned by `test_cl1_screen.py::test_tx_safe_is_retired_and_bench_permit_shows_in_the_tx_slot`. |
| Medium | Strict G13 + **no operator-profile editor in the Qt app**: an engagement can't be opened in Qt until `operator.json` has a callsign or name (Tk Operator tool, or the file). The panel says so in its placeholder. | Open. Needs a profile field in SYSTEM › SETTINGS (CL6-sized). |
| Medium | **Tk Mesh send is now blocked**: strict decision 2 needs saved `tx_enabled` (default now False) + arm + **unlock**, and the Tk hub has no unlock. The Qt MESH tab has no send at all. | Consequence of decision 2 — open question 2. |
| Low | RECON's WIFIPENT card has one target field, so **deauth is always refused** (no client). Handshake and PMKID work. | Open. A client field is a layout change (CL6). |
| Low | FORGE Proxmark active ops are refused live: no live UID read-back path is wired in the UI (demo reads the synthetic card). Fails closed. | Open (CL6 executor pane). |
| Low | FORGE replay's default frequency changed 433.92 → 915.000 MHz, because 433.92 is amateur in the default US region. | Done (UI default only). |
| Low | `executor.ISSUERS` is a caller-frame check: it stops a well-meaning module minting its own ticket, not hostile in-process code. | Stated in code. |
| Info | Executor tickets are **issued but not executed** by the Qt gate cards (RECON / FORGE show them). Only BENCH and Tk Scout / devterm-SSH / HID run tickets. The executor output pane is CL6. | As designed. |

## Suite, lint

Run on the Mac: Python 3.12.13, PySide6 6.12, Qt offscreen (no xvfb on macOS), venv with
tkinter / PySide6 / pyqtgraph / flask / numpy / pyflakes. **Not run on Python 3.13 or on the uConsole.**

```text
$ QT_QPA_PLATFORM=offscreen python -m pytest -q tests
989 passed, 12 skipped, 2 warnings in 250.59s (0:04:10)
```

(branch tip before CL2: `910 passed, 12 skipped`)

```text
$ python -m pyflakes <the 55 .py files changed or added by CL2>
tests/test_palisade_qt.py:181:5: local variable 'before' is assigned to but never used
tests/test_palisade_qt.py:202:5: 'palisade_qt.__main__ as m' imported but unused
tests/test_palisade_qt.py:1503:9: 'skyfield' imported but unused
```
The 3 `test_palisade_qt.py` warnings were already there on the CL1 branch (lines 181, 202 and 1490 in the CL1 report).

## Screenshots (1280×720)

`plan/briefs/CL2-renders/after/` — 168 PNGs, all exactly 1280×720 (`sizes_*.json`). Each covers
{disarmed, armed, unlocked-engaged, expired} × {FORGE BUS, FORGE RADIO, RECON WIFI, RECON NET,
SYSTEM › BENCH, TX panel, ENGAGEMENT panel} × {dark, light, sun} × {live, demo}. PNGs are
git-ignored (repo rule); regenerate with `python3 plan/briefs/CL2-renders/render.py <out> <theme> <live|demo>`.
To show PERMITTED states the renderer stands in for the saved bench / replay opt-ins and the
operator profile. The engines decide every state shown.

## Open questions (owner)

1. **Conducted bench on protected bands**: denied (`CONDUCTED_PROTECTED_ALLOWED = False`). Keep, or add a typed per-session override?
2. **LoRa / Meshtastic**: no exemption (`EXEMPT_SERVICES = ()`), Mesh `tx_enabled` default off. Tk Mesh send is therefore blocked until a Tk unlock exists or LoRa is exempted from arm/unlock. Setting `EXEMPT_SERVICES = ("lora",)` keeps the env lock, `tx_enabled` and band checks.
3. **Callsign enables TX**: no (`CALLSIGN_ENABLES_TX = False`).
4. **S3: retire the Tk gated tools or keep them?** The Tk suite cannot open an engagement or unlock TX, so its gated tools stay blocked; only the false "sent" was fixed.
5. **Default region** is US (433.92 MHz = amateur). Set `tx_region` per device if it is used in the EU.

## Stage → model

All stages ran on the session model (**Claude Opus 5.5**, not Mythos as the README suggests for CL2): gate code, all denial tests, inventory (done inline with grep — no haiku agent), suite / pyflakes runs, renders, and every verdict. No subagents were used.
The commit trailer uses `Co-Authored-By: Claude Opus 5.5`, the model that actually wrote it, plus the brief's `Claude-Session` line.

---

# CL2-fix — closes what RA-CL2 found

**Branch:** `fix/cl2-gates` · base `dcb7c4f` (RA-CL2) · code + report in one commit after it.
Brief: `plan/briefs/CL2-fix.md` (on `docs/briefs`). Owner decisions 1–3 (2026-11-15) are implemented as written.
New regression file: `tests/test_cl2_fix.py` (59 tests). **56 of 59 fail on `dcb7c4f`.**
The 3 that pass there are sanity checks showing the fix is not over-broad: txguard still issues on an allowed band, wired tools need no kill switch, and a real bound child still follows its hub.
Evidence: `plan/briefs/CL2-fix-evidence/before_dcb7c4f.txt` and `after.txt`.

## Per finding

| ID | Verdict | Fix · file:line | Regression test(s) |
|---|---|---|---|
| **N1** SDR TX via engagement gate | **CLOSED** | `rfemit.py` (new) classifies argv. An SDR transmitter matches if its name appears in any token (exact set, or a transmit-shaped pattern so unknown names fail closed). Wrappers like `sudo` and `sh -c`, and full paths, are caught. `executor.py:121,151-155`: only `TX_ISSUERS=("txguard",)` may mint an SDR-TX ticket, a structural backstop for every issuer. `engagement.py:603` refuses first, before the trail records anything. | `test_n1_engagement_cannot_issue_hackrf_1090_poc` (the RA p5 PoC); `test_n1_wrapped_and_lookalike_transmitters_refused_at_issue` (×8); `test_n1_executor_refuses_sdr_tx_from_every_issuer_but_txguard`; `test_n1_txguard_still_issues_sdr_tx_on_an_allowed_band`; **static** `test_n1_static_no_non_txguard_issuer_names_a_transmitter` (a module that issues through engagement or the executor must not name a transmitter) |
| **N2** hard lock + kill switch don't silence emitters | **CLOSED** | `txguard.emit_allowed()` (`txguard.py:335`) denies on the env lock, stale hub state, or the kill switch OFF. `executor._with_rf_gate` (`executor.py:124,157`) adds it to the re-check of **every** ticket that `rfemit` classifies as an emitter. That check runs at issue, at spawn, and on every sweep, so a disarm (notification) or a lock (0.25 s monitor) kills the process. `engagement.issue` pre-checks at `engagement.py:612`. Emitter classes: Wi-Fi (aireplay-ng, hcxdumptool, mdk…), Zigbee (`zb*` except known RX tools), Z-Wave (`zwave-*` except the sniffer), BLE (gatttool …), RFID (pm3), and serial lines (Flipper by verb, failing closed on unknown verbs; every ESP32 or unknown device). | `test_n2_kill_switch_off_refuses_every_emitter_at_issue_poc` (×9 classes); `test_n2_env_hard_lock_refuses_every_emitter_at_issue_poc` (×9); `test_n2_every_emitter_refused_at_spawn_after_disarm_or_lock` (×9, both closes); `test_n2_disarm_kills_a_running_deauth_poc`; `test_n2_env_lock_mid_run_kills_a_running_emitter`; `test_n2_wired_tools_do_not_need_the_kill_switch`; `test_n2_classifier_table` |
| **N3** gatestate trusts any live pid | **CLOSED** | `gatestate.py:115-136`. The child must hold the hub nonce in `PALISADE_GATE_NONCE`; `child_env` hands it over and the child never reads it from the file. The file's pid must be alive, and its start time must equal what the hub recorded (`proc_start`, `gatestate.py:104`: `/proc/<pid>/stat` on Linux, `sysctl KERN_PROC_PID` on macOS). A missing or unknown start time counts as locked. | `test_n3_live_pid_with_wrong_start_time_is_locked_recycled_pid`; `test_n3_stale_file_after_hub_crash_is_locked`; `test_n3_file_from_another_hub_is_locked`; `test_n3_missing_start_time_is_locked`; `test_n3_forged_file_naming_a_live_pid_is_not_trusted_by_a_child_poc` (RA `l1_forged`, real child process); `test_n3_real_child_of_a_real_publisher_still_follows_the_hub` |
| **N4** Proxmark emulated ID not scope-checked | **CLOSED** | `proxmark.py:35,75-81,109-118`. The `hf_mf_sim` uid and the `lf_hid_clone` id must also be `uid:` entries in scope. They are checked at issue and on every re-check (`engagement.issue(also=…)`), and the command carries exactly the normalised, checked ID. Any parameter that is not a single plain token is refused, which closes a second command smuggled through pm3's `;`. | `test_n4_sim_out_of_scope_emulated_id_refused_poc` (RA `g5_pm_param`); `test_n4_clone_out_of_scope_written_id_refused`; `test_n4_in_scope_emulated_id_allowed_and_bound_into_the_command`; `test_n4_second_pm3_command_cannot_be_smuggled_in_a_parameter` |
| **N5** hostname bound by name | **CLOSED** | `engagement.pin_host` (`engagement.py:271`) resolves once. `netpent.py:62-68` hands nmap every checked address, never the name; the extra addresses are re-checked through `also`. | `test_n5_hostname_target_is_pinned_to_its_checked_address_poc` (RA `g4_rebind`); `test_n5_every_resolved_address_is_pinned_and_checked` |
| **N6** `"2e6"` sample rate crashes | **CLOSED** | `txguard.as_hz` (`txguard.py:129`) uses the same `_finite` value the gate bounds-checks. Used by the replay, bench and loopback argv builders and the bench log. | `test_n6_float_format_sample_rate_does_not_crash_and_is_bounded_poc` (RA `poc3`; also 2e9, nan, inf and 1e3 are refused) |
| **N8** re-check uses settings snapshot | **CLOSED** | `txguard.issue_ticket` re-checks the caller's own settings object, not a copy, or `live()` (`txguard.py:455`). Bench: `start_transmit(opt_in=…)` (`bench.py:95-125`). The Qt BENCH app passes the SAVED `tx_enabled` as a live opt-in (`palisade_qt/bench_app.py:212`), ANDed with the dict. | `test_n8_recheck_reads_live_settings_not_a_snapshot_poc` (RA `g11_settings_snapshot`); `test_n8_bench_saved_opt_in_is_live` |
| **N9a** demo ticket writes to any port | **CLOSED** (trivial) | `executor.py:326` refuses a `binding="demo"` ticket unless the port class is `SYNTHETIC` (`hwlab.DemoSerial`, `hwlab.py:285`). | `test_n9a_demo_ticket_only_writes_to_the_synthetic_port` |
| **N7** Tk hub has no UNLOCK | **DEFERRED** (owner decision 3) | Unchanged: the Tk gated tools stay permanently blocked and no unlock control was added. Listed for retirement in CL8 below. | (existing `test_g8_*` keep them blocked) |
| **N9b** Scout fallback scanner runs outside the executor | **OPEN — found, not fixed** (not trivial) | When nmap is absent, `scout.py`'s connect-scan runs in in-process threads. It is gated before start, but `executor.kill_all` cannot stop it; only its stop flag can. A fix would move it into a subprocess under the executor, or register its stop flag with `kill_all`. | — |

## Test changes to existing files

> **Correction (CL2-fix2, after RA-CL2b R2):** an earlier version of this heading said "no denial
> weakened". **That was false.** No assertion text changed, but 4 unchanged out-of-scope tests
> (`test_wifipent::test_out_of_scope_blocked`, `test_blepent::test_out_of_scope_blocked`,
> `test_zigbee::test_inject_out_of_scope_blocked`, `test_proxmark::test_active_op_blocked_out_of_scope`)
> were left disarmed. They then passed on the RF gate's refusal even with scope enforcement removed.
> Fixed in CL2-fix2: they now arm and unlock, then assert the scope reason (see below).

- These tests drive an RF emitter, so they now arm the kill switch after opening the engagement (owner decision 2). Every refusal assertion is kept:
  - `test_cl2_gates.py`: g2, g3-allowlisted, g5 pmkid, g5 deauth, g5 zigbee, g5 proxmark, g5 unbindable
  - `test_blepent.py` (3), `test_flipper.py`, `test_proxmark.py`, `test_wifipent.py`, `test_zigbee.py`, `test_zwave.py`
  - Each of those module files' fixtures now also resets txguard, so no armed state leaks between tests.
- `test_palisade_qt.py::test_forge_proxmark_write_gated_and_reads_are_not`: **stricter**. It now also asserts the write is refused ("RF silenced") while disarmed, then arms.
- `test_cl2_gates.py::test_l1_child_sees_parent_arm_and_disarm`: `read()` now takes the hub nonce (N3).
- `test_proxmark.py::test_active_op_allowed_in_scope`: the expected command is `…-r 2006F623AE`, the normalised identity that is scope-checked (N4).
- `GATED_MODULES` now includes `rfemit.py`, so the one-gate static scan covers it.

## Brief vs reality

- N2 is applied **strictly**. Every radiating action is gated, not only the owner's examples: PMKID (hcxdumptool transmits), Zigbee *discover* (beacon requests), BLE *enum/read* (they connect), Z-Wave map/query, every ESP32 or unknown serial line, and Flipper verbs not on the known non-RF list (`loader open …` included). Relaxing any of these means editing one table in `rfemit.py`. Flipper `ir` and `ibutton` are treated as non-RF (optical / contact).
- Engagement-gated emitters need **arm only**, not the session unlock. The unlock is part of txguard's SDR chain, and the owner decision names the hard lock and the kill switch.

## Found, not in the audit

| Sev | Finding | Status |
|---|---|---|
| Medium | `proxmark.prepare` put caller parameters raw into a `pm3 -c` string, and pm3 runs `;`-separated commands. A parameter like `data="…; lf hid clone -r <any>"` smuggled a second, unchecked command. | **Fixed** with N4 (`_PARAM_RE`), test `test_n4_second_pm3_command_cannot_be_smuggled_in_a_parameter` |
| Low | `lf_t55_write`, `hf_mf_restore` and `hf_iclass_clone` write content that is not an identity parameter. It cannot be scope-bound; the reason now says "written content is not bound to the scope". **Correction (CL2-fix2):** the trail and the ticket still said `scoped` until CL2-fix2 R5. | Labelled. Owner may prefer to refuse these. |
| Low (fails safe) | With an engagement open and the kill switch OFF, the RECON / FORGE cards show emitter buttons as available. The engine refuses with "RF silenced …" on press. G12-style: the UI should reflect `txguard.emit_allowed()`. UI work, so not done here. | Open, for CL1/CL4 UI |
| Info | `netpent` trail entries for a hostname now carry the pinned address as the target; the name goes into the label (`net:portscan:nas.lan`). | By design (N5) |

## For CL8 (retirement list, owner decision 3)

The Tk gated tools stay blocked: Tk CW, RTTY, digital modes (`digimodes.py`), replay, Mesh send, and the Tk engagement-gated tools (wifipent, blepent, zigbee, zwave, proxmark, usbhid Tk windows). The Tk hub has ARM but no UNLOCK and cannot open an engagement.

## Suite, lint, renders

```text
$ QT_QPA_PLATFORM=offscreen python3.12 -m pytest -q tests        # Py 3.12.16, PySide6, macOS
FAILED tests/test_audit_tiles.py::test_undecodable_tile_is_marked_failed
FAILED tests/test_sstvdec.py::test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone
2 failed, 1044 passed, 14 skipped in 249.41s
```
Both failures are the known ones, already failing on `main@e6184c6` (RA-CL2 confirmed this). The second fails because `skyfield` is missing from this venv. Before CL2-fix the suite was 985 passed; +59 new tests.

```text
$ python3.12 -m pyflakes rfemit.py executor.py txguard.py engagement.py gatestate.py proxmark.py netpent.py \
    replay.py bench.py loopback.py hwlab.py palisade_qt/bench_app.py tests/test_cl2_fix.py tests/test_cl2_gates.py \
    tests/test_blepent.py tests/test_flipper.py tests/test_proxmark.py tests/test_wifipent.py tests/test_zigbee.py \
    tests/test_zwave.py tests/test_palisade_qt.py
tests/test_palisade_qt.py:181:5: local variable 'before' is assigned to but never used
tests/test_palisade_qt.py:202:5: 'palisade_qt.__main__ as m' imported but unused
tests/test_palisade_qt.py:1508:9: 'skyfield' imported but unused
```
All 3 warnings are pre-existing: the same warnings appear on `dcb7c4f`, at line 1503 there. Nothing new. **Not run on Python 3.13 or on the uConsole.** The Linux branch of `gatestate.proc_start` (`/proc/<pid>/stat`) is exercised only there.

**Renders** (token budget: only pages a finding touches, dark + sun, live): `plan/briefs/CL2-fix-renders/{dark,sun}-live/`. That is 56 PNGs, all exactly 1280×720 (`sizes_*.json`), covering the 4 gate states × FORGE BUS/RADIO, RECON WIFI/NET, SYSTEM › BENCH, and the TX and ENGAGE panels. No layout changed; BENCH has only a gate-wiring change. PNGs are git-ignored.

## Stage → model

| Stage | Model |
|---|---|
| Gate code, tests, every verdict | session model (Claude Opus 5.5) |
| Inventory, suite, pyflakes, renders | session model, inline. **No subagents were used**, which is within the token-budget rule (max 4; none needed). |

## Open questions (owner)

1. **N2 breadth:** keep BLE enum/read, Zigbee discover and PMKID under the kill switch, or limit it to write, inject and deauth? This branch is at the strict answer.
2. **Unbindable Proxmark writes** (`lf_t55_write`, `hf_mf_restore`, `hf_iclass_clone`): keep them label-only for content, or refuse them?
3. **N9b:** fix Scout's fallback scanner in CL2, or defer it to the Scout cluster?

Stop. **RA-CL2b** follows.

---

# CL2-fix2 — closes what RA-CL2b found

**Branch:** `fix/cl2-gates`, base `18770be` (RA-CL2b). Brief: `plan/briefs/CL2-fix2.md`. The owner decisions on R1 and R5 are implemented as written.
New regression file: `tests/test_cl2_fix2.py`, 65 tests. **54 of the 65 fail on `18770be`.** The 11 that pass there are sanity checks: shipped commands still issue, Flipper verbs that were already emitters, an R2 scope test that was already armed, an R6 matching argv, and an R5 bound op.
Evidence is in `plan/briefs/CL2-fix2-evidence/`: `before_18770be.txt`, `after.txt` and `mutation_all_in_scope.txt`.

| ID | Verdict | Fix (file:line) | Regression test(s) |
|---|---|---|---|
| **R1** allowlist | **CLOSED** | `engagement.issue` (`engagement.py:648`) reads the **calling** module's `ALLOWED_PROGRAMS` and refuses any argv whose argv[0] is not in that set. argv[0] must be a bare name, so a path or a renamed or symlinked binary is refused. `NEVER_PROGRAMS` and the interpreter pattern (`engagement.py:594-622`) refuse shells, interpreters and wrappers even when a module declares them. `rfemit.is_sdr_tx` still runs first, as defence in depth and to give the clearer reason. Declared sets: blepent, wifipent, zigbee, zwave, proxmark, netpent, passaudit, buslab, canbus, devterm (`ssh`). Payload tickets (Flipper, USB-HID) are not programs, so the allowlist does not apply to them. | `test_r1_every_ra_bypass_refused_through_the_engagement_gate_poc` (×20: quoting, glob, ANSI-C, `${var}`, `python -c`, `python3.13`, perl, env/sudo/xargs, renamed binary, a declared name given as a path, Cyrillic, `tune`, `sendook`, `tx_waveforms`, `urh_cli`, flowgraph, whitespace, empty); `test_r1_a_module_cannot_declare_a_shell_or_interpreter`; `test_r1_undeclared_module_runs_nothing`; `test_r1_every_shipped_module_real_commands_still_issue` (15 real commands); static `test_r1_static_every_argv_issuer_declares_allowed_programs` |
| **R1** DEVTERM SSH | **CLOSED** | `devterm._self_target` (`devterm.py:177`) refuses `localhost`, loopback, unspecified, IPv4-mapped loopback, and any address on this device's interfaces. It checks after resolution, and refuses the whole command if any address matches. Interface addresses come from `getifaddrs` through ctypes (`devterm.py:138`); if they cannot be listed, it refuses (fail closed). `prepare_ssh` (`devterm.py:219`) pins `-o HostName=<checked address>` and adds `-o ProxyCommand=none -o ProxyJump=none`, so ssh cannot be redirected back to this device. The remote command is label-only and is **not** subject to the RF hard lock (owner decision). A literal transmitter name in the remote command is still refused. `authorize_ssh_host` (interactive open) gets the same self-target refusal. | `test_r1_ssh_to_loopback_refused_at_issue_poc` (×8, including the RA PoC `127.0.0.1` + `hackrf_trans''fer`); `test_r1_ssh_to_an_own_interface_address_refused`; `test_r1_ssh_fails_closed_when_own_addresses_unknown`; `test_r1_ssh_remote_host_is_pinned_label_only_and_not_rf_locked`; `test_r1_ssh_ra_poc_never_spawns` |
| **R2** weakened tests | **CLOSED** | The 4 tests now arm and unlock, assert `"not in the engagement scope"`, and show that the in-scope twin issues. RA mutation re-run (`engagement._match` forced in scope, same 7 files): **17 tests catch it, the same set as `211fa0c`** (`mutation_all_in_scope.txt`). | `test_wifipent::test_out_of_scope_blocked`, `test_blepent::test_out_of_scope_blocked`, `test_zigbee::test_inject_out_of_scope_blocked`, `test_proxmark::test_active_op_blocked_out_of_scope`, plus `test_r2_scope_refusals_hold_when_armed_and_unlocked` |
| **R4** Flipper `input` | **CLOSED** | `input` was removed from `FLIPPER_NON_RF` (`rfemit.py:55`). `loader`, `js`, `subghz`, `nfc`, `rfid` and `bt` were already absent. Allowlisted Flipper reads (e.g. `bt hci_info`) stay reads. | `test_r4_flipper_radio_driving_verbs_silenced_by_lock_and_disarm_poc` (×8: refused while disarmed and under the lock, issued when armed); `test_r4_input_not_in_non_rf_list` |
| **R6** argv frequency | **CLOSED** | `txguard.issue_ticket` (`txguard.py:502`) calls `argv_matches_freq`. `TX_ARGV_GRAMMAR` (`txguard.py:443`) gives the exact option grammar per TX program; today that is `hackrf_transfer`: `-t -f -s -x` with a value, and `-R`. It refuses: an argv[0] that is not in the grammar (wrappers and paths included), an unknown option, the attached form `-f1090000000`, a missing or repeated `-f`, a non-ASCII-digit value, and any frequency that is not exactly the authorized one. | `test_r6_argv_1090_on_a_915_authorization_refused_poc`; `test_r6_unparseable_or_ambiguous_tx_argv_refused` (×12); `test_r6_matching_argv_still_issues_and_builders_agree` |
| **R5** unbound Proxmark writes | **KEPT, label now real** | Owner: keep `lf_t55_write`, `hf_mf_restore` and `hf_iclass_clone` allowed and label-only. Confirming it showed that **the label was only in the reason**: the trail and the ticket said `scoped`, so FORGE showed no LABEL-ONLY tag. `authorize_action` and `issue` take a `binding` override (`engagement.py:569`), and proxmark passes `"label-only"` for these ops (`proxmark.py:125`). | `test_r5_unbound_proxmark_writes_are_label_only_in_trail_ticket_and_ui` (×3); `test_r5_bound_proxmark_ops_are_not_marked_label_only` |

## Behaviour changes to existing tests (all stricter)

- `test_digimodes::test_prepare_authorizes_with_gate_and_tool` → `…_refused_even_with_gate_and_tool_freq_unverifiable`. The argv for `wsjtx`, `js8call` and `fldigi` carries no frequency (it is set inside the app), so R6 as written refuses it. Digimodes is a Tk-only tool, already blocked (owner decision 3) and on the CL8 retirement list. **Owner question 1.**
- The 4 R2 tests are as above. No assertion was removed or loosened. Mutation: 17 catch the scope mutation, compared with 13 on `18770be`.

## Found, not fixed

| Sev | Finding |
|---|---|
| Low | `executor.issue` itself does not check `ALLOWED_PROGRAMS`. Of its issuers, only `engagement` runs argvs from many modules; `txguard` is now grammar-bound (R6), and `flipper` mints payloads only. Enforcing the allowlist in `engagement.issue` covers every argv path the engagement gate has. |
| Low | The R6 grammar checks the frequency only. `-s` and `-x` are parsed but not compared with the authorized sample rate or the gain cap. `authorize`/`check_gain` validate those inputs, and every builder derives `-s`/`-x` from them. |
| Low | The SSH self-target check runs at issue, not at spawn. If this device's addresses change within the 120 s ticket TTL (a DHCP lease), the pinned address is not re-checked against them. |
| Info | `own_addresses()` was tested on macOS (real `getifaddrs`). The Linux `sockaddr` layout (`u16` family, native order) was reviewed but **not run on Linux or on the uConsole.** |

## Suite, lint

```text
$ QT_QPA_PLATFORM=offscreen python -m pytest -q tests      # Py 3.12, venv: PySide6 pyqtgraph flask numpy, macOS
FAILED tests/test_audit_tiles.py::test_undecodable_tile_is_marked_failed          # known main failure
FAILED tests/test_hwlab.py::test_doctor_hwbench_check - assert (None is True)     # env, fails on dcb7c4f too
FAILED tests/test_sstvdec.py::test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone   # known: no skyfield
3 failed, 1108 passed, 14 skipped in 258.64s
```
`test_hwlab::test_doctor_hwbench_check` fails the same way on `dcb7c4f` and `18770be` in this venv (RA-CL2b). It comes from a missing optional dependency, not from CL2-fix2.
```text
$ pyflakes engagement.py txguard.py rfemit.py devterm.py blepent.py wifipent.py zigbee.py zwave.py proxmark.py \
    netpent.py passaudit.py buslab.py canbus.py tests/test_cl2_fix2.py tests/test_digimodes.py tests/test_wifipent.py \
    tests/test_blepent.py tests/test_zigbee.py tests/test_proxmark.py
(no output, rc=0)
```
Not run on Python 3.13 or on the uConsole. No UI layout changed, so no renders. The only UI-visible change is that FORGE now shows the existing LABEL-ONLY tag for the three unbound Proxmark writes, through the existing `_ticket_text` path.

## Stage → model

| Stage | Model |
|---|---|
| Gate code, tests, mutation, every verdict | session model (Opus 5.5), inline |
| Suite / pyflakes | run directly in the shell; no subagents |

## Open questions (owner)

1. **Digimodes (R6):** the frequency cannot be verified from `wsjtx`/`js8call`/`fldigi` argv, so they are now refused at issue. Keep them refused until CL8 retires them (recommended), or add a rig-control path that sets and reads back the dial frequency?
2. **SSH ProxyJump:** `ProxyCommand=none` and `ProxyJump=none` break any engagement host that is only reachable through a jump host in `~/.ssh/config`. Accept that, or allow a declared jump host that is also self-checked?

Stop. **RA-CL2c** follows.
