# PALISADE — Feature coverage map

Mandate: **every capability from the Sentry (Tk) suite ports into the Qt app, wired to its
REAL backend — nothing dropped — and consolidated under the 9 callsigns, plus the new
features below.** A callsign is "done" only when its panels run real backends (not demo).

Status key: ✅ wired · ◐ partial/demo · ⬜ not started · ➕ new feature

---

## OPS — situational home
Absorbs: field_status, sensors, powergov, doctor (status), sitrep (summary), live feed aggregate.
- ◐ live contact feed (currently synthetic) → wire the real aggregated event bus
- ⬜ **PPI scope hero** (from the concept) — dominant situational element, missing today
- ⬜ power/thermal/GPS/battery telemetry from real `field_status` + `powergov`
- ➕ one unified alert/timeline strip fed by every callsign

## OVERWATCH — sky dome + radio director
Absorbs: overwatch, astro, skyintel(ADS-B, NOT sat), wxsat(passes), passsched, radio arbiter.
- ◐ **OVERWATCH page wired** — sub-views SKY DOME / RADIO / PASSES, all backends AS-IS.
  - **SKY DOME** — a QPainter polar dome (zenith centre, horizon rim, N/E/S/W, elevation rings)
    with the sun + moon from pure `astro.sun_azel`/`moon_azel` (always live — deterministic math)
    and satellite positions + pass arcs; projection reuses `overwatch.project`/`dome_r`/`compass`.
  - **RADIO** (the director seed) — the operator's view into the one-owner dongle: current
    `radio_arbiter` holder, acquire/release history (from the arbiter's `changed` signal), and a
    "FREE THE RADIO" hand-over that releases the holder so the next layer can take it.
  - **PASSES** — upcoming passes from `wxsat.predict` (skyfield + TLE) scheduled via
    `passsched.schedule`/`next_pass`/`assign_decoder`; the next real pass raises an
    `alert(source=OVERWATCH)` for the OPS next-pass card. No TLE → "NO TLE — update required"
    standby, no synthetic passes in live; demo passes are flagged; tests inject a fake TLE file and
    never fetch from network.
- Scout (site survey) stays under **RECON** (network/RF survey fits there, not the sky/radio view).
- ⬜ autopilot radio rotation, per-pass arbiter record (acquire on AOS / release on LOS) on-device,
  live TLE refresh.

## ATLAS — the map
Absorbs: sky_app (ADS-B), skyintel, mlat, balloons, aprs, dronewatch (Remote ID), kraken (DF),
tacmap, geo, tiles, fieldcomp (map/trip/almanac).
- ✅ **ONE layered map** — aircraft / ships / APRS / **drones (Remote-ID, first-class)** / DF /
  balloons, togglable layers + legend; selectable contact → detail (id, alt, speed, dist+brg)
- ✅ every contact publishes a typed `contact` event to the event bus → renders on ATLAS's map
  AND the OPS PPI (one stream, two views); demo feed wired, flagged by the SDR-DEMO chip
- ◐ **live ADS-B WIRED** — reuses `sky_app.AdsbFeed` (readsb/dump1090 `aircraft.json`) as-is and
  adapts its aircraft to typed `contact` events (`adsb_to_contact`, kind=aircraft, source=ADS-B,
  7x00 squawk/emergency → alert). No 2nd radio and no lease (readsb owns its radio). Shows on the
  ATLAS map AND the OPS PPI. **Device validation (real RTL capture) pending on the uConsole.**
- ◐ **live Remote-ID (dronewatch) WIRED** — reuses dronewatch's OpenDroneID decoder as-is over a
  BLE (bleak) scan; publishes the **DRONE (red)** AND its **OPERATOR (violet, the differentiator)**
  as typed contacts. BLE/Wi-Fi, NOT the SDR → no lease. Wi-Fi-monitor path stubbed (device-only).
  On the ATLAS map + OPS PPI. **Device validation (real beacons / BLE on the uConsole) pending.**
- ◐ **live APRS WIRED** (the FIRST lease-using source) — aprs's 144.39 decoder as-is
  (rtl_fm→multimon-ng→parse_frame/decode/Stations); stations as typed contacts (amber, kind=station).
  Holds the single-SDR **LEASE only while the APRS layer is on** (acquire on toggle-on, release on
  toggle-off AND page close); opt-in in live, so opening ATLAS never grabs the radio or disturbs
  the autopilot. This is the template for AIS/PRISM. **Device validation (real 144.39 + dongle) pending.**
- ◐ **live AIS WIRED** — ais's 162 MHz decoder as-is (rtl_ais→AivdmAssembler/decode/Vessels);
  vessels as typed contacts (cyan, kind=vessel). Uses the shared radio arbiter. Device validation pending.
- ➕ **RADIO ARBITER** (radio_arbiter.py) — one SDR owner at a time (APRS/AIS; later PRISM). A
  denied lease-layer renders "RADIO BUSY — held by X" on the map rail + an OPS alert, and ADS-B
  shows BUSY (readsb paused) while a layer holds the radio, resuming on release. No time-sharing;
  the displaced layer shows BUSY. This is the seed of the OVERWATCH radio director.
- ⬜ remaining live adapters (kraken DF, balloons) — stubbed; zero until wired

## BABEL — universal decoder
Absorbs: ais, signals (ACARS/VDL2), pager (POCSAG/FLEX), rds, cw, rtty, digimodes, tpms,
zigbee, zwave, nwr, sstv/sstvdec, wxsat (LRPT/APT).
- ✅ ais, signals, pager, rds wired
- ✅ **single-SDR via the shared radio arbiter** (PR-B1 foundation) — BABEL's radio modes
  (AIS/ACARS/POCSAG/RDS) lease the one dongle through `radio_arbiter` under NAME `BABEL`
  (no longer the base-class lease), so it coexists with ATLAS/PRISM — one owner at a time; a
  held radio renders "RADIO BUSY — held by X" and, being live, decodes nothing. The live
  runners gained the `_open_pipe` offscreen/offline seam so tests/CI never open a real radio.
- ✅ **TPMS** (PR-B2) — tire-pressure sensors via rtl_433 JSON (315/433.92 MHz); `tpms.parse_tpms`
  reused AS-IS, SDR-leased, honest standby (no `rtl_433` → "TPMS STANDBY"), real decodes publish to
  the bus as `decode(source=BABEL-TPMS)` → OPS decode card.
- ⬜ **CW / RTTY / digimodes — no reusable live RX backend AS-IS.** cw.py/rtty.py expose only the
  *encode/decode primitives* (`decode_morse`, `decode_timing`, `decode_codes`) and are TX keyers
  gated by txguard; there is **no audio→timing / audio→FSK demodulator**. digimodes.py has **no
  decode path at all** (a txguard-gated TX launcher). Wiring these "live" would require building new
  DSP — out of the UI-only mandate — so they stay practice/demo until a demod backend exists.
- ⬜ **classify** — pure `classify(iq, fs)` modulation triage, but BABEL has no live IQ feed to run
  it on; it belongs where an IQ source exists (PRISM/file), not a BABEL live tab.
- ✅ **SSTV** (PR-B3) — ISS SSTV image decoder: `sstv.Recorder` (rtl_fm→WAV) under the `BABEL-SSTV`
  lease, re-running `sstvdec.decode_wav` on the growing WAV until a frame decodes (both reused
  AS-IS). A stacked **image panel** renders the RGB frame (numpy→QImage); honest standby (no
  `rtl_fm`/numpy → "SSTV STANDBY"), a frame shown only on a real decode (ISS SSTV is rare →
  listening is the norm); offscreen seam opens no radio. Decodes publish to the bus.
- ⬜ **wxsat — image decoder, own PR** (device-only): drives SatDump (APT/LRPT) → PNGs,
  pass-scheduled; a SatDump subprocess + filesystem harvest, not a pure reuse.
- NWR is wired under **PROWL** (SAME/EAS), not duplicated here.
- ⬜ **406 MHz COSPAS-SARSAT** (new decoder), Zigbee / Z-Wave (engagement-gated, future)
- ➕ protocol filter + per-source coloring + one searchable decode log

## PRISM — spectrum + waterfall
Absorbs: rf_explorer, specan, waterfall, iqtool, noisefloor, classify.
- ◐ spectrum/waterfall render (demo) → wire real RTL-SDR IQ
- ⬜ IQ record/replay, noise-floor tracking, signal classifier
- ➕ click-to-tune into PROWL/BABEL from a spectrum peak

## PROWL — scanner / tuner
Absorbs: scanner, fm, freqdb.
- ✅ scanner wired · ⬜ fm, freqdb
- ➕ memory banks + scan/hold + audio with the top-bar volume

## FORGE — hardware & IO bench
Absorbs: hwlab (serial/I2C/GPIO), devterm (serial/BLE/MQTT/SSH), buslab, canbus, proxmark,
flipper, usbhid, rollcode, replay, sensors.
- ◐ **FORGE page wired** — sub-tabs SERIAL / BUS / RFID / RADIO / SENSORS, all backends AS-IS.
  - **One colored multiplexed console** (`ConsolePane`): per-device scrollback + input line +
    tx/rx/sys/ok/deny coloring. SERIAL = hwlab console (`SerialReader`/`DemoSerial` via a seam);
    the same pane serves the CAN monitor and Proxmark reads.
  - **Two gate types, same model as RECON** (engine-enforced, UI only reflects): engagement-gated
    (canbus `prepare_send`, proxmark `prepare` write/clone/sim, usbhid `prepare` inject) show
    "REQUIRES ENGAGEMENT"; txguard-gated (replay `prepare_replay`) shows a live **TX GATED** banner
    (armed/unlocked). The UI never spawns a produced write/TX argv and wires no new TX path.
  - **Passive always on**: hwlab serial console + I2C/GPIO read, canbus monitor (OBD/UDS decoded),
    proxmark/flipper reads, rollcode RX analysis, sensors ISM readout — honest "NO DEVICE" standby,
    demo flagged, bus publishes device/CAN/RFID/sensor reads as `decode(source=FORGE)`.
- ➕ gated-action authorizations + flipper NFC-relay alerts → OPS strip.
- ⬜ live device I/O (real serial/CAN/USB/Proxmark/Flipper) + buslab flash/JTAG write + per-op
  Proxmark/Flipper param UIs are device-only follow-ups.

## RECON — network + RF survey (authorized)
Absorbs: wifisurvey, wifipent, netpent, blescan, blepent, passaudit, scout, rffinger,
bugsweep, jammer (detector), imsicatch (detector), gnss, + engagement/opprofile/evidence.
- ◐ **RECON page wired** — sub-tabs WIFI / BLE / NET / RF / COUNTER / ENGAGE, all backends AS-IS.
  - **ENGAGE** (keystone): operator identity (`opprofile`), engagement scope (`engagement.start/end`),
    the authorized-action trail + the tamper-evident evidence chain (`evidence.EvidenceChain`).
  - **Gate is engine-enforced** — active tools (wifipent/blepent/netpent/passaudit) call their own
    `prepare()` → `engagement.authorize_action(...)`; with no engagement (or out-of-scope target) the
    engine returns no argv. The UI only reflects state ("REQUIRES ENGAGEMENT" vs the active scope) and
    passes the shared evidence chain — it never routes around the gate or wires a new TX/attack path.
  - **Passive**: wifisurvey AP scan + blescan BLE enum (hermetic seams, honest standby, bus publish).
  - **COUNTER**: bugsweep / jammer / imsicatch / gnss — all receive-only detectors (no TX, guardrail
    test), demo-fed, alerts → OPS strip.
- ➕ open-network / fake-BTS / jammer / GPS-spoof alerts → `alert(source=RECON)` on the OPS strip;
  Wi-Fi/BLE scans → `decode(source=RECON)`.
- ⬜ live adapter wiring (monitor-mode Wi-Fi, bleak BLE, nmap, SatDump) is device-only; RF fingerprint
  + scout site-survey are standby until an on-device feed is wired.

## BENCH — conducted TX self-test
Absorbs: bench, loopback, txguard UI.
- ◐ self-test UI → wire bench/loopback engines behind txguard; show the gate state live

## MORE / SYSTEM (under a gear/overflow)
Absorbs: settings_ui, doctor, assistant (AI), sitrep (spoken), transcriber, mesh_dash
(Meshtastic), engagement, opprofile, evidence, fusion.
- ⬜ settings, device doctor, **AI assistant tied to live context**, spoken sitrep, transcriber,
  Meshtastic chat/nodes, session logging (engagement/evidence)

---

## New, cross-cutting features (the "and more")
- ➕ **Event bus** — one alert/timeline every callsign publishes to; OPS + spoken sitrep consume it.
- ➕ **Session record + replay** — capture a field session (all feeds) and play it back.
- ➕ **Cross-feed fusion** — correlate ADS-B + ACARS + RF into single tracks (fusion.py).
- ➕ **Command palette (⌘K)** — jump to any callsign/freq/tail/decoder.
- ➕ **Watchlists** — watch a tail/callsign/freq/MAC; alert on hit.
- ➕ **Export** — KML/CSV/GPX for contacts, tracks, logs.
- ➕ **Global health-aware load shedding** — thermal/battery service shuts heavy panels first.
- ➕ **Theme** — violet light/dark per DESIGN.md, legible at 1280×480.

## Guardrails (unchanged)
RX-first; TX only behind txguard (ham/ISM/conducted, protected bands denied); no OTA
attack/jam/deauth; jammer/imsicatch are detectors; no kernel/firewall/SSH changes; keep the
`uconsole-suite` data path; legacy Tk app stays as fallback until parity.
