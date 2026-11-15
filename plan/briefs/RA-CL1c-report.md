# RA-CL1c — final cold re-audit of `fix/cl1-screen-structure` (PR #19)

Audited tip `c97a05b`, in worktree `../ra-cl1c`. Auditor only; no code changed. Python 3.12.16 venv,
PySide6 6.12.0, Qt `offscreen`, macOS. PoC scripts and raw output are in `plan/briefs/RA-CL1c-evidence/`.
PNGs are git-ignored; to make them again, run the scripts listed under Renders.

**Verdict: DO NOT MERGE. One narrow blocker (F1).** In SUN, the 4 px focus ring paints over the
first and last glyph columns of whichever nav key has keyboard focus, so `8 SYSTEM` reads as
`3 SYSTEM`. The CL1-fix2 report and the D7 test both say no ring covers a glyph, but the test only
checks the top and bottom borders. Every other CL1-fix2 item holds against direct attack.

## Stage → model

| Stage | Model |
|---|---|
| PoCs, mutations, renders, suite, pyflakes, every verdict | session model (Opus 5.5), run directly. No subagents. |

## Suite and lint

```
$ QT_QPA_PLATFORM=offscreen python -m pytest -q tests      (3.12 venv: PySide6 6.12, pyqtgraph, flask, numpy)
FAILED tests/test_audit_tiles.py::test_undecodable_tile_is_marked_failed
FAILED tests/test_hwlab.py::test_doctor_hwbench_check
FAILED tests/test_sstvdec.py::test_iss_passes_use_their_own_tle_and_leave_weather_cache_alone
3 failed, 961 passed, 14 skipped in 238.39s
$ pyflakes palisade_qt tests/test_cl1_fix2.py tests/test_cl1_fix.py tests/test_cl1_screen.py plan/briefs/CL1-renders/*.py
rc=0 (clean)
```
These are the same 3 failures RA-CL1b found on `main`. None of them is CL1's. Fail-first check:
on `5cbc1de` with the new test file copied in, **14 failed and 2 passed**. The 2 that pass are the
N10 tests, which is expected because that behaviour was already correct.

## Step 1: CL1-fix2 items, attacked

| Item | Verdict | Attack → result | Test |
|---|---|---|---|
| N1 ATLAS fits, never clips | **CLOSED** | Each theme, demo, with an injected 6-digit alt (123456, 999999), a 30-char callsign, a 34-char ID, a negative alt, a 5-digit NM and 52 rows (v-scroll on). Sections 275/76/87 = viewport 438 (sun 270/76/87 = 433). h-scroll max 0. Checked every cell's `visualRect` against the style's text rect: nothing runs past the viewport, and nothing is cut without "…". Only CONTACT elides, with its full text in the tooltip. All numbers show whole. | `test_atlas_table_fits_…[3]` |
| N2 selection follows item | **CLOSED** | Re-sort pushed the selected contact to the end: the highlight and `_selected` followed it, and the detail showed the fresh data. Removing it cleared the highlight. All `selected` consumers (atlas/prowl/babel/more) only update the display, so the emit on every refresh has no side effect. | `test_feed_selection_follows_…`, `test_atlas_keeps_…` |
| PANIC ↔ BENCH ack (N3) | **CLOSED** | BENCH ack held, operator on ATLAS (BENCH not shown), PANIC: ack unchecked, TX button off, slot `OFF`, banner `BENCH ack revoked · … · TX OFF`. ARMED + ack, PANIC → `OFF`. Re-checking the ack afterwards gives `PERMITTED` again (a deliberate operator act). The slot and banner come from `chrome.read_tx()` after the re-read. A survivor is reported as `TX still PERMITTED (src)`. | `test_panic_unchecks_the_bench_ack_…`, `test_panic_banner_reports_a_permit_that_survives` |
| N10 SIGKILL / killpg pinned | **CLOSED** | Mutation m1 (no SIGKILL) and m2 (no `killpg`) are both **caught** now. They survived in RA-CL1b. | `test_panic_kills_a_pipeline_that_ignores_sigterm`, `test_panic_group_kill_reaches_…` |
| D7 callsign + label visible ≥ 16 px | **PARTIAL → F1** | Not focused: all 8 keys, both lines are 16 px, advance ≤ width, labels visible, strip 40 px, every theme. **Focused in SUN: 14–39 glyph pixels per key are painted over by the ring.** | `test_every_nav_key_shows_its_function_label_…[3]` (does not test focus left/right) |
| Item 6 panels → UNKNOWN | **CLOSED** | RADIOS shows `◌ UNKNOWN` in amber with the error, and FREE THE RADIO is disabled. ENGAGEMENT `open()` with raising `info`/`actions` shows UNKNOWN and the evidence row reads UNKNOWN. Mutations m7, m8 and m19 are caught. | `test_radios_panel_shows_unknown_…`, `test_engagement_panel_shows_unknown_…` |
| ACK ALL SEEN | **CLOSED** | 5 seen plus 1 that arrived while the drawer was open: 5 acked, `late` stays NEW. The count line says `1 arrived since opened (not in ACK ALL SEEN; reopen to include)`. The palette command uses the same rule. Nothing else calls `store.ack_all()`. Mutations m5 and m6 are caught. | `test_ack_all_never_acks_…` |
| ENG "1 target" (N4) | **CLOSED** | Through the real `engagement.start`: `["NONE"]`, `["None"]`, `["Unknown "]` and a 29-char host all show `1 target`. `["10.0.0.5"]` shows `10.0.0.5`. An empty scope is refused by the engine (`NONE`). | `test_a_scope_target_spelled_like_…` |

