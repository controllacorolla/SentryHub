# RA-MAIN-1 — post-merge cold check of `main` after PR #19 (CL1) + PR #20 (CL2)

**Fresh session, Opus.** Auditor only, own worktree of `origin/main`. Token budget per `README.md`.
The CL2 branch was merged with `main` by the planner (commit "Merge main (CL1) into fix/cl2-gates")
and that resolution has not been cold-audited. Check only the merged surface:

1. PANIC (`palisade_qt/shell.py`): order and completeness — executor.kill_all, page permits
   (BENCH ack), child-tree stop, gate re-read, banner text from `chrome.read_tx()`. Re-run the
   CL1-fix2 PANIC tests and the CL2 G11/G12 tests; try PANIC with a running gated process + BENCH
   ack held + armed/unlocked: everything must stop and the slot must read what the gate says.
2. TX slot words (`chrome.read_tx`): OFF / PERMITTED / ARMED / UNLOCKED / UNKNOWN; PERMITTED is
   now reachable only if a page permit exists while disarmed — say whether that can still happen
   under CL2's bench gate, and whether the word should be retired.
3. ENGAGEMENT slot + panel: scope word, EXPIRED, UNKNOWN, TARGETS row, no clipping at 1280×720
   (dark + sun).
4. **Linux font metrics:** on a Debian/FreeType box (or the uConsole), `PalisadeHub.minimumSizeHint()`
   in the worst-case strip is **1284 px** (the planner measured this in a Linux container with IBM
   Plex Mono installed via fontconfig; `palisade_qt/fonts/` is NOT in the repo, so `load_fonts()`
   is a no-op everywhere). Confirm on Linux if you can; otherwise flag as a device-check item.
5. Suite once on 3.12. Write `plan/briefs/RA-MAIN-1-report.md` on a new branch `audit/ra-main-1`,
   push, no PR. One line: CLEAN or FIX NEEDED (with the fix list).

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
