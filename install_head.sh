#!/bin/bash
# PALISADE installer (uConsole): the PALISADE Qt hub (default), the legacy Tk hub and apps,
# Sky (ADS-B + airband + transcripts), FM Radio, Weather Sats, SSTV, APRS, Mesh, Field Status.
# Usage:  bash install-uconsole-suite.sh
set -e
# everything runs inside main(), called on the last line: a cut-off copy of this file
# is a syntax error and runs nothing at all
main() {
APP="$HOME/.local/share/uconsole-suite/app"
echo "=== Sentry installer (uConsole) ==="
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
for pkg in python3-tk python3-pil python3-pil.imagetk python3-pip pulseaudio-utils espeak-ng mpv iw redsea rtl-433 multimon-ng nmap iproute2 libnotify-bin wmctrl stress-ng python3-serial i2c-tools raspi-gpio bluez rtl-sdr; do
  dpkg -s "$pkg" >/dev/null 2>&1 || NEED=1
done
if [ "$NEED" = 1 ] && [ -z "${SKIP_APT_UPDATE:-}" ]; then
  sudo apt-get update -qq || true
elif [ "$NEED" = 1 ]; then
  echo "      (package lists not refreshed - see the warning above; missing packages may be skipped)"
fi
# one package at a time, so one unavailable or conflicting package can't block the rest
for pkg in python3-tk python3-pil python3-pil.imagetk python3-pip pulseaudio-utils espeak-ng mpv iw redsea rtl-433 multimon-ng nmap iproute2 libnotify-bin wmctrl stress-ng python3-serial i2c-tools raspi-gpio bluez rtl-sdr; do
  rc=0; safe_apt "$pkg" >/dev/null 2>&1 || rc=$?
  case $rc in 0) echo "      ok  $pkg";; 2) echo "      --  $pkg (not in your apt sources - optional)";; *) echo "      --  $pkg (skipped)";; esac
done
# (the H4M / HackRF is deliberately not installed or configured: this suite does not use it)

# --- Pentest + SIGINT toolkit (OPTIONAL) --------------------------------------------------------
# Every tool is gated behind an open, scoped engagement (engagement.py) before it can run; the
# installer only makes the binary available. Each is best-effort via safe_apt: a package that is
# missing from your apt sources, or that would remove a system package, is skipped ("--"), never
# fatal. Source-build / pip / go tools are NOT auto-built here (see the "[2c]" notes below).
# Verified against Debian trixie arm64 (2026-11-17). See FEATURE_MAP.md "Tool scope" for the matrix.
echo "[1b/8] Pentest + SIGINT tools (optional, engagement-gated)"
# nikto lives in non-free and is skipped automatically if that component is not enabled.
# tshark is installed non-interactively by preseeding wireshark-common: install-setuid=true lets the
# package give /usr/bin/dumpcap the capture capabilities (restricted to the 'wireshark' group), so
# tshark captures without full root. We add you to that group below (owner-authorized capabilities,
# 2026-11-18). tcpdump still covers pcap on its own.
echo "wireshark-common wireshark-common/install-setuid boolean true" | sudo debconf-set-selections 2>/dev/null || true
for pkg in \
  arp-scan tcpdump tshark nbtscan netdiscover masscan smbmap python3-impacket hydra bettercap \
  sqlmap whatweb gobuster ffuf nikto testssl.sh \
  aircrack-ng hcxdumptool hcxtools \
  gqrx-sdr inspectrum rtl-433 dsdcc \
  libnfc-bin libnfc-examples mfoc mfcuk \
  sigrok-cli pulseview flashrom openocd picocom minicom can-utils \
  libimage-exiftool-perl cewl hashcat python3-scapy ; do
  rc=0; safe_apt "$pkg" >/dev/null 2>&1 || rc=$?
  case $rc in 0) echo "      ok  $pkg";; 2) echo "      --  $pkg (not in your apt sources - optional)";; *) echo "      --  $pkg (skipped)";; esac
done

# --- [1c] Privileges for the passive capture / discovery tools + Responder (owner decision
# 2026-11-18, "Capabilities + Responder rule"). These are the ONLY privileged changes PALISADE
# makes, each narrow and named: file capabilities on specific capture binaries, one 'wireshark'
# group add, and a single NOPASSWD sudoers rule for exactly the Responder launcher. No firewall,
# kernel, SSH or full-system change. Every one is best-effort and skipped cleanly if it can't run.
echo "[1c/8] Capture/discovery capabilities + Responder launcher (owner-authorized)"
if command -v setcap >/dev/null 2>&1; then
  for b in tcpdump arp-scan netdiscover; do
    p="$(command -v "$b" 2>/dev/null || true)"
    if [ -n "$p" ]; then
      if sudo setcap cap_net_raw,cap_net_admin+eip "$p" 2>/dev/null; then
        echo "      ok  cap_net_raw on $b ($p) — runs from PALISADE without sudo"
      else
        echo "      --  could not set caps on $b — it will say 'requires root' until you do"
      fi
    fi
  done
else
  echo "      --  setcap not present (install libcap2-bin) — capture tools will need root"
fi
# add you to the 'wireshark' group so dumpcap/tshark may capture (takes effect after re-login)
if getent group wireshark >/dev/null 2>&1; then
  sudo usermod -aG wireshark "$USER" 2>/dev/null \
    && echo "      ok  added $USER to the 'wireshark' group (re-login to take effect)" \
    || echo "      --  could not add $USER to 'wireshark' (tshark capture may need root)"
