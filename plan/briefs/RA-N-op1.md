# RA-N-op1 — cold audit of N-op1 (`fix/n-op1-operator`)

**FRESH session, Opus.** Auditor only. Own worktree
(`git worktree add ../wt-RA-N-op1 origin/fix/n-op1-operator`). Token budget per `README.md`.
Read item 8 (N-op1) of `plan/briefs/PLANNER-HANDOFF.md` for the defect. Read
`plan/briefs/N-op1-report.md` on the branch only at step 4.

Scope: the diff `origin/main...origin/fix/n-op1-operator` (palisade_qt/system.py, tests/conftest.py,
tests/test_n_op1_operator.py). Gate code (engagement.py, opprofile.py, txguard.py) must be unchanged.

1. Reproduce on main: SYSTEM › SETTINGS, type an operator, SAVE, then `engagement.start(...)` with
   the REAL `engagement._profile_operator` (conftest stubs it) against a temp `suite.CFG`. Confirm
   refusal on main and success on the branch, for a name ("DALTON") and a valid ham call.
2. Attack the fix:
   - Can SAVE ever set, flip or create `tx_enabled`, or otherwise make `opprofile.tx_settings` /
     txguard more permissive? Any other operator.json key changed (grid, authorization, opt-ins)?
   - Can the engagement record an identity different from what the field shows / what was typed
     (old callsign shadowing a new name, case, whitespace, SSID calls like N0CALL-9)?
   - Empty / whitespace operator: is an engagement still refused? Corrupt or read-only operator.json:
     does SAVE fail closed and say so honestly (no "saved" claim)?
   - Invalid HOME path: nothing saved, including the operator?
   - Does any other reader still depend on `palisade_ui.json` `callsign` (grep the tree)?
   - Does the new conftest `suite.CFG` redirect mask or change any other test's meaning?
3. UI-only rule: no data/decoding/radio behaviour changed. Render SETTINGS after SAVE at 1280×720,
   dark + sun, live.
4. Regression: `tests/test_n_op1_operator.py`, then the full suite once
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`). Known baseline failures:
   see PLANNER-HANDOFF (no tkinter → test_shell errors; test_audit_tiles, test_hwlab doctor,
   flaky test_cl1_fix2 alerts). Diff assertions in `tests/` against main; justify any weakened one.
5. Write `plan/briefs/RA-N-op1-report.md` on `fix/n-op1-operator`, push, remove the worktree.
   Table per check, new findings with severity, then one line: MERGE / DO NOT MERGE. Blockers: any
   gate weakened, tx_enabled touched, engagement still impossible from the UI, or a false "saved".

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALT3rG9nUELpTMmr2eR`
