# Device notes — first hands-on test (fix/cl8-ship on uConsole CM5)

Owner's running notes from on-device testing, started 2026-11-17. Filed by screen.
Tags: **[bug]** broken/wrong behaviour · **[UI]** look/layout/wording · **[idea]** feature request.

Already logged elsewhere (not repeated here): top key-strip labels overlap and subtitles
misalign; CL8 device-check test failure.

## OPS

## ATLAS
- **[UI]** Maps are too small; give more of the 1280×720 to the map. (2026-11-16 22:02)
- **[UI]** Side menus/panels should be collapsible on any screen with a map, so the map can go near full-screen. (2026-11-16 22:02)

- **[bug]** SAT basemap shows only "API KEY REQUIRED" placeholder tiles. `palisade_qt/kit/tiles.py` uses Esri `server.arcgisonline.com/.../World_Imagery`, which now serves a key-required placeholder to keyless clients. The repo already uses a keyless alternative, USGS `basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}` (see `doctor.py:514`). That covers the US only, so it needs a world fallback or an honest "no imagery" state. Also purge the cached placeholder tiles under `~/.cache/palisade/tiles/satellite/`, or they will stick after the fix. Check too: the placeholder text renders upside-down/mirrored, so confirm the `canvas[::-1]` flip doesn't put real tiles upside down. Screenshot: Dalton 22:14. (2026-11-16 22:14)

- **[bug]** Can't pan or zoom the map. `kit/mappanel.py` sets `setMouseEnabled(False, False)` and ATLAS fixes `span_nm=80`, so there's no drag, no wheel/pinch and no zoom keys. Wanted: touch/mouse pan + zoom, plus keys (e.g. +/− like PRISM) and a re-centre-on-HOME control. Tile fetching must follow the view. (2026-11-16 22:17)
- **[bug]** The basemap shows the wrong place: Dalton set his HOME coords and the map shows "somewhere in a desert". Unconfirmed cause; candidates: (a) longitude entered without the minus sign (Denver area is about 39.7, -104.9; +104.9 lands in China/Mongolia desert); input validation accepts it silently; (b) `tiles.py` `canvas[::-1]` vertical flip, the same suspicion as the upside-down SAT placeholder text; (c) tile x/y vs. nm-extent mapping. Waiting on the exact coords he typed. (2026-11-16 22:17)

## PRISM

## PROWL

## RECON
- **[bug]** The passive Wi-Fi scan never works on the device. `wifisurvey.scan_argv` runs `iw dev wlan0 scan passive` as the normal user. On the uConsole (user `dragon`) this fails with `command failed: Operation not permitted (-1)`, because a scan needs CAP_NET_ADMIN. The installer doesn't grant it. Fix options for the planner: (a) fall back to NetworkManager (`nmcli -t dev wifi list`, unprivileged, but triggers an active scan, so label it non-passive); (b) a scoped capability or polkit rule for the scan, which is a system change and the owner must OK it. Also check that the UI shows "WIFI SCAN FAILED — Operation not permitted" and not an empty list. (2026-11-16 22:11)
- **[bug]** BLE scan doesn't work on the device either. The cause is different from the Wi-Fi scan: live BLE scanning was never wired. `BleScanWorker._scan_adverts()` returns None (audit E4), and the UI shows "BLE NOT IMPLEMENTED" or "BLE STANDBY — bleak is not installed". It needs a real bleak (BlueZ D-Bus, no root needed) passive scan, plus bleak in the installer if it's missing. Owner expects it for v0.1 testing. (2026-11-16 22:12)

## FORGE

## SYSTEM
- **[bug]** SETTINGS → SAVE SETTINGS does not set the operator profile, so ENGAGEMENT refuses with "no operator profile" after the owner saved his callsign. Cause: `palisade_qt/system.py` `_write_settings` saves `callsign` into `~/.config/uconsole-suite/palisade_ui.json`, but `engagement._profile_operator()` reads `opprofile.load(suite.settings)` = `operator.json`. The prefill reads `operator.json` too, so the field may look blank after re-open. Workaround given: write `name` into `operator.json` directly. Gate-adjacent (opprofile feeds engagement + TX), so it needs a regression test and an audit. Screenshot: Dalton's 22:05 capture. (2026-11-16 22:08)

## General
- **[idea]** Owner requirement: "everything needs to be scanable". Every survey surface (Wi-Fi, BLE, and the other RECON/PROWL/SWEEP feeds) must do a real live scan on the device out of the box. No stubs, no "NOT IMPLEMENTED", no permission dead-ends. Treat as a v0.1-readiness bar for passive tools. Owner clarified (22:15): "no scan networks freqs etc". He couldn't find an obvious SCAN action for (a) networks: Wi-Fi/BLE lists and LAN host discovery under an engagement; (b) frequencies: SDR band/frequency scanning. Each needs a visible SCAN control that does a real scan on the device. Check whether PROWL's scanner (Space = hold/resume) is discoverable enough. (2026-11-16 22:15)
- **[UI]** Top status strip colours: keep TX `UNLOCKED` red (as now), but "on" states for the SDR and ENGAGEMENT slots should read green. Today SDR held = accent colour, ENGAGEMENT active = amber diamond (`palisade_qt/kit/topbar.py` ~L404–430). Note: amber for an active engagement was a deliberate RA-CL1 choice; changing it is a design decision. (2026-11-16 22:02)
- (Top-bar overlapping text: re-reported 2026-11-16 22:02; already logged elsewhere.)
