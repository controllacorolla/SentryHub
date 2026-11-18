# RA-S1c — targeted cold re-audit of the RA-S1b fixes, `fix/shell-frame` (PR #33)

Auditor: fresh session, own worktree, detached at `origin/fix/shell-frame` da49f28.
Scope: `git diff c4ed94e..origin/fix/shell-frame -- palisade_qt tests` (1 commit: `shell.py` +53/−9,
`theme.py` 2 lines, `tests/test_shell_frame.py` +58, 4 new tests).
Bar: RA-S1b N1–N5 and F10, and Dalton's "Device run 2" batch 3 note (no permanent bottom bar; "a small
message is OK somewhere, but not there").
PoCs: a live hub (`demo=False`) and a demo hub at 1280x720, offscreen. Renders: Xvfb 1280x720x24,
`QT_QPA_PLATFORM=xcb`, `shell.show_fitted(hub)` (opens maximized), DARK / LIGHT / SUN.

## Verdict: **DO NOT MERGE** (one small fix)

N2, N3 and N4 are fixed. F10 is fixed apart from two stale comments. N1 is fixed for the case it
named (RECON WIFI STANDBY → BLE STANDBY now notifies). But the new signature brings back the F2
problem on ATLAS:

- **N6 (Medium, regression from the N1 fix):** ATLAS's `sdr` chip is `warn` in live mode whenever
  the ADS-B feed is down, and its text holds per-layer counts that read `—` at zero and a number
  otherwise. `_sig` maps digits to `#` but leaves `—` alone. So each time a layer goes 0 ↔ 1 (a
  balloon, DF bearing, APRS station or vessel appears or ages out), the same
  "ADS-B NO FEED" warning pops up again for 7 s. A real live PoC gives 6 notices for 7 chip
  updates. The `(key, state)` dedupe at c4ed94e gave 1. On the device, with no ADS-B feed, this is
  the repeating message Dalton asked to be rid of.

Fix: make `—` part of the "numbers" in `_sig` (for example `re.sub(r"\d+|—", "#", text)`). The
better fix is to give ATLAS's ADS-B health its own chip key (`adsb`, warn/alert) and keep the
layer-count chip `neutral`. Add a regression test that drives the real `_layer_summary` with
`_adsb_health={"state": "none"}` through `[] → [balloon] → []` and expects one notice. The re-run
can be scoped to `PageNotice` plus ATLAS's chip.

## Per-finding table

| # | RA-S1b finding | Status | Evidence |
|---|---|---|---|
| N1 | different warning on the same key swallowed | **Fixed for the named case; regression N6** | `_sig = (state, re.sub(r"\d+","#",text).strip())`. Live PoC: a different text on the same key and state shows. A ticking counter (`(12s)` → `(13s)`) does not. alert → warn with the same message does not (`was[0]=="alert" and was[1]==sig[1]`). warn → alert with the same message does show, which is right: it is an escalation. Unit test `test_ra_s1b_n1_…` covers WIFI→BLE STANDBY. **Digit-only differences:** no warn/alert text in `palisade_qt` today differs only in a channel number ("CH 1" vs "CH 6" does not exist). The real cases are PROWL `"locked out %.4f"` (warn, `prowl.py:1253`): locking out 146.5200 and then 162.4000 shows only the first (PoC). Also `on_fault` messages that differ only in a number and change without clearing in between. Both are low impact (N7). The case that does matter goes the other way: `—` is not a digit (N6). |
| N2 | warning held under an open panel never shows | **Fixed** | When blocked, `consider` keeps in `_active` only the signatures that are already shown and unchanged, and starts the 700 ms single-shot retry. PoC: ALERTS open, `HELD 3` raised, not shown; drawer closed, shown within 1 s. **Never loops forever:** `_on_retry` restarts only while `blocked()`. When not blocked it calls `refresh` once, and `consider` restarts the timer only on the blocked branch. After the panel closed, the PoC counted 0 timeouts in 2 s. While the panel is open it polls at most every 700 ms. On ATLAS the page's own status traffic restarts it first, so it observed 0 timeouts in 3 s, and the notice came from the next status update instead (Info N9). **Wrong page:** `refresh` reads `self._current` when it fires, and the page left is `forget`-ed. PoC: warning held on ATLAS, switch to SYSTEM with the drawer still open, close the drawer, wait 1.2 s: nothing is shown on SYSTEM. It shows on return to ATLAS. **After close:** it fires once (N8, Low). Test `test_ra_s1b_n2_…` exercises the real hub. |
| N3 | still-active warning not shown on return | **Fixed** | `show_page` calls `notice.forget(self._current)` before switching. PoC and test `test_ra_s1b_n3_…`: ATLAS → SYSTEM → ATLAS re-shows "STILL BROKEN". **Quick flipping:** 10 ATLAS↔SYSTEM flips give 10 notices. There is one `QLabel`, so they never stack. Each flip hides the old notice (`show_page`). None appeared on SYSTEM. **Noise on arrival** (live, no hardware): ATLAS shows 2–3 lines on every visit (ADS-B NO FEED…, HOME NOT SET…), RECON shows "WIFI STANDBY — offline" and PRISM "SDR ACQUIRING". OPS, PROWL, FORGE, ASSISTANT, MESH and SYSTEM show nothing. This is what N3 chose (RA-S1b left the noise to Dalton). Flagged as N10. |
| N4 | open nav key focus a hairline | **Fixed** | `navkey_on:focus { border: {focus_w} solid {focus_on}; }`. Rendered the ATLAS key unfocused vs Tab-focused (window active, `hasFocus()==True`) in all three themes. **DARK:** a white 2 px ring on #A492DA, clearly visible (653/5520 px differ). **LIGHT:** a black 2 px ring on #5A4790, clearly visible (656 px). **SUN:** a white 4 px ring on the white rail, 1232 px differ. It reads as the black tile shrinking 4 px a side with squarer corners, not as a ring. That is the same look as the F5 open-sub tile, visible but not a ring (Info). **No shift:** key size (115x48 / 114x48 SUN) and the call label geometry `(5,3,105,20)` are identical focused and unfocused in every theme, so the text does not move. The test only checks the QSS string (Low, as before). |
| F10 | stale docstrings | **Fixed**, two stale comments left | `shell.py:9` ("There is no footer: the rail holds the page keys…") and `set_nav_hidden` ("the number keys still switch pages") now match. `overwatch.py:1` "(key 2)" is still right (ATLAS is key 2). Still stale (Info): `PageNotice.__init__` comment `self._active = {}  # page -> {key: state}`, which now holds `(state, skeleton)` signatures; `ops.py:73` "not a bare PWR in this footer". |
| N5 | Info | unchanged | Sub-tab switches still do not hide the notice. The prefix keeps it honest. |

