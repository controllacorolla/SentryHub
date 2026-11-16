# RA-CL4b — cold re-audit of CL4-fix (`fix/cl4-honest-state` @ f8172a2+)

**FRESH session, Opus.** Auditor only. Own worktree
(`git worktree add ../wt-RA-CL4b origin/fix/cl4-honest-state`). Token budget per `README.md`.
Read `plan/briefs/RA-CL4-report.md` (findings N26–N34, E1 residual) first; read the "CL4-fix"
section of `plan/briefs/CL4-report.md` only at step 4.

IDs: N26 (High, the blocker) N27 N28 N29 N30 N31 N32 N34 · E1 residual. N33 is declared not
fixed (follow-up). Re-confirm nothing RA-CL4 marked CLOSED has regressed.

1. Re-run the RA-CL4 PoCs (`plan/briefs/RA-CL4-poc/`) against the branch: every DEFECT test for a
   fixed ID should now fail (defect gone). Say which still reproduce.
2. Attack the fixes:
   - N26: with HOME unset (live) is any range picture left anywhere — PPI, map, rings, ring labels,
     basemap, centre marker, OVERWATCH, the detail card, a tooltip? Is any tile requested for a
     placeholder origin (watch the network and `TileLayer.fetch`)? Set HOME in SETTINGS: does
     the picture come back without a restart, centred on HOME?
   - N27/N28: tampered chain, malformed head with an engagement active, no engagement. Does the
     trail ever say "nothing authorized" or "no engagement" when it cannot know?
   - N29: anything other than a receiver's contacts/decodes that makes SITREP say "Watching …".
   - N30: start RECON hidden / on BLE many times — any `iw` spawn?
   - N31/N32: END with an orphan that exits on its own between match and kill; a keyed record
     naming the session leader or an ancestor.
   - E1: aircraft.json without `now` (file and HTTP), with a future `now`.
3. UI-only rule. Renders at 1280×720, dark + sun, live, for OPS, ATLAS and ENGAGEMENT (HOME unset,
   HOME set, tampered chain). No table blank, strip ≤ 1270 px.
4. Regression: `tests/test_cl4_*.py`, then the full suite once on Python 3.12. Diff assertions
   in `tests/` against `692513f`; any weakened one must be justified.
5. Write `plan/briefs/RA-CL4b-report.md` on `fix/cl4-honest-state`, push, remove the worktree.
   Table per ID, new findings, then one line: MERGE / DO NOT MERGE. Same blockers as RA-CL4.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALQMMsmycF1AqRUye2B`
