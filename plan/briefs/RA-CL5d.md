# RA-CL5d — cold re-audit of CL5-fix3 (`fix/cl5-radio`, tip of the branch)

**Fresh session, Opus.** Auditor only, own worktree (`git worktree add ../wt-RA-CL5d
origin/fix/cl5-radio`). Token budget per `README.md`. Read `plan/briefs/RA-CL5c-report.md` (your
predecessor's findings and its fix list) and `plan/audit/REAUDIT_PROMPT.md` first. Read the
"CL5-fix3" section of `plan/briefs/CL5-report.md` only at step 4.

IDs: RA-CL5c's N-k … N-q, its weak-test note, and N13. Re-rate A1 and R3 from RA-CL5c's tables.

1. Re-run every PoC in `plan/briefs/RA-CL5c-evidence/` (`rerun_all.sh` covers the RA-CL5 and
   RA-CL5b ones) against the tip. Use real processes and real threads; patch only
   `radio_arbiter._make_lease`; live paths need `QT_QPA_PLATFORM=minimal`. Each one must come out
   clean, or you say exactly what still reproduces.
2. Attack the fix, not the tests:
   - **NWR** must never read LIVE or "no alerts" unless PROWL-NWR HOLDS the radio and the decoder
     is continuously reading audio. Cases to try:
     - rtl_fm stderr chatter;
     - a decoder that is stuck, or SIGSTOPped;
     - a decoder that dies every 1–5 s;
     - bursty audio;
     - `/proc/<pid>/io` that cannot be read;
     - revoke, forced free, PANIC, hide, retune, and a switch in both directions.

     Also check whether a healthy receiver ever drops out of LIVE spuriously (rtl_fm's real
     buffering and the 1 s gap rule).
   - **Revoke during a switch (N-k):**
     - FREE THE RADIO;
     - another page requesting the radio;
     - a forced free;
     - PANIC, in every phase of a switch;
     - the same-name chains SCAN→FM→SCAN and BABEL text→SSTV→text.

     Can the page end up in a state it does not show, such as RUN ticked with no worker, or
     "press Enter" with the radio held?
   - **`_Relay` (N-n):**
     - Is every row, status, error and fault of the current worker still delivered, in order?
     - Is anything from a retired worker ever applied?
     - Are there lifetime problems (the relay is a child of the page, the worker outlives it)?
     - Check pages whose workers are not created by `_start_new_worker` (FORGE, RECON, SWEEP,
       SYSTEM, OVERWATCH, BENCH).
   - **SSTV (N-m):**
     - A late frame from a stopped recorder must be shown once, with no duplicate decode event.
     - It must not leak into the next RUN's frames or clock.
   - **PANIC** must leave the arbiter FREE, keep it FREE, and leave no decoder or zombie behind.
     Re-race it against pending switches and a hidden ATLAS.
   - **Anything the fix made worse elsewhere:** demo mode, the CL1 keyboard tests, OVERWATCH's
     radio director, the RADIOS panel, the BABEL fault banner.
3. UI-only rule: no page shows a radio state the arbiter does not hold. Render at 1280×720, dark
   and sun, live, in these states:
   - NWR with an rtl_fm that only writes stderr;
   - PROWL after a revoke during a switch;
   - BABEL after a revoke during a switch;
   - BABEL after PANIC.
4. Regression:
   - Run `tests/test_cl5_fix3.py`, `test_cl5_fix2.py`, `test_cl5_fix.py`, `test_cl5_radio.py`,
     `test_cl1_*.py` and `test_palisade_qt.py`.
   - Then run the full suite once on **Python 3.12**.
   - Diff the denial and negative assertions in `tests/` against `9b2f940`. Every changed
     assertion must be justified, or it is a finding.
   - Check that each `test_cl5_fix3.py` test fails on `f8172c7` (the report says 8 of 8).
5. Write `plan/briefs/RA-CL5d-report.md` on `fix/cl5-radio`.
   - Put evidence in `plan/briefs/RA-CL5d-evidence/`.
   - Push. On rejection, fetch and merge; never force.
   - Remove the worktree.
   - These are blocking:
     - a radio held after release, revoke or PANIC;
     - a surviving decoder or zombie;
     - a GUI-thread block;
     - a worker destroyed or dropped while running;
     - a page claiming a radio state it does not have;
     - NWR reading LIVE without a held radio and audio reaching the decoder;
     - a dropped alert.
   - Pre-existing arbiter design items (N-o, N-p) and hygiene are follow-ups unless the fix made
     them worse.
   - Last line: **MERGE** or **DO NOT MERGE**.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALNvJDsXP1W8kEoM9cY`
