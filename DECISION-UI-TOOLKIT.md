# Decision Record — UI toolkit

**Status: DECIDED (2026-11-13).** PALISADE's UI layer moves from Tkinter to
**PySide6 (Qt) + PyQtGraph.**

## Decision
- **Widget toolkit:** PySide6 (official Qt for Python, **LGPL** — safe for any distribution).
  Prefer it over PyQt6, which is GPL/commercial.
- **Real-time plotting:** PyQtGraph (spectrum, waterfall, PPI scope, live charts).
- **Theming:** Qt stylesheets (QSS) implementing the DESIGN.md §4 depth tokens; two sheets for
  light/dark.
- Not web, not DearPyGui, not staying on Tk.

## Options considered

| Option | Verdict | Why |
|---|---|---|
| **PySide6 + PyQtGraph** | **CHOSEN** | What real-time SDR instruments are actually built in; native waterfall/spectrum; light; runs on Pi 5-class CM5; QSS reaches most of the concept's chrome |
| Local web (Chromium) | Rejected | Viable on the cooled build, but documented Chromium-on-Pi memory-leak sawtooth needs a watchdog + scheduled reboots; battery hit; biggest rewrite; adds the `headless.py` XSS as the live UI surface |
| DearPyGui | Rejected | Its value is GPU accel — exactly what's historically unreliable on Pi (Pi 4 "not well tested", software-GL fallback "unusably slow", lagging wheels). Pi 5 maybe better but unproven |
| Stay on Tkinter | Rejected (as target) | Cheapest and keeps the 40 apps, but can't reach the concept's depth/soft-shadow/float chrome; weak native real-time viz |

## Evidence (from Nov 13 research)
- **Hardware is not the constraint.** CM5 = BCM2712 quad Cortex-A76 @ 2.4 GHz (Pi 5-class),
  and the user's custom build has a heatsink + fan running ~65 °C — well under the ~80–85 °C
  throttle. Thermal headroom is fine for any of these toolkits.
- **SDR-community standard is Qt + PyQtGraph.** The canonical PySDR reference builds its
  real-time spectrum analyzer with time/frequency/waterfall views and SDR controls in exactly
  this stack. PyQtGraph is purpose-built for the PRISM/ATLAS archetypes.
- **Chromium-on-Pi has a known operational tax:** memory grows until a watchdog restarts the
  browser; deployments use daily reboots and report tab crashes after 1–2 days. Fine for a
  wall dashboard, wrong for an unattended battery handheld.
- **DearPyGui on Pi:** GPU path flaky; without it, software rendering is unusably slow.

## Why this isn't a big-bang rewrite
The Hub **already launches most apps as separate subprocesses.** So Qt apps and Tk apps
coexist as separate processes during migration: convert one app to Qt, the Hub launches it as
a Qt process, the rest stay Tk until their turn. The UI-layer rewrite proceeds **cluster by
cluster**, suite green throughout — no flag day.

## Architecture implications
- **Engines untouched.** Pure helpers, decoders, the SDR lease, `suite` — all stay. Only each
  app's presentation/interaction layer is reimplemented in Qt. The ~13 library modules and the
  pure-logic tests don't move.
- **Embed pattern → Qt.** Replace `theme.workspace_class()` with a base `QWidget` that runs
  standalone (`QMainWindow`) and embeds in the Hub (stacked widget / tab).
- **Threading → Qt native, and it closes review items R1/R3.** Replace `queue` + `root.after`
  with `QThread` + signals/slots; the worker emits to the GUI thread and is `quit()/wait()`-ed
  on close. Bake into the base widget → every migrated app gets correct thread lifecycle for
  free (no more unjoined daemon threads).
- **Theming → QSS.** The depth tokens become a QSS stylesheet; this is where the rounded
  floating window, soft shadows, hairlines, and tabular type the mock wants actually come from.
- **Viz → PyQtGraph:** PRISM spectrum/waterfall (`ImageItem` + roll), ATLAS map, OPS PPI scope.
- **Tests → pytest-qt** for UI smoke (construct → pump → close, assert no leaked QThread);
  pure-logic tests unchanged.
- **`headless.py`** stays as the optional remote JSON API — fix its XSS (review S1) regardless,
  but it's no longer in the primary UI path.

## Cheap confirmation before committing hard
Build **one live waterfall** (an `rtl_power`/FFT feed) in PyQtGraph on the actual uConsole and
watch RAM/CPU/temp for 30 min. Expected to pass easily on the 65 °C cooled build; it only
de-risks the viz path before the kit is built.

## Open sub-questions (not blockers)
- PySide6 wheel availability for the target Python on the CM5 (3.12 recommended); confirm in the
  dev-env setup step.
- Map rendering in ATLAS: PyQtGraph `ImageItem` tiles vs a dedicated Qt map widget — decide
  during the ATLAS archetype, not now.
