# RA-S2c report: targeted cold re-audit of the RA-S2b fixes on `fix/ops-maps` (PR #34)

Auditor: a fresh Opus session, 2026-11-18. Audited `origin/fix/ops-maps` at `8e37b1d`.
Scope: `git diff 3516932..origin/fix/ops-maps -- . ':!plan'` (4 files, +83/-22: `netpolicy.py`,
`palisade_qt/kit/mappanel.py`, `palisade_qt/ops.py`, `tests/test_ops_maps.py`).

Method:
- Live hubs at 1280x720 (xcb/xvfb) with HOME typed (39.6261, -104.968), in DARK, LIGHT and SUN.
  OPS and ATLAS were each rendered unfolded and folded (12 renders). In DARK the RA-S2b N8 PoC was
  re-run on both maps: tap, move HOME to an uncached area (47.6, -122.3), zoom in and rebuild, tap
  again. Overlap with every visible widget over the plot was checked, and so was `childAt` on the
  chip.
- Nothing reached the internet. `PALISADE_NET=OFFLINE`, `urllib.request.urlopen` was stubbed (DNS
  failure), and the tile `CACHE_ROOT` was in scratch.
- The probes (`probe/p1.py` for renders, N8, N9 and N10 live, and `probe/p2.py` for netpolicy and the
  lint regex), their output and the screenshots are in the session scratchpad under `ra-s2c/`.
- pyflakes is clean on all 4 files.

Tests (one file per process, offscreen xvfb, `--timeout=240 --timeout-method=thread`):
`tests/test_ops_maps.py` 18 passed; `tests/test_cl8_ship.py` 153 passed.

## Findings table

| ID | Verdict | Evidence |
|---|---|---|
| **N8** strip put away for the session | **fixed** | A tap folds the strip to a 138x34 "NO IMAGERY ▸" chip and hides the button. Moving HOME to an uncached area and a zoom-in rebuild both leave the chip visible (`banner=True 'NO IMAGERY ▸'`) on OPS and on ATLAS. Tapping the chip brings back `'NO IMAGERY · NET OFFLINE  ✕'` with an enabled DOWNLOAD MAP. The chip overlaps no widget in DARK, LIGHT or SUN, and `childAt(chip centre)` is the QLabel. It is readable in all three themes (renders `*_folded*.png`). A change of state still unfolds it. The regression test covers fold, a new blank area, and unfold. A residual case, a fold during a download, is **N12** (Low). |
| **N9** old alert vs prediction state | **fixed** | Live, with OVERWATCH's `pass_state`: alert at now+3000 and state `live` with an empty list gives `'none in 24 h'`. HOME cleared after the alert (`no-home`) gives `'HOME NOT SET'`. `no-tle` with the alert gives `'NO TLE'`. With no OVERWATCH state, an alert pass that has started (AOS-300) gives `'NOAA-19 NOW'`. A list pass that has started gives `'NOAA 19 NOW'`. The alert fallback is now reached only before OVERWATCH's first prediction. The regression test covers `no-home` only. The "NOW" branch of the fallback has no test (Low, for Dalton). |
| **N10** refused grants / https / lint | **fixed** (logging, https) / **weak** (lint) | `http://server.arcgisonline.com/x` is refused with `grant refused: https only`. `https://evil.example/x` is refused with `not a grantable host`. Both append a `blocked` entry to `netpolicy.log()` and notify listeners. Nothing is sent. The port is not pinned: `https://server.arcgisonline.com:8443/x` is still sent under a grant. The lint test is easy to fool: see **N13** (Low). |
| N1 NEXT PASS | no regression | List-first logic is unchanged. Live: a started list pass gives "NOW", and an empty list with `live` gives "none in 24 h". `test_ra_s2_n1_*` passes. |
| N2 strip placement | no regression | Unfolded strip 282x34 plus button, and folded chip 138x34. Both are in the top band, right side (OPS y=119, ATLAS y=129 in window coordinates, under DARK SAT/zoom/HOME). There are 0 overlaps in 3 themes x 2 maps x 2 states. |
| N3 banner height | no regression | 34 px in every render. |
| N4 grant scope | no regression | `GRANTABLE` is unchanged, and a non-grantable host is still refused (now also logged). |
| N5 redirect under grant | unchanged (declared) | Not in this diff. |
| N6 retry | no regression | After a failed download the strip reads `'NO IMAGERY · DOWNLOAD FAILED  ✕'`, with RETRY visible and enabled. The duration residual is unchanged. |
| N7 SKY DOME heading | no regression | Not in this diff. `test_ra_s2_n7_*` passes. |
| UI-only / lifecycle | ok | The only non-UI change is the netpolicy refusal path (log + notify + https pin). Nothing new is threaded. No decoder or radio change. |

