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

---

## Planner follow-up (commit after `a716e2f`, run here on Python 3.13.18 / PySide6 6.12 / xvfb)

Decisions on the open questions, applied in this commit so the re-audit sees one branch:

| # | Question | Decision |
|---|---|---|
| 1 | Force-add 220 PNGs? | **No.** Binary renders stay out of the repo. Before/after contact sheets were sent to the owner directly; `render.py` regenerates the set. |
| 2 | PANIC key | **Shift+Esc is the primary PANIC chord** (no Fn layer, one hand, top-left of the uConsole keyboard); F12 stays as an alias. |
| 3 | 11 px nav labels | **Rejected — nothing in the strip may be under 16 px.** At ~294 ppi an 11 px caption is under 1 mm tall. Nav keys are now one line, `<n> CALLSIGN` at 16 px; the function word is in the tooltip, the key map (`?`) and the palette (`/`). Status-slot captions are inline at 16 px (`SDR`, `TX`, `ENG`); MODE and ALERTS need none (the word / the triangle is the caption). Worst-case strip width 1268 px. |
| 4 | UI scale 1.0 | **Correct.** The brief's sizes are physical pixels on the 1280×720 panel; Qt's DPI auto-scaling would shrink the canvas. Keep `PALISADE_UI_SCALE` as the override. |
| 5 | PANIC and receive decoders | **PANIC stops everything, receive included.** That is the point of a panic key; CL2's registry will make the kill list explicit, not narrower. |
| 6 | Bus source `"SWEEP"` | **Keep.** The source is the key the operator will look at. |

Also in this commit:

- **Owner rule (2026-11-15): all maps are DARK or SAT.** `kit/mappanel.py` offers only those two
  (`STYLES = ["dark", "satellite"]`), defaults to DARK in every theme including light and SUN,
  and the offline fallback is black, never a light scope. Test: `test_maps_are_dark_or_satellite_only`.
- `OWNER_LABELS` shortened to ≤ 8 characters (`PROWL SC`, `PROWL FM`, `PROWL WX`, `SSTV`) so
  the owner is the SDR slot's state word; `HELD` is in the tooltip.
- **Reliability fix found while running on 3.13:** `test_all_callsigns_build_in_both_themes`
  segfaulted 1 run in 3 (`Shiboken::BindingManager::runDeletionInMainThread`). A page that
  becomes cyclic garbage is collected by whichever thread triggers the GC — a worker QThread —
  and shiboken then deletes a QWidget off the GUI thread. Pages and their joined workers are
  now retained for the life of the process (`app._retain`), which is what the running app does
  anyway. Reproducer `/tmp/crash.py`-style loop (40 × build/start/stop of every page) went
  from crashing by iteration ≤ 3 to 4 × 40 clean. This is R-class territory and should be
  re-checked under CL2.
- New tests: `test_maps_are_dark_or_satellite_only`, `test_strip_has_no_text_under_16px_at_all`.

Suite on this machine (Python 3.13.18, xvfb, no `tkinter`):
`xvfb-run -a python3 -m pytest -q tests` → **912 passed, 1 failed, 4 skipped, 7 errors** (9:16). Two failures are pre-existing on `main` and unrelated to CL1:
`tests/test_audit_tiles.py::test_undecodable_tile_is_marked_failed` (fails on `main` too) and
the seven `tests/test_shell.py` errors (`No module named 'tkinter'` in this container).

---

## CL1-fix (after RA-CL1: DO NOT MERGE)

Brief: `plan/briefs/CL1-fix.md`. Same branch, no PR change. RA-CL1's evidence (result JSON + PoC
scripts) is committed at `plan/briefs/CL1-reaudit-evidence/` (`fd4d320`); PNGs and the 64 source
trees the auditors copied for mutation are not.

**Branch:** `fix/cl1-screen-structure` · code + tests in the commit after `fd4d320` (hash in the
push message below).

### Fail-first and teeth

All new tests are in `tests/test_cl1_fix.py` (38 tests). I ran that file against the pre-fix tree
(`git archive fd4d320`, the new test file copied in): **32 failed, 6 passed**. The 6 that passed
pin behaviour that was already right (items 11, 13-rail, 17, 18), and a few base failures were for
an API reason rather than the defect (items 14 slot colours, 15 OPS card). Every one of those got a
mutation check instead: break the fix in a copy of the fixed tree, run the test, expect a failure.
**17 of 17 mutations killed** (two added after the render check below). Script and raw output: `plan/briefs/CL1-fix-evidence/`
(`mutate.py`, `mutations.txt`, and `base_failfirst.txt` for the pre-fix run).

