# RA-S2 report: cold audit of Stage 2 (OPS, ATLAS, maps) on `fix/ops-maps`

Auditor: a fresh Opus session, 2026-11-18. Audited `origin/fix/ops-maps` at `bc16de9`.
Scope: `git diff origin/fix/shell-frame..origin/fix/ops-maps -- . ':!plan'` (11 files, +691/-25).
The bar is Dalton's notes from device run 2, not the plan's wording.

Method:
- Live hub and `--demo` hub, rendered with xcb/xvfb at 1280x720 in DARK, LIGHT and SUN: OPS, ATLAS MAP, DOWNLOAD MAP (tapping, then done), SKY DOME and PASSES. Also a live run with no HOME, and a live run with the F toggle.
- Nothing reached the internet. `PALISADE_NET=OFFLINE` was set, `urllib.request.urlopen` was stubbed with fake tiles or a DNS failure, and the tile `CACHE_ROOT` pointed at a scratch dir.
- The probe scripts and screenshots are in the session scratchpad: `ra-s2/probe/` and `ra-s2/shots/`.
- pyflakes is clean on every changed file.

## Item tables

### 1. Maps (plan 7): "There's no satellite map." / "Maps don't load."

| Check | Result | Evidence |
|---|---|---|
| Root cause addressed | yes | With NET OFFLINE (default) every tile was `NetBlocked` and swallowed. `_fetch_one` now counts `blocked`/`failed`, and `imagery_state` turns the counts into a reason. |
| Banner says why, live, all themes | yes | OPS and ATLAS both show "NO SATELLITE IMAGERY — NET is OFFLINE. Tap DOWNLOAD MAP…" with the button, in DARK, LIGHT and SUN. |
| DOWNLOAD MAP fetches once, NET unchanged, logged | yes | Probe: one tap gave 36 stubbed fetches, all to `server.arcgisonline.com`, with 36 `granted` log entries. Mode was still `OFFLINE` afterwards and the banner was gone (`ok`). The session log records "operator-granted … despite mode OFFLINE" (warn). |
| Grant is one-shot | yes (in TileLayer) | After the download, `refresh()` made 0 network calls and served every tile from the cache. `test_s2_7_a_granted_build_is_one_shot` passes. |
| Grant scoped to tiles; nobody else can ride it | **no** (netpolicy layer) | `netpolicy.urlopen(any_url, granted=True)` skips the mode check for any host and any caller. See N4. Today only `tiles.py` passes it. |
| Tiles cached, then load offline | yes | Same probe: a rebuild after the download read everything from disk. |
| Refetch on NET change | yes | `_on_net` refreshes BaseMaps whose state is `offline`/`partial`/`failed` (test passes). |
| Banner never lies | partly | No banner without HOME (the HOME cover shows instead: correct). No banner over a loaded map. Failures are honest: a DNS failure gives the "tile download failed: …" banner with no button. But: it cannot be dismissed and sits over the map centre (N2). It is oversized on ATLAS (N3). A granted fetch that is redirected is reported as "NET is OFFLINE, tap DOWNLOAD" again (N5). The error text is raw urllib (N6). |
| Placeholder / blank tiles | yes | Placeholders are dropped and not cached. A map made only of placeholders reads "no imagery for this area". |
| ATLAS and OPS both | yes, separately | Each map has its own banner and button. A download on ATLAS does not cover OPS's ±80 NM view, so OPS still shows its banner and needs a second tap (L-a). |
| Cache path `uconsole-suite` | unchanged by Stage 2 | `CACHE_ROOT = ~/.cache/palisade/tiles`, the same as on `main` before this PR. Not a Stage 2 regression (L-b). |
| Operator-initiated only | yes | `_grant_next` is set only by `BaseMap.download`, which runs only from the button's `clicked`. |

### 2. OPS (plan 8): "OPS does nothing."

| Check | Result | Evidence |
|---|---|---|
| Cards open their pages | yes | PRISM, DECODES → PROWL›DECODE, ALERTS → history drawer, NEXT PASS → ATLAS›PASSES, HOME → SYSTEM›SETTINGS, and the scope count → ATLAS. Each has a pointing-hand cursor and a tooltip (test passes). |
| Empty reason from ATLAS feed health, even with ATLAS hidden | yes | Live render: "no contacts · ADS-B NO FEED · DF — · BALLOONS —". No HOME: "no contacts · HOME NOT SET". ATLAS not started: "contact feeds not running (open ATLAS)". `feed_health` is computed on the hidden path. |
| Never "SDR —" or nothing | partly | It never says "SDR —". It does say "DF —" and "BALLOONS —": a bare dash Dalton has to decode (L-c). |
| NEXT PASS honest | **no** | NO TLE / HOME NOT SET / predicting… / demo are all correct. But "none in 24 h" is false for most of each hour after a pass (N1, Medium). |
| OVERWATCH started at launch, stopped on close | yes | Probe: after `start_background_feeds` the OverwatchApp is `_started` with 2 workers running. After `hub.close()` it is `_stopped`, has no workers, and only MainThread is left. |

