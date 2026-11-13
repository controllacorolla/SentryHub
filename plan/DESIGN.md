# PALISADE — Design & Identity

Living design spec for the UI overhaul. Pairs with the project build-prompt.
Live concept artifact (home screen, dark + light, interactive): the "Sentry — UI
concept (tactical)" artifact. Render locally with Chrome headless (see bottom).

Status: concept locked for the **home / OPS** screen. Module archetypes next.

---

## 1. Identity

**Name — `PALISADE`** (locked). A defensive wall of vertical stakes / a picket line — the
barrier that stands watch. The vertical-stakes motif doubles as a signal spectrum, which
drives the mark.

**Logo** — the mark is a row of pointed stakes whose varying heights read as both a palisade
wall and an RF spectrum (center peak). Works filled (app-icon) and as a small top-bar glyph.
App-icon + in-app wordmark lockup to be finalized.

**Accent** — muted violet `#a492da` (dark) / `#5a4790` (light). Green `#56d68e` = live/OK
state. Everything else monochrome graphite. Color carries meaning, never decoration.

---

## 2. Naming system (consolidated apps)

85 modules collapse into ~9 named tools, each a consolidated super-module:

| Callsign | Role | Absorbs |
|---|---|---|
| **OPS** | Situational home / dashboard | the home screen |
| **OVERWATCH** | Sky dome + autopilot radio director | overwatch |
| **ATLAS** | Live map | ADS-B/sky, AIS, APRS, dronewatch (Remote ID), DF/kraken, tacmap |
| **BABEL** | Universal decoder | ACARS, VDL2, POCSAG, RDS, TPMS, CW, RTTY, digimodes, Zigbee, Z-Wave |
| **PRISM** | Spectrum + waterfall (CASCADE) + IQ + classifier + noise floor | specan, waterfall, iqtool, classify, noisefloor |
| **PROWL** | Scanner / tuner | scanner, fm, freqdb |
| **FORGE** | Hardware & IO bench | hwlab, buslab, canbus, proxmark, flipper |
| **RECON** | Network + RF site survey (authorized) | wifisurvey, wifipent, netpent, blescan, blepent, passaudit, scout |
| **BENCH** | Conducted TX self-test / loopback (txguard-gated) | loopback, bench |

Rule: a module only merges into a callsign if it genuinely shares that app's shape —
confirm by reading code, never by filename.

---

## 3. Design language

**Feel** — "an Apple application, the tactical version." Serious defense-software restraint
(Anduril/Lattice), not a dense Tk dashboard. Dominant focal zone + quiet telemetry rails.

**Typography** — monospace (`JetBrains Mono`), tabular numerals.
- Big numerals for the one number that matters (hero stat, ~54px/300).
- Uppercase micro-labels, 2–2.5px tracking, for section/telemetry labels.
- Nav hierarchy flipped: **group label = main tier** (larger, brighter); module items =
  sub tier (smaller, indented, uppercase). Active item keeps a 2px accent bar.
- Sentence case for body/values; UPPERCASE reserved for labels and the wordmark.

**Modes** — dark and light are both first-class and must be designed, not inverted. Light
needs genuinely dark features (hairlines, scope strokes, secondary text) — never washed out.

**Status honesty** — it transmits now (gated), so the chrome shows a **TX SAFE** state chip,
never an "RX-only" badge. Top bar carries SDR / TX / GPS / PWR, a volume control, and the
light/dark toggle; DTG clock far right.

---

## 4. Depth system (tokens)

Flat Tk is the problem; depth is the fix. Layered surfaces + soft shadows.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#070809` | `#e7eaee` | page / hero well (deepest) |
| `--p1` | `#0f1318` | `#f3f5f7` | elevated chrome rails (nav, telemetry, top, foot) |
| `--p2` | `#171c26` | `#ffffff` | raised cards (readouts, telemetry sections) |
| `--well` | `#050609` | `#dde1e6` | recessed scope well |
| `--line` / `--line2` | `#242b33` / `#323a44` | `#c3c9d1` / `#a6adb6` | hairlines |
| `--acc` / `--acc2` | `#a492da` / `#bcace8` | `#5a4790` / `#4a3a7e` | accent |
| `--live` | `#56d68e` | `#1f8f55` | live/OK state |
| `--warn` | `#e0ac48` | `#946713` | caution (power discharge) |

Shadows: `--shl` (window float), `--sh` (card), `--shin` (recessed well inset), `--hi`
(1px top inner highlight on every elevated surface). Window itself floats: `border-radius:14px`
+ ambient shadow.

**Layering:** chrome rails (`--p1`) sit above the hero well (`--bg`); the scope sinks into a
recessed `--well` with inset shadow; readouts + telemetry are raised `--p2` cards. Hero stays
the darkest "focal well" so the eye lands there first.

---

## 5. Layout (OPS / home)

```
┌ top bar ──────────────────────────────────────────────────────────┐
│ ◇ SENTRY   SDR IDLE · TX SAFE · GPS · PWR      [vol] [☀] 0547Z      │
├─────────┬──────────────────────────────────┬──────────────────────┤
│ NAV     │ HERO (focal well)                │ TELEMETRY (cards)     │
│ main    │  big stat + unit                 │  POWER                │
│  sub    │  ── recessed PPI scope ──        │  POSITION             │
│  sub    │  [readout] [readout] [readout]   │  NETWORK              │
│ main…   │                                  │  ACTIVITY             │
├─────────┴──────────────────────────────────┴──────────────────────┤
│ ⌘K jump · esc home · ⌘W close                                      │
└────────────────────────────────────────────────────────────────────┘
```

Hero = one dominant situational element (PPI scope for OPS), not a grid of equal tiles.
Telemetry rail = instrument readouts, never competing with the focal zone.

---

## 6. Archetypes & method (see build-prompt for full detail)

Build **one UI kit + ~5 archetypes**, then plug every app in. Don't hand-build bespoke screens.
1. **Decoder feed** (BABEL): table + detail + status rail
2. **Map / geo** (ATLAS)
3. **Spectrum / waterfall** (PRISM)
4. **Scanner / tuner** (PROWL)
5. **Device / IO console** (FORGE, RECON, BENCH)

Per-module **use brief** before any layout (what it's for, who uses it in the field, the one
glanceable thing, the few actions). Uniform chassis, considered content — reject "a table
because the archetype had a table."

Migrate one cluster per PR, suite green each step, before/after screenshots in the PR. UI only —
never change a module's data/decoding/radio behaviour while reskinning.

---

## 7. Rendering the concept locally

```bash
google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=2 --window-size=1360,560 \
  --screenshot=out.png file:///path/to/concept.html
```
uConsole screen is 1280×480. The concept HTML carries a working light/dark toggle and volume
control; swap `<body class="dark">`/`"light"` to screenshot each mode.
