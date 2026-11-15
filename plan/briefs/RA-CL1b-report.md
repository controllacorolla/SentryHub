# RA-CL1b — second cold re-audit of `fix/cl1-screen-structure` (PR #19)

Audited tip `4e51d3d`. Fresh session, auditor only, no fixes written. Python 3.12.16, PySide6 6.12.0,
Qt `offscreen`, macOS. PoC scripts and raw output: `plan/briefs/RA-CL1b-evidence/`.

**Verdict: DO NOT MERGE.** Two problems block it: the ATLAS contact table cuts altitude digits off
at 1280×720 with no ellipsis (N1), and the list cursor now jumps to a different item than the
detail card after every refresh (N2). Both were introduced by CL1/CL1-fix. PANIC kills
SIGTERM-ignoring pipelines correctly, but nothing pins that path: deleting the SIGKILL escalation
leaves every test green (N10). Everything else holds.

## Stage → model

| Stage | Model |
|---|---|
| PoCs (PANIC pipelines, mixer, alerts, readers, popups), font/fit walker, renders, suite, pyflakes, mutations | run directly in this session's shell. No subagents were used. |
| Every verdict and severity | session model (Opus 5.5) |

## Suite and lint

```
$ QT_QPA_PLATFORM=offscreen python3.12 -m pytest -q tests      (venv: PySide6 6.12, pyqtgraph, flask, numpy)
3 failed, 946 passed, 14 skipped in 232.05s
FAILED tests/test_audit_tiles.py::test_undecodable_tile_is_marked_failed
FAILED tests/test_hwlab.py::test_doctor_hwbench_check
FAILED tests/test_sstvdec.py::test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone
```
All 3 also fail on `main` (`git archive main`, same venv: `3 failed`). They are not CL1's.
`pyflakes palisade_qt tests/test_cl1_fix.py tests/test_cl1_screen.py plan/briefs/CL1-renders/render.py` → clean.

## Audit IDs

| ID | Verdict | Evidence | Test |
|---|---|---|---|
| D1 | CLOSED | Hub `minimumSizeHint` 1253×473 live, 1258×537 demo (worst-case strip: DEMO, owner `PROWL SC`, PERMITTED, `999 targets`, 99+ alerts). No rail. BENCH REASON wraps. | `test_every_page_and_subtab_fits_1280x720`, `test_no_rail_the_page_starts_at_the_window_edge`, `test_detail_values_wrap_instead_of_widening` |
| D2 | CLOSED | My own walker read `QFontInfo` of every visible label, button, header, combo, item view and pyqtgraph axis/TextItem on all 8 pages, every sub-tab and all 5 panels (sun/live, dark/demo). **Zero widgets under 16 px.** | `test_rendered_text_is_16px_or_more_everywhere_including_captions_headers_and_plots` |
| D3 | CLOSED | No rail, no shell footer, vertical sub-tab rail, OPS scope dead space measured by the test. One residue, see N6. | `test_sub_tabs_are_a_vertical_rail_left_of_the_page`, `test_ops_scope_has_at_most_24px_dead_space_each_side` |
| D4 (slots) | CLOSED | 4 shell-owned slots. Word + colour + shape. Readers that raise give UNKNOWN (dashed ring, amber). ENG wording: see N4. | `test_unreadable_engines_show_unknown_not_the_all_clear`, `test_slots_paint_the_whole_owner_and_scope_never_an_ellipsis` |
| D7 | CLOSED, **owner flag** | 8 keys present. The function label is **not** beside each key: it is in the tooltip, key map and palette only (planner commit `1e0993c`). `AUDIT_INDEX.md` still records the owner decision as "function label beside each". The owner should confirm which rule stands. | `test_eight_keys_in_order_with_function_labels`, `test_every_page_key_parses_to_a_real_key` |
| D8 | CLOSED | Keys 1–8, ← →, ↑ ↓, Enter, Esc, `[ ]`, `/`, `?`, R/E/A/M and Shift+Esc/F12 work. Focus ring renders. | `test_r_e_m_keys_and_panic_with_a_panel_open`, `test_bracket_keys_…`, `test_focus_ring_…` |
| D9 | CLOSED | ARMED/PERMITTED/ENG never green. SUN is black and white. | `test_armed_and_active_slots_are_never_green[*]`, `test_babel_protocol_colours_are_readable[*]` |
| D10 | CLOSED | Drawer with history and ack by id. Empty cards collapse. PRISM "send to" works. | `test_empty_detail_cards_collapse_in_live_pages`, `test_ops_alert_card_…`, `test_prism_peak_can_be_sent_to_the_tuner` |
| RADIOS | CLOSED | Read-only inventory, owner, history, FREE THE RADIO. 2 s re-read while visible. | `test_radios_panel_rereads_the_kernel_while_visible` |
| audio | CLOSED | Off-thread, read-back only. Fault shows `♪!` + tooltip. Minor issues: N7. | item 3 tests |