### 3. Legend (plan 9): "OPS legend is way too big: space it out across the bottom of the map, keep it tight."

| Check | Result | Evidence |
|---|---|---|
| One tight row across the bottom | yes | `LegendRow` at 596x25 in a 612x612 scope (rail shown) and 584x25 in 600x600 (demo). Eight items, evenly spread, 8 px from the bottom edge, in all three themes. |
| 16 px floor | yes | Each item is `font-size: 16px`. (`make_legend`'s `14 if row else 16` branch is dead: `row=True` returns earlier.) |
| Fits at the real width | yes | The last item's right edge is 589, inside 596. Nothing is clipped in any theme. |
| Hidden behind the HOME cover | partly | Hidden at launch. After F toggles (resize), `place_legend()` → `raise_()` lifts it above the HOME NOT SET cover. `childAt(legend centre)` is the legend QLabel. This was already true before Stage 2 (the old resize also raised it), so it is not a regression (L-d). |
| No timers in the scope (CL8 B5) | yes | `ppi.py` adds none. It re-places synchronously after the re-fit. |

### 4. SKY DOME (plan 10): "Not sure what SKY DOME does or shows."

| Check | Result | Evidence |
|---|---|---|
| Title + help | yes | "SKY DOME · THE SKY ABOVE HOME, NOW" plus a plain paragraph: overhead is the centre, horizon on the outer ring, north up, and what to use it for. |
| Key | yes / partly | Sun, moon, satellite up now, pass track, rings. In SUN theme the sun and "satellite up now" dots are both black and cannot be told apart (L-e). |
| Next pass | yes | "Next pass: NOAA-19 (demo) at 08:40Z, up to 58° high, 137.1 MHz (demo)". Live without a TLE it reads "No pass tracks: NO TLE — update required". |
| Column headers | yes | OBJECT / ELEVATION ° / BEARING °. |
| Ring labels | yes | 0° (horizon), 30°, 60°, and 90° at the centre, drawn on the dome. |
| Honest heading | **no** | The table is now headed "ABOVE THE HORIZON" but lists Sun −59° and Moon −16° (both below the horizon) in every render (N7). |

Overall: a first-time viewer can read the page now. The heading in N7 contradicts the numbers under it.

### 5. Lifecycle / scope

| Check | Result |
|---|---|
| netpolicy listeners | 1 before close, 0 after (`_NetBridge.stop`). No new listener left behind. |
| OVERWATCH child | Stopped by the ATLAS composite's `stop()`. Workers are joined. |
| Tile worker threads | Daemon threads. An `imagery.emit` on a deleted layer is swallowed by `_work`'s `except`. |
| `_ClickFilter` | Parented to its card. `clear_body` schedules `singleShot(0, …)` without a liveness guard (harmless in practice). |
| UI-only | Yes, apart from the operator-granted tile fetch. No decoder, radio or arbiter change. |

### 6. Tests (one file per process, offscreen xvfb, `--timeout=240 --timeout-method=thread`)

| File | Result |
|---|---|
| tests/test_ops_maps.py | 12 passed |
| tests/test_ui_polish.py | 104 passed (6 pre-existing chrome.py disconnect RuntimeWarnings) |
| tests/test_cl8_ship.py | 153 passed |
| tests/test_cl1_screen.py | 51 passed |

## New findings

**N1 — Medium (honesty): after the announced pass ends, OPS NEXT PASS says "none in 24 h" while OVERWATCH holds future passes.**
- How it happens: OPS learns the next pass only from OVERWATCH's bus alert. OVERWATCH re-predicts hourly (`PassWorker.RE_PREDICT_S = 3600`) and only alerts from `_on_passes`. `OpsHome._refresh_ppi` drops `_next_pass` at AOS+15 min. `_pass_text()` then maps `pass_state == "live"` to "none in 24 h".
- Effect: with a pass 10 min after a prediction, OPS claims there is no pass in 24 h from about T+25 to T+60 min, every hour, while ATLAS›PASSES lists the next ones. This is the dishonest empty state item 8 asks about.
- PoC (probe2, live hub): `ops.pass_state = lambda: "live"`, then publish the OVERWATCH alert `sat="NOAA-19", aos=now-1000`, then `ops._refresh_ppi()`. Result: `mini_pass` reads `'none in 24 h'`.
- Fix: when the announced pass is over, take the next one from OVERWATCH's `_passes` through `passsched.next_pass`, or show "predicting…" until the next alert. Add a regression test.

**N2 — Medium (OPS/ATLAS usability, the default state): the imagery banner and button cannot be dismissed and cover the centre of the map.**
- What: NET OFFLINE is the default, and a field device often has no route. So a banner of about 560x80 px plus the DOWNLOAD button sits over the middle of the OPS scope and the ATLAS map, the area right around HOME.
- When it stays: indefinitely in every theme, and again after a failed download. The failed banner has no button and goes away only on a NET change.
- Effect: in the LIGHT demo render, contacts sit under it. The banner is a child QLabel of the PlotWidget, so it also eats clicks meant for the contacts it covers. Dalton's complaint was "OPS does nothing": a permanent box over the scope works against that fix.
- Fix: put it on the top or bottom edge, make it compact, or make it dismissible (tap to collapse to a small chip). Keep the reason text.

**N3 — Low: the ATLAS banner is about 2.5x too tall, and the ring labels show through its text.**
- Measured: ATLAS banner geometry is `(96, 84, 560, 203)`, and `heightForWidth(560)` returns 203 there. The same code on OPS gives a tight box of about 80 px.
- Effect: the range-ring labels "60/40/20" show through the translucent plate. "40" lands inside "NET is OFFLINE" in DARK, LIGHT and SUN.
- Fix: size from `fontMetrics().boundingRect(...)` plus padding, or use an opaque plate.

**N4 — Low (defence in depth): the `granted=True` grant is not scoped to a host or a caller.**
- PoC: `netpolicy.urlopen('https://example.com/anything', purpose='not a tile', granted=True)` goes out while the mode stays OFFLINE. It is logged as `('granted', 'example.com', 'not a tile')`, which the session log renders as "operator-granted".
- Coverage gap: `test_l3_no_module_opens_a_url_except_through_netpolicy` does not catch a new caller that passes `granted=True`.
- Today: only `tiles.py` passes it, and only after an operator's tap, so this is not exploitable now.
- Fix: limit `grant()` to the `TILE_SOURCES` hosts, or have it take a single-use token minted by the button. Add a lint test that only `palisade_qt/kit/tiles.py` passes `granted=`.

**N5 — Low: a redirect during a granted fetch is refused and reported as "NET is OFFLINE".**
- Why: `_NoCrossModeRedirect` calls `check(newurl)`, which blocks in OFFLINE. PoC: `redirect_request(… 'https://cdn.arcgisonline.com/x')` raises `NetBlocked … (redirect)`.
- Effect: that tile counts as `blocked`, so the banner asks for DOWNLOAD MAP again. Every tap would repeat this for a redirecting source.
- Fix: carry the grant through to same-purpose redirects (still logged), or count a redirect separately as `failed`.

**N6 — Low:**
- A failed download shows raw urllib text: "<urlopen error [Errno -3] Temporary failure in name resolution>".
- After a failure there is no retry button; the only retry path is a NET change.
- With no route, one tap made 108 attempts (36 tiles x 3 SAT sources). At the 8 s timeout on a black-holed link, the button could read "DOWNLOADING…" for minutes.

**N7 — Low (honesty, item 10):** the SKY DOME table heading "ABOVE THE HORIZON" lists the Sun and Moon at negative elevation. Either filter to el ≥ 0 or rename the heading (e.g. "SUN, MOON, SATELLITES · where they are now").

Lows outside Stage 2, or Dalton's call:
- **L-a**: DOWNLOAD MAP on ATLAS does not fill OPS's view. Each map needs its own tap.
- **L-b**: the tile cache is `~/.cache/palisade/tiles`, not `uconsole-suite`. It was like this before Stage 2.
- **L-c**: "DF —" and "BALLOONS —" in OPS's empty reason are bare dashes.
- **L-d**: the legend rises above the HOME NOT SET cover after an F toggle. This was already true before Stage 2.
- **L-e**: in SUN theme the sun and satellite key dots are both black.

## Verdict

**DO NOT MERGE.** Two Medium findings block:
- **N1**: OPS NEXT PASS says "none in 24 h" when passes exist.
- **N2**: the default-state banner cannot be dismissed and covers the centre of both maps.

Both are small, contained fixes, each with a regression test. Everything else in Stage 2 does answer Dalton's notes:
- The maps now say why they are blank, and one tap fetches and caches the area with NET left OFFLINE and logged.
- The OPS cards work and the empty reasons are real.
- The legend is one tight row.
- SKY DOME explains itself.

N3–N7 and L-a–L-e are Low: Dalton's call, or a follow-up.
