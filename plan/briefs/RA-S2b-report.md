# RA-S2b report: targeted cold re-audit of the RA-S2 fixes on `fix/ops-maps` (PR #34)

Auditor: a fresh Opus session, 2026-11-18. Audited `origin/fix/ops-maps` at `9d9d08f`.
Scope: `git diff 516a56c..origin/fix/ops-maps -- . ':!plan'` (7 files, +216/-26: `netpolicy.py`,
`kit/mappanel.py`, `kit/tiles.py`, `ops.py`, `overwatch.py`, `shell.py`, `tests/test_ops_maps.py`).

Method:
- Live and `--demo` hubs at 1280x720 (xcb/xvfb), HOME typed (39.6261, -104.968), in DARK, LIGHT and SUN.
  OPS and ATLAS were each rendered with FULL MAP off, on, and off again (side panels shown, hidden,
  shown). That is 36 renders, each with the strip's geometry checked against every visible widget
  over the map, not only `_overlay_rects()`.
- Nothing reached the internet. `PALISADE_NET=OFFLINE`, `urllib.request.urlopen` stubbed (DNS
  failure), tile `CACHE_ROOT` in scratch. The only real `urlopen` calls were loopback feed polls
  (127.0.0.1).
- The probes (`probe/render.py`, `probe2.py`, `probe3.py`), their outputs and the screenshots are in
  the session scratchpad under `ra-s2b/`.
- pyflakes is clean on all 7 files.

## Findings table

| ID | Verdict | Evidence |
|---|---|---|
| **N1** NEXT PASS | **fixed** | The RA-S2 PoC was re-run on a live hub: `pass_state` live, the alert's pass at AOS-1000 s, and OVERWATCH's list holding a later pass. Result: `'METEOR-M2 3 10:30Z'` (was `'none in 24 h'`). During a pass the card reads `'NOAA 15 NOW'`. With LOS 3 s ahead and only the 700 ms `_prune` timer running, it moved on to the next pass within 4 s. An empty list with status live gives `'none in 24 h'`, which is correct. `shell._next_pass` picks the earliest pass whose LOS is not past, falling back to AOS when LOS is missing. A residual edge is N9 (Low). |
| **N2** strip over the centre | **fixed** (placement) / **new N8** (put-away) | In all 36 renders the strip is one line, 282x34, plus the 140x34 button. It sits in the top band, right side (OPS y≈8 px into the plot; ATLAS just below the zoom/HOME row). `covers_centre` is false everywhere. There are 0 overlaps with any visible widget: FULL MAP / SHOW PANELS, DARK SAT, −/+/HOME, legend. `childAt(button centre)` is the QPushButton in every case, so the button can be reached. It is readable in all three themes. Tapping puts it away, and a changed state brings it back. But putting it away hides a new problem: see **N8**. |
| **N3** ATLAS banner height | **fixed** | The height is 34 px on both maps. A ring label no longer shows through the text. The opaque strip now hides the ATLAS "60" ring label: N11, cosmetic. |
| **N4** grant scoped | **fixed** (for the stated scope) | `GRANTABLE` = {a.basemaps.cartocdn.com, server.arcgisonline.com, basemap.nationalmap.gov, tiles.maps.eox.at}. `example.com`, `server.arcgisonline.com.evil.com`, `user@evil.com` and `server.arcgisonline.com.` are refused with NetBlocked, and nothing is sent. A tile host still goes out (the stub was reached). Mode is still OFFLINE afterwards. "From outside": `netpolicy.allow_grant()` is public and `GRANTABLE` is a plain module dict. `allow_grant(["example.com"], …)` from the probe made the next `granted=True` request go out. No lint test pins `allow_grant`/`granted=` to `kit/tiles.py`. This is in-process code only, so it is defence in depth: N10, Low. |
| **N5** redirect under grant | **not changed** (as declared) | `_NoCrossModeRedirect.redirect_request(… cdn.arcgisonline.com)` still raises `NetBlocked (redirect)`. |
| **N6** retry / raw error | **fixed** (retry, tooltip) / **partly** (duration) | Live: one tap with no route gives `failed`, `'NO IMAGERY · DOWNLOAD FAILED  ✕'`, and a visible, enabled RETRY. The raw `<urlopen error [Errno -3] …>` appears only in the tooltip. RETRY repeats the same one-shot logged grant (108 more attempts, all `granted` in the log, NET still OFFLINE). A partial failure shows `PART IMAGERY · SOME TILES FAILED` with RETRY. The RA-S2 third bullet is unchanged: 108 attempts at an 8 s timeout on a black-holed link can leave "DOWNLOADING…" up for minutes. |
| **N7** SKY DOME heading | **fixed** | The heading is "SKY OBJECTS · BELOW 0° = UNDER THE HORIZON" over Sun −43 and Moon −32, in DARK and SUN. It fits on one line. |
| L-a ATLAS download does not fill OPS | unchanged | No code change. Each map still needs its own tap. |
| L-b cache path | unchanged | `CACHE_ROOT = ~/.cache/palisade/tiles`. |
| L-c bare dashes | unchanged | "ADS-B NO FEED · DF — · BALLOONS —" appears in every live render. |
| L-d legend above HOME cover after F | unchanged | `ppi.py` is not in the diff. |
| L-e SUN key dots | unchanged | The SUN render still shows the sun and "satellite up now" dots both black. |
| UI-only / lifecycle | ok | The only non-UI change is the netpolicy grant restriction. Nothing new is threaded. The strip's event filter is on its own label. `OverwatchApp.passes` is a plain list set on the GUI thread (`_on_passes` slot). No decoder or radio change. |

