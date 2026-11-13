# PALISADE — Final Build Plan

**The single source of truth for the overhaul.** Combines the Nov 12 design/branding/naming
plan (`DESIGN.md`, `BACKLOG.md`, `PROJECT_PROMPT.md`, the OPS concept) with the outside code
review (`CODE_REVIEW_HANDOFF.md`) and the per-module audit (`TRIAGE.md`). Where this doc and
an input disagree, **this doc wins**; the inputs remain as detail references.

Repo: `github.com/controllacorolla/SentryHub` · `main` is the source of truth · device app
path stays `~/.local/share/uconsole-suite/app` · screen **1280×480**, handheld, outdoors,
often one-handed.

---

## 0. The core idea (why this plan is shaped the way it is)

The design plan assumes "the architecture underneath is sound." The code review found it's
*mostly* sound but carries real defects — swallowed exceptions, unjoined threads, a web
dashboard XSS, global singletons. **Reskinning on top of those just repaints the bugs.** So
this plan interleaves two tracks that the separate docs kept apart:

- **Track A — Harden** (from the review): fix the security + lifecycle defects, add CI.
- **Track B — Overhaul** (from the design plan): UI kit → archetypes → 9 callsigns → brand.

They meet at one object: **the UI kit is also the lifecycle base class.** Build thread-join
on close, `after`-cancellation, the queue pump, and the `--demo` contract *into* the kit, so
every module migrated onto an archetype inherits both the PALISADE look and the correctness
fixes (R1/R3) at once. Likewise, **the per-module "use brief" is also the wire/merge/hide
decision** — one sweep answers UX and disposition together.

RULE ZERO (unchanged, from the build-prompt): **inspect, read, render, before you touch.**
Filenames mislead; the code is truth. Render real `--demo`/`xvfb` screenshots of any module
before redesigning it.

---

## 1. UI toolkit — DECIDED: PySide6 (Qt) + PyQtGraph

**Locked.** The UI layer moves from Tkinter to **PySide6 (Qt, LGPL) + PyQtGraph**. Full
rationale, options considered, and evidence in `DECISION-UI-TOOLKIT.md`. Short version: it's
the toolkit real-time SDR instruments are actually built in (native waterfall/spectrum via
PyQtGraph), it's far lighter than a browser, it runs well on the Pi 5-class CM5, and Qt
stylesheets (QSS) reach most of the concept's depth/chrome that Tk can't. Web/Chromium was
viable on the cooled build but carries a documented memory-leak/watchdog/reboot tax and a
battery hit; DearPyGui's GPU path is unreliable on Pi; Tk can't hit the look.

**Why this isn't a big-bang rewrite:** the Hub already launches most apps as **separate
subprocesses**, so a Qt app and a Tk app coexist as separate processes during migration.
Convert one app to Qt, the Hub launches it as a Qt process, the rest stay Tk until their turn.
That makes the UI-layer rewrite **incremental**, cluster by cluster.

Key implications (detail in the memo):
- **Engines stay.** Pure helpers, decoders, lease, `suite` — untouched. Only each app's
  presentation/interaction layer is reimplemented in Qt.
- **Embed pattern → Qt.** Mirror `theme.workspace_class()` with a base `QWidget` that runs
  standalone (own `QMainWindow`) and embeds in the Hub (stacked widget / tab).
- **Threading → Qt native, and it fixes R1/R3.** Replace the `queue`+`root.after` pattern with
  `QThread` + signals/slots; worker emits to the GUI thread, clean `quit()/wait()` on close.
  Bake this into the base widget so every migrated app gets correct thread lifecycle for free.
- **Theming → QSS.** DESIGN.md §4 depth tokens map to a QSS stylesheet; light/dark = two
  sheets. This is where the rounded float / soft shadows / tabular type the mock wants come from.
- **Viz → PyQtGraph.** PRISM (spectrum/waterfall via `ImageItem`), ATLAS map, the OPS PPI scope.
- **Tests → pytest-qt** for the UI smoke layer; pure-logic tests are unaffected (no Tk/Qt).

Still worth a cheap confirmation before committing hard: build **one live waterfall** in
PyQtGraph on the actual uConsole and watch RAM/CPU/temp for 30 min. Expected to pass easily on
the cooled 65 °C build; it just de-risks the viz path.

---

## 2. Track A — Harden (do alongside Phase 0–2; don't let Track B outrun it)

Full detail in `CODE_REVIEW_HANDOFF.md`. Priority order:

**A0 — Secure the in-flight work (first, today).** Commit the uncommitted bugfix batch (15
files + `tests/test_bughunt.py`) to `fix/bughunt` and push — it's unbacked-up. Reconcile
`ui/warm-collapsible-nav` (land `fix/bughunt` first, rebase the UI branch, keep the violet
bits for the real theme). Prune the two merged branches after approval.

**A1 — Security (P0).**
- **S1 — DOM-XSS in `headless.py`** (`.innerHTML` of feed fields; ADS-B callsigns are OTA
  attacker-controlled). Use `textContent`/`createElement`. **If the gate picks a web UI, this
  is the whole UI's input path — fix before building on it.**
- **S2** — headless server: default `127.0.0.1`, require a token, non-loopback needs an
  explicit flag + warning; `/api/contacts` leaks own GPS.
- **S3** — 8 `shell=True` call sites built from settings (`ais/aprs/nwr/pager/rds/specan/
  waterfall/canbus`): move to argv lists, validate `freq/gain/iface`.
- **S4** — `harden.sh --revert` fails open; restore default-deny instead.

**A2 — Lifecycle & reliability (P1), folded into the UI kit (§4).**
- **R1/R3** — 53 unjoined daemon threads + the hand-rolled queue/`after` pattern → bake
  `stop()/join()` on close and `after`-handle cancellation into the kit's base workspace.
- **R2** — ~150 swallowed exceptions (23 in `sky_app`) → route to one `SessionLog`.
- **R4** — `suite.py` module-global singletons (`_HOLDER`, `AUTOPILOT`, …) → wrap in a
  `SuiteContext` incrementally; stop adding module-level mutable state.

**A3 — Infra.** CI (`pyflakes` + headless `pytest` under `xvfb`) before heavy migration, so
every cluster PR is gated. Pin/lock Python deps. (The 5 `test_headless` failures are just
missing `flask` in a bare env — install it in CI rather than ignoring.)

**Detector check (resolves review C1):** confirm by reading that `jammer.py` and
`imsicatch.py` have **no TX path** — they're detectors, and that's the acceptance criterion
for keeping them. Everything that transmits stays behind `txguard` (ham/ISM/conducted, the
"TX SAFE" chip in the chrome), protected bands denied. No OTA attack/jam/deauth built or
extended.

---

## 3. Identity & scope (locked, from DESIGN.md)

- **Name: PALISADE** (data path stays `uconsole-suite`). Rebrand UI, splash, installer,
  desktop entries, `--doctor` — fixes the review's branding-sprawl item.
- **Accent** violet `#A492DA` dark / `#5A4790` light; green `#56D68E` = live/OK; graphite
  monochrome chrome; color carries state only. Dark **and** light both first-class.
- **Depth tokens** per DESIGN.md §4 (surfaces `--bg/--p1/--p2/--well`, hairlines, shadows,
  1px top highlight). Flat Tk is the problem; layered depth is the fix.
- **Type** JetBrains Mono, tabular numerals; hero numeral for the one number that matters;
  uppercase micro-labels; nav hierarchy flipped (group = main tier, modules = sub tier).
- **Chrome**: top bar = SDR / **TX SAFE** / GPS / PWR + volume + light-dark toggle + DTG
  clock. Bottom = ⌘K jump · esc home · ⌘W close.
- **Logo** (open, BACKLOG decision): finish mark #4, export **SVG** (recolors for light),
  bake into UI + boot splash.