| Mutation | Test that fails |
|---|---|
| a 150 px rail beside the page stack | `test_no_rail_the_page_starts_at_the_window_edge` |
| detail values `setWordWrap(False)` | `test_detail_values_wrap_instead_of_widening` |
| sub-tab rail laid out horizontally | `test_sub_tabs_are_a_vertical_rail_left_of_the_page` |
| `R` key removed | `test_r_e_m_keys_and_panic_with_a_panel_open` |
| PANIC does nothing while a panel is open | `test_r_e_m_keys_and_panic_with_a_panel_open` |
| PROWL FM `[` `]` removed | `test_bracket_keys_step_prowl_scan_bank_and_fm_frequency` |
| SWEEP detectors never `start()` | `test_detectors_start_when_sweep_opens_and_not_before` |
| ARMED slot painted `live` (green) | `test_armed_and_active_slots_are_never_green` |
| ENG ACTIVE slot painted `live` | `test_armed_and_active_slots_are_never_green` |
| OPS alert card shows nothing | `test_ops_alert_card_shows_newest_unacknowledged_alerts` |
| a dark BABEL colour under 4.5:1 | `test_babel_protocol_colours_are_readable[dark]` |
| PANIC calls `chrome.reset()` again | `test_panic_leaves_tx_slot_on_the_real_bench_gate_and_says_ack_not_revoked` |
| `FONT_CAPTION = 13` | `test_rendered_text_is_16px_or_more_everywhere_…` |
| table header 10 px | `test_rendered_text_is_16px_or_more_everywhere_…` |
| plot axis ticks 9 px | `test_rendered_text_is_16px_or_more_everywhere_…` |

(A first version of the PANIC-with-panel mutation broke only one of PANIC's two routes and
survived; the route it left intact still fired PANIC, so it was not a real break. The mutation
above makes PANIC inert and is killed.)

### Status per item