### Mutations (`RA-CL1c-evidence/mutate.py`, each run against `tests/test_cl1_fix2.py`)

17 of 19 were caught. m1 to m11, m13 to m15 and m17 to m19 were caught; the per-mutation results
are in `mutations.txt`. Two survived:

| Mutation | Result | Meaning |
|---|---|---|
| m12 put TYPE back as a 4th ATLAS column | survived | Harmless. `fit_viewport` still fits 4 columns (CONTACT elides). The guard is the fit, not the column count. |
| m16 no refit when the viewport resizes | **survived** | This line matters. Without it, a FeedTable that gains a v-scroll overflows by 10 px, and one that narrows by 40 px overflows by 50 px, with no scroll bar. ALT is cut silently, which is exactly N1 (`poc_vscroll.py`). ATLAS hides it because every render resets the model. F3. |

## Step 2: regression sweep

- Every page, sub-tab and panel was rendered at **1280×720** in dark/live, sun/live and sun/demo
  (stress), 34 views each (`CL1-renders/render.py`). All 102 are exactly 1280×720. The largest hub
  minimum-size hint is 1193.
- Strip worst case (DEMO, `PROWL SC`, PERMITTED, `999 targets`, `99+`, focus on a key), measured
  in 3 themes × live/demo × idle/worst/UNKNOWN. Hub minimum is **1279 in SUN demo (1 px spare),
  1272 in dark/light demo, and 1260–1267 in live**. No key or slot text is wider than its widget,
  and no strip widget is under 16 px. This matches the CL1 report exactly.
- One step beyond that worst case overflows (F2): `1000 targets` gives 1289 in SUN demo and 1282 in
  dark demo.
- ATLAS font walk (sun/demo, MAP / SKY DOME / PASSES: labels, buttons, item views, headers,
  pyqtgraph TextItems and axes): **0 under 16 px**.

## Step 3: CL1-report claims

| Claim | Check |
|---|---|
| Retired `test_panic_leaves_tx_slot_…_ack_not_revoked` | Matches owner decision 1. A replacement test exists and was mutation-verified (m3, m4). |
| `test_eight_keys_…` updated | Stronger now: it also asserts `key.label.text()`. Matches decision 2. |
| Anything else weakened | No. Only those two test files changed outside the new `test_cl1_fix2.py`. |
| "Every new test failed on 5cbc1de (13 of 15)" | Actually **14 of 16** (16 tests). A miscount only. |
| Strip 1279 SUN / 1272 dark, 1 px spare | Reproduced exactly. |
| ATLAS 438/433, no h-scroll, 123456 shows whole | Reproduced. |
| "nav focus ring keeps full width left/right … **so no ring covers a glyph**" | **False in SUN** (F1). The ring is 4 px and the key's side inset is 1 px. |
| Found-not-fixed list (DetailCard hero clip, content-keyed lists drop cursor, N5–N9, 1 px headroom) | Accurate and disclosed. |

