"""
uConsole suite UI theme - "C2 map" style (think ATAK / Lattice).

Rules this module enforces:
  * Muted neutral grays, ONE accent (amber). Red only for faults/alerts.
  * Thin 1px lines, no ornament. Small, dense type: IBM Plex Sans + Plex Mono.
  * Sentence case for text; small tracked caps only for section labels.
  * Controls are compact; nothing is a big coloured slab.
Falls back to DejaVu if the bundled Plex fonts aren't installed.
"""

import json
import os
import time

# ---------------------------------------------------------------- UI scale
# The uConsole's 5" panel (native 720x1280, rotated to 1280x720) is ~290 ppi,
# so desktop-sized pixels read tiny.
# Everything (fonts and panel widths) is multiplied by SCALE. Change it from the Hub
# (A- / A+) or in ~/.config/uconsole-suite/ui.json.
UI_PATH = os.path.join(os.path.expanduser("~"), ".config", "uconsole-suite", "ui.json")
DEFAULT_UI = {"scale": 1.4, "sans": "Atkinson Hyperlegible", "mono": "IBM Plex Mono", "night": False,
              "style": "maven"}
STYLES = ("maven", "classic")


def load_ui():
    try:
        with open(UI_PATH) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    out = dict(DEFAULT_UI)
    out.update({k: v for k, v in d.items() if k in DEFAULT_UI})
    if out.get("style") not in STYLES:
        out["style"] = DEFAULT_UI["style"]
    try:
        out["scale"] = max(0.8, min(2.5, float(out["scale"])))
    except (TypeError, ValueError):
        out["scale"] = DEFAULT_UI["scale"]
    return out


def save_ui(ui):
    os.makedirs(os.path.dirname(UI_PATH), exist_ok=True)
    tmp = UI_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(ui, f, indent=2)
    os.replace(tmp, UI_PATH)


UI = load_ui()
SCALE = UI["scale"]


def px(n):
    """Scale a layout size (pixels) by the UI scale."""
    return int(round(n * SCALE))

# ---------------------------------------------------------------- tokens
BG = "#0c0e10"          # app background / map surround
SURFACE = "#13161a"     # docked panels
SURFACE_2 = "#191d21"   # rows, inputs
HOVER = "#1f2429"
LINE = "#262c32"
LINE_HI = "#3a424a"
MAPBG = "#0a0c0d"
RING = "#1e2429"

TXT = "#e4e7ea"
TXT_2 = "#9aa3ab"
TXT_3 = "#5f6870"

ACCENT = "#f0a73a"      # the one accent: selection, live, primary
ACCENT_BG = "#2a2113"   # accent wash for selected rows
ALERT = "#e5534b"
OK = "#5fae83"          # status dots only

# legacy names used across the apps
PANEL, ROW, ROW_OFF, ROW_HOT = SURFACE, SURFACE_2, SURFACE, ACCENT_BG
GRID = RING
MUTED, DIM = TXT_2, TXT_3
AMBER, AMBER_DIM = ACCENT, "#6b5124"
GREEN, RED = OK, ALERT
BLUE = ACCENT           # selection = accent
PURPLE = ACCENT         # "heard" = accent
TRACK = "#c6ccd2"       # default contact colour

STYLE = UI.get("style", "maven")
NOTE = "#5ec4d4"           # notable data (military, watched) - cyan, not orange
FILL = "#2d72d2"           # primary button fill
if STYLE == "maven":
    # Analyst-workstation look: near-black graphite, greyscale chrome, ONE blue accent.
    # Colour is reserved for data and state; the UI itself is monochrome.
    BG, SURFACE, SURFACE_2, HOVER = "#0b0c0e", "#121417", "#1a1d21", "#23272c"
    LINE, LINE_HI, MAPBG, RING = "#262a30", "#3b4149", "#07080a", "#1a1e23"
    TXT, TXT_2, TXT_3 = "#e8eaed", "#9aa1aa", "#6e7883"   # TXT_3 lifted for small-label legibility
    ACCENT, ACCENT_BG = "#4c90f0", "#122641"
    ALERT, OK = "#e5484d", "#3fb27f"
    PANEL, ROW, ROW_OFF, ROW_HOT = SURFACE, SURFACE_2, SURFACE, ACCENT_BG
    GRID = RING
    MUTED, DIM = TXT_2, TXT_3
    AMBER, AMBER_DIM = ACCENT, "#1d3a63"       # legacy "live/notable" = the accent
    GREEN, RED = OK, ALERT
    BLUE = PURPLE = ACCENT
    TRACK = "#c9ced5"
