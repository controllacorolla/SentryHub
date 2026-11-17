# Device notes — first hands-on test (fix/cl8-ship on uConsole CM5)

Owner's running notes from on-device testing, started 2026-11-17. Filed by screen.
Tags: **[bug]** broken/wrong behaviour · **[UI]** look/layout/wording · **[idea]** feature request.

Already logged elsewhere (not repeated here): top key-strip labels overlap and subtitles
misalign; CL8 device-check test failure.

## OPS
- **[UI]** OPS home map should default to a dark satellite basemap (satellite imagery, darkened to fit the theme), not the current style. Depends on the SAT tile source fix under ATLAS (Esri now needs a key). (2026-11-16 22:19)

## ATLAS
- **[UI]** Maps are too small; give more of the 1280×720 to the map. (2026-11-16 22:02)
- **[UI]** Side menus/panels should be collapsible on any screen with a map, so the map can go near full-screen. (2026-11-16 22:02)

- **[bug]** SAT basemap shows only "API KEY REQUIRED" placeholder tiles. `palisade_qt/kit/tiles.py` uses Esri `server.arcgisonline.com/.../World_Imagery`, which now serves a key-required placeholder to keyless clients. The repo already uses a keyless alternative, USGS `basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}` (see `doctor.py:514`). That covers the US only, so it needs a world fallback or an honest "no imagery" state. Also purge the cached placeholder tiles under `~/.cache/palisade/tiles/satellite/`, or they will stick after the fix. Check too: the placeholder text renders upside-down/mirrored, so confirm the `canvas[::-1]` flip doesn't put real tiles upside down. Screenshot: Dalton 22:14. Update 22:20: real imagery loaded at the current view, so the placeholder may be intermittent, zoom-dependent or a cached placeholder tile. Still move off the keyless Esri endpoint. (2026-11-16 22:14)

