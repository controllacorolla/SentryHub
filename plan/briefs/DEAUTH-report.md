# DEAUTH — targeted Wi-Fi deauth is a gated capability (owner decision 2026-11-17)

Branch `claude/project-thread-1m4ns8`, **stacked on RX** (PR #27, `claude/project-thread-st3z1x`),
because RX is what makes RECON Wi-Fi actions execute. Merge #27 first.

## What was wrong
- The deauth gate itself already existed on main (`wifipent.prepare("deauth")`: active engagement,
  AP and client both in scope, no broadcast form, count capped at `DEAUTH_MAX`=10, TX kill switch
  via `executor._with_rf_gate`). CLAUDE.md lost its "no deauth" line on 2026-11-13, but four
  working docs still said "No OTA attack/jam/deauth built or extended" (BACKLOG Guardrails,
  BUILD_PLAN detector check + §11, PROJECT_PROMPT constraints) and the toolkit cluster kept
  "flagging" deauth as an open owner call. That stale text is where the refusal came from.
- In RECON (RX), deauth shared the one Wi-Fi run pane with the handshake capture, so it could
  never run while the capture it exists for was running (button disabled: "a tool is already
  running — STOP it first"). In practice it was unusable.

## What changed
| Item | Change | File |
|---|---|---|
| Rule | CLAUDE.md states the gated rule: active engagement, AP + client in scope, TX armed, issue/spawn/exit in the chain; not a ban, don't refuse/hide/flag it. Broadband RF jamming stays unbuilt (47 U.S.C. § 333). | `CLAUDE.md` |
| Stale bans | Rewritten to the gated rule; BACKLOG owner-call (1) marked DECIDED. | `plan/BACKLOG.md`, `PALISADE_BUILD_PLAN.md`, `plan/PROJECT_PROMPT.md` |
| Concurrency | `GatedTool(runners={action: pane})`; Wi-Fi gets a DEAUTH pane. Each pane still runs one process; same `prepare()` gate, same `executor.start`. `run_panes()` and `stop()` include it. | `palisade_qt/recon.py` |
| Gate code | **Unchanged** — engagement.py, chain.py, txguard.py, rfemit.py, opprofile.py, executor.py, wifipent.py byte-identical to the RX head. | — |

## Regression tests (`tests/test_deauth_gate.py`, 13)
| Requirement | Test |
|---|---|
| Refuses with no engagement, nothing spawned | `test_deauth_with_no_engagement_is_refused_and_nothing_spawns` |
| Refuses out-of-scope AP (no issue/spawn record) | `test_deauth_out_of_scope_bssid_is_refused_and_nothing_spawns` |
| Refuses out-of-scope client | `test_deauth_out_of_scope_client_is_refused_and_nothing_spawns` |
| No broadcast / clientless / malformed client | `test_deauth_has_no_broadcast_or_clientless_form` (×3) |
| Refuses with TX kill switch off | `test_deauth_with_the_tx_kill_switch_off_is_refused` |
| In scope: runs exact argv; issue → spawn → exit in chain, state EXECUTED | `test_in_scope_deauth_runs_and_issue_spawn_exit_are_in_the_engagement_chain` |
| Count capped | `test_deauth_count_is_capped_in_the_issued_argv` |
| Runs while the handshake capture keeps running | `test_deauth_runs_while_the_handshake_capture_keeps_running` |
| Closing RECON kills it, kill recorded | `test_closing_recon_kills_a_running_deauth_and_records_the_kill` |
| END kills it; spawn < kill < exit < engagement.close | `test_end_kills_a_running_deauth_and_records_kill_before_close` |
| DISARM kills a running deauth | `test_disarm_kills_a_running_deauth_from_the_card` |

## Renders (RECON WIFI, 1280×720, capture running + deauth fired)
`DEAUTH-renders/before-recon-wifi-{dark,sun}.png` (RX head: DEAUTH disabled while capturing) ·
`DEAUTH-renders/after-recon-wifi-{dark,sun}.png` (capture RUNNING, DEAUTH DONE · exit 0 on its own pane).

## On the uConsole
Still needs a USB monitor-mode Wi-Fi adapter (the onboard CM5 radio has no monitor mode) and
root or capabilities on aireplay-ng/airodump-ng — setting those up is a system step outside
PALISADE. The gate, UI and tests here are independent of that.

## Not changed (owner calls, not raised as blockers)
- `DEAUTH_MAX` = 10 frames per press and the client-required (no broadcast-to-AP) form are the
  existing CL2 gate defaults. Relaxing either is a gate-default change and needs Dalton's word.

## Follow-ups
- Wi-Fi right column is tight at 720 px: the monitor-mode note takes 4 lines, each pane shows ~2
  output lines. Move the note into the card or collapse it once an adapter is present.
- The survey label still ends "· no deauth/inject" (true of the survey path, reads oddly beside a
  DEAUTH button).

## Suite
SUITE_RESULT
