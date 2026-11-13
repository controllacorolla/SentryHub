# PALISADE — UI overhaul: project build-prompt

Drop this in as the project's instructions / kickoff. Pairs with DESIGN.md + BACKLOG.md.

```
PALISADE — module UI overhaul

REPO: github.com/controllacorolla/SentryHub
  - main = full suite, 85 modules, 732 tests green (source of truth)
PALISADE (formerly "Sentry") is a Python/Tkinter SDR + field-signals suite on a ClockworkPi
uConsole (CM5, screen 1280x480). It also ships as a self-contained bash installer; the live
app on the device is at ~/.local/share/uconsole-suite/app (data path name kept).

RULE ZERO — INSPECT, READ, AND LOOK BEFORE YOU TOUCH ANYTHING.
Filenames here mislead; the code is truth. Before any UI work:
  - git clone; read hub.py, theme.py, suite.py end to end.
  - RENDER real screenshots of every module you touch (demo under xvfb) and design from what
    you see, not what you assume.
  - Run the suite: xvfb-run -a python3.12 -m pytest -q tests (≈732 pass; 5 test_headless fails
    are just missing flask in a bare env — ignore).

THE PROBLEM
  85 modules, most with weak, inconsistent, "vibe-coded" UIs. Architecture underneath is sound
  (shared theme, workspace/embed pattern, SDR lease, txguard, tests); the sprawl is the UI layer.

THE GOAL (user's words): uniformity, detail, and real thought about how each module is actually
used and how a human interacts with it. Uniform chassis, considered content — never a uniform
template with no thought in it.

PER-MODULE UX PASS (required before any layout — this is the point, not decoration)
For each module write a short "use brief" and design to it:
  - What is this module FOR, in one sentence? What decision/task does it serve?
  - WHO uses it and WHERE: a handheld in the field — 1280x480, outdoors, sometimes one-handed,
    quick in-and-out, not a desk.
  - The ONE thing the operator must see at a glance (biggest, clearest element).
  - The 2-3 secondary things, on demand, not competing with the primary.
  - The actions taken here, in as few taps as possible.
  - What's live vs static reference; what the empty/no-signal state should say.
Every migrated module PR includes its use brief + before/after screenshots. Reject any screen
that's "just a table because the archetype had a table."

THE PLAN (do NOT hand-build 85 bespoke UIs)
1. Build ONE reusable UI kit (feed table, detail card, status header, control bar, map panel,
   spectrum/waterfall panel, empty-state).
2. From the kit define ~5 ARCHETYPES (confirm against real code):
   a. Decoder feed (BABEL): AIS, ACARS, VDL2, POCSAG, RDS, TPMS, CW, RTTY, digimodes, Zigbee, Z-Wave
   b. Map/geo (ATLAS): ADS-B/sky, APRS, dronewatch, DF/kraken, tacmap
   c. Spectrum/waterfall (PRISM): specan, waterfall, iqtool, classify, noisefloor
   d. Scanner/tuner (PROWL): scanner, fm, freqdb
   e. Device/IO console (FORGE/RECON/BENCH): hwlab, buslab, canbus, proxmark, flipper, net/wifi tools
3. Each module declares its config and inherits a real UI from its archetype.
4. MERGE where safe: thin modules within an archetype collapse into tabbed super-modules (the
   way sky.py hosts aircraft). 85 -> ~9 named callsigns (see DESIGN.md). Verify by reading, not name.

THEMING / COLOR
  Accent violet #A492DA (dark) / #5A4790 (light); green #56D68E = live/OK; near-black graphite base;
  chrome monochrome, color only for state/data. Dark AND light are both first-class and designed —
  light needs genuinely dark features, never washed out. Depth system (surfaces + soft shadows): see
  DESIGN.md §4. Render options and post them before shipping a palette.

METHOD — small, reviewable, reversible
  - One cluster per branch, one PR per cluster; full suite green after every change.
  - UI only — a module's data/decoding/radio behaviour must not change when reskinned.
  - Every migrated module PR: use brief + before/after screenshots.

CONVENTIONS (match existing code — read overwatch.py, devterm.py, sky_app.py)
  - Pure helpers (no Tk/IO), unit-testable; Tk workspace_class runs standalone via main() AND
    embedded in the hub.
  - Worker thread -> queue -> root.after. Never touch Tk from a worker thread.
  - Pack fixed/bottom bars BEFORE expanding content (known clip bug).
  - --demo mode with synthetic data per module. Health-aware via suite.start_health.
  - One shared RTL-SDR via the lease; never spin up two radios at once.

CONSTRAINTS
  - Receive-first; any TX stays behind txguard (ham/ISM/conducted only, protected bands denied).
    Do not route around it, do not add OTA attack/jam/deauth capability. jammer.py / imsicatch.py
    are DETECTORS (keep).
  - No kernel-hold / firewall / SSH / sudoers changes; no full-system apt upgrades.
  - Data/config path name stays `uconsole-suite`.

ENV / how to see the UI
  python3.12 + tkinter; tests via xvfb. Render a screen headless:
    xvfb-run -a -s "-screen 0 1280x480x24" bash -c \
      'python3.12 hub.py --demo --no-splash --no-ops & sleep 8; import -window root out.png; kill %1'

START HERE
  1. Clone, read hub/theme/suite, run tests.
  2. Render 4-5 representative module screens (one per archetype) and post them to lock the list.
  3. Propose the UI kit API + archetype list + theming, then build the kit before migrating.
  4. First open decision for the user: Tkinter vs a local fullscreen web UI (see BACKLOG.md).
```
