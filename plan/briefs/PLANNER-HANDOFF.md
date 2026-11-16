# PLANNER HANDOFF — read this first in a new chat/Project (written 2026-11-15 16:20 MT; updated 2026-11-16 CL5 audit)

You are the **planner** for PALISADE (repo `controllacorolla/SentryHub`). The owner, Dalton, is
not a software engineer. Communicate in short, decisive messages with one action at a time, and
report what you did and why (merges, decisions taken, anything found) so he can see and correct
it. He asked not to be consulted on routine steps, so: proceed on routine merges that passed a
cold audit and **tell him each time**; stop and ask before anything irreversible or outside the
audit protocol (force-push, deleting branches, system changes, relaxing a gate default, anything
touching a protected band or the device). Decisions he reserved: Tk vs web, logo/SVG, second SDR,
ham callsign, head signing automation, session-chain prune policy, the v0.1 launch line.

## How work flows (owner decision 2026-11-15 16:33; README "Where audits run")
- One Project chat (`PALISADE`, repo attached) is the planner: writes fixes on the cluster branch,
  runs the suite (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`), opens and
  merges PRs, updates this file after every merge. Owner reads and approves what is flagged.
- **Cold audits run as subagents from that chat**: spawn a fresh `general-purpose` agent on Opus,
  own worktree, prompt = "git fetch origin docs/briefs && read plan/briefs/<RA-ID>.md and
  plan/audit/REAUDIT_PROMPT.md; do exactly that; push the report to the cluster branch". It must
  not be given anything from the planner's context. Verdict MERGE / DO NOT MERGE; on DO NOT MERGE
  fix, push, spawn `RA-<cluster><next letter>`.
- The Mac runner is retired (owner closes the Terminal windows). Mac = hardware/device checks only.
- Models: planner Mythos; gate/evidence/TX code Mythos; audits Opus; mechanical Sonnet/Haiku.
- Token rules: suite once per stage, renders only for touched screens, ≤4 subagents, no polling or
  sleep-and-check loops, new chat every 1–2 clusters (write this file first). Never force-push.

## State at handoff
| Cluster | Branch | State |
|---|---|---|
| CL1 screen | merged (PR #19) | RA-CL1d MERGE |
| CL2 gates | merged (PR #20) | RA-CL2e MERGE. **RA-MAIN-1** (post-merge check) was queued on the Mac runner; if no `RA-MAIN-1-report.md` exists on `audit/ra-main-1`, run it as a subagent |
| CL3 evidence chain | **merged (PR #21, 5c5607b)** | RA-CL3d MERGE (via RA-CL3b → CL3-fix2 B3/N14 → RA-CL3c → CL3-fix3 N16–N19). Owner decisions: 2 s END drain accepted; N16 = kill orphan only on pid+start-time match ("orphan at END"), else UNCONFIRMED. Follow-ups for CL4: **N20 Med** (verified_gone/`_kill_group` check only the group leader — probe killpg(pg,0), SIGKILL rest, UNCONFIRMED if any survive), N21–N25 Low (see RA-CL3d-report), plus N11 N12 N13 N15 R1 |
| CL5 radio/threads | `fix/cl5-radio` @ ed4694a | 2026-11-16: 3 stale tests fixed + RA-MAIN-1 F1 (strip ≤1270, `N tgts` for 100–999) and F2 (false finding; font-load test) folded in; CL5-report.md + renders pushed. **RA-CL5 = DO NOT MERGE**: A1 R1 R3 open, A3 regressed (decoders start/LIVE while ACQUIRING), PANIC leaves arbiter HELD + pages respawn, GUI-thread blocks on free/stop, NWR false all-clear after FREE (Critical), bus drops alerts (High). Next: **CL5-fix** = the 12-item list in `RA-CL5-report.md`, then spawn `RA-CL5b`. Note: branch is based on c00f57b (pre-CL2), merges clean with main |
| CL4 honest state | not started | H1–H19 E1 E4 D4(empty) L5 + CL3 follow-ups N20 (Med) N21–N25 N11 N12 N13 N15 — branch off main (CL3 is in) |
| CL6, CL7, CL8 | not started | `plan/audit/AUDIT_INDEX.md` |

## Owner decisions 2026-11-16
- Keep the PERMITTED TX word for v0.1. CL3's 2 s END wait accepted (deliberate). CL3 B3 fix is in a separate thread.
- Sonnet is not enabled for this org (switch refused); mechanical work runs on Opus.

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
1. `git fetch origin`; check for `RA-CL3b-report.md` on `fix/cl3-evidence` and `RA-MAIN-1-report.md`
   on `audit/ra-main-1`. Missing → spawn each as a cold subagent. Present → act on the verdict.
2. CL5: fix the 3 tests above, report, `RA-CL5` subagent. 3. CL4 off main once CL3 merges, then CL8.
4. When CL5 merges, ask the owner to confirm the v0.1 launch line. Tell him in one line after each merge.
