# RA-S1d — targeted cold re-audit of the RA-S1c fixes (`fix/shell-frame`, PR #33)

Auditor: fresh session, Opus. Head audited: `8bf8c5c`. Scope: `git diff 62a26df..8bf8c5c -- palisade_qt tests`
(`PageNotice._sig` / `consider` / `forget` / `stop` / `show_all`, `closeEvent`, a comment in `ops.py`, 3 tests).
Owner context: device run 2, batch 3 says no permanent bottom bar, and "a small message is OK somewhere, but not
there". So the notice is now the only way a warning reaches the operator without a click.

Probes were run in a live 1280x720 hub (offscreen, no hardware), using `tests/test_shell_frame.py` helpers.
`_show` was wrapped to record every notice. The probe scripts are in the auditor's scratchpad and are not committed.

## Verdict per finding

| ID | Claim | Verdict | Evidence |
|---|---|---|---|
| N6 | ATLAS layer counts moving no longer re-pop ADS-B NO FEED | **Fixed** | Live ATLAS with `_adsb_health={"state":"none"}`, real `_layer_summary` + `set_chip("sdr", …)`, 9 updates (balloon 0/1/2, DF 0/1, APRS 0/12): **exactly 1 notice**. `ADS-B STALE 12s → 13s → 40s → 300s` (alert): silent after the first. N1 does not regress: RECON `WIFI STANDBY — offline` → `BLE STANDBY — offline` shows (live). F2: `BLE STANDBY — retry in 12s/13s/14s/99s` gives one notice (the first is a different message, which is correct) and then nothing. Side effect, Info: `ADS-B STALE 12s` → `ADS-B STALE` (age `None`) loses the word `S`, so it re-shows once. Harmless. |
| N7 | (accepted Low) warnings that differ only by number/punctuation merge | **Accepted, still Low** | The fold is wider now: everything except ASCII letters is dropped. Real merges in the code: PROWL `locked out %.4f` (a second lockout is silent, but the operator caused it); PRISM `SDR FAULT — rtl_power exited (rc)` with a different rc; PROWL `NWR DOWN — decoder exited (rc) ×n` (n rising is silent; the flap FAULT at 3 exits has new words and shows, and `on_fault` puts it in the session log). I found nothing Dalton needs that is hidden only by this fold: every merged case is either caused by the operator or followed by a FAULT with new words. For Dalton: with the bottom bar gone, a merged warning is visible only by clicking the page name. |
| N8 | `PageNotice.stop()` from `closeEvent`: no timer fires after close | **Fixed** (residual Info) | ALERTS open, a warning held (retry active), `hub.close()`: right after, `_retry` and `_timer` are inactive. After 2.5 s nothing has been shown. The test `test_ra_s1c_n8_…` asserts this. Residual (Info, N15): a page status that arrives *after* close (for example a queued worker signal) still goes `_page_status → consider → _show` and starts `_timer` again. PoC: after close, `set_chip("late","LATE WARNING","warn")` → `_timer.isActive() == True`. It only hides a label on a closed window and never calls page code, so it is harmless. Guard with `if not self.isVisible(): return` in `_page_status` if wanted. |
| N10 | reminder only after `REMIND_S` (60 s) away; a quick flip does not repeat | **Fixed as designed** (residual Low, owner's call) | The test flips ATLAS→SYSTEM→ATLAS and gets no repeat; with `REMIND_S=0` the warning is reminded. **Clears and returns while away < 60 s:** lost. PoC: `SDR FAULT — X` (alert) shown on ATLAS, go to SYSTEM, the chip clears and is raised again, come back: **0 notices**. `alert→warn→alert` while away: also 0. The cause: `consider` only runs for the page on screen, so `_active` never sees the clear. Severity for the operator: **Low**. The text is identical to what he saw under a minute ago. A *different* warning, or a new key, that arrives while he is away does show on return (the signatures differ). Faults also go to the session log or ALERTS through `on_fault`. Also, flips that each stay away under 60 s never remind, however long the session runs. That is consistent with "no repeat on a quick flip". Both are listed for Dalton (N14). |
| new | a second warning moments later joins the notice showing | **Defective** (N12, N13) | It does not carry over from `show_all` (`_page=None`; PoC: after `show_page_messages`, a new warning shows alone), from another page (`show_page` hides, so `isVisible()` is false; PoC: PROWL notice, then ATLAS shows only `ATLAS · ATLAS NEW`), or from a click-dismiss (hidden). **But the lines it keeps are not checked against the page's current status**, and nothing caps them. See N12 and N13. |

## New findings

### N12 — Medium (blocker; honesty) — the joined notice keeps lines that cleared or were replaced, so it shows contradictory warnings side by side

`consider` merges with `lines = [ln for ln in self._lines if ln not in lines] + lines`. Every line still showing
is kept, even when its key cleared or now says something else. Live PoCs, real hub:

1. **RECON, the normal flow.** RECON opens and the notice reads `RECON · WIFI STANDBY — offline`. The
   operator taps the BLE sub-tab within 7 s. `_switch("BLE")` → `set_chip("sdr", "BLE STANDBY — offline")`, and the notice becomes:
   ```
   RECON · WIFI STANDBY — offline
   RECON · BLE STANDBY — offline
   ```
   `shown_status()["sdr"]` is only BLE. The WIFI line is from a sub-tab that is no longer on screen.
2. **ATLAS, the same key.** `ADS-B NO FEED · …` (warn), then the feed reports stale: the notice shows
   `ADS-B NO FEED · DF — · BALLOONS —` **and** `ADS-B STALE 12s · DF — · BALLOONS —` at once. One sentence says no feed and the other says a stale feed.
3. **A cleared warning.** `FIRST PROBLEM` shows. The key is cleared, and then `SECOND PROBLEM` is raised: the notice lists both,
   while `shown_status()` holds only `sdr` and `probeB`.

Each `new` restarts the 7 s timer, so the stale lines stay up as long as new ones keep arriving. This is exactly
the honesty problem CLAUDE.md asks us to avoid: the notice claims as current something the page no longer reports.

**Fix (small, UI-only):** keep what is showing by key, `self._shown = {key: text}`. On a join, rebuild the
lines from `cur`: the keys that were in the visible notice *and are still in `cur`* with their current text, plus the new
ones. A replaced or cleared key then drops out. Regression test: the RECON WIFI→BLE PoC above asserts `"WIFI" not in
n.text()`, and the FIRST/SECOND PoC asserts `"FIRST" not in n.text()`.

### N13 — Low (fixed by N12's fix) — the joined notice has no bound
Lines are deduplicated by their exact text, so a key that alternates between two messages, one of them carrying a
number, adds a line on every swing. PoC (pure `PageNotice`, parent 1280x680, anchored): 60 swings of
`LINK LOST after %d tries` (alert) ↔ `RECONNECTING` (warn) give **61 lines, a label 1484 px tall at y=0, on a 680 px page**.
It runs off the page. On the device today the cases I found are bounded: NWR `DOWN ×n` ↔ `waiting for audio` is capped by the
flap FAULT at 3 exits, and RECON WIFI↔BLE has only 2 texts. So this is Low. Rebuilding the lines from `cur` (N12) bounds them to the number of keys.
If you also want a guard, add `setMaximumHeight` / elide.

### N14 — Low (owner's call, listed for Dalton) — a repeat of the same warning while away under 60 s is not re-announced
See N10 above. The options are: leave it (my recommendation; the text is the same one he saw under a minute ago, and a real
fault is also in LOG / ALERTS); or record a clear seen while away (`_page_status` for an off-screen page could
drop the cleared keys from `_active[page]`) so that a fresh occurrence re-announces.

### N15 — Info — a status that arrives after close restarts the hide timer
See N8 above. It is harmless.

## UI-only and lifecycle
- UI-only: `PageNotice` and `closeEvent` (the `notice.stop()` call) change; the `ops.py` change is a comment. No data, decode
  or radio path is touched.
- Lifecycle: both timers are stopped on close, and `refresh` and `blocked` are cleared. There is a residual Info (N15).
- pyflakes is clean on `palisade_qt/shell.py` and `tests/test_shell_frame.py`.

## Tests
`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q -p no:cacheprovider --timeout=240
--timeout-method=thread`, one file per process:
- `tests/test_shell_frame.py`: **23 passed** (20 + 3 new).
- `tests/test_cl1_fix3.py`: **17 passed**.

40 passed, 0 failed. The new join test (`test_ra_s1c_a_second_warning_joins_the_notice_showing`) only
checks that two distinct, still-active warnings both show. It does not cover a cleared or replaced key (N12).

## Decision
**DO NOT MERGE** until N12 is fixed and has a regression test. It is a few lines in `consider`, and the same fix closes N13.
N6, N8 and N10 are fixed. N7, N14 and N15 are not blockers. N7 and N14 are listed for Dalton.
