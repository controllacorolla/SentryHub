# Developing Sentry in VS Code

The suite runs on the uConsole (CM5, Linux) but develops fine on Windows or macOS
in **demo mode** — every app has a `--demo` flag that feeds it synthetic data, so
you can work on the UI and logic without the radio hardware. Device-only features
(real RTL-SDR, I2C, GPIO, GPS) are stubbed or disabled off-device.

## Get it

```bash
git clone https://github.com/controllacorolla/SentryHub.git
cd SentryHub
code .
```

## Environment

Python 3.11+ with Tk. Create a virtualenv and install deps:

```bash
python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate
pip install -r requirements-dev.txt
```

tkinter note:
- Windows / macOS: bundled with the python.org installer.
- Debian/Ubuntu/uConsole: `sudo apt install python3-tk`.

Pick the `.venv` interpreter in VS Code (Ctrl/Cmd-Shift-P → "Python: Select
Interpreter"). The Python + Pylance extensions are all you need; debugpy ships with
the Python extension.

## Run / debug

`F5` uses the configs in `.vscode/launch.json`:
- **Hub (demo)** — the whole workstation with synthetic data.
- **Hub (demo, no splash)** — skips the boot splash for faster iteration.
- **Hub --doctor** — the dependency/health report.
- **Current app (demo)** — runs whatever app file is open, in demo mode. Good for
  working on one screen (e.g. open `hwlab.py`, hit F5).
- **Overwatch (demo, autopilot)** — the sky dome with the radio autopilot on.

## Test & lint

- Test Explorer is wired to pytest (`tests/`). Or run the **test (pytest)** task
  (Ctrl/Cmd-Shift-B).
- **lint (pyflakes)** task runs the same gate used before every release build.
  (`imported but unused` warnings are expected — those are runtime feature probes.)
- UI tests need a display. On a headless Linux box use `xvfb-run -a python -m
  pytest -q tests`; on Windows/macOS they run against the real display.

## Build the installer

The suite ships as one self-contained bash installer (head + base64 tarball of the
source + tail). Build it with the **build installer** task or:

```bash
bash build_installer.sh sentry-dev.sh
```

Copy that `.sh` to the uConsole and run it; it unpacks to
`~/.local/share/uconsole-suite/app`, installs desktop entries, and never touches
the kernel or upgrades packages.

## Layout & conventions

See `README.md` for the file map. Key points when editing:
- **One window, many workspaces.** Each app's `main()` runs both standalone and
  embedded in the Hub via `theme.workspace_class()`. Don't call Tk from worker
  threads — use a queue + `root.after` pump (every app follows this).
- **Pack bottom bars before the expanding content**, or Tk's `expand` eats their
  space and they clip (see the Field Kit apps for the pattern).
- **Receive-only.** No transmit path except Meshtastic text. Scout stays scoped to
  the local /24.
- Lint and test green before building: `python -m pyflakes *.py && python -m pytest
  -q tests`.
