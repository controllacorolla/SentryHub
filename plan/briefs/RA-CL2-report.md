# RA-CL2 — cold re-audit of `fix/cl2-gates`

**Auditor:** a fresh session with no CL2 context. `CL2-report.md` was read only after the verdicts were
fixed (step 4). **Branch audited:** `fix/cl2-gates` at tip `211fa0c` (code `02e1b16`). It was audited
in a separate worktree, so the owner's uncommitted CL1 edits were not touched.
**Method:** I re-derived every PoC from the PDF (§4 gates, §15.1). My own probes are in
`plan/briefs/RA-CL2-evidence/`. I did not use the implementer's tests as evidence. I ran them only as
the suite.

## Verdict

**MERGE the 14 declared fixes.** Every declared ID that reproduced is fixed, and a regression test
encodes its PoC. One qualification is about scope. **"There is one gate" holds for regulated-spectrum
(HackRF) TX. It does not hold for the executor as a whole.** The engagement gate is a second path into
the same executor. Through it, a HackRF TX command on a protected band can be spawned with no txguard
check (N1). No shipped code takes this path today, so it is latent. Close N1, or have the owner
formally accept it, before CL2 is treated as final.

## Per ID

| ID | Verdict | Evidence (fix · file:line) | Regression test (implementer) · my independent probe |
|---|---|---|---|
| **G1** BENCH | **CLOSED** | The saved `tx_enabled` is read and never forced (`bench_app.py` `_settings`). The 121.5 MHz preset is gone (`bench_app.py:35`). The one chain is `txguard.authorize("bench")`. Protected bands are denied even conducted (`CONDUCTED_PROTECTED_ALLOWED=False`). The run goes through the executor and reports the real exit code. | `test_g1_*` (6). My probes: the checkbox alone leaves TX off; 121.5, 1090 and GPS are denied conducted; exit codes 7 and 0 are reported correctly. |
| **G2** SERIAL | **CLOSED** | Device class comes from USB VID:PID, and a Flipper is trusted only with its product string (`flipper.py:66`). The only write path is `hwlab.gated_send`, then `prepare_command`, then `executor.write`. Every line is logged. | `test_g2_*` (5). My probe: on the Qt SERIAL tab only an allowlisted Flipper read reaches the port. Unknown and ESP32 devices wrote 0 bytes. |
| **G3** classifier | **CLOSED** | Allowlist `READ_ALLOW` (`flipper.py:24`). Any control character is refused outright. | `test_g3_*` (4). My probe: 24 emit strings, including U+2028, tab and empty input, all classify as emit. Every allowlisted read passes. |
| **G4** scope | **CLOSED** | Typed entries `parse_entry` (`engagement.py:151`). Containment uses `ipaddress` intervals. Globs, bare `*`, string scopes, `/0` and networks wider than /8 are refused. | `test_g4_*` (4). My probe: 33 hostile targets, including IPv4-mapped IPv6, decimal and hex IPs, `:port`, `%iface`, comma lists, `-sS` and unicode digits. None leaked. Leading or trailing whitespace is stripped, then matched correctly; that is not a leak. |
| **G5** binding | **CLOSED** (with N4 and N5) | PMKID gets `--filterlist_ap` and `--filtermode=2`, and the filter file is part of the ticket. Deauth requires an in-scope client; no broadcast form exists. CAN scope is interface plus ID range. Zigbee scope is PAN@channel. Proxmark reads back the UID. Tools that cannot be bound say "label-only" in the reason, the ticket and the trail. | `test_g5_*` (6). My probes: all of the above reproduced as fixed. Two residual gaps are listed as N4 and N5. |
| **G8** one gate | **CLOSED for txguard** (see N1, N2, N7) | `decide()` is gone; only the private `_decide` remains. `authorize` is the one public chain. `EXEMPT_SERVICES=()`. The Qt TX panel has ARM and UNLOCK. | `test_g8_*` (3). My probe: LoRa is refused at 1090 MHz, with `tx_enabled` False, and with no frequency. Every public TX entry refuses while disarmed, and while armed but not unlocked. |
| **G9** power/gain | **CLOSED** (see N6) | `gain_for_power` and `check_gain`. Non-finite power, power below the floor, and a sample rate outside 2–20 Msps are denied. | `test_g9_*` (2). My probe: `-x 47` and `-x 999` are clamped to the cap. NaN, inf and bool power are denied. 40 dBm is clamped to 10. |
| **G10** fail-open | **CLOSED** | `tx_enabled is True`. Any truthy `SUITE_TX_LOCK` locks. The band table is region-aware, and 433.92 MHz is amateur in the US. | `test_g10_*`. My probe: `"yes"`, `1`, `"true"` and `1.0` lock. `" 1 "` and `"x"` lock. An unknown region falls back to the US table. |
| **G11** capability | **CLOSED** (see N1, N8) | `executor.py`. A ticket is immutable, single-use, expires after 120 s, and is bound to a SHA-256 of the argv and files. The gate is re-run at spawn. The process gets its own group. END, disarm and expiry kill it. | `test_g11_*` (10). My probe: reuse, altered argv, mutated `_argv`, expiry, forged and bare-argv tickets are all refused. The gate re-runs after END. END and disarm kill the process. A race where the gate closes inside the spawner still kills the child. Engagement expiry kills a running process. |
| **G12** UI = engine | **CLOSED** | `chrome.GateSignals`. The replay banner shows the engine's own `authorize()` answer. | `test_g12_*` (4). My probe: with the poll timer stopped, the TX and ENGAGE slots follow the engines. Across 12 arm × unlock × frequency combinations, the replay banner never disagreed with the engine. FORGE cards disable on END. |
| **G13** lifecycle | **CLOSED** | A second start is refused and the first engagement and its trail are kept. Expiry is 8 h by default, 24 h at most. The operator comes from the profile. The authorization field is not pre-filled. | `test_g13_*` (5). All reproduced as fixed. |
| **L1** one state | **CLOSED** (see N3) | `gatestate.py`. The hub publishes a 0600 file. Children get `child_env`, which exports `SUITE_TX_LOCK=1` while disarmed. A bound child cannot arm, unlock or start an engagement. | `test_l1_*` (4). My probes: a real child follows the hub and loses authorization on disarm. A file whose hub is dead, a world-writable file, non-bool fields, malformed JSON and a missing file all fail closed. A running child that re-reads the file after disarm is denied. |
| **S2** Scout/devterm | **CLOSED** (see N9) | `scout.scan_network` uses the real netmask, then `netpent.prepare`, then the executor. The devterm BLE connect, MQTT publish, SSH open and SSH run are gated. | `test_s2_*` (3). My probe: with no engagement, no nmap runs and no TCP connect is made. A /24 engagement does not cover the real /22. An SSH host starting with `-` is refused. |
| **S3** Tk USB-HID | **CLOSED** for the false "sent" | `usbhid.run_payload` reports exactly what was written. | `test_s3_*` (2). My probe: a failed write and a missing gadget report 0 and never "sent". A good write reports the real count. Whether to retire the Tk gated tools is still the owner's call. |

