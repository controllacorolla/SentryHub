# SentryHub — Wire / Merge / Hide Triage

**Companion to `CODE_REVIEW_HANDOFF.md` (item H1).** Per-module worklist driving the two
agreed workstreams: **wiring** (connect finished engines to their UI) and **consolidation**
(collapse overlapping tiles). Generated from an AST audit of every module's UI entry
(`main`/`run_gui`) — engine functions defined vs. actually called from the UI, widget count,
canvas/after/loop presence.

**Caveats:** heuristic classification. Anything marked `(verify)` had an ambiguous signal and
must be eyeballed before acting. Confirm nothing here on the dev Mac without a 3.11+/tk venv.
Line/behavior claims are static-only.

## Audit summary
- **~40 WIRED** working apps — keep (some are merge *targets*).
- **~17 PLACARD** — engine present and often unit-tested, but `main()` renders only a static
  description. → **wire** (if worth a tile) or **hide** (if hardware-gated / legally fraught).
- **~13 LIBRARY** modules — imported engines, never tiles. Leave as-is; don't list in the Hub.

Action legend: **KEEP** (wired, stays) · **WIRE** (engine done, build the UI) ·
**MERGE→x** (fold into x) · **HIDE** (behind an `experimental`/quarantine flag, not on the
default grid) · **LIB** (not a tile).

---

## A. Consolidation groups (do these as units, not module-by-module)

### 1. Spectrum / wideband → one **Spectrum** app (target: `rf_explorer`)
| module | LOC | state | action |
|---|---|---|---|
| `rf_explorer` | 560 | WIRED | **KEEP** — make it the Spectrum host (modes: waterfall / analyzer / noise) |
| `waterfall` | 234 | WIRED | **MERGE→rf_explorer** (waterfall mode) |
| `specan` | 298 | WIRED | **MERGE→rf_explorer** (analyzer mode) |
| `noisefloor` | — | LIB/thin | **MERGE→rf_explorer** (noise-floor readout) |

### 2. Assistant / brief → one **Assistant** (target: `assistant`)
| module | LOC | state | action |
|---|---|---|---|
| `assistant` | 672 | WIRED | **KEEP** — host (PTT + live context) |
| `copilot` | 174 | WIRED | **MERGE→assistant** (offline RF-analyst mode) |
| `sitrep` | 280 | WIRED (non-widget) | **MERGE→assistant** as the "brief" engine; keep `sitrep.brief()` callable |

### 3. Signal ID / triage → fold into `signals`
| module | LOC | state | action |
|---|---|---|---|
| `signals` | 635 | WIRED | **KEEP** — host |
| `classify` | 116 | PLACARD (real engine: modulation classifier) | **WIRE → as a `signals` panel** |
| `rffinger` | 84 | PLACARD | **MERGE→signals** (RF fingerprint panel) |

### 4. BLE → one **BLE** app (scan + gated assess)
| module | LOC | state | action |
|---|---|---|---|
| `blescan` | 96 | PLACARD | **WIRE** as the BLE host (passive scan) |
| `blepent` | 80 | PLACARD (verify) | **MERGE→blescan** as a gated "assess" tab |

### 5. Wi‑Fi → one **Wi‑Fi** app
| module | LOC | state | action |
|---|---|---|---|
| `wifisurvey` | 158 | WIRED | **KEEP** host (passive survey) |
| `wifipent` | 96 | PLACARD (verify) | **MERGE→wifisurvey** as a gated "assess" tab |

### 6. Maps → keep **air** vs **ground**, fold the placard
| module | LOC | state | action |
|---|---|---|---|
| `sky_app` | 4585 | WIRED | **KEEP** (air map; also split later — see handoff C10) |
| `overwatch` | 989 | WIRED | **KEEP** (sky dome / autopilot) — revisit whether it merges into sky_app |
| `fieldcomp` | 586 | WIRED | **KEEP** (ground/offline map) |
| `tacmap` | 105 | PLACARD | **MERGE→fieldcomp** (tactical overlay) |

### 7. Pass prediction → share one engine (keep the three apps)
`passsched` (KEEP), `wxsat` (KEEP), `sstv` (KEEP), `balloons` (KEEP) each predict passes.
**Dedupe the pass-prediction engine into one shared helper** (several already lean on
`skyfield`); don't merge the apps — they're distinct captures.

### 8. Digital-mode decoders → one **Decoders** launcher (keep each mode)
`ais`, `cw`, `rtty`, `rds`, `digimodes`, `pager`, `nwr` are all WIRED, real, distinct
decoders. Don't merge their logic — group them under one "Decoders" category/menu so they
stop eating seven top-level tiles.

### 9. Vehicle bus → pair under one **Bus** app
`canbus` (352, WIRED) + `buslab` (200, WIRED) → **one Bus app**, two tabs.

---

## B. Standalone WIRE candidates (engine done, worth their own tile)
| module | LOC | engine | action | note |
|---|---|---|---|---|
| `tpms` | 95 | real, tested (`Vehicles`, RSSI range) | **WIRE** | genuinely useful for phys-sec; small UI |
| `rollcode` | 108 | real, tested (bit-stability) | **WIRE** | analysis-only, no TX — safe |
| `bugsweep` | 93 | engine (verify) | **WIRE or HIDE** | TSCM sweep; decide if it's demo-worthy |
| `dxcluster` | 101 | engine | **WIRE or MERGE→scanner** | DX spots; low priority |

## C. HIDE behind `experimental`/hardware gate (don't wire yet)
Hardware you may not have, or niche — keep the engine, drop from the default grid:
| module | LOC | reason |
|---|---|---|
| `kraken` | 112 | needs KrakenSDR (DF array) |
| `proxmark` | 94 | needs Proxmark3 hardware |
| `zigbee` | 79 | needs CC2531/killerbee |
| `zwave` | 94 | needs Z‑Wave radio |
| `netpent` | 79 | **MERGE→scout** instead, or hide (overlaps scout's network assess) |

## D. QUARANTINE — human decision required (handoff C1), do **not** wire
| module | LOC | reason |
|---|---|---|
| `jammer` | 85 | operating a jammer is a US federal offense |
| `imsicatch` | 89 | cell-site simulation is a federal crime |
These contradict the "receive-only" framing. Leave the code, remove from the grid, and get a
human decision on whether they belong in the repo at all before touching them.

## E. LIBRARY modules — not tiles, leave alone
`alerts`, `radio`, `skyintel`, `sstvdec`, `geo`, `freqdb`, `astro`, `fusion`, `evidence`,
`engagement`, `txguard`, `powergov`, `opprofile`, `loopback`, `iqtool`, `gnss`, `mlat`,
`replay`, `bench`, `noisefloor`, `sky` (launcher shim). These are engines/helpers other apps
import or run shims. Confirm none is wrongly on the Hub grid; otherwise untouched.

**Confirmed by import-graph audit (2026-11-13):** `engagement` is currently exposed as a Hub
tile (key `eng`) but is imported by **12** modules — it is a shared evidence/logging library,
not an app. **Remove the `eng` tile from the grid** when the grid is rebuilt (the hide pass);
keep the module. Same check cleared the rest: `noisefloor` (imported by specan/waterfall/
jammer/bugsweep) folds into PRISM per §A1; `radio` (cw/rtty/replay/loopback), `skyintel` (6
aircraft apps), `txguard` (7), `geo`/`settings_ui`/`suite` are all true libraries, not tiles.

## F. Needs eyeball before action (`? review` in the audit)
Heuristic couldn't classify — open each `main()` and confirm wired vs placard:
`alerts`, `doctor`, `radio`, `skyintel`, `sstvdec`, `transcriber`, `blepent`, `netpent`,
`proxmark`, `wifipent`, `kraken`, `zigbee`. (Most are either library modules in §E or the
gated placards already in §C — verify, don't assume.)

---

## Recommended order
1. **Hide first (fast, high-impact):** §C + §D off the default grid, §E confirmed not-tiles.
   The Hub instantly stops overselling. One PR.
2. **Consolidate §A groups 1–3** (Spectrum, Assistant, Signals) — biggest tile reduction,
   all targets already WIRED.
3. **Wire §B** (`tpms`, `rollcode`) and §A groups 4–5 (BLE, Wi‑Fi) — real engines, small UIs.
4. **§A 6–9** (maps fold, pass-engine dedupe, decoder/bus grouping) — layout, low risk.
5. Only then revisit `sky_app` split and `overwatch`↔`sky_app` (handoff C10).

## Definition of done per tile
A tile is "finished" when its `main()` calls its own engine functions, has interactive
widgets (not a static Label), joins its worker threads on close (handoff R1), and has a
headless demo-mode smoke test (handoff H3). Hidden tiles carry a `# STUB:` marker (H2).