## New findings

| # | Sev | Blocker? | Finding | Evidence |
|---|---|---|---|---|
| F1 | **Medium** | **Yes**: what the operator reads | **SUN focus ring paints over the edge glyphs of the focused nav key.** `navkey:focus` keeps `focus_w` on the left and right (SUN 4 px), but `NavKey.SIDE` is 1 px and the widest line fills the key (`7 FORGE`/`hardware`: advance 77 in width 77). Painted glyph pixels lost per focused key in SUN: ATLAS 23, PRISM 27, PROWL 14, SWEEP 26, RECON 28, FORGE 34, SYSTEM 39. Dark/light lose 0–5. In the zoom, the `8` of `8 SYSTEM` reads as `3` and the `s` of `settings` is cut. This already existed on the callsign line before fix2, and D7 adds the label line to it. The D7 test checks only top/bottom border clearance, so it cannot catch this. Width is the constraint: the SUN strip has 1 px spare, so widening the keys by 2×3 px won't fit. Show focus without painting over glyphs (an inset or underline, or a left/right border at `bw` plus a fill). Test: focused vs unfocused ink per key, all themes. | `poc_focus_ring.py` → `poc_focus_ring.txt`; zoom render `strip_sun_demo_worst_focusSYSTEM` |
| F2 | Low | No | **The strip overflows 1280 when the scope has ≥ 1000 targets** (DEMO: SUN 1289, dark 1282; LIVE at ≥ 10000). The window grows past the screen and loses its right 2–18 px. `engagement.start` does not cap scope size. Fix: `scope_summary` caps at `999+ targets`. | `poc_strip_beyond.txt` |
| F3 | Low | No | **Test gap: no test covers the viewport-resize refit** (m16 survives). The behaviour is correct today. | `poc_vscroll.py` |
| F4 | Low | No | When the selected contact disappears, the highlight clears but the ATLAS detail card keeps showing it as if it were current (`N12345 · 123456 ft · 20000 nm`). This is not new: the card was stale before CL1 too. Mark it LOST or clear it. | `poc_atlas_strip.json` `after_removal` |
| F5 | Low | No | Nav keys sit about 2–4 px apart, so `5 SWEEP6 RECON` reads as a run-on and the key number can look attached to the previous callsign. Nothing is clipped. A hairline separator or 1 px more gap would help, but there is no spare width in SUN demo. | strip renders |

Follow-ups already disclosed by the implementer and confirmed: DetailCard hero clips long tokens
(→ CL4); content-keyed lists (RECON/PROWL/MESH) drop the cursor when a row's content changes (give
them `_id`s); N5 → CL2; N6 → CL4; N7/N8/N9 Low.

## Renders (1280×720; PNGs git-ignored, regenerate with)

- `python3 plan/briefs/CL1-renders/render.py <out> dark live` · `… sun live` · `… sun demo` (stress): 34 views each
- `python3 plan/briefs/RA-CL1c-evidence/poc_atlas_strip.py <repo> <out>`: `atlas_stress_{dark,light,sun}.png`, `strip_{theme}_{live,demo}_worst_focusSYSTEM.png`

## Not checked

Python 3.13, the uConsole panel and keyboard, a real window manager, real tiles.

## Merge line

**DO NOT MERGE** until F1 is fixed: in every theme, the nav-key focus indicator must not paint over
any glyph of either line, with a test that compares focused and unfocused ink per key (it must fail
on `c97a05b` in SUN). After that, a scoped check of F1 alone is enough. F2–F5 are follow-ups, not
blockers.
