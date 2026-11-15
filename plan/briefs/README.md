# Briefs — the hand-off protocol

Two Claude instances work this repo: the **planner** (cloud session; writes briefs, reviews,
opens PRs) and the **implementer** (Claude Code in VS Code on the Mac; writes code). They cannot
message each other. This directory is the channel.

## Protocol

1. Planner commits `plan/briefs/<ID>.md` on the `docs/briefs` branch and pushes.
2. Owner tells the implementer: **`run <ID>`**. Nothing else is needed.
3. Implementer: `git fetch origin docs/briefs && git show origin/docs/briefs:plan/briefs/<ID>.md`,
   reads the brief, reads everything it cites, does the work on the branch the brief names.
4. Implementer writes `plan/briefs/<ID>-report.md` **on its own working branch** (so the report
   travels with the code), commits, pushes, opens no PR, tells the owner **done**.
5. Owner tells the planner **`<ID> done`**. Planner reads the report + diff from GitHub, runs or
   commissions the re-audit (`plan/audit/REAUDIT_PROMPT.md`), opens the PR or writes `<ID>-fix.md`.

## Report format (`<ID>-report.md`)

- Branch + final commit hash
- Per finding ID in the brief: CLOSED / PARTIAL / OPEN / DEFERRED, with file:line and the
  regression test name. No test → not CLOSED.
- Anything the brief got wrong, with evidence.
- Anything found that is not in the audit, with severity.
- Suite result (`xvfb-run -a python3 -m pytest -q tests` tail), pyflakes result.
- Paths of the screenshots, rendered at exactly **1280×720**.
- Open questions for the owner (decisions only the owner can make).

## Rules that apply to every brief

- One cluster per branch. No drive-by fixes from other clusters; note them in the report instead.
- Nothing is CLOSED without a regression test derived from the audit's PoC.
- Screen is **1280×720** (not 480 — see `plan/audit/AUDIT_INDEX.md` correction).
- Render every touched page at 1280×720 in dark / light / sun × live / demo before reporting.
- The implementer's own review does not close a cluster; the cold re-audit does.
- Commits end with the trailer the brief specifies.

## Model tiers and fan-out (owner rule, 2026-11-15 — applies to every brief)

- **Session model (top tier)** for: implementation, gate/safety/TX auditing, severity judgement,
  and every CLOSED / OPEN / PARTIAL / REGRESSED verdict.
- **`sonnet`** for mechanical stages: render sweeps, suite and pyflakes runs, single-claim PoC
  *reproduction* (does it still reproduce — the verdict on it stays on the session model).
- **`haiku`** for pure search / file inventory.
- **Fan-out cap: at most ~10 parallel subagents per stage** unless the brief says otherwise.
- In the report, list which stages ran on which model.
- Owner guidance on the chat itself: start `RA-*`, `CL2`, `CL3` on Mythos with `ultrathink`;
  `CL4`–`CL9` on Opus without it.

## Token budget (owner rule, 2026-11-15 — supersedes the fan-out cap above where stricter)

- Max **4** parallel subagents per stage. Never run a subagent on the session model.
- Session model: reasoning and every verdict. `sonnet`: PoC reruns, suite/pyflakes, renders.
  `haiku`: grep / file inventory.
- Renders: only pages a finding touches, dark + sun, live only, plus one stress pass. Full
  matrix only for the final pre-merge pass.
- Run the suite once per stage, not per finding. Read only the files and lines a finding cites.
- Reports: table + short evidence per row. No narrative.
- On a cyber-safeguard block: `/model claude-opus-5-5` and continue.

## Runner (owner rule, 2026-11-15)

Briefs are now launched headless by `plan/runner/run.sh` on the owner's Mac from
`plan/runner/QUEUE`. Two lanes run at once, so **every session works in its own git worktree**
(`git worktree add ../wt-<ID> origin/<branch>`), never the shared checkout, and removes it when
done. Nobody can answer questions mid-run: where a brief is ambiguous, take the strictest
reading, say so in the report, and finish. End by pushing the report; the planner reads it.
