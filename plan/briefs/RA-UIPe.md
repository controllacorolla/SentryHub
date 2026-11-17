# RA-UIPe — cold re-audit of the RA-UIPd fixes, branch `fix/ui-polish`

**FRESH session, Opus.** Auditor only. Own worktree off `origin/fix/ui-polish`. Read first:
`CLAUDE.md`, `plan/briefs/device-notes.md` (on `docs/briefs`), `plan/briefs/RA-UIP.md`,
`plan/briefs/RA-UIPc.md` and `plan/briefs/RA-UIPd.md` (constraints, claims and blockers still
apply), then `plan/briefs/RA-UIPd-report.md` on the branch, then the fix diff:
`git diff c048fe6..origin/fix/ui-polish -- palisade_qt tests` (c048fe6 = RA-UIPd report).
Read `plan/briefs/UIP-report.md` only at step 5.

RA-UIPd said DO NOT MERGE (N1, N2 High; N3, N4 Medium; L-a, L-b, L-c). Commit 90fe6b0 claims all.
Re-run every RA-UIPd PoC on the new head, then try to break each fix:

1. **N1 — honest empty state per view** (`atlas._view_empty`, `_rid_state`, `on_error`,
   `on_status`, `_toggle`, `_render` now calling `_update_busy` before the empty state). For every
   single-layer view and every source state (layer off; DRONES starting / passive / active / setup /
   fault / turned off and on again; APRS/AIS acquiring / busy / held; DF; SONDE file missing /
   present), the text must match what the source is really doing — no "listening" without a running
   source, no stale state after a toggle. Does moving `_update_busy` earlier change OPS alerts
   (duplicate or missed RADIO BUSY alerts)? Does any non-Remote-ID error starting "Remote-ID…"
   exist, or a Remote-ID fault that doesn't start with it?
2. **N2 — tiles placed by their own HOME** (`tiles.ready` now carries the build HOME;
   `BaseMap._on_tiles(…, built)`). Re-run the queued-delivery PoC. Delivery after a small move:
   slid correctly, `_built` = build HOME, later slides do not compound. After a big move: dropped
   with a refetch, and the old image is not left mislabelled. Any other `ready` consumer?
3. **N3 — untouched HOME field** (`system._home_text_shown`, `_save_settings`). SAVE with an
   untouched field: HOME unmoved while following, stored typed HOME kept at full precision. An edit
   is a typed HOME. Check USE GPS (fills the field → counts as an edit), whitespace-only edits,
   clearing the field, a failed persist, and re-opening SETTINGS after SAVE.
4. **N4 / L-a** — `RidSource.SETUP_PROBLEMS`: bleak's "No powered Bluetooth adapters found." is a
   setup WARN with the right fix; "/dev/rfkill: permission denied" stays a fault; retry the
   RA-UIPc/RA-UIPd near-miss strings. **L-b, L-c** as stated.
5. Regression sweep of everything RA-UIPd marked CLOSED; hard constraints as in RA-UIP §1;
   `tests/test_ui_polish.py`, then the full suite once (baseline and flakes as in RA-UIPd §6).
   Renders at 1280x720, dark + light, LIVE (not demo): ATLAS DRONES / DF / SONDE / SEA
   (`plan/briefs/UIP-renders/render_views_live.py`), SETTINGS.
6. Write `plan/briefs/RA-UIPe-report.md` on `fix/ui-polish`, push (fetch + merge on reject, never
   force), remove the worktree. Table per RA-UIPd finding (CLOSED / OPEN / PARTIAL / REGRESSED ·
   evidence · test), new findings with severity, then MERGE / DO NOT MERGE. Blockers as RA-UIPd.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
