# RA-CL1d — scoped cold re-audit of CL1-fix3 (`fix/cl1-screen-structure`)

Audited tip **`91d5870`** in worktree `../wt-RA-CL1d`. Auditor only; no product code changed.
Python 3.12.16 venv, PySide6 6.12.0, pyqtgraph, flask, numpy; Qt `offscreen`, macOS. PoCs and raw
output: `plan/briefs/RA-CL1d-evidence/`. PNGs are git-ignored; regenerate with the commands under Renders.

**Verdict: MERGE.** F1–F4 hold under direct attack. Nothing found that an operator would misread.

## Stage → model

| Stage | Model |
|---|---|
| PoCs, mutations, renders, suite, pyflakes, every verdict | Session model (Opus 5.5), run directly. No subagents. |

## F1–F4

| ID | Verdict | Attack → result | Test |
|---|---|---|---|
| F1 focus ring over edge glyphs | **CLOSED** | Independent ink-diff, not using the fix's text-rect maths: ink = unfocused pixels ≠ the key's main background colour; diffed against the focused image. Covered 3 themes × live/demo × current-page on/off × 8 keys = 96 cases (`poc_focus_ink.txt`). **Dark/light: 0 ink pixels changed.** **SUN: 6 (PRISM) and 10 (SYSTEM) pixels changed**, all on row 1, colours `#dbdbdb`–`#fefefe` (≤ 14 % coverage). This is the anti-alias overshoot fringe above round tops (`3`, `8`, `S`), not glyph body (`poc_focus_where.txt`). No side paint anywhere. Viewed zoomed at 6–8× and 2× (each key focused, current page OPS and SYSTEM): every callsign and label reads correctly, `8 SYSTEM` stays `8`, and `settings` is whole. Strip width is unchanged (`test_…does_not_widen`). | `test_nav_key_focus_cue_never_paints_inside_the_text_rect[×6]` fails on `ee4ac57` in all 6 params |
| F2 strip > 1280 at ≥ 1000 targets | **CLOSED** | Real `engagement.start` with 999 / 1000 / 100000 targets × 3 themes × live/demo × the 2 longest owner labels, PERMITTED, 99+, focus on SYSTEM. Hub min: 999 → 1260–1279 (SUN demo 1279, 1 px spare, as before). 1000 and 100000 → `999+ tgts`, 1241–1260. Nothing passes 1280. | `test_scope_summary_caps_the_target_count`, `test_strip_fits_1280_with_a_huge_scope[×6]` (fail on `ee4ac57`) |
| F3 m16 refit untested | **CLOSED** | Mutation m16 (viewport-resize refit removed) is **caught**. The test passes on `ee4ac57` because the behaviour was already correct; only the pin was missing. | `test_feed_table_refits_when_the_viewport_gains_a_vscroll_or_narrows` |
| F4 ATLAS shows a gone contact as current | **CLOSED** | Selected contact removed, gone stale (STALE_S), or its layer hidden: in every case the card shows `<label> / LOST · NO LONGER REPORTED / STATUS LOST`, with no ALT, SPEED, RANGE or BEARING. It stays that way on later refreshes. Selecting another contact shows that contact normally (`poc_f2_f4.txt`). | `test_atlas_detail_marks_a_vanished_selected_contact_lost` (fails on `ee4ac57`) |

Fail-first: on `ee4ac57` with `test_cl1_fix3.py` copied in, **14 failed and 2 passed**. The 2 that pass are the
no-widen test and the F3 pin, which is expected (`failfirst_ee4ac57.txt`).

### Mutations (`mutate.py` → `mutations.txt`, each run against `tests/test_cl1_fix3.py`)

| Mutation | Result |
|---|---|
| m16 no viewport refit | CAUGHT |
| F1: exact pre-fix side ring (`{focus}`, `focus_w` sides) | CAUGHT |
| F1: `focus_w` sides on the current-page key | CAUGHT |
| F1: no focus cue (transparent) | CAUGHT |
| F1: SUN underline 6 px | CAUGHT |
| F1: `focus_w` side width but sides still transparent | survived. **Equivalent mutant**: a transparent border paints nothing, and the labels are placed by `_place`, not by the box model. |
| F2: no cap · cap spelled `999+ targets` | CAUGHT · CAUGHT |
| F4: `_show_lost` not called · LOST keeps the stale rows · LOST without the word | CAUGHT ×3 |

## Sweep

- Every page, sub-tab, panel and stress view rendered in **sun/demo**: 34 views, all exactly 1280×720 (`CL1-renders/render.py`). Also the SUN and dark demo worst-case strip with focus on each key (2 current pages × 8 keys), and the ATLAS selected → LOST views (`CL1-fix3-renders/render.py`). Eyeballed: ATLAS LOST, stress OPS, stress ENGAGEMENT, and the strip focus stacks. Nothing clipped, overlapping or misleading.
- Suite (once, 3.12 venv, offscreen): `3 failed, 977 passed, 14 skipped in 265.26s`. The 3 failures are the same ones found on `main` (`test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::test_iss_passes_…`). None is CL1's. The pass count went from 961 to 977, which is the 16 new tests.
- `pyflakes palisade_qt tests/test_cl1_*.py plan/briefs/CL1-fix3-renders/*.py plan/briefs/RA-CL1d-evidence/*.py` → rc=0.

## New findings (none block)

| # | Sev | Finding | Evidence |
|---|---|---|---|
| G1 | Low | In SUN the focus over-line touches the cap tops with **0 px gap** on 1 OPS, 3 PRISM, 4 PROWL, 7 FORGE and 8 SYSTEM. On the current-page key it is white on white glyphs. The tops of `T`/`E`/`M` join the bar, but the letter shapes survive (the bar *is* their top stroke), and no misread was found at 2×. Also, the fix's test text-rect starts at `tightBoundingRect` top, so it does not see the overshoot fringe on row 1 (G1's 6–10 px). A 1 px clearance would need the key 1 px taller or the GAP 1 px smaller. | `poc_focus_ink.txt` `gap_top=0`; `sun_navkeys_focus_stack_2x.png` |
| G2 | Low | After LOST, if the same contact is reported again, the card stays **LOST** while the contact is back in the list (nothing is highlighted). This errs on the safe side; the operator re-selects it. | `poc_f2_f4.txt` "X1 reported again" |
| G3 | Low | Hiding the contact's layer shows `LOST · NO LONGER REPORTED`, but the contact is only hidden by the operator's own toggle. Wording only, e.g. `HIDDEN · layer off`. | `poc_f2_f4.txt` "aircraft layer hidden" |

F5 (key spacing) is deferred by the implementer and still a follow-up. Earlier follow-ups (DetailCard hero clip → CL4, content-keyed
lists, N5–N9) are unchanged.

## Renders (1280×720; regenerate with)

- `python3 plan/briefs/CL1-renders/render.py <out> sun demo`: 34 views
- `python3 plan/briefs/RA-CL1d-evidence/render_strip_focus.py <repo> <out>`: `{sun,dark}_demo_page{OPS,SYSTEM}_focus<KEY>.png` + `*_navkeys_focus_stack_2x.png`
- `python3 plan/briefs/CL1-fix3-renders/render.py <repo> <out>`: `atlas_{dark,sun}_{selected,lost}.png`, strip focus per key

## Not checked

Python 3.13, the uConsole panel and keyboard, a real window manager, real tiles.

## Merge line

**MERGE.** G1–G3 are follow-ups.
