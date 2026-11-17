# RA-UIPd — cold re-audit of the RA-UIPc fixes, branch `fix/ui-polish`

**FRESH session, Opus.** Auditor only. Own worktree off `origin/fix/ui-polish`. Read first:
`CLAUDE.md`, `plan/briefs/device-notes.md` (on `docs/briefs`: the owner's notes),
`plan/briefs/RA-UIP.md` and `plan/briefs/RA-UIPc.md` (hard constraints, claims and blockers still
apply), then `plan/briefs/RA-UIPc-report.md` on the branch, then the fix diff:
`git diff 451e877..origin/fix/ui-polish -- palisade_qt tests` (451e877 = RA-UIPc report).
Read `plan/briefs/UIP-report.md` only at step 6.

RA-UIPc said DO NOT MERGE (H1, M2, M3, M4 + L1–L9). Commit 1e10cc1 claims to fix all of them.
Re-run every RA-UIPc PoC against the new head; then try to break each fix:

1. **H1 / L2 — typed vs GPS HOME** (`system.py` `_typed_home`, `_saved_settings`, `_save_settings`;
   `gpshome.py`). The SETTINGS HOME field must show only the typed (saved) HOME, never a GPS fix.
   SAVE with follow ON and an unchanged field must not move HOME, relabel it `settings`, or persist
   a GPS position. Editing the field while following: is that a deliberate typed HOME (persisted,
   applied) and does the follower then retake HOME on the next fix — is that what the UI tells the
   operator? Follow OFF with a GPS HOME: back to the typed HOME, or (none typed) keep the fix,
   unsaved, and say so. Restart with no fix → typed HOME. Hunt any other path (USE GPS, the
   hemisphere check, the auto-read at launch, demo) that persists a GPS position or stamps it
   `settings`.
2. **M2 / L8 — V cycles ATLAS views through the real hub** (`shell.py` key routing,
   `panels.KEYMAP`). Re-run `v_key_through_the_hub` with a real `QKeyEvent`. V must not be eaten by
   text fields (filter box, SETTINGS inputs, ASSISTANT) and must do nothing harmful on other pages.
3. **M3 / L5 / L6 / L9 — Remote-ID setup needles** (`atlas.RidSource.SETUP_PROBLEMS`,
   `setup_problem`, `_set_setup`, `on_status`). Re-run `setup_needles`: the three false matches
   must now stay faults; the real setup errors (NotReady, not powered, rfkill / soft-hard blocked,
   no adapter, org.bluez not provided / ServiceUnknown, passive needs --experimental) must still map
   to a WARN with the right fix text. Try fresh near-miss strings. Session log gets the raw error.
4. **M4 — moving HOME cost** (`kit/mappanel.BaseMap.set_home`, `_covers`, `_rect0`, `_built`,
   `kit/tiles._work` stale drop, ATLAS `_home_pending` / `set_active`). A GPS move < SHIFT_MAX_NM
   must slide the existing image (no blank, no refetch while it still covers the view), and the
   slide must be geometrically right (AEQD vs a shifted image: quantify the error at the view edge
   for a 5 nm shift at the default and widest zoom). A build started before a HOME change must be
   dropped, never drawn in the new frame. Hidden ATLAS must not rebuild per move, and must show the
   right map the first time it is opened. Zoom/pan after a slide still correct.
5. **L1, L3, L4, L7** as listed in RA-UIPc §3. Then a regression sweep of RA-UIPc's CLOSED claims
   (1a, 1b, 2a–2c, 3a/3b, 4a–4e) — the fix diff touches the same files.
6. Hard constraints as in RA-UIP §1. Gate files untouched; UI-only except `gpshome.py` reading
   gpsd and `eventbus.set_home`. `tests/test_ui_polish.py`, then the full suite once. Baseline
   container failures as in RA-UIP §4; known flakes `test_cl1_fix2` ack-all,
   `test_cl4_gates::test_n21…`, `test_cl1_screen::test_up_down…`,
   `test_cl5_fix2::test_nh_panic_banner…`.
7. Renders at 1280x720 (dark, light · live, demo) of SETTINGS (follow on / off), ATLAS in two
   views, OPS.
8. Write `plan/briefs/RA-UIPd-report.md` on `fix/ui-polish`, push, remove the worktree. Table per
   RA-UIPc finding (CLOSED / OPEN / PARTIAL / REGRESSED · evidence · test), new findings with
   severity, then MERGE / DO NOT MERGE. Blockers: any path where a bad or stale GPS fix sets,
   relabels or persists HOME; any High; any regression of a CLOSED claim.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALRGvWXijhRVAnAZWYH`
