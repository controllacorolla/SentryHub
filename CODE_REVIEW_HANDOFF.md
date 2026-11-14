# SentryHub — Code Review & Remediation Handoff

**Audience:** Claude Code (VS Code), working in the `SentryHub` repo.
**Author:** outside review pass, 2026-11-12. Findings are from reading the file map, git
state, docs, the installer/hardening scripts, `headless.py`, `plugins.py`, `suite.py`
globals, a sample of the SIGINT modules, and static scans. **Nothing was run on hardware**
— no claim below has been dynamically verified. Confirm before trusting.

This document is the single source of work. Read it top to bottom, then execute
**Workstream 0 first**, then P0 → P1 → P2. Pause for review after each numbered item that
changes behavior.

---

## 0. Operating constraints (read before touching anything)

- **You cannot run this suite or its UI tests on the dev Mac**: system Python is 3.10 with
  no `tkinter`; there is no 3.11+ and no venv. The suite needs **Python 3.11+ with tk**;
  UI/decoder tests need a display + `numpy`. Set up a venv (`brew install python-tk@3.12`
  or equiv) before claiming any test result. If you cannot, say so — do **not** report
  tests as passing that you did not run.
- **Do not commit to `main`.** Every change lands on a branch.
- **Do not delete git branches** (local or remote) without explicit approval.
- **Pure helpers are already well-tested.** The risk is in the UI/threading layer. Prefer
  surgical changes; preserve the existing architecture (embeddable `main()`, shared radio
  lease, graceful-degradation-on-missing-deps). Don't restructure working systems to taste.

### Current git state (verify with `git status` / `git branch -a` before acting)
- `main` is in sync with `origin/main`.
- **Uncommitted bugfix batch in the working tree:** 15 modified files + new
  `tests/test_bughunt.py` (11 regression tests). Not committed anywhere. **This is
  unbacked-up work — securing it is Workstream 0.**
- `origin/ui/warm-collapsible-nav`: **2 commits ahead of main, unmerged** (violet accent +
  hide idle power banner). Touches `theme.py`/`hub.py` — will conflict with the bugfix
  batch, which touches the same files.
- `origin/fix/loopback-and-sky` and `origin/sync-full-sigint-suite`: **already merged into
  main** (stale, deletable — with approval).

---

## Workstream 0 — Secure and sequence the in-flight work (do first)

**0.1 Back up the bugfix batch.**
- `git status` and confirm the working tree matches "15 modified + `tests/test_bughunt.py`".
- Build a venv (3.11+ w/ tk), run `pyflakes *.py` and `pytest -q tests`. Record real results.
- **Only if green:** `git switch -c fix/bughunt`, commit with a clear message, push.
  If you cannot build the env, commit to `fix/bughunt` anyway to preserve the work, and
  state clearly that it is unverified.

**0.2 Decide merge order with `ui/warm-collapsible-nav`.**
Both edit `theme.py` and `hub.py`. Recommend: land `fix/bughunt` first (it fixes a real
correctness bug — the duplicate `"pass"` dict key — and the UI branch should rebase onto
fixed code), then rebase `ui/warm-collapsible-nav` on top. Confirm with the user before
merging either.

**0.3 Stale branches.** Propose deleting `fix/loopback-and-sky` and
`sync-full-sigint-suite` (both merged). Do not delete without approval.

---

## P0 — Security (highest priority; these are real, not style)

### S1. DOM-XSS in the headless dashboard, with an over-the-air injection vector
**File:** `headless.py` → `dashboard_html()`
**Problem:** The contacts table is built client-side with `.innerHTML` + string
concatenation of `x.id`, `x.type`, `x.lat/lon`. Those fields originate from **attacker-
controllable RF**: ADS-B callsigns, APRS comments, Meshtastic node names — anyone nearby
can transmit a crafted value (e.g. a callsign containing an `onerror=` payload), which then
executes in the operator's browser. This is stored XSS in the one component designed to run
unattended.
**Fix:** Build the DOM with `document.createElement` + `textContent`; never interpolate feed
data into `innerHTML`. Escape anything that must be HTML.
**Acceptance:** A contact whose `id` is `<img src=x onerror=alert(1)>` renders as literal
text, not an element. Add a test feeding a malicious field through the provider and
asserting the served HTML/JSON escapes it.

### S2. Headless server has no auth, no TLS; binding is enforced only by a comment
**File:** `headless.py` → `make_app()` / server bootstrap
**Problem:** `/api/contacts` serves live lat/lon including the operator's own GPS fix. The
docstring says "bind to localhost/VPN" but nothing enforces it; one `host="0.0.0.0"` and a
box "left on site" broadcasts the operator's position unauthenticated over plain HTTP.
**Fix:** Default bind `127.0.0.1`. Require a bearer token (env/config) on `/api/*`. Any
non-loopback bind must require an explicit `--listen <addr>` flag **and** print a loud
warning. Consider gating `/api/contacts` position data behind a config flag.
**Acceptance:** Default run is loopback-only and token-protected; binding to a routable
address without the explicit flag refuses to start.