## New findings

**N12 — Low: folding and unfolding during a download re-arms DOWNLOAD MAP, and a second tap queues a second full granted download.**
- Cause: `dismiss()` now calls `_on_imagery(*self.imagery)`. That call always runs `download_btn.setEnabled(True)` and `setText("DOWNLOAD MAP")`, even while `tiles._busy` is set.
- PoC (`p1.py`, live ATLAS, DARK): DOWNLOAD MAP gives `'DOWNLOADING…' en=False`. Tap the strip twice (fold, then unfold) and it gives `'DOWNLOAD MAP' en=True busy True`. A second tap sets `_pending='satellite'` and `_grant_next=True`. Result: 216 tile requests (2x108) for one view, all logged as granted. While the first download runs, the map claims none is running.
- Fix: keep a `_downloading` flag in BaseMap, set in `download()` and cleared when the imagery signal returns. While it is set, `_on_imagery` keeps the button disabled and showing "DOWNLOADING…".

**N13 — Low (defence in depth, N10 residual): the grant lint test is easily fooled, and the port is not pinned.**
- The regex `granted\s*=\s*(True|getattr)|allow_grant\(` misses all 8 evasions tried (`p2.py`):
  - `granted=1`
  - `granted=ok`
  - a positional `urlopen(u, 10, "p", True)`
  - `**{"granted": True}`
  - a direct `netpolicy.GRANTABLE["evil.com"] = …`
  - `allow_grant (` with a space
  - `getattr(netpolicy, "allow_" + "grant")`
  - `from netpolicy import allow_grant as ag; ag(…)`
- The test drops directories whose absolute path contains "tests", "plan" or "venv" (a substring match). A checkout under, for example, `~/plans/SentryHub` would skip the whole tree and fail spuriously. It cannot pass spuriously.
- `https://grantable-host:8443/…` is still granted.
- A sturdier version would be an AST walk for any `urlopen` call with a 4th positional argument or a `granted` keyword, plus any reference to `allow_grant`/`GRANTABLE` outside the two files. Also make `granted` keyword-only and require the default port.
- Every bypass is in-process code, so this is Low.

**N14 — Low (pre-existing, undercuts N10): one DOWNLOAD MAP evicts most of the NET audit log.**
- `netpolicy._log` is a `deque(maxlen=200)`. One download of an ATLAS view writes 108 `granted` entries, and DOWNLOAD plus RETRY writes 216. Both evict every earlier entry, including the new "grant refused" ones.
- In the probe, a slice of the log taken after two downloads came back empty for this reason.
- Fix: log one entry per download (host and tile count), or raise the cap.

Out of scope (not in this diff, seen in the SUN renders): on ATLAS in SUN, the detail line under "NO LIVE LAYER" ("ADS-B NO FEED · DF — · BALLOONS —") is almost invisible, light grey on white (`sun_ATLAS_*.png`).

## For Dalton (Low)
- N12: fold/unfold during a download re-arms DOWNLOAD MAP (a double granted download is possible).
- N13: the grant lint is regex-shallow, and the port is not pinned.
- N14: the 200-entry NET log is flushed by a single download.
- N9: the "NOW" branch of the alert fallback has no regression test.
- Carried over from RA-S2b: N5 (a redirecting tile source reads as NET OFFLINE), N6 duration (minutes on "DOWNLOADING…" with no route), N11 (the strip hides the ATLAS "60" ring label, and a tap in its band does not reach a contact under it), L-a, L-b, L-c, L-d, L-e.
- The SUN ATLAS "NO LIVE LAYER" detail contrast (out of scope, above).

## Verdict

**MERGE.** N8, the only Medium, is fixed: a folded strip always stays as a visible "NO IMAGERY ▸"
chip, and one tap brings back DOWNLOAD MAP. This holds after a HOME move and after a zoom. N9 and
N10 are fixed as briefed. N1-N7 show no regression. The new findings (N12-N14) are all Low.