else:
    NOTE = "#f0a73a"

NIGHT = bool(UI.get("night"))


def _to_night(hexcol):
    """Red-only version of a colour: keeps its brightness, drops green/blue (night vision)."""
    h = hexcol.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    rr = int(min(255, lum * 1.15 + 8))
    return "#%02x%02x%02x" % (rr, int(rr * 0.08), int(rr * 0.04))


def night(hexcol):
    """Pass a hardcoded colour through the night filter when night mode is on."""
    return _to_night(hexcol) if NIGHT else hexcol


if NIGHT:
    for _n in ("BG", "SURFACE", "SURFACE_2", "HOVER", "LINE", "LINE_HI", "MAPBG", "RING", "TXT",
               "TXT_2", "TXT_3", "ACCENT", "ACCENT_BG", "ALERT", "OK", "AMBER_DIM", "TRACK"):
        globals()[_n] = _to_night(globals()[_n])
    PANEL, ROW, ROW_OFF, ROW_HOT = SURFACE, SURFACE_2, SURFACE, ACCENT_BG
    GRID = RING
    MUTED, DIM = TXT_2, TXT_3
    AMBER = ACCENT
    NOTE = _to_night(NOTE)
    GREEN, RED = OK, ALERT
    BLUE = PURPLE = ACCENT

_FAM = None


def _families(root):
    global _FAM
    if _FAM is None:
        import tkinter.font as tkfont
        _FAM = set(tkfont.families(root))
    return _FAM


def fonts(root):
    import tkinter.font as tkfont
    fam = _families(root)
    want = UI["sans"]
    if STYLE == "maven" and want == DEFAULT_UI["sans"]:
        want = "IBM Plex Sans"               # the workstation look; Atkinson stays selectable
    sans = next((f for f in (want, "IBM Plex Sans", "Atkinson Hyperlegible", "DejaVu Sans")
                 if f in fam), "DejaVu Sans")
    mono = next((f for f in (UI["mono"], "IBM Plex Mono", "DejaVu Sans Mono") if f in fam),
                "DejaVu Sans Mono")
    spec = {
        "title": (sans, 14 if STYLE == "maven" else 16, "bold"),     # app name in the bar
        "h": (sans, 15, "bold"),         # panel headings
        "now": (sans, 20, "bold"),       # the one prominent value in a panel
        "big": (sans, 15, "bold"),       # primary button
        "row": (sans, 15, "normal"),
        "rowb": (sans, 15, "bold"),
        "sm": (sans, 14, "normal"),
        "smb": (sans, 14, "bold"),
        "lbl": ((mono, 10, "normal") if STYLE == "maven" else (sans, 11, "bold")),  # caps labels
        "mapb": (sans, 12, "bold"),
        "map": (mono, 12, "normal"),
        "mono": (mono, 13, "normal"),
        "monol": (mono, 15, "normal"),
        "freq": (mono, 15, "normal"),
        "data": (mono, 22, "normal"),
        "xl": (mono, 40, "normal"),
    }
    return {k: tkfont.Font(family=f, size=-px(sz), weight=w) for k, (f, sz, w) in spec.items()}


def spaced(text):
    return " ".join(text.upper())


def _mix(a, b, t):
    ah = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    bh = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ah, bh))


# ---------------------------------------------------------------- workstation embedding
# When the workstation shell is running, EMBED is the shell and every app's "root" is a
# Workspace: a frame inside the one window that answers the handful of Tk-root calls the
# apps make. Standalone (python3 ops.py) nothing here is used and each app owns a window.
EMBED = None
_WS = []
_WIDGET_EVENTS = ("<Configure", "<Destroy", "<Map", "<Unmap", "<Visibility", "<FocusIn",
                  "<FocusOut", "<Enter", "<Leave", "<Expose")