## CL1-fix items 1–18

| # | Verdict | Evidence (my PoC) | Test |
|---|---|---|---|
| 1 PANIC kill | **PARTIAL** (behaviour right, not pinned) | Real `sh -c "trap '' TERM; sleep \| sh -c \"trap '' TERM; sleep\""`: 4 members, **all 4 dead**. Banner `4 of 4 … (verified gone)`. The UI blocks for 1.6 s (escalates to SIGKILL). The real `child_pids` path (no seam) works too: 3 of 3. But removing the SIGKILL escalation or the `killpg` passes every test (m1, m2 → N10). A daemonized member escapes (N5). | `test_panic_stops_every_pipeline_member_and_counts_only_verified[*]` and 3 more |
| 2 PANIC TX display | CLOSED (as briefed) | BENCH ack held → PANIC → slot `PERMITTED` on every page. Banner says `BENCH ack not revoked — TX still PERMITTED`. ARMED wins over PERMITTED. **The brief's premise is wrong**, see "Brief got wrong". | `test_panic_leaves_tx_slot_on_the_real_bench_gate_…` |
| 3 Mute | CLOSED | Mixer that hangs 2 s: toggle returns in 0.07 s and does not show checked before the read-back. Failing mixer shows `♪!`, true state, not checked. A lying mixer (set OK, read-back unmuted) shows unmuted. Minor issues: N7. | 4 mixer tests |
| 4 Drawer by id | CLOSED | Selected "alert 1". A new alert arrived. Ack acted on "alert 1" only. The general FeedTable cursor bug remains: N2. | `test_alert_arriving_while_drawer_open_…` |
| 5 Slots never elide | CLOSED | Worst case painted in full: `PROWL SC`, `PERMITTED`, `999 targets`, `99+`, `DEMO`. Strip min width is 1253 live and 1227 + 2×border in demo. | `test_slots_paint_the_whole_owner_and_scope_…` |
| 6 Readers → UNKNOWN | CLOSED | `txguard.is_armed` and `engagement.info` raise → both slots show `UNKNOWN` with the `unknown` shape. | `test_unreadable_engines_show_unknown_not_the_all_clear` |
| 7 PANIC through popups | CLOSED | Combo popup open + Shift+Esc → PANIC ran and the popup closed. A modal `QMenu.exec()` + F12 → PANIC ran. The app has no QDialog/QMessageBox, so there is no modal-dialog hole. | `test_panic_works_with_a_combo_dropdown_open`, `…_context_menu_…` |
| 8 ENGAGEMENT panel | CLOSED | Stress render (sun): a 6-target scope wraps in full, the evidence table has room for ≥ 3 rows, OPERATOR/AUTH/TARGETS shown. | `test_engagement_panel_shows_whole_scope_…` |
| 9 Alert cap | CLOSED | 603 unacked → 603 kept, 603 drawer rows, strip `99+`. | `test_alert_cap_never_drops_an_unacknowledged_alert` |
| 10a sky-dome labels | CLOSED | Test + render. | `test_sky_dome_labels_…` |
| 10b focus ring | CLOSED | Test compares pixels. | `test_focus_ring_…` |
| 10c no green demo | CLOSED | Test. | `test_prowl_demo_data_is_never_painted_green` |
| 10d feed columns | **REGRESSED** | No ellipsis any more. Instead the ATLAS contact table is 470 px wide in a 433–438 px viewport, and the right-aligned ALT column is cut at the viewport edge: N1. | `test_feed_columns_get_real_widths_…` passes. It does not check that a column fits. |
| 11 D1 pins | CLOSED | Mutation list in CL1 report + mine. | as D1 |
| 12 D2 measured | CLOSED | Independently re-measured: 0 widgets under 16 px. The report's explanation (`CAPTION_CLASSES` exempted the measured classes) is correct. | as D2 |
| 13 D3 | CLOSED | | as D3 |
| 14 D9 | CLOSED | | as D9 |
| 15 D10 cards | CLOSED | | as D10 |
| 16 RADIOS refresh | CLOSED | `QTimer` 2 s while shown, stopped on hide. | as RADIOS |
| 17 keys | CLOSED | | as D8 |
| 18 SWEEP detectors | CLOSED, intended | Detectors start on SWEEP's first show and are joined on close. | `test_detectors_start_when_sweep_opens_and_not_before` |

## Mutations (try to break a fix without a test noticing)

Each mutation was applied to a copy of the tree, then `tests/test_cl1_fix.py` and
`tests/test_cl1_screen.py` were run (`RA-CL1b-evidence/mutate.py`).

