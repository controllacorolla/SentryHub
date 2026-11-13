# PALISADE — Backlog

Everything outstanding, pulled from the Nov 12 working session. Grouped by what needs
**you** (decisions/physical) vs. workstreams I can run. Pairs with `DESIGN.md`.

---

## 🔴 Decisions needed from you first (these unblock everything else)

1. **UI toolkit — Tk or web?** The concept fidelity (depth, type, the look you approved) is
   hard in raw Tkinter. Either (a) push Tk as far as it goes, or (b) move the UI to a local
   fullscreen web front-end on the uConsole (Python backend stays). This decides how all UI
   work below gets built. **Biggest fork — decide before archetype work starts.**
2. **Logo** — in progress (you're generating directions). Once picked: finalize lockup,
   favicon, app-icon, bake into UI + boot splash.
3. **Mark** — if not using a generated one, lock A·Spectrum / B·Rampart / C·Warded.
4. **Second SDR** — Airspy Mini (sensitivity) vs 2nd RTL-SDR Blog V4 (decontention). No buy yet.
5. **Ham TX callsign** — only if you want the legal APRS/SSTV TX features off `txguard`.

Locked: **name = PALISADE**, accent = violet `#A492DA` + green live, both light/dark modes.

---

## UI / Design (the main thrust)

- [x] Home / OPS concept — depth, flipped nav, TX-SAFE chip, light+dark (live artifact).
- [ ] Decide Tk vs web (see above), then apply the design to the real app.
- [ ] Build the **UI kit** (feed table, detail card, status header, control bar, map panel,
      spectrum/waterfall panel, empty-state) — once, shared.
- [ ] Build **~5 archetypes** from the kit: decoder-feed (BABEL), map (ATLAS),
      spectrum/waterfall (PRISM), scanner/tuner (PROWL), device/IO console (FORGE/RECON/BENCH).
- [ ] **Per-module UX pass** — a short "use brief" per app before layout (see DESIGN.md).
- [ ] Migrate modules onto archetypes, one cluster per PR, tests green, before/after shots.
- [ ] Boot/splash screen using the "Wall" lockup.

## Naming / consolidation

- [ ] Rename product Sentry → PALISADE across UI (keep `uconsole-suite` data path).
- [ ] Consolidate 85 modules → ~9 callsigns (OPS, OVERWATCH, ATLAS, BABEL, PRISM, PROWL,
      FORGE, RECON, BENCH). Do the **import-graph audit first** — merge only real duplicates,
      confirmed by reading code, never by filename.

## Features (verify what's built vs. pending)

- [x] dronewatch (BLE Remote ID), AIS, ACARS/VDL2 (signals), POCSAG/FLEX (pager) — landed in main.
- [ ] **406 MHz COSPAS-SARSAT** decoder — still missing (was stubbed/TODO).
- [ ] Ham TX consumers (APRS beacon / SSTV) — needs your callsign; comes off `txguard`.
- [ ] Bench tab GUI for `bench.py` (engine + tests exist; no UI yet).

## Repo / dev

- [x] Device v44 suite merged into `main` (85 modules, 732 tests green).
- [x] loopback hardware-gate test fixed (was hardware-dependent).
- [ ] Pull `main` to the Mac, set up VS Code (use `python3`, not `python`; deps already in 3.14).
- [ ] Reconcile branch `ui/warm-collapsible-nav` (warm→violet theme + collapsible Tk nav) —
      fold the keep-able Tk bits into the final design, or close it.
- [ ] Commit docs (`DESIGN.md`, `BACKLOG.md`, brand assets) so VS Code pulls them.

## Device / hardware (physical — on you)

- [ ] 1090 antenna is deaf + GPS no fix — placement + sky view, then `ppm` calibration.
- [ ] Under-voltage seen — run LLM / HackRF / long SDR sessions plugged in.
- [x] X display / `hub` launch error — fixed.

## Guardrails (standing)

- Receive-first; any TX stays behind `txguard` (ham/ISM/conducted only, protected bands denied).
- `jammer.py` and `imsicatch.py` are **detectors** (defensive), not weapons — keep.
- No over-the-air attack/jam/deauth tooling built or extended.
- No kernel-hold / firewall / SSH / sudoers changes; no full-system apt upgrades.
