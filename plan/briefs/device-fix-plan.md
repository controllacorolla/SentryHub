# Device fix plan — Dalton's device run 2 (demo/v0.1 on the uConsole, 2026-11-18)

Game plan posted to Dalton 2026-11-18 02:25Z, all 25 comments by module. Four stages, each a PR he
demos on demo/v0.1 before it merges; nothing merges to main until he says so. Source notes: the two
2026-11-18 batches in `device-notes.md` (section "Device run 2").

**How each stage closes:** fix, regression test per item, full suite once, backcheck against this
list and both notes with a coverage table, real-window run, cold audit, then his demo.

Status: open · in progress · done (PR). Keep this table current as items close.

## Stage 1: Frame and shell (goes first) — owner: UI thread

| # | Item | Status | PR |
|---|---|---|---|
| 1 | Window locks to 1280x720 maximized. Full-map toggle and every panel collapse never resize or push the window off-screen. Verified on a real window, not a render. | in progress | — |
| 2 | Left rail: numbers removed, items spaced evenly down the full height, ending just above the bottom edge. System settings last. | in progress | — |
| 3 | Tiles everywhere: purple for modules, light purple for sub-modules, same tile component across all pages. | in progress | — |
| 4 | Status strip: "0221Z" gets a UTC label or goes. Power % moves to a fixed, labelled slot. The icon beside CONTACTS LIVE and the item left of it get names or tooltips. | in progress | — |
| 5 | Every start/stop/scan button app-wide: green while running, red when stopped. One shared control (`kit.components.set_run`) so it can't drift per page. | in progress | — |
| 6 | Volume slider: full-length with real travel. | in progress | — |
| 26 | Remove the bottom status bar from every module (the line with "SDR present", a second power icon). The top strip carries status; anything that only lived in the bottom bar (SDR presence, power) is shown once in the strip, labelled. A transient message, if needed, goes somewhere unobtrusive, not a permanent bar. (Dalton 02:38Z) | in progress | — |

## Stage 2: OPS, ATLAS and maps — owner: UI thread

| # | Item | Status | PR |
|---|---|---|---|
| 7 | Maps load on the device. Root-cause first (tile source vs network vs cache path), then satellite tiles actually appear offline and online. | open (cause found: NET defaults OFFLINE, tile fetches are refused silently) | — |
| 8 | OPS: wire it to real contacts (readsb, gpsd, Wi-Fi/BLE sightings) so it shows something, with an honest reason when empty. | open | — |
| 9 | OPS legend: one tight row spread across the bottom of the map. | open | — |
| 10 | SKY DOME: title, legend and what's plotted so it explains itself. | open | — |

## Stage 3: RECON — owner: RECON thread

| # | Item | Status | PR |
|---|---|---|---|
| 11 | Right panel: readable font at 720p, collapsible. | open | — |
| 12 | Wi-Fi: click a network, get an action menu for it (details, nmap on it if in scope, capture/handshake, deauth greyed with the reason until the adapter arrives). | open | — |
| 13 | Full RECON layout pass to the tile standard; Bluetooth stays as is. | open | — |

## Stage 4: Radio — owner: Radio thread

| # | Item | Status | PR |
|---|---|---|---|
| 14 | PRISM gets the SDR++ set: click/drag VFO, direct frequency entry, AM/NFM/WFM/USB/LSB/CW with audio, bandwidth, squelch, gain/AGC, zoom, bookmarks, recording. | open | — |
| 15 | PROWL scanner: preset banks (airband first), dwell/hold, resume delay, step, lockouts, priority channel, per-bank squelch, range scan. SCAN button green/red. | open | — |

## Needs Dalton before they're built

| # | Item | Status |
|---|---|---|
| 16 | RF module is empty: what RF should show versus PRISM/PROWL. | waiting on Dalton |
| 17 | ASSISTANT has no model: Opus (cloud) or a local model for offline field use. | waiting on Dalton |
| 18 | MESH: UI thread proposes a real layout for his yes/no. | proposal being drafted |
