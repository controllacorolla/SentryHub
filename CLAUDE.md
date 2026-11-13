# CLAUDE.md — PALISADE (SentryHub) working rules

You are working on **PALISADE** (repo name `SentryHub`, formerly "Sentry"): a Python/Tkinter
SDR + field-signals suite for a ClockworkPi uConsole (CM5, 1280×480 handheld). This file is
the contract. Read it first, every session.

## Read these before doing anything
1. **`PALISADE_BUILD_PLAN.md`** — the master plan. It drives. Everything else is detail.
2. `CODE_REVIEW_HANDOFF.md` — defects to fix (security/reliability/honesty), with file refs.
3. `TRIAGE.md` — per-module wire / merge / hide worklist.
4. `DESIGN.md` / `BACKLOG.md` / `PROJECT_PROMPT.md` + `concept/` + `renders/` — the design vision.

## RULE ZERO — inspect, read, render before you touch
Filenames mislead; the code is truth. Before any UI work: read `hub.py`, `theme.py`,
`suite.py` end to end, and **render real `--demo`/`xvfb` screenshots** of any module you'll
change. Design from what you see, not what a filename implies. (This is literally how a bug
got in — a name-based assumption created a duplicate dict key.)

## Hard constraints (do not violate without asking the human)
- **Never commit to `main`.** One cluster per branch, one PR per cluster.
- **UI-only changes must not alter a module's data/decoding/radio behaviour.**
- **Don't claim tests pass that you didn't run** in a real **Python 3.12 + tkinter** venv
  (the dev Mac's system Python has no tk). Tests: `xvfb-run -a python3.12 -m pytest -q tests`.
  Install `flask` in the env (the only `test_headless` failures are its absence).
- **Receive-first.** Any TX stays behind `txguard` (ham/ISM/conducted; protected bands
  denied; chrome shows "TX SAFE"). Do **not** route around txguard or add OTA
  attack/jam/deauth. `jammer.py` and `imsicatch.py` are **detectors** — keep them; if you
  touch them, confirm they have no TX path.
- **No system changes:** no kernel-hold / firewall / SSH / sudoers edits, no full-system apt
  upgrades. Data/config path stays `uconsole-suite`.
- Don't delete git branches or force-push without explicit approval.

## Sequence (from the build plan — don't skip ahead)
1. **A0 first:** there may be an **uncommitted local bugfix batch** (15 files +
   `tests/test_bughunt.py`) not yet pushed. Run `git status`. If present, commit to
   `fix/bughunt` and push before anything else — it's unbacked-up. Some `file:line` refs in
   the review assume it; if you cloned clean `main`, they may differ.
2. **Gate decision (Tk vs local web UI)** must be settled before archetype work — spike the
   OPS home both ways, measure on-device, decide on numbers.
3. **Security fixes** (S1–S4) — independent of the gate; S1 (headless XSS) first if web wins.
4. **Build the UI kit = lifecycle base class** (join threads on close, cancel `after`,
   `--demo` hook) before migrating anything.
5. **Archetypes → per-module sweep** (use brief + wire/merge/hide together), one cluster per PR.

## Per-PR definition of done
On a branch · UI-only · uses the kit (lifecycle correct by construction) · use brief +
before/after screenshots · `pyflakes` + full suite green in a tk venv/CI · open/close smoke
test · scoped to the cluster, no drive-by refactors.

## Decisions reserved for the human (flag, don't decide)
Tk vs web · logo/SVG · second SDR · ham callsign · whether `jammer`/`imsicatch` stay.
