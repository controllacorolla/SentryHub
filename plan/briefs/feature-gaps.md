# PALISADE — feature gaps vs. what was discussed (2026-11-17)

Trigger: Dalton, after the first uConsole install: "still missing an ass load of features we
discussed." Read-only audit. No code changed.

**Baseline audited:** `fix/cl8-ship` @ d8149b6 (the build on the device), which is `main` @ 1bc8ad1
plus CL8. Open branches are credited where they already fix something: PR #25 SCAN
(`claude/project-thread-08f65f`), `fix/ui-polish` (UIP), PR #26 N-op1 (`fix/n-op1-operator`).
Parked Phase-2 branches (`qt/phase2-opsec`, `qt/phase2-sentinel`, `qt/phase2-entity-graph`) hold
code that never merged.

**Where things were promised (Source column):**
FMAP = `FEATURE_MAP.md` (the "every Tk capability ports into Qt" mandate + Phase-2 list) ·
DN = `plan/briefs/device-notes.md` (tonight) · BL = `plan/BACKLOG.md` · DS = `plan/DESIGN.md` ·
BP = `PALISADE_BUILD_PLAN.md` · TR = `TRIAGE.md` · AUD = `plan/audit/AUDIT_INDEX.md` (CL6/CL7 scope) ·
Tk = a tile in the legacy `hub.py` that PALISADE was meant to absorb · CLAUDE = `CLAUDE.md`
("all tools come in … wire every module into the Qt UI").

**Status key:**
- **WORKS** — confirmed on the device by Dalton.
- **WIRED** — real backend in Qt; not yet confirmed on the device (may be STANDBY if a binary is missing).
- **ON BRANCH** — fixed on an open branch, not on the device yet.
- **STUB** — the screen exists but says NOT IMPLEMENTED / shows a static note / is demo-only in live, or **authorizes an action but never runs it**.
- **MISSING** — no code in the Qt app.
- **TK-ONLY** — works only in the legacy Tk app (still installed as "Sentry (legacy Tk hub)").
- **PARKED** — code exists on an unmerged branch.

