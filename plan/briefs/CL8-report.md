# CL8 — security + shipping (`fix/cl8-ship`)

Base: `main @ 1bc8ad1` (CL4 merged). Scope: L4 C1 L3 L2 L6 S1 S4 C4 C5 P1 P2 P3 B4 B5 B6 E6, plus
the v0.1 launch line (owner, 2026-11-16: SWEEP and unfinished tools hidden) and the CL2-fix
retirement list (Tk gated tools). Regression tests: `tests/test_cl8_ship.py` (86).

## Per finding

| ID | Fix | Where | Tests |
|---|---|---|---|
| **L4** High | New `argsafe.py`: `freq_arg` (strict `^\d{1,10}(\.\d{1,6})?([eE][+]?\d{1,2})?[kKMG]?$`, numbers 0<f<1e11), `gain_arg` (0..60), `safe_tokens` (pinned program, `[A-Za-z0-9_,:=+-]` tokens, no `/` `~` or leading `.`), raising `SettingsRefused` (a ValueError). Every legacy decoder is an argv pipeline run as one process group (`PipeGroup`, stage 1 `process_group=0`, later stages join it) — the string `pipeline()` builders are deleted (pager, rds, nwr, aprs, ais). `signals.build_argv` validates the editable ACARS/VDL2/rtl_433 templates. TPMS freqs/gain checked. canbus/specan/waterfall use `S.spawn(argv)`. hub's SDR++ hand-off watcher is `python3 -c … argv`, not `bash -c`. BABEL and PROWL catch `SettingsRefused`: FAULT · SETTINGS REFUSED, radio released, no retry until retune; Tk apps show Fault before starting. `fm.pipeline` refuses nan/inf/out-of-range. | argsafe.py, pager/rds/nwr/aprs/ais/signals/fm/hub.py, palisade_qt/babel.py, prowl.py | `test_l4_*` (PoC string refused by every builder; no `shell=True`/`os.system`/`sh -c` anywhere shipped; BABEL + PROWL with PoC settings start nothing and give the radio back; PipeGroup metacharacters are data; missing stage kills started ones) |
| **C1** High | Remote Mode needs a token: every route but `/health` is 401 without `Authorization: Bearer <token>` (or `?token=` once on `/`, which the page then strips from the URL). Token generated once into `headless.json` written 0600; `make_app` refuses to build without one. `no-store`, `nosniff`, `no-referrer`, CSP `default-src 'none'`. Dashboard already `textContent` (CL4). | headless.py | `test_c1_*` |
| **L3** Medium | New `netpolicy.py`: the one door for outbound HTTP. Modes OFFLINE (default; loopback only, never resolves a name) / LAN (every resolved address must be private, loopback or link-local) / ONLINE. Unknown or unreadable setting = OFFLINE. Non-http(s) schemes refused; redirects re-checked. Every `urlopen` in the suite routed through it (sitrep, wxsat, sky_app, tiles ×2, assistant, copilot, headless webhook, doctor, kraken, signals, hub). Requests logged; **NET slot** in the top strip (OFF / LAN / ON); the SESSION LOG panel holds the switch. Cached map tiles still draw offline. | netpolicy.py, palisade_qt/kit/topbar.py, panels.py, shell.py | `test_l3_*` (incl. a source scan: no `urlopen` outside netpolicy) |
| **C4** Medium | `palisade_qt/sessionlog.py`: one session log (memory + `~/.cache/uconsole-suite/session.log`, rotated at 1 MB), repeats counted. Every worker `on_error`/`on_fault`, parked workers, uncaught exceptions (sys + threading hooks), FORGE serial read/write failures (now also shown in the console), and the arbiter's swallowed lease-release errors are recorded. **Fault indicator**: the MODE slot's glyph becomes a red caution triangle (word stays LIVE/DEMO) until the log is opened; clicking MODE opens it. | sessionlog.py, app.py, forge.py, radio_arbiter.py | `test_c4_*` |
| **L2** Medium | `harden.sh --field`: reset, default deny incoming, allow outgoing, enable — no exceptions. `--revert` now returns to that default-deny (never `ufw disable`). HOME profile warns that on a client site the subnet is the client's LAN. No `apt-get update`. **Edited only; not run on any system.** | harden.sh | `test_l2_*` (sudo/ufw/ip stubbed on PATH, they only record) |
| **L6** Low | Launchers in `/usr/local/bin` are root-owned files (`sudo install -m 0755 -o root -g root`), not symlinks into `~/.local/bin`; an old symlink is replaced; our user copy removed. | install_tail.sh | `test_l6_*` |
| **S1** High | Installer ships `palisade_qt/` (payload + compile check), installs numpy/pyqtgraph/PySide6 (apt first, pip fallback) and flask, adds `palisade` (`python3 -m palisade_qt`) and a **PALISADE** menu entry as the default; the Tk hub stays as "Sentry (legacy Tk hub)"; the false "receive-only" description is gone. | install_head.sh, install_tail.sh, build_installer.sh | `test_s1_*` (builds the real installer, checks `bash -n` and the payload) |
| **S4** Medium | Doctor's default-password check reads the shadow file itself and calls `crypt(3)` from libcrypt via ctypes (yescrypt and sha512 on Debian 13); no `crypt`/`spwd`. | doctor.py | `test_s4_*` |
| **C5** Low | `plugins.py` (auto-loaded Python from the app dir) and its tests deleted, hook removed from hub.py. The offscreen check has one copy (`palisade_qt/kit/seams.py`). `more.py` was already gone (CL5). | | `test_c5_*` |
| **P1** Medium | BSS header must be `^BSS <mac>` at line start: an SSID `BSS de:ad:be:ef:00:01` no longer creates a phantom AP or blanks the real one. | wifisurvey.py | `test_p1_*` |
| **P2** Medium | Security class from the Privacy bit + AKM suites: open, WEP, WPA, WPA2-PSK, WPA3-SAE, WPA2/WPA3, WPA2-EAP, WPA3-EAP, OWE, WPA2/3 (RSN, AKM not heard). WEP is no longer "open". | wifisurvey.py | `test_p2_*` (11 cases) |
| **P3** Low | AIS: NMEA checksum required (missing/wrong = refused). Remote ID: a drone is red only after ≥3 adverts over ≥2 s; before that amber, label `id ?`, card `STATUS UNCONFIRMED · n adverts`. Every positional source carries a SOURCE line (UNAUTHENTICATED RID/ADS-B/AIS/APRS). Demo AIS sentences had wrong checksums: fixed. | ais.py, dronewatch.py (adds `adverts`/`first` fields only), atlas.py | `test_p3_*` |
| **B4** Medium | Selection was already kept by item (CL1); now the scroll position is too (top visible item, unless at the top following the live feed); arrow keys drive the detail. | kit/feed.py | `test_b4_*` |
| **B5** Low | OPS scope: click a contact to select it (violet ring + label), click again to clear; the decorative sweep and its 16 fps timer are gone. | kit/ppi.py, ops.py | `test_b5_*` |
| **B6** Low | TPMS hops every 30 s (`-H 30`; rtl_433's default with two `-f` is 600 s), configurable 5–600. Map labels decluttered: a label whose box would overlap one already placed is skipped (the dot stays). | babel.py, kit/mappanel.py | `test_b6_*` |
| **E6** Low | Pass search starts 30 min before now; passes not yet set are kept and flagged `in_progress`. | wxsat.py | `test_e6_*` (real skyfield, mid-pass) |

**v0.1 line.** `palisade_qt/release.py`: `HIDDEN_PAGES = {"SWEEP"}` — not on the strip, not on a
number key, not in the palette, not openable by name (`PALISADE_SHOW_HIDDEN=1` for development).
Keys renumber 1–7 (RECON 5, FORGE 6, SYSTEM 7). **Retired from the Tk hub** (CL2-fix list): cw,
rtty, digimodes, replay, proxmark, wifipent, blepent, zigbee, zwave, usbhid tiles. Engines stay;
digimodes stays refused.

## Changed tests (semantic changes, each justified)

- `test_cl5_radio::test_a4_decoder_argv_builders_match_the_legacy_strings` — the legacy strings
  are deleted (L4); the argv they split into is now frozen literally (verified identical to main).
- `test_cl5_fix{,2,3}` — monkeypatch `ais.pipeline_argv` (the string `pipeline` is gone); fake
  `rtl_ais` sentence checksum corrected `*5C`→`*5F` (P3 now refuses the wrong one).
- `test_headless`, `test_cl4_honest::test_l5_…` — requests carry the token (C1).
- `test_palisade_qt::test_rid_source_decodes_drone_and_operator` — one advert is now amber
  UNCONFIRMED; the test then feeds 3 s of adverts and asserts red (P3).
- `test_cl1_screen::test_eight_keys…` — ALL_CALLSIGNS keeps 8; CALLSIGNS is 7 (v0.1 line).
- `test_cl1_screen::test_opsec_slot_is_reserved_as_a_placeholder` — see the flag below.
- `tests/test_plugins.py` deleted with `plugins.py` (C5).

## Flags for the owner

1. **OPSEC placeholder.** The strip had 1 px spare in the worst case. NET needed 88 px; it took
   SWEEP's key (hidden in v0.1) and the 20 px reserved OPSEC placeholder, which showed nothing.
   When OPSEC lands it needs room again (SWEEP's return in v0.2 has the same problem). Worst case
   now 1267 px (sun, demo) ≤ 1270.
2. **NET defaults to OFFLINE** on every install, home included: map tiles, METAR/TFR, Celestrak
   and adsbdb need NET set to LAN/ONLINE once (it persists in `net.json`).
3. **Not done (follow-ups):** AIS and RDS are still implemented twice (BABEL vs ATLAS/PROWL/FM) —
   merging them changes radio paths, so it belongs with CL6. 150 legacy Tk `except Exception`
   sites remain; the Qt package's worst ones are logged.
4. Remote ID confirmation (3 adverts / 2 s) and the 30 s TPMS hop are my numbers; easy to tune.

## Renders

`plan/briefs/CL8-renders/` (1280×720, live, dark + sun; `render_cl8.py`): `ops`, `ops_select`,
`atlas_rid`, `recon` before/after; after only: `ops_fault` (red ▲ LIVE), `session_log`,
`net_lan`.

## Device check (uConsole, Debian 13 / Python 3.13)

`python3 plan/briefs/device_check_cl8.py` — changes nothing (no sudo, no firewall, no radio).
Expected last line: `DEVICE CHECK CL8: PASS (10/10)`. Here (container, 3.13.18): PASS 10/10.

## Suite

Full suite, Python 3.13.18, `QT_QPA_PLATFORM=offscreen xvfb-run -a python3 -m pytest -q tests`:
first run 8 failed / 1549 passed / 7 skipped / 7 errors. Baseline (same on main, env): test_audit_tiles
undecodable tile, test_hwlab doctor hwbench, 7 test_shell errors (no tkinter). The other 6 were CL8
semantic changes, fixed in the tests (commit 889b7ed):

- `test_audit_sitrep::test_metar_stops_after_network_failure`, `test_audit_tiles::test_http_404_does_not_mark_layer_offline`,
  `test_sitrep_doctor::test_tfr_filters_by_state` — they test behaviour once the network is allowed;
  L3 makes OFFLINE the default, so they set `PALISADE_NET=ONLINE`. New
  `test_cl8_ship::test_l3_offline_sitrep_and_tiles_never_call_urlopen` pins the OFFLINE side
  (only loopback is reached).
- `test_cl1_fix::test_detectors_start_when_sweep_opens_and_not_before`,
  `test_palisade_qt::test_every_callsign_opens_pumps_closes_clean[SWEEP]`,
  `test_palisade_qt::test_hub_soak_…` — SWEEP is hidden in v0.1; its own tests set
  `PALISADE_SHOW_HIDDEN=1`, so it is still built and soaked.

Second full run: see below.