| # | Item | Status | Where | Tests |
|---|---|---|---|---|
| 1 | PANIC kill: whole tree, verified count | CLOSED | `palisade_qt/procs.py` (`stop_tree`, `alive`, `describe`); `shell.py` `panic()`; `start_new_session=True` added to ATLAS APRS/AIS and PRISM `rtl_power` spawns (PROWL and BABEL already had it) | `test_panic_stops_every_pipeline_member_and_counts_only_verified[True/False]` (real `sh -c 'sleep \| sleep'`, with and without its own session), `test_panic_never_counts_a_signal_as_a_kill`, `test_decoder_pipelines_start_in_their_own_session`, `test_panic_never_signals_its_own_process_group` |
| 2 | PANIC TX display reads the real gate | CLOSED (display); revocation handed to CL2 | `shell.py` `panic()` no longer calls `chrome.reset()`; `bench_app.py` `on_gate_changed` re-reads `bench.preflight`; banner adds "BENCH ack not revoked — TX still PERMITTED" | `test_panic_leaves_tx_slot_on_the_real_bench_gate_and_says_ack_not_revoked` |
| 3 | Mute / volume honest, off the UI thread | CLOSED (unverified on device) | `kit/audio.py` `AudioController` (one daemon thread, every set followed by a read-back); `kit/topbar.py` `_mute_clicked`, `_on_mixer`, `_show_audio` | `test_mute_shows_muted_only_after_the_read_back_says_so`, `test_failed_mixer_command_shows_a_fault_and_the_true_state`, `test_unreadable_mixer_shows_unknown_never_zero_and_unmuted`, `test_a_hanging_mixer_does_not_freeze_the_ui` (2 s hang: GUI timer keeps ticking, click returns < 0.3 s) |
| 4 | Alerts drawer acts by alert id | CLOSED | `panels.py` `AlertStore` ids + `ack(id)`; `AlertsDrawer.selected_id/select_id/ack_selected` | `test_alert_arriving_while_drawer_open_does_not_get_acked_in_place_of_the_selected_one` |
| 5 | Slots never elide the varying part | CLOSED | `kit/topbar.py` `StatusSlot` (no character cap; `painted_text()`); `chrome.scope_summary` (one target ≤ 10 chars shown as itself, else "N targets") | `test_slots_paint_the_whole_owner_and_scope_never_an_ellipsis` (asserts the painted text for every owner label and scope form, and that all owners paint differently); `test_every_page_and_subtab_fits_1280x720` now uses the real worst case |
| 6 | Readers fail to UNKNOWN | CLOSED | `chrome.read_tx` / `read_engagement`; `topbar` `unknown` shape (dashed ring + bar), amber | `test_unreadable_engines_show_unknown_not_the_all_clear` |
| 7 | PANIC through popups and modifiers | CLOSED | `shell.py` `eventFilter` checks PANIC before the focus/target test, accepts a popup opened from the hub, closes it | `test_panic_works_with_a_combo_dropdown_open`, `test_panic_works_with_a_context_menu_open_and_with_modifiers_held` |
| 8 | ENGAGEMENT panel | CLOSED | `panels.py` `EngagePanel`: 1040×640, card sized to its text, evidence table ≥ 3 rows, TARGETS row | `test_engagement_panel_shows_whole_scope_three_evidence_rows_and_banner_parity` |
| 9 | Alert cap never drops unacknowledged | CLOSED | `panels.py` `AlertStore._trim` drops acknowledged alerts only | `test_alert_cap_never_drops_an_unacknowledged_alert` |
| 10a | Sky-dome labels | CLOSED | `overwatch.py` `SkyDome.label_rect` (font-sized, kept inside the dome) | `test_sky_dome_labels_are_font_sized_and_stay_inside_the_dome` |
| 10b | Focus ring: active nav key, map style combo | CLOSED | `theme.py` `navkey_on:focus`, `subtab:focus`; `kit/mappanel.py` combo `:focus` | `test_focus_ring_is_visible_on_the_active_nav_key_and_the_map_style_combo` (compares rendered pixels with and without focus) |
| 10c | No green on PROWL demo data | CLOSED | `prowl.py` DEMO statuses neutral; hot rows accent in demo | `test_prowl_demo_data_is_never_painted_green` |
| 10d | Feed columns not elided | CLOSED | `kit/feed.py` `fit_columns` (measured widths; a wide table scrolls) | `test_feed_columns_get_real_widths_even_when_filled_while_hidden` |
| 11 | D1 pins | CLOSED | (behaviour unchanged) | `test_no_rail_the_page_starts_at_the_window_edge`, `test_detail_values_wrap_instead_of_widening` |
| 12 | D2 measured on real widgets | CLOSED | `theme.py` `FONT_CAPTION = 16`, `QHeaderView` font set | `test_rendered_text_is_16px_or_more_everywhere_including_captions_headers_and_plots`; `test_no_status_bearing_text_under_16px` now exempts nothing |
| 13 | D3: OPS scope, vertical rail test | CLOSED | `ops.py` `_fit_scope` keeps the scope column square; `kit/ppi.py` padding 0.02 | `test_ops_scope_has_at_most_24px_dead_space_each_side` (measured ~10 px), `test_sub_tabs_are_a_vertical_rail_left_of_the_page` |
| 14 | D9: never-green test; BABEL colours | CLOSED | `babel.py` `proto_colors()` per theme | `test_armed_and_active_slots_are_never_green[*]`, `test_babel_protocol_colours_are_readable[*]` |
| 15 | D10: empty cards collapse; OPS card test | CLOSED | `kit/components.py` `DetailCard`: the card keeps its slot, the drawn box (`.box`) shrinks to title + hint when empty; `ops.py` `RailCard.clear_body` hides old rows before deleting them | `test_empty_detail_cards_collapse_in_live_pages` (every live page/sub-tab: no empty drawn card over 110 px, was 214–636; and none shorter than its own content), `test_ops_alert_card_shows_newest_unacknowledged_alerts` (incl. no stale rows painted underneath) |
| 16 | RADIOS refresh while visible | CLOSED | `panels.py` `RadiosPanel` 2 s poll while shown, stopped when hidden | `test_radios_panel_rereads_the_kernel_while_visible` |
| 17 | Keys R E M `[` `]`, PANIC with a panel open | CLOSED | (behaviour unchanged) | `test_r_e_m_keys_and_panic_with_a_panel_open`, `test_bracket_keys_step_prowl_scan_bank_and_fm_frequency` |
| 18 | Detectors start when SWEEP opens | CLOSED, **intended** | `sweep.py` (unchanged): detectors start on SWEEP's first show; RECON no longer starts them. On `main` they started on RECON's first show; nothing starts them at launch on either. | `test_detectors_start_when_sweep_opens_and_not_before` (also asserts the four threads are joined when the hub closes) |

"CLOSED" here is my claim; RA-CL1b decides.

### Item 12: why the earlier test passed with 10 / 11 / 13 px on screen

