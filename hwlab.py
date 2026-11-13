#!/usr/bin/env python3
"""Hardware workbench - the uConsole's GPIO header as a bench instrument.

SERIAL   A terminal for anything on a USB or UART port: watch an ESP32's boot log and
         sensor output scroll by, send it commands, log the whole session to a file. Line
         view with timestamps, or a raw hex view for binary protocols.
BUS      Scan the I2C bus (and list SPI/UART devices) on the 40-pin header - every chip
         that answers, by address, with the common ones named.
GPIO     Read every pin's mode and level at a glance; toggle an output; watch an input.

Everything here only reads or drives the user's own hardware on the bench. --demo runs a
synthetic ESP32 and a couple of fake I2C chips so the workbench can be used without anything
wired up.
"""
import collections
import glob
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S          # noqa: E402

LOG_DIR = os.path.join(S.DATA, "hwlab")
BAUDS = [9600, 19200, 38400, 57600, 74880, 115200, 230400, 460800, 921600]
DEFAULTS = {"port": "", "baud": 115200, "newline": "\r\n", "view": "line", "echo": True,
            "autoscroll": True, "logging": False,
            "macros": [["help", "help"], ["status", "status"], ["reboot", "reboot"]]}
PLOT_COLORS = ["#4c90f0", "#5ec4d4", "#e8a33a", "#7bc96f", "#d46a9f", "#c86a6a", "#9a8cf0"]

# the I2C chips you actually run into on a bench, by 7-bit address
I2C_NAMES = {
    0x0c: "AK8963 mag", 0x0d: "compass", 0x18: "LIS3DH accel", 0x19: "LSM accel",
    0x1e: "HMC5883 mag", 0x20: "MCP23017 / PCF8574", 0x23: "BH1750 light",
    0x27: "PCF8574 LCD", 0x28: "BNO055 IMU", 0x29: "VL53L0X / TCS34725",
    0x36: "MAX17048 fuel gauge", 0x38: "AHT10 / FT6236 touch", 0x39: "APDS-9960",
    0x3c: "SSD1306 OLED", 0x3d: "SSD1306 OLED", 0x40: "INA219 / SHT31 / Si7021",
    0x44: "SHT3x", 0x48: "ADS1115 / LM75", 0x4a: "ADS1115", 0x50: "AT24 EEPROM",
    0x51: "PCF8563 RTC", 0x53: "ADXL345", 0x57: "MAX30102 / AT24", 0x5a: "MLX90614 / CCS811",
    0x60: "MCP4725 / Si5351 / ATECC", 0x62: "SCD30 CO2", 0x68: "MPU6050 / DS3231 / DS1307",
    0x69: "MPU6050 / ICM", 0x6a: "LSM6DS gyro", 0x6b: "LSM6DS gyro", 0x70: "TCA9548 mux / HT16K33",
    0x76: "BME280 / BMP280 / MS5611", 0x77: "BME280 / BMP280",
}
# addresses the Linux kernel or a driver usually already owns
I2C_RESERVED = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x78, 0x79, 0x7a, 0x7b,
                0x7c, 0x7d, 0x7e, 0x7f}


# ---- pure helpers (tested without hardware) -------------------------------------------------
def list_serial_ports():
    """(device, description) for every serial port, best first. USB adapters before the
    Pi's own UARTs; a flaky enumerator never takes the app down."""
    out = []
    try:
        import serial.tools.list_ports as lp
        for p in lp.comports():
            out.append((p.device, (p.description or "").strip() or p.device))
    except Exception:
        pass
    have = {d for d, _ in out}
    for dev in sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*") +
                      glob.glob("/dev/ttyAMA*") + glob.glob("/dev/serial0")):
        if dev not in have:
            out.append((dev, dev))

    def rank(item):
        d = item[0]
        return (0 if "USB" in d or "ACM" in d else 1, d)
    return sorted(out, key=rank)


class LineFramer:
    """Turns a byte stream into terminal lines. Holds an unfinished line between reads so a
    chunk that splits mid-line doesn't produce two fragments. Control bytes are shown as
    printable escapes so a stray 0x00 can't corrupt the Tk text widget."""

    def __init__(self):
        self.buf = ""

    def feed(self, data):
        """bytes -> list of completed lines (without their newline). Remainder is held."""
        if not data:
            return []
        self.buf += data.decode("utf-8", "replace")
        self.buf = self.buf.replace("\r\n", "\n").replace("\r", "\n")
        parts = self.buf.split("\n")
        self.buf = parts.pop()
        return [clean_text(p) for p in parts]

    def flush(self):
        """Whatever is held, as a line (for a stream that never sends a final newline)."""
        if not self.buf:
            return None
        line, self.buf = clean_text(self.buf), ""
        return line


def clean_text(s):
    """Printable form of a decoded line: tabs kept, other control bytes shown as ^X / \\xNN."""
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\t" or o >= 32 and o != 127:
            out.append(ch)
        elif o < 32:
            out.append("^" + chr(o + 64))
        else:
            out.append("\\x%02x" % o)
    return "".join(out)


import re as _re
_KV = _re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*[=:]\s*(-?\d+\.?\d*)(?![xX])")
_NUM = _re.compile(r"-?\d+\.?\d*")


