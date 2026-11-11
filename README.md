# uConsole Suite

A receive-only SDR and field-instrument suite for the ClockworkPi uConsole (CM5), built in
Python + Tkinter. Everything runs in one window (the **Hub**): each app is a *workspace* you
switch between, and they share one RTL-SDR dongle through a radio manager.

## Running from source

```bash
python3 hub.py              # the workstation (all apps)
python3 hub.py --demo       # synthetic data, no hardware needed
python3 sky_app.py --demo   # a single app standalone
```

Needs Python 3.11+ with `tkinter`. Optional per-app tools (rtl-sdr, multimon-ng, rtl_433,
pyserial, i2c-tools, bleak, paho-mqtt, skyfield, …) are detected at runtime — missing ones
just disable their feature. `python3 hub.py --doctor` reports what's present.

## Building the installer

The suite ships as one self-contained bash installer that unpacks the app, installs its
desktop entries, and sets up passwordless start/stop of the plane-map service only.

```bash
bash build_installer.sh uconsole-suite.sh    # head + base64(tar of source) + tail
```

## Layout

| Area | Files |
|------|-------|
| Shell / platform | `hub.py`, `suite.py`, `theme.py`, `settings_ui.py`, `tiles.py` |
| Aircraft | `sky_app.py`, `ops.py`, `overwatch.py`, `transcriber.py`, `signals.py`, `skyintel.py` |
| Listen | `fm.py`, `scanner.py`, `rf_explorer.py` |
| Weather & space | `wxsat.py`, `sensors.py`, `sstv.py`, `sstvdec.py`, `balloons.py` |
| Network & field | `mesh_dash.py`, `scout.py`, `field_status.py`, `aprs.py`, `aprs_app.py` |
| Field Kit | `hwlab.py` (serial/I2C/GPIO), `devterm.py` (BLE/MQTT/SSH) |
| Assistant | `assistant.py`, `sitrep.py` |
| Health / diagnostics | `doctor.py` |
| Installer | `install_head.sh`, `install_tail.sh`, `build_installer.sh`, `install_radiosonde.sh`, `harden.sh` |

## Tests

```bash
python3 -m pytest -q tests          # pure logic; UI tests need a display (xvfb-run -a)
```

## Design notes

- **One window, many workspaces.** `theme.workspace_class()` lets each app emulate the Tk-root
  calls it uses (`bind`, `after`, `title`, …) so the same `main()` runs both standalone and
  embedded in the Hub. `theme.EMBED` is the shell when embedded.
- **One radio, shared.** `suite.RtlLease` + a holder registry hand the dongle between apps and
  restart `readsb` (the plane map) when nothing else is listening. Overwatch's Autopilot rotates
  it automatically.
- **Receive-only.** No transmit path except Meshtastic text. Scout is scoped to the local /24.
- **Device health.** `suite.start_health()` polls temperature, under-voltage, and battery; apps
  shed load when the CM5 is hot or low.

Fonts under `fonts/` are SIL Open Font License (Atkinson Hyperlegible, IBM Plex).