`test_no_status_bearing_text_under_16px` did measure real widgets, but it skipped every label whose
class was in `CAPTION_CLASSES = {"micro", "navlabel", "navlabel_on", "slotcap"}` — exactly the
classes the audit measured at 13, 11 and 10 px. It could not fail on them by construction. And
`test_type_scale_and_row_height` asserted module constants against literals, not widgets. Now the
set is empty, captions are 16 px, the header's own font is set so its size is measurable, and the
new test reads `QFontInfo` of every visible label, button, input and header on every page plus the
pyqtgraph axis tick fonts.

### Decisions I had to make (flag if wrong)

- **ENG slot word is the scope, not "ACTIVE · scope".** With both, the worst case strip was
  1325 px. Following the planner's RADIO-slot rule (the owner *is* the word), the ENG slot paints
  the scope summary — `ENG ◆ 10.0.0.*`, `ENG ◆ 6 targets` — with the amber diamond meaning
  active; "ACTIVE" and the engagement name are in the tooltip and the panel. A single target is
  shown as itself up to 10 characters (`chrome.SCOPE_CHARS`), else the count. Worst-case strip is
  now within 1280 − 12 px (demo border) in all three themes.
- **Strip spacing tightened by a few px** (layout spacing 2 → 1, nav key inner margin 2 → 1, slot
  spacing 4 → 3) to make that fit. Nothing under 16 px.
- **Mixer worker is a daemon `threading.Thread`, not a `QThread`.** A hung mixer call must not
  hold up exit, and a QThread that outlives its join aborts the process (A2). The controller and
  thread are retained for the process (the `_retain` rule), results come back over a queued Qt
  signal.
- **PANIC process stop blocks the GUI for up to ~2.5 s** (SIGTERM, 1.5 s wait, SIGKILL, 1 s wait),
  only when something refuses to die. A stop key that returns before it knows is the defect being
  fixed.
- **An empty detail card keeps its slot; only the drawn card shrinks** to title + hint at the top
  of it. My first version shrank the whole widget, and the render check showed what that does:
  on PROWL FM the page layout spread the freed height between the remaining widgets, so the tune
  bar floated mid-page, and on PROWL DECODE the collapsed MESSAGE card clipped its own title (its
  height was computed before the 16 px stylesheet font applied). Both fixed; see "Render check".

### Hand to CL2

- **PANIC cannot revoke the BENCH conducted-TX acknowledgement.** `txguard.arm(False)` does not
  affect `bench.preflight` (bench policy does not consult arm), and there is no gate API to clear
  the ack. Per the brief I added none: the TX slot keeps showing PERMITTED from the real gate, and
  the banner says "BENCH ack not revoked — TX still PERMITTED".
- PANIC's kill list is still "every child of this process"; CL2's registry should make it explicit.

### Found, not fixed

- **ATLAS's own stop still terminates only the `sh` wrapper** of its APRS/AIS pipelines
  (`atlas.py` `_proc.terminate()`), so a normal page stop can leave `rtl_fm`/`multimon-ng`
  running. PANIC now stops them; ordinary stop is CL5 (R-class).
- **Side effect of `start_new_session=True`:** a decoder in its own session does not get the
  terminal's SIGHUP if PALISADE crashes, so it can outlive a crash. PROWL and BABEL already
  behaved this way; ATLAS and PRISM now do too. CL5 should own decoder cleanup on abnormal exit.
- The ~25 Low items from RA-CL1 are skipped per the brief. The 19 that were never independently
  verified: see `reaudit_result.json` → each group's `new_low_unverified`.

### Not checked here (owner, on the device)

Python 3.13, the uConsole itself, a real window manager (`main()` calls `show()`, not
`showFullScreen()`, so a title bar could push the bottom status row off the 720 px panel), and real
map tiles. None of these is claimed. One command on the uConsole:

```
cd ~/SentryHub && git fetch && git checkout fix/cl1-screen-structure && git pull && xvfb-run -a python3 -m pytest -q tests && python3 -m palisade_qt.shell
```

(the suite on 3.13, then the app on the real panel: check the bottom row is visible, press `M`,
open `R` with the dongle in and out, and press Shift+Esc with a dropdown open.)

### Render check (1280×720, dark / light / sun × live / demo)

`plan/briefs/CL1-renders/render.py` now also renders a stress pass (engagement with a six-target
scope, radio held by PROWL SCAN, 12 alerts: `stress-ops`, `stress-panel-{engagement,alerts,radios}`),
34 views per theme/mode. A sonnet agent ran all six sets and looked at 30 images. What it found,
and what I did:

