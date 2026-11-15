# CL1 report — screen fit, structure, keyboard, legibility

- **Branch:** `fix/cl1-screen-structure`
- **Branched off:** `docs/audit-2026-11-15` @ `f0e55f3` — **not** `main`. PR #18 was not merged
  when I started (`main` was still `e6184c6`), so per the brief I branched off the audit branch.
- **Code commit:** `1531caf` (code, tests, render size tables). This report and the render script
  are in the commit after it; the branch tip is the final hash.
- **No PR opened** (README step 4). The brief's "PR title" line is for the planner.

Nothing here is closed by my own review. Status below is my claim, for the cold re-audit to
falsify.

## Status per finding

| ID | Status | Where | Regression test (`tests/test_cl1_screen.py`) |
|---|---|---|---|
| D1 | CLOSED | `shell.py:53` (1280×720), `kit/components.py:138` (values wrap), `bench_app.py:83` (ack + gate on their own row), `overwatch.py:52`, `babel.py:473` (desktop minimums removed) | `test_every_page_and_subtab_fits_1280x720` (3 themes × live/demo, slots at their widest), `test_bench_long_reason_does_not_widen_the_window` (the 1845 px PoC), `test_detail_card_values_wrap_and_empty_card_collapses`, `test_no_desktop_fixed_minimums` |
| D2 | PARTIAL | `theme.py:15` (body 18, status 16, caption 13, rows 40), `theme.py:208` (scale), `kit/scope.py:38` and map/PPI labels (16 px) | `test_no_status_bearing_text_under_16px` (3 themes, every page, sub-tab and panel), `test_type_scale_and_row_height`, `test_ui_scale_is_pinned_and_overridable`, `test_plot_text_is_status_size` |
| D3 | PARTIAL | `kit/topbar.py:16` (one 40 px strip), `kit/subtabs.py:10` (vertical sub-tabs), rail + footer deleted from `shell.py` | `test_one_top_strip_no_rail_no_footer`, `test_focus_and_checked_states_are_visible` |
| D4 (status slots) | CLOSED, one state missing | `chrome.py:66`, `kit/topbar.py:74` and `:298`, `app.py:137` (page status row), `panels.py:506` (DEMO border), `theme.py:86` (disabled style) | `test_four_fixed_status_slots_exist_with_word_and_shape`, `test_pages_cannot_overwrite_the_status_slots` (the H7 "5 AP" PoC), `test_slots_follow_engine_state`, `test_tx_safe_is_retired_and_bench_permit_shows_in_the_tx_slot`, `test_demo_draws_a_border_and_live_does_not`, `test_disabled_buttons_look_disabled` |
| D7 | CLOSED | `ops.py:27` (8 keys + labels), `pages.py:19-35` (composites), `shell.py:45` (folded callsigns), `sweep.py` | `test_eight_keys_in_order_with_function_labels`, `test_folded_pages_live_where_the_brief_put_them`, `test_composite_child_is_only_active_while_its_tab_is_in_front` |
| D8 | CLOSED | `shell.py:333` (key routing), `shell.py:277` (PANIC), `panels.py:389` (key map), `panels.py:431` (palette), `kit/feed.py:82,103`, `theme.py:83-86` | `test_every_page_key_parses_to_a_real_key` (the `QKeySequence("10")` PoC), `test_keyboard_only_walk_reaches_every_page_and_subtab`, `test_up_down_drive_the_list_and_the_detail_follows`, `test_enter_runs_the_primary_action_and_typing_is_never_stolen`, `test_band_and_span_keys_in_prism`, `test_key_map_and_command_palette`, `test_panic_key_disarms_ends_engagement_and_kills_children`, `test_panic_works_while_typing`, `test_navigation_leaves_focus_on_the_page_not_on_a_nav_key` |
| D9 | PARTIAL | `theme.py:44` (SUN), tokens at `theme.py:20-43`, `forge.py:290,329,364`, `recon.py:133`, `bench_app.py:145`, `panels.py` (`EngagePanel._activate`) | `test_sun_theme_is_black_and_white_at_7_to_1_with_2px_borders`, `test_light_and_dark_status_colours_meet_contrast`, `test_green_means_receiving_only_not_authorized_or_armed` |
| D10 | CLOSED | `panels.py:278,341` (alert history + drawer), `ops.py:303`, `prism.py:214` (send to tuner), `kit/components.py:172` (collapse) | `test_alerts_persist_until_acknowledged_not_capped_at_three`, `test_prism_peak_can_be_sent_to_the_tuner`, `test_detail_card_values_wrap_and_empty_card_collapses` |
| §9 RADIOS panel | PARTIAL (read-only, as briefed) | `panels.py:76`, `radios.py:64` | `test_radio_inventory_reads_presence_and_power`, `test_radios_panel_opens_from_the_radio_slot_and_frees_the_holder` |
| §9 audio control | CLOSED, not verified on the device | `kit/audio.py:22`, `kit/topbar.py:261` | `test_volume_slider_and_mute_drive_the_real_sink`, `test_audio_backends_build_argv_lists`, `test_no_audio_sink_disables_the_controls_instead_of_pretending` |