def parse_values(line):
    """Numbers worth plotting from a serial line, as {name: float}.

    Handles three shapes, in order of preference:
      key=value / key:value   ->  {"temp": 21.3, "hum": 41}
      bare CSV of numbers      ->  {"ch0": .., "ch1": ..}   (only if the whole line is numeric)
      a single number in text  ->  {"value": ..}
    A leading "[  1000]" millis counter and trailing units (C, %, hPa, dBm) are ignored."""
    line = line.strip()
    if not line:
        return {}
    # strip a leading bracketed counter like "[ 1000]" so it isn't plotted
    line = _re.sub(r"^\[\s*\d+\s*\]\s*", "", line)
    kv = _KV.findall(line)
    if kv:
        out = {}
        for k, v in kv:
            try:
                out[k] = float(v)
            except ValueError:
                pass
        if out:
            return out
    # a pure CSV / whitespace row of numbers
    toks = _re.split(r"[,\s]+", line)
    nums = [t for t in toks if _re.fullmatch(r"-?\d+\.?\d*", t)]
    if toks and len(nums) == len(toks) and nums:
        return {"ch%d" % i: float(n) for i, n in enumerate(nums)}
    # otherwise, a single number embedded in text
    m = _NUM.search(line)
    if m and len(_NUM.findall(line)) == 1:
        try:
            return {"value": float(m.group())}
        except ValueError:
            return {}
    return {}


def hexdump(data, width=16, base=0):
    """Classic offset | hex | ascii dump, as a list of lines."""
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hx = " ".join("%02x" % b for b in chunk)
        hx += "   " * (width - len(chunk))
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append("%08x  %s  %s" % (base + i, hx, asc))
    return lines


def i2c_label(addr):
    return I2C_NAMES.get(addr, "")


def parse_i2cdetect(text):
    """Parse `i2cdetect -y N` output into a sorted list of 7-bit addresses that answered."""
    found = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        row, cells = line.split(":", 1)
        try:
            base = int(row.strip(), 16)
        except ValueError:
            continue
        for j, cell in enumerate(cells.split()):
            c = cell.strip().lower()
            if c in ("", "--", "uu"):
                continue
            try:
                found.append(int(c, 16))
            except ValueError:
                if len(c) == 2 and all(x in "0123456789abcdef" for x in c):
                    found.append(base + j)
    return sorted(set(found))


def scan_i2c(bus=1, run=None):
    """Addresses answering on an I2C bus. Prefers the kernel's i2cdetect; falls back to
    smbus probing. Returns (addresses, error|None)."""
    run = run or S.run
    dev = "/dev/i2c-%d" % bus
    if not os.path.exists(dev):
        return [], "no %s - enable I2C (raspi-config / dtparam=i2c_arm=on) and wire SDA/SCL" % dev
    import shutil
    if shutil.which("i2cdetect"):
        rc, out = run(["i2cdetect", "-y", str(bus)], timeout=8)
        if rc == 0:
            return parse_i2cdetect(out), None
    try:
        import smbus2
    except ImportError:
        return [], "install i2c-tools (i2cdetect) or python3-smbus2 to scan"
    found = []
    try:
        b = smbus2.SMBus(bus)
        for addr in range(0x03, 0x78):
            try:
                b.write_quick(addr)
                found.append(addr)
            except OSError:
                pass
        b.close()
    except Exception as e:
        return [], str(e)[:80]
    return found, None


def gpio_chip_present():
    return bool(glob.glob("/dev/gpiochip*"))


def read_gpio(run=None):
    """Every GPIO line's (num, name, mode, level) via `gpioinfo`/`raspi-gpio`, or []."""
    run = run or S.run
    import shutil
    if shutil.which("raspi-gpio"):
        rc, out = run(["raspi-gpio", "get"], timeout=5)
        if rc == 0:
            return parse_raspi_gpio(out)
    return []


