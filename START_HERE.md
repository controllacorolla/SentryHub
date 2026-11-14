# PALISADE — handoff package

Drop this whole folder into the repo root, then tell Claude in VS Code:
"Read CLAUDE.md and PALISADE_BUILD_PLAN.md, then start on A0."

- CLAUDE.md ................. working rules (read first, every session)
- PALISADE_BUILD_PLAN.md .... the master plan — drives everything
- CODE_REVIEW_HANDOFF.md .... defects to fix, with file refs
- TRIAGE.md ................. per-module wire / merge / hide list
- plan/ .................... design vision: DESIGN, BACKLOG, PROJECT_PROMPT,
                            concept/ (live OPS mockup), brand/, renders/

Note: the review assumes an uncommitted local bugfix batch may be present.
Run `git status` first (A0 in the plan).