fi
# Responder: clone it (source-only) and install a bare 'responder' launcher on PATH that escalates
# ONLY itself via a dedicated NOPASSWD sudoers rule, so the engagement gate still sees a plain
# program name (it refuses 'sudo ...' as argv[0]). Analyze mode is passive; poisoning is gated.
TOOLS="$HOME/.local/share/uconsole-suite/tools"
RESP_DIR="$TOOLS/Responder"
RESP_PY="$RESP_DIR/Responder.py"
if command -v git >/dev/null 2>&1; then
  mkdir -p "$TOOLS"
  if [ ! -f "$RESP_PY" ]; then
    git clone --depth 1 https://github.com/lgandx/Responder "$RESP_DIR" >/dev/null 2>&1 \
      && echo "      ok  cloned Responder to $RESP_DIR" \
      || echo "      --  could not clone Responder (no network?) — RESPONDER stays unavailable"
  else
    echo "      ok  Responder already present in $RESP_DIR"
  fi
fi
PY3="$(command -v python3 || echo /usr/bin/python3)"
if [ -f "$RESP_PY" ]; then
  mkdir -p "$HOME/.local/bin"
  cat > "$HOME/.local/bin/responder" <<SHIM
#!/bin/sh
# PALISADE Responder launcher: escalates only this script via the dedicated NOPASSWD sudoers rule.
exec sudo -n "$PY3" "$RESP_PY" "\$@"
SHIM
  chmod +x "$HOME/.local/bin/responder"
  echo "      ok  installed 'responder' launcher ($HOME/.local/bin/responder)"
  case ":$PATH:" in *":$HOME/.local/bin:"*) : ;; *)
    echo "      note: add \$HOME/.local/bin to PATH so PALISADE can find 'responder'";; esac
  # the single NOPASSWD rule, validated before it is installed (never write a broken sudoers file)
  RULE="$USER ALL=(root) NOPASSWD: $PY3 $RESP_PY *"
  TMP_SUDO="$(mktemp)"
  printf '%s\n' "$RULE" > "$TMP_SUDO"
  if sudo visudo -cf "$TMP_SUDO" >/dev/null 2>&1; then
    sudo install -m 0440 "$TMP_SUDO" /etc/sudoers.d/palisade-responder 2>/dev/null \
      && echo "      ok  sudoers rule for the Responder launcher (/etc/sudoers.d/palisade-responder)" \
      || echo "      --  could not install the Responder sudoers rule — run Responder as root yourself"
  else
    echo "      --  Responder sudoers rule failed validation — not installed"
  fi
  rm -f "$TMP_SUDO"
fi
# --------------------------------------------------------------------------------------------------
echo "[2c/8] Non-apt enumeration tools (best-effort; your engagement tools, engagement-gated)"
# The internal-pentest workhorses the coordinator asked to wire now: netexec + enum4linux-ng (pip)
# and nuclei (go). Best-effort and non-fatal — a failure just leaves that tool 'not installed' in
# the UI. The rest below stay as notes (install by hand if an engagement needs them).
for pp in netexec enum4linux-ng; do
  python3 -m pip install --user --break-system-packages --quiet "$pp" >/dev/null 2>&1 \
    && echo "      ok  $pp (pip)" || echo "      --  $pp (pip failed — install by hand if needed)"
done
if command -v go >/dev/null 2>&1; then
  GOBIN="$HOME/go/bin" go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest >/dev/null 2>&1 \
    && echo "      ok  nuclei (go; in ~/go/bin — add it to PATH)" \
    || echo "      --  nuclei (go install failed)"
else
  echo "      --  nuclei needs Go (apt install golang) — skipped"
fi
echo "      more by hand if needed:"
echo "      pip  : mitmproxy · urh · btlejack · bluing"
echo "             (python3 -m pip install --user --break-system-packages <name>)"
echo "      go   : rtlamr (github.com/bemasher/rtlamr)"
echo "      cargo: feroxbuster  (or grab the arm64 GitHub release binary)"
echo "      apt repo: kismet — add the official repo at kismetwireless.net/repos (trixie arm64)"
echo "      source : Responder (github.com/lgandx/Responder) · OP25 (github.com/boatbod/op25) ·"
echo "               dsd-fme (github.com/lwvmobile/dsd-fme) · Proxmark3 client (github.com/RfidResearchGroup/proxmark3)"
echo "      These are catalogued and engagement-gated; they just are not auto-built here."
# -----------------------------------------------------------------------------------------------

echo "[2/8] Python packages (PALISADE UI, Whisper, Skyfield, Meshtastic) - this can take a few minutes"
PIP="python3 -m pip install --user --break-system-packages --upgrade --quiet"
# S1: the Qt UI. Debian packages first (no compiler, matched to the system Qt); pip if apt
# has none. PALISADE does not start without PySide6 + pyqtgraph + numpy.
for pkg in python3-numpy python3-pyqtgraph python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtsvg; do
  rc=0; safe_apt "$pkg" >/dev/null 2>&1 || rc=$?
  case $rc in 0) echo "      ok  $pkg";; *) echo "      --  $pkg (not from apt; trying pip)";; esac
done
python3 -c 'import PySide6.QtWidgets' 2>/dev/null || $PIP PySide6 || \
  echo "      WARNING: PySide6 failed - PALISADE (the Qt hub) will not start; the legacy hub still works"
python3 -c 'import pyqtgraph' 2>/dev/null || $PIP pyqtgraph || \
  echo "      WARNING: pyqtgraph failed - PALISADE will not start"
python3 -c 'import numpy' 2>/dev/null || $PIP numpy || echo "      WARNING: numpy failed"
python3 -c 'import flask' 2>/dev/null || $PIP flask || echo "      note: flask not installed - Remote Mode needs it"
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
