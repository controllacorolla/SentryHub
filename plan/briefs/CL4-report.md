# CL4 — honest state: report

Branch `fix/cl4-honest-state`, off main `04a76ab` (CL3 + CL5 in). Scope per `PLANNER-HANDOFF.md`:
H1–H19, E1, E4, D4 (empty state), L5, plus the CL3 follow-ups N20 (Med), N21–N25, N11, N12, N13,
N15 and R1. H9 was closed by CL3.

Rule for every screen: if a value is not backed by real data right now, the screen says what it
lacks (OFFLINE / NOT IMPLEMENTED / STALE / HOME NOT SET) instead of showing a number, a green
chip or a blank table.

## Gate and evidence (carried from CL3) — `tests/test_cl4_gates.py` (32 tests)

| ID | Fix | Where |
|---|---|---|
| N20 Med | END's orphan kill and the executor's `_kill_group` now check the whole process group, not just the leader: `gatestate.group_members/group_alive` (killpg(pg,0) probe + /proc scan, zombies excluded). TERM → wait → KILL the leader if it still matches, KILL the group if members survive. A member that survives SIGKILL records **UNCONFIRMED** with `group_survivor`, never KILLED. | `gatestate.py`, `engagement.py::_kill_orphans`, `executor.py::_kill_group`, `Handle.stop` |
| N21 | A kill is recorded only if the handle is not already stopped or exited (under `_rec_lock`); an exit with a negative code after KILLED keeps KILLED in the fold. | `executor.py`, `chain.states()` |
| N22 | Zombie orphans get their own reason ("already exited (zombie, not yet reaped)") instead of "pid does not match". | `engagement._identity`, `_UNSEEN_REASON` |
| N23 | `_identity` refuses the hub's own pid, parent and process group. | `engagement._identity` |
| N24 | END kills orphans as one batch: TERM all, one wait, then KILL. 4 SIGTERM-ignoring orphans finish in ≈1 grace + 1 kill wait instead of ≈1 s each. A kill that raises still closes the engagement and records UNCONFIRMED. | `engagement._kill_orphans` |
| N25 | macOS: `kinfo_proc` parsed once for start time and `p_stat` (SZOMB=5) → `is_zombie` works on darwin. Verified with a fabricated kinfo buffer only (no Mac here). | `gatestate._darwin_parse` |
| N12 | Malformed head files and non-dict JSONL lines raise `ChainError` (fail closed); `_active_chain` catches any exception, so a corrupt chain blocks actions instead of crashing the GUI. | `chain.py`, `engagement._active_chain` |
| N13 | (a) a directory-fsync failure after the head rename no longer rolls back a committed record; (b) crash between the JSONL append and the head rename (head one behind, last line's prev hash matches) is recovered under an exclusive lock: the head rolls forward and a `recovered` record is appended. Two unaccounted lines are still refused. | `chain._read_verify`, `_append_locked` |
| N15 | The fold keys by the authorization's chain `seq` (`auth_seq` carried from `issue()` into the executor's records), so two actions with the same label and target no longer merge. Falls back to (label, target) for old records. | `engagement._authorize`, `executor`, `chain.states()` |
| R1 | Partly: a per-process high-water mark refuses a chain that goes backwards while the hub is running ("rolled back"). A snapshot restored while the hub is **not** running still verifies — that needs an external anchor (a key-held counter outside the chain dir) and is documented as the limit in `chain.py`'s docstring. | `chain._HIGH_WATER` |
| N11 | ENGAGEMENT trail uses `fit_viewport`: no sideways scroll; long values elide with a tooltip. | `panels.EngagePanel` |

## Honest state — `tests/test_cl4_honest.py` (58 tests)