def workspace_class():
    if _WS:
        return _WS[0]
    import tkinter as tk

    class Workspace(tk.Frame):
        embedded = True

        def __init__(self, shell, parent, key, title):
            tk.Frame.__init__(self, parent, bg=BG)
            self.shell, self.key, self.ws_title = shell, key, title
            self.keys = {}            # key/wheel sequences -> handler, live only while shown
            self.alive = True
            self.on_close = None      # the app's own shutdown (stops radio, saves)
            self.bar = None           # its status bar, hosted in the shell's bar strip
            self._afters = set()
            self.cleanups = []        # stop helper threads when this workspace closes

        # keyboard and wheel shortcuts belong to whichever workspace is in front
        def bind(self, sequence=None, func=None, add=None):
            if sequence and func is not None and not sequence.startswith(_WIDGET_EVENTS):
                self.keys[sequence] = func
                self.shell.route(sequence)
                return None
            return tk.Frame.bind(self, sequence, func, add)

        # timers die with the workspace instead of firing into destroyed widgets
        def after(self, ms, func=None, *args):
            if func is None:
                return tk.Frame.after(self, ms)
            if not self.alive:
                return None           # a worker thread reporting to a closed workspace
            box = []

            def run():
                if box:               # (a worker thread's after(0) can fire before append)
                    self._afters.discard(box[0])
                if self.alive:
                    func(*args)
            try:
                box.append(tk.Frame.after(self, ms, run))
            except Exception:         # destroyed between the check and the call
                return None
            self._afters.add(box[0])
            return box[0]

        def after_cancel(self, ident):
            self._afters.discard(ident)
            try:
                tk.Frame.after_cancel(self, ident)
            except Exception:
                pass

        def mainloop(self, n=0):
            return None               # the shell runs the one event loop

        def protocol(self, name=None, func=None):
            if name == "WM_DELETE_WINDOW" and func:
                self.on_close = func

        def title(self, *a):
            return self.ws_title

        def geometry(self, *a):
            return ""

        def attributes(self, *a, **k):
            return ""

        def go_home(self):
            self.shell.show("home")

        def destroy(self):
            if not self.alive:
                return
            self.alive = False
            for ident in list(self._afters):
                try:
                    tk.Frame.after_cancel(self, ident)
                except Exception:
                    pass
            self._afters.clear()
            for fn in self.cleanups:
                try:
                    fn()
                except Exception:
                    pass
            self.cleanups = []
            self.shell.closed(self)
            if self.bar is not None:
                try:
                    self.bar.destroy()
                except Exception:
                    pass
            tk.Frame.destroy(self)

    _WS.append(Workspace)
    return Workspace


def on_workspace_close(fn):
    """Run fn() when the workspace being built right now closes, so its helper threads end
    with it. Standalone (one app, one process) this does nothing: the process exit does it."""
    sh = EMBED
    w = sh.ws.get(getattr(sh, "pending", None)) if sh is not None else None
    if w is not None and w.alive:
        w.cleanups.append(fn)


def make_root(title, parent=None):
    import tkinter as tk
    import os
    if parent is not None:
        # Render into a caller-supplied frame instead of a fresh workspace/window — used by a
        # tabbed host (e.g. the Sky shell) that embeds several modules side by side. The caller
        # is responsible for giving `parent` the workspace-like behaviour a module expects
        # (after/bind/protocol/cleanups); make_root only hands back the frame and the fonts.
        return parent, (EMBED.F if EMBED is not None else fonts(parent.winfo_toplevel()))
    if EMBED is not None:
        return EMBED.new_workspace(title), EMBED.F
    root = tk.Tk()
    root.title(title)
    root.configure(bg=BG)
    # Fill the real screen. On the uConsole the native 720x1280 panel is rotated
    # to 1280x720 and presented via labwc/Xwayland, where "-zoomed" is unreliable
    # and labwc otherwise adds a titlebar that pushes the window off the bottom
    # (clipping the map and low dropdowns). "-fullscreen" (NET_WM_STATE_FULLSCREEN)
    # is honored reliably and removes decorations. Set UCS_NO_FULLSCREEN=1 on a
    # desktop to run windowed; F11 toggles either way.
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry("%dx%d+0+0" % (sw, sh))
    if not os.environ.get("UCS_NO_FULLSCREEN"):
        try:
            root.attributes("-fullscreen", True)
        except tk.TclError:
            try:
                root.attributes("-zoomed", True)   # X11 desktop fallback
            except tk.TclError:
                pass

    def _toggle_fs(_=None):
        try:
            root.attributes("-fullscreen", not bool(root.attributes("-fullscreen")))
        except tk.TclError:
            pass
    root.bind("<F11>", _toggle_fs)
    root.update_idletasks()
    return root, fonts(root)


