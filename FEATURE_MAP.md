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

## OVERWATCH — sky dome + radio director + power manager + SENTINEL
Absorbs: overwatch, astro, radio (SDR lease/autopilot), scout, passsched.
- ⬜ sky dome (sun/moon/sat passes via astro), pass scheduling
- 🔧 **SENTINEL autonomous watch mode** — unattended RF monitoring + baseline diffing + alerting (see Platform Capabilities above)
- 🔧 **radio director** — autopilot time-sharing the dongle across active layers (rotation)
- 🔧 **remote sensor nodes** — distributed PALISADE instances feeding one OPS dashboard
- 🔧 **GPIO power manager** (AIO V2) — individual SDR/GPS/LoRa/USB power on/off via GPIO for load shedding + hardware control
- 🔧 **OPSEC mode** — one-button RF-dark confirmation: kill all TX, pure monitor WiFi, no BLE advertising, visual OPS indicator (see Operational Modes above)

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
- 🔧 **entity graph** — multi-radio identity resolution: WiFi+BLE+TPMS+APRS co-movement → single entity (see Platform Capabilities above)
- 🔧 **OSINT enrichment layer** — auto-lookup detected identifiers against cached offline databases on NVMe: MAC → vendor (IEEE OUI), MMSI → vessel name/flag (ITU), tail number → aircraft registration (FAA), callsign → ham license (FCC ULS), BSSID → known AP mapping. Turns raw contacts into identified entities. Feeds the entity graph
- 🔧 **geofenced alerts** — define areas, alert on contact enter/leave
- 🔧 **temporal timeline view** — scrub through time across all radios: "at 14:32 this BLE appeared, at 14:35 this WiFi probed, at 14:37 this TPMS arrived" with correlation markers

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
- 🔧 **Sub-GHz LoRa band scanner** (AIO V2 SX1262) — 860–960 MHz spectrum scan + RSSI waterfall via LoRa radio, separate from RTL-SDR
- 🔧 **AI signal classification** — ML model trained on known signal types, flags unknowns for human review. "This doesn't match anything in the database" = potential covert transmitter
- 🔧 **Spectral fingerprinting** — capture physical-layer manufacturing imperfections of individual radios from IQ data. Same model WiFi router, different fingerprint. Identifies devices even after MAC change
- 🔧 **TEMPEST** — EM emanation monitoring (gr-tempest, experimental)
- ➕ click-to-tune into PROWL/BABEL from a spectrum peak

## PROWL — scanner / tuner
Absorbs: scanner, fm, freqdb, nwr.
- ✅ scanner + FM tuner + NWR/SAME decode, all on arbiter, sub-mode tabs
- 🔧 **DMR / P25 / TETRA / NXDN digital trunked radio** — decode digital police/fire/EMS/commercial/military radio via SDRTrunk or OP25. Majority of modern radio traffic is digital; without this PALISADE is deaf to it. Mature open-source tools, RTL-SDR compatible
- ➕ memory banks + scan/hold + audio with the top-bar volume
- ➕ CTCSS/DCS decoder

## FORGE — hardware & IO bench
Absorbs: hwlab (serial/I2C/GPIO), devterm (serial/BLE/MQTT/SSH), buslab, canbus, proxmark,
flipper, usbhid, rollcode, replay, sensors (I2C).
- ⬜ all — real serial/I2C/CAN/BLE consoles + tool integrations
- ➕ one colored multiplexed console with per-device tabs
- 🔧 **Inductive CAN bus sniffing via SDR** — contactless vehicle CAN data extraction using RTL-SDR + inductive probe, no physical OBD-II connection needed (per NEWSDR 2025 paper). Different from wired canbus.py
- 🔧 **LoRa packet capture + replay** (AIO V2 SX1262) — raw LoRa sniff, record, decode, and replay (TX replay gated behind txguard). IoT/LoRaWAN security testing
- 🔧 **Meshtastic packet analysis** (AIO V2 SX1262) — decode mesh traffic: node IDs, positions, messages, channel keys. Counter-mesh recon
- 🔧 **Bias tee control** (AIO V2 RTL-SDR) — software toggle for 5V bias tee powering external LNAs/active antennas through coax
- 🔧 **Ubertooth integration** — raw Bluetooth Classic sniffing (beyond BLE)
- 🔧 **Nordic nRF sniffer** — protocol-aware BLE packet capture (GATT endpoints, pairing, keys) vs raw BLE scan