**Owner column:** N-OP1 (PR #26) · UIP (`fix/ui-polish`, UI reorganisation) · SCAN (PR #25) ·
BANKS (planned next: preset banks, aviation then ham) · CL5-fu (decoder-liveness watchdog, CL8
follow-up) · CL6 / CL7 (v0.2) · **—** = nobody owns it yet.

> **The single biggest finding.** Every *active* tool in RECON and FORGE stops at the gate. The
> card calls `prepare()`, the gate authorizes, the UI shows a single-use ticket — and nothing runs.
> `executor.run/start` is called from exactly one Qt place (BENCH); RECON says "Execution of the
> argv is device-only; nothing is spawned here", FORGE says "the executor output pane is CL6".
> So for a pentester, wifipent, blepent, netpent, passaudit, Proxmark write/clone, USB-HID and
> replay are all **look-but-don't-run** today. That is CL6's "executor + output pane".

---

## OPS (1 · home)

| Feature | Source | Status | Owner |
|---|---|---|---|
| PPI scope hero, alert card, decode card, telemetry rail, honest STANDBY | FMAP, DS §5 | WIRED | — |
| Contacts on OPS without opening ATLAS first (feeds owned by the shell, not the page) | DN (OPS 22:30), AUD D6 | MISSING — OPS only plots what ATLAS publishes; empty in demo and live until ATLAS runs | CL6 (D6) |
| Basemap on the OPS scope (dark satellite) | DN | ON BRANCH | UIP |
| Collapsible side panels (map near full-screen) | DN | ON BRANCH (F key) | UIP |
| GPS satellites / own position on OPS | FMAP, DS §3 top bar | STUB — `_read_gps_sats()` returns None (TODO) | CL6 (GPS) |
| Battery / CPU temp | FMAP | WIRED (sysfs) | — |
| Power governor / load shedding (`powergov`, `field_status`) | FMAP, Tk "Power Governor", "Field Status" | TK-ONLY | — |
| Spoken sitrep from OPS | FMAP | MISSING on OPS (SITREP lives in SYSTEM, see below) | — |
| OPSEC one-button RF-dark indicator | FMAP Tier 1 #4 | PARKED (`qt/phase2-opsec`); strip slot was removed in CL8 | — |
| SENTINEL autonomous watch (baseline + diff + alert) | FMAP Tier 1 #1 | PARKED (`qt/phase2-sentinel`) | — |
| Remote sensor nodes / distributed PALISADE | FMAP | MISSING | — |
| Remote web dashboard + API (`headless.py`) | Tk "Remote Mode" | TK-ONLY | — |

## ATLAS (2 · map) — includes SKY DOME and PASSES (old OVERWATCH)

| Feature | Source | Status | Owner |
|---|---|---|---|
| ADS-B aircraft (readsb) | FMAP | WIRED (readsb running on device; antenna reported deaf earlier, BL) | — |
| APRS stations (144.39, SDR lease) | FMAP | WORKS (real station KF0HEG-9 in Dalton's 22:22 screenshot) | CL5-fu (liveness) |
| AIS vessels | FMAP | WIRED, but `rtl_ais` is not in the installer → likely STANDBY on device (unverified) | — |
| Remote-ID drones + operator (BLE) | FMAP | ON BRANCH (active-scan fallback; passive needs `bluetoothd --experimental`, Dalton's call) | SCAN |
| Remote-ID over Wi-Fi (NAN/beacon) | FMAP | STUB (TODO device-only, needs monitor NIC) | — |
| Balloons / radiosondes | FMAP | WIRED only as a reader of `sondes.json`, which the **Tk** Balloons app writes; nothing in Qt runs auto_rx | — |
| Direction finding (KrakenSDR) | FMAP | STUB — `df_contacts()` always returns [] (TODO) | — (hardware not owned) |
| MLAT feed | Tk "MLAT Feed" | TK-ONLY | — |
| Map pan / zoom / re-centre, north-up fix, bigger map | DN | ON BRANCH | UIP |
| Dark-satellite / light-satellite styles only; keyless imagery | DN | ON BRANCH | UIP |
| HOME from GPS automatically (typed HOME as fallback) | DN, AUD (CL6 GPS) | ON BRANCH as a manual "USE GPS for HOME" button; automatic + own-ship marker MISSING | UIP (manual) / CL6 |
| C2-style track symbology: heading icons, leaders, trails, data blocks, colour+shape by type (fixed-wing / rotor / drone / military), legend | DN 22:31–22:32 | MISSING (dots) | — |
| Layout: empty WATCHING box, stale CONTACT card after layer off, cramped chips, truncated errors | DN 22:22 | PARTLY ON BRANCH (bigger map); rest unowned | UIP / — |
| Offline tile cache for the field | FMAP, AUD (CL6 offline map) | PARTIAL — tiles cache on disk, no pre-download of an area | CL6 |
| Cross-feed fusion, pattern-of-life, temporal timeline, geofence alerts, OSINT enrichment (OUI / MMSI / FAA / FCC) | FMAP Tier 3 | MISSING | — |
| Entity graph (WiFi+BLE+TPMS+APRS → one identity) | FMAP Tier 1 #2 | PARKED (`qt/phase2-entity-graph`, engine + tests only) | — |
| SKY DOME (sun, moon, satellites) | FMAP | WIRED | — |
| PASSES | FMAP | WIRED, but Qt has no TLE update; shows "NO TLE" unless the Tk Weather Sats app fetched one (unverified on device) | — |
| Weather-satellite image capture (SatDump APT/LRPT), per-pass radio hand-off | FMAP, Tk "Weather Sats", "Pass Scheduler" | TK-ONLY (SatDump not installed either) | — |
| Ground map: track/breadcrumbs, almanac (`fieldcomp`), tactical overlay (`tacmap`) | Tk "Field computer", "Tactical Map", TR §A6 | TK-ONLY | — |

## PRISM (3 · spectrum)

| Feature | Source | Status | Owner |
|---|---|---|---|
| Spectrum + waterfall (rtl_power sweep), centre / span / gain, peak readout | FMAP | WIRED (rtl-sdr now installed by SCAN-4). Note: rtl_power is a slow sweep, not a real-time FFT | SCAN (installer) |
| Peak → PROWL FM | FMAP | WIRED (FM only; no AM/NFM hand-off) | — |
| Click-to-tune / demodulate a signal on the waterfall | FMAP | MISSING | — |
| Band presets (selectable per screen) | DN (preset banks) | MISSING | BANKS |
| Markers, max-hold, analyzer mode (`specan`) | TR §A1, Tk "Spectrum" | TK-ONLY | — |
| Noise-floor baseline / "new emitter" alerts | FMAP, Tk "Noise Floor" | MISSING in Qt (engine used only to parse) | CL7 (via SWEEP) |
| IQ record / replay (`iqtool`) | FMAP, Tk "IQ Recorder" | TK-ONLY | — |
| Modulation classifier (`classify`) | FMAP, Tk "Classifier" | TK-ONLY | — |
| Triggered IQ recording, RF environment diffing | FMAP op-modes | MISSING | — |
| SigDigger-style analysis, LoRa band scan (SX1262), TEMPEST, ML classification, spectral fingerprinting | FMAP Phase 2 | MISSING | — |
| SDR++ launcher | Tk "SDR++" | TK-ONLY | — |

## PROWL (4 · listen) — includes DECODE (old BABEL)

| Feature | Source | Status | Owner |
|---|---|---|---|
| SCAN across a bank, squelch, hold | FMAP | WIRED; discoverability of SCAN (Space) questioned | CL5-fu (NFM SCAN stall) |
| Full preset banks out of the box | DN 22:23 | PARTIAL — CB 40, FRS/GMRS 22, MURS 5, NOAA 7 are complete; Ham 2m/70cm simplex only; Airband 9 channels (guard + unicom); Marine 8; Railroad 8 | BANKS |
| Local airband (tower, ground, approach, ATIS, center) by HOME; full 118–137 MHz | DN 22:22 | MISSING | BANKS (aviation first) |
| Direct AM tune of any frequency | DN 22:22 | MISSING — FM tab is wbfm/nbfm only | BANKS |
| Public safety, ISM, ADS-B/APRS reference banks | DN 22:23 | MISSING | BANKS |
| Custom channels / memory banks from the UI | FMAP | MISSING in UI (only via settings file) | — |
| FM broadcast + RDS | FMAP | WIRED | — |
| NWR / SAME alerts | FMAP | WIRED (LIVE only with continuous decoder audio, owner rule) | — |
| CTCSS/DCS decode, true signal-seek, volume on the top bar | FMAP | MISSING | — |
| DMR / P25 / NXDN / TETRA trunked voice | FMAP Tier 2 #5 | MISSING | — |
| Airband voice + ATC transcripts | Tk "Sky", "Transcripts" | TK-ONLY | — |
| DECODE: POCSAG/FLEX, RDS, TPMS, SSTV | FMAP | WIRED (multimon-ng, redsea, rtl-433 installed) | CL5-fu (SSTV/stall) |
| DECODE: AIS, ACARS | FMAP | WIRED but binaries not installed (`rtl_ais`; `acarsdec` not in Debian) → STANDBY likely | — |
| DECODE: VDL2 | Tk "Signals" | MISSING in Qt | — |
| DECODE: CW / RTTY / digimodes (FT8, WSPR, PSK31) | FMAP, Tk | STUB — "practice only (no live decode)"; no demodulator exists | — |
| CW/RTTY/APRS/SSTV transmit | BL, BP §7 | MISSING (Tk TX tiles retired in CL8); needs ham callsign — **Dalton's decision** | — |
| 406 MHz COSPAS-SARSAT, Iridium, DECT, LTE/GSM cell scan, number-station DB | FMAP, BL | MISSING | — |
| Frequency DB lookup / ALLOCATION row | FMAP | WIRED | — |
| DX cluster spots | Tk "DX Cluster" | TK-ONLY | — |

## RECON (6 · survey)

| Feature | Source | Status | Owner |
|---|---|---|---|
| Wi-Fi scan | DN 22:11 | ON BRANCH — nmcli fallback (labelled ACTIVE); passive needs `setcap` on iw (Dalton's call) | SCAN |
| BLE scan | DN 22:12 | ON BRANCH — bleak / bluetoothctl, listen only | SCAN |
| Visible SCAN control on every survey surface | DN 22:15 | PARTIAL — Wi-Fi/BLE auto-scan on branch; no explicit SCAN button anywhere | SCAN / — |
| Engagement open (operator identity → ENGAGEMENT) | DN, handoff N-op1 | ON BRANCH (v0.1 blocker, audited MERGE) | N-OP1 |
| WIFIPENT deauth / PMKID / handshake | FMAP, CLAUDE | STUB — authorizes, never runs | CL6 (executor) |
| BLEPENT enum / characteristics (read/write omitted) | FMAP | STUB — authorizes, never runs | CL6 |
| NETPENT discover / portscan / services (nmap) | FMAP | STUB — authorizes, never runs; no results view | CL6 |
| PASSAUDIT convert / hashcat / aircrack | FMAP | STUB — authorizes, never runs | CL6 |
| SCOUT own-subnet site survey | FMAP, Tk "Scout" | STUB (static note); `scout.py` already has nmcli + nmap discovery | — (SCAN report recommends next) |
| RFFINGER RF fingerprinting | FMAP | STUB (static note) | — |
| Engagement report | FMAP Tier 1 #3 | PARTIAL — EXPORT REPORT writes **HTML** from the verified chain; PDF, screenshots, GPS tags, ATT&CK mapping MISSING | — |
| Screenshot / voice-note evidence | FMAP | MISSING | — |
| Monitor-mode Wi-Fi: probe-request fingerprinting, rogue-tool detection (Pineapple, Pwnagotchi, Marauder), Wi-Fi 6E, MouseJack | FMAP Tier 2/3 | MISSING | — |
| BLE tracker detection (AirTag / Tile / SmartTag) + "following you" alert | FMAP Tier 2 #12 | MISSING | — |
| BLE MITM / GATTack, nRF sniffer, Ubertooth | FMAP | MISSING | — |
| Zigbee, Z-Wave (gated) | FMAP, TR §C | MISSING in Qt (Tk tiles retired) | — |
| Dev terminal: BLE GATT console, MQTT, SSH | Tk "Dev terminal" | TK-ONLY | — |

## FORGE (7 · hardware)

| Feature | Source | Status | Owner |
|---|---|---|---|
| Serial console (USB-serial, Flipper-gated writes) | FMAP | WIRED | — |
| I2C scan / GPIO (`hwlab`) | FMAP, Tk "Hardware" | TK-ONLY | — |
| CAN monitor (SocketCAN candump, OBD/UDS decode) | FMAP, AUD CL6 | STUB — "CAN NOT IMPLEMENTED"; also no CAN hardware fitted | CL6 |
| CAN send (gated) | FMAP | STUB — authorizes, never runs | CL6 |
| Bus Lab: UART / JTAG / SPI-flash (`buslab`) | FMAP, Tk "Bus Lab" | MISSING in Qt (Tk tile gated/retired) | — |
| Proxmark read | FMAP | STUB — prints the command, "(reading… device-only)", never runs pm3 | CL6 |
| Proxmark write / clone / sim | FMAP | STUB — always refused live (no read-back path); parameterised ops have no UI | CL6 |
| Flipper bridge + NFC relay alerts | FMAP, Tk "Flipper" | PARTIAL — Flipper only identified on serial; bridge/relay MISSING | — |
| USB-HID inject | FMAP | STUB — authorizes, never runs | CL6 |
| Signal replay (txguard) | FMAP | STUB — ticket shown, never transmits | CL6 |
| Rolling-code RX analysis | FMAP, TR §B | STUB (static note, no capture loader) | — |
| SENSORS: rtl_433 ISM decode (weather, doorbells, keyfobs…) | FMAP Tier 2 #6, AUD CL6 | STUB — "SENSORS NOT IMPLEMENTED — rtl_433 is installed" | CL6 |
| Bias-tee toggle, LoRa capture/replay, Meshtastic packet analysis (SX1262), inductive CAN | FMAP Phase 2 | MISSING | — |

## SYSTEM (8 · settings) — SETTINGS, DOCTOR, SITREP, BENCH

| Feature | Source | Status | Owner |
|---|---|---|---|
| SETTINGS saves the operator the gates read | DN | ON BRANCH | N-OP1 |
| DOCTOR health checks | FMAP | WIRED; scan-path checks ON BRANCH | SCAN |
| SITREP text + spoken read-out (espeak-ng) | FMAP | WIRED (speech unverified on device) | — |
| BENCH loopback self-tests + conducted TX (executor, txguard) | FMAP | WIRED — the only Qt screen that actually runs a gated action | — |
| RADIOS panel: power on/off, device select | AUD §9 | STUB — lists devices, "arrive with CL6" | CL6 |
| Settings drawer, start/stop per tool, search/sort, export (KML/CSV/GPX) | AUD CL6, FMAP | MISSING | CL6 |
| Session record + replay, watchlists, ATAK/CoT export | FMAP cross-cutting | MISSING (session log is faults only) | — |
| Command palette | FMAP | WIRED (`/`) | — |
| Grouping: SYSTEM is a catch-all; ASSISTANT and MESH should leave it | DN 22:35–22:36 | MISSING | — |

## MESH (asked to be its own comms page)

| Feature | Source | Status | Owner |
|---|---|---|---|
| Own place in navigation (comms home, not under SYSTEM) | DN 22:36 | MISSING | — |
| Live Meshtastic node list + messages | FMAP | STUB — live says "MESH NOT IMPLEMENTED"; demo only. The Tk Mesh app works and `meshtastic` is installed | — |
| Send to the mesh | FMAP | STUB — "(NOT IMPLEMENTED — not transmitted)". It is a LoRa TX: the open audit question "LoRa bypass in txguard" must be settled first (Dalton's decision) | — |
| Mesh relay of contacts/alerts, Meshtastic CoT bridge | FMAP Tier 4 | MISSING | — |

## ASSISTANT (asked to be its own top-level page)

| Feature | Source | Status | Owner |
|---|---|---|---|
| Own entry in the left nav | DN 22:36 | MISSING | — |
| Answers about the live picture | FMAP | PARTIAL — three keyword answers (alerts / map / decodes) | — |
| Free-form questions via local LLM (Ollama) | FMAP, Tk "Assistant" | STUB — "Free-form questions: NOT IMPLEMENTED here" | — |
| Push-to-talk voice in / spoken answers | Tk "Assistant", DS | TK-ONLY | — |
| Offline RF analyst (`copilot`, qwen) merged in | TR §A2, Tk "RF Copilot" | TK-ONLY | — |

## SWEEP (5 · counter-surveillance) and other v0.2 items

SWEEP is hidden in v0.1 by owner decision (launch line 2026-11-16) and returns with CL7.

| Feature | Source | Status | Owner |
|---|---|---|---|
| Bug sweep (new emitters from a real PRISM sweep) | FMAP, AUD K1 | STUB — NOT IMPLEMENTED, page hidden | CL7 |
| Jamming detector | FMAP, AUD | STUB, hidden | CL7 |
| GNSS jam / spoof watch (gpsd C/N0) | FMAP, AUD K6 | STUB, hidden; gpsd runs on the device, so this is the cheapest to wire | CL7 |
| IMSI-catcher detect | FMAP, AUD K5 | STUB, hidden; needs a cellular modem (none fitted) | CL7 |
| Vehicle counter-surveillance mode, site-survey heatmap, TPMS vehicle fingerprinting | FMAP op-modes | MISSING | — |

## Cross-cutting UI (owner's 22:27–22:28 direction)

| Feature | Source | Status | Owner |
|---|---|---|---|
| Page nav as a vertical stack on the left; top strip = status only; one hierarchy page → sub-view → controls | DN 22:27–22:28 | MISSING (UIP fixed the overlapping key labels, not the layout) | — |
| Key-strip overlap, green SDR/ENG on states | DN | ON BRANCH | UIP |
| Boot/splash, logo lockup | BL, BP §7 | MISSING; logo is **Dalton's decision** | — |
| Decoder-liveness watchdog for every radio path (decoder starts then stalls) | CL8 RA-CL8f | MISSING (NWR has one) | CL5-fu |

---

## Top 10 gaps for a pentester in the field (ranked)

| # | Gap | Why it hurts in the field | Owner | v0.1 or v0.2 |
|---|---|---|---|---|
| 1 | Active tools authorize but never run (RECON wifipent/blepent/netpent/passaudit; FORGE Proxmark/HID/replay/CAN send) and there is no output pane | Nothing offensive actually executes; the suite is survey-only | CL6 | **v0.2 as planned.** Recommend pulling RECON NET (nmap) + WIFI execution into a v0.1.x cluster: the executor already exists and BENCH proves the pattern. Gate code → planner writes it, cold audit required |
| 2 | Can't open an engagement (operator never saved) | Blocks #1 and every gated card | N-OP1, PR #26 | **v0.1** — audited MERGE, waiting on Dalton's OK |
| 3 | Wi-Fi and BLE scans dead on the device | No situational survey at all | SCAN, PR #25 | **v0.1** — in audit (RA-SCAN) |
| 4 | Map unusable: no pan/zoom, rotated 90°, small, keyed satellite tiles | ATLAS/OPS are the core picture | UIP | **v0.1** — on branch, needs report + audit |
| 5 | Navigation: three competing zones, apps clumped, ASSISTANT/MESH buried | Slow to find tools one-handed | — (new cluster) | Left-nav move + ASSISTANT/MESH pages: **v0.1 stretch** (shell + strip, contained, but re-touches CL1's strip-width tests). Full IA pass: v0.2 |
| 6 | Thin frequency banks; no AM direct tune; no local airband/public safety | Can't just turn it on and listen | BANKS | **v0.1** — mostly data plus one AM mode; low risk |
| 7 | No live GPS: HOME manual, no own-ship, no GPS on OPS | Range/bearing wrong when you move; no tagged evidence | UIP (manual button) / CL6 | Manual button **v0.1** (on branch). Automatic gpsd → HOME is small and Dalton signalled he wants it: **v0.1 candidate**; own-ship + time sync v0.2 |
| 8 | Counter-surveillance hidden; no BLE tracker / rogue-tool detection | TSCM and "am I being followed" are a core field use | CL7 | **v0.2**; GNSS spoof (gpsd) could come early with #7 |
| 9 | OPS empty until ATLAS is opened; DF is a stub; dots instead of C2 symbology | The home screen lies by omission | CL6 (D6) / — | Shell-owned feeds **v0.2** (CL6); symbology v0.2, unowned |
| 10 | Decoder coverage: rtl_433 SENSORS and MESH are stubs, AIS/ACARS binaries not installed, no VDL2, no DMR/P25 | Large slices of the spectrum stay deaf | CL6 / — | SENSORS + MESH live read: **v0.2** (CL6; needs the liveness watchdog). AIS binary in installer: **v0.1** one-liner if `rtl-ais` is in Debian (unverified). DMR/P25: later |

**Before the v0.1 tag (realistic):** #2, #3, #4, #6, the manual half of #7, and the AIS installer
line. **Stretch for v0.1** if Dalton wants it before tagging: the left-nav move (#5), gpsd → HOME
(#7). **v0.2 (CL6/CL7):** #1 (unless pulled forward), #8, #9, #10, and every TK-ONLY row.

## Uncertainties (not verified on the device)
- AIS, ACARS, Balloons and PASSES status on the device is inferred from the installer and code, not
  seen. A 30-second check of each sub-tab on the uConsole would settle it.
- APRS "WORKS" is inferred from a real-looking callsign in Dalton's screenshot; the demo feed has no
  such name in the code.
- `rtl-ais` availability in Debian 13 apt was not checked from this container.
- Whether the parked Phase-2 branches (OPSEC, SENTINEL, entity graph) still apply cleanly on top of
  CL1–CL8 was not tested; assume rework.
- Decisions this list touches that are Dalton's: ham callsign (all ham TX), LoRa TX gate (mesh send),
  `setcap` on iw (passive Wi-Fi), `bluetoothd --experimental` (passive Remote-ID), logo, second SDR,
  the v0.1 launch line itself.
