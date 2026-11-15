# CL2 — Gate integrity

**Branch:** `fix/cl2-gates`. Branch off `fix/cl1-screen-structure` (PR #19), because CL1 rewrote
`palisade_qt/{forge,recon,bench_app,shell}.py` and `kit/topbar.py`, which this cluster also
touches. If PR #19 has merged by the time you start, branch off `main` instead. Say which you
did in the report. If RA-CL1 later forces changes to those files, the planner will tell you to
rebase; do not pre-empt it.
**Findings (PDF §5, §15.1):** G1 G2 G3 G4 G5 G8 G9 G10 G11 G12 G13 · L1 · S2 · S3.
**Not in this cluster:** G6, G7 (evidence chain → CL3). Do not touch `evidence.py`. Where an
executor must record something (G11), call a single `record(...)` hook that exists today or is
a no-op stub with a clear `# CL3` marker. Do not design the chain here.
**Read first:** `CLAUDE.md`, `plan/audit/AUDIT_INDEX.md`, the PDF §5 (gates) and §15.1 "Gates",
`plan/briefs/README.md` (including **Model tiers and fan-out**), then `txguard.py`,
`engagement.py`, `opprofile.py`, `flipper.py`, `replay.py`, `bench.py`, `netpent.py`,
`wifipent.py`, `canbus.py`, `proxmark.py`, `zigbee.py`, `zwave.py`, `usbhid.py`, `buslab.py`,
`hwlab.py`, `scout.py`, `devterm.py`, `hub.py`, `mesh_dash.py`, and the Qt callers in
`palisade_qt/{bench_app,forge,recon,kit/topbar}.py`.

## Ground rules (this is the safety-critical cluster)

- **Do not route around the gates, and do not weaken any.** Every change here makes a gate
  stricter, single-sourced, or more honest. If a fix would loosen anything, stop and report it.
- **PoC first.** For every finding, before fixing, write the regression test from the PDF's PoC
  and run it on the branch tip to watch it fail (the failure is evidence). Then fix. Then watch
  it pass. The report lists, per ID, the test name and "failed before / passed after".
- **Fail closed.** Missing, malformed, non-finite or ambiguous input means DENIED, never
  authorized.
- No real emission in any test. Fake at the process boundary (no `hackrf_transfer`, no
  serial write, no `nmap`): inject a fake spawner / fake serial port and assert on what it was
  asked to do or that it was never called.
- UI work here is limited to making banners and chips subscribe to engine state (G12). No
  layout changes.

## Owner decisions: apply the strictest default, flag, do not decide

The audit left three decisions to the owner. Implement the **strict** answer, make it a single
named constant or setting so it can be relaxed later, and list it under "Open questions":

1. **Conducted bench on protected bands** (e.g. 1090 MHz, 121.5 MHz): DENIED even when
   conducted. No typed per-session override in this cluster. Remove the 121.5 MHz preset (G1).
2. **LoRa bypass:** `service="lora"` goes through the same band/power/arm checks as everything
   else (G8). No service name is exempt.
3. **`opprofile.tx_settings` enabling TX because a callsign exists:** a callsign alone must
   never set `tx_enabled`. TX enable comes only from the saved explicit setting.

Also flag, do not decide: **S3 — retire the Tk gated tools or keep them?** Do the part that is
unambiguous (fix the false "sent" in Tk USB-HID so it reports what actually happened). Leave the
decision on retiring to the owner.

## Findings and required behaviour

**G1 — BENCH.** `bench_app` and `bench.py` read `tx_enabled` from saved settings, default off.
Route bench transmit through the single gate (G8). Run it in a worker with a registered process
handle so it can be stopped; report the runner's real exit code, not a synthetic success.
Rename any "TX SAFE · conducted" wording to "TX PERMITTED". Remove the 121.5 preset. Test: with
txguard disarmed and no engagement, ticking the checkbox does not enable the TX button and
`bench.transmit` never produces a command (the PoC).

**G2 + G3 — SERIAL console and Flipper classifier.** Identify the serial device by USB VID:PID.
Known emitters (Flipper-class, ESP32 RF firmware, slcan) go through an **allowlist** classifier
and the engagement gate; unknown devices are read-only until an engagement is active. Allowlist
the read-only Flipper commands; everything else is "emit". Reject CR and LF inside a command
(a second command after a newline must not pass as a read). Log every line sent. The Qt SERIAL
tab must call `flipper.prepare_command`. Tests: each PoC string from the PDF
(`subghz chat`, `ir universal`, `loader open`, `input send`, `js`, `rfid raw_emulate`,
`storage remove`, a command with embedded CR/LF) classifies as emit and is refused without an
engagement; an allowlisted read command passes; no write reaches the fake port otherwise.

**G4 — scope matching.** Typed scope entries. IP containment with `ipaddress`
(network/host/range). Resolve hostnames and check every resolved address. Reject bare `*`,
non-list scope (a string must not become characters), bracket/glob syntax, and
`192.168.1.1/0`-style masks. Tests: every PoC target in the PDF (`192.168.1.1/0`,
`192.168.1.0-255.0-255`, `192.168.1.evil.example.com`, `["*"]`, string scope) is rejected or
out of scope; in-scope addresses still pass.

**G5 — bind scope to the command.** Wi-Fi: capture tool gets a BSSID filter; deauth requires
and scope-checks the client (no client = refuse, not broadcast). CAN: scope is interface plus ID
range. Zigbee: PAN and channel. Proxmark: read back the UID and compare before a write.
Where binding is not possible (USB-HID, flash, Flipper, Z-Wave), the UI and the record must say
**"label-only authorization"**. Tests: pmkid command contains the BSSID filter; deauth with no
client is refused; out-of-range CAN ID refused; UID mismatch refuses the Proxmark write.

**G8 — one gate.** Make `decide()` a private classifier. Everything reachable (bench, Meshtastic
send, replay, CW/RTTY/digital, loopback) goes through one public authorize chain that knows arm,
unlock and engagement. Add the missing unlock control (a real UI control in SYSTEM or the TX
slot's panel, not a test hook); nothing outside tests calls `unlock_session(True)` today. Test:
every public TX entry point refuses with txguard disarmed; a service name never bypasses
(`service="lora"` at any frequency, PoC).

**G9 — power and gain.** Derive gain from the allowed power; clamp; reject non-finite
(`nan`, `inf`) and out-of-range values. Check sample rate. Tests: `-x 47`, `-x 999` under a
10 dBm cap come back clamped or denied, never passed through; `nan` power denied.

**G10 — fail-open details.** `tx_enabled` must be `is True` for settings built outside
`suite.settings`. `SUITE_TX_LOCK` locks on any truthy value (`1`, `true`, `yes`, `on`). Make the
band table region-aware: 433.05–434.79 MHz is **not** licence-free ISM in the US region; check
the amateur table first for that region. Tests: `"yes"`/`1`/`"true"` do not enable TX; `true`
lock locks; the 433 MHz case in the US region is treated as amateur-band (needs licence), in
the other region as ISM.

**G11 — capability, not command.** The gate issues a single-use, expiring ticket bound to a hash
of the argv. One executor accepts only tickets, re-checks the gate at spawn, registers the
process group, streams output, and returns the exit code (hand it to the CL3 hook). END
engagement and disarm kill every registered process. Make the argv builders private. Tests: a
ticket cannot be used twice; a ticket with altered argv is refused; an expired ticket is
refused; ending the engagement kills a running fake process; disarming kills it.

**G12 — UI follows engine.** `engagement` and `txguard` emit change signals; the TX/ENG slots,
the FORGE replay banner and the FORGE engagement cards subscribe. No static chip. Tests: after
END, FORGE cards go disabled and the text changes; the replay banner never says "armed +
unlocked" while the engine answers DENIED (assert the two agree across arm / unlock / engage
combinations).

**G13 — engagement lifecycle.** `start()` while active is refused (no silent replace, no trail
wipe). Add an expiry (default 8 h, configurable) enforced by the gate. Operator comes from the
profile, not free text. Authorization text is not pre-filled from the saved profile. Tests: a
second `start()` raises/denies and leaves the first intact; an expired engagement denies.

**L1 — one gate state across processes.** The Qt shell is one process; the Tk hub launches
children. Publish arm, unlock and engagement in a session-scoped state file under the runtime
directory, read by every child and removed when the hub exits. Export `SUITE_TX_LOCK=1` to
children whenever disarmed. The Tk master kill switch and the power auto-disarm must change
that shared state. Tests (fake child that reads the state): arming in the parent is seen by the
child; disarming is seen by the child; Tk kill switch with a running child ends the child's
authorization; stale state file from a dead hub is ignored (fail closed).

**S2 — Scout.** Route "Scan my network" through `netpent.prepare` (engagement, scope, log).
Use the real netmask, never an assumed /24. Gate the dev terminal's BLE connect, MQTT publish
and SSH command the same way. Test (fake nmap): with no engagement, Scout starts no scan and
never calls the spawner.

**S3 — Tk USB-HID.** Report what actually happened; never print "sent" when nothing was
written. Flag the retire-or-keep decision. Test: fake HID device records zero writes and the
tool does not claim "sent".

## Model tiers (this brief, per the README rule)

Session model: all gate code, all tests that assert a denial, every verdict. `sonnet`: running
the suite and pyflakes, rendering the FORGE/BENCH/RECON strips for the report. `haiku`: finding
every caller of `decide()`, `prepare`, `unlock_session`, `tx_settings`, `flipper.prepare_command`,
and every subprocess/serial write site (the inventory that proves there is one gate). Cap ~10
parallel agents per stage. List stage → model in the report.

## Also required: prove there is one gate

Add a test that fails if any module outside the executor can spawn a process or write to a
serial/radio device without a ticket — an AST or grep-based check over the repo for
`subprocess`, `Popen`, `os.system` and serial `.write(` in gated modules, with an explicit,
reviewed allowlist. New entries need a justification line. This is what will keep the claim true
after this cluster.

## Tests, suite, renders

- Each finding above has a named regression test that failed before and passes after.
- `xvfb-run -a python3 -m pytest -q tests` and `pyflakes` run for real; paste the tails. If a
  test needs `tkinter` or `flask` and the env lacks it, say so — do not claim it passed.
- Render the FORGE, RECON and BENCH-in-SYSTEM pages at exactly 1280×720, dark / light / sun ×
  live / demo, showing the new TX / ENG states (disarmed, armed, armed + unlocked + engaged,
  expired).

## Done means

`plan/briefs/CL2-report.md` on the branch in `README.md` format, branch pushed, **no PR**.
Then stop. The branch gets a cold re-audit (`plan/audit/REAUDIT_PROMPT.md`,
`<IDS>` = G1 G2 G3 G4 G5 G8 G9 G10 G11 G12 G13 L1 S2 S3) before merge. CL3 (evidence chain)
starts after CL2 merges, because both edit `engagement.py`.

Commits end with:
```
Co-Authored-By: Claude Mythos 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4
```
