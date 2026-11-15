# PLANNER HANDOFF — read this first in a new chat/Project (written 2026-11-15 16:20 MT)

You are the **planner** for PALISADE (repo `controllacorolla/SentryHub`). The owner, Dalton, is
not a software engineer. Communicate in short, decisive messages with one action at a time, and
report what you did and why (merges, decisions taken, anything found) so he can see and correct
it. He asked not to be consulted on routine steps, so: proceed on routine merges that passed a
cold audit and **tell him each time**; stop and ask before anything irreversible or outside the
audit protocol (force-push, deleting branches, system changes, relaxing a gate default, anything
touching a protected band or the device). Decisions he reserved: Tk vs web, logo/SVG, second SDR,
ham callsign, head signing automation, session-chain prune policy, the v0.1 launch line.

## How work flows (see `README.md` in this directory for the full protocol)
- **The planner writes the fix code** on the cluster branch (owner decision 13:27) and runs the
  suite in its own workspace (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`).
- **Cold audits run on the owner's Mac** through `plan/runner/run.sh`: append a line
  `<lane A|B>  <BRIEF-ID>  opus` to `plan/runner/QUEUE` on branch `docs/briefs`, push, and the
  runner executes `claude -p "run <ID>"` headless within a minute. Reports land on the cluster
  branch as `plan/briefs/<ID>-report.md`. Poll GitHub for them (the runner's own status log does
  not reach GitHub; that is harmless).
- Every session works in its own git worktree. Never force-push (forbidden by CLAUDE.md).
- Briefs live in `plan/briefs/<ID>.md`. Audit briefs are short and scoped; verdicts are one line
  MERGE / DO NOT MERGE. On DO NOT MERGE: fix, push, queue `RA-<cluster><next letter>`.

## State at handoff
| Cluster | Branch | State |
|---|---|---|
| CL1 screen | merged (PR #19) | RA-CL1d MERGE |
| CL2 gates | merged (PR #20) | RA-CL2e MERGE; the planner's merge resolution is being checked by **RA-MAIN-1** (lane B) |
| CL3 evidence chain | `fix/cl3-evidence` @ 13c04a4 | CL3-fix pushed; **RA-CL3b** queued (lane A). MERGE → open PR → merge → tell owner |
| CL5 radio/threads | `fix/cl5-radio` | kit done: worker (interruptible stop/pause/backoff), app lifecycle (park, never abort; exit drain), arbiter FREE/ACQUIRING/HELD + revoke/ack, bus copy/retention/backlog, `kit/procs.py` Pipeline, aprs/ais/nwr argv builders, NWR poll/DOWN state, `more.py` deleted. Remaining: BABEL R1/R2, E2 scan bank skip/dwell, E3 BLE toggle, R5 SSTV rolling window, B1 FM tuner 3 decimals + step, B2 squelch, B3 epoch hit times; tests; report; then RA-CL5 |
| CL4 honest state | not started | H1–H19 E1 E4 D4(empty) L5 — branch off main once CL3 merges |
| CL6, CL7, CL8 | not started | `plan/audit/AUDIT_INDEX.md` |

## Known environment facts
- Linux (FreeType) renders the top strip **1284 px** wide in the worst case (Mac: 1279). The repo
  does not ship `palisade_qt/fonts/` (load_fonts is a no-op). Fix = bundle fonts + 8 px headroom;
  flagged in RA-MAIN-1; do it in CL5 or a small CL1-fix4. The uConsole runs Debian.
- Known baseline failures on main: `test_audit_tiles::test_undecodable_tile_is_marked_failed`,
  `test_hwlab::test_doctor_hwbench_check` (env), `test_sstvdec::…iss_passes…` (skyfield). Without
  tkinter, `tests/test_shell.py` errors; `test_all_callsigns_build_in_both_themes` segfaults on
  3.13 only on branches that predate CL1's `_retain`.
- Owner decisions so far are recorded in the briefs: CL2 (strict TX defaults), CL2-fix (SDR
  transmitters txguard-only; lock silences every emitter; Tk gated tools stay blocked → retire in
  CL8), CL2-fix2 (SSH program allowlist, no ProxyJump in v0.1, digimodes refused until CL8),
  CL1-fix2 (PANIC unchecks BENCH ack, nav labels visible, ATLAS no h-scroll), CL3 (strict
  defaults; head signing not automated — owner question open).
- Proposed launch line (owner has NOT confirmed): v0.1 = CL1–CL5 + CL8 with SWEEP and unfinished
  tools hidden; CL6/CL7 → v0.2. Ask him when CL5 is in.

## First actions in a new chat
1. `git fetch origin`; read `plan/runner/QUEUE` and the newest `RA-*-report.md` on each open branch.
2. Act on verdicts (merge + tell the owner, or fix). 3. Continue CL5 from the list above.
