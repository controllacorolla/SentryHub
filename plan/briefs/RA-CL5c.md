# RA-CL5c — cold re-audit of CL5-fix2 (`fix/cl5-radio`, tip of the branch)

**Fresh session, Opus.** Auditor only, own worktree (`git worktree add ../wt-RA-CL5c
origin/fix/cl5-radio`). Token budget per `README.md`. Read `plan/briefs/RA-CL5b-report.md` (your
predecessor's findings and its 7-item fix list) and `plan/audit/REAUDIT_PROMPT.md` first. Read
the "CL5-fix2" section of `plan/briefs/CL5-report.md` only at step 4.

IDs: RA-CL5b's N-a … N-j, plus N11, N13 and N14. Re-rate A1, R2, R3, R5 and item 6 (GUI-thread
blocks) from RA-CL5b's tables. The owner chose to fix N-d (NWR liveness) in this round.

1. Re-run every PoC in `plan/briefs/RA-CL5b-evidence/` (and the RA-CL5 ones it re-ran) against
   the tip. Use real processes and real threads; patch only `radio_arbiter._make_lease`; live
   paths need `QT_QPA_PLATFORM=minimal`. Each one must now come out clean, or you say exactly what
   still reproduces.
2. Attack the fix, not the tests:
   - **Safety first** (owner priority):
     - **NWR** must never read LIVE or "no alerts" unless PROWL-NWR HOLDS the radio and audio is
       flowing. Try a wedged rtl_fm, a stuck multimon-ng, a decoder that dies every 1–5 s, a
       `/proc/<pid>/io` that cannot be read, revoke, forced free, PANIC, hide, a retune, and a
       sub-mode switch in both directions.
     - **PANIC** must leave the arbiter FREE, keep it FREE, and leave no decoder or zombie
       behind. Race it against a pending sub-mode switch (the old worker still releasing), against
       a hidden ATLAS with AIS/APRS, and against the cases RA-CL5b already raced.
   - **`PalisadeApp.swap_worker`** (the new non-blocking switch):
     - Can two workers ever hold or open the dongle at once?
     - Can a retiring worker's release free its successor's lease (same lease name: SCAN→FM→SCAN
       quickly; BABEL text→SSTV→text)?
     - Can a running QThread ever lose its last reference?
     - Can a worker that never finishes leave the page lying about its state?
     - Are the `finished`-signal and close/stop paths correct (`stop()` while retiring)?
     - Does any switch block the GUI thread, given a stage that ignores SIGTERM and a 3.5 s
       lease release?
   - **Hidden ATLAS**:
     - A revoke, a forced free and PANIC while it is hidden.
     - Hidden during ACQUIRING.
     - The cost while hidden: it must start nothing besides the lease layers. Check ADS-B, RID
       and readsb behaviour.
   - **Arbiter**: `_release` now announces FREE before the slow `lease.release()`. Is anything
     granted the dongle while readsb is still restarting that was not before? Is the new
     `transition` signal correct from every thread?
   - **SSTV**:
     - The N-e lock: is there a deadlock or a dropped frame?
     - The Tk last-window rewrite (N-f): check disk writes per recording, `.prev.wav` cleanup,
       and that a capture which decoded at `ed4694a` decodes again.
   - **Anything the fix made worse elsewhere**: demo mode, the CL1 keyboard tests, OVERWATCH's
     radio director, the RADIOS panel, and the BABEL fault banner.
3. UI-only rule: PROWL (SCAN/FM/NWR), BABEL, PRISM, ATLAS and the RADIOS panel must not show a
   radio state the arbiter does not hold. Render at 1280×720, dark and sun, live, in these states:
   - NWR with a wedged rtl_fm;
   - PROWL during a slow sub-mode switch;
   - RADIOS after a hidden-ATLAS revoke;
   - BABEL after PANIC.

   The planner's renders are in `plan/briefs/CL5-fix-renders/`; make your own.
4. Regression:
   - Run `tests/test_cl5_fix2.py`, `test_cl5_fix.py`, `test_cl5_radio.py`, `test_cl1_*.py` and
     `test_palisade_qt.py`.
   - Then run the full suite once on **Python 3.12**
     (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`).
   - Diff the denial and negative assertions in `tests/` against `c4f5612`. Every changed
     assertion must be justified by a CL5-fix2 semantic change (the report lists them), or it is
     a finding.
   - Check that each `test_cl5_fix2.py` test fails on `510359e` (the report says 14 of 15; the
     15th is a control).
5. Write `plan/briefs/RA-CL5c-report.md` on `fix/cl5-radio`: a table per item, then new findings.
   - Put evidence in `plan/briefs/RA-CL5c-evidence/`.
   - Push. On rejection, fetch and merge; never force.
   - Remove the worktree.
   - These are blocking:
     - a radio held after release, revoke or PANIC;
     - a surviving decoder or zombie;
     - a GUI-thread block;
     - a worker destroyed or dropped while running;
     - a page claiming a radio state it does not have;
     - NWR reading LIVE without a held radio and flowing audio;
     - a dropped alert.
   - Hygiene is a follow-up.
   - Last line: **MERGE** or **DO NOT MERGE**.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALNvJDsXP1W8kEoM9cY`
