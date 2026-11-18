# RA-S2 — cold audit of device-run-2 Stage 2 (OPS, ATLAS, maps), branch `fix/ops-maps` (PR #34)

**FRESH session, Opus.** Auditor only: you write a report, not fixes. Own worktree off
`origin/fix/ops-maps`. Read `CLAUDE.md`, then Stage 2 items 7-10 of `plan/briefs/device-fix-plan.md`,
and the "Device run 2" section of `plan/briefs/device-notes.md` (Dalton's own words) — both on
`origin/docs/briefs`. Scope: `git diff origin/fix/shell-frame..origin/fix/ops-maps -- . ':!plan'`
(Stage 1 is audited separately; only judge it where Stage 2 changed it).

The bar is Dalton's notes, not the plan's wording. For each item, decide whether what he will see on a
1280x720 uConsole screen answers what he wrote (yes / partly / no, with evidence). Render at 1280x720
in DARK, LIGHT and SUN, live (no `--demo`) and demo, and look at the images.

1. **Maps (7).** Root cause: NET defaults OFFLINE and tile fetches were refused silently. Fix: map
   banner says why; DOWNLOAD MAP fetches the visible area once (`netpolicy.grant` +
   `urlopen(granted=True)`, logged "granted", NET mode unchanged); tiles cached and then load offline;
   refetch on NET change. Try to break it: is the grant strictly one-shot and scoped to tiles (could
   any other caller ride it)? Does NET stay OFFLINE afterwards? Does the banner ever lie (blank map
   with no banner; banner over a loaded map; no HOME)? Failed / partial / placeholder tiles? The
   ATLAS and OPS maps both? Cache path stays `uconsole-suite`. This is a NET-policy change: check it
   cannot be used to route around `netpolicy` (operator-initiated, logged).
2. **OPS (8).** Cards open their pages; the empty reason comes from ATLAS feed health (computed even
   while ATLAS is hidden); NEXT PASS from OVERWATCH started at launch (NO TLE / HOME NOT SET /
   predicting… / none in 24 h). Is every empty state honest? Does OPS ever say "SDR —" or nothing?
   Is the OVERWATCH child stopped on close?
3. **Legend (9).** One tight row across the bottom of the OPS scope; 16 px floor; fits at the scope's
   real width in every theme; hidden behind the HOME cover where it should be; no timers in the
   scope (CL8 B5).
4. **SKY DOME (10).** Title, help, key, next pass, column headers, ring labels: does it explain
   itself to someone who has never seen it?
5. Lifecycle: anything new connected (bus, netpolicy, workers, child apps) is stopped/disconnected
   on close. UI-only apart from the operator-granted tile fetch: no decoding or radio change.
6. Run `tests/test_ops_maps.py`, `tests/test_ui_polish.py`, `tests/test_cl8_ship.py`,
   `tests/test_cl1_screen.py`, one file per process (`QT_QPA_PLATFORM=offscreen xvfb-run -a python
   -m pytest -q --timeout=240 --timeout-method=thread`). No full suite (the thread runs it).
7. Write `plan/briefs/RA-S2-report.md` on `fix/ops-maps`: a table per item, new findings with
   severity and a PoC, then MERGE / DO NOT MERGE (only Medium or worse blocks; list Lows that are
   Dalton's call). Push (fetch + merge on reject, never force), remove the worktree.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
