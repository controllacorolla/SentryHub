# RA-CL5 — cold re-audit of CL5 (`fix/cl5-radio` @ 85335ea+)

**FRESH session, Opus.** Auditor only. Own worktree
(`git worktree add ../wt-RA-CL5 origin/fix/cl5-radio`). Token budget per `README.md`. Read the
audit PDF §§ for A1–A6, R1–R5, E2, E3, B1–B3 and §15.1 "Workers" first; read
`plan/briefs/CL5-report.md` only at step 4.

IDs: A1 A2 A3 A4 A5 A6 R1 R2 R3 R4 R5 E2 E3 B1 B2 B3 (+ §15.1 Workers). Also pinned here:
RA-MAIN-1 F1 (strip headroom) and F2 (font load claim).

1. Re-derive every audit PoC against the branch (`radio_arbiter.py`, `worker.py`, `app.py`,
   `kit/procs.py`, `eventbus.py`, `atlas.py`, `prowl.py`, `babel.py`, `prism.py`, `aprs.py`,
   `ais.py`, `nwr.py`, `sstv.py`, `scanner.py`). Real processes and real threads where the finding
   is about them; patch only the lease seam (`radio_arbiter._make_lease`).
2. Attack the design:
   - arbiter: request/release/revoke races across threads; a release during ACQUIRING; revoke
     timeout firing after a re-grant to another owner; GUI-thread `owner()`/`state()` never block.
   - PANIC and the arbiter's revoke vs a `Pipeline`: a stage that forks a grandchild, a stage
     that ignores SIGTERM, a stage that changes its own process group. Are any processes or
     zombies left? Is the dongle actually free afterwards (the next `request` succeeds and nothing
     is holding `/dev/bus/usb`)?
   - workers: close a page mid-sleep / mid-retry and check the shell quits with no QThread
     destroyed while running. Is a parked (A2) worker ever reaped?
   - BABEL/PROWL/NWR: does any path open the radio while the page is hidden, RUN is off, or in
     demo? Is there lease churn on a decoder that exits at once?
   - eventbus: a mutated payload after publish; unbounded growth.
   - no `shell=True` / `sh -c` left in `palisade_qt/` or the decoder argv builders.
3. UI-only rule: the RADIOS panel, PROWL, BABEL and ATLAS must not show a state the arbiter does
   not hold. Render at 1280×720 dark + sun, live, plus one stress pass (ACQUIRING held long,
   revoke pending, FAULT backoff). Top strip worst case ≤ 1270 px (RA-MAIN-1 F1).
4. Regression: `tests/test_cl5_radio.py`, `test_cl1_*.py`, `test_palisade_qt.py`, then the full
   suite once on **Python 3.12** (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`).
   Diff denial/negative assertions in `tests/` against `ef64fcd` (main). Any weakened assertion
   must be justified by a CL5 semantic change, or it is a finding. Three tests were rewritten on
   purpose (`test_cl1_fix::test_decoder_pipelines_start_in_their_own_session`,
   `test_palisade_qt::test_babel_live_mode_…`, `…test_overwatch_radio_director_…`), so check that
   each still proves what it claimed.
5. Write `plan/briefs/RA-CL5-report.md` on `fix/cl5-radio`, push it, and remove the worktree.
   Report a table per ID, then new findings, then one line: MERGE / DO NOT MERGE. These block: a
   radio that stays held after release/revoke/PANIC, a surviving decoder process or zombie, a
   GUI-thread block, a worker destroyed while running, or a page claiming a radio state it does
   not have. Hygiene is a follow-up.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPhNshq7gJQoo26LBF`