| Found | Cause | Action |
|---|---|---|
| OPS alerts card: first row drawn over an older row (all themes) | `RailCard.clear_body` only `deleteLater()`-ed old rows; they stayed painted until the event loop deleted them. Pre-existing, made visible by the stress render | Fixed (hide + unparent first); test + mutation |
| PROWL FM: tune bar floating mid-page between gaps | my first card-collapse | Fixed (card keeps its slot) |
| PROWL DECODE: collapsed MESSAGE card clips its title | my first card-collapse | Fixed; test asserts no collapsed card is shorter than its content |
| RADIOS table: Wi-Fi/Bluetooth OWNER cell "not arbitra…" | last (stretched) column of a 900 px panel | Not fixed: static text, not state. Found-not-fixed (Low) |
| ATLAS contact table scrolls sideways; ALT at the right edge | measured column widths (item 10d): a wide table now scrolls instead of eliding | Intended trade-off; flag if the owner prefers fewer columns |
| ATLAS map labels overlap at the centre (demo) | RA-CL1 Low (`kit/mappanel.py`), skipped per brief | Found-not-fixed |
| Nav keys sit close together; slider next to the clock | strip spacing tightened to fit the scope in the ENG slot | Cosmetic; flag |

No "…" in any top-strip slot in the 30 images. Every PNG is exactly 1280×720 (script check, all six
sets). The re-render after the fixes is listed below with the final suite run. PNGs are git-ignored;
`render.py` regenerates them.

### Suite, lint, renders (final tree, this Mac: Python 3.12.16, PySide6 6.12, Qt offscreen)

```
QT_QPA_PLATFORM=offscreen python -m pytest -q tests
951 passed, 12 skipped, 2 warnings in 227.97s (0:03:47)
```

(913 before this work + the 38 tests in `tests/test_cl1_fix.py`. No xvfb on this Mac; the
offscreen platform is the headless equivalent. Not run on Python 3.13 — see "Not checked".)

`pyflakes palisade_qt tests/test_cl1_fix.py tests/test_cl1_screen.py plan/briefs/CL1-renders/render.py`
→ clean. `tests/test_palisade_qt.py` still has its three pre-existing warnings (lines 181, 202,
1490), untouched.

Re-render after the fixes (all six sets, `render.py` with `HOME` redirected): every line
`<theme> <mode> 34 shots; not 1280x720: none`. I looked at `stress-ops` (sun live),
`prowl-fm` (light live), `prowl-decode` (sun live) and `stress-panel-engagement` (dark demo)
after the fix: no overlapping row, the FM page packs to the top, the MESSAGE card shows its
title, and the ENGAGEMENT panel shows name, operator, authorization, 6 targets, the whole scope
and five evidence rows. Regenerate with
`python3 plan/briefs/CL1-renders/render.py <outdir> <dark|light|sun> <live|demo>`.

### Model tiers used (owner rule)

| Stage | Model |
|---|---|
| Implementation, tests, verdicts in this report | session model (Opus 5.5) |
| Suite, pyflakes, fail-first and mutation runs | no agent — run directly in the shell |
| Render sweep (6 runs) + visual check of 30 views | sonnet (1 agent) |
| Re-render after the fixes + check of the 4 affected views | session model, directly (no agent) |
| Inventory / search | none needed |

---

## CL1-fix2 — closing RA-CL1b (branch `fix/cl1-screen-structure`, on `5cbc1de`)

Brief: `plan/briefs/CL1-fix2.md`. Tests: `tests/test_cl1_fix2.py`. Every new test failed on `5cbc1de`
(13 of 15 then; the 2 N10 tests passed because the behaviour was already right; they are proven
by mutation below). Python 3.12.16 venv, PySide6 6.12.0, Qt offscreen.

