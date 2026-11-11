#!/bin/bash
# uConsole Suite installer: Radio Hub, Sky (ADS-B + airband + transcripts), FM Radio,
# Weather Sats, SSTV, Balloons, APRS, Mesh, Field Status, Assistant.
# Usage:  bash install-uconsole-suite.sh
set -e
# everything runs inside main(), called on the last line: a cut-off copy of this file
# is a syntax error and runs nothing at all
main() {
APP="$HOME/.local/share/uconsole-suite/app"
echo "=== uConsole Suite installer ==="
if [ "$(id -u)" = "0" ]; then echo "Run as your normal user (not sudo)."; exit 1; fi

safe_apt() {   # install only packages that exist, and only if nothing gets removed
  local want=() missing_src=0
  for p in "$@"; do
    dpkg -s "$p" >/dev/null 2>&1 && continue
    apt-cache show "$p" >/dev/null 2>&1 && want+=("$p") || missing_src=1
  done
  [ ${#want[@]} -eq 0 ] && { [ "$missing_src" = 1 ] && return 2; return 0; }
  local sim remv kern
  sim=$(apt-get -s install --no-upgrade "${want[@]}" 2>/dev/null || true)
  remv=$(echo "$sim" | grep '^Remv' || true)
  # never let a suite install drag in a kernel, firmware or bootloader change
  kern=$(echo "$sim" | grep -E '^(Inst|Remv) (akrex-kernel|clockworkpi-|linux-image|linux-headers|raspberrypi-kernel|raspi-firmware|rpi-eeprom|initramfs)' || true)
  if [ -n "$remv" ] || [ -n "$kern" ]; then
    echo "      SKIPPING ${want[*]}: apt would change system packages:"; echo "$remv$kern"; return 1
  fi
  sudo apt-get install -y --no-upgrade "${want[@]}"
}

echo "[0/8] Safety check: system updates"
KPK=$(dpkg-query -W -f '${Package} ${Status}\n' akrex-kernel clockworkpi-kernel 2>/dev/null | awk '/install ok installed/{print $1}')
AUTO=""
for u in unattended-upgrades apt-daily-upgrade.timer; do
  [ "$(systemctl is-enabled $u 2>/dev/null)" = "enabled" ] && AUTO="$AUTO $u"
done
UNHELD=""
for k in $KPK; do apt-mark showhold 2>/dev/null | grep -qx "$k" || UNHELD="$UNHELD $k"; done
if [ -n "$AUTO" ] || [ -n "$UNHELD" ]; then
  echo "      WARNING: this uConsole can update its own kernel without asking."
  [ -n "$AUTO" ]   && echo "        automatic updates are on:$AUTO"
  [ -n "$UNHELD" ] && echo "        kernel not held:$UNHELD"
  echo "      A kernel update has left uConsoles with a black screen or unable to start."
  echo "      To prevent it:"
  [ -n "$UNHELD" ] && echo "        sudo apt-mark hold$UNHELD"
  [ -n "$AUTO" ]   && echo "        sudo systemctl disable --now$AUTO"
  echo "      (This installer changes neither; it will not refresh package lists until they are safe.)"
  SKIP_APT_UPDATE=1
else
  echo "      ok  kernel held, automatic updates off"
fi

echo "[1/8] System packages"
NEED=0
for pkg in python3-tk python3-pil python3-pil.imagetk python3-pip pulseaudio-utils espeak-ng mpv iw redsea rtl-433 multimon-ng nmap iproute2 libnotify-bin wmctrl stress-ng python3-serial i2c-tools raspi-gpio bluez; do
  dpkg -s "$pkg" >/dev/null 2>&1 || NEED=1
done
if [ "$NEED" = 1 ] && [ -z "${SKIP_APT_UPDATE:-}" ]; then
  sudo apt-get update -qq || true
elif [ "$NEED" = 1 ]; then
  echo "      (package lists not refreshed - see the warning above; missing packages may be skipped)"
fi
# one package at a time, so one unavailable or conflicting package can't block the rest
for pkg in python3-tk python3-pil python3-pil.imagetk python3-pip pulseaudio-utils espeak-ng mpv iw redsea rtl-433 multimon-ng nmap iproute2 libnotify-bin wmctrl stress-ng python3-serial i2c-tools raspi-gpio bluez; do
  rc=0; safe_apt "$pkg" >/dev/null 2>&1 || rc=$?
  case $rc in 0) echo "      ok  $pkg";; 2) echo "      --  $pkg (not in your apt sources - optional)";; *) echo "      --  $pkg (skipped)";; esac
done
# (the H4M / HackRF is deliberately not installed or configured: this suite does not use it)

echo "[2/8] Python packages (Whisper, Skyfield, Meshtastic) - this can take a few minutes"
PIP="python3 -m pip install --user --break-system-packages --upgrade --quiet"
$PIP faster-whisper || echo "      WARNING: faster-whisper failed - transcripts/assistant voice won't work"
$PIP skyfield || echo "      WARNING: skyfield failed - weather-sat predictions won't work"
$PIP meshtastic || echo "      WARNING: meshtastic failed - Mesh app won't connect"
$PIP pyserial || echo "      note: pyserial not installed - the Hardware serial terminal needs it (python3-serial also works)"
$PIP bleak || echo "      note: bleak not installed - the Dev terminal BLE scanner needs it"
$PIP paho-mqtt || echo "      note: paho-mqtt not installed - the Dev terminal MQTT dashboard needs it"

echo "[3/8] Installing apps to $APP"
# unpack beside the working copy and only swap it in once it is complete and loads, so a
# damaged or half-downloaded installer can never leave a broken app behind
STAGE="$APP.new"; BAD=0
DONE=0
finish() {   # a cut-off installer ends inside the payload and never reaches the end
  if [ "$DONE" != 1 ] && [ -d "$STAGE" ]; then
    rm -rf "$STAGE"
    echo "      STOP: the installer file is incomplete (cut-off download or copy)."
    echo "      Nothing was changed - your installed version is untouched. Copy the file again."
    exit 1
  fi
}
trap finish EXIT
rm -rf "$STAGE"; mkdir -p "$STAGE"
base64 -d <<'B64EOF' | tar xz -C "$STAGE" || BAD=1
