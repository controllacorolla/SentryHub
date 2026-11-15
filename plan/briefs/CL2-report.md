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