Why the PARTIALs:

- **D2.** Body, status and row sizes are done and enforced. Two things are not: captions are
  under 16 px on purpose (slot captions 10 px, nav labels 11 px, section captions 13 px), and the
  "device scale factor appropriate to ~294 ppi" is an interpretation — see open questions. Nothing
  was measured on the device.
- **D3.** Chrome is one strip and sub-tabs are vertical. I did not rework pages into three columns
  (list · scope · detail); pages keep the splits they had. PRISM and SWEEP are single-pane.
- **D4.** The RADIO slot never shows `ACQUIRING`: the arbiter has no such state (that is A3, CL5),
  and adding one is engine work. The slot handles it if the arbiter ever reports it.
- **D9.** Word + shape pairing is done for the status slots, gate lines and the OPS alert card.
  Tables still colour a word (PASS/FAIL, severity) rather than adding a shape. Card-against-
  background contrast was raised by strengthening borders (3:1), not by changing the surfaces.
- **RADIOS.** Presence and power are read from the kernel and shown; nothing can be switched on or
  off, and the device picker is disabled with a note. That is what the brief asked for in this
  cluster.

## What was moved (mechanically, behaviour unchanged)

| From | To | Worker owner |
|---|---|---|
| OVERWATCH sky dome, passes | ATLAS sub-tabs SKY DOME, PASSES | still `OverwatchApp` |
| OVERWATCH radio view (holder, FREE THE RADIO, history) | `panels.RadiosPanel` | no worker |
| BABEL | PROWL sub-tab DECODE | still `BabelApp` |
| RECON COUNTER (4 detectors) | SWEEP page (`sweep.py`) | `DetectorWorker` class stays in `recon.py`; the four instances are now started by `SweepApp` instead of `ReconApp` |
| RECON ENGAGE | `panels.EngagePanel`, opened from the ENGAGEMENT slot | no worker |
| BENCH | SYSTEM sub-tab BENCH | still `BenchApp` |
| MORE (settings, doctor, assistant, mesh, sitrep) | SYSTEM sub-tabs | still `MoreApp` |

The old callsigns still resolve: `hub.open_callsign("BABEL")` opens PROWL on DECODE.

Two behaviour-adjacent changes that came with the moves, so the re-audit can judge them:

- The detector alert source on the bus is now `"SWEEP"` (was `"RECON"`).
- RECON's gated cards used to refresh when the ENGAGE tab was used. They now refresh when the shell
  sees the engagement change (a 500 ms poll of `engagement.info()`, plus directly after the panel
  or PANIC). FORGE's cards are untouched and still stale after END (G12, CL2).

## What the brief got wrong, or what I had to interpret

1. **Eight keys with labels do not fit one 40 px row at 16 px.** Callsign + label for eight keys
   plus four slots, alerts, mute, volume and clock is about 1,600 px in a single line. I made each
   key two lines (callsign 16 px, label 11 px under it) and shortened two labels: "counter-surv"
   and "survey+assess". Worst-case strip width is now 1,228–1,235 px. The full label is in the
   tooltip.
2. **"Nothing status-bearing under 16 px" needs a definition.** I treated static names (captions,
   nav labels, slot captions) as not status-bearing and everything else as status-bearing. The test
   encodes exactly that split (`CAPTION_CLASSES`).
3. **"Set a device scale factor appropriate to ~294 ppi."** The sizes in the brief (16/18/40) only
   make sense as physical pixels on a 1280×720 canvas, so I pinned the scale to 1.0 and turned
   desktop auto-scaling off, with `PALISADE_UI_SCALE` to override. A factor above 1 would shrink
   the canvas and break the fits-1280×720 test.
4. **RADIO `ACQUIRING`** cannot be shown without changing the arbiter (see D4 above).
5. **TX `PERMITTED`** has no engine-level source. The shell shows it when a page reports that its
   own gate passes; today only BENCH does. `ARMED` and `OFF` come from `txguard`.
6. **PANIC "kill child processes"** has nothing registered to kill (that is G11). It sends SIGTERM
   to every direct child of the app, which includes receive decoders. Their workers may respawn
   them (R2).
