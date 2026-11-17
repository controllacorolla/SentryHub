# RA-UIPf — scoped cold re-audit of the RA-UIPe follow-ups, branch `fix/ui-polish`

**FRESH session, Opus.** Auditor only. Own worktree off `origin/fix/ui-polish`. Read `CLAUDE.md`,
`plan/briefs/RA-UIP.md` (§1 constraints), `plan/briefs/RA-UIPe.md`, then
`plan/briefs/RA-UIPe-report.md` on the branch (verdict MERGE, follow-ups E1–E6), then the diff:
`git diff 8b9fc42..origin/fix/ui-polish -- palisade_qt tests`. Scope is that diff only.

Re-run each RA-UIPe PoC, then try to break each fix:
1. **E1/E3** — DRONES switch generation (`AtlasLiveWorker.set_layer(gen=)`, `_reconcile_rid`,
   `AtlasApp._toggle`, `_rid_gen`, `on_status` `rid_gen` / `rid_fault`). Off→on inside one tick
   starts a fresh scan and stops the old one; notes AND faults from an old scan are dropped; the
   current scan's fault still reaches the page (fault chip, `_rid_state`, session log via
   `on_error`) exactly as before (`test_cl5_fix::test_fix10…`). Remote-ID faults no longer go
   through `worker.error`: does anything else (OPS, the composite, MODE on the strip, sessionlog)
   depend on that? The fault chip cleared on DRONES off must only ever be a Remote-ID one.
2. **E2** — `sonde_feed_state`, SONDE empty state: none / bad / stale / fresh with honest text.
   (`balloon_contacts()` still republishes old sondes regardless of age: pre-existing data
   behaviour, deliberately not changed in a UI cluster; say whether that is acceptable to flag.)
3. **E4** — one rebuild on a big move racing a delivery; no case left with no refetch.
4. **E5/E6** — HOME field: same value in another format is not an edit; clearing unsets the typed
   HOME on disk without moving the live HOME; USE GPS + SAVE still an edit; follow-off text after
   a clear is true. No path persists, relabels or moves HOME from a GPS fix.
5. `tests/test_ui_polish.py`, then the full suite once (baseline/flakes as RA-UIPd §6).
6. Write `plan/briefs/RA-UIPf-report.md` on `fix/ui-polish`, push (fetch + merge on reject, never
   force), remove the worktree. Table per E-item, new findings with severity, MERGE / DO NOT MERGE.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
