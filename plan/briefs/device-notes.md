# Device notes — first hands-on test (fix/cl8-ship on uConsole CM5)

Owner's running notes from on-device testing, started 2026-11-17. Filed by screen.
Tags: **[bug]** broken/wrong behaviour · **[UI]** look/layout/wording · **[idea]** feature request.

Already logged elsewhere (not repeated here): top key-strip labels overlap and subtitles
misalign; CL8 device-check test failure.

## OPS

## ATLAS
- **[UI]** Maps are too small; give more of the 1280×720 to the map. (2026-11-16 22:02)
- **[UI]** Side menus/panels should be collapsible on any screen with a map, so the map can go near full-screen. (2026-11-16 22:02)

## PRISM

## PROWL

## RECON
- **[bug]** The passive Wi-Fi scan never works on the device. `wifisurvey.scan_argv` runs `iw dev wlan0 scan passive` as the normal user. On the uConsole (user `dragon`) this fails with `command failed: Operation not permitted (-1)`, because a scan needs CAP_NET_ADMIN. The installer doesn't grant it. Fix options for the planner: (a) fall back to NetworkManager (`nmcli -t dev wifi list`, unprivileged, but triggers an active scan, so label it non-passive); (b) a scoped capability or polkit rule for the scan, which is a system change and the owner must OK it. Also check that the UI shows "WIFI SCAN FAILED — Operation not permitted" and not an empty list. (2026-11-16 22:11)

## FORGE

## SYSTEM
- **[bug]** SETTINGS → SAVE SETTINGS does not set the operator profile, so ENGAGEMENT refuses with "no operator profile" after the owner saved his callsign. Cause: `palisade_qt/system.py` `_write_settings` saves `callsign` into `~/.config/uconsole-suite/palisade_ui.json`, but `engagement._profile_operator()` reads `opprofile.load(suite.settings)` = `operator.json`. The prefill reads `operator.json` too, so the field may look blank after re-open. Workaround given: write `name` into `operator.json` directly. Gate-adjacent (opprofile feeds engagement + TX), so it needs a regression test and an audit. Screenshot: Dalton's 22:05 capture. (2026-11-16 22:08)

## General
- **[UI]** Top status strip colours: keep TX `UNLOCKED` red (as now), but "on" states for the SDR and ENGAGEMENT slots should read green. Today SDR held = accent colour, ENGAGEMENT active = amber diamond (`palisade_qt/kit/topbar.py` ~L404–430). Note: amber for an active engagement was a deliberate RA-CL1 choice; changing it is a design decision. (2026-11-16 22:02)
- (Top-bar overlapping text: re-reported 2026-11-16 22:02; already logged elsewhere.)
