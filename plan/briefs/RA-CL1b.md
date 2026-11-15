# RA-CL1b — second cold re-audit of PR #19 (`fix/cl1-screen-structure`)

**FRESH Claude Code session**, no CL1 / CL1-fix context. Auditor only; write no fixes. Do not
read `plan/briefs/CL1-report.md` or `CL1-fix-evidence/` until step 4.

1. `git fetch origin && git checkout fix/cl1-screen-structure && git pull` (tip `4e51d3d`+).
2. Read the PDF, `plan/audit/AUDIT_INDEX.md`, and `plan/briefs/CL1-fix.md` (the 18 items).
3. Run `plan/audit/REAUDIT_PROMPT.md` with `<BRANCH> = fix/cl1-screen-structure`,
   `<IDS> = D1 D2 D3 D4 D7 D8 D9 D10 + RADIOS + audio + CL1-fix items 1–18`. Re-derive every PoC
   yourself (real `sh -c 'a | b'` pipelines for PANIC, failing/hanging mixer, alert arrives
   mid-drawer, reader that raises, popup open during PANIC). Measure **rendered** font sizes of
   real widgets. Render 1280×720 via `plan/briefs/CL1-renders/render.py`.
   Suite: `QT_QPA_PLATFORM=offscreen python3.12 -m pytest -q tests`.
4. Then read the CL1 report and CL1-fix evidence; check every claim and the mutation list (try
   to break a fix without a test noticing).
5. Specifically attack: the ENG slot now shows scope only (is "active" still unmistakable
   by word + shape?); PANIC when a process ignores SIGTERM; TX slot after PANIC with BENCH ack
   held; ATLAS table horizontal scroll at 1280×720; anything a fix made worse.
6. Model tiers per `plan/briefs/README.md` (verdicts on session model; PoC reruns and renders on
   sonnet; ≤10 agents per stage). If a cyber-safeguard block hits, `/model claude-opus-5-5`.
7. Write `plan/briefs/RA-CL1b-report.md` on the branch, commit, push, no PR. Table per item,
   new findings by severity, one-line MERGE / DO NOT MERGE. Tell the owner **done**.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
