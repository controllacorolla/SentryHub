# RA-CL4 — cold re-audit of CL4 (`fix/cl4-honest-state`)

**FRESH session, Opus.** Auditor only. Own worktree
(`git worktree add ../wt-RA-CL4 origin/fix/cl4-honest-state`). Token budget per `README.md`. Read
the audit PDF §§ for H1–H19, E1, E4, D4 (empty state) and L5 first, then `RA-CL3d-report.md` for
N20–N25 and the earlier RA-CL3 reports for N11, N12, N13, N15 and R1. Read
`plan/briefs/CL4-report.md` only at step 4.

IDs: H1 H2 H3 H4 H5 H6 H7 H8 H10 H11 H12 H13 H14 H15 H16 H17 H18 H19 · E1 E4 · D4 (empty state)
· L5 · carried from CL3: **N20 (Med)** N21 N22 N23 N24 N25 N11 N12 N13 N15 R1. H9 closed in CL3.

1. Re-derive every audit PoC against the branch. Gate/evidence (N20–N25, N12, N13, N15, R1):
   `engagement.py`, `executor.py`, `chain.py`, `gatestate.py`, with real processes and real
   process groups (a group leader that exits on SIGTERM while a member ignores it; a member that
   survives SIGKILL; a zombie orphan; a forged record naming the hub's own pgrp / ppid). Honest
   state: `palisade_qt/{sweep,recon,prism,prowl,babel,atlas,ops,overwatch,system,panels,
   radio_arbiter,eventbus,worker,app,kit/feed,kit/components,kit/scope}.py`, `radios.py`,
   `headless.py`, `assistant.py`, `wifisurvey.py`, `sky_app.py`, `bench_app.py`.
2. Attack the design:
   - END: wall time with several SIGTERM-ignoring orphans (N24); a group member that survives
     SIGKILL must record UNCONFIRMED, never KILLED (N20). Does any path still signal a process
     whose identity does not match (pid + start time)? Can a keyed forgery still reach the hub's
     own process group or its parent (N23)?
   - chain: kill -9 between the jsonl append and the head rename, then reopen and append (N13).
     Malformed head / non-dict lines must fail closed, never crash the GUI (N12). Snapshot
     rollback (R1): what is now refused, and is the documented limit honest?
   - honest state: find any screen that shows LIVE, a count, a range, "all quiet", "0", a dBm or
     a local time that is not backed by real data at that moment. Specifically: PRISM with
     rtl_power dead or silent; a failed Wi-Fi scan; a failed lease acquire (H4 — is the radio
     ever HELD after `RtlLease.acquire()` raises, and does the backoff ever wedge a page?); HOME
     unset (H5 — any range/bearing/pass computed from a guessed origin?); a DVB driver bound
     (H6); a stale aircraft.json (E1) on ATLAS and in Remote Mode (L5); SITREP/assistant with no
     feed, and with 30 aircraft evicting an alert (H17).
   - BLE/MESH/CAN/sensors/detectors: is NOT IMPLEMENTED said only where it is true, and does any
     live path still blame hardware that is present (E4)?
   - Remote Mode: contact fields come off the air. Any HTML injection left in the dashboard?
   - worker change: a resumed worker now steps at once (no full interval). Any page that relied
     on the old delay, or a resume storm?
   - the Wi-Fi scan must not run while RECON › WIFI is not on screen (H3).
3. UI-only rule: no data/decoding/radio behaviour change beyond what the findings require (the
   passive scan flag and the arbiter's refusal to grant on a failed lease are required changes;
   check nothing else moved). Render at 1280×720 dark + sun, live: OPS, SWEEP, PRISM, PROWL,
   ATLAS, OVERWATCH, RECON, FORGE, BENCH, SYSTEM (settings, assistant, sitrep, mesh) and the
   ENGAGEMENT panel. No table may be blank. Top strip worst case ≤ 1270 px.
4. Regression: `tests/test_cl4_gates.py`, `tests/test_cl4_honest.py`, `test_cl1_*.py`,
   `test_cl5_radio.py`, `test_palisade_qt.py`, then the full suite once on **Python 3.12**
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`). Diff denial/negative
   assertions in `tests/` against `04a76ab` (main). Any weakened assertion must be justified by a
   CL4 semantic change, or it is a finding. Changed on purpose: the event contract gained a
   `demo` key (H7), `wifisurvey.scan_argv` gained `passive` (H3), and the RA-CL3d PoC that
   monkeypatched `_kill_orphan` no longer applies (END batches kills, N24). Run the RA-CL3d PoCs
   (`plan/briefs/RA-CL3d-poc/`) — the DEFECT tests for N20–N25, N12, N13 should now fail
   (defect gone); say which still reproduce.
5. Write `plan/briefs/RA-CL4-report.md` on `fix/cl4-honest-state`, push it, and remove the
   worktree. Report a table per ID, then new findings, then one line: MERGE / DO NOT MERGE.
   These block: a screen that claims live data, a count, a range or "all clear" it does not
   have; an END that records KILLED for a process that survived, or signals a process that is not
   the one logged; a chain that bricks or verifies after tampering it should refuse; a radio
   granted after a failed lease; an injection in Remote Mode; a GUI-thread network call.
   Hygiene is a follow-up.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALQMMsmycF1AqRUye2B`