7. **README says render dark / light / sun × live / demo "before".** There is no sun theme on main,
   so the before set is dark and light only. BENCH and MORE in the before set are 1845 px wide —
   that is the D1 bug, not a render error.
8. **Suite command.** README says `xvfb-run -a python3 -m pytest -q tests`; the Mac has no xvfb, so
   I ran `QT_QPA_PLATFORM=offscreen python3.12 -m pytest -q tests`.

## Found, not fixed (outside CL1)

| Severity | What | Where |
|---|---|---|
| High | SWEEP is now one key away and still cannot detect anything live: the detectors have no feed and the table is blank while they are offline. Promoting the page makes H1/D5 more visible, not fixed. In demo the table is also blank until a detector happens to fire. | `sweep.py`, `recon.py` `DetectorWorker.step` |
| Medium | Moving BABEL under PROWL does not change R1: open DECODE once and BABEL keeps the radio, so SCAN/FM/NWR on the same page show RADIO BUSY. | `babel.py` |
| Medium | The four detectors all write the same page-status key, so the row shows whichever reported last (H1's overwrite, now confined to SWEEP). | `sweep.py`, `app.py:137` |
| Medium | Bus events still carry no demo marker and most workers still default to `demo=True` (rest of H7). The shell-owned DEMO slot and border are the only part done here. | — |
| Low | In SUN, placeholder text in a disabled field renders lighter than 7:1 (Qt draws placeholders at reduced opacity). | `theme.py` |
| Low | `kit.StatusHeader` lost its chip styling when the old chip classes were removed; only dead `more.py` uses it (C5). | `kit/components.py` |
| Low | `tests/test_palisade_qt.py` has three pyflakes warnings that are also on main (lines 181, 202, 1490). Not touched. | — |
| Info | Feed-table changes needed for keyboard navigation overlap B4 (CL8): selection now follows the cursor row and survives a refresh by row index. Restoring by key, and scroll position, are not done. | `kit/feed.py:82-103` |

## Suite and lint

```
$ QT_QPA_PLATFORM=offscreen python3.12 -m pytest -q tests
910 passed, 12 skipped, 2 warnings in 258.14s (0:04:18)

$ python3.12 -m pyflakes palisade_qt/ tests/test_cl1_screen.py plan/briefs/CL1-renders/render.py
(clean)
```

- Run on the Mac, Python 3.12, PySide6 6.12, offscreen. **Not run on Python 3.13 and not run on the
  uConsole** — there is no 3.13 interpreter on this machine.
- The two warnings are a skyfield/NumPy deprecation, present on main.
- 40 tests are new (`tests/test_cl1_screen.py`); 11 existing tests in `tests/test_palisade_qt.py`
  were updated for the new structure (they asserted the old rail, callsigns and "TX SAFE").

## Screenshots

PNG files are git-ignored in this repo (`.gitignore:8`, `*.png`) and no PNG is tracked anywhere,
so I did not force-add them. On the Mac they are at:

- `plan/briefs/CL1-renders/before/` — 40 PNGs, main's ten pages, dark + light × live + demo
- `plan/briefs/CL1-renders/after/` — 180 PNGs: 25 page/sub-tab views + 5 panels, dark + light +
  sun × live + demo, every one exactly 1280×720

Committed, so the planner can check sizes without the images:
`plan/briefs/CL1-renders/{before,after}/sizes_<theme>_<mode>.json` (grab size and hub minimum size
per view) and `plan/briefs/CL1-renders/render.py`, which regenerates the after set:

```
python3 plan/briefs/CL1-renders/render.py <outdir> <dark|light|sun> <live|demo>
```

## Open questions for the owner

1. **Screenshots.** Do you want the 220 PNGs (15 MB) force-added to this branch so the planner and
   re-auditor can see them on GitHub, or is regenerating with `render.py` enough?
2. **PANIC key.** I picked `F12`. If F-keys on the uConsole need the Fn layer, that is a two-key
   chord, not one key. Which physical key should it be?
3. **Nav labels.** Are "counter-surv" and "survey+assess" at 11 px acceptable, or do you want full
   labels at the cost of a second strip row (about 20 px of height)?
4. **UI scale.** Is 1.0 right on the device, or should the default be larger with the layout
   re-fitted to a smaller logical canvas?
5. **PANIC and receive decoders.** Should PANIC kill receive pipelines too (it does now), or only
   transmit-capable children once CL2 registers them?
6. **Bus source rename.** Detector alerts now come from `"SWEEP"` instead of `"RECON"`. Keep, or
   revert until CL7?