**Owner defaults, checked on every entry point:** all three hold. Protected bands are denied even
conducted. No LoRa bypass exists. A callsign never enables TX. The constants are strict and actually
consulted.

**Denial assertions vs `main`:** I diffed all 22 changed test files. No denial was weakened. Every
inverted assertion became stricter. Globs are now refused. Deauth without a client is now refused.
Conducted 1090 MHz is now refused. LoRa with `tx_enabled` False is now refused. A callsign alone no
longer enables TX.

## New findings (not in the 93)

| # | Sev | Finding | PoC |
|---|---|---|---|
| **N1** | **Medium** (latent High) | **The engagement gate can spawn regulated-spectrum TX with no txguard check.** `engagement.issue(argv=…)` mints a ticket for any argv, and its re-check is the engagement check only. A `hackrf_transfer … -f 1090000000 -x 47` command (ADS-B, a protected band) was issued against a label scope and spawned by the executor. Its re-check passed with the kill switch OFF. The one-gate static test does not catch this: going through `engagement.issue` and then the executor is a "legal" executor path. None of the 13 shipped `engagement.issue` callers passes a HackRF argv, so this is latent. Fix: the executor, or `engagement.issue`, refuses a ticket whose argv[0] is an RF-TX tool unless txguard issued it. | `ra_cl2_poc2.py` p5; confirmed directly |
| **N2** | **Medium** | **Neither `SUITE_TX_LOCK` nor the TX kill switch silences the engagement-gated RF emitters.** Under `SUITE_TX_LOCK=1` and disarmed, tickets were still issued and spawned for Wi-Fi deauth (`aireplay-ng`), Zigbee inject (`zbreplay`), BLE write and Flipper `subghz tx`. DISARM does not kill a running deauth. Only END or PANIC does; PANIC was verified to kill them. This matches the documented two-gate design. But an operator who sets the env hard lock to enforce RF silence would rely on it, and these paths ignore it. **Owner decision:** should `SUITE_TX_LOCK`, the kill switch, or both gate every RF emitter? | `ra_cl2_poc2.py` p1–p3 |
| **N3** | **Medium** (latent) | **`gatestate` trusts any live process owned by the same user.** `read()` checks only that the named pid is alive (`os.kill(pid,0)`). The `nonce` is written (`gatestate.py:110,120`) and never verified. A file left by a crashed hub whose pid was later recycled is therefore trusted, as is a forged file. A child read `armed`, `engaged` and `tx_authorized=True` from a file naming the parent shell's pid. No shipped bound child transmits through txguard today. Fix: verify hub identity (the nonce cross-checked against the process, or its start time) before trusting a file from another process. | `ra_cl2_poc.py` `l1_forged` |
| **N4** | **Medium** | **Proxmark sim and clone do not scope-check the identity being emulated or written.** The UID read-back binds the physical card, but `hf mf sim -u CAFEBABE` was authorized while the scope and the card were both `DEADBEEF`. For sim and clone, that parameter is the impersonated identity. | `ra_cl2_poc.py` `g5_pm_param` |
| **N5** | **Low** | **A hostname target is bound by name, not by its pinned address.** `netpent.prepare("portscan","nas.lan")` resolves the name and checks it, but the argv carries `nas.lan`. The spawn-time re-check catches a DNS change made before spawn. nmap then does its own unchecked lookup, which leaves a DNS-rebinding window. Fix: substitute the resolved, in-scope address into the argv. | `ra_cl2_poc.py` `g4_rebind` |
| **N6** | **Low** | **A float-format string sample rate passes the gate, then crashes argv building.** `sample_rate="2e6"` passes `_finite` and the range check, but `int("2e6")` in `_replay_argv` raises an unhandled ValueError. It fails closed, by a crash. Fix: normalize to int inside the gate. | `ra_cl2_poc3.py` |
| **N7** | **Low** (fails safe) | **The Tk hub has ARM but no UNLOCK,** so Tk TX tools (CW, RTTY, digital modes, replay, Mesh send) can never key up. The implementer flagged this too. It belongs with the decision on retiring the Tk tools. | `ra_cl2_poc.py` `g8_tk_unlock` |
| **N8** | **Low** | **The re-check uses a snapshot of `tx_enabled`.** Clearing `tx_enabled` in settings during a transmission does not stop it. The live kill switches (disarm, unlock, env lock, END, expiry) do stop it, which was verified. Defensible as "the opt-in was already given", but it is a deviation from re-running the gate. | `ra_cl2_poc.py` `g11_settings_snapshot` |
| **N9** | **Low** | **Two paths rely on callers keeping a contract.** (a) `flipper.prepare_command(kind="demo")` issues an ungated write ticket for any line. Shipped code pairs `kind="demo"` only with the fake DemoSerial port, but the executor does not enforce that pairing. (b) When nmap is absent, Scout's fallback connect-scanner runs in in-process threads outside the executor. It is gated before it starts, but `kill_all` cannot stop it; only its own stop flag can. | `ra_cl2_poc2.py` p6; code review |