### S3. `shell=True` with config-interpolated command strings (8 call sites)
**Files / lines (verify):** `ais.py:304`, `aprs.py:691`, `canbus.py:287`, `nwr.py:171`,
`pager.py:168`, `rds.py:145`, `specan.py:230`, `waterfall.py:167`
**Problem:** Each builds a shell pipeline string from settings values (`s.get("freq")`,
`s.get("gain")`, `s.get("iface")`) and runs it with `shell=True`. Settings come from
hand-editable JSON (there's even `.corrupt` recovery for broken edits). A value like
`iface="can0; <cmd>"` is command injection into a process that drives the radio. Low
severity (own box, own settings) but it's a pattern you'd flag on a client, and
`canbus.py` already has `candump_argv()` proving the argv-list fix is known.
**Fix:** Build `argv` lists, `shell=False`, throughout. Validate/whitelist `freq`/`gain`
as numeric and `iface` against an allowlist.
**Acceptance:** No `shell=True` remains in these files; a setting with shell metacharacters
is rejected or passed inertly as a single argv element.

### S4. `harden.sh --revert` fails *open*
**File:** `harden.sh` (revert branch: `ufw --force reset; ufw disable`)
**Problem:** The undo of the safety tool leaves the device **wide open** (its own message
says so) — less safe than a sane default. For a field device the whole model is backwards:
it should fail closed by default and require a step to open up.
**Fix:** `--revert` should restore `default deny incoming` / `allow outgoing` (and keep SSH
from the current subnet so you don't lock yourself out), not strip the firewall. Long term,
consider a default-deny posture that `harden.sh` *relaxes* for the home subnet rather than
an opt-in that reverts to open.
**Acceptance:** After `--revert`, incoming is still default-deny; SSH from the local subnet
still works.

### S5. (minor) Root-path symlink to a user-writable target
**File:** installer (`install_tail.sh`) — `sudo ln -sf /usr/local/bin/<name> →
~/.local/bin/<name>`
**Problem:** Anything that can write `~/.local/bin/hub` controls what runs from a
root-owned path. Single-user box = low stakes; note it, fix if convenient (install the
launcher directly into `/usr/local/bin` as root-owned, or drop the system symlink).

---

## P1 — Reliability & correctness

### R1. 53 daemon threads with no clean shutdown → file corruption
**Scope:** systemic; `sky_app.py` spawns ~9, `scout` ~4, `suite`/`sstv`/`signals` ~3 each.
**Problem:** `daemon=True` threads are killed mid-execution at process exit. Fine for a
reader loop, **not** fine for threads writing `transcriber` status, the logbook, or any
`.json`. This is the class your bugfix batch keeps patching one instance at a time.
**Fix:** On workspace/Hub close, `join()` writer threads (with a timeout) before destroy.
Centralize: give worker threads a `stop()` + `join()` contract via the workspace base class
(see R3). Writers should use atomic write-then-rename (some already do) **and** be joined.
**Acceptance:** Closing an app mid-write never leaves a truncated status/log/json; a test
simulates close during a write.

### R2. ~150 swallowed exceptions (23 in `sky_app.py`, 15 `sitrep`, 10 `suite`, 8 `hub`)
**Problem:** Bare `except:` / `except Exception: pass` hides operational faults exactly in
the flagship app. `doctor` checks deps but runtime failures vanish.
**Fix:** Route caught exceptions to one visible session log (`suite.SessionLog`), even at
debug level. Reserve silent `pass` for cases that are genuinely expected (and comment why).
**Acceptance:** A forced failure in a worker leaves a log line; blanket silent passes are
reduced and the remaining ones are justified in a comment.

### R3. The Tk-threading pattern is hand-reimplemented ~90× → recurring races
**Problem:** The README rule ("never call Tk from worker threads; use a queue +
`root.after`; cancel timers on close") is a convention each `main()` re-implements. Your
batch just fixed three violations (GPS fix tearing, leaked clock timers, worker shutdown).
~87 more opportunities remain.
**Fix:** Factor the lifecycle into `theme.workspace_class()` or a `WorkspaceApp` base: the
queue pump, `after`-handle registry with cancel-on-close, and the worker `stop()/join()`
contract (R1). Migrate the deep apps first (`sky_app`, `fm`, `scout`, `hwlab`, `overwatch`).
**Acceptance:** New/migrated apps get lifecycle correctness for free; the three batch fixes
are expressible as "uses the base class."

### R4. `suite.py` module-level mutable singletons → apps aren't actually independent
**File:** `suite.py` — `_HOLDER=[None]` (~210), `_RADIO_WATCH=[]`, `AUTOPILOT={…}` (~212,
"set by Overwatch, read by the Hub"), `_LOCKS=[]` (~319), `_CHILDREN=[]` (~345),
`_HEALTH={…}` (~709).
**Problem:** The dongle lease is a hand-rolled process-global single slot; `AUTOPILOT` is
cross-module coupling via a shared dict. Consequences: can't run two Hubs in one process;
the "embeddable `main()`" independence is partly illusory; tests must monkeypatch globals.
**Fix (incremental, not a rewrite):** Wrap the lease + health + autopilot state in a single
`SuiteContext` object created once by the Hub and passed down (keep thin module-level
accessors for back-compat during migration). At minimum, document the shared-state contract
so it isn't expanded accidentally.
**Acceptance:** Shared state is reachable through one object; new code doesn't add
module-level mutable globals.

---

## P1 — Completeness & honesty (unwired tiles + redundancy inflate the grid)

### H1. A block of tiles are finished engines behind an unwired placard UI
**Corrected by AST audit — see `TRIAGE.md` for the per-module worklist.** An earlier draft
of this doc estimated ~40 unwired placards and only ~8 working apps; the audit of every
module's `main()`/`run_gui` corrects both:
- **~40 WIRED** working apps (`sky_app`, `ops`, `scout`, `hwlab`, `aprs`, `fm`, `scanner`,
  `overwatch`, `signals`, `devterm`, …). The working core is much larger than first stated.
- **~17 PLACARD** — engine present, often unit-tested, but `main()` renders only a static
  descriptive `Label`; the analysis functions are **never called from the UI**
  (`tpms`, `rollcode`, `classify`, `blescan`, `zigbee`, `imsicatch`, `jammer`, …).
- **~13 LIBRARY** — engines other apps import, never tiles (`alerts`, `radio`, `skyintel`,
  `sstvdec`, `fusion`, `evidence`, …). These should not appear on the Hub at all.

**Fix:** per-module **wire / merge / hide**, fully enumerated in `TRIAGE.md`. For the
placards the hard part (DSP/parsing) is already done and tested — wiring is binding engine →
widgets. Hardware-gated and legally-fraught tiles get **hidden**, not wired.
**Acceptance:** every visible tile either does something or is explicitly `experimental`;
`TRIAGE.md` stays in sync as modules are wired or hidden.

### H2. One `TODO/FIXME` in 33k lines — stubs are indistinguishable from finished code
**Problem:** Nothing marks what's incomplete, so H1's unwired apps look done. You can't
`grep` for unfinished work.
**Fix:** Add honest `# STUB:` / `# TODO(wire-ui):` markers to every module whose `main()`
doesn't call its own engine. Add a test or lint that lists them.
**Acceptance:** `grep -rn "STUB\|TODO(wire-ui)"` enumerates exactly the unwired modules.

### H3. Test coverage is concentrated where bugs aren't
**Problem:** ~110 test files, but they exercise the pure helpers (already safe). The Tk
integration, threading, and shutdown lifecycle — where every recent bug lived — are largely
untested (UI tests need a display).
**Fix:** Add headless smoke tests under `xvfb` that actually construct each app's `main()`
in demo mode, pump a few cycles, and close it, asserting no exception and clean thread exit.
Wire into CI (X1).
**Acceptance:** A CI job builds + tears down every app's UI in demo mode under xvfb.

### H4. `plugins.py` is built, tested, and unused — and the thing it replaces caused a bug
**Problem:** `plugins.py` exists to let modules register via manifest "without editing
hub.py", but `hub.py` still carries a hand-maintained `TILES`/`MAP`/`ICON` dict — and the
duplicate `"pass"` key bug lived in that dict. The abstraction earns nothing today.
**Fix (choose one):**
  1. **Adopt it** — generate the Hub tile/launch tables from manifests (`from_legacy` shims
     already exist), deleting the hand-maintained dicts.
  2. **Delete it** — remove `plugins.py` and its tests as dead weight.
**Acceptance:** No dormant abstraction — either the Hub is manifest-driven or `plugins.py`
is gone. (Keep the AST dict-key-uniqueness test from the batch regardless.)

---

## P2 — Hygiene, consistency, docs

### C1. "Receive-only" is false as written — resolve the lane
Docs say "receive-only, no transmit path except Meshtastic text," but the tree has
`jammer.py`, `imsicatch.py`, a TX suite, and `txguard`. Beyond tidiness: operating a jammer
or IMSI catcher is a US federal offense, so the framing that invites running them from a
tile is the risk. **Decide:** either it's an RX field instrument (remove/clearly quarantine
TX/jam/IMSI) or a full SIGINT kit (stop calling it receive-only). Make docs and tile
labels tell one consistent story.

### C2. Branding sprawl — pick one name
"Sentry" (installer, desktop entry), "uConsole Suite" (README title), bins `hub`/`sky`.
Choose one product name and make README, installer, desktop entries, and `--doctor` agree.

### C3. Stale docs
`README.md` title is outdated; it lists `aprs_app.py` (does not exist) and omits ~half the
modules. Regenerate the file map from the actual tree; fix the receive-only line (C1).

### C4. Dependency drift — pin and lock
`requirements.txt` is `>=` floors only; the installer runs `pip install --upgrade` on
`faster-whisper`/`skyfield`/`meshtastic`; `run_tests.sh` silently `pip install
--break-system-packages` pytest. Three places defaulting to "latest, unpinned, into the
live env." For a device you flash and leave: pin exact versions, add a lockfile, and make
the test runner not mutate the environment without consent.

### C5. Icon collisions
Reused glyphs across apps: `ᛒ` (BLE scan/assess), `⚡` (jammer/power), `⊕` (field
comp/tacmap/sdr++), `◉` (overwatch/tpms), `⌨` (devterm/usb-hid), `⬡` (zigbee/mesh). On a
5" screen icons are navigation — make each unique.

### C6. App-key naming is cryptic and collision-prone
`wifi`/`wifix`, `ble`/`blex`, `pass`/`pwaudit`, `tx`=transcriber. This is literally how the
duplicate-key bug happened. Namespace keys (e.g. `rf.*`, `net.*`, `kit.*`) and keep the AST
uniqueness test as the guard.

### C7. Hardcoded personal defaults
`sky_app.py` falls back to `KAPA` airport and `1750 m` altitude. Move to settings with a
first-run prompt; a silent personal default produces subtly wrong output for anyone else
(and for you when a fix is off by exactly your home elevation).

### C8. Hub surface is too dense for the screen
60+ tiles on a 5" display; `Ctrl+K` is the real navigation, so the grid is mostly
decoration. Pin ~8–10 core apps + search, categorize the rest, and hide the unwired ones
(H1). This and C1/H1 are the same cleanup from different angles.

### C9. Test names encode history, not coverage
`test_v44.py`, `test_bughunt.py`, `test_audit_*` — fold into per-module test files named by
what they cover.

### C10. `sky_app.py` is a 4,584-line monolith
Not urgent, but it's the one file where the next bug will be hardest to find. Split by
concern (feed/model, map/render, alerts, GPS, controller) the next time you're in it
heavily — not as a standalone refactor.

---

## X. Missing infrastructure

### X1. No CI
Add a GitHub Actions workflow on push/PR: `pyflakes *.py` + `pytest -q tests` for the
headless (pure-logic) subset, plus the xvfb UI-smoke job from H3. This is the thing that
catches the next duplicate-key / unwired-app regression before it reaches the device.

### X2. No release discipline
Installers went `v44`→`v54` then got gitignored; no tags, no CHANGELOG. For a tool you flash
to hardware, "which build is on the device" will matter — tag releases and keep a short
CHANGELOG.

---

## Suggested execution order

1. **Workstream 0** — back up the bugfix batch, decide merge order, (propose) prune stale
   branches.
2. **X1 (CI)** — so everything after is gated. Start with pyflakes + pure-logic pytest.
3. **P0 security** — S1, S2, S3, S4 (S5 if convenient).
4. **R1 + R3 together** — the workspace base class fixes the threading/shutdown class, not
   instances; R2 (logging) rides along.
5. **H1 triage** — produce the engine/UI/tests table; wire the demo-worthy apps, hide the
   rest (H2 markers as you go); then H3 UI-smoke tests; then decide H4.
6. **R4** — introduce `SuiteContext` incrementally.
7. **P2 hygiene** — C1/C8/H1 are one cleanup; then docs (C2/C3), deps (C4), the rest.

## Definition of done (per item)
Each numbered item is done when: the fix is on a branch (not `main`), `pyflakes` + `pytest`
are green **in a real 3.11+/tk venv or CI**, a regression test covers it where testable, and
the change is scoped to the item (no drive-by refactors). For P0, include the adversarial
test described under each item.

## Do not, without asking
- Commit to `main`, delete branches, or force-push.
- Claim tests pass that you didn't run in a tk-capable env.
- Rewrite working subsystems (lease, embed model, graceful-degradation) wholesale.
- Remove, enable, or change the gating on `jammer`/`imsicatch`/TX code — flag C1 for a human
  decision instead.