| Item | Status | Where | Test |
|---|---|---|---|
| N1 ATLAS fits, never clips a value | CLOSED | `atlas.py`: TYPE column dropped (type is on the map colour + label, the layer chips and the detail card); `kit/feed.py` `FeedTable(fit_viewport=True)`: every section sized explicitly to the viewport (refit on viewport resize, needs clamped to the header minimum), sideways scroll off, too-wide values elide with "…", every cell's tooltip is its full value | `test_atlas_table_fits_without_hscroll_and_never_clips_a_value[dark/light/sun]` (with a 30-char ID and a 6-digit altitude injected) |
| N2 selection follows the item | CLOSED | `kit/feed.py` `row_key` (`_id`, else the row's whole content), `_remember_row`/`_restore_row` re-select by key, emit `selected` with the fresh row (detail follows), clear the highlight if the item is gone. ATLAS rows carry `_id` | `test_feed_selection_follows_the_item_across_a_resort_and_the_detail_matches`, `test_atlas_keeps_the_same_aircraft_selected_when_it_resorts` |
| N10 PANIC escalation + group kill pinned | CLOSED | (behaviour unchanged) | `test_panic_kills_a_pipeline_that_ignores_sigterm` (real `sh -c "trap '' TERM; sleep \| sleep"`), `test_panic_group_kill_reaches_members_the_snapshot_missed` (same pipeline, child listing blinded so only `killpg` reaches the members) |
| N3 PANIC revokes the BENCH ack | CLOSED | `app.py` `on_panic()` hook (composite forwards); `bench_app.py` `on_panic` unchecks the ack (pure UI; the gate then refuses on its own logic); `shell.py` `panic()` calls the hook, re-reads, and the banner reports `chrome.read_tx()` — `TX OFF`, or `TX still PERMITTED (<source>)` if any gate still passes. The "ack not revoked" path is gone | `test_panic_unchecks_the_bench_ack_and_the_slot_reads_the_gate`, `test_panic_banner_reports_a_permit_that_survives` |
| D7 function label beside every key | CLOSED | `kit/topbar.py` `NavKey`: callsign over label, both 16 px, placed by measured ink (`tightBoundingRect`), 2 px gap; labels `home · map · spectrum · listen · sweep · survey · hardware · settings` (`ops.py`); nav focus ring keeps full width left/right, normal border width top/bottom (`theme.py`) so no ring covers a glyph | `test_every_nav_key_shows_its_function_label_beside_the_callsign[dark/light/sun]` — compares the strip's painted pixels with the same text drawn unclipped, per line, ≥ 99 %; checks ≥ 16 px, ≤ 40 px strip, ≤ 1280 px |
| Item 6 panels fail to UNKNOWN | CLOSED | `panels.py` `RadiosPanel._refresh_holder/_refresh_table`, `EngagePanel.refresh/render_actions`: a raising read shows `◌ UNKNOWN` (amber) with the error, never FREE / NONE; FREE THE RADIO disabled | `test_radios_panel_shows_unknown_when_the_arbiter_read_raises`, `test_engagement_panel_shows_unknown_when_the_engine_read_raises` |
| Ack all = seen only | CLOSED | `panels.py` `AlertStore.ack_all(upto_id)`; `AlertsDrawer.open` snapshots the newest id shown, `ack_all_seen` acks up to it (button "ACKNOWLEDGE ALL SEEN"; count line says how many arrived since opening); palette "Acknowledge all alerts" uses the same rule | `test_ack_all_never_acks_an_alert_that_arrived_after_the_drawer_was_viewed` |
| RA-CL1b N4 (Low) | CLOSED | `chrome.STATE_WORDS`: a single target spelled like a state word shows as `1 target` | `test_a_scope_target_spelled_like_a_state_word_is_never_the_slot_word` |

Superseded tests: `test_cl1_fix.py::test_panic_leaves_tx_slot_on_the_real_bench_gate_and_says_ack_not_revoked`
retired (owner decision 1 reverses it; comment left in place). `test_cl1_screen.py::test_eight_keys_…`
now asserts the label is drawn.

### Mutations (each applied to a copy, `tests/test_cl1_fix2.py` run)

| Mutation | Caught by |
|---|---|
| no SIGKILL fallback (`procs.py`) | `test_panic_kills_a_pipeline_that_ignores_sigterm`, `test_panic_group_kill_…` |
| no `killpg` (`procs.py`) | `test_panic_group_kill_reaches_members_the_snapshot_missed` |
| nav lines overlap (GAP −8) | `test_every_nav_key_shows_its_function_label_…[all 3]` |
| nav key 8 px shorter | `test_every_nav_key_shows_its_function_label_…[all 3]` |
| restore by row number | `test_feed_selection_follows_…`, `test_atlas_keeps_the_same_aircraft_…` |
| ATLAS `fit_viewport=False` | `test_atlas_table_fits_…[all 3]` (survived before the long-ID case was added to the test; it was added, and it then also exposed two real fit bugs — stale stretch section, header minimum — both fixed) |
| PANIC does not uncheck the ack | `test_panic_unchecks_the_bench_ack_…` |
| ack all acks everything | `test_ack_all_never_acks_an_alert_that_arrived_…` |

### Measurements

- Two 16 px lines: line box 20 px each (40 > the key's 36), but ink is 12 rows (callsign, caps +
  digits) + 17 rows (label, ascender to descender). Placed by ink: rows 3–32 of a 36 px key.
- Strip width: 1078 px live default; worst case (DEMO, `PROWL SC`, PERMITTED, `999 targets`, 99+)
  hub minimum **1279 px in SUN, 1272 in dark** — fits 1280 with **1 px to spare in SUN**. Any new
  strip content needs width from somewhere else.
- ATLAS at 1280×720: CONTACT / NM / ALT sum = viewport width (438 px dark/light, 433 sun); no
  sideways scroll; a 30-char ID elides, 123456 ft shows whole.

### Renders (1280×720, ATLAS + top strip, dark + sun live, plus a stress pass)

`atlas_{dark,sun}_live.png`, `atlas_{sun,dark}_stress.png` (demo, long ID selected, strip worst
case): `python3 plan/briefs/CL1-renders/render_fix2.py <outdir>`; PNGs are git-ignored.
Checked by eye: labels under every key, nothing cut in the table, `…` on the long ID.

### Found, not fixed

- **DetailCard hero clips a long unbreakable token** (pre-existing): the stress render shows
  `RID-1581F5FAB2C3D4E5F…` cut at the card edge (no ellipsis) at hero size. The full value is in the
  table cell's tooltip, so decision 3 holds, but the card should wrap anywhere or elide. Medium; CL4.
- RA-CL1b N2 class elsewhere: lists without an `_id` (RECON Wi-Fi/BLE, PROWL, MESH…) now keep the
  selection only while the row's content is unchanged, else clear it — honest, but a changing RSSI
  drops the cursor. Give them ids (bssid, address) in their own clusters.
- RA-CL1b N5 (daemonized member escapes PANIC) → CL2 process registry. N6 (page status row
  captioned "SDR") → CL4. N7 (double-M; M during first read dropped), N8 (PANIC blocks ≤ 2.5 s),
  N9 (unreachable `ACQUIR…` branch) — Low, not fixed.
- Strip has 1 px of headroom in SUN + DEMO worst case (see Measurements).

### Suite and lint

```
$ QT_QPA_PLATFORM=offscreen python -m pytest -q tests        (python3.12 venv: PySide6 6.12, pyqtgraph, flask, numpy)
FAILED tests/test_audit_tiles.py::test_undecodable_tile_is_marked_failed - As...
FAILED tests/test_hwlab.py::test_doctor_hwbench_check - assert (None is True)
FAILED tests/test_sstvdec.py::test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone
3 failed, 961 passed, 14 skipped in 236.74s (0:03:56)
$ python -m pyflakes palisade_qt tests/test_cl1_fix2.py tests/test_cl1_fix.py tests/test_cl1_screen.py plan/briefs/CL1-renders/render.py plan/briefs/CL1-renders/render_fix2.py
(clean)
```
The 3 failures are pre-existing on `main` (verified in RA-CL1b: same venv, `git archive main`, same 3).
(After the suite run, one unused import in `tests/test_cl1_fix2.py` was removed for pyflakes; that
file was re-run alone: 16 passed.)

### Stage → model

| Stage | Model |
|---|---|
| Implementation, tests, mutations, renders, verdicts | session model (Opus 5.5), run directly — no subagents |

### Not checked here

Python 3.13, the uConsole panel and keyboard, a real window manager, real tiles. Device command as
in the CL1 section above.

---

## CL1-fix3 — close RA-CL1c (brief `plan/briefs/CL1-fix3.md`)

Branch `fix/cl1-screen-structure`, base `ee4ac57` (code identical to `c97a05b`; ee4ac57 adds only
the RA-CL1c docs). Worktree `../wt-CL1-fix3`. Python 3.12 venv, PySide6 6.12.0, Qt offscreen, macOS.
New tests: `tests/test_cl1_fix3.py` (16 tests). Fail-first on `ee4ac57`: the F1 tests (all six
theme × on/off cases) failed, as did both F2 tests and the F4 test. F3 passed (the behaviour was
already correct); it **fails under mutation m16** (`('vscroll appeared', 430, 420)`).

| ID | Verdict | Fix (file) | Regression test |
|---|---|---|---|
| F1 | CLOSED | `theme.py` navkey focus: over- and underline only. Sides keep their unfocused width and colour (`bw`, transparent / accent), so nothing is painted in the glyph columns. Underline `focus_under` (2/2/3 px) fits the ink-free rows. Corners are square, because a rounded thick underline curled into the edge glyphs. `focus_on` + a double underline on the current-page key, because SUN black-on-black was invisible. The checked key is now square in both states, because its rounded 5 px accent corner sat inside the text rect and changed on focus. Width is unchanged. | `test_nav_key_focus_cue_never_paints_inside_the_text_rect[{dark,light,sun}-{off,on}]`: every pixel in both text rects (advance box ∪ ink, ink rows) is identical focused vs unfocused, and ≥ key-width pixels change elsewhere, so the cue is visible. `test_nav_key_focus_cue_does_not_widen_the_strip` |
| F2 | CLOSED (wording deviates, see below) | `chrome.py` `SCOPE_MAX = 999` → `999+ tgts` | `test_scope_summary_caps_the_target_count`, `test_strip_fits_1280_with_a_huge_scope[{3 themes}-{live,demo}]`: through `engagement.start` at 999, 1000 and 100000 targets, owner `PROWL SC` and the longest owner label, PERMITTED, 99+, focus on SYSTEM; hub and strip ≤ 1280 |
| F3 | CLOSED | none (test gap only) | `test_feed_table_refits_when_the_viewport_gains_a_vscroll_or_narrows`: m16 caught |
| F4 | CLOSED | `atlas.py` `_render` → `_show_lost()`: hero keeps the label, sub `LOST · NO LONGER REPORTED`, rows replaced by `STATUS LOST` (last alt/speed/range dropped), `_selected` cleared | `test_atlas_detail_marks_a_vanished_selected_contact_lost`: also checks that 123456 / `ft` are gone and that selecting another contact shows it normally |
| F5 | DEFERRED | none | No zero-width option exists. A separator in the keys' existing transparent `bw` side border costs no width, but it would sit under ink at x=1 (PROWL) and x=68 (ATLAS, the key's last column). That is the F1 defect again. |