| ID | Before | After |
|---|---|---|
| H1 | SWEEP showed an empty findings table while all four detectors were offline; their standby went to one shared chip. | One fixed row per detector: OFFLINE (with reason) / LEARNING / WATCHING / STALE, sample count and last-sample age. Per-detector state rides the row signal, not the shared chip. Live detectors say **NOT IMPLEMENTED — no live feed is wired (needs …)** and stop polling. Findings table shows the OFFLINE empty state: "Nothing is being watched, so no findings does not mean all clear." |
| H2 | PRISM green whenever the lease was held. | LIVE only if a sweep arrived in the last 5 s; STARTING before the first; STALE after; a dead rtl_power is **SDR FAULT** with its stderr tail and retries after 5 s. |
| H3 | A failed `iw scan` read as "0 AP"; the scan was active and ran every 4 s for the whole session. | Exit code checked (**WIFI SCAN FAILED — exit N — stderr**); `iw dev X scan passive`; 15 s interval; paused unless RECON › WIFI is on screen. Open-network alerts fire once per BSSID instead of every scan. |
| H4 | Arbiter granted the radio when the real lease failed. | `_make_lease` raises `LeaseFailed` (after releasing what it paused); the arbiter returns to FREE, emits `failed`, and backs off 20 s. Pages say **RADIO FAILED — why (retry in Ns)**. No suite module (dev host) still grants. |
| H5 | HOME defaulted to Seattle (47.6, −122.3) silently. | HOME is unset unless saved in SETTINGS (demo uses the demo home, flagged). OPS/ATLAS show **HOME NOT SET**, no range/bearing; OVERWATCH predicts no passes. SETTINGS writes HOME live through `eventbus.set_home` (consumers re-centre / re-predict on `home_changed`) and never persists the demo home. GPS as a source is CL6. |
| H6 | `/dev/swradio0` counted as "SDR OK" — it appears exactly when the DVB driver has the dongle. | `radios.sdr_state` reads the USB ID and bound interface driver: **SDR BLOCKED — dvb_usb_rtl28xxu bound** / ABSENT / PRESENT / HELD · owner / `SDR ?` when there is no sysfs. |
| H7 | Workers defaulted to demo; demo events looked live on the bus. | Worker defaults are live; every event carries a `demo` flag; demo publishes set it. |
| H8 | BENCH said KEYED on spawn. | STARTING until the runner has stayed up 1 s, then KEYED; a runner that exits first is **FAILED TO KEY** with its exit code. The power spinbox *is* read (it is the power txguard authorizes and derives the gain from) — kept. |
| H10 | ATLAS: one total ("1 CONTACTS") hid a dead ADS-B feed. | Per-layer status: AIRCRAFT n / **ADS-B STALE Ns** / **ADS-B NO FEED**, and so on per layer. |
| H11 | PROWL showed dBm nothing measured. | A unitless audio LEVEL % for the tuned channel only; other rows blank; detail says "not measured". |
| H12 | Peak hold multiplied negative dB by 0.97, so it **rose** to ≈0 dB. | Decays 0.5 dB per sweep toward the live trace. |
| H13 | "dBm" on an uncalibrated rtl_power readout. | "dB rel" / "PEAK · dB (relative)". |
| H14 | Decode rate = min(60, n·6): one decode ever read "6/min". | Real count of decodes in the last 60 s. |
| H15 | OPS counted "military" on live contacts (no live source sets it). | Shown only in demo, labelled "(demo)". |
| H16 | Only TPMS and SSTV reached the bus. | AIS, ACARS, POCSAG and RDS runners publish every real decode. |
| H17 | One 1000-event log; 30 aircraft evicted an alert in ≈3 s; SITREP said "All quiet" with no feed and SPEAK read it. | Per-type bounded logs + a latest-state contact store keyed by (source, id), pruned at 5 min. Assistant and SITREP read contacts from the store, alerts from the acknowledgement store, decodes from the last 10 min (device telemetry excluded). With no feed: **"No feed is running — nothing is being watched. This is not an all-clear."** |
| H18 | Assistant probed `http://desktop:11434` on the GUI thread, then returned a canned string. | No default remote host (localhost only). No probe in the Qt page: free-form questions say **NOT IMPLEMENTED**; keyword questions answer from live state. |
| H19 | Tables showed local time under a Zulu clock. | `timebase.zulu()` everywhere; column headers say "(Z)". No `localtime`/`%H:%M` formatting left in `palisade_qt/` (a test enforces it). |
| E1 | An hour-old aircraft.json republished as live, age 0 s. | `AdsbFeed` keeps the receiver's own data time; status none when no source answers. ATLAS publishes aircraft only while LIVE and shows STALE with the age. |
| E4 | "no bleak/adapter" with both present; "attach a Meshtastic device" without looking; CAN/sensors silent with can-utils/rtl_433 installed. | **BLE / MESH / CAN / SENSORS NOT IMPLEMENTED — … installed; live … is not wired here**; hardware is blamed only when it is actually missing. |
| D4 | Empty tables were blank. | One `EmptyState` with three looks — OFFLINE (amber, hatched, reason), WATCHING (green, count + age), STALE (red age). `FeedTable` shows it whenever it has no rows; a worker's standby reason fills it; SWEEP, RECON, ATLAS and the ENGAGEMENT trail set specific reasons. |
| L5 | Remote Mode always served zero contacts (hard-coded provider). | Real provider: the ADS-B feed (the one source this standalone process can read). Aircraft served only while LIVE; status says ADS-B LIVE / STALE (age) / NO FEED. The dashboard table is now built with `textContent` — callsigns come off the air and were going into `innerHTML` (S1-class XSS). |