| Mutation | Result |
|---|---|
| m1 PANIC never escalates to SIGKILL (`procs.py:108`) | **SURVIVED**: 89 passed |
| m2 PANIC never `killpg`s the group (`procs.py:96`) | **SURVIVED**: 89 passed |
| m3 no descendant walk | caught: `test_panic_stops_every_pipeline_member_…[False]` |
| m4 combo popup not closed on PANIC | caught: `test_panic_works_with_a_combo_dropdown_open` |
| m5 drawer does not re-select by id | caught: `test_alert_arriving_while_drawer_open_…` |
| m6 cap drops unacked alerts | caught: `test_alert_cap_never_drops_an_unacknowledged_alert` |
| m7 mute button not synced to read-back | caught: `test_mute_shows_muted_only_after_…` |
| m8 mixer fault not shown | caught: `test_failed_mixer_command_shows_a_fault_…` |
| m9 BENCH `on_gate_changed` does nothing | **SURVIVED**: 89 passed |
| m10 unreadable txguard → OFF | caught: `test_unreadable_engines_show_unknown_…` |
| m11 banner hides survivors | caught: `test_panic_never_counts_a_signal_as_a_kill` |
| m12 mixer set blocks the GUI 0.6 s | caught: `test_a_hanging_mixer_does_not_freeze_the_ui` |

m1 and m2 matter. The PANIC test pipeline is `sleep | sleep`, which dies on SIGTERM, and the
descendant walk alone reaches every member. So neither the SIGKILL escalation nor the group kill is
pinned. My PoC shows both work today (a SIGTERM-ignoring pipeline dies), but a regression would not
be caught: N10. m9 is benign today, because PANIC cannot change BENCH's gate, so the re-read has
nothing to show.

## New findings

| # | Sev | Finding | PoC / evidence |
|---|---|---|---|
| N1 | **High** | **ATLAS ALT digits silently cut off at 1280×720** (all themes). The columns measure 162 + 108 + 100 + 100 = 470 px; the viewport is 433–438 px. ALT is right-aligned, so the end of a 5-digit altitude falls past the edge: `15023` reads as `150`, and a drone at `3xx` reads as `3`. There is no ellipsis, only a scroll bar whose range is one column. Before item 10d this column was elided ("…"), which at least showed it was cut; now it is not. The CL1 report lists this as an "intended trade-off". It is not one: an operator reads a wrong altitude. | `RA-CL1b-evidence/atlas_cols.py` → `{"viewport_w": 438, "cols": [... ["ALT", 370, 100]], "alt_visible_px": 68}`; render `atlas-map_light_demo.png` shows `744`, `3`, `171` cut off |
| N2 | Medium | **List cursor restored by row index; detail does not follow** (new in `kit/feed.py:96-127`, CL1). After `set_rows`, `_restore_row` selects the *same row number* with signals blocked. When a list re-sorts or gains a row, the highlight lands on a different item and the detail card keeps the old one. ATLAS re-sorts by range every render, so a highlighted aircraft drifts away from its detail card. RECON Wi-Fi/BLE, PROWL, the RADIOS history and others use `set_rows` too. The alerts drawer is safe only because it corrects by id afterwards. No primary action consumes the highlighted row today, so this is a display fault, not a wrong-target action. | PoC: rows A,B,C, cursor on B, `set_rows([X,A,B,C])` → highlight **A**, detail **B** |
| N3 | Medium | **PANIC leaves BENCH able to key up although the UI could revoke it.** The ack is the page's checkbox. The engine has no session ack (`bench_app.py:129-136` builds the settings from `self.ack.isChecked()`), so `bench.ack.setChecked(False)` would revoke it UI-only. After PANIC, `ack_checked: true`, `tx_btn_enabled: true`. The display is honest (slot PERMITTED, banner says so), so this fails safe in what it shows, but the PANIC key does not stop what it could stop. Owner decision: see below. | `poc_panic.py` P4 |
| N4 | Low | **ENG slot has no state word.** Active shows the scope, e.g. `ENG ◆ 10.0.0.*`. In SUN (black and white) the only active-vs-none cue besides the text is a 9 px filled diamond vs ring. A single short target spelled like a state word paints `ENG ◆ NONE`, which in SUN differs from the real `ENG ○ NONE` only by that glyph. Realistic scopes (IPs, CIDRs, globs, SSIDs, `6 targets`) read unambiguously, so this is Low. A fix: reserve state words (`NONE`, `OFF`, `UNKNOWN`) in `scope_summary`, or prefix `▶`. | stress strip renders `strip_sun_scopeNONE.png` vs `strip_sun_active.png` |
| N5 | Low | **A daemonized pipeline member escapes PANIC and is not reported.** A member that double-forks and `setsid`s is reparented away before the snapshot. PANIC reports `2 of 2 … stopped (verified gone)` while it keeps running. No current Qt spawn daemonizes (checked every `Popen` in `palisade_qt/`), so it is latent. CL2's explicit process registry (already handed over) closes it. | `poc_mixer_alerts_readers.py` P2b |
| N6 | Low | Pages still have a bottom status row (`SDR —`, `SDR DEMO`, `PWR —`), written by the page via `set_chip("sdr", …)`. Its "SDR" caption repeats the shell-owned SDR slot with page content that is not radio state (BENCH writes `SELF-TEST PASS`). This is a D4/H7 residue: a page-written chip under a radio caption. | renders `ops_*`, `atlas-map_*` |
| N7 | Low | Mute: (a) `M` pressed while the first mixer read is in flight is dropped silently, because the control is disabled. (b) Two quick `M` presses both compute "mute" from the last *confirmed* state, so a double press ends muted rather than toggling back. Honest, but surprising. | `poc_mixer_alerts_readers.py` M_hang, M_double_press |
| N8 | Low | PANIC blocks the GUI for up to ~2.5 s when something ignores SIGTERM (1.6 s measured). The CL1 report states this and explains why. Recorded here only so it is not lost. | P1 |
| N10 | Medium | **PANIC's SIGTERM-ignoring path has no test.** Mutations m1 (no SIGKILL) and m2 (no `killpg`) pass all 89 CL1 tests. To fix, add a test pipeline with `trap '' TERM` in each member that asserts every member is dead, and a test where a member is not a descendant but shares the group (e.g. `setpgid` into it). | mutation table |
| N9 | Low | `chrome.ChromeState.radio()` never yields `ACQUIRING`. `topbar.set_state` has an `ACQUIR…` branch that is unreachable, and its literal "…" would contradict item 5 if it were ever reached. | `chrome.py:111-115`, `topbar.py:381-383` |