---

## 4. Track B — The UI kit (build once, before any migration)

One reusable kit, which is also the lifecycle base class (Track A2):

Built in **Qt (PySide6)**. One reusable kit of `QWidget` components: status header · control
bar · feed table (`QTableView`/model) · detail card · map panel · spectrum/waterfall panel
(**PyQtGraph**) · empty/no-signal state. Plus the base workspace `QWidget`: standalone
(`QMainWindow`) **and** embeddable in the Hub (stacked widget/tab), a `QThread`+signals worker
contract with clean `quit()/wait()` on close (this *is* the R1/R3 fix), a `--demo` synthetic
feed hook, health-awareness via `suite.start_health`, and the QSS depth-token theme (light/dark).

**Acceptance for the kit:** a throwaway module built on it, in demo mode, renders the QSS depth
tokens correctly in both modes, survives open→close with no leaked `QThread` and no exception
(the R1/R3 test, via pytest-qt), and matches the OPS concept at 1280×480.

---

## 5. Track B — Archetypes (≈5, built from the kit)

Confirm membership by reading code, not filenames. From DESIGN.md §6 / build-prompt:

| Archetype | Shape | Modules (verify) |
|---|---|---|
| **Decoder feed** | table + detail + status rail | AIS, ACARS, VDL2, POCSAG, RDS, TPMS, CW, RTTY, digimodes, Zigbee, Z-Wave |
| **Map / geo** | map + contact list + telemetry | ADS-B/sky, APRS, dronewatch, DF/kraken, tacmap |
| **Spectrum / waterfall** | recessed scope well + controls | specan, waterfall, iqtool, classify, noisefloor |
| **Scanner / tuner** | channel list + tuner + squelch | scanner, fm, freqdb |
| **Device / IO console** | serial/console + controls | hwlab, buslab, canbus, proxmark, flipper, net/wifi tools |

Each archetype ships with a **use brief** template; each module declares its config and
inherits the real UI.

---

## 6. Track B — Consolidate 85 modules → 9 callsigns (the per-module sweep)

This is where the design plan's callsigns and the review's `TRIAGE.md` wire/merge/hide become
**one decision per module.** Target map (DESIGN.md §2):

| Callsign | Role | Absorbs |
|---|---|---|
| **OPS** | Situational home | the dashboard |
| **OVERWATCH** | Sky dome + autopilot radio director | overwatch |
| **ATLAS** | Live map | sky/ADS-B, AIS, APRS, dronewatch, DF/kraken, tacmap |
| **BABEL** | Universal decoder | ACARS, VDL2, POCSAG, RDS, TPMS, CW, RTTY, digimodes, Zigbee, Z-Wave |
| **PRISM** | Spectrum + waterfall + IQ + classifier + noise floor | specan, waterfall, iqtool, classify, noisefloor |
| **PROWL** | Scanner / tuner | scanner, fm, freqdb |
| **FORGE** | Hardware & IO bench | hwlab, buslab, canbus, proxmark, flipper |
| **RECON** | Network + RF survey (authorized) | wifisurvey, wifipent, netpent, blescan, blepent, passaudit, scout |
| **BENCH** | Conducted TX self-test / loopback (txguard-gated) | loopback, bench |

