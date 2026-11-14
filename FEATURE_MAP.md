# PALISADE — Feature coverage map

Mandate: **every capability from the Sentry (Tk) suite ports into the Qt app, wired to its
REAL backend — nothing dropped — and consolidated under the 9 callsigns, plus the new
features below.** A callsign is "done" only when its panels run real backends (not demo).

Status key: ✅ wired · ◐ partial/demo · ⬜ not started · ➕ new feature · 🔧 engineering (new code, not just wiring)

---

## OPS — situational home
Absorbs: field_status, sensors, powergov, doctor (status), sitrep (summary), live feed aggregate.
- ✅ event-bus spine, PPI scope hero, right-rail cards, honest standby states
- ◐ power/thermal/GPS/battery telemetry from real `field_status` + `powergov`
- ➕ one unified alert/timeline strip fed by every callsign
- ➕ spoken sitrep (AI-generated voice summary of current picture)

## OVERWATCH — sky dome + radio director
Absorbs: overwatch, astro, radio (SDR lease/autopilot), scout, passsched.
- ⬜ sky dome (sun/moon/sat passes via astro), pass scheduling
- 🔧 **radio director** — autopilot time-sharing the dongle across active layers (rotation)
- 🔧 **remote sensor nodes** — distributed PALISADE instances feeding one OPS dashboard

## ATLAS — the map
Absorbs: sky_app (ADS-B), skyintel, mlat, balloons, aprs, dronewatch (Remote ID), kraken (DF),
tacmap, geo, tiles, fieldcomp (map/trip/almanac), gnss.
- ✅ ADS-B (readsb), Remote-ID drone+operator (BLE/WiFi), APRS (144.39, SDR lease),
  AIS (162 MHz, SDR lease), DF/kraken (scaffolded, device-gated), balloons (radiosonde)
- ✅ radio arbiter — one-owner model, RADIO BUSY states across all lease-using layers
- ✅ all contacts on ONE map (aircraft + ships + APRS + drones + DF), selectable layers
- ➕ offline tile cache for field use without internet
- 🔧 **cross-feed fusion** — correlate ADS-B + AIS + APRS + BLE + WiFi into unified tracks
- 🔧 **pattern-of-life ledger** — time-series contact tracking with anomaly/change alerts
- 🔧 **geofenced alerts** — define areas, alert on contact enter/leave

## BABEL — universal decoder
Absorbs: ais, signals (ACARS/VDL2), pager (POCSAG/FLEX), rds, cw, rtty, digimodes, tpms,
zigbee, zwave, nwr, sstv/sstvdec, wxsat (LRPT/APT), classify.
- ✅ ais, signals, pager, rds wired (B1)
- ◐ TPMS, SSTV, wxsat wired (B2); CW/RTTY/digimodes/classify as demo/practice (no live backend yet)
- ⬜ Zigbee, Z-Wave (engagement-gated)
- 🔧 **CW decoder** — Goertzel tone detection → Morse → text
- 🔧 **RTTY decoder** — FSK demod → Baudot → text
- 🔧 **Digimodes** — PSK31, FT8, WSPR decoders (or integrate direwolf/js8call/wsjtx)
- 🔧 **Signal classifier** — IQ → auto signal identification (ML or heuristic)
- 🔧 **rtl_433 integration** — decode 433 MHz ISM devices (weather stations, sensors, doorbells, car keys, etc.) — hundreds of device types, mature tool
- 🔧 **ACARS/VDL2** — aircraft data link messages beyond ADS-B (wire acarsdec/dumpvdl2)
- 🔧 **Iridium satellite decode** — sat pager/comms intercept (Iridium-Toolkit)
- 🔧 **DECT phone decode** — cordless phone interception (gr-dect2)
- 🔧 **LTE cell scanning** — passive cellular recon: cell ID, MCC/MNC, signal strength (LTE-Cell-Scanner/srsRAN)
- 🔧 **GR-GSM** — passive GSM decode + cell mapping
- 🔧 **406 MHz COSPAS-SARSAT** — emergency beacon decode
- 🔧 **SatDump integration** — NOAA APT, Meteor LRPT, GOES satellite imagery
- ➕ protocol filter + per-source coloring + one searchable decode log
- ➕ number station / spy station database + tuner integration

## PRISM — spectrum + waterfall
Absorbs: rf_explorer, specan, waterfall, iqtool, noisefloor, classify, freqdb, rffinger.
- ✅ PyQtGraph waterfall + spectrum, violet→green colormap, peak-hold, on arbiter
- ◐ IQ record/replay (iqtool), noise-floor tracking, RF fingerprint, freqdb overlay
- 🔧 **SigDigger-level signal analysis** — symbol recording, constellation view, baud rate estimation, scrambling polynomial detection, transition analysis
- 🔧 **TEMPEST** — EM emanation monitoring (gr-tempest, experimental)
- ➕ click-to-tune into PROWL/BABEL from a spectrum peak

## PROWL — scanner / tuner
Absorbs: scanner, fm, freqdb, nwr.
- ✅ scanner + FM tuner + NWR/SAME decode, all on arbiter, sub-mode tabs
- ➕ memory banks + scan/hold + audio with the top-bar volume
- ➕ CTCSS/DCS decoder

## FORGE — hardware & IO bench
Absorbs: hwlab (serial/I2C/GPIO), devterm (serial/BLE/MQTT/SSH), buslab, canbus, proxmark,
flipper, usbhid, rollcode, replay, sensors (I2C).
- ⬜ all — real serial/I2C/CAN/BLE consoles + tool integrations
- ➕ one colored multiplexed console with per-device tabs
- 🔧 **Ubertooth integration** — raw Bluetooth Classic sniffing (beyond BLE)

