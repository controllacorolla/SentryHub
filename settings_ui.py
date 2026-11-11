"""Shared in-app settings editor: a typed form built from a small schema, so no app needs a
JSON file opened in a text editor.

    schema = [
        ("Section title", [
            {"key": "airband_device", "label": "Airband radio", "type": "choice",
             "choices": [("rtlsdr", "Built-in SDR"), ("hackrf", "H4M")], "help": "..."},
            {"key": "hackrf.lna", "label": "H4M LNA gain", "type": "int", "min": 0, "max": 40, "step": 8},
            {"key": "watch", "label": "Watch list", "type": "list", "help": "callsigns, comma separated"},
            {"key": "channels", "label": "Channels", "type": "table",
             "columns": [("freq", "MHz", "float"), ("label", "Label", "str"), ("on", "On", "bool")]},
        ]),
    ]
    open_settings(root, F, "Sky settings", schema, data, on_save)

Keys use dots for nested dicts.  on_save receives a new dict (the original is not mutated).
Field types: bool, int, float, str, text (multi-line), choice, list (comma separated strings),
numlist (comma separated numbers), table (list of dicts with typed columns).
"""
import copy
import json

import theme as T


def _get(d, key):
    cur = d
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set(d, key, value):
    parts = key.split(".")
    cur = d
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _coerce(kind, text):
    text = text.strip()
    if kind == "int":
        return int(round(float(text)))
    if kind == "float":
        return float(text)
    if kind == "bool":
        return text.lower() in ("1", "true", "yes", "on", "y")
    return text


class _Table:
    """Editable rows of typed cells with add/delete; lives inside the form."""

    def __init__(self, parent, F, field, rows, on_dirty):
        import tkinter as tk
        self.tk, self.F, self.field, self.on_dirty = tk, F, field, on_dirty
        self.cols = field["columns"]
        self.frame = tk.Frame(parent, bg=T.SURFACE)
        self.rows = []
        hdr = tk.Frame(self.frame, bg=T.SURFACE)
        hdr.pack(fill="x")
        for key, label, kind in self.cols:
            tk.Label(hdr, text=label, font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w",
                     width=self._width(kind, key)).pack(side="left", padx=(0, 6))
        self.body = tk.Frame(self.frame, bg=T.SURFACE)
        self.body.pack(fill="x")
        for r in rows or []:
            self._add_row(r)
        foot = tk.Frame(self.frame, bg=T.SURFACE)
        foot.pack(fill="x", pady=(4, 0))
        T.btn(foot, "+ Add row", lambda: (self._add_row(dict(field.get("template", {}))), on_dirty()),
              F, padx=8, pady=2, kind="quiet").pack(side="left")

    def _width(self, kind, key):
        if kind == "bool":
            return 4
        if kind in ("int", "float"):
            return 8
        if key in ("url", "system", "text"):
            return 24
        return 14 if key in ("label", "name", "model") else 7

    def _add_row(self, r):
        tk = self.tk
        row = tk.Frame(self.body, bg=T.SURFACE)
        row.pack(fill="x", pady=1)
        cells = {}
        for key, label, kind in self.cols:
            val = r.get(key, "")
            if kind == "bool":
                b = T.btn(row, "on" if val else "off", None, self.F, padx=6, pady=1,
                          kind="primary" if val else "quiet")
                b.state = bool(val)

                def flip(b=b):
                    b.state = not b.state
                    T.set_btn(b, "on" if b.state else "off", "primary" if b.state else "quiet")
                    self.on_dirty()
                b.bind("<Button-1>", lambda e, f=flip: f())
                b.pack(side="left", padx=(0, 6))
                cells[key] = ("bool", b)
            else:
                e = T.entry(row, self.F, width=self._width(kind, key), font="mono" if kind != "str" else "map")
                e.insert(0, ("%g" % val) if isinstance(val, float) else str(val))
                e.bind("<KeyRelease>", lambda ev: self.on_dirty())
                e.pack(side="left", padx=(0, 6), ipady=2)
                cells[key] = (kind, e)
        T.btn(row, "×", lambda: self._del_row(row), self.F, padx=6, pady=1, kind="quiet").pack(side="left")
        self.rows.append((row, cells))

    def _del_row(self, row):
        self.rows = [(r, c) for r, c in self.rows if r is not row]
        row.destroy()
        self.on_dirty()

    def value(self):
        out = []
        for _, cells in self.rows:
            d = {}
            for key, (kind, w) in cells.items():
                if kind == "bool":
                    d[key] = w.state
                else:
                    raw = w.get()
                    if raw.strip() == "" and kind in ("int", "float"):
                        raise ValueError("'%s' needs a number" % key)
                    d[key] = _coerce(kind, raw)
            out.append(d)
        return out