# ---------------------------------------------------------------- controls

def btn(parent, text, cmd, F, fg=None, bg=None, font="sm", padx=12, pady=5, kind="ghost"):
    """Compact button. kind: ghost (hairline), primary (accent outline), danger (red outline),
    quiet (text only)."""
    import tkinter as tk
    b = tk.Label(parent, text=text, font=F[font if font in F else "sm"], padx=px(padx), pady=px(pady),
                 cursor="hand2", highlightthickness=1)
    b._fg = fg if fg not in (None,) else None
    b.bind("<Button-1>", lambda e: cmd())
    b.bind("<Enter>", lambda e: b.config(bg=HOVER))
    b.bind("<Leave>", lambda e: b.config(bg=b._bg))
    set_btn(b, kind=kind)
    return b


def set_btn(b, text=None, kind=None):
    if kind:
        b._kind = kind
        flat = STYLE == "maven" and not NIGHT
        look = {
            "ghost": ((getattr(b, "_fg", None) or TXT, SURFACE_2, SURFACE_2) if flat else
                      (getattr(b, "_fg", None) or TXT, SURFACE, LINE)),
            "primary": ((TXT, FILL, FILL) if flat else (ACCENT, SURFACE, ACCENT)),
            "danger": ((TXT, "#a5282d", "#a5282d") if flat else (ALERT, SURFACE, ALERT)),
            "quiet": (TXT_2, SURFACE, SURFACE),
            "busy": (TXT_3, SURFACE, LINE),
        }[kind]
        b._bg = look[1]
        b.config(fg=look[0], bg=look[1], highlightbackground=look[2], highlightcolor=look[2])
    if text is not None:
        b.config(text=text)


class Tag:
    """Status chip: coloured dot + text. config(text=, bg=) where bg picks the dot colour."""

    def __init__(self, parent, F, text="", bg=DIM, side="left"):
        import tkinter as tk
        pbg = parent.cget("bg")
        self.f = tk.Frame(parent, bg=pbg)
        if STYLE == "maven":
            self.f.config(highlightthickness=1, highlightbackground=LINE, padx=px(6), pady=1)
        d = px(7)
        self.dot = tk.Canvas(self.f, width=d, height=d, bg=pbg, highlightthickness=0)
        self._d = d
        self.dot.pack(side="left", padx=(0, 6))
        self.lbl = tk.Label(self.f, text="", font=F["map"] if STYLE == "maven" else F["sm"],
                            bg=pbg, fg=TXT_2)
        self.lbl.pack(side="left")
        self.f.pack(side=side, padx=(8 if STYLE == "maven" else 18, 0))
        self._col = None
        self.config(text=text, bg=bg)

    def config(self, text=None, bg=None, **_):
        if text is not None:
            self.lbl.config(text=text)
        if bg is not None and bg != self._col:
            self._col = bg
            self.dot.delete("all")
            off = bg in (DIM, TXT_3)
            self.dot.create_oval(1, 1, self._d - 1, self._d - 1, fill="" if off else bg,
                                 outline=TXT_3 if off else bg)
            self.lbl.config(fg=TXT_2 if off or bg == OK else (bg if bg in (ALERT, ACCENT) else TXT))

    configure = config


def brackets(*a, **k):
    return []


def panel(parent, bg=SURFACE, border=LINE, **kw):
    import tkinter as tk
    return tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=border, **kw)


def section(parent, F, text, fg=None, bg=None, right=""):
    """Small tracked-caps label + optional right-side note."""
    import tkinter as tk
    bg = bg or parent.cget("bg")
    f = tk.Frame(parent, bg=bg)
    tk.Label(f, text=spaced(text), font=F["lbl"], fg=fg or TXT_3, bg=bg).pack(side="left")
    r = tk.Label(f, text=right, font=F["lbl"], fg=TXT_3, bg=bg)
    r.pack(side="right")
    f.right = r
    return f


def divider(parent, pad=0):
    import tkinter as tk
    d = tk.Frame(parent, bg=LINE, height=1)
    d.pack(fill="x", pady=pad)
    return d