## RECON — network + RF survey + pentest (authorized)
Absorbs: wifisurvey, wifipent, netpent, blescan, blepent, passaudit, scout, rffinger,
bugsweep, jammer (detector), imsicatch (detector), gnss (spoof detect), mesh_dash,
opprofile, engagement, evidence.
- ⬜ wifi survey/audit, BLE scan, net scan, RF fingerprint, counter-surveillance (bugsweep,
  jam-detect, IMSI-catcher-detect, GNSS spoof-detect)
- ⬜ engagement governance UI (opprofile, engagement, evidence)
- ➕ open-network / rogue-AP / tracker + fake-BTS alerts into the OPS alert strip
- 🔧 **threat correlation** — cross-reference WiFi/BLE/cellular anomalies into a unified threat picture

## BENCH — conducted TX self-test
Absorbs: bench, loopback, txguard UI.
- ◐ self-test UI → wire bench/loopback engines behind txguard; show the gate state live

## MORE / SYSTEM (under a gear/overflow)
Absorbs: settings_ui, doctor, assistant (AI), sitrep (spoken), transcriber, fusion.
- ⬜ settings, device doctor, **AI assistant tied to live context**, spoken sitrep, transcriber,
  session logging
- 🔧 **Meshtastic mesh relay** — relay contacts/alerts over LoRa mesh to other PALISADE nodes

---

## New, cross-cutting features

### Wiring phase (UI + integration, no new algorithms)
- ✅ **Event bus** — typed contract, thread-safe, geo-native payloads. OPS + all panels consume.
- ✅ **Radio arbiter** — one-owner dongle model, RADIO BUSY states, seed for OVERWATCH director.
- ✅ **Theme** — violet light/dark per DESIGN.md, depth tokens, legible at 1280×480.
- ➕ **Session record + replay** — capture all event-bus traffic, play back field sessions.
- ➕ **Command palette (⌘K)** — jump to any callsign/freq/tail/decoder.
- ➕ **Watchlists** — watch a tail/callsign/freq/MAC/MMSI; alert on hit.
- ➕ **Export** — KML/CSV/GPX for contacts, tracks, logs.
- ➕ **ATAK/Cursor-on-Target export** — push contacts to TAK as CoT XML over multicast.
- ➕ **Global health-aware load shedding** — thermal/battery service shuts heavy panels first.
- ➕ **Offline/air-gapped mode** — bundled assets, no internet required for core functions.

### Engineering phase (new code / DSP / algorithms)
- 🔧 **DSP decoders** — CW, RTTY, digimodes, signal classifier (see BABEL above)
- 🔧 **rtl_433 ISM** — 433 MHz device decode (see BABEL above)
- 🔧 **ACARS/VDL2 + Iridium + DECT + LTE + GSM** — protocol decoders (see BABEL above)
- 🔧 **SatDump satellite imagery** — NOAA/Meteor/GOES (see BABEL above)
- 🔧 **Signal analysis** — SigDigger-level inspection in PRISM (see PRISM above)
- 🔧 **Cross-feed fusion** — multi-source track correlation (see ATLAS above)
- 🔧 **Pattern-of-life + anomaly detection** — contact time-series intelligence (see ATLAS above)
- 🔧 **Radio director** — autopilot dongle rotation (see OVERWATCH above)
- 🔧 **Remote sensor nodes** — distributed multi-device SIGINT (see OVERWATCH above)
- 🔧 **Meshtastic mesh relay** — LoRa contact/alert relay (see MORE above)
- 🔧 **TEMPEST** — EM emanation monitoring (see PRISM above, experimental)
- 🔧 **Ubertooth BT Classic** — raw Bluetooth sniffing (see FORGE above)
- 🔧 **Threat correlation** — unified threat picture from WiFi/BLE/cellular (see RECON above)
- 🔧 **Second SDR support** — dual-dongle architecture for simultaneous operation
- 🔧 **HackRF TX paths** — conducted self-test transmit for BENCH (behind txguard)

---

## Build order
### Phase 1 — Wiring (current: get a usable app)
OPS ✅ → ATLAS ✅ → PRISM ✅ → PROWL ✅ → BABEL (in progress) → RECON → FORGE → OVERWATCH → BENCH → MORE

### Phase 2 — Engineering (after wiring: build what doesn't exist)
Priority order:
1. rtl_433 ISM (easiest win, massive device coverage)
2. ACARS/VDL2 (aircraft data beyond ADS-B, mature tools)
3. Session record/replay + ATAK/CoT export (makes it a real field tool)
4. Cross-feed fusion + pattern-of-life (the differentiator vs iNTERCEPT)
5. Remote sensor nodes (distributed PALISADE)
6. LTE cell scanning + GSM (cellular gap)
7. SigDigger-level signal analysis in PRISM
8. DSP decoders (CW/RTTY/digimodes)
9. Iridium + DECT + SatDump (niche but powerful)
10. TEMPEST + Ubertooth (experimental/hardware-gated)
11. Second SDR + radio director (unlocks simultaneous operation)
12. HackRF TX for BENCH (conducted self-test only)

## Guardrails
All tools come in. Active assessment gated behind engagement.py (authorization), opprofile.py
(operator identity), and txguard (TX safety on protected bands). Do not route around these
gates. No kernel/firewall/SSH changes; keep the `uconsole-suite` data path; legacy Tk app
stays as fallback until parity.