def parse_raspi_gpio(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("GPIO "):
            continue
        try:
            num = int(line.split()[1].rstrip(":"))
        except (IndexError, ValueError):
            continue
        d = {}
        for tok in line.split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                d[k] = v
        rows.append((num, d.get("func", "?"), d.get("fsel", ""), d.get("level", "?")))
    return rows


# ---- demo (no hardware) ---------------------------------------------------------------------
class DemoSerial:
    """A synthetic ESP32: boot banner, then periodic sensor lines, and it answers a few
    typed commands. Mirrors the real reader's .read_lines()/.write() so the UI path is
    identical to a live port."""
    BOOT = ["ets Jun  8 2016 00:22:57", "rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)",
            "configsip: 0, SPIWP:0xee", "mode:DIO, clock div:1", "load:0x3fff0030,len:1184",
            "entry 0x400805f0", "", "[boot] RF Reaper firmware v0.4.1 (demo)",
            "[wifi] connecting to lab-ap...", "[wifi] got ip 10.0.0.42",
            "[i2c] BME280 found at 0x76", "[rf] CC1101 init ok, 433.92 MHz", "ready >"]

    def __init__(self):
        self.q = collections.deque(self.BOOT)
        self.t0 = time.time()
        self.n = 0
        self.open = True
        self.raw = bytearray()

    def read_lines(self):
        out = []
        while self.q:
            out.append(self.q.popleft())
        if time.time() - self.t0 > 1.2:
            self.t0 = time.time()
            self.n += 1
            out.append("[%6d] temp=%.1fC hum=%d%% pres=%.1fhPa rssi=-%ddBm" % (
                self.n * 1000, 21 + (self.n % 5) * 0.3, 40 + self.n % 8,
                1012.0 + (self.n % 10) * 0.2, 60 + self.n % 25))
        for ln in out:
            self.raw += ln.encode("utf-8") + b"\r\n"
        return out

    def take_raw(self):
        data, self.raw = bytes(self.raw), bytearray()
        return data

    def write(self, data):
        cmd = data.decode("utf-8", "replace").strip().lower()
        reply = {"help": "commands: help, status, scan, reboot",
                 "status": "up %ds, heap=180KB, rf=idle" % int(time.time() - self.t0 + 30),
                 "scan": "[rf] listening 433.92 MHz... 0 frames",
                 "reboot": "rebooting..."}.get(cmd, "unknown cmd '%s' (try help)" % cmd if cmd else "")
        if reply:
            self.q.append(reply)
        if cmd == "reboot":
            self.q.extend(self.BOOT)

    def close(self):
        self.open = False


DEMO_I2C = [0x3c, 0x68, 0x76]
DEMO_GPIO = [(2, "INPUT", "", "1"), (3, "INPUT", "", "1"), (4, "OUTPUT", "", "0"),
             (14, "ALT0", "", "1"), (15, "ALT0", "", "0"), (17, "OUTPUT", "", "1"),
             (18, "INPUT", "", "0"), (27, "INPUT", "", "0")]


RAW_KEEP = 65536     # bytes of raw serial history kept for the Hex view


# ---- live serial reader ---------------------------------------------------------------------
class SerialReader:
    """Owns the pyserial port and a reader thread. The UI calls read_lines() each tick and
    write() to send; nothing here touches Tk."""

    def __init__(self, port, baud):
        import serial
        self.ser = serial.Serial(port, baud, timeout=0.2)
        self.open = True
        self.lock = threading.Lock()
        self.inbuf = bytearray()
        self.raw = bytearray()        # same bytes, kept for the Hex view
        self.framer = LineFramer()
        self.err = None
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self):
        while self.open:
            try:
                data = self.ser.read(4096)
            except Exception as e:
                self.err = str(e)[:80]
                self.open = False
                return
            if data:
                with self.lock:
                    self.inbuf += data

    def read_lines(self):
        with self.lock:
            data, self.inbuf = bytes(self.inbuf), bytearray()
        self.raw += data
        if len(self.raw) > RAW_KEEP:
            del self.raw[:-RAW_KEEP]
        return self.framer.feed(data)

    def take_raw(self):
        """The raw bytes behind the lines read_lines() has returned since the last call."""
        data, self.raw = bytes(self.raw), bytearray()
        return data

    def read_bytes(self):
        with self.lock:
            data, self.inbuf = bytes(self.inbuf), bytearray()
        return data

    def write(self, data):
        try:
            self.ser.write(data)
        except Exception as e:
            self.err = str(e)[:80]

    def set_lines(self, dtr=None, rts=None):
        if dtr is not None:
            self.ser.dtr = dtr
        if rts is not None:
            self.ser.rts = rts

    def close(self):
        self.open = False
        try:
            self.ser.close()
        except Exception:
            pass


