# RA-MESHb — targeted cold re-audit of the RA-MESH fixes, branch `fix/mesh-assistant` (PR #35)

**FRESH session, Opus.** Auditor only. Own worktree off `origin/fix/mesh-assistant`. Read `CLAUDE.md`
and `plan/briefs/RA-MESH-report.md` (M1, M2, L1-L10) on that branch, and Dalton's MESH/ASSISTANT
decisions in `plan/briefs/device-fix-plan.md` items 17-18 on `origin/docs/briefs`.
Scope: `git diff d92f8bc..origin/fix/mesh-assistant -- palisade_qt/mesh.py palisade_qt/system.py
tests/test_mesh_assistant.py` (the rest of that diff is Stage 2 merged in, audited separately).
- **M1** a DM target that drops off the node list stays selected, marked "not in the node list now";
  never falls back to everyone. Re-run your probe, plus a reconnect and a failed list read. Can a
  stale marked entry pile up or survive when the operator picks another target?
- **M2** `map_where` note and the NO REFERENCE POSITION cover. Render with some nodes lacking a
  position and with no reference at all, at 1280x720.
- **L2** STOP / close before the first token (socket shutdown under the response). Does it ever
  break a later ask, raise in the worker, or leave the 3 s join exceeded?
- **L3, L4, L5, L6, L8, L9, L10**: confirm each. L1 and L7 were not changed (L7 should be gone with
  the Stage 2 corner strip: check the MESH demo map).
UI-only; the TX gate still re-checked at send time; lifecycle.
Run `tests/test_mesh_assistant.py`, `tests/test_palisade_qt.py`, one file per process
(`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q --timeout=240 --timeout-method=thread`).
Write `plan/briefs/RA-MESHb-report.md` on `fix/mesh-assistant`: a table, new findings with severity
and a PoC, MERGE / DO NOT MERGE (only Medium or worse blocks; list Lows for Dalton). Push (fetch +
merge on reject, never force), remove the worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
