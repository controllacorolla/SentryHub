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
Absorbs: overwatch, astro, radio (SDR lease/autopilot), scout.
- ⬜ sky dome (sun/moon/sat passes via astro), autopilot radio rotation, pass scheduling

## ATLAS — the map
Absorbs: sky_app (ADS-B), skyintel, mlat, balloons, aprs, dronewatch (Remote ID), kraken (DF),
tacmap, geo, tiles, fieldcomp (map/trip/almanac).
- ◐ map panel exists (dark/light/sat tiles, range rings) → wire real feeds
- ⬜ real ADS-B (sky_app), APRS stations, **drone Remote ID (dronewatch)**, DF bearings (kraken)
- ➕ **all contacts on ONE map** (aircraft + ships + APRS + drones + DF), selectable layers

## BABEL — universal decoder
Absorbs: ais, signals (ACARS/VDL2), pager (POCSAG/FLEX), rds, cw, rtty, digimodes, tpms,
zigbee, zwave, nwr, sstv/sstvdec, wxsat (LRPT/APT).
- ✅ ais, signals, pager, rds wired
- ⬜ TPMS, CW, RTTY, digimodes, Zigbee, Z-Wave, NWR
- ⬜ **406 MHz COSPAS-SARSAT** (new decoder), SSTV, weather-sat imagery (wxsat)
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
flipper, usbhid, rollcode, replay, sensors (I2C).
- ⬜ all of it — real serial/I2C/CAN/BLE consoles + tool integrations
- ➕ one colored multiplexed console with per-device tabs

## RECON — network + RF survey (authorized)
Absorbs: wifisurvey, wifipent, netpent, blescan, blepent, passaudit, scout, rffinger,
bugsweep, jammer (detector), imsicatch (detector).
- ⬜ wifi survey/audit, BLE scan, net scan, RF fingerprint, counter-surveillance (bugsweep,
  jam-detect, IMSI-catcher-detect)
- ➕ open-network / rogue-AP / tracker + fake-BTS alerts into the OPS alert strip

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