# ---- the app --------------------------------------------------------------------------------
def main():
    S.single_instance("Hardware")
    demo = "--demo" in sys.argv
    s, spath = S.settings("hwlab", DEFAULTS)
    root, F = S.make_root("Hardware")
    import tkinter as tk
    T = S.T
    slog = S.SessionLog("hwlab")
    st = {"reader": None, "tab": "serial", "logf": None, "rawbytes": bytearray(), "rawtotal": 0,
          "lines": 0, "closed": False, "i2c": None, "i2c_err": None, "gpio": [],
          "scanning": False}

    top = S.top_bar(root, F, "Hardware", "GPIO workbench" if not demo else "demo")
    conn_pill = S.pill(top, F, "Disconnected")
    if demo:
        S.pill(top, F, "DEMO", S.AMBER)

    # ---- tab bar
    tabs_row = tk.Frame(root, bg=T.SURFACE)
    tabs_row.pack(side="top", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="top", fill="x")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    panes = {}
    for key in ("serial", "bus", "gpio"):
        panes[key] = tk.Frame(body, bg=S.BG)
    tab_btns = {}

    def show_tab(key):
        st["tab"] = key
        for k, p in panes.items():
            p.pack_forget()
        panes[key].pack(fill="both", expand=True)
        for k, b in tab_btns.items():
            T.set_btn(b, kind="primary" if k == key else "ghost")
        if key == "bus" and st["i2c"] is None and not st["scanning"]:
            scan_bus()
        if key == "gpio":
            refresh_gpio()

    for key, label in (("serial", "Serial"), ("bus", "Bus scan"), ("gpio", "GPIO")):
        b = S.btn(tabs_row, label, lambda k=key: show_tab(k), F, padx=14, pady=6,
                  kind="ghost")
        b.pack(side="left", padx=(T.px(6), 0), pady=T.px(5))
        tab_btns[key] = b

    # ================= SERIAL =================
    sp = panes["serial"]
    ctl = tk.Frame(sp, bg=T.SURFACE)
    ctl.pack(side="top", fill="x")
    tk.Frame(sp, bg=S.LINE, height=1).pack(side="top", fill="x")
    crow = tk.Frame(ctl, bg=T.SURFACE)
    crow.pack(fill="x", padx=T.px(10), pady=T.px(7))

    tk.Label(crow, text="Port", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE).pack(side="left")
    port_var = tk.StringVar(value=s.get("port") or "")
    port_menu = S.dropdown(crow, F, port_var, [""], width=16)
    port_menu.pack(side="left", padx=(T.px(6), T.px(12)))

    def refresh_ports():
        ports = [("demo://esp32", "demo ESP32")] if demo else list_serial_ports()
        menu = port_menu["menu"]
        menu.delete(0, "end")
        if not ports:
            port_var.set("")
            menu.add_command(label="(no ports - plug in a USB adapter)",
                             command=lambda: None)
        else:
            if port_var.get() not in [p for p, _ in ports]:
                port_var.set(ports[0][0])
            for dev, desc in ports:
                menu.add_command(label="%s  -  %s" % (dev, desc[:30]),
                                 command=lambda d=dev: port_var.set(d))

    tk.Label(crow, text="Baud", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE).pack(side="left")
    baud_var = tk.IntVar(value=s.get("baud", 115200))
    baud_menu = S.dropdown(crow, F, baud_var, BAUDS, width=7)
    baud_menu.pack(side="left", padx=(T.px(6), T.px(12)))

    connect_btn = S.btn(crow, "Connect", lambda: toggle_connect(), F, padx=12, pady=4,
                        kind="primary")
    connect_btn.pack(side="left")

    def set_view(v):
        s["view"] = v
        save()
        for vv, b in (("line", view_line), ("hex", view_hex), ("plot", view_plot)):
            T.set_btn(b, kind="primary" if vv == v else "ghost")
        if v == "plot":
            outwrap.pack_forget()
            plotwrap.pack(fill="both", expand=True)
            draw_plot()
        else:
            plotwrap.pack_forget()
            outwrap.pack(fill="both", expand=True)
            redraw_output()
    view_plot = S.btn(crow, "Plot", lambda: set_view("plot"), F, padx=10, pady=4, kind="ghost")
    view_plot.pack(side="right")
    view_hex = S.btn(crow, "Hex", lambda: set_view("hex"), F, padx=10, pady=4, kind="ghost")
    view_hex.pack(side="right", padx=(0, T.px(4)))
    view_line = S.btn(crow, "Line", lambda: set_view("line"), F, padx=10, pady=4, kind="ghost")
    view_line.pack(side="right", padx=(0, T.px(4)))
    log_btn = S.btn(crow, "Log: off", lambda: toggle_log(), F, padx=10, pady=4, kind="ghost")
    log_btn.pack(side="right", padx=(0, T.px(10)))

    # ESP32 reset / download-mode (DTR=IO0, RTS=EN, the esptool convention)
    def esp_reset(download=False):
        r = st["reader"]
        if r is None or not hasattr(r, "set_lines"):
            append("sys", "Connect to a real port first." if r is None else
                          "Reset needs a hardware port (not demo).")
            return
        try:
            r.set_lines(dtr=False, rts=True)   # EN low: hold in reset
            time.sleep(0.1)
            if download:
                r.set_lines(dtr=True, rts=False)   # IO0 low, EN high: enter bootloader
            else:
                r.set_lines(dtr=False, rts=False)  # release: normal boot
            time.sleep(0.05)
            r.set_lines(dtr=False, rts=False)
            append("sys", "Sent %s pulse." % ("download-mode" if download else "reset"))
            slog.event("hwlab", "esp %s" % ("bootloader" if download else "reset"), id="esp")
        except Exception as e:
            append("sys", "Reset failed: %s" % str(e)[:60])
    S.btn(crow, "Boot", lambda: esp_reset(download=True), F, padx=10, pady=4,
          kind="quiet").pack(side="right", padx=(0, T.px(4)))
    S.btn(crow, "Reset", lambda: esp_reset(download=False), F, padx=10, pady=4,
          kind="quiet").pack(side="right", padx=(0, T.px(4)))

    # output (line / hex)
    outwrap = tk.Frame(sp, bg=S.BG)
    # NOTE: not packed here. The bottom send row (srow) is packed first, below, so it always
    # keeps its space; set_view() then packs outwrap/plotwrap into whatever remains. A Text
    # defaults to a 24-line request, which would otherwise overflow the window and clip srow.
    out = tk.Text(outwrap, bg="#07080a", fg=T.TXT_2, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="none", state="disabled", padx=T.px(10), pady=T.px(6), height=1)
    sb = tk.Scrollbar(outwrap, command=out.yview, bg=T.SURFACE, troughcolor=S.BG, bd=0,
                      highlightthickness=0, width=T.px(10))
    out.config(yscrollcommand=sb.set)
    S.bind_wheel(out)
    sb.pack(side="right", fill="y")
    out.pack(side="left", fill="both", expand=True)
    out.tag_config("tx", foreground=T.ACCENT)
    out.tag_config("rx", foreground=T.TXT_2)
    out.tag_config("sys", foreground=T.TXT_3)
    out.tag_config("ts", foreground=T.TXT_3)
    ring = collections.deque(maxlen=4000)      # (kind, text, ts) so we can redraw on view change

    # plotter: one series per numeric field seen on incoming lines
    plotwrap = tk.Frame(sp, bg="#07080a")
    plot = tk.Canvas(plotwrap, bg="#07080a", highlightthickness=0)
    plot.pack(fill="both", expand=True)
    legend = tk.Frame(plotwrap, bg="#07080a")
    legend.pack(side="bottom", fill="x")
    series = collections.OrderedDict()         # name -> deque[(n, value)]
    hidden = set()                             # series the user (or auto) has hidden
    plot_n = [0]
    _seen_legend = set()
    PLOT_MAX = 600

    def feed_plot(line):
        vals = parse_values(line)
        if not vals:
            return
        plot_n[0] += 1
        for k, v in vals.items():
            if k not in series:
                if len(series) >= 7:
                    continue                   # cap at 7 series, keep the first seen
                series[k] = collections.deque(maxlen=PLOT_MAX)
            series[k].append((plot_n[0], v))

    def draw_plot():
        plot.delete("all")
        w, h = max(plot.winfo_width(), 100), max(plot.winfo_height(), 60)
        pad_l, pad_r, pad_t, pad_b = T.px(44), T.px(10), T.px(10), T.px(18)
        if not series or all(len(d) < 2 for d in series.values()):
            plot.create_text(w / 2, h / 2, text="Numbers on incoming lines are graphed here.\n"
                             "e.g.  temp=21.3  hum=41", font=F["map"], fill=T.TXT_3,
                             justify="center")
            return
        vis = [(n, d) for n, d in series.items() if n not in hidden and len(d) >= 2]
        if not vis:
            plot.create_text(w / 2, h / 2, text="All series hidden. Tap a name in the legend.",
                             font=F["map"], fill=T.TXT_3)
            return
        allv = [v for _, d in vis for _, v in d]
        lo, hi = min(allv), max(allv)
        if hi - lo < 1e-9:
            lo, hi = lo - 1, hi + 1
        span = hi - lo
        ns = [n for _, d in vis for n, _ in d]
        nlo, nhi = min(ns), max(ns)
        nspan = max(1, nhi - nlo)

        def X(n):
            return pad_l + (n - nlo) / nspan * (w - pad_l - pad_r)

        def Y(v):
            return pad_t + (hi - v) / span * (h - pad_t - pad_b)
        # gridlines + y labels
        for frac in (0, 0.25, 0.5, 0.75, 1.0):
            yv = lo + span * frac
            y = Y(yv)
            plot.create_line(pad_l, y, w - pad_r, y, fill=T.LINE)
            plot.create_text(pad_l - T.px(6), y, text="%g" % yv, anchor="e", font=F["lbl"],
                             fill=T.TXT_3)
        order = list(series.keys())
        for name, d in vis:
            col = PLOT_COLORS[order.index(name) % len(PLOT_COLORS)]
            pts = []
            for n, v in d:
                pts += [X(n), Y(v)]
            if len(pts) >= 4:
                plot.create_line(*pts, fill=col, width=T.px(1.5), smooth=False)
                plot.create_text(X(d[-1][0]) - 2, Y(d[-1][1]) - T.px(7), text="%g" % d[-1][1],
                                 anchor="e", font=F["lbl"], fill=col)

    def toggle_series(name):
        hidden.discard(name) if name in hidden else hidden.add(name)
        build_legend()
        draw_plot()

    def build_legend():
        for w in legend.winfo_children():
            w.destroy()
        longest = max((len(d) for d in series.values()), default=0)
        for i, (name, d) in enumerate(series.items()):
            # a value seen once or twice while others stream is boot noise: hide it by default
            if longest >= 10 and len(d) <= 2 and name not in hidden and name not in _seen_legend:
                hidden.add(name)
            _seen_legend.add(name)
            col = PLOT_COLORS[i % len(PLOT_COLORS)]
            off = name in hidden
            cell = tk.Frame(legend, bg="#07080a", cursor="hand2")
            cell.pack(side="left", padx=T.px(8), pady=T.px(3))
            sw = tk.Frame(cell, bg=T.LINE if off else col, width=T.px(10), height=T.px(10))
            sw.pack(side="left", padx=(0, T.px(4)))
            lb = tk.Label(cell, text=name, font=F["lbl"], fg=T.TXT_3 if off else T.TXT_2,
                          bg="#07080a")
            lb.pack(side="left")
            for wdg in (cell, sw, lb):
                wdg.bind("<Button-1>", lambda e, nm=name: toggle_series(nm))
        if series:
            S.btn(legend, "Clear", lambda: (series.clear(), hidden.clear(), _seen_legend.clear(),
                                            plot_n.__setitem__(0, 0),
                                            build_legend(), draw_plot()), F, padx=8, pady=2,
                  kind="quiet").pack(side="right", padx=T.px(8))
    plot.bind("<Configure>", lambda e: draw_plot())

    # send row
    srow = tk.Frame(sp, bg=T.SURFACE)
    srow.pack(side="bottom", fill="x")
    tk.Frame(sp, bg=S.LINE, height=1).pack(side="bottom", fill="x")

    # macro bar: one-tap sends, editable
    macro_bar = tk.Frame(srow, bg=T.SURFACE)
    macro_bar.pack(fill="x", padx=T.px(10), pady=(T.px(6), 0))

    def send_text(text):
        r = st["reader"]
        if r is None:
            append("sys", "Not connected.")
            return
        r.write((text + s.get("newline", "\r\n")).encode("utf-8", "replace"))
        if s.get("echo", True):
            append("tx", text)

    def build_macros():
        for w in macro_bar.winfo_children():
            w.destroy()
        tk.Label(macro_bar, text="MACROS", font=F["lbl"], fg=T.TXT_3, bg=T.SURFACE).pack(
            side="left", padx=(0, T.px(6)))
        for label, cmd in (s.get("macros") or [])[:8]:
            S.btn(macro_bar, label[:14], lambda c=cmd: send_text(c), F, padx=9, pady=3,
                  kind="ghost").pack(side="left", padx=(0, T.px(4)))
        S.btn(macro_bar, "Edit…", lambda: edit_macros(), F, padx=9, pady=3,
              kind="quiet").pack(side="right")

    def edit_macros():
        import settings_ui
        rows = {"v": [list(m) for m in (s.get("macros") or [])]}
        schema = [("Macro buttons (label → command sent)", [
            {"key": "macros", "label": "label | command", "type": "list",
             "help": "one per line as  label | command   (e.g.  reboot | reboot)"},
        ])]
        flat = {"macros": ["%s | %s" % (m[0], m[1]) for m in (s.get("macros") or [])]}

        def saved(ns):
            out = []
            for line in ns.get("macros", []):
                if "|" in line:
                    lab, cmd = line.split("|", 1)
                    out.append([lab.strip(), cmd.strip()])
                elif line.strip():
                    out.append([line.strip(), line.strip()])
            s["macros"] = out
            save()
            build_macros()
        settings_ui.open_settings(root, F, "Serial macros", schema, flat, saved, path=None)
        _ = rows

    sendwrap = tk.Frame(srow, bg=T.SURFACE)
    sendwrap.pack(fill="x", padx=T.px(10), pady=T.px(7))
    entry = tk.Entry(sendwrap, bg=T.SURFACE_2, fg=T.TXT, font=F["mono"], bd=0,
                     insertbackground=T.TXT, highlightthickness=1, highlightbackground=T.LINE,
                     highlightcolor=T.ACCENT)
    entry.pack(side="left", fill="x", expand=True, ipady=T.px(5))
    nl_var = tk.StringVar(value={"\r\n": "CRLF", "\n": "LF", "\r": "CR", "": "none"}.get(
        s.get("newline", "\r\n"), "CRLF"))
    nl_menu = S.dropdown(sendwrap, F, nl_var, ["CRLF", "LF", "CR", "none"], width=4,
                         command=lambda v: set_newline(v), font="lbl")
    nl_menu.pack(side="left", padx=(T.px(6), 0))
    send_btn = S.btn(sendwrap, "Send", lambda: do_send(), F, padx=12, pady=4, kind="primary")
    send_btn.pack(side="left", padx=(T.px(6), 0))
    history = []
    hist_idx = [0]

    def set_newline(v):
        s["newline"] = {"CRLF": "\r\n", "LF": "\n", "CR": "\r", "none": ""}[v]
        save()

    def append(kind, text, ts=None):
        ts = ts if ts is not None else time.time()
        ring.append((kind, text, ts))
        if kind == "rx":
            before = len(series)
            feed_plot(text)
            if len(series) != before and s.get("view") == "plot":
                build_legend()
        if st["tab"] == "serial":
            write_line(kind, text, ts)
        if st["logf"]:
            try:
                st["logf"].write("%s %s\n" % (time.strftime("%H:%M:%S", time.localtime(ts)),
                                              text if kind != "tx" else "> " + text))
                st["logf"].flush()
            except OSError:
                pass

    def write_line(kind, text, ts):
        out.config(state="normal")
        if s.get("view") == "hex" and kind in ("rx", "tx"):
            pass                                # hex view is rendered wholesale in redraw
        else:
            at_end = out.yview()[1] > 0.995
            prefix = {"tx": "> ", "sys": "", "rx": ""}.get(kind, "")
            out.insert("end", "%s " % time.strftime("%H:%M:%S", time.localtime(ts)), "ts")
            out.insert("end", prefix + text + "\n", kind)
            if s.get("autoscroll", True) and at_end:
                out.see("end")
        out.config(state="disabled")

    def redraw_output():
        out.config(state="normal")
        out.delete("1.0", "end")
        if s.get("view") == "hex":
            data = bytes(st["rawbytes"][-4096:])
            for ln in hexdump(data, base=st["rawtotal"] - len(data)):
                out.insert("end", ln + "\n", "rx")
        else:
            for kind, text, ts in ring:
                prefix = {"tx": "> ", "sys": "", "rx": ""}.get(kind, "")
                out.insert("end", "%s " % time.strftime("%H:%M:%S", time.localtime(ts)), "ts")
                out.insert("end", prefix + text + "\n", kind)
        if s.get("autoscroll", True):
            out.see("end")
        out.config(state="disabled")

    def toggle_connect():
        if st["reader"] is not None:
            disconnect()
            return
        port = port_var.get()
        if not port:
            append("sys", "No port selected. Plug in a USB-serial adapter (or use demo).")
            return
        baud = baud_var.get()
        s["port"], s["baud"] = port, baud
        save()
        try:
            st["reader"] = DemoSerial() if demo else SerialReader(port, baud)
        except Exception as e:
            append("sys", "Couldn't open %s: %s" % (port, str(e)[:70]))
            if "Permission" in str(e):
                append("sys", "You may need to be in the 'dialout' group: "
                              "sudo usermod -aG dialout $USER  (then log out and back in)")
            return
        st["lines"] = 0
        conn_pill.config(text="%s @ %d" % (os.path.basename(port), baud), bg=S.GREEN)
        T.set_btn(connect_btn, "Disconnect", "danger")
        append("sys", "Connected to %s at %d baud." % (port, baud))
        slog.event("hwlab", "serial %s @ %d" % (os.path.basename(port), baud), id="ser")
        entry.focus_set()

    def disconnect():
        r = st["reader"]
        st["reader"] = None
        if r:
            r.close()
        conn_pill.config(text="Disconnected", bg=S.DIM)
        T.set_btn(connect_btn, "Connect", "primary")
        append("sys", "Disconnected.")

    def do_send(_=None):
        r = st["reader"]
        if r is None:
            append("sys", "Not connected.")
            return
        text = entry.get()
        entry.delete(0, "end")
        if text:
            history.append(text)
            hist_idx[0] = len(history)
        r.write((text + s.get("newline", "\r\n")).encode("utf-8", "replace"))
        if s.get("echo", True):
            append("tx", text)

    entry.bind("<Return>", do_send)

    def hist(delta):
        if not history:
            return
        hist_idx[0] = max(0, min(len(history), hist_idx[0] + delta))
        entry.delete(0, "end")
        if hist_idx[0] < len(history):
            entry.insert(0, history[hist_idx[0]])
    entry.bind("<Up>", lambda e: (hist(-1), "break")[1])
    entry.bind("<Down>", lambda e: (hist(1), "break")[1])

    def toggle_log():
        if st["logf"]:
            st["logf"].close()
            st["logf"] = None
            T.set_btn(log_btn, "Log: off", "ghost")
            append("sys", "Logging stopped.")
            return
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            path = os.path.join(LOG_DIR, time.strftime("serial-%Y%m%d-%H%M%S.log"))
            st["logf"] = open(path, "w")
            T.set_btn(log_btn, "Log: on", "primary")
            append("sys", "Logging to %s" % path)
        except OSError as e:
            append("sys", "Couldn't open log: %s" % e)

    def clear_output():
        ring.clear()
        st["rawbytes"] = bytearray()
        st["rawtotal"] = 0
        redraw_output()
    S.btn(crow, "Clear", clear_output, F, padx=10, pady=4, kind="quiet").pack(
        side="right", padx=(0, T.px(4)))

    # ================= BUS SCAN =================
    bp = panes["bus"]
    bhead = tk.Frame(bp, bg=T.SURFACE)
    bhead.pack(side="top", fill="x")
    tk.Frame(bp, bg=S.LINE, height=1).pack(side="top", fill="x")
    brow = tk.Frame(bhead, bg=T.SURFACE)
    brow.pack(fill="x", padx=T.px(10), pady=T.px(7))
    S.btn(brow, "Scan I2C", lambda: scan_bus(), F, padx=12, pady=4, kind="primary").pack(
        side="left")
    bus_status = tk.Label(brow, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE)
    bus_status.pack(side="left", padx=(T.px(12), 0))
    bgrid = tk.Frame(bp, bg=S.BG)
    bgrid.pack(fill="both", expand=True, padx=T.px(14), pady=T.px(12))

    def scan_bus():
        if st["scanning"]:
            return
        st["scanning"] = True
        bus_status.config(text="scanning…", fg=T.TXT_3)

        def work():
            if demo:
                time.sleep(0.4)
                addrs, err = list(DEMO_I2C), None
            else:
                addrs, err = scan_i2c(1)
            def done():
                st["scanning"] = False
                st["i2c"], st["i2c_err"] = addrs, err
                draw_bus()
            root.after(0, done)
        S.in_thread(work)

    def draw_bus():
        for w in bgrid.winfo_children():
            w.destroy()
        addrs = st["i2c"] or []
        err = st["i2c_err"]
        if err:
            bus_status.config(text=err, fg=S.AMBER)
        else:
            bus_status.config(text="%d device%s on I2C bus 1" % (len(addrs),
                                                                 "" if len(addrs) == 1 else "s"),
                              fg=T.TXT if addrs else T.TXT_3)
        # the 0x00-0x7f grid, like i2cdetect but readable
        head = tk.Frame(bgrid, bg=S.BG)
        head.pack(anchor="w")
        tk.Label(head, text="    ", font=F["mono"], bg=S.BG).pack(side="left")
        for col in range(16):
            tk.Label(head, text="%x" % col, font=F["mono"], fg=T.TXT_3, bg=S.BG,
                     width=3).pack(side="left")
        for row in range(8):
            rf = tk.Frame(bgrid, bg=S.BG)
            rf.pack(anchor="w")
            tk.Label(rf, text="%02x:" % (row * 16), font=F["mono"], fg=T.TXT_3, bg=S.BG).pack(
                side="left")
            for col in range(16):
                a = row * 16 + col
                if a in addrs:
                    txt, fg = "%02x" % a, "#07080a"
                    lab = tk.Label(rf, text=txt, font=F["mono"], fg=fg, bg=T.ACCENT, width=3)
                elif a in I2C_RESERVED:
                    lab = tk.Label(rf, text="··", font=F["mono"], fg=T.TXT_3, bg=S.BG, width=3)
                else:
                    lab = tk.Label(rf, text="--", font=F["mono"], fg=T.LINE_HI, bg=S.BG, width=3)
                lab.pack(side="left")
        # named devices
        if addrs:
            tk.Frame(bgrid, bg=S.BG, height=T.px(10)).pack()
            T.section(bgrid, F, "Devices found").pack(anchor="w", pady=(T.px(6), T.px(4)))
            for a in addrs:
                name = i2c_label(a)
                rowf = tk.Frame(bgrid, bg=S.BG)
                rowf.pack(anchor="w", fill="x")
                tk.Label(rowf, text="0x%02x" % a, font=F["mono"], fg=T.ACCENT, bg=S.BG,
                         width=6, anchor="w").pack(side="left")
                tk.Label(rowf, text=name or "unknown device", font=F["map"],
                         fg=T.TXT if name else T.TXT_3, bg=S.BG, anchor="w").pack(side="left")
        else:
            tk.Frame(bgrid, bg=S.BG, height=T.px(10)).pack()
            tk.Label(bgrid, text="Nothing answered. Check wiring (SDA/SCL/GND), pull-ups, and "
                                 "that I2C is enabled.", font=F["map"], fg=T.TXT_3, bg=S.BG,
                     wraplength=T.px(560), justify="left", anchor="w").pack(anchor="w")

    # ================= GPIO =================
    gp = panes["gpio"]
    ghead = tk.Frame(gp, bg=T.SURFACE)
    ghead.pack(side="top", fill="x")
    tk.Frame(gp, bg=S.LINE, height=1).pack(side="top", fill="x")
    grow = tk.Frame(ghead, bg=T.SURFACE)
    grow.pack(fill="x", padx=T.px(10), pady=T.px(7))
    S.btn(grow, "Refresh", lambda: refresh_gpio(), F, padx=12, pady=4, kind="primary").pack(
        side="left")
    gpio_status = tk.Label(grow, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE)
    gpio_status.pack(side="left", padx=(T.px(12), 0))
    gwrap = tk.Frame(gp, bg=S.BG)
    gwrap.pack(fill="both", expand=True, padx=T.px(14), pady=T.px(12))

    def refresh_gpio():
        rows = list(DEMO_GPIO) if demo else read_gpio()
        st["gpio"] = rows
        for w in gwrap.winfo_children():
            w.destroy()
        if not rows:
            gpio_status.config(text="raspi-gpio not available", fg=S.AMBER)
            tk.Label(gwrap, text="Install raspi-gpio to read the header "
                                 "(sudo apt install raspi-gpio), then Refresh.",
                     font=F["map"], fg=T.TXT_3, bg=S.BG, wraplength=T.px(560),
                     justify="left").pack(anchor="w")
            return
        gpio_status.config(text="%d lines" % len(rows), fg=T.TXT_3)
        hdr = tk.Frame(gwrap, bg=S.BG)
        hdr.pack(fill="x")
        for txt, w in (("GPIO", 7), ("Function", 12), ("Level", 7)):
            tk.Label(hdr, text=txt, font=F["lbl"], fg=T.TXT_3, bg=S.BG, width=w,
                     anchor="w").pack(side="left")
        for num, func, fsel, level in rows:
            rf = tk.Frame(gwrap, bg=S.BG)
            rf.pack(fill="x")
            tk.Label(rf, text="%d" % num, font=F["mono"], fg=T.TXT, bg=S.BG, width=7,
                     anchor="w").pack(side="left")
            fg = T.NOTE if func in ("OUTPUT", "INPUT") else T.TXT_3
            tk.Label(rf, text=func, font=F["mono"], fg=fg, bg=S.BG, width=12,
                     anchor="w").pack(side="left")
            hi = level == "1"
            tk.Label(rf, text="HIGH" if hi else "LOW", font=F["mono"],
                     fg=S.GREEN if hi else T.TXT_3, bg=S.BG, width=7, anchor="w").pack(side="left")

    def save():
        try:
            S.save_json(spath, s)
        except OSError:
            pass

    # ---- tick: drain the serial reader
    def pump():
        r = st["reader"]
        if r is not None:
            try:
                lines = r.read_lines()
            except Exception:
                lines = []
            for ln in lines:
                append("rx", ln)
                st["lines"] += 1
            raw = r.take_raw() if hasattr(r, "take_raw") else b""
            if raw:
                st["rawbytes"] += raw
                st["rawtotal"] += len(raw)
                if len(st["rawbytes"]) > RAW_KEEP:
                    del st["rawbytes"][:-RAW_KEEP]
                # redraw only while the user is at the end, so scrolling back isn't yanked away
                if st["tab"] == "serial" and s.get("view") == "hex" and out.yview()[1] > 0.995:
                    redraw_output()
            if hasattr(r, "err") and r.err:
                append("sys", "Port error: %s" % r.err)
                disconnect()
            if st["tab"] == "serial":
                conn_pill.config(text="%s · %d lines" % (
                    os.path.basename(port_var.get()), st["lines"]), bg=S.GREEN)
                if s.get("view") == "plot" and lines:
                    draw_plot()
        if not st["closed"]:
            root.after(120, pump)

    def on_close():
        st["closed"] = True
        if st["reader"]:
            st["reader"].close()
        if st["logf"]:
            try:
                st["logf"].close()
            except OSError:
                pass
        root.destroy()

    S.bind_quit(root, on_close)
    S.header_quit(top, root, F, on_close)

    build_macros()
    build_legend()
    refresh_ports()
    S.btn(crow, "↻", lambda: refresh_ports(), F, padx=8, pady=4, kind="quiet").pack(
        side="left", padx=(0, T.px(8)))
    set_view(s.get("view", "line"))
    show_tab("serial")
    append("sys", "Hardware workbench. Pick a port and Connect, or try the Bus scan and GPIO "
                  "tabs." if not demo else "Demo mode: a synthetic ESP32. Connect to watch it "
                  "boot, then type 'help' and Send.")
    if demo:
        root.after(400, toggle_connect)
    if "--plot" in sys.argv:
        root.after(1600, lambda: set_view("plot"))
    pump()
    root.mainloop()


if __name__ == "__main__":
    main()