def top_bar(root, F, title, subtitle=""):
    """Thin status bar: Title  context ........ chips ........ 20:41:00 L  0341Z"""
    import tkinter as tk
    tb = BG if STYLE == "maven" else SURFACE
    emb = getattr(root, "embedded", False)
    if emb:                         # one bar for the whole window: the shell swaps them
        wrap = tk.Frame(root.shell.barhost, bg=tb)
        root.bar = wrap
    else:
        wrap = tk.Frame(root, bg=tb)
        wrap.pack(fill="x")
    top = tk.Frame(wrap, bg=tb)
    top.pack(fill="x", padx=12, pady=6 if STYLE == "maven" else 7)
    if STYLE == "maven":
        mk = tk.Canvas(top, width=px(14), height=px(14), bg=tb, highlightthickness=0)
        mk.pack(side="left", padx=(0, 8))
        q = px(14)
        mk.create_polygon(q / 2, 1, q - 1, q / 2, q / 2, q - 1, 1, q / 2, outline=ACCENT, fill="")
        mk.create_polygon(q / 2, q * .3, q * .7, q / 2, q / 2, q * .7, q * .3, q / 2, fill=ACCENT,
                          outline="")
        if emb:                     # the mark is the way home
            mk.config(cursor="hand2")
            mk.bind("<Button-1>", lambda e: root.shell.show("home"))
        title = title.upper()
    tk.Label(top, text=title, font=F["title"], fg=TXT, bg=tb).pack(side="left")
    if subtitle:
        tk.Label(top, text=subtitle, font=F["map"] if STYLE == "maven" else F["sm"], fg=TXT_3,
                 bg=tb).pack(side="left", padx=(10, 0))
    clk = tk.Label(top, text="", font=F["map"] if STYLE == "maven" else F["mono"], fg=TXT_2,
                   bg=tb)
    clk.pack(side="right")

    def tick():
        now = time.time()
        if STYLE == "maven":
            clk.config(text=time.strftime("%d%b%Y %H:%M:%SZ", time.gmtime(now)).upper())
        else:
            clk.config(text="%s L   %sZ" % (time.strftime("%H:%M:%S", time.localtime(now)),
                                            time.strftime("%H%M", time.gmtime(now))))
        clk.after(1000, tick)
    tick()
    if not emb:
        tk.Frame(root, bg=LINE, height=1).pack(fill="x")
    return top


def entry(parent, F, width=20, font="mono"):
    import tkinter as tk
    return tk.Entry(parent, font=F[font], width=width, bg=SURFACE_2, fg=TXT, insertbackground=ACCENT,
                    relief="flat", highlightthickness=1, highlightbackground=LINE,
                    highlightcolor=LINE_HI, selectbackground=ACCENT_BG)


# ---------------------------------------------------------------- map helpers

def scope_grid(cv, w, h, step=None):
    """No grid in this style - kept for API compatibility."""
    return


def range_ring(cv, cx, cy, r, label, F):
    cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=RING)
    cv.create_text(cx + 4, cy - r - 2, text=label, fill=TXT_3, font=F["map"], anchor="sw")


def scale_bar(cv, x, y, px_per_nm, F, unit="nm"):
    """Bottom-left scale bar at a round distance (px_per_nm is px per unit)."""
    nm = 100
    for n in (1, 2, 5, 10, 20, 50, 100):
        if n * px_per_nm >= 70:
            nm = n
            break
    L = nm * px_per_nm
    cv.create_line(x, y, x + L, y, fill=TXT_3)
    cv.create_line(x, y - 4, x, y + 1, fill=TXT_3)
    cv.create_line(x + L, y - 4, x + L, y + 1, fill=TXT_3)
    cv.create_text(x + L + 6, y, text="%d %s" % (nm, unit), fill=TXT_3, font=F["map"], anchor="w")


# ---------------------------------------------------------------- detail graphics

def compass_ring(cv, cx, cy, r, F, labels=True, color=None):
    """Bearing ring: minor ticks every 5°, major every 30° with 3-digit labels."""
    import math
    col = color or night("#2a3238")
    for a in range(0, 360, 5):
        rad = math.radians(a)
        L = 9 if a % 30 == 0 else (5 if a % 10 == 0 else 3)
        x1, y1 = cx + r * math.sin(rad), cy - r * math.cos(rad)
        x2, y2 = cx + (r - L) * math.sin(rad), cy - (r - L) * math.cos(rad)
        cv.create_line(x1, y1, x2, y2, fill=night("#3a434a") if a % 30 == 0 else col)
        if labels and a % 30 == 0:
            xt, yt = cx + (r + 11) * math.sin(rad), cy - (r + 11) * math.cos(rad)
            cv.create_text(xt, yt, text="%03d" % a, fill=TXT_3, font=F["map"])