**Not findings (the brief got these right):** the device and port are not bound at write time for
label-only serial tickets. That is the G5 label-only limitation, already stated in the UI and the trail.
In the renders, BENCH showing TX PERMITTED while the engagement is EXPIRED is correct, because BENCH
TX depends on txguard only.

## Suite, lint, renders

```text
$ QT_QPA_PLATFORM=offscreen python3.12 -m pytest -q tests      # Py 3.12, PySide6, macOS
2 failed, 985 passed, 14 skipped in 249.29s
```

Both failures are **pre-existing on `main`**: I ran them on `main@e6184c6` and they fail the same way.
They are not CL2 regressions. One is `test_audit_tiles::test_undecodable_tile_is_marked_failed`. The
other is `test_sstvdec::…iss_passes…`, which fails because `skyfield` is missing from my venv. The
implementer's 989 passed / 12 skipped comes from a venv that has more optional dependencies.
**pyflakes:** no warnings in any file CL2 touched. The remaining warnings are older, in `aprs.py`,
`doctor.py`, `suite.py` and similar files. **Not run on Python 3.13 or on the uConsole.**

**Renders:** 168 PNGs, all exactly 1280×720. The set covers 4 gate states × 7 pages × {dark, light,
sun} × {live, demo}. The size check is in `RA-CL2-renders/sizes_*.json`. PNGs are git-ignored.
Regenerate them with `python3 plan/briefs/CL2-renders/render.py <out> <theme> <live|demo>`. No "SAFE"
chip appears anywhere. The only cosmetic issue is the ENGAGE slot truncating to `ACTIVE ·…`, which is
CL1 slot width, not CL2.

## Stage → model

| Stage | Model |
|---|---|
| All gate analysis, severity and every verdict | session model (Mythos 5.1, then Opus 4.8 and Opus 5.5 after owner model switches mid-session) |
| PoC reproduction runs, render sweep | `sonnet` (2 subagents) |
| Spawn / write / send inventory | `haiku` (1 subagent) |

At most 2 subagents ran in parallel.

## Open questions (owner)

1. **N1:** should regulated-spectrum TX be structurally restricted to txguard tickets? My
   recommendation is yes, before CL2 is final.
2. **N2:** should `SUITE_TX_LOCK`, the TX kill switch, or both silence every RF emitter, including
   deauth, Zigbee, BLE and Flipper? Today they cover HackRF TX only.
3. **N7 / S3:** retire the Tk gated tools, or add a Tk unlock?