Tests (one file per process, offscreen xvfb, `--timeout=240 --timeout-method=thread`):
`tests/test_ops_maps.py` 16 passed; `tests/test_cl8_ship.py` 153 passed.

## New findings

**N8 — Medium (honesty / usability, the default state): once the strip is put away, DOWNLOAD MAP is gone for the session, and a newly blank area says nothing.**
- Cause: `_dismissed` is cleared only when `(state, text)` changes. `imagery_state` text carries no area or count, so every OFFLINE build of any new view produces the identical `("offline", "NO SATELLITE IMAGERY — NET is OFFLINE…")`.
- Effect: after one tap on the ✕, moving HOME to an uncached area, or zooming to an uncached level, leaves the map black. There is no reason and no button. DOWNLOAD MAP is the owner's chosen answer to "There's no satellite map". It cannot be reached again until a restart, or until NET is turned on (which the owner wanted to avoid). This is the original "maps don't load, no word why" symptom, back for exactly the new area.
- PoC (`probe2.py`, live hub):
  1. ATLAS shows `offline` with the strip.
  2. `QTest.mouseClick(banner)` hides the strip and the button.
  3. `eventbus.set_home((47.6, -122.3), "settings")` gives `offline banner False btn False`.
  4. A zoom-in rebuild gives `offline banner False`.
  5. Screenshot: `shots/dismissed_new_home_atlas.png`, a black map with no strip.
- Fix (small): clear `_dismissed` when the view's area changes (in `set_home` on a rebuild, in `refresh` when the view differs from the one dismissed). Or put the strip away to a small "NO IMAGERY" chip that brings it back. Add a regression test: dismiss, `set_home` to a new area, and assert the strip and DOWNLOAD MAP show.

**N9 — Low: the old alert fallback can outlive OVERWATCH's own state.**
- What: `_pass_text` falls back to the bus-alert `_next_pass` whenever the list has no pass that is not over. That alert is dropped only at AOS+15 min.
- PoC (`probe3.py`): an alert for a pass at now+3000 s, then OVERWATCH goes to `no-home` with an empty list. OPS reads `'NOAA-19 10:51Z'` and not "HOME NOT SET", for up to an hour.
- A second case: with an empty list and the alert's pass over (AOS-600), the card shows that past time without "NOW".
- Fix: when OVERWATCH is reachable, trust its list and status only, and use the alert only when there is no OVERWATCH.

**N10 — Low (defence in depth, N4 residual): the grant allow-list is not closed, and a refused grant is not logged.**
- `allow_grant` is public. A refused `granted=True` request raises NetBlocked but appends nothing to `netpolicy.log()` and notifies nobody (probe: `new log entries []`). A blocked `check()` request is logged.
- Host matching ignores scheme and port, so `http://server.arcgisonline.com/…` and `:8443` are accepted.
- Fix: log or notify the refusal like a `blocked` request. Add a lint test that only `palisade_qt/kit/tiles.py` calls `allow_grant` or passes `granted=`. Optionally pin the scheme to https.

**N11 — Low (cosmetic): the strip has two small costs on the map.**
- On ATLAS it hides the "60" range-ring label in every theme (render `dark_live_ATLAS_fm0.png`).
- Any tap in its 34 px band dismisses it instead of reaching a contact under it. The band is at the top edge, 43 % of the plot height away from HOME.

## For Dalton (Low, unchanged or new)
- N5: a redirecting tile source still reads as "NET OFFLINE".
- N6 (duration): with no route, a download can sit on "DOWNLOADING…" for minutes.
- L-a: each map needs its own DOWNLOAD MAP tap.
- L-b: the tile cache is not under `uconsole-suite`.
- L-c: "DF —" and "BALLOONS —" are bare dashes.
- L-d: the legend rises above the HOME NOT SET cover after F.
- L-e: in SUN, the sun and satellite key dots are both black.
- N9, N10, N11 above.

## Verdict

**DO NOT MERGE.** One Medium blocks: **N8**. Putting the strip away makes DOWNLOAD MAP unreachable for the session and lets a newly blank area go silent. It is a few lines, plus a regression test.

N1, N2 (placement), N3, N4 and N7 are fixed, and N6 is fixed apart from the timeout duration. The rest is Low: Dalton's call, or a follow-up.