**The sweep — for each module, one pass answers four things:**
1. **Use brief** (what it's for, who/where in the field, the one glanceable thing, the actions).
2. **Disposition** (from `TRIAGE.md`): already-WIRED → migrate; **PLACARD** (engine done, UI
   not wired: `tpms`, `rollcode`, `classify`, `blescan`, …) → wire *as part of its callsign*;
   **LIBRARY** (`alerts`, `radio`, `skyintel`, `sstvdec`, … ~13) → never a tile, just an
   import; **hardware-gated** (`kraken`, `proxmark`, `zigbee`, `zwave`) → include behind a
   "hardware absent" state, not a dead tile.
3. **Merge target** = its callsign; confirm by import-graph + reading, never by name (the
   duplicate-`"pass"`-key bug is what name-based assumptions cause).
4. **Lifecycle** inherited from the kit (R1/R3) — no bespoke threading.

Reconciles two numbers: the design plan says "85 modules / 732 tests"; the review's AST audit
counted ~62 *app* modules (+~13 libraries + gated). **Trust the import graph, not either
count** — do the audit first, merge only real duplicates.

**Hard rule (both docs agree):** UI only. A module's data/decoding/radio behaviour must not
change while it's reskinned or merged.

---

## 7. Features & hardware (from BACKLOG, after the overhaul lands)

- 406 MHz COSPAS-SARSAT decoder (still a stub/TODO).
- Ham TX consumers (APRS beacon / SSTV) — needs your callsign; comes off `txguard`.
- `bench.py` GUI (engine + tests exist, no UI).
- Boot/splash using the "Wall" lockup.
- **Physical (on you):** 1090 antenna deaf + GPS no-fix (placement/sky view, then `ppm`);
  under-voltage on heavy SDR/LLM sessions (run plugged in); second-SDR choice (Airspy Mini
  vs 2nd RTL V4) — no buy yet.

---

## 8. Decisions that need you (not the agent)

1. **UI toolkit** — DECIDED: PySide6 + PyQtGraph (§1, `DECISION-UI-TOOLKIT.md`). No open question.
2. **Logo #4** → SVG export + lockup/favicon/app-icon.
3. **Second SDR** — Airspy Mini vs 2nd RTL V4 (decontention). No purchase yet.
4. **Ham callsign** — only if you want the legal APRS/SSTV TX features.
5. **jammer/imsicatch** — confirmed detectors; just verify no-TX-path in code (§2). No action
   needed unless the code says otherwise.

---

## 9. Execution order (the merged sequence)

1. **Phase 0** — A0 (secure the bugfix batch, reconcile branches) + A3 CI skeleton.
2. **Phase 1** — Confirm the viz path: one live PyQtGraph waterfall on-device, watch
   RAM/CPU/temp 30 min (expected to pass on the cooled build). In parallel: A1 security fixes
   (S1–S4). Stand up PySide6 + pyqtgraph in the dev env.
3. **Phase 2** — Build the **Qt UI kit = lifecycle base class** (§4 + A2). Nothing migrates
   until it exists and passes its open/close/no-leaked-QThread test (pytest-qt).
4. **Phase 3** — Build the ~5 archetypes (§5). Render one representative screen each, post to
   lock the look.
5. **Phase 4** — The per-module sweep (§6): one cluster per branch, one PR per cluster, suite
   green after each, every PR carries its **use brief + before/after screenshots**. Hide
   gated/unwired as you go; wire the placards into their callsigns.
6. **Phase 5** — Brand finish (logo SVG, splash, rebrand strings), then features (§7).

## 10. Definition of done (every migration PR)
On a branch (never `main`) · UI-only, no behaviour change · uses the kit (so lifecycle is
correct by construction) · use brief + before/after shots attached · `pyflakes` + full suite
green in CI (3.12, PySide6 + pyqtgraph + flask; Tk still present for not-yet-migrated apps) ·
a pytest-qt open/close smoke test for the screen · scoped to its cluster, no drive-by refactors.

## 11. Standing guardrails
Receive-first; TX only behind `txguard` (ham/ISM/conducted, protected bands denied; "TX SAFE"
chip, never an "RX-only" badge). `jammer`/`imsicatch` are detectors — keep, verify no TX. No
OTA attack/jam/deauth built or extended. No kernel-hold / firewall / SSH / sudoers changes; no
full-system apt upgrades. Data/config path stays `uconsole-suite`.

---
*Inputs folded into this plan: `DESIGN.md`, `BACKLOG.md`, `PROJECT_PROMPT.md`, the OPS
concept, `CODE_REVIEW_HANDOFF.md`, `TRIAGE.md`. Keep those for detail; drive from this.*