- **[bug]** Can't pan or zoom the map. `kit/mappanel.py` sets `setMouseEnabled(False, False)` and ATLAS fixes `span_nm=80`, so there's no drag, no wheel/pinch and no zoom keys. Wanted: touch/mouse pan + zoom, plus keys (e.g. +/− like PRISM) and a re-centre-on-HOME control. Tile fetching must follow the view. (2026-11-16 22:17)
- **[bug]** The basemap is rotated 90°. With HOME correct (39.6261, -104.968), the Front Range, which runs N–S to the west of Denver, draws as an E–W band along the SOUTH of the map (Dalton's 22:20 screenshot). The upside-down "API KEY REQUIRED" text was the same bug. Likely cause: `kit/mappanel.py` `pg.ImageItem().setImage(arr)` assumes pyqtgraph's row-major image order, but `imageAxisOrder="row-major"` is only set globally inside `kit/scope.py` (`pg.setConfigOptions` in the Scope constructor). If no Scope widget exists yet (ATLAS opened before PRISM), pyqtgraph uses its default col-major order, so the array is transposed, and with `tiles.py` `canvas[::-1]` that is a 90° rotation. So the map orientation depends on page-open order. Fix: set `axisOrder="row-major"` on the map's ImageItem (or set the config once at app start), plus a regression test that renders a known asymmetric tile. Earlier "desert" report was likely this plus a first-entry issue; coords he now uses are correct. (2026-11-16 22:17, updated 22:20)

- **[idea]** Location should be automatic. Today HOME comes only from SYSTEM › SETTINGS; `eventbus.py:37` says GPS isn't wired yet (planned CL6, v0.2). Owner wants it automatic: GPS (gpsd) when there's a fix, with the typed HOME as fallback. Possibly a coarse network/Wi-Fi fix when NET is on, labelled as approximate. Owner signal to consider pulling GPS→HOME into v0.1. (2026-11-16 22:18)

- **[UI]** Map style choices should be just two: **dark satellite** and **light satellite** (imagery with a dark or light treatment), replacing today's dark / light / SAT set. Applies to ATLAS and the OPS home map. (2026-11-16 22:21)

- **[bug]** A BLE passive scan reports needing "bluez" (owner's words, 22:21; exact text and screen not yet confirmed, probably ATLAS › DRONES Remote-ID). `atlas.py` `scanner_kwargs` already passes `bluez.or_patterns`; on Linux, bleak's passive mode uses BlueZ's AdvertisementMonitor API, which on many BlueZ builds only exists when `bluetoothd` runs with experimental features (`-E`). Turning that on is a system change, so it's the owner's call. Fix options: detect the missing monitor API and say so plainly, or fall back to an active scan, labelled as active, under the passive-only rule (owner decision). Asked owner for the exact message plus `bluetoothctl --version`. (2026-11-16 22:21)

- **[UI]** "Layout is weird" (owner, 22:22 screenshot; specifics pending). Visible in the shot: the right column is a large mostly-empty "WATCHING — no contacts" box over a CONTACT card that still shows an APRS contact (KF0HEG-9, LOST) after the APRS layer was toggled off; layer chips sit in two cramped rows; the left rail (MAP/SKY DOME/PASSES) wastes width next to a too-small map; the Remote-ID error in the bottom status line is truncated ("…requires BlueZ >…"). (2026-11-16 22:22)
- **[bug]** Confirmed Remote-ID BLE failure text: "Remote-ID BLE scan failed: passive scanning on Linux requires BlueZ >…" (cut off). This is bleak's version/experimental check. Debian 13's BlueZ is new enough, so likely `bluetoothd` lacks `--experimental`. See the earlier BLE entry. Also the error sets MODE to the red ▲ LIVE fault state. (2026-11-16 22:22)

## PRISM

## PROWL
- **[idea]** Aviation voice: it exists but is thin. PROWL › SCAN › bank "Airband" (AM) holds only 121.5 guard and the 122.7–123.075 unicom/multicom channels. No tower, ground, approach/departure, ATIS or center for the operator's area. Wanted: local ATC frequencies preloaded (e.g. from FAA data by HOME), plus a direct AM tune for any airband frequency. (2026-11-16 22:22)
- **[idea]** "All frequencies need to be pre-programmed": ship complete preset banks out of the box, not starter lists. Current banks (`scanner.BANKS`): CB, GMRS/FRS, MURS, Ham 2m, Ham 70cm, Airband, Marine VHF, NOAA Wx, Railroad, each partial. Wanted: full channel plans per service, local airband/public-safety by HOME, so nothing has to be typed in. Target scope for a future preset-bank cluster (PROWL/PRISM, selectable per screen): aviation voice AM 118–137 MHz, NWR, FRS/GMRS, MURS, marine, public safety, ADS-B, APRS, ISM. Owner's band priority: pending. (2026-11-16 22:23)

## RECON
- **[bug]** The passive Wi-Fi scan never works on the device. `wifisurvey.scan_argv` runs `iw dev wlan0 scan passive` as the normal user. On the uConsole (user `dragon`) this fails with `command failed: Operation not permitted (-1)`, because a scan needs CAP_NET_ADMIN. The installer doesn't grant it. Fix options for the planner: (a) fall back to NetworkManager (`nmcli -t dev wifi list`, unprivileged, but triggers an active scan, so label it non-passive); (b) a scoped capability or polkit rule for the scan, which is a system change and the owner must OK it. Also check that the UI shows "WIFI SCAN FAILED — Operation not permitted" and not an empty list. (2026-11-16 22:11)
- **[bug]** BLE scan doesn't work on the device either. The cause is different from the Wi-Fi scan: live BLE scanning was never wired. `BleScanWorker._scan_adverts()` returns None (audit E4), and the UI shows "BLE NOT IMPLEMENTED" or "BLE STANDBY — bleak is not installed". It needs a real bleak (BlueZ D-Bus, no root needed) passive scan, plus bleak in the installer if it's missing. Owner expects it for v0.1 testing. (2026-11-16 22:12)

## FORGE

## SYSTEM
- **[UI]** SETTINGS reports "persisted: operator" after SAVE, but the operator never reaches the operator profile the gates read (see the bug below). The message is misleading until that bug is fixed. (2026-11-16 22:19)
- **[bug]** The SYSTEM status line reads "MESH NOT IMPLEMENTED — the Meshtastic link is not wired into this screen". Another stub; falls under the owner's "everything needs to be scanable/working" bar. (2026-11-16 22:19)
- **[bug]** SETTINGS → SAVE SETTINGS does not set the operator profile, so ENGAGEMENT refuses with "no operator profile" after the owner saved his callsign. Cause: `palisade_qt/system.py` `_write_settings` saves `callsign` into `~/.config/uconsole-suite/palisade_ui.json`, but `engagement._profile_operator()` reads `opprofile.load(suite.settings)` = `operator.json`. The prefill reads `operator.json` too, so the field may look blank after re-open. Workaround given: write `name` into `operator.json` directly. Gate-adjacent (opprofile feeds engagement + TX), so it needs a regression test and an audit. Screenshot: Dalton's 22:05 capture. (2026-11-16 22:08)

## General
- **[idea]** Owner requirement: "everything needs to be scanable". Every survey surface (Wi-Fi, BLE, and the other RECON/PROWL/SWEEP feeds) must do a real live scan on the device out of the box. No stubs, no "NOT IMPLEMENTED", no permission dead-ends. Treat as a v0.1-readiness bar for passive tools. Owner clarified (22:15): "no scan networks freqs etc". He couldn't find an obvious SCAN action for (a) networks: Wi-Fi/BLE lists and LAN host discovery under an engagement; (b) frequencies: SDR band/frequency scanning. Each needs a visible SCAN control that does a real scan on the device. Check whether PROWL's scanner (Space = hold/resume) is discoverable enough. (2026-11-16 22:15)
- **[UI]** Top status strip colours: keep TX `UNLOCKED` red (as now), but "on" states for the SDR and ENGAGEMENT slots should read green. Today SDR held = accent colour, ENGAGEMENT active = amber diamond (`palisade_qt/kit/topbar.py` ~L404–430). Note: amber for an active engagement was a deliberate RA-CL1 choice; changing it is a design decision. (2026-11-16 22:02)
- (Top-bar overlapping text: re-reported 2026-11-16 22:02; already logged elsewhere.)
