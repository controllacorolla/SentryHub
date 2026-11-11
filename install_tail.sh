B64EOF
if [ "$BAD" = 0 ] && [ -f "$STAGE/hub.py" ] && python3 - "$STAGE" <<'PYCHK'
import glob, py_compile, sys
for f in glob.glob(sys.argv[1] + "/*.py"):
    py_compile.compile(f, doraise=True)
PYCHK
then
  rm -rf "$APP.prev"
  [ -d "$APP" ] && mv "$APP" "$APP.prev"
  mv "$STAGE" "$APP"
  [ -d "$APP.prev" ] && echo "      previous version kept in $APP.prev"
else
  rm -rf "$STAGE"
  echo "      STOP: the installer file is damaged (incomplete download or copy)."
  echo "      Nothing was changed - your installed version is untouched. Copy the file again."
  exit 1
fi
chmod +x "$APP"/*.py
[ -f "$APP/harden.sh" ] && chmod +x "$APP/harden.sh"
[ -f "$APP/run_tests.sh" ] && chmod +x "$APP/run_tests.sh"
[ -f "$APP/install_radiosonde.sh" ] && chmod +x "$APP/install_radiosonde.sh"
mkdir -p "$HOME/.local/share/fonts/uconsole-suite"
cp "$APP"/fonts/* "$HOME/.local/share/fonts/uconsole-suite/"
fc-cache -f "$HOME/.local/share/fonts" >/dev/null 2>&1 || true
echo "      Fonts installed: Atkinson Hyperlegible + IBM Plex (SIL Open Font License)"

echo "[4/8] Commands: hub, sky"
mkdir -p "$HOME/.local/bin"
for pair in "hub:hub.py" "sky:sky_app.py"; do
  name=${pair%%:*}; file=${pair#*:}
  printf '#!/bin/bash\nexec python3 "%s/%s" "$@"\n' "$APP" "$file" > "$HOME/.local/bin/$name"
  chmod +x "$HOME/.local/bin/$name"
  sudo ln -sf "$HOME/.local/bin/$name" "/usr/local/bin/$name"
done

echo "[5/8] Menu entries"
D="$HOME/.local/share/applications"; mkdir -p "$D"
mk() { # id name comment script icon
  cat > "$D/uc-$1.desktop" <<EOF2
[Desktop Entry]
Type=Application
Name=$2
Comment=$3
Exec=python3 $APP/$4
Icon=$5
Terminal=false
Categories=AudioVideo;HamRadio;
EOF2
}
mk hub "Sentry" "uConsole receive-only signals + field terminal" hub.py network-wireless
mk sky "Sky" "Live ADS-B map + airband voice" sky_app.py applications-science
mk fm "FM Radio" "FM + NOAA Weather Radio" fm.py audio-radio
mk wx "Weather Sats" "Meteor LRPT passes + capture" wxsat.py weather-few-clouds
mk mesh "Mesh" "Meshtastic dashboard" mesh_dash.py mail-send-receive
mk field "Field Status" "GPS, battery, thermals" field_status.py utilities-system-monitor
mk ai "Assistant" "Push-to-talk local AI" assistant.py audio-input-microphone
mk tx "Transcripts" "Airband transcripts" "transcriber.py --view" accessories-text-editor
# the older single-app entries now point at the suite copy
[ -f "$D/sky.desktop" ] && sed -i "s#^Exec=.*#Exec=$HOME/.local/bin/sky#" "$D/sky.desktop"
update-desktop-database "$D" 2>/dev/null || true

echo "[6/8] Passwordless start/stop of the plane-map service (only that)"
SVCS=""
for s in readsb dump1090-fa; do
  systemctl list-unit-files "$s.service" 2>/dev/null | grep -q "^$s.service" && SVCS="$SVCS $s"
done
if [ -n "$SVCS" ]; then
  CMDS=""
  for p in /usr/bin/systemctl /bin/systemctl; do
    [ -x "$p" ] || continue
    for s in $SVCS; do for a in start stop; do CMDS="$CMDS, $p $a $s"; done; done
  done
  TMP=$(mktemp); echo "$USER ALL=(root) NOPASSWD: ${CMDS#, }" > "$TMP"
  if sudo visudo -cf "$TMP" >/dev/null; then
    sudo install -m 0440 -o root -g root "$TMP" /etc/sudoers.d/uconsole-suite
    echo "      ok:$SVCS"
  fi
  rm -f "$TMP"
fi
id -nG "$USER" | grep -qw plugdev || sudo usermod -aG plugdev "$USER" || true

echo "[6b] Plane map on the built-in SDR (the H4M is not used by this suite)"
if [ -f /etc/default/readsb ] && command -v readsb >/dev/null; then
  if grep -q 'RECEIVER_OPTIONS=.*hackrf' /etc/default/readsb; then
    # an earlier version of this installer pointed readsb at the H4M: undo that
    sudo cp /etc/default/readsb /etc/default/readsb.h4m-$(date +%Y%m%d-%H%M%S)
    if [ -f /etc/default/readsb.before-uconsole-suite ] && \
       ! grep -q 'RECEIVER_OPTIONS=.*hackrf' /etc/default/readsb.before-uconsole-suite; then
      sudo cp /etc/default/readsb.before-uconsole-suite /etc/default/readsb
      echo "      ok  readsb restored to its original built-in SDR settings"
    else
      sudo sed -i 's|^RECEIVER_OPTIONS=.*|RECEIVER_OPTIONS="--device-type rtlsdr --device 0 --ppm 0"|' /etc/default/readsb
      echo "      ok  readsb set to the built-in SDR"
    fi
    sudo systemctl restart readsb || true
    echo "          (the H4M config was saved next to it as readsb.h4m-<date>)"
  else
    echo "      ok  readsb already on the built-in SDR"
  fi
  echo "      note: one radio - the plane map pauses while another app is listening."
else
  echo "      --  readsb not installed; skipped"
fi
ok() { if eval "$2" >/dev/null 2>&1; then echo "  OK  $1"; else echo "  --  $1  -> $3"; fi; }
ok "rtl_airband" "command -v rtl_airband" "install rtl_airband (Sky needs it)"
ok "plane map on the built-in SDR" "! grep -q 'RECEIVER_OPTIONS=.*hackrf' /etc/default/readsb" "readsb is still pointed at the H4M"
ok "rtl_fm (FM Radio)" "command -v rtl_fm" "sudo apt install rtl-sdr"
ok "redsea (FM station names)" "command -v redsea" "optional: sudo apt install redsea"
ok "rtl_433 (Signals: sensors)" "command -v rtl_433" "sudo apt install rtl-433"
ok "acarsdec (Signals: ACARS)" "command -v acarsdec" "optional: build from github.com/TLeconte/acarsdec"
ok "rtl_power (Scout: spectrum)" "command -v rtl_power" "sudo apt install rtl-sdr"
ok "nmap (Scout: network scan)" "command -v nmap" "sudo apt install nmap"
ok "nmcli (Scout: Wi-Fi scan)" "command -v nmcli" "optional: sudo apt install network-manager"
ok "SatDump (Weather Sats)" "command -v satdump" "install SatDump (DragonOS usually ships it)"
ok "SDR++ (Hub tile)" "command -v sdrpp" "optional"
ok "meshtasticd running (Mesh)" "systemctl is-active --quiet meshtasticd" "sudo systemctl enable --now meshtasticd"
ok "gpsd running (Field Status, Weather Sats location)" "systemctl is-active --quiet gpsd" "see note below"
ok "Ollama reachable locally (Assistant)" "curl -s -m 2 http://127.0.0.1:11434/api/tags" "optional - Assistant can use your desktop instead"
ok "faster-whisper" "python3 -c 'import faster_whisper'" "pip install failed"
ok "skyfield" "python3 -c 'import skyfield'" "pip install failed"
ok "meshtastic" "python3 -c 'import meshtastic'" "pip install failed"
echo
if pgrep -f "$APP/hub.py" >/dev/null 2>&1 || pgrep -f "bin/hub" >/dev/null 2>&1; then
  echo "The Hub is open: close it (Ctrl+Q) and start it again to use the new version."
fi
echo "Open Sentry from the menu, or run:  hub"
echo "Check every connection (radios, services, servers):  hub --doctor"
echo "Security review of your own device:  hub --security"
echo "Spoken situation report:  hub --sitrep"
echo "Overwatch (in the Hub): the sky dome, with Autopilot sharing the one radio between apps."
echo "Hardware (in the Hub): serial terminal, I2C/SPI bus scan, and GPIO - the bench instruments."
echo "Field computer (in the Hub): offline moving map, GPX track recording, and a sun/moon/ISS almanac."
echo "Every app has a Settings button - no JSON editing needed."
echo
echo "Notes:"
echo " - Assistant: Settings -> Ollama hosts: set the first URL to your desktop's Tailscale name, e.g."
echo "   http://my-desktop:11434. On the desktop, bind Ollama to its Tailscale IP only"
echo "   (OLLAMA_HOST=100.x.y.z), not 0.0.0.0 - Ollama has no login."
echo " - GPS: if meshtasticd owns /dev/ttyAMA0, Field Status shows 'no gpsd'. Either run gpsd"
echo "   on ttyAMA0 and point meshtasticd at gpsd, or leave it - Mesh still shows your position."
echo " - Signals: rtl_433 (sensors) is installed. ACARS needs acarsdec, which isn't in Debian -"
echo "   build it from github.com/TLeconte/acarsdec, then it appears in the Signals app."
echo " - Scout (Network/RF site survey): scans only your own subnet and is receive-only. The Wi-Fi"
echo "   tab needs nmcli (NetworkManager); without it that tab shows how to install it."
echo " - The H4M is not used. Leave it unplugged."
DONE=1
}
main "$@"
