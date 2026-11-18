# RA-S1 — cold audit of device-run-2 Stage 1 (frame and shell), `fix/shell-frame` (PR #33)

Auditor: fresh session, own worktree, detached at `origin/fix/shell-frame` 6b084f1.
Scope: `git diff origin/fix/ui-polish..origin/fix/shell-frame -- palisade_qt tests` (2 commits,
9 files, +654/−56). Bar: Dalton's own notes ("Device run 2", `device-notes.md`), not the plan wording.
Renders: Xvfb at 1280x720x24 (`QT_QPA_PLATFORM=xcb`), `shell.show_fitted(hub)`, DARK / LIGHT / SUN,
demo and live. No window manager in the container: "maximized" here is `windowState()==Maximized`
plus the size cap. The plan's "verified on a real window" check is still owed on the device.

## Verdict: **DO NOT MERGE** (yet)

The frame work is good: the window no longer grows, the rail matches what Dalton asked for, the tiles
are in, and the strip fits at 1280 in every theme. Four things block it, and each is a small fix:

- **F0:** the PR turns a test red (`test_cl1_screen::test_eight_keys_in_order_with_function_labels`).
- **F1:** the new BAT slot, and the SDR ABSENT/BLOCKED state in the strip, stop updating as soon as
  the operator leaves OPS.
- **F2:** the notice that replaced the bottom bar becomes a permanent overlay when a warning's text
  carries a counter (PROWL › NWR re-raises it every 400 ms).
- **F3:** a notice from one page stays up after a page switch, does not say which page it came from,
  and covers the bottom-right control of the new page (SYSTEM › BENCH: KEY CONDUCTED TX).

F2 and F3 are the bottom bar coming back in another form, which item 26 was meant to remove. F1 means
the power reading Dalton asked to have in a fixed, labelled slot (item 4) is often stale. Fix F0–F3
(F5 strongly advised) and re-run this audit on the delta.

## Per-item table