## New findings

### N6 — Medium (blocker; regression from the N1 fix) — ATLAS re-notifies "ADS-B NO FEED" whenever a layer count goes 0 ↔ 1
`atlas.py:_layer_summary` builds the `sdr` chip as `"ADS-B NO FEED · DF — · BALLOONS —"` (state `warn`)
or `"ADS-B STALE 12s · …"` (`alert`). A layer at zero reads `—`, and at n reads the number. `_sig`
only folds digits, so `"BALLOONS —"` and `"BALLOONS 1"` are different warnings, and the whole line is shown again for 7 s.
At c4ed94e the `(key, state)` dedupe swallowed these. Live hub, real `_layer_summary` + `set_chip`:
```python
hub.open_callsign("ATLAS"); a = hub.page_app("ATLAS"); a._adsb_health = {"state": "none"}
for s in ([], [{"kind":"balloon"}], [{"kind":"balloon"}]*2, [], [{"kind":"df"}],
          [{"kind":"balloon"},{"kind":"df"}], []):
    t, st = a._layer_summary(s); a.set_chip("sdr", t, state=st); pump(30)
# notices: 6 of 7 updates ->
#  'ATLAS · ADS-B NO FEED · DF — · BALLOONS —', '… BALLOONS 1', '… BALLOONS —', '… DF 1 · BALLOONS —', …
```
Contacts age out on `STALE_S`, so with sparse APRS, balloon or DF traffic this repeats every few minutes for
as long as ATLAS is on screen. Fix: see the verdict.

### N7 — Low — digit-only distinct warnings collapse
`PageNotice("dark", w).consider("PROWL", {"scan": {"text": "locked out 146.5200", "state": "warn"}})`
returns the line. The same call with `"locked out 162.4000"` returns `[]`. The operator caused the
lockout and sees the chip, so this matters little. No "CH 1"/"CH 6" style warning exists in the code today. Accept and
document in `_sig`'s docstring, or exempt frequencies (`\d+\.\d+`) from the fold.

### N8 — Low (lifecycle) — the retry can fire once after the hub closes
`closeEvent` does not stop `notice._retry` (or `notice._timer`). Parenting only frees them when the
hub is deleted, which `close()` does not do. PoC: ALERTS open, new warning held (retry active),
`hub.close()`. After 2.5 s `refresh` had run once, calling `_page_status` → `shown_status()` on the
already-stopped ATLAS page → `_show` on a hidden window. Nothing is visible and nothing crashed, but it runs
code on a stopped page. Fix: `self.notice._retry.stop(); self.notice._timer.stop()` in `closeEvent`,
and add an assert to the close test.

### N9 — Info — the retry is debounced by page traffic
Each blocked `consider` restarts the single-shot. On a page that emits status more often than
every 700 ms (ATLAS), it never times out while the panel is open. After the panel closes, the next status
update shows the held warning, so the result is right. It does not loop.

### N10 — Low (owner's call) — every arrival on a page with a standing warning pops the notice
This is a consequence of the N3 fix. In live mode without hardware, every visit to ATLAS (2–3 lines, 7 s), RECON or PRISM
shows a notice, and 10 flips give 10. It never stacks and never shows on the wrong page. Dalton asked for "a little
message"; whether it should re-show on every return is his decision. A cheap middle ground is to re-show
on return only if the warning is older than N minutes, or only once per session per page.

### N11 — Info
When a panel blocks, keys that de-escalated (alert → warn, same message) are dropped from
`_active`. After the panel closes, that warn shows as new. This only happens when another new warning
was held in the same call. It is harmless.

## UI-only and lifecycle
- UI-only: the diff touches only `PageNotice`, `show_page`'s notice bookkeeping, one QSS rule and docstrings.
  No data, decode or radio path changes.
- The new `QTimer` is parented to the notice, which is parented to the central widget, and dies with the hub.
  It is **not stopped on close** (N8).
- pyflakes: clean on `shell.py`, `theme.py`, `tests/test_shell_frame.py`.

## Tests
`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q -p no:cacheprovider --timeout=240
--timeout-method=thread`, one file per process: `tests/test_shell_frame.py` **20 passed** (16 + 4
new); `tests/test_cl1_fix3.py` **17 passed**. 37 passed, 0 failed. The new tests do not cover N6 or N8.
Full suite not run (per brief).