def open_settings(root, F, title, schema, data, on_save, width=720, path=None):
    """Open the editor window. Returns the Toplevel."""
    import tkinter as tk
    win = tk.Toplevel(root, bg=T.SURFACE)
    win.title(title)
    win.transient(root)
    win.geometry("%dx%d+%d+%d" % (max(320, min(T.px(width), root.winfo_width() - 60)),
                                    max(240, min(root.winfo_height() - 100, T.px(560))),
                                  root.winfo_rootx() + 30, root.winfo_rooty() + 40))
    work = copy.deepcopy(data)

    # scrollable body
    outer = tk.Frame(win, bg=T.SURFACE)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=T.SURFACE, highlightthickness=0)
    sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview, bg=T.SURFACE, troughcolor=T.SURFACE,
                      activebackground=T.LINE_HI, bd=0, highlightthickness=0, width=T.px(10))
    body = tk.Frame(canvas, bg=T.SURFACE)
    body_id = canvas.create_window((0, 0), window=body, anchor="nw")
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    def on_cfg(e=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfig(body_id, width=canvas.winfo_width())
    body.bind("<Configure>", on_cfg)
    canvas.bind("<Configure>", on_cfg)
    # bound on the window, not bind_all: inside the workstation a global binding would
    # also catch the wheel over every other workspace and outlive this window
    win.bind("<Button-4>", lambda e: canvas.yview_scroll(-3, "units"))
    win.bind("<Button-5>", lambda e: canvas.yview_scroll(3, "units"))

    pad = tk.Frame(body, bg=T.SURFACE, padx=T.px(18), pady=T.px(12))
    pad.pack(fill="both", expand=True)
    widgets = []      # (field, kind, widget/getter)
    status = tk.Label(win, text="", font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w", padx=T.px(18))
    dirty = [False]

    def mark_dirty():
        if not dirty[0]:
            dirty[0] = True
            T.set_btn(save_btn, "Save", "primary")
            status.config(text="Unsaved changes", fg=T.ACCENT)

    for section, fields in schema:
        T.section(pad, F, section).pack(fill="x", pady=(T.px(8), T.px(4)))
        for f in fields:
            kind = f.get("type", "str")
            row = tk.Frame(pad, bg=T.SURFACE)
            row.pack(fill="x", pady=(0, T.px(6)))
            row.columnconfigure(0, minsize=T.px(190))
            row.columnconfigure(1, weight=1)
            lab = tk.Frame(row, bg=T.SURFACE)
            lab.grid(row=0, column=0, sticky="nw", padx=(0, T.px(12)))
            tk.Label(lab, text=f["label"], font=F["sm"], fg=T.TXT, bg=T.SURFACE, anchor="w",
                     wraplength=T.px(180), justify="left").pack(fill="x")
            if f.get("help"):
                tk.Label(lab, text=f["help"], font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w",
                         wraplength=T.px(180), justify="left").pack(fill="x")
            val = _get(work, f["key"])
            if val is None and "default" in f:
                val = f["default"]
            ctl = tk.Frame(row, bg=T.SURFACE)
            ctl.grid(row=0, column=1, sticky="new")
            if kind == "bool":
                b = T.btn(ctl, "On" if val else "Off", None, F, padx=10, pady=2,
                          kind="primary" if val else "quiet")
                b.state = bool(val)

                def flip(b=b):
                    b.state = not b.state
                    T.set_btn(b, "On" if b.state else "Off", "primary" if b.state else "quiet")
                    mark_dirty()
                b.bind("<Button-1>", lambda e, fl=flip: fl())
                b.pack(side="left")
                widgets.append((f, kind, lambda b=b: b.state))
            elif kind == "choice":
                choices = f["choices"]
                keys = [c[0] for c in choices]
                cur = [keys.index(val) if val in keys else 0]
                b = T.btn(ctl, choices[cur[0]][1], None, F, padx=10, pady=2, kind="ghost")

                def cyc(b=b, cur=cur, choices=choices):
                    cur[0] = (cur[0] + 1) % len(choices)
                    T.set_btn(b, choices[cur[0]][1])
                    mark_dirty()
                b.bind("<Button-1>", lambda e, c=cyc: c())
                b.pack(side="left")
                widgets.append((f, kind, lambda cur=cur, keys=keys: keys[cur[0]]))
            elif kind in ("int", "float"):
                e = T.entry(ctl, F, width=10)
                e.insert(0, ("%g" % val) if val is not None else "")
                e.pack(side="left", ipady=3)
                e.bind("<KeyRelease>", lambda ev: mark_dirty())
                step = f.get("step")
                if step:
                    def nudge(d, e=e, f=f, kind=kind):
                        try:
                            v = _coerce(kind, e.get() or "0") + d
                        except ValueError:
                            return
                        if "min" in f:
                            v = max(f["min"], v)
                        if "max" in f:
                            v = min(f["max"], v)
                        e.delete(0, "end")
                        e.insert(0, "%g" % v)
                        mark_dirty()
                    T.btn(ctl, "−", lambda n=nudge, s=step: n(-s), F, padx=8, pady=2, kind="quiet").pack(
                        side="left", padx=(6, 0))
                    T.btn(ctl, "+", lambda n=nudge, s=step: n(s), F, padx=8, pady=2, kind="quiet").pack(side="left")
                if f.get("unit"):
                    tk.Label(ctl, text=f["unit"], font=F["sm"], fg=T.TXT_3, bg=T.SURFACE).pack(side="left", padx=6)
                widgets.append((f, kind, lambda e=e: e.get()))
            elif kind == "text":
                t = tk.Text(ctl, height=f.get("rows", 4), bg=T.SURFACE_2, fg=T.TXT, font=F["sm"], bd=0,
                            highlightthickness=1, highlightbackground=T.LINE, insertbackground=T.ACCENT,
                            wrap="word", padx=6, pady=4)
                t.insert("1.0", val or "")
                t.pack(fill="x")
                t.bind("<KeyRelease>", lambda ev: mark_dirty())
                widgets.append((f, kind, lambda t=t: t.get("1.0", "end").rstrip("\n")))
            elif kind in ("list", "numlist"):
                e = T.entry(ctl, F, width=40, font="sm")
                e.insert(0, ", ".join(("%g" % x) if isinstance(x, float) else str(x) for x in (val or [])))
                e.pack(fill="x", ipady=3)
                e.bind("<KeyRelease>", lambda ev: mark_dirty())
                widgets.append((f, kind, lambda e=e: e.get()))
            elif kind == "table":
                tb = _Table(ctl, F, f, val or [], mark_dirty)
                tb.frame.pack(fill="x")
                widgets.append((f, kind, tb.value))
            else:
                e = T.entry(ctl, F, width=40, font="sm")
                e.insert(0, "" if val is None else str(val))
                e.pack(fill="x", ipady=3)
                e.bind("<KeyRelease>", lambda ev: mark_dirty())
                widgets.append((f, kind, lambda e=e: e.get()))

    def collect():
        out = copy.deepcopy(work)
        for f, kind, getter in widgets:
            raw = getter()
            try:
                if kind in ("int", "float"):
                    if str(raw).strip() == "":
                        v = None if f.get("optional") else _get(work, f["key"])
                    else:
                        v = _coerce(kind, str(raw))
                        if "min" in f and v < f["min"]:
                            raise ValueError("at least %g" % f["min"])
                        if "max" in f and v > f["max"]:
                            raise ValueError("at most %g" % f["max"])
                elif kind == "list":
                    v = [x.strip() for x in str(raw).split(",") if x.strip()]
                elif kind == "numlist":
                    v = [float(x) for x in str(raw).split(",") if x.strip()]
                else:
                    v = raw
            except ValueError as e:
                raise ValueError("%s: %s" % (f["label"], e))
            _set(out, f["key"], v)
        return out

    def save(close=False):
        try:
            new = collect()
        except ValueError as e:
            status.config(text="Fix before saving - %s" % e, fg=T.ALERT)
            return
        try:
            on_save(new)
        except Exception as e:
            status.config(text="Save failed: %s" % str(e)[:100], fg=T.ALERT)
            return
        work.clear()
        work.update(new)
        dirty[0] = False
        T.set_btn(save_btn, "Saved", "ghost")
        status.config(text="Saved.", fg=T.TXT_3)
        if close:
            on_close()

    def on_close():
        win.destroy()

    bar = tk.Frame(win, bg=T.SURFACE, padx=T.px(18), pady=T.px(10))
    bar.pack(side="bottom", fill="x")
    status.pack(side="bottom", fill="x", pady=(0, 2))
    save_btn = T.btn(bar, "Saved", lambda: save(False), F, padx=14, pady=4, kind="ghost")
    save_btn.pack(side="left")
    T.btn(bar, "Save & close", lambda: save(True), F, padx=12, pady=4, kind="quiet").pack(side="left", padx=8)
    T.btn(bar, "Close", on_close, F, padx=12, pady=4, kind="quiet").pack(side="right")
    if path:
        status.config(text="Stored in %s" % path)
    win.protocol("WM_DELETE_WINDOW", on_close)
    win.bind("<Escape>", lambda e: on_close())
    return win


def dump(data):
    return json.dumps(data, indent=2)
