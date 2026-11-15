# RA-CL1 — cold re-audit of PR #19 (`fix/cl1-screen-structure`)

**Run this in a FRESH Claude Code session** (new chat, no CL1 context). You are the auditor, not
the implementer. You write no fixes. You may not read `plan/briefs/CL1-report.md` until step 4.

## Steps

1. `git fetch origin && git checkout fix/cl1-screen-structure && git pull` — the tip must be
   `1e0993c` or later (the planner pushed a follow-up commit after `a716e2f`).
2. Read `plan/audit/PALISADE_full_audit_report_2026-11-15.pdf` and `plan/audit/AUDIT_INDEX.md`.
3. Run the prompt in `plan/audit/REAUDIT_PROMPT.md` with
   `<BRANCH> = fix/cl1-screen-structure` and
   `<IDS> = D1 D2 D3 D4 D7 D8 D9 D10 + §9 RADIOS panel + §9 audio control` (per `plan/briefs/CL1.md`).
   Re-derive every PoC yourself from the PDF. Render at exactly 1280×720 with
   `python3 plan/briefs/CL1-renders/render.py <outdir> <dark|light|sun> <live|demo>`.
   Suite: `QT_QPA_PLATFORM=offscreen python3.12 -m pytest -q tests` (the Mac has no xvfb).
4. Only now read `plan/briefs/CL1-report.md` and check every CLOSED claim against your own
   findings. A claim with no test, or a test that does not encode the PoC, is OPEN.
5. Additionally test these two owner rules, which postdate the audit:
   - every map is DARK or SAT only, default DARK, in all three themes (`kit/mappanel.py`);
   - nothing rendered in the top strip is under 16 px (`tests/test_cl1_screen.py::test_strip_has_no_text_under_16px_at_all`
     exists — try to break it: open every panel, widest slot states, SUN theme).
6. Write `plan/briefs/RA-CL1-report.md` **on the `fix/cl1-screen-structure` branch**, commit,
   push, open no PR. Format: the REAUDIT_PROMPT table, new findings with severity, one-line
   verdict MERGE / DO NOT MERGE. Tell the owner **done**.

Commit trailer:
```
Co-Authored-By: Claude Mythos 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4
```
