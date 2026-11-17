# RA-UIPb — re-audit of the RA-UIP fixes, branch `fix/ui-polish`

**FRESH session, Opus.** Auditor only. Own worktree off `origin/fix/ui-polish`. Read first:
`CLAUDE.md`, `plan/briefs/RA-UIP.md` (the first brief: its hard constraints and blockers still
apply), `plan/briefs/RA-UIP-report.md` on the branch (the findings), then the fix diff
`git diff 5aa0974..origin/fix/ui-polish` (5aa0974 = the RA-UIP report commit). Scope is the
RA-UIP findings and anything the fixes touched; do not re-open closed items unless a fix broke them.

Claims to falsify:

1. **H1 (blocker).** Imagery, range rings and contacts now share one projection: the stitched
   Web-Mercator canvas is resampled per pixel onto `eventbus.to_xy`'s azimuthal-equidistant frame
   (`tiles.aeqd_inverse`, `tiles.reproject`, `TileLayer._build`). Re-run your registration PoC
   (Denver, Fairbanks, a southern-hemisphere HOME, the antimeridian, a view over a pole if reachable
   within ±600 nm; ranges 0–600 nm; views 1 nm to 1200 nm). Is the ground under every contact and
   ring its own? Is `tile_span` still bounded (≤ MAX_TILES except the z3 floor) and still covering
   the view after the bbox change? Is the output size / reprojection cost acceptable for the CM5
   (method stated)? Does `test_u5_imagery_under_a_contact_is_the_contacts_own_ground` actually fail
   on the old equirectangular placement?
2. **M5.** `test_cl1_screen::test_every_page_and_subtab_fits_1280x720` 10/10 alone and in the full
   run. The hub's `eventFilter` now ignores a non-QObject `obj` or non-QEvent `ev` and catches the
   stale-wrapper error from the base call. The root cause (which code leaves a stale `QWidgetItem`
   wrapper) is NOT pinned in the fix: a `takeAt` in `ops.RailCard.clear_body` was tried and ruled
   out (still 2/10). Confirm the guard cannot swallow a real key press (PANIC, 1–9, F, Esc) or hide
   another real error; find the root cause if you can.
3. **M1–M4.** M1: a colourless placeholder tile (`tiles._placeholder`) is never drawn and its cache
   file removed; check real imagery that is nearly grey (snow, salt flats, cloud, night) is not
   thrown away, and what is drawn when every source returns a placeholder. M2: `emergency` flag
   from `adsb_to_contact` → red on MIL too. M3/L5: only USE GPS arms the sign check; a second SAVE
   keeps the typed HOME; 2° band; bools rejected; SAVE is still the only path that sets HOME.
   M4/L10: the shell's hidden background ATLAS prunes but does not redraw; redraws at once on show;
   BUSY edge alerts only once ATLAS has been opened; a standalone ATLAS is unchanged.
4. **Lows fixed:** L1/L2 (OPS captions), L6 (test), L8 (`course` drawn; AIS 360/511 never drawn as a
   direction), L9 (key map). Lows left open: L3, L4, L7 (state whether any must block).
5. Hard constraints as in RA-UIP §1 (passive-only background feed, no gate touched, UI-only).
6. `tests/test_ui_polish.py`, then the full suite once. Baseline as in RA-UIP §4, plus
   `test_cl1_screen::test_up_down_drive_the_list_and_the_detail_follows` (fails the same way on
   `fix/cl8-ship` alone) and the order-dependent `test_cl5_fix2::test_nh_panic_banner…`.
7. Write `plan/briefs/RA-UIPb-report.md` on `fix/ui-polish`, push, remove the worktree. Table per
   finding (CLOSED / OPEN / PARTIAL / REGRESSED · evidence · test), new findings with severity, then
   MERGE / DO NOT MERGE. Blockers as in RA-UIP.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
