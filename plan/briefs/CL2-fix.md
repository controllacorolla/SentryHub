# CL2-fix — close what RA-CL2 found

**Branch:** `fix/cl2-gates` (same branch; no PR). Read `plan/briefs/RA-CL2-report.md` (on that
branch) first, then `README.md` incl. **Token budget**. Gate code on the session model.
Same rules as CL2: strictest default, fail closed, PoC test fails before / passes after, no
real emission, never loosen a gate.

## Owner decisions (made 2026-11-15)

1. HackRF-class transmit tickets may be issued **only** by the txguard path. The engagement
   gate must refuse to mint a ticket for any argv whose program is a transmitter (hackrf_transfer,
   etc.) — fail closed on unknown programs that match a transmit-capable list.
2. The hard lock (`SUITE_TX_LOCK`) and the TX kill switch silence **every** RF emitter: Wi-Fi
   deauth, Zigbee inject, BLE write, Flipper sub-GHz, Proxmark sim/clone, replay. Disarm kills
   running ones, as END and PANIC already do.
3. Tk gated tools: leave permanently blocked as they are. Do not add an unlock control. List
   them for retirement in CL8. (Owner can reverse.)

## Fix

- **N1** Ticket issuer allowlist per gate: txguard may issue for transmitters; engagement gate
  may not. Extend the "one gate" static test so a new transmitter program minted via the wrong
  gate fails the suite. Test: your 1090 MHz PoC is now refused at issue time.
- **N2** Make the hard lock + kill switch part of the common spawn-time re-check for every
  emitter class; disarm kills all registered emitter processes, including a running deauth.
  Tests: lock on → each emitter class refused at issue and at spawn; disarm mid-run kills it.
- **N3** Verify the hub id (and start time / pid) in the gate-state file, not just liveness.
  Recycled pid, stale file after crash, file from another hub → treated as locked. Tests for each.
- **N4** Proxmark sim/clone: scope-check the emulated/target card ID, not only the card on the
  antenna. Test: out-of-scope emulated ID refused.
- **Low:** scan hostname resolved once and nmap given the resolved address; sample rate parsed
  as float ("2e6") without crashing and bounds-checked; re-checks read live settings, not a
  snapshot. The other two Lows: fix if trivial, otherwise list in "found, not fixed".

## Done means

`CL2-report.md` appended, suite + pyflakes pasted for real (the 2 known main failures named),
branch pushed, no PR. Stop: **RA-CL2b** (short, scoped to N1–N4 + regression sweep) follows.

Commits end with:
```
Co-Authored-By: Claude Mythos 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4
```
