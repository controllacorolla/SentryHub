#!/usr/bin/env python3
"""rfemit.py — which gated commands put RF on the air (CL2-fix N1 / N2).

The executor asks this module about every ticket it mints. Two answers matter:

  * SDR_TX — the command keys a general-purpose SDR transmitter (hackrf_transfer and the like).
    Only txguard may authorize those, because only txguard knows the band plan, the protected
    ranges and the power caps (owner decision 1, 2026-11-15). Any other gate asking for one is
    refused at issue time. Matching is by program name ANYWHERE in the argv (so `sudo …`,
    `sh -c "…"`, `/usr/bin/…` wrappers are caught) and by a transmit-capable name pattern, so an
    unknown transmitter whose name looks like one fails closed.

  * any other class (wifi / zigbee / zwave / ble / rfid / serial-rf) — the command radiates from an
    engagement-gated tool. The env hard lock (SUITE_TX_LOCK) and the TX kill switch silence these
    too (owner decision 2): they are refused at issue and at spawn, and a disarm kills a running
    one. The engagement gate still decides WHAT may be targeted; this decides WHETHER the suite may
    radiate at all.

Wired-only tools (nmap, CAN, USB-HID, JTAG/flash, SSH, password audit) are not RF emitters.
Classification is deliberately strict: when in doubt a radio tool is an emitter.
"""
import os
import re

SDR_TX = "sdr-tx"

# General-purpose SDR / RF transmitters: txguard-only. Exact names, plus a pattern for names that
# look transmit-capable (fails closed on an unknown transmitter).
SDR_TX_PROGRAMS = frozenset((
    "hackrf_transfer", "rpitx", "sendiq", "pifmrds", "pi_fm_rds", "pifm", "fl2k_file",
    "fl2k_tcp", "osmocom_siggen", "osmocom_siggen_nogui", "uhd_siggen", "uhd_siggen_gui",
    "tx_samples_from_file", "limesdr_send", "limesdr_toolbox", "soapy_sdr_tx", "bladerf-cli",
    "bladeRF-cli", "plutotx", "iio_writedev", "txsdr", "sdr_tx", "rfcat", "yardstick",
))
SDR_TX_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(hackrf_transfer|rpitx|sendiq|pi_?fm\w*|fl2k_\w+|\w*siggen\w*|"
    r"tx_samples\w*|limesdr_send|soapy\w*tx\w*|bladerf-cli|plutotx|iio_writedev|rfcat|yardstick)"
    r"(?![A-Za-z0-9])", re.I)

# Engagement-gated RF emitters by program (basename). zb* / zwave-* are prefix families: every
# member is an emitter unless it is a known receive-only tool.
EMITTER_PROGRAMS = {
    "aireplay-ng": "wifi", "airbase-ng": "wifi", "besside-ng": "wifi", "mdk3": "wifi",
    "mdk4": "wifi", "hcxdumptool": "wifi", "hostapd": "wifi", "hostapd-mana": "wifi",
    "wifite": "wifi", "reaver": "wifi", "bully": "wifi", "bettercap": "wifi",
    "gatttool": "ble", "btlejack": "ble", "bluetoothctl": "ble", "hcitool": "ble", "btmgmt": "ble",
    "pm3": "rfid", "proxmark3": "rfid", "nfc-mfclassic": "rfid", "nfc-emulate-uid": "rfid",
}
PREFIX_FAMILIES = (("zb", "zigbee"), ("zwave-", "zwave"))
RX_ONLY_PROGRAMS = frozenset((
    "zbdump", "zbid", "zbconvert", "zbcat", "zbdsniff", "zbgoodfind", "zbopenear", "zbwireshark",
    "zbwardrive", "zwave-sniffer",
))

# Flipper CLI verbs (first token) that do NOT radiate. `input` is NOT here (CL2-fix2 R4): it presses
# buttons, so it can drive a radio app (Sub-GHz / NFC / RFID / BT) to transmit; neither are
# loader / js / subghz / nfc / rfid / bt. Every other non-read Flipper command does
# (subghz / nfc / rfid / bt / loader open … — fail closed on unknown verbs).
FLIPPER_NON_RF = frozenset((
    "gpio", "storage", "led", "vibro", "power", "date", "badusb", "ibutton", "ir",
    "infrared", "update", "log", "help", "?", "device_info", "info", "uptime", "free",
    "free_blocks", "ps", "music_player", "buzzer", "crypto", "onewire", "i2c",
))
# Serial device classes. A Flipper line is classified by verb; an ESP32 (Marauder etc.) or an
# unidentified device can radiate anything, so every gated line to one is an emitter.
SERIAL_RF_CLASSES = ("esp32", "unknown")
SERIAL_WIRED_CLASSES = ("slcan", "demo")


def _base(tok):
    return os.path.basename(str(tok)).strip()


def is_sdr_tx(argv):
    """True if any argv token names (or looks like) a general-purpose SDR transmitter."""
    for tok in argv or ():
        s = str(tok)
        if _base(s) in SDR_TX_PROGRAMS or SDR_TX_PATTERN.search(s):
            return True
    return False


WRAPPERS = frozenset(("sudo", "doas", "env", "nice", "ionice", "timeout", "stdbuf", "nohup",
                      "setsid", "chrt", "taskset", "exec", "command", "xargs"))
SHELLS = frozenset(("sh", "bash", "dash", "zsh", "ash", "busybox"))


def _programs(argv):
    """Basenames in a command position. argv[0] is the program; when it is a wrapper (sudo, env,
    timeout …) or a shell, every later word counts (strict: `sudo -u x aireplay-ng …` and
    `sh -c "aireplay-ng …"` are both caught)."""
    toks = [str(t) for t in (argv or ())]
    if not toks:
        return []
    first = _base(toks[0])
    if first not in WRAPPERS and first not in SHELLS:
        return [first]
    out = [first]
    for t in toks[1:]:
        out.extend(_base(w) for w in re.split(r"[\s;&|()`'\"]+", t) if w)
    return out


def _program_class(argv):
    for b in _programs(argv):
        if not b or b in RX_ONLY_PROGRAMS:
            continue
        if b in EMITTER_PROGRAMS:
            return EMITTER_PROGRAMS[b]
        for pre, cls in PREFIX_FAMILIES:
            if b.startswith(pre) and len(b) > len(pre):
                return cls
    return None


def _payload_class(payload, meta):
    if not (meta or {}).get("class"):
        return None                  # not a serial line (e.g. a USB-HID report: wired)
    cls = str(meta["class"])
    if cls in SERIAL_WIRED_CLASSES:
        return None
    if cls in SERIAL_RF_CLASSES:
        return "serial-rf"
    if cls == "flipper":
        line = bytes(payload or b"").decode("utf-8", "replace").strip()
        try:
            import flipper
            if flipper.classify_command(line) == "read":
                return None
        except ImportError:
            pass
        verb = (line.split() or [""])[0].lower()
        return None if verb in FLIPPER_NON_RF else "serial-rf"
    return "serial-rf"               # an unrecognised serial class: fail closed


def classify(argv=None, payload=None, meta=None):
    """SDR_TX, another emitter class string, or None (does not radiate)."""
    if argv is not None:
        if is_sdr_tx(argv):
            return SDR_TX
        return _program_class(argv)
    if payload is not None:
        return _payload_class(payload, meta)
    return None