## RECON — network + RF survey + pentest (authorized)
Absorbs: wifisurvey, wifipent, netpent, blescan, blepent, passaudit, scout, rffinger,
bugsweep, jammer (detector), imsicatch (detector), gnss (spoof detect), mesh_dash,
opprofile, engagement, evidence.
- ⬜ wifi survey/audit, BLE scan, net scan, RF fingerprint, counter-surveillance (bugsweep,
  jam-detect, IMSI-catcher-detect, GNSS spoof-detect)
- ⬜ engagement governance UI (opprofile, engagement, evidence)
- 🔧 **automated engagement report** — PDF generation from evidence chain (see Platform Capabilities above)
- 🔧 **screenshot / evidence capture** — save current PALISADE view as timestamped, GPS-tagged evidence image
- 🔧 **voice notes** — record audio memo tied to a contact or event on the timeline (uConsole mic)
- ➕ open-network / rogue-AP / tracker + fake-BTS alerts into the OPS alert strip
- 🔧 **WiFi 6E (6 GHz) pentest** (AC1200 MT7921AUN) — monitor mode + packet injection on 2.4/5/6 GHz tri-band via mt76 driver
- 🔧 **BT 5.2 recon** (AC1200 MT7921AUN) — Bluetooth 5.2 scanning/enum built into the WiFi card, supplements blescan
- 🔧 **BLE proximity tracking** — passive BLE beacon/tag detection (AirTag, Tile, SmartTag) with RSSI-based distance estimation + alert on unknown trackers following you
- 🔧 **WiFi client probe fingerprinting** — passive capture of probe requests to identify devices/people by their preferred network lists
- 🔧 **Bluetooth MITM / GATTack** (engagement-gated) — BLE man-in-the-middle testing via blepent
- 🔧 **threat correlation** — cross-reference WiFi/BLE/cellular anomalies into a unified threat picture
- 🔧 **rogue tool detection** — detect nearby Hak5 WiFi Pineapples, Pwnagotchi, ESP32 Marauder, and other offensive tools by their beacon/probe signatures. Passive, under COUNTER
- 🔧 **wireless keyboard/mouse sniffing** — 2.4 GHz non-WiFi traffic (MouseJack-style) via MT7921AUN monitor mode. Keystroke injection attack vector detection
- 🔧 **Amazon Sidewalk detection** — 900 MHz Ring/Alexa mesh traffic via SX1262. Novel IoT surveillance vector
- 🔧 **TPMS vehicle fingerprinting** — cross-reference TPMS sensor IDs with time + GNSS location = unique vehicle fingerprint without LPR. Feeds entity graph

## BENCH — conducted TX self-test
Absorbs: bench, loopback, txguard UI.
- ◐ self-test UI → wire bench/loopback engines behind txguard; show the gate state live

## MORE / SYSTEM (under a gear/overflow)
Absorbs: settings_ui, doctor, assistant (AI), sitrep (spoken), transcriber, fusion.
- ⬜ settings, device doctor, **AI assistant tied to live context**, spoken sitrep, transcriber,
  session logging
- 🔧 **Meshtastic mesh relay** — relay contacts/alerts over LoRa mesh to other PALISADE nodes

---

## Platform capabilities (the big three — what makes PALISADE a platform, not a tool)

### 🔧 SENTINEL — Autonomous RF Watch Mode
Drop the uConsole in a room, vehicle, or on a rooftop. SENTINEL runs unattended: continuous
baseline spectrum capture across all bands (RTL-SDR + SX1262), WiFi/BLE device inventory
(MT7921AUN), cellular tower mapping, LoRa traffic logging — and **diffs against itself over
time**. New transmitter → alert. Device gone → alert. Signal pattern changed → alert. Come back
hours or days later, pull the NVMe forensic RF timeline. This is what $50k+ TSCM monitoring
systems do. Lives under OVERWATCH as an autonomous mode.

### 🔧 ENTITY GRAPH — Multi-Radio Identity Resolution
Not contacts — **identities**. A WiFi probe, a BLE beacon, and a TPMS sensor all arrive at
14:32 and leave at 15:17 → that's one person in one car. When the same entity shows up at a
different site three days later, PALISADE sees it. Passive identity construction from
multi-radio correlation: WiFi MAC + BLE address + TPMS ID + APRS callsign + probe
fingerprint + GNSS co-movement → entity. Lives under ATLAS as an intelligence layer on top
of the contact map. Nobody in open source does this.

### 🔧 AUTOMATED ENGAGEMENT REPORTING
Auto-generate a professional PDF pentest/TSCM report directly from the evidence chain:
executive summary, methodology, GPS-tagged timestamped findings with screenshots, risk
ratings mapped to a framework (PRTF 108 techniques, MITRE ATT&CK wireless, or custom),
recommendations, raw data appendices. The engagement/opprofile/evidence system already
captures everything — this assembles and formats it. Turns PALISADE from "a tool I use
during the engagement" into "the thing that writes half my report." Lives under RECON ENGAGE.