def sparkline(cv, x, y, w, h, values, color=None, fill=None, vmax=None, bars=False):
    """Tiny line or bar chart in the box (x, y, w, h)."""
    vals = [v for v in values if v is not None]
    if not vals:
        cv.create_line(x, y + h, x + w, y + h, fill=LINE)
        return
    top = vmax or max(max(vals), 1e-9)
    n = len(values)
    if bars:
        bw = w / max(n, 1)
        for i, v in enumerate(values):
            if not v:
                continue
            bh = max(1, h * min(v, top) / top)
            cv.create_rectangle(x + i * bw, y + h - bh, x + (i + 1) * bw - 1, y + h,
                                fill=color or TXT_3, outline="")
        return
    pts = []
    for i, v in enumerate(values):
        if v is None:
            continue
        pts += [x + w * i / max(n - 1, 1), y + h - h * min(v, top) / top]
    if fill and len(pts) >= 4:
        cv.create_polygon(pts[0], y + h, *pts, pts[-2], y + h, fill=fill, outline="")
    if len(pts) >= 4:
        cv.create_line(*pts, fill=color or TXT_2, width=1.2)


def arc_gauge(cv, cx, cy, r, frac, F, label="", value="", color=None, warn=None):
    """240° arc gauge with tick marks."""
    import math
    frac = max(0.0, min(1.0, frac or 0))
    start, extent = 210, -240
    cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=extent, style="arc",
                  outline=LINE, width=6)
    col = color or (warn if warn else TXT)
    if frac > 0:
        cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=extent * frac,
                      style="arc", outline=col, width=6)
    for i in range(0, 11):
        a = math.radians(start + extent * i / 10)
        r1, r2 = r + 6, r + (11 if i % 5 == 0 else 8)
        cv.create_line(cx + r1 * math.cos(a), cy - r1 * math.sin(a),
                       cx + r2 * math.cos(a), cy - r2 * math.sin(a), fill=TXT_3)
    cv.create_text(cx, cy - 2, text=value, fill=TXT, font=F["data"])
    cv.create_text(cx, cy + r * 0.62, text=label, fill=TXT_3, font=F["map"])


def level_bar(cv, x, y, w, h, frac, segments=20, color=None):
    """Segmented level meter."""
    frac = max(0.0, min(1.0, frac or 0))
    sw = w / segments
    lit = int(round(frac * segments))
    for i in range(segments):
        on = i < lit
        c = (ALERT if i >= segments * 0.9 else (color or ACCENT)) if on else LINE
        cv.create_rectangle(x + i * sw, y, x + (i + 1) * sw - 2, y + h, fill=c, outline="")


def help_overlay(root, F, title, pairs, extra=""):
    """A dismissible panel of keyboard shortcuts. pairs = [(key, description), ...]."""
    import tkinter as tk
    win = tk.Toplevel(root, bg=SURFACE)
    win.title(title)
    win.transient(root)
    win.configure(highlightthickness=1, highlightbackground=LINE_HI)
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass
    pad = tk.Frame(win, bg=SURFACE, padx=px(26), pady=px(20))
    pad.pack(fill="both", expand=True)
    tk.Label(pad, text=spaced(title), font=F["lbl"], fg=TXT_3, bg=SURFACE).pack(anchor="w", pady=(0, px(12)))
    grid = tk.Frame(pad, bg=SURFACE)
    grid.pack(fill="both", expand=True)
    half = (len(pairs) + 1) // 2
    cols = (pairs[:half], pairs[half:])
    for ci, col in enumerate(cols):
        cf = tk.Frame(grid, bg=SURFACE)
        cf.grid(row=0, column=ci, sticky="nw", padx=(0, px(28)))
        for key, desc in col:
            r = tk.Frame(cf, bg=SURFACE)
            r.pack(fill="x", pady=px(3))
            kb = tk.Label(r, text=key, font=F["mono"], fg=ACCENT, bg=SURFACE_2, padx=px(8), pady=px(2),
                          width=6)
            kb.pack(side="left")
            tk.Label(r, text=desc, font=F["sm"], fg=TXT, bg=SURFACE, anchor="w").pack(side="left",
                                                                                      padx=(px(10), 0))
    if extra:
        tk.Label(pad, text=extra, font=F["map"], fg=TXT_3, bg=SURFACE, justify="left",
                 wraplength=px(440)).pack(anchor="w", pady=(px(14), 0))
    tk.Label(pad, text="Press ? or Esc to close", font=F["map"], fg=TXT_3, bg=SURFACE).pack(
        anchor="w", pady=(px(14), 0))

    def close(e=None):
        win.destroy()
    win.bind("<Escape>", close)
    win.bind("?", close)
    win.bind("<Button-1>", close)
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    x = root.winfo_rootx() + (root.winfo_width() - w) // 2
    y = root.winfo_rooty() + (root.winfo_height() - h) // 2
    win.geometry("+%d+%d" % (max(0, x), max(0, y)))
    win.focus_set()
    return win