Also changed to make the above true: a worker resumed after a pause steps at once instead of
after a full interval (otherwise the Wi-Fi scan waited 15 s after RECON opened).

## Not done / follow-ups

- BABEL runners still show "AIS LIVE" etc. as soon as the decoder starts, before a first decode
  arrives (STARTING would be honest). Not in an audit ID; proposed for CL7 with the decoders.
- H5 "prefer GPS": GPS is not wired (CL6).
- R1: offline snapshot rollback still verifies (see table); needs an anchor outside the chain dir.
- H17 bus: workers still poll at their interval when hidden unless they opt in to pausing; that
  §15.1 item belongs to CL5's worker work.

## Tests

Full suite once on Python 3.12 (venv: PySide6, pyqtgraph, flask, numpy; no tkinter in this
container): **1464 passed, 6 failed, 7 errors, 7 skipped** (669 s). Of those:
- 4 were CL4's: the CL2 one-gate allowlist named `recon._run_cmd` (the spawn moved to
  `_run_scan`, same passive command) and two `test_palisade_qt` tests that asserted the old
  defects ("All quiet" with no feed; free-form answered "offline" after a probe). Updated to the
  CL4 semantics; the 4 re-run and pass.
- The rest are baseline, identical on main `04a76ab` in this container: `test_audit_tiles`
  undecodable tile, `test_hwlab` doctor, and the 7 `test_shell` errors (`No module named
  'tkinter'` — a Tk test, not a CL4 change).

Changed assertions, on purpose: event contract gained `demo` (H7); `scan_argv` gained `passive`
(H3); the two SYSTEM tests above. `tests/test_cl4_gates.py` 32/32 and `tests/test_cl4_honest.py`
58/58 pass. `pyflakes` clean on every touched file.

## Renders (1280×720, live, dark + sun) — `plan/briefs/CL4-renders/`

`{ops,sweep,prism,prowl,atlas,overwatch,recon_wifi,forge,bench,settings,assistant,sitrep,mesh,
engagement}_{dark,sun}_live_{before,after}.png`, script `render_cl4.py` (before = `04a76ab`).
Highlights: `sweep_*` (blank table → four detector rows + OFFLINE empty state), `sitrep_*`,
`assistant_*`, `recon_wifi_*` (standby reason fills the table), `atlas_*` (ADS-B NO FEED, HOME NOT
SET, empty list says why), `ops_*` (SDR chip from the kernel), `engagement_*`.

## CL4-fix — RA-CL4 findings (`RA-CL4-report.md`: DO NOT MERGE on N26)

| ID | Fix | Test |
|---|---|---|
| N26 High | With HOME unset (live), the OPS PPI and the ATLAS map are covered by an OFFLINE "HOME NOT SET" state (`kit.components.Cover`) and no contact is drawn on rings; the contact list still shows what is heard, without range. `MapPanel` never requests tiles until it has a real HOME (`_can_fetch`); setting HOME re-centres and fetches. | `test_n26_*` (2); renders `ops_*`, `atlas_*` |
| N27 Med | A chain that fails verification shows STALE "TRAIL UNREADABLE", never "nothing authorized yet". | `test_n27_*` |
| N28 Med | `engagement.chain_unreadable()` tells "engagement active, chain cannot be opened" from "no engagement"; the panel shows the reason. | `test_n28_*` (2) |
| N29 Med | Only contact/decode publishers (not telemetry, not alerts such as pass predictions or RADIO BUSY) count as a running feed. | `test_n29_*` |
| N30 Low | The Wi-Fi worker is paused before `start()` when RECON › WIFI is not on screen. | `test_n30_*` (10 trials, zero scans) |
| N31 Low | An orphan gone before END signalled it records `unconfirmed` "exited on its own before END signalled it", not a kill. | `test_n31_*` |
| N32 Low | END also refuses the session leader and every ancestor of the hub. | `test_n32_*` |
| N34 Low | The evidence-chain caption wraps instead of clipping. | render `engagement_sun_*` |
| E1 residual | No `now` in aircraft.json → the file's mtime (HTTP: unknown → stale); a `now` in the future is stale. | `test_e1_residual_*` |
| N33 Low | **Not fixed** (follow-up): a torn last line still refuses the chain. It fails closed. | — |

Full suite after CL4-fix (Python 3.12, same container): **1478 passed, 2 failed, 7 errors, 7
skipped** — all baseline and identical on main (`test_audit_tiles` undecodable tile,
`test_hwlab` doctor, 7 `test_shell` errors from missing tkinter). `test_cl4_*` 100/100.
