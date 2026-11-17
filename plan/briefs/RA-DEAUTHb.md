# RA-DEAUTHb — cold re-audit of DEAUTH-fix, branch `claude/project-thread-1m4ns8`

**FRESH session, Opus.** Auditor only. Own worktree
(`git worktree add ../wt-RA-DEAUTHb origin/claude/project-thread-1m4ns8`). Token budget per `README.md`.
This is round 2. First re-verify every finding of `plan/briefs/RA-DEAUTH-report.md` (on the branch):
N1 (High — broadcast/group client in scope authorized), N2 (FEATURE_MAP stale), N3 (client == AP),
N4 (field widths / clipped card line / uncommitted renders / SUITE_RESULT placeholder), N5 (Low),
Info — mark each CLOSED / OPEN / PARTIAL with evidence. Then the checks below.

Owner decision 2026-11-17: targeted deauth (`aireplay-ng --deauth`) is a gated capability, not a
ban — active engagement, AP + client in scope, TX armed, issue/spawn/exit in the chain. Broadband
jamming unbuilt.

The fix is commit `9ebc439`. It changes a **gate file** (`wifipent.py`) — the whole point of the
re-audit. Verify the change is strictly *narrower* (refuses more), never wider:
1. N1/N3: `wifipent.prepare("deauth", …)` must refuse, before any `issue` record and with nothing
   spawned, a client whose first-octet I/G bit is set (`ff:ff:ff:ff:ff:ff`; any `01:…`, `03:…`,
   `33:33:…` multicast; odd first octet) EVEN WHEN that address is in the engagement scope, and a
   client equal to the AP. Try odd-first-octet unicast-looking values, mixed case, `-`/`:` forms.
   Confirm a normal in-scope unicast client is still issued (not over-refused). Confirm the capped
   count and the existing out-of-scope / no-client / TX-off / no-engagement refusals still hold.
2. Confirm no other refusal was loosened and no non-deauth path changed: diff `wifipent.py` and
   `palisade_qt/recon.py` against the RX head; engagement.py, chain.py, txguard.py, rfemit.py,
   opprofile.py, executor.py otherwise byte-identical to the RX head.
3. Test-fixture change: `test_cl2_fix.py` and `test_cl2_gates.py` changed a deauth CLIENT MAC from
   a multicast value (`11:…`, `99:…`, I/G bit set) to a unicast one. Confirm this is a fixture
   correction, not a weakened assertion — the tests still assert the same ok/refuse outcomes, and
   the old MACs were in fact group addresses.
4. N4 layout: render RECON WIFI at 1280×720 dark + sun with a capture running and a deauth done
   (`plan/briefs/DEAUTH-renders/render.py`). The CLIENT MAC must be fully readable. Note any
   remaining clipping of the card's echoed-command line (accepted if the same text is in the pane).
5. Regression: `tests/test_deauth_gate.py tests/test_wifipent.py tests/test_cl2_fix.py
   tests/test_cl2_gates.py tests/test_rx_recon_exec.py`, then the full suite once
   (`QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`). Known baseline failures:
   PLANNER-HANDOFF (test_shell ×7 no-tkinter, test_audit_tiles, test_hwlab doctor, test_sstvdec
   iss, flaky test_cl1_screen up/down — fails on the RX head too; segfault at exit).
6. Write `plan/briefs/RA-DEAUTHb-report.md` on `claude/project-thread-1m4ns8`, push, remove the
   worktree. Table per finding + any new finding with severity, then one line: MERGE / DO NOT MERGE.
   Blockers: N1 not actually closed, any gate path widened, an out-of-scope/disarmed/broadcast
   spawn, a kill/exit not recorded, a weakened assertion.

Trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALTR9RWPs844a49kAGV`