### Where the brief was wrong

- **F2 `999+ targets` does not fit.** It is 12 characters. `999 targets` (11) is the widest value the
  strip is sized for, and the extra character overflowed in a measured run (dark demo 1282 px). So the
  capped form is `999+ tgts`. The test asserts it is never longer than `999 targets`. If the owner
  wants the full word, the strip needs about 10 px from somewhere else.
- RA-CL1c PoC column "glyph-cols-under-ring" is computed from `focus_w` and no longer means anything,
  because the side ring is gone. The pixel column is the truth: it now reads **0 px in every key
  in every theme**.

### Found, not fixed (not CL1-fix3 scope)

- Low: `ChromeState.stop()` called twice (explicit `hub.state.stop()` then `close()`) logs a
  PySide `Failed to disconnect` RuntimeWarning (`chrome.py:136`). It is harmless, but `stop()` is not idempotent.
- Low: after LOST, if the contact reappears it is not auto-reselected. That is deliberate: the
  operator must re-pick it.

### Measurements (render script, worst case `PROWL SC` / PERMITTED / `999+ tgts` / 99+)

dark demo hub_min 1253 · dark live 1241 · sun demo 1260 · sun live 1248 (all ≤ 1280).
`poc_focus_ring.py` after the fix: overpainted glyph pixels = 0 for all 8 keys × 3 themes.

