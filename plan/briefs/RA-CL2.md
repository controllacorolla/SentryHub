# RA-CL2 — cold re-audit of `fix/cl2-gates`

**FRESH Claude Code session** (new chat, no CL2 context). You are the auditor; you write no
fixes. Do not read `plan/briefs/CL2-report.md` until step 4. This is the safety-critical
cluster: be adversarial, and prove or break "there is one gate".

## Steps

1. `git fetch origin && git checkout fix/cl2-gates && git pull` (tip `211fa0c` or later).
2. Read the PDF (§5 gates, §15.1 "Gates") and `plan/audit/AUDIT_INDEX.md`.
3. Run `plan/audit/REAUDIT_PROMPT.md` with `<BRANCH> = fix/cl2-gates` and
   `<IDS> = G1 G2 G3 G4 G5 G8 G9 G10 G11 G12 G13 L1 S2 S3`. Re-derive every PoC from the PDF
   yourself (do not reuse the implementer's tests as your evidence). Suite:
   `QT_QPA_PLATFORM=offscreen python3.12 -m pytest -q tests`.
4. Only now read `CL2-report.md`; any CLOSED with no test that encodes the PoC is OPEN.
5. Additionally try to **break the gate**, independent of the finding list:
   - find any path that spawns a process, writes a serial/radio device, or sends (BLE, MQTT, SSH,
     LoRa, HID, Flipper, CAN, Proxmark) without a valid ticket; check the "one gate" test's
     allowlist for entries that should not be there;
   - replay a used / expired / argv-altered ticket; race END/disarm against spawn;
   - stale or forged shared-state file (L1); child started before disarm;
   - scope: IPv6, IPv4-mapped, hostnames resolving to mixed in/out-of-scope addresses, DNS
     rebinding between check and use, CIDR /0, whitespace, unicode digits;
   - the three owner defaults (protected bands denied when conducted, no LoRa bypass, callsign
     never enables TX) hold on every entry point;
   - confirm nothing a gate used to deny is now allowed, and no existing denial assertion was
     weakened (diff the tests against `main`).
6. Follow "Model tiers and fan-out" in `plan/briefs/README.md`: verdicts and all gate analysis on
   the session model, PoC reproduction and renders on `sonnet`, inventory on `haiku`, ≤10
   parallel agents per stage.
7. Write `plan/briefs/RA-CL2-report.md` on `fix/cl2-gates`, commit, push, no PR. Table per ID,
   new findings with severity, one-line MERGE / DO NOT MERGE. Tell the owner **done**.

Commit trailer:
```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4
```
