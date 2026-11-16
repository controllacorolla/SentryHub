# RA-CL5b — cold re-audit of CL5-fix (`fix/cl5-radio`, tip of the branch)

**Fresh session, Opus.** Auditor only, own worktree (`git worktree add ../wt-RA-CL5b
origin/fix/cl5-radio`). Token budget per `README.md`. Read `plan/briefs/RA-CL5-report.md` (your
predecessor's findings and its 12-item fix list) and `plan/audit/REAUDIT_PROMPT.md` first. Read
the "CL5-fix" section of `plan/briefs/CL5-report.md` only at step 4.

IDs: the 12 fix items of RA-CL5 (1 HELD before decode · 2 kill→wait→release in PROWL · 3 SSTV
RUN/hide/revoke · 4 SCAN revoke · 5 PANIC · 6 GUI-thread blocks · 7 honest give-back / NWR
MONITORING · 8 bus alerts · 9 Pipeline · 10 E3 BlueZ · 11 B2 retune · 12 SSTV new audio), plus
N1–N5 and N7–N12 as RA-CL5 rated them. Re-rate A1 A3 A4 A6 R1 R3 R5 E3 B2 from RA-CL5's table.

1. Re-run every PoC in `plan/briefs/RA-CL5-evidence/` against the tip (real processes, real
   threads; patch only `radio_arbiter._make_lease`; live paths need `QT_QPA_PLATFORM=minimal`).
   Each must now come out clean or you say exactly what still reproduces.
2. Attack the fix, not the tests:
   - Safety first (owner priority): **NWR** must never read LIVE / "no alerts" unless PROWL-NWR
     HOLDS the radio (arbiter HELD) with a running decoder — try revoke, forced free (holder that
     never acks), PANIC, hide, sub-mode switch, a decoder that hangs silently, a stalled worker.
     **PANIC**: after `hub.panic()` the arbiter must be FREE and stay FREE, no decoder process or
     zombie may remain or come back (BABEL text modes, SSTV, PROWL SCAN/FM/NWR, PRISM, ATLAS
     APRS/AIS) — race PANIC against a worker that is mid-spawn and one mid-ACQUIRING.
   - Ordering: at every release (hide, STOP, revoke, PANIC, close, sub-mode switch, forced free)
     is every stage of the holder's pipeline already gone? Is there any path that releases from
     the GUI thread while a decoder lives?
   - GUI thread: no handler that runs on the GUI thread (RUN, hide, revoke, PANIC, mode switch,
     close) may block on a process (stage that ignores SIGTERM, slow lease release).
   - HELD gating: can any holder spawn or claim LIVE during ACQUIRING, or after it lost ownership?
   - Event bus: can an alert still be lost (backlog, retention, a subscriber that throws)? Can
     alert-only delivery grow the queue without bound?
   - Pipeline: process-group reuse after `terminate()` (does it ever signal a pgid that is no
     longer ours?), concurrent terminate from two threads, partial start.
   - SSTV: the decode window (only new audio + the frame being received), duplicate events, disk
     writes per hour, rotation, the Tk `sstv.py` app that also uses `Recorder`.
   - Anything the fix made worse elsewhere (demo mode, the CL1 keyboard tests, OVERWATCH's
     radio director, the RADIOS panel).
3. UI-only rule: PROWL (SCAN/FM/NWR), BABEL (text + SSTV), PRISM, ATLAS and the RADIOS panel must
   not show a radio state the arbiter does not hold. Render at 1280×720 dark + sun, live: NWR live
   and after revoke, BABEL during a long ACQUIRING, BABEL after PANIC (the planner's renders are in
   `plan/briefs/CL5-fix-renders/`; make your own).
4. Regression: `tests/test_cl5_fix.py`, `tests/test_cl5_radio.py`, `test_cl1_*.py`,
   `test_palisade_qt.py`, then the full suite once on **Python 3.12**
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`). Diff denial/negative
   assertions in `tests/` against `ed4694a` (the RA-CL5 tip): every changed assertion must be
   justified by a CL5-fix semantic change (the report lists them), or it is a finding. Check that
   each `test_cl5_fix.py` test fails on `ed4694a` (the report says 31 of 32 do).
5. Write `plan/briefs/RA-CL5b-report.md` on `fix/cl5-radio` (table per item, then new findings),
   evidence in `plan/briefs/RA-CL5b-evidence/`, push (on rejection: fetch + merge, never force),
   remove the worktree. Blocking: a radio held after release/revoke/PANIC, a surviving decoder or
   zombie, a GUI-thread block, a worker destroyed while running, a page claiming a radio state it
   does not have, NWR reading LIVE without a held radio and a live decoder, a dropped alert.
   Hygiene is a follow-up. Last line: **MERGE** or **DO NOT MERGE**.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALNvJDsXP1W8kEoM9cY`