---

## Operational modes (cross-callsign behaviors)

### 🔧 OPSEC Mode
One button: kills all TX, puts WiFi in pure monitor (no probes), stops BLE advertising,
disables LoRa TX, confirms "you are RF-dark" with a visual indicator on OPS. Warns if
anything on the device starts transmitting unexpectedly. Table stakes for professional use.

### 🔧 Vehicle Counter-Surveillance Mode
While driving: GNSS tracks your route while all radios passively monitor which BLE/WiFi/TPMS
IDs persist near you across turns and time. If the same BLE address or TPMS set has been
within range for 20 minutes through 5 turns — potential tail or tracker. Alert to OPS.
Uses entity graph for correlation.

### 🔧 Site Survey / Heatmap Mode
Walk a space with WiFi/BLE/RF survey running. GNSS tags every measurement. Generate a
signal-strength heatmap overlaid on ATLAS: WiFi coverage, BLE density, cellular strength,
spectrum power by band. Professional site survey deliverable, exportable as PDF/KML.

### 🔧 Triggered IQ Recording
PRISM watches the spectrum. When energy appears in a user-defined band or above a
threshold, auto-start IQ capture to NVMe. Catches burst transmitters, intermittent bugs,
and signals that only appear when you're not looking. Timestamps + GNSS tags each capture.

### 🔧 RF Environment Diffing
Take a full spectrum + device baseline of a room/site. Store to NVMe. Come back later,
run the same scan, diff it. Any new persistent signal = potential planted device. Compare
across visits ("this transmitter was also at the other location"). Feeds into SENTINEL
for continuous operation.

---

## New, cross-cutting features

### Wiring phase (UI + integration, no new algorithms)
- ✅ **Event bus** — typed contract, thread-safe, geo-native payloads. OPS + all panels consume.
- ✅ **Radio arbiter** — one-owner dongle model, RADIO BUSY states, seed for OVERWATCH director.
- ✅ **Theme** — violet light/dark per DESIGN.md, depth tokens, legible at 1280×480.
- ➕ **Session record + replay** — capture all event-bus traffic to NVMe SSD, play back field sessions.
- ➕ **Command palette (⌘K)** — jump to any callsign/freq/tail/decoder.
- ➕ **Watchlists** — watch a tail/callsign/freq/MAC/MMSI; alert on hit.
- ➕ **Export** — KML/CSV/GPX for contacts, tracks, logs.
- ➕ **ATAK/Cursor-on-Target export** — push contacts to TAK as CoT XML over multicast.
- ➕ **Meshtastic CoT bridge** (AIO V2 SX1262) — relay contacts/alerts to other PALISADE nodes or TAK devices over LoRa mesh when there's no internet.
- ➕ **Global health-aware load shedding** — thermal/battery + GPIO power gating (AIO V2) shuts heavy panels and radios individually.
- ➕ **Offline/air-gapped mode** — bundled assets, NVMe storage, no internet required for core functions.
- ➕ **GNSS position + heading overlay** (AIO V2 GNSS) — own-ship position on ATLAS map + bearing to contacts + moving map.
- ➕ **Time sync from GNSS** (AIO V2 GNSS + RTC) — accurate timestamps on all event-bus records even without NTP; RTC holds time across reboots.

### Engineering phase (new code / DSP / algorithms)
- 🔧 **DSP decoders** — CW, RTTY, digimodes, signal classifier (see BABEL above)
- 🔧 **rtl_433 ISM** — 433 MHz device decode (see BABEL above)
- 🔧 **ACARS/VDL2 + Iridium + DECT + LTE + GSM** — protocol decoders (see BABEL above)
- 🔧 **SatDump satellite imagery** — NOAA/Meteor/GOES (see BABEL above)
- 🔧 **Signal analysis** — SigDigger-level inspection in PRISM (see PRISM above)
- 🔧 **Cross-feed fusion** — multi-source track correlation (see ATLAS above)
- 🔧 **Pattern-of-life + anomaly detection** — contact time-series intelligence (see ATLAS above)
- 🔧 **Radio director** — autopilot dongle rotation (see OVERWATCH above)
- 🔧 **GPIO power manager** — individual hardware power gating via AIO V2 (see OVERWATCH above)
- 🔧 **Remote sensor nodes** — distributed multi-device SIGINT (see OVERWATCH above)
- 🔧 **LoRa packet capture + replay + Meshtastic analysis** — sub-GHz security testing via SX1262 (see FORGE above)
- 🔧 **Sub-GHz LoRa band scanner** — 860–960 MHz spectrum via SX1262 (see PRISM above)
- 🔧 **Meshtastic mesh relay + CoT bridge** — LoRa contact/alert relay (see cross-cutting above)
- 🔧 **WiFi 6E pentest + BT 5.2 recon** — tri-band monitor mode + injection via MT7921AUN (see RECON above)
- 🔧 **BLE proximity tracking + tracker detection** — AirTag/Tile/SmartTag detection + unknown tracker alerts (see RECON above)
- 🔧 **WiFi client probe fingerprinting** — passive device identification from probe requests (see RECON above)
- 🔧 **Nordic nRF BLE sniffer** — protocol-aware BLE packet capture (see FORGE above)
- 🔧 **Bluetooth MITM / GATTack** — BLE MITM testing, engagement-gated (see RECON above)
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

