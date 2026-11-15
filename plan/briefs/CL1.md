# CL1 — Screen fit, structure, keyboard, legibility

**Branch:** `fix/cl1-screen-structure` off `main` (after PR #18 merges; if not merged, branch off
`docs/audit-2026-11-15` and say so in the report).
**Findings:** D1 D2 D3 D4(status slots) D7 D8 D9 D10 · report §9 "Missing everywhere": radio
on/off + selection (RADIOS panel), audio control.
**Read first:** `plan/audit/AUDIT_INDEX.md`, the PDF §8 and §15.1 "Honest state and design",
`plan/briefs/README.md`, `CLAUDE.md`, then `palisade_qt/shell.py`, `theme.py`, `kit/topbar.py`,
and every page module. Render every page on `main` at **1280×720** before changing anything,
and keep those renders as the "before" set.

## Correction that reshapes this cluster

The panel is **1280×720**, not 480 (device diagnostic: CWU50 DSI, native 720×1280 rotated;
~294 ppi). So the 551 px shell fits, and D1 is High, not Critical. What remains true:
- BENCH's unwrapped REASON line widens the window to 1845 px (D1) — still a bug.
- At ~294 ppi, 10 px labels are ~0.86 mm and 13 px body ~1.1 mm (D2) — too small for status
  read at arm's length outdoors.
- A 136 px left rail plus a square scope on a 16:9 screen wastes width (D3) — still true,
  less severe.
- D7, D8, D9, D10 do not depend on resolution at all.
Design for 1280×720. Add the test that proves it.

## Structure — 8 keys (owner decision, recorded in AUDIT_INDEX.md)

Function label shown beside each callsign, always.

| key | callsign | label | content |
|---|---|---|---|
| 1 | OPS | home | as now |
| 2 | ATLAS | map | + sky dome and sat passes (from OVERWATCH) |
| 3 | PRISM | spectrum | as now |
| 4 | PROWL | listen | absorbs BABEL — scanner, FM, NWR, every decoder: one page, one job |
| 5 | **SWEEP** | counter-surveillance | promoted from RECON/COUNTER: bugsweep, jammer, imsicatch, gnss. The safety-critical use gets its own key. SENTINEL (parked) will live here. |
| 6 | RECON | survey + assess | WiFi / BLE / net only. ENGAGE moves to the top strip. |
| 7 | FORGE | hardware | as now |
| 8 | SYSTEM | settings | + BENCH, doctor, assistant, mesh, sitrep |

OVERWATCH retires as a page. Its radio-arbiter dashboard becomes the RADIOS panel (below). If
moving a sub-tab means moving a worker's owner, move it mechanically and say so in the report;
do **not** fix its behaviour here (CL4/CL5).

## Chrome (D1, D3, D4)

Delete the left rail and the footer. One top strip, ≤ 40 px at the new type scale, holding:

- Eight numbered nav keys, callsign + label.
- **Four fixed status slots**, each word + colour + shape, owned by the shell, never written
  by a page:
  - MODE — `LIVE` / `DEMO`. DEMO also draws a hatched border round the whole window.
  - RADIO — `FREE` / `HELD · <owner>` / `ACQUIRING`. Clicking opens the RADIOS panel.
  - TX — `OFF` / `PERMITTED` / `ARMED`. "TX SAFE" is retired; it meant two different things.
  - ENGAGEMENT — `NONE` / `ACTIVE · <scope>`. Global state belongs in chrome.
- **RADIOS panel**: every radio the arbiter knows plus rfkill/USB presence — power, present /
  absent, owner, device picker. In this cluster it *reads* and exposes what the arbiter already
  does; no new engine behaviour.
- Volume slider wired to the real audio sink, plus mute. It is currently connected to nothing.
- A reserved OPSEC shield slot (placeholder; PR #16 fills it later).

Pages get the rest. Sub-tabs vertical at the page's left edge. Where it fits, three columns:
list · scope · detail.

## Type and size (D2)

Nothing status-bearing under **16 px**. Body **18 px**. Table rows **40 px**. Set a device
scale factor appropriate to ~294 ppi and make it the default on the uConsole. Wrap every card
value. Delete every fixed minimum that assumes a desktop (sky dome 360×360, SSTV 240 px, etc.);
size from available space.

## Keyboard (D8)

Keys + trackball, no touchscreen. Visible focus ring and checked state on every control.
`1`–`8` pages · `←` `→` sub-tabs · `↑` `↓` lists, detail follows · `Enter` primary action ·
`Esc` back · `[` `]` step band in PRISM/PROWL · `+` `−` span · `Space` hold · `/` command
palette (callsigns, actions, a bare frequency) · `?` key map · one **PANIC** key (pick it,
document it): disarm TX, end engagement, kill child processes. Remove the two advertised but
unimplemented footer shortcuts. `QKeySequence("10")` parses to nothing — that bug goes away
with 8 keys, but add a test so it can't come back.

## Visual (D9, D10)

Green = receiving-and-healthy **only**. Armed / authorized / engagement-active = amber or red.
Strip green from "AUTHORIZED", "engagement active", "TX armed + unlocked". Every colour pairs
with a word and a shape. Add a **SUN** theme: black and white, nothing under 7:1, 2 px borders.
Alerts: a drawer with history and acknowledge, not a 3-item cap that vanishes. Collapse empty
detail cards instead of a 100 px dash.

## Scope rules

UI, layout, chrome, keyboard, theme. Do **not** touch engines, gates, workers' logic, the
arbiter's semantics, or any decode path. Those are CL2–CL5; mixing them makes the re-audit
impossible. Put drive-by discoveries in the report under "found, not fixed".

## Tests to add

- Every page instantiates and `minimumSizeHint()` fits **1280×720** with the top strip present.
- Keyboard-only walk reaches every page and every sub-tab (`1`–`8`, arrows, Enter, Esc).
- No status-bearing widget has a font under 16 px.
- Every page key parses to a non-empty `QKeySequence`.
- Suite green, pyflakes clean.

## Done means

`plan/briefs/CL1-report.md` on the branch, per `README.md` format. Before/after renders of every
page at exactly 1280×720 in dark / light / sun × live / demo. PR title `CL1: screen fit + 8-key
structure`. Then **stop** — the branch gets a cold re-audit (`plan/audit/REAUDIT_PROMPT.md`,
`<IDS>` = D1 D2 D3 D4 D7 D8 D9 D10) before CL2.

Commits end with:
```
Co-Authored-By: Claude Mythos 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4
```