| # | Dalton's note | Answers it? | Evidence |
|---|---|---|---|
| 1 Window | "Going from full map back to regular knocks the window out of maximized and extends it beyond the screen"; "the window keeps resizing itself" | **Yes** (still needs a run on the real window) | `PageStack` min 320x240 with Ignored policy. On a 1280x720 screen, `show_fitted` returns `maximized`, the window state is Maximized and the size cap is 1280x720. Every page and every sub-tab (24 combinations) at DARK demo, LIGHT live and SUN live: hub 1280x720. F on ATLAS and OPS ×2 at each sub-tab: no change. RADIOS / ENGAGEMENT / TX / ALERTS / KEYS overlays: no change. "window" path (1920x1080 screen, no max cap): 1280x720 at the worst-case strip in all 3 themes, live and demo. No page is clipped: the largest page minimum is PRISM 994x223 and PROWL 863x451, against a 1140x668 stack in demo and 1152x680 in live. |
| 2 Rail | "Get rid of the numbers"; "left side too condensed … space items evenly down to just above the bottom"; "System settings should go last" | **Yes** | No digits on keys. SYSTEM is last (`CALLSIGNS[-1]`). With no sub-tabs open, the gaps are even (26/27 px) and the last key ends 18 px above the rail bottom (650/668 demo, 662/680 live). With a sub-list open, the keys shrink to 41–45 px with 6 px gaps; nothing overlaps and no text is clipped (checked FORGE/PROWL/RECON/SYSTEM, DARK+SUN). The digits follow the new order everywhere a user sees them: the hotkey (`CALLSIGNS[int-1]`), the palette (`enumerate(CALLSIGNS)`), tooltips ("SYSTEM — settings (key 9)") and the key map ("1 – 9"). Hidden SWEEP leaves no gap, because it is filtered out of `CALLSIGNS` before numbering. Docstrings are stale: F10. |
| 3 Tiles | "If modules use tiles, they all need to be tiles: purple for modules, light purple for sub-modules" | **Partly** | Every rail sub-list (ATLAS/PROWL/RECON/FORGE/SYSTEM) uses the light-purple `subtab` tile. Open tiles read clearly in all themes: text contrast 7.0 (DARK page), 10.9 (DARK sub), 7.7 / 9.1 (LIGHT), 21 (SUN). Gaps: in SUN, the open sub tile has no focus cue at all (F5). In DARK, a closed page tile (#3c3b51) and a closed sub tile (#424254) look almost the same, so "purple vs light purple" shows only on the open one (F11). ATLAS's own view row (ALL/AIR/…) is `class="subtab"` but sits outside the rail, so it stays flat grey (F11). |
| 4 Strip | "Unknown 0221Z"; "Power percentage in a random spot"; "Unclear logo next to CONTACTS LIVE and the item to its left" | **Partly** | The clock now reads "UTC 0438Z" with a tooltip. ALERTS and BAT are captioned. OPS reads "CONTACTS ON MAP —" with tooltips, and "ALL FEEDS" has a tooltip. The second power indicators are gone everywhere: the footer PWR chip, the OPS POWER card (now HOME), and `kit.StatusHeader` is unused. The only other "BATT" readings are mesh nodes and sensor payloads, which is correct. Worst-case strip (`PROWL SC` owner, PERMITTED, `999+ tgts`, 3 faults, 150 alerts, NET ON, BAT 100%, and SDR BLOCKED): strip minimum 1204–1215 px ≤ 1268/1280, no child past the right edge, in DARK/LIGHT/SUN, demo and live, on ASSISTANT/SYSTEM/OPS. The title elides to "PALISADE · ASSI…" in demo. **But the BAT slot freezes off OPS (F1).** The `TitleLabel.text()` override is Python-only (F12, Info). Nothing in QSS or the tests depends on it. `test_ui_polish:692` uses `text()` and passes. |
| 5 Run state | "Any start/stop button: red when stopped, green when on" | **Yes for BABEL**; one miss in scope | `set_run` and the QSS work. BABEL RUN is red, STOP is green, and `_untick_run` resets it to red. The disabled state is dashed. The miss in UI-thread scope is SYSTEM › BENCH "KEY CONDUCTED TX" / "STOP CONDUCTED TX" (`bench_app.py:120,237`), a start/stop toggle without `set_run` (F6). One-shot actions (RUN SELF-TEST, RUN HEALTH CHECK, FORGE AUTHORIZE/run cards, SITREP) are not toggles. Not in scope (not failed): PROWL SCAN/FM/NWR and PRISM (radio thread), RECON DEAUTH/PMKID/HANDSHAKE (RECON thread). In SUN, `live` and `alert` are both #000, so RUN and STOP differ only by the word. That follows SUN's "word + shape" rule (Info). |
| 6 Volume | "Volume slider far too small, barely any adjustability" | **Partly** | 40 px → 130 px, 20 px handle, step 2, page 10. Right-arrow from 0 to 100 takes 50 presses (100 before). **The disabled slider (no sink) is pixel-identical to the enabled one** in all 3 themes (0 of 1950 pixels differ), so the bigger slider looks live when it does nothing (F7). This was already true before the PR, but item 6 asked for it. |
| 26 No bottom bar | "remove the status bar at the bottom of all modules … A small message is OK somewhere, but not there" | **Partly** | No `page_status` row is visible on any page (all 9 pages + sub-tabs, rendered). OPS SDR presence reaches the strip (ABSENT/BLOCKED). A new warning becomes a notice inside the page area, never over the strip or the rail. A click on the page name lists everything. The notice never steals focus (focus is unchanged while a drawer is open). A page that is not on screen raises no notice, and its new warnings show when you open it. **But:** a warning with a counter makes it permanent (F2). It survives a page switch and covers the next page's controls (F3). A warning that clears and comes back never notifies again (F4). It draws above an open drawer (F8). There is no keyboard path to "what this page reports" (F9). |
| 8 Lifecycle / UI-only | — | **Yes** | `eventbus.bus.published → _on_bus` is disconnected in `closeEvent`. After close, a telemetry publish does not touch the BAT slot (PoC run). `status_shown` lambdas die with the pages, the notice timer is parented, and `_render_status` emit guards RuntimeError. UI-only: the OPS telemetry event is unchanged, `pwr` is dropped only from the page status dict, and BABEL changes are `set_run` only. No data, decode or radio behaviour changes. |
| 9 Tests | — | **No: one new red** | `test_shell_frame.py` 11/11 and `test_cl1_fix3.py` 17/17 pass. `test_ui_polish.py`: 104 passed. `test_cl1_screen.py`: 49 passed, 2 failed. One is the known flake `test_up_down_drive_the_list_and_the_detail_follows`, which passed when re-run alone. The other is **`test_eight_keys_in_order_with_function_labels`, which fails on this branch, passes on `fix/ui-polish`, and fails again when re-run alone (F0).** pyflakes is clean on all changed files. |

## Findings

### F0 — Medium (blocker: suite red) — the PR leaves `test_eight_keys_in_order_with_function_labels` red
`tests/test_cl1_screen.py:415-427` still pins the old order (`… "FORGE", "SYSTEM", "ASSISTANT",
"MESH"`) and the numbered title (`key.call.text() == "%d %s" % (i, name)`). This PR deliberately
changes both, but did not update the test. That breaks the DoD ("full suite green").
```
cd ra-s1 && QT_QPA_PLATFORM=offscreen xvfb-run -a python -m pytest -q \
  "tests/test_cl1_screen.py::test_eight_keys_in_order_with_function_labels"
# fix/shell-frame: 1 failed  (AssertionError at :415)   fix/ui-polish: 1 passed
```
Fix: update the test to the new contract (SYSTEM last, callsign-only title, "(key N)" in the tooltip).

### F1 — Medium — BAT slot and the strip's SDR presence freeze whenever OPS is not on screen
The strip's BAT slot (`shell._on_bus`) and SDR ABSENT/BLOCKED (`_page_status("OPS")`) are fed only by
OPS's worker. `LiveStatusWorker` / `DemoFeedWorker` inherit `Worker.PAUSE_WHEN_HIDDEN = True`, so on
every other page the worker is paused and nothing more is published. An operator who sits on PROWL
for an hour sees the last value from OPS. The ≤10 % red state can never fire there. An SDR unplugged
while on PRISM still reads FREE in the strip. Dalton asked for power in "a fixed, labelled slot", and
a slot that silently stops updating is worse than the old OPS-only chip, because the strip claims to
be live.
```python
# live hub, xvfb 1280x720
hub.open_callsign("OPS"); pump(4500)    # 3 telemetry events
hub.open_callsign("PRISM"); pump(6000)  # 0 telemetry events; hub.ops._worker.paused == True
```
Fix (UI-side): set `PAUSE_WHEN_HIDDEN = False` on the two OPS status workers (one sysfs read every
2 s), or have the shell own a small telemetry timer. Also add a regression test that changes page
and checks the BAT slot still updates.

### F2 — Medium — a warning with a counter makes the notice permanent (the bottom bar returns as an overlay)
`PageNotice.consider` dedupes on `(page, key, text)`. PROWL › NWR emits `"NWR — no audio reaching the
decoder (%ds)"`, state warn, every step (`prowl.py:743-748`, `interval_ms=400`). Each new second is a
new text, so the notice is re-shown and its 7 s timer restarted on every update. It never goes away
while the condition holds. It covers the bottom-right of the page, and `_seen` grows without bound.
```python
hub.open_callsign("PROWL", "NWR"); child = hub.pages["PROWL"].current_child()
for i in range(12):
    child.set_chip("sdr", "NWR — no audio reaching the decoder (%ds)" % (20+i), state="warn"); pump(1000)
# notice visible after every update: [True]*12; len(hub.notice._seen) == 13
```
Fix: dedupe on `(page, key, state)` (a key that stays in warn does not re-notify while its text
changes), or rate-limit per key. Add a regression test with a changing text.

### F3 — Medium — the notice follows the operator to another page, unlabelled, over that page's controls
`show_page` does not hide the notice, and the notice text carries no page name. Leave RECON › BLE
within 7 s of its "BLE STANDBY — no bleak and no bluetoothctl (sudo apt install bluez)" notice and
it sits over SYSTEM › BENCH's **KEY CONDUCTED TX** button. The notice is at (969,616,299,92) and the
button at (831,669,432,38). It reads as a BENCH problem. A click on it only dismisses it, so the
press meant for the button underneath is lost.
```python
hub.open_callsign("RECON", "BLE"); pump(1500)    # notice: 'BLE STANDBY — …'
hub.open_callsign("SYSTEM", "BENCH"); pump(500)
# notice still visible, same text, intersects page_app("SYSTEM").current_child().tx_btn
```
Fix: hide the notice in `show_page` (or prefix it with the page name). Consider moving it away from
the bottom-right action corner.

### F4 — Low — a warning that clears and comes back never notifies again
`_seen` is never pruned. Examples: SDR BLOCKED after a re-plug, a RADIO BUSY that recurs, a fault
that clears and returns. The warning is still listed when the page name is clicked, but it no longer
pushes a notice.
```python
a.set_chip("probe", "REMOTE-ID: SETUP NEEDED …", state="warn")  # notice shown
a.set_chip("probe", None); a.set_chip("probe", "REMOTE-ID: SETUP NEEDED …", state="warn")
# notice not shown
```
Fix: drop `(page, key, *)` from `_seen` when that key leaves the warn/alert state.

### F5 — Medium — SUN: no focus cue on the open sub-page tile; the nav-key focus cue is almost gone
`QWidget[nested="true"] QPushButton.subtab:focus { border: {focus_w} solid {focus} }` uses
`focus` (#000 in SUN) on `sub_on_bg` (#000), so the border is invisible. The rendered border/fill
contrast is 1.00:1, and the frame looks the same as unfocused. `navkey_on` correctly uses `focus_on`,
but the subtab rule does not. On closed nav keys in SUN, the focus cue is now +1 px of black under an
existing 2 px black tile border. Before, a black over/underline appeared on a borderless key. This
weakens the RA-CL1c F1 focus requirement in the theme meant for direct sun. DARK open sub: white on
#C9BCF2 is 1.76:1, weak but visible.
```python
# SUN, ATLAS › SKY DOME open; Tab focus to the SKY DOME sub tile
# sampled border #000000 on fill #000000 -> contrast 1.00 (no visible change vs unfocused)
```
Fix: add a `:checked:focus` rule using `focus_on`, and give the closed tiles a focus cue that
differs from their border (e.g. `focus_w` all round, or an inner contrasting line).

### F6 — Low — SYSTEM › BENCH conducted-TX start/stop is not on `set_run`
`bench_app.py:120/237` toggles "KEY CONDUCTED TX (confirm)" ↔ "STOP CONDUCTED TX" with no run
colour. This page is in UI-thread scope, and Dalton said "any start/stop button". (Green for a keyed
transmitter may be the wrong signal. Flag it for Dalton rather than apply blindly.)

### F7 — Low (pre-existing) — the disabled volume slider looks enabled
`QSlider#vol:disabled::handle:horizontal` never matches. With no sink, the slider is pixel-identical
to an enabled one in DARK/LIGHT/SUN (0 of 1950 pixels differ). Only the dotted mute key and the
tooltip say so. At 130 px the dead control is now prominent.
Fix: `QSlider#vol::handle:horizontal:disabled` / `::sub-page:horizontal:disabled` in the disabled
colour, and a regression test that compares the two renders.

### F8 — Low — the notice draws over an open overlay
With the ALERTS drawer open (140,100,1000,560), a new warning puts the notice at (969,592,299,116),
raised above the drawer's bottom-right corner, next to ACKNOWLEDGE ALL SEEN. Focus stays in the
drawer. Fix: don't raise the notice while an overlay is open, or place it below the overlays.

### F9 — Low — no keyboard path to "what this page reports"
The bottom bar was always visible. Its replacement opens only on a pointer click on the strip title
(a QLabel with no focus). It is not in the command palette, the key map, or any shortcut.
Fix: add a palette entry, e.g. "Page messages".

### F10 — Low — stale key-number docstrings and comments
`shell.py:1-6` ("eight page keys", "7 SYSTEM settings", old order), `shell.py:359` ("1-7"),
`ops.py:26` ("eight page keys … (1-8)"), `kit/topbar.py:1,143,240` ("numbered nav keys",
"'<n> CALLSIGN'", "1-7 shortcuts"), `recon.py:1` ("key 6", now 5), `sweep.py:1` ("key 5").
None of these are user-visible. They will mislead the next reader (RULE ZERO).

### F11 — Low — the two tile kinds are hard to tell apart when closed (DARK); ATLAS views stay flat
DARK closed page fill #3c3b51 and closed sub fill #424254 are nearly the same. Indent and size tell
them apart, colour does not. ATLAS's view buttons (`atlas.py:1017`, `class="subtab"`) are outside a
`nested` container, so they render as flat grey tiles next to purple ones. Whether views count as
"sub-modules" is Dalton's call.

### F12 — Info — `TitleLabel.text()` is a Python-only override
Qt's C++ side (accessibility, `QAccessible` name) sees the elided text ("PALISADE · ASSI…"). The
tooltip carries the full title. No QSS or test is affected.

### F13 — Info — page-name click on non-radio pages lists "SDR —"
`PalisadeApp._last_status` seeds an `sdr` chip on every page, so SYSTEM/ASSISTANT/MESH list "SDR —".
Chip tooltips (`tip`, sometimes the full text of a shortened fault) are no longer shown anywhere.
The old bottom bar showed them on hover.

## Commands run
- Tests (offscreen, `--timeout=240`): `test_shell_frame.py` 11 passed. `test_cl1_fix3.py` 17 passed.
  `test_ui_polish.py` 104 passed. `test_cl1_screen.py` 49 passed, 2 failed (F0, plus the known flake
  `test_up_down…`, which passes on a re-run). The full suite was not run (the thread runs it).
- `pyflakes` on all changed files: clean.
- Real-size renders and PoCs: Xvfb 1280x720x24 and 1920x1080x24, `shell.show_fitted`, all pages and
  sub-tabs in DARK demo, LIGHT live and SUN live, the overlays, the worst-case strip, focus samples,
  volume disabled/enabled diffs, and notice and telemetry PoCs (scripts in the auditor scratchpad;
  the snippets above reproduce each).