**Tier 1 — Platform-defining (changes what PALISADE is):**
1. **SENTINEL watch mode** — autonomous RF monitoring + baseline + diff + alert. Changes PALISADE from a tool to a sensor.
2. **Entity graph** — multi-radio identity resolution (WiFi+BLE+TPMS+APRS → entity). Changes it from a collector to an intelligence platform.
3. **Automated engagement reporting** — PDF from evidence chain. Changes it from a tool to a business.
4. **OPSEC mode** — one-button RF-dark. Table stakes for professional field use.

**Tier 2 — High field value (use your hardware, produce deliverables):**
5. DMR/P25/TETRA/NXDN digital trunked radio (SDRTrunk/OP25 — hear modern radio traffic)
6. rtl_433 ISM (easiest win, massive device coverage)
7. ACARS/VDL2 (aircraft data beyond ADS-B, mature tools)
7. Session record/replay to NVMe + ATAK/CoT export (field tool + team SA)
8. Vehicle counter-surveillance mode (BLE/WiFi/TPMS persistence tracking while driving)
9. Site survey / heatmap mode (GNSS-tagged RF measurements → heatmap deliverable)
10. RF environment diffing (baseline → revisit → diff → find planted devices)
11. Triggered IQ recording (auto-capture on spectrum anomaly to NVMe)
12. BLE tracker detection (AirTag/Tile/SmartTag counter-surveillance)
13. LoRa packet capture + Meshtastic analysis (AIO V2 SX1262 — IoT pentest)
14. WiFi 6E pentest + BT 5.2 recon (AC1200 tri-band + BT)
15. Rogue tool detection (Pineapple/Pwnagotchi/Marauder beacon signatures)
16. TPMS vehicle fingerprinting (TPMS IDs + GNSS = vehicle tracking without LPR)

**Tier 3 — Intelligence depth (algorithms + ML):**
18. OSINT enrichment layer (MAC/MMSI/tail/callsign/BSSID → identity from offline databases on NVMe)
19. Cross-feed fusion + pattern-of-life + temporal timeline (the differentiator)
18. AI signal classification (ML on known signals, flag unknowns)
19. Spectral fingerprinting (physical-layer device identification from IQ)
20. WiFi probe fingerprinting (passive device/person identification)
21. Amazon Sidewalk / proprietary IoT detection (900 MHz via SX1262)
22. Wireless keyboard/mouse sniffing (2.4 GHz MouseJack-style detection)

**Tier 4 — Protocol expansion + infrastructure:**
23. Meshtastic CoT bridge + mesh relay (off-grid team SA)
24. GPIO power manager (hardware load shedding)
25. GNSS own-ship position + time sync (moving map + timestamps)
26. Remote sensor nodes (distributed PALISADE)
27. LTE cell scanning + GSM (cellular gap)
28. Sub-GHz LoRa band scanner in PRISM
29. SigDigger-level signal analysis in PRISM
30. DSP decoders (CW/RTTY/digimodes)
31. Nordic nRF BLE sniffer + BLE MITM/GATTack
32. Iridium + DECT + SatDump (niche but powerful)
33. TEMPEST + Ubertooth (experimental/hardware-gated)
34. Inductive CAN bus sniffing via SDR (contactless vehicle data extraction)
35. Second SDR + radio director (simultaneous operation)
36. HackRF TX for BENCH (conducted self-test only)

## Guardrails
All tools come in. Active assessment gated behind engagement.py (authorization), opprofile.py
(operator identity), and txguard (TX safety on protected bands). Do not route around these
gates. No kernel/firewall/SSH changes; keep the `uconsole-suite` data path; legacy Tk app
stays as fallback until parity.
