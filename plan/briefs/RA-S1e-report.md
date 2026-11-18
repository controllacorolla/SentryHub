# RA-S1e — targeted cold re-audit of the RA-S1d fix (`fix/shell-frame`, PR #33)

Auditor: a fresh session (Opus), working in its own worktree off `origin/fix/shell-frame` at `cbc8a12`.
Scope: `git diff 337b91a..origin/fix/shell-frame -- palisade_qt tests`, which touches `palisade_qt/shell.py`
(`PageNotice.consider` and the new `_show_keys`) and adds 2 tests to `tests/test_shell_frame.py`.
Every PoC below ran live on a real hub (`_big_hub`, 1280x720, offscreen) unless it says otherwise.

| Item | Check | Verdict | Evidence |
|---|---|---|---|
| N12 RECON | WIFI to BLE sub-tab within 7 s | **Fixed** | RECON opens and the notice reads `RECON · WIFI STANDBY — offline`. Then `_switch("BLE")` makes it `RECON · BLE STANDBY — offline`, one line, with no `WIFI`. Switching back to WIFI shows WIFI only. |
| N12 ATLAS | NO FEED to STALE on the real `sdr` key | **Fixed** | `ADS-B NO FEED · …` (warn), then `ADS-B STALE 12s · …`. The notice shows the `HOME NOT SET …` line and the `STALE 12s` line. `NO FEED` is gone. |
| N12 cleared | FIRST cleared, SECOND arrives | **Fixed** | The notice lists the page's still-reported `sdr` and `home` lines plus `SECOND PROBLEM`. `FIRST` is not there. |
| N12 clear only | a line whose warning cleared goes without a new warning arriving | **Fixed** | `pz` is cleared with nothing new arriving: its line goes, the other lines stay, and the timer runs on. |
| N12 hide | the notice hides once nothing it showed is still reported | **Fixed** | On FORGE, `ONLY PROBLEM` shows. When it clears, `isVisible() == False`. The unit test covers the same thing (`consider("ATLAS", {})`). |
| N13 | the notice is bounded by status keys | **Fixed** | `_keys` holds one entry per key and the lines are rebuilt from `cur`, so there is at most one line per key. The test runs 60 swings and gets 1 line. The height is still not capped, but it can grow only with the number of distinct warning keys a page has (ATLAS has about 3 today). |
| F2 | a ticking counter stays silent | **Fixed, and correct** | `STALE 12s` to `14s`: the text is rewritten in place, and the timer is set to its remaining time (6035 ms before, 6050 ms after; the extra few ms are from the event pump). It is not restarted at 7 s and nothing is re-shown. Once the notice is hidden, a tick does not show it again. Rewriting in place is right: the notice must not show a stale number, and the timer must not be extended. |
| N1 | same key, different message, is new | **Kept** | WIFI to BLE re-shows the notice and restarts the timer. The old unit test (lines 374-379) still passes. |
| N2 | a panel holds the notice back, and the retry shows it | **Kept** | A new key raised while ALERTS is open is not shown. When the drawer closes, the 700 ms retry shows it (`… · OLD`). The test `test_ra_s1b_n2_…` passes. Caveat: see N16. |
| N3/N10 | 60 s reminder | **Kept** | `_active`, `_left` and `forget` are unchanged. The tests `test_ra_s1b_n3_…` and the N10 test pass. |
| N6 | an ATLAS layer count going `—` to `1` is not new | **Kept** | `DF —` to `DF 1` is rewritten in place, and the timer is left as it was (6025 ms). |
| N8 | timers stop on close | **Kept** | `stop()` is unchanged. The N8 test passes. N15 (Info) is still there: a status that arrives after close and is new starts `_timer` again (seen: `_timer.isActive() == True`). The new in-place path cannot do this, because `isVisible()` is false after close. Harmless. |
| `show_all` | a click on the page name, or the palette | **Unaffected** | `_page=None`, so a tick does not touch the full list. Its text and its 12 s timer are left as they were. |
| UI-only | | **Yes** | Only `PageNotice` changed. No data, decode or radio path is touched. |
| Lifecycle | | **Yes** | It adds no timer, thread or connection. pyflakes is clean on `shell.py` and `test_shell_frame.py`. |

## New findings

### N16 — Low (regression of F8, non-blocking) — an in-place rewrite raises the notice above an open drawer
`_show_keys(restart=False)` calls `_show()`, and `_show()` does `show()` and `raise_()`. At `337b91a` an
unchanged warning did nothing at all. Now a tick, a layer count change or a cleared line all redraw the notice and raise it.
The `blocked()` check only guards the `newk` path. So a notice that was showing when a drawer opened jumps on top of
the drawer at the next status change (on ATLAS, a 1 Hz `STALE ns` counter does this almost at once).

PoC (live hub, ATLAS): `set_chip("t","STALE 1s","warn")` shows the notice. `open_panel("alerts")`. The z-order in
`central.children()` is then notice 19, drawer 21: the drawer is on top. Then `set_chip("t","STALE 2s","warn")`, and the
z-order becomes notice 21, drawer 20. The notice is on top, and the two overlap: notice (764,592,504x116), drawer (140,100,1000x560).
The notice accepts clicks (click to dismiss), so it also catches taps meant for the drawer's lower-right corner. This lasts until
the remaining ≤ 7 s run out.

F8 was rated Low, so this is Low too. Possible fixes: in the `restart=False` branch, when `blocked()` is true, only
`setText`/`adjustSize` with no `raise_()`. Or hide the notice when a panel opens.

### N17 — Info — a blocked new key leaves a line that cleared at the same moment on screen until the retry
When one status change both clears key A and raises a new key B while a panel is open, `consider` takes the blocked
early return before the rebuild. A's line stays visible, under the drawer, until the retry about 700 ms after
the drawer closes, which rebuilds the notice correctly. It is not visible to the operator (the drawer covers it, apart from N16), and it is short-lived.

### N18 — Info — a replaced key's line moves to the bottom
`keys = [kept…] + newk`, so a re-shown key (WIFI to BLE, NO FEED to STALE) is listed last instead of keeping its
place. Seen in the ATLAS PoC: `HOME NOT SET` moved above the `sdr` line. This is cosmetic. One could argue it is useful, because the newest line is at the bottom.

## Tests
`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q -p no:cacheprovider --timeout=240
--timeout-method=thread`, one file per process:
- `tests/test_shell_frame.py`: **25 passed** (23 + 2 new: `test_ra_s1d_n12_…`, `test_ra_s1d_n13_…`).
- `tests/test_cl1_fix3.py`: **17 passed**.

The new tests cover what RA-S1d asked for: `"WIFI" not in`, `"FIRST" not in`, hide when empty, and one line on the same key. They use a
bare `PageNotice`; the live hub PoCs above confirm the same behaviour end to end. No test covers N16.

## Lows for Dalton (judgement calls)
- **N16**: fix the raise above a drawer now (2 lines), or accept it as F8-class Low.
- **N7, N14** (from RA-S1d) are still open as owner's calls. This fix does not change them.

## Decision
**MERGE.** N12 and N13 are fixed, and there are regression tests for both. F2, N1, N2, N3/N10, N6 and N8 still hold, and `show_all` is
unaffected. The only new finding with operator impact is N16, which is Low, so it does not block.