## Specific attacks (brief step 5)

| Attack | Result |
|---|---|
| ENG slot shows scope only: is active unmistakable by word + shape? | Mostly. Colour + diamond + scope text read as active in dark/light, and `6 targets` is clear. In SUN it rests on the glyph, and a scope spelled `NONE` collides (N4, Low). |
| PANIC when a process ignores SIGTERM | Holds. SIGKILL escalation kills the whole tree, the count is verified, ~1.6 s block. |
| TX slot after PANIC with BENCH ack held | Shows PERMITTED (truthful) on every page. The banner says the ack was not revoked. The ack *could* be revoked UI-only (N3). |
| ATLAS table horizontal scroll at 1280×720 | **Fails**: ALT is cut off without a marker (N1). SYSTEM › MESH also has a 1-column horizontal scroll (static content). |
| Anything a fix made worse | N1 (item 10d) and N2 (`_restore_row`). |

## Brief got wrong

- **CL1-fix item 2 / "Hand to CL2"** assumes the BENCH acknowledgement is engine state that needs a
  gate API to revoke. In the Qt app it is only `BenchApp.ack` (a `QCheckBox`); `bench.preflight`
  gets it through the settings dict the page builds. PANIC unchecking it is UI-only and does not
  change any gate's logic.
- `plan/briefs/README.md` says the suite runs with `python3.12`; the Mac's system `python3.12` has no
  PySide6. I used a fresh venv (`python3.12 -m venv`, pip PySide6/pyqtgraph/flask/numpy/pytest/pyflakes).

## Report claims checked

All per-item claims in the CL1-fix section reproduce, except the "intended trade-off" label on the
ATLAS horizontal scroll (N1). The 3 suite failures are pre-existing on `main`. The CL1 report says
"1 pre-existing failure" on 3.13; on this Mac 3 fail on both `main` and the branch.

## Process note

A second Claude session (scratchpad `9a1201b7…`) ran RA-CL1b against this same working tree at
the same time. It wrote `p_*.py`, `run.sh` and `suite_tail.txt` into `RA-CL1b-evidence/`. Those
files are not mine, are not committed here, and this report does not rely on them. The owner
should reconcile the two reports.

## Not checked (cannot be from here)

Python 3.13, the uConsole panel, a real window manager, a real PipeWire/ALSA mixer, real tiles. The
owner's device command is in the CL1 report.

## Owner decisions

1. **D7:** function label beside every key (AUDIT_INDEX) or tooltip/key-map only (planner `1e0993c`)?
2. **N3:** should PANIC uncheck the BENCH conducted-only ack (UI-only, in this PR), or leave it for CL2?
3. **N1:** fix by dropping or narrowing a column in ATLAS (e.g. TYPE as a glyph), or by left-aligning
   numbers so a cut is at least visible? A wide table that scrolls must never cut a value.

## Merge line

**DO NOT MERGE**: fix N1 (High) and N2 (Medium, introduced by this branch), and pin item 1 (N10).
Each needs a test that fails first. Then a scoped re-check of those three only.
