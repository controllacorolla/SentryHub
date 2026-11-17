# RA-DEAUTH — cold audit of gated targeted Wi-Fi deauth, branch `claude/project-thread-1m4ns8`

**FRESH session, Opus.** Auditor only. Own worktree
(`git worktree add ../wt-RA-DEAUTH origin/claude/project-thread-1m4ns8`). Token budget per `README.md`.
Read `plan/briefs/DEAUTH-report.md` on the branch only at step 5.

Owner decision 2026-11-17 (Dalton): targeted deauth (`aireplay-ng --deauth`) is a **gated
capability, not a ban**. It may run only inside an active engagement, with the AP BSSID AND the
client MAC both in the engagement scope, the TX kill switch armed (`txguard.emit_allowed`), and
issue / spawn / exit recorded in the engagement's evidence chain. Broadband RF jamming stays unbuilt.

The branch is **stacked on RX** (PR #27, `claude/project-thread-st3z1x`, which makes RECON Wi-Fi
actions execute). Scope = `git diff origin/claude/project-thread-st3z1x...origin/claude/project-thread-1m4ns8`:
CLAUDE.md, PALISADE_BUILD_PLAN.md, plan/BACKLOG.md, plan/PROJECT_PROMPT.md (rule text),
palisade_qt/recon.py (GatedTool `runners=` per-action pane; Wi-Fi page gets a DEAUTH pane so a
deauth can run while the handshake capture keeps running), tests/test_deauth_gate.py,
plan/briefs/DEAUTH-renders/. `engagement.py, chain.py, txguard.py, rfemit.py, opprofile.py,
executor.py, wifipent.py` must be byte-identical to the RX head — verify.

1. Rule text: CLAUDE.md states the gated rule exactly as above and no doc on the branch still
   carries a blanket "no deauth" ban (grep *.md outside plan/audit and historical reports). Broadband
   jamming is still not built.
2. Gate: from RECON (card buttons AND `GatedTool._authorize` called directly) try deauth with no
   engagement, expired/ended engagement, out-of-scope AP, out-of-scope client, broadcast / empty /
   malformed client, iface or client that looks like an option, TX disarmed, `SUITE_TX_LOCK=1`.
   Each must refuse BEFORE any `issue` record and spawn nothing. Can the new per-action pane path
   reach `executor.start` without a ticket from `wifipent.prepare`, or run a ticket for a different
   action/argv than the button pressed?
3. Concurrency: capture running + deauth: is each pane still one process at a time? Can PMKID or
   HANDSHAKE start a second capture via the deauth pane, or deauth run twice at once? Does the card
   status line follow the right pane (no stale RUNNING, no ENDED for the wrong process)?
4. Kill + evidence: with a long-running deauth (substituted process), check DISARM, env lock,
   END, PANIC, STOP on the DEAUTH pane, and closing RECON each kill it and record kill/exit in the
   chain; the capture pane is unaffected by a deauth STOP. `run_panes()` / `stop()` include the
   new pane.
5. Honesty + layout: render RECON WIFI at 1280×720, dark + sun, with a capture running and a deauth
   done (`plan/briefs/DEAUTH-renders/render.py`). Both panes readable, nothing clipped that hides
   state.
6. Regression: `tests/test_deauth_gate.py tests/test_rx_recon_exec.py tests/test_wifipent.py
   tests/test_cl2_fix.py`, then the full suite once
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`). Known baseline failures:
   PLANNER-HANDOFF (no tkinter → test_shell errors; test_audit_tiles, test_hwlab doctor,
   test_sstvdec iss, flaky test_cl1_fix2 alerts). A segfault at interpreter exit after the RX tests
   also occurs on the RX head. Diff assertions in `tests/` against the RX head; justify any weakened one.
7. Write `plan/briefs/RA-DEAUTH-report.md` on `claude/project-thread-1m4ns8`, push, remove the
   worktree. Table per check, new findings with severity, then one line: MERGE / DO NOT MERGE.
   Blockers: any gate weakened or bypassed, an out-of-scope or disarmed spawn, a kill/exit not
   recorded, a gate file changed, a blanket deauth ban left in the working rules.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALTR9RWPs844a49kAGV`
