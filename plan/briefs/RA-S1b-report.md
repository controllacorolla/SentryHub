# RA-S1b — cold re-audit of the RA-S1 fixes, `fix/shell-frame` (PR #33)

Auditor: fresh session, own worktree, detached at `origin/fix/shell-frame` a0483cb.
Scope: `git diff 91275a1..origin/fix/shell-frame -- palisade_qt tests` (1 commit, 8 files, +153/−28),
plus regressions it causes in the Stage 1 diff (`origin/fix/ui-polish..origin/fix/shell-frame`).
Bar: RA-S1 F0–F13 and Dalton's "Device run 2" notes (items 1–6, 26).
Renders: Xvfb 1280x720x24, `QT_QPA_PLATFORM=xcb`, `shell.show_fitted(hub)`, DARK / LIGHT / SUN, demo.
PoCs: live and demo hubs, offscreen, scripts in the auditor scratchpad (snippets below reproduce each).

## Verdict: **DO NOT MERGE** (one small fix)

F0, F1, F2, F4, F7 and the DARK part of F11 are fixed, and the F5 focus cues now render in every theme.
One thing blocks:

- **N1 (Medium, regression from the F2 fix):** the notice now dedupes on `(key, state)`, so a
  *different* warning that arrives on the same key in the same state is swallowed. RECON keeps one
  `sdr` chip for all its sub-tabs. WIFI STANDBY (warn) → BLE STANDBY (warn) never raises a notice.
  The old `(page, key, text)` dedupe did show it. With the bottom bar gone, the notice is the only
  push channel for a new warning, and the brief asks exactly this ("is a real new warning ever
  swallowed?").

Two Low items should be fixed in the same pass, because they are the same `_active` bookkeeping. **N2:**
a warning suppressed while a panel is open is recorded as shown, so it never appears after the
panel closes (F8 is only partly fixed). **N3:** a still-active warning is not shown again when you come back
to its page (F3, residual). Fix N1 (N2/N3 advised) and re-run on the delta. The re-run can be scoped to `PageNotice`.

## Per-finding table

| # | RA-S1 finding | Status | Evidence |
|---|---|---|---|
| F0 | `test_eight_keys_in_order_with_function_labels` red | **Fixed** | The test still pins the exact `ALL_CALLSIGNS` and `CALLSIGNS` order (SYSTEM last, SWEEP hidden), `nav_keys` order, `call.text() == name` (no digit), and `"key %d" % i` in each tooltip, so the digit shortcut follows rail order. Function labels are unchanged. This is the new contract, still a real check, not a relaxed one. Passes (see Tests). |
| F1 | BAT / SDR presence freeze off OPS | **Fixed** (live) | `LiveStatusWorker.PAUSE_WHEN_HIDDEN = False`. Live hub on PRISM: worker not paused, 3 telemetry events in 4.5 s. Minimized: 2 events in 4.5 s (one sysfs read every 2 s, a negligible cost; before the fix it already ran while minimized on OPS). After `hub.close()`: worker `isRunning() == False`, 0 events in 4.5 s, and `_on_bus` is disconnected in `closeEvent` (unchanged). The decode log is time-windowed (`DECODE_WINDOW_S` 600 s, telemetry filtered), so 0.5 telemetry events/s cannot evict real decodes from SITREP. Residual: `DemoFeedWorker` still pauses, so in `--demo` the BAT slot freezes off OPS (Info, by design per the test). The regression test checks the class flag and `paused`, not that the BAT slot actually updates off OPS, as RA-S1 asked (Low). |
| F2 | counter text makes the notice permanent | **Fixed**, but see **N1** | `consider` keys on `(page, key) -> state`. 12 updates of `"no audio (%ds)"` in warn produce 1 notice (test + PoC). Two pages cannot pile up: there is one `QLabel`, `_show` replaces its text, and `show_page` hides it. The fix over-reaches: a different warning text on the same key and state is also swallowed (N1). |
| F3 | notice follows you to another page | **Fixed**; residual **N3** | `show_page` hides the notice on a page change. Lines are prefixed `"PAGE · "`. PoC: ATLAS warning shown, then SYSTEM: hidden. A warning *raised while away* does show on return ("ATLAS · RAISED WHILE AWAY"). A warning that was showing when you left and is still active does **not** show on return. It is lost until it clears and returns (N3). |
| F4 | cleared-and-returning warning never re-notifies | **Fixed** (on screen) | PoC and test: clear, then the same warning again, shows again. warn → alert shows (escalation). alert → warn is silent, which is correct. Only on the page on screen: a clear-and-return while away is not seen on return (part of N3). |
| F5 | SUN open-sub focus invisible; weak nav-key focus | **Fixed** (visible), weak in places | Rendered SKY DOME open/closed sub tiles and PRISM/ATLAS nav keys, focused (Tab reason) vs unfocused, in all three themes. **Open sub** (`:checked:focus`, `focus_on`): DARK white 2 px ring on #C9BCF2 (1.76:1, visible), LIGHT black ring (12.9:1), SUN white 4 px ring inside the black tile. In SUN the ring is white on the white rail, so the cue reads as "the tile shrinks and loses its rounding" (1792 of 4028 px change). It is visible but not a ring (Info). **Closed sub**: a thick border in all themes (816–857 px change). **Closed nav key**: `focus_w` over and under (SUN 2 → 4 px black, DARK/LIGHT 1 → 2 px in the focus colour), visible in all renders. **Open nav key** (`navkey_on:focus`, unchanged by this PR): still only a thin double underline, barely visible in all three themes (N4, Low). The regression test is a QSS-string check only, with no rendered focus check (Low). |
| F6 | BENCH TX not on `set_run` | **Unchanged, by design** | `bench_app.py` is not in the fix diff. Left for Dalton. |
| F7 | disabled volume looks enabled | **Fixed** | `::handle:horizontal:disabled` now matches. Enabled vs disabled: 296/3834 px differ in DARK and LIGHT, 206/3834 in SUN (was 0/1950). The rendered result: SUN shows a grey dashed ring instead of the black knob. In DARK the 1 px dashed `disabled` border on the dark strip renders as a few specks, so the handle all but disappears. That reads as "off", which is the point (Info). The test diffs real grabs, which is a real check. |
| F8 | notice drawn over an open overlay | **Partly**; see **N2** | `_panel_open` covers all 7 shell overlays (radios, engage, tx, alerts, keymap, palette, log, the same set as `_overlays`). PoC: no notice while the ALERTS drawer is open. **But after the drawer closes, the still-active warning never shows**: `consider` recorded it in `_active` while suppressed. The test reaches it only through the manual "Page messages" command. |
| F9 | no keyboard path to page messages | **Fixed**; empty state not honest (carried F13) | Keyboard only: `/`, type `messages`, Enter. The palette lists exactly one match, closes, and the notice shows the current page's messages (SYSTEM, ASSISTANT, ATLAS). Empty state: on SYSTEM/ASSISTANT/ATLAS (live) it shows **"SDR —"**, not "SYSTEM: nothing to report", because every `PalisadeApp` seeds an `sdr` chip (F13). The honest empty state is unreachable on those pages (Low, pre-existing). `show_all` lines carry no page prefix (Info: the operator just asked for this page). |
| F10 | stale key-number docstrings | **Partly** | Fixed: `shell.py:1-6`, `ops.py:26`, `topbar.py:1,143,240`, `recon.py:1`, `sweep.py:1`. Still stale: `shell.py:9` "There is no left rail and no footer", which now contradicts line 1. `shell.py:367` "(1-7 still switch pages)". `overwatch.py:1` "(key 2)" is still correct. |
| F11 | DARK closed page vs sub tile; ATLAS views flat | **Fixed (DARK)**; ATLAS views unchanged by design | DARK `sub_bg` alpha 0.24 → 0.36. Rendered fills: closed page #3c3b51, closed sub #57556c (1.51:1 between them, was near-identical), open sub #c9bcf2 (4.09:1 vs closed sub), rail #0c0f13. All three are distinguishable in the render. LIGHT (closed page/sub 1.16:1) was not in F11's scope. SUN is uniform white by design. ATLAS view row (`atlas.py`) untouched, left for Dalton. |
| F12 / F13 | Info | unchanged | F13 now also affects F9's empty state (above). |

## New findings

### N1 — Medium (blocker; regression from the F2 fix) — a different warning on the same key is swallowed
`PageNotice.consider` skips a key whose state is unchanged (`before.get(key) == v.get("state")`),
whatever its text. Several pages put different warnings on one key: RECON's `sdr` chip carries the
chip of whichever sub-tab is on screen (`recon.py:_switch/_tab_chip`). Switching RECON WIFI → BLE (both
warn in live mode with no adapters) never notifies the BLE warning. Before the fix, the
`(page, key, text)` dedupe showed it. The same happens for any page whose chip text changes from one
warn to another (for example `ATLAS · probe` REMOTE-ID SETUP NEEDED → GNSS JAMMING SUSPECTED).
```python
# live hub, offscreen 1280x720
hub.open_callsign("ATLAS"); a = hub.page_app("ATLAS")
a.set_chip("probe", "REMOTE-ID: SETUP NEEDED (no bleak)", state="warn")   # notice: shown
hub.notice.hide(); a.set_chip("probe", "GNSS JAMMING SUSPECTED", state="warn")
hub.notice.isVisible()  # False
hub.open_callsign("RECON", "WIFI")      # sdr = 'WIFI STANDBY — offline' (warn)
hub.open_callsign("RECON", "BLE")       # sdr = 'BLE STANDBY — offline' (warn)
hub.notice.isVisible()  # False
```
Fix: dedupe on `(key, state, skeleton)`, where the skeleton is the text with digits stripped
(`re.sub(r"\d+", "#", text)`). This keeps F2 (a counter is not new) and restores "different words =
new warning". Add a test with two different texts on one key, and the RECON WIFI→BLE case.

### N2 — Low — a warning suppressed under an open panel is marked as shown and never appears (F8)
`consider` writes `self._active[page]` before checking `blocked()`. A warning that arrives while
ALERTS, the palette or any panel is open counts as already shown. When the panel closes it does not
appear, and it never will until it clears and comes back. Only the explicit page-name click or
"Page messages" reveals it.
```python
hub.open_callsign("ATLAS"); hub.open_panel("alerts")
a.set_chip("probe3", "DRAWER-TIME WARNING", state="warn")      # suppressed (correct)
hub.open_panel("alerts")                                       # drawer closed
a.set_chip("probe3", "DRAWER-TIME WARNING", state="warn"); pump(500)
hub.notice.isVisible()  # False
```
Fix: when blocked, do not record the new keys (leave `_active[page][key]` at its previous state), or
re-run `consider` for the current page when the last overlay closes.

### N3 — Low — a still-active warning is not shown again when you return to its page (F3 residual)
`show_page` hides the notice, but `_active[page]` keeps the warning as shown. On return, the warning is
still active and still listed by "Page messages", but no notice appears. A warning that clears and
comes back while you are away is also missed (`_active` is only updated for the page on screen).
```python
a.set_chip("probe4", "STILL-ACTIVE WARNING", state="warn")   # shown on ATLAS
hub.open_callsign("SYSTEM"); hub.open_callsign("ATLAS")
hub.notice.isVisible()  # False; shown_status()["probe4"] is still warn
```
Fix (either is fine): on a page change, drop `_active` for the page being left, so its active warnings
re-notify when you come back. Or accept it and say so in the docstring. This is Dalton's call on noise.

### N4 — Low (pre-existing) — the open nav key's focus cue is a hairline
`QPushButton.navkey_on:focus` draws only a thin double underline in `focus_on`. In the renders it is
barely visible in DARK, LIGHT and SUN (ATLAS key focused vs not: 386–580 px differ, all in a 1–2 px
line at the tile's bottom edge). Focus lands there only by Tab (`show_page` sends focus to the hub),
so the impact is small. Consider the same `focus_w` over and under used for closed keys.

### N5 — Info
- A sub-tab switch inside one page does not hide the notice (the RECON WIFI notice stays over the BLE
  tab). The line says "RECON · WIFI …", so it is not misleading.
- `test_ra_s1_f1_…` builds an unused `LiveStatusWorker()` (never started). Harmless.

## UI-only and lifecycle
- No data, decode or radio behaviour change. The only non-styling code change outside `shell.py` is
  the OPS telemetry worker's pause flag, a sysfs read that does not touch the SDR or arbiter.
  `bench_app.py`, `atlas.py`, `prowl.py`, `babel.py` are untouched by the fix commit.
- Disconnected on close: `eventbus.bus.published → _on_bus` (unchanged). The notice timer is parented.
  `notice.blocked` is a bound method of the hub and dies with it. The OPS worker stops with the page
  (`isRunning() == False` after `close()`, no further telemetry).
- pyflakes: clean on all changed files.

## Tests
`QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q -p no:cacheprovider --timeout=240
--timeout-method=thread tests/test_shell_frame.py tests/test_cl1_screen.py tests/test_cl1_fix3.py
tests/test_ui_polish.py`, run one file per process: `test_shell_frame.py` 16 passed (11 + 5 new);
`test_cl1_screen.py` 51 passed (F0 green; the known flake `test_up_down…` passed too);
`test_cl1_fix3.py` 17 passed; `test_ui_polish.py` 104 passed. **188 passed, 0 failed.** The new tests do not cover N1–N3.
Full suite not run (the thread runs it).
