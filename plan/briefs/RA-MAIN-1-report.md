# RA-MAIN-1 — post-merge cold check of `main` (PR #19 CL1 + PR #20 CL2)

**Verdict: FIX NEEDED.** F1 and F2 (strip fit on Linux, fonts never loaded) block on-device sign-off. F3–F5 are low severity.

- Audited: `origin/main` @ `ef64fcd` (worktree `../wt-RA-MAIN-1`, branch `audit/ra-main-1`)
- Env: macOS, Python 3.12.16 venv, PySide6 6.12.0, `QT_QPA_PLATFORM=offscreen` (no xvfb or docker on this Mac)
- Models: every stage ran on the session model (Opus 5.5). No subagents were used.
- Evidence: `plan/briefs/RA-MAIN-1-evidence/` (PoC test, strip-width probe, render script, 8 PNGs at 1280×720)

## Brief items

| # | Item | Result | Evidence |
|---|------|--------|----------|
| 1 | PANIC order and completeness | **PASS** | Order in `shell.py:265-319`: `txguard.arm(False)` → `engagement.end()` → `executor.kill_all` → page `on_panic` (BENCH ack) → `stop_tree` → `_gate_changed` + `state.poll` → banner from `chrome.read_tx()`. Each step has its own try. PoC `test_panic_everything_live` set everything up at once: armed+unlocked, BENCH ack held, BENCH keyed through the executor, a netpent scan running under an engagement, and a child tree that ignores SIGTERM. After PANIC every process is verifiably dead, `executor.running()==[]`, the ack is unchecked, there are no permit sources, ENG reads NONE, and the slot reads `OFF`, which equals `read_tx()`. Banner: `PANIC — TX disarmed · engagement job ended · BENCH ack revoked · 2 of 2 child process(es) stopped (verified gone) · TX OFF`. The CL1-fix2 PANIC tests and the CL2 G11/G12 tests all pass in the suite run. See F4 for one gap in the banner. |
| 2 | TX slot words | **PASS, with F3** | OFF / ARMED / UNLOCKED / UNKNOWN behave correctly. Under CL2, **PERMITTED cannot be a true steady state**. `bench.preflight` → `txguard.authorize` requires both armed (`txguard.py:400`) and session unlock (`:402`), and `EXEMPT_SERVICES = ()` (`:40`). So whenever a page permit really holds, `read_tx` returns ARMED/UNLOCKED first (`chrome.py:96-97`). PERMITTED appears only when a permit is stale (F3) or comes from a test-injected source. **Recommendation: retire the word** (owner decision on slot vocabulary). |
| 3 | ENGAGEMENT slot + panel | **PASS, with F5** | The slot reads `10.0.0.5` / `999 targets` / `EXPIRED` (red triangle) / `UNKNOWN`. The panel shows the TARGETS row, the EXPIRED hero and UNKNOWN. Live, dark + sun, 1280×720, `eng_{single,many,expired,unknown}_{dark,sun}_live.png`. The strip does not clip in any of them. The panel SCOPE value does clip (F5). |
| 4 | Linux font metrics | **NOT CONFIRMED (no Linux box) → device-check. FIX NEEDED (F1, F2)** | Mac/CoreText worst-case `minimumSizeHint` (longest owner label, PERMITTED/UNLOCKED/UNKNOWN, 999 targets/EXPIRED/UNKNOWN, 150 alerts, focus on a key): dark 1260/1272, light 1260/1272, **sun 1267/1279** (live/demo). The result is the same with and without Plex registered. That leaves 1 px of headroom, while the planner measured 1284 on FreeType. The brief is wrong about one detail: Plex **is** in the repo, at top-level `fonts/` (tracked). `load_fonts()` looks in `palisade_qt/fonts/` instead (`theme.py:253`), so it is a no-op. |
| 5 | Suite on 3.12 | **3 failed, 1241 passed, 14 skipped** (272.7 s) | These 3 failed on `main` before CL1 too (recorded in RA-CL1d/RA-CL2 reports): `test_audit_tiles::test_undecodable_tile_is_marked_failed`, `test_hwlab::test_doctor_hwbench_check`, `test_sstvdec::…iss_passes…` (`skyfield` is not in the venv). None comes from the merge. pyflakes: `palisade_qt/` is clean; the warnings are 9 unused imports/variables in `tests/` only. |