### Suite and lint

```
$ QT_QPA_PLATFORM=offscreen python -m pytest -q tests
FAILED tests/test_audit_tiles.py::test_undecodable_tile_is_marked_failed - As...
FAILED tests/test_hwlab.py::test_doctor_hwbench_check - assert (None is True)
FAILED tests/test_sstvdec.py::test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone
3 failed, 977 passed, 14 skipped, 6 warnings in 278.38s (0:04:38)
$ python -m pyflakes palisade_qt tests/test_cl1_fix3.py tests/test_cl1_fix2.py tests/test_cl1_screen.py tests/test_cl1_fix.py plan/briefs/CL1-fix3-renders/render.py
(clean)
```
These are the same 3 failures as on `main` and in RA-CL1c. The run was on the committed tree.

### Renders (1280×720, PNGs git-ignored)

`python3 plan/briefs/CL1-fix3-renders/render.py <repo> <out>` writes
`strip_{dark,sun}_{demo,live}_worst_focus<KEY>.png` (full 1280×720 frame, focus on each of the 8 keys),
`zoom_strip_*` (2× zoom of the strip), and `atlas_{dark,sun}_{selected,lost}.png`. The local copies are in
`~/palisade-renders/CL1-fix3/` on the dev Mac, plus `cl1fix3_ops_grid.png` (current-page key,
unfocused | focused, sun/dark/light).

### Stage → model

| Stage | Model |
|---|---|
| Implementation, tests, mutation m16, renders, suite, verdicts | session model (Opus 5.5), run directly. No subagents. |

### Not checked here

Python 3.13, the uConsole panel and keyboard, a real window manager.