def sheet(anchor, F, title, build, side="below"):
    """Inline popover placed INSIDE the window (never a separate top-level, so Wayland/Xwayland
    can't lose it off-screen or leave it stuck). build(frame) fills it. Returns a Frame with
    .close(), .rebuild() and .winfo_exists(); dismissed by the X, by tapping outside, or by
    re-tapping the button that opened it."""
    import tkinter as tk
    root = anchor.winfo_toplevel()
    panel = tk.Frame(root, bg=SURFACE, highlightthickness=1, highlightbackground=LINE_HI)
    state = {"bindid": None, "closed": False, "arming": False}

    def _inside(w):
        # True if widget w is the panel, the anchor, or a descendant of either
        while w is not None:
            if w is panel or w is anchor:
                return True
            try:
                w = w.master
            except AttributeError:
                return False
        return False

    def _outside_press(e):
        if not _inside(e.widget):
            close()

    def close(e=None):
        state["closed"] = True
        try:
            if state["bindid"] is not None:
                root.unbind("<Button-1>", state["bindid"])
                state["bindid"] = None
            panel.place_forget()
            panel.destroy()
        except tk.TclError:
            pass

    def render():
        for c in list(panel.winfo_children()):
            c.destroy()
        pad = tk.Frame(panel, bg=SURFACE, padx=px(12), pady=px(10))
        pad.pack(fill="both", expand=True)
        hdr = tk.Frame(pad, bg=SURFACE)
        hdr.pack(fill="x", pady=(0, px(6)))
        if title:
            tk.Label(hdr, text=spaced(title), font=F["lbl"], fg=TXT_3, bg=SURFACE).pack(side="left")
        xb = tk.Label(hdr, text="✕", font=F["smb"], fg=TXT_2, bg=SURFACE, cursor="hand2", padx=px(8))
        xb.pack(side="right")
        xb.bind("<Button-1>", close)
        body = tk.Frame(pad, bg=SURFACE)
        body.pack(fill="both", expand=True)
        build(body)
        _place()

    def _place():
        panel.update_idletasks()
        pw, ph = panel.winfo_reqwidth(), panel.winfo_reqheight()
        rw, rh = root.winfo_width(), root.winfo_height()
        ax = anchor.winfo_rootx() - root.winfo_rootx()
        ay = anchor.winfo_rooty() - root.winfo_rooty()
        aw, ah = anchor.winfo_width(), anchor.winfo_height()
        if side == "left":
            x, y = ax - pw - px(4), ay
        elif side == "right":
            x, y = ax + aw - pw, ay + ah + px(4)
        else:
            x, y = ax, ay + ah + px(4)
        x = max(px(4), min(x, rw - pw - px(4)))
        y = max(px(4), min(y, rh - ph - px(4)))
        panel.place(x=x, y=y)
        panel.lift()
        # arm tap-outside-to-dismiss after this turn's click has already propagated,
        # so the very click that opened the sheet doesn't immediately close it
        if state["bindid"] is None and not state["arming"]:
            state["arming"] = True
            root.after(1, _arm)

    def _arm():
        # skip if the sheet was closed (fast double-tap) before this ran: a binding made now
        # would never be removed and would call close() on a dead panel at every click
        state["arming"] = False
        if not state["closed"] and state["bindid"] is None:
            state["bindid"] = root.bind("<Button-1>", _outside_press, add="+")

    panel.close = close
    panel.rebuild = render
    render()
    return panel