## Findings (not closed: no fix and no regression test in this audit)

| ID | Sev | Finding | Evidence | Fix |
|----|-----|---------|----------|-----|
| F1 | **MED** | The worst-case strip is 1279 px on Mac and 1284 px on Linux/FreeType (planner measurement). It overflows 1280 on the target OS. `test_cl1_fix3::test_strip_fits_1280_with_a_huge_scope` passes only because it is measured with Mac metrics. | `strip_width.py` output above | Build in headroom. Either assert ≤ 1260 in the test (about 1.5 % for FreeType vs CoreText), or shrink the worst case (e.g. `999+ tgts` → `999+`, a shorter owner label). Then re-measure on the uConsole. |
| F2 | **MED** | `theme.load_fonts()` never loads the bundled Plex. It reads `palisade_qt/fonts/`, but the fonts are tracked in `<repo>/fonts/`. The device therefore renders in whatever fontconfig resolves for "IBM Plex Mono" (DejaVu Sans Mono if Plex is not system-installed; Qt also warns that the "DejaVu Sans Mono" alias is missing on Mac), so every metric-based fit test measures a different font than the device uses. | `theme.py:251-258`, `git ls-files fonts` | Point `load_fonts` at `os.path.join(_HERE, "..", "fonts")` (or check both paths). Add a test that `QFontDatabase.applicationFontFamilies` contains "IBM Plex Mono" after `load_fonts()`. |
| F3 | LOW | Disarming outside PANIC (TX panel / `txguard.arm(False)`) while BENCH is keyed makes the slot read **PERMITTED for about 180 ms**. The gate already refuses at that point. `BenchApp._refresh_gate` returns early while the handle is running (`bench_app.py:164`), so the stale `report_tx_permit("BENCH", True)` survives until the 200 ms `_check_handle` poll. | PoC `test_stale_permitted_after_plain_disarm_while_keyed`: timeline `[(0.0,'PERMITTED'),(0.18,'OFF')]` | Retire PERMITTED (item 2). Otherwise, in the early-return branch, still re-run `preflight` and withdraw the permit when it fails, leaving STOP enabled. |
| F4 | LOW | The PANIC banner leaves out gated processes that the disarm/end listeners stopped. `txguard.arm(False)` and `engagement.end()` kill them before `kill_all` runs, so `kill_all` returns 0 and the line is dropped. In the PoC, a keyed BENCH transmitter and a netpent scan were stopped and the banner mentions neither. | PoC banner text (item 1) | Snapshot `executor.running()` before the disarm. After the steps, report `N of M gated process(es) stopped (verified gone)`. |
| F5 | LOW | The ENGAGEMENT panel SCOPE row is cut off partway through a line for large scopes. There is no ellipsis, scrollbar or "+N more", in dark or sun. TARGETS shows the right count. | `eng_many_dark_live.png`, `eng_many_sun_live.png` | Cap SCOPE at about 5 lines with `… +N more`, or put the row in a scroll area. |

## Not in the brief

- `ChromeState.stop()` raises `RuntimeWarning: Failed to disconnect` on every hub close (`chrome.py:179`). The `except (TypeError, RuntimeError)` does not catch it because PySide raises a warning, not an exception. This is noise only.

## Open questions for the owner

1. Retire the `PERMITTED` TX word now that no real permit can exist while disarmed (item 2 / F3)?
2. Does F1 need a uConsole measurement before the fix, or is building in ≥ 20 px of headroom enough?
