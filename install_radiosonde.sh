#!/bin/bash
# One-time, opt-in setup for the Balloons app: builds radiosonde_auto_rx in the suite's
# data folder. No system service, no open ports, no upload: the Balloons app starts it on
# demand and writes a config that keeps the web UI and telemetry on 127.0.0.1.
set -e
DATA="$HOME/.local/share/uconsole-suite"
SRC="$DATA/radiosonde_auto_rx"
VENV="$DATA/radiosonde_venv"
if [ "$(id -u)" = "0" ]; then echo "Run as your normal user (not sudo)."; exit 1; fi
mkdir -p "$DATA"
echo "[1/4] build tools (apt: git build-essential python3-venv libsamplerate0-dev)"
PK="git build-essential python3-venv libsamplerate0-dev sox rtl-sdr"
if apt-get -s install --no-upgrade $PK 2>/dev/null | grep -E '^(Inst|Remv) (akrex-kernel|clockworkpi-|linux-image|linux-headers|raspberrypi-kernel|raspi-firmware|rpi-eeprom|initramfs)'; then
  echo "STOP: installing these would change the kernel or firmware (listed above). Nothing was installed."; exit 1
fi
sudo apt-get install -y --no-upgrade $PK >/dev/null
echo "[2/4] fetch radiosonde_auto_rx"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" pull --ff-only || echo "      (pull failed, keeping current copy)"
else
  git clone --depth 1 https://github.com/projecthorus/radiosonde_auto_rx.git "$SRC"
fi
echo "[3/4] build decoders"
( cd "$SRC/auto_rx" && bash ./build.sh )
echo "[4/4] python environment"
[ -x "$VENV/bin/python" ] || python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install -q -r "$SRC/auto_rx/requirements.txt"
echo "Done. Open Balloons from the hub and press Listen (or turn on Auto)."
