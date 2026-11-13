#!/usr/bin/env python3
"""Sky — tabbed airspace workspace (Phase 1b).

Hosts the existing airspace modules as tabs: Aircraft (ADS-B radar + ATC voice, sky_app) and
Balloons (NWS radiosondes, balloons). Phase 2's dronewatch lands here as one more tab.

Thin shell: each tab renders an unmodified module into its own workspace-like frame, keeping
its own radio lease and worker thread. Tabs are built LAZILY — only when first opened — so the
uConsole never spins up two heavy radios/UIs at once (power + the single built-in SDR). Add a
tab by appending to TABS; nothing else changes.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import suite as S  # noqa: E402

TABS = [
    ("Aircraft", "sky_app", "run_gui"),
    ("Balloons", "balloons", "main"),
    ("DroneWatch", "dronewatch", "main"),
]


class _TabShell:
    """Minimal 'shell' so each tab can be a theme Workspace (giving the embedded module the
    after/bind/protocol/cleanup behaviour it expects) without being a top-level hub workspace.
    Keyboard shortcuts route to the front tab, and only while the Sky workspace itself is in
    front (so a hidden Sky doesn't steal keys from another hub workspace)."""

    def __init__(self, root, host_shell, my_key):
        self.root = root                # real top-level, for key bindings
        self.host_shell = host_shell    # the hub Shell (theme.EMBED) or None standalone
        self.my_key = my_key            # the Sky workspace's key in the hub
        self.tabs = {}                  # tab key -> Workspace
        self.active_tab = None
        self.routed = set()
        self.barhost = None             # where each tab's top_bar is parented; swapped on switch

    def route(self, seq):
        if seq in self.routed:
            return
        self.routed.add(seq)
        # add="+" so we never clobber the hub's own binding for the same sequence.
        self.root.bind(seq, lambda e, q=seq: self._dispatch(q, e), add="+")

    def _dispatch(self, seq, e):
        if self.host_shell is not None and getattr(self.host_shell, "active", None) != self.my_key:
            return None                 # another hub workspace is in front — don't steal keys
        w = self.tabs.get(self.active_tab)
        fn = w.keys.get(seq) if (w is not None and w.alive) else None
        return fn(e) if fn else None

    def closed(self, w):
        for k, ws in list(self.tabs.items()):
            if ws is w:
                del self.tabs[k]
        if self.active_tab == getattr(w, "key", None):
            self.active_tab = None

    def show(self, key):
        # go_home from inside a tab bubbles up to the hub; standalone there is no home.
        if self.host_shell is not None:
            self.host_shell.show(key)


def main(parent=None):
    if parent is None:
        S.single_instance("Sky")
    root, F = S.make_root("Sky", parent=parent)
    import tkinter as tk
    T = S.T
    EMBED = T.EMBED
    sky_key = getattr(root, "key", None)
    tabshell = _TabShell(root.winfo_toplevel(), EMBED, sky_key)

    # Fixed tab bar first, then the expanding body (pack fixed bars before content — clip bug).
    barrow = tk.Frame(root, bg=T.SURFACE)
    barrow.pack(side="top", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="top", fill="x")
    barhost = tk.Frame(root, bg=S.BG)       # each tab's own top_bar lives here; swapped on switch
    barhost.pack(side="top", fill="x")
    tabshell.barhost = barhost
    body = tk.Frame(root, bg=S.BG)
    body.pack(side="top", fill="both", expand=True)

    tabs = []     # dicts: label, mod, entry, frame, btn, ws, built

    def build_tab(t):
        if t["built"]:
            return
        t["built"] = True
        import importlib
        key = "sky:" + t["label"].lower()
        ws = T.workspace_class()(tabshell, t["frame"], key, t["label"])
        ws.pack(fill="both", expand=True)
        tabshell.tabs[key] = ws
        t["ws"] = ws
        # Point EMBED.pending at the Sky workspace so a module's on_workspace_close() registers
        # its thread-stop there — tabs persist for Sky's lifetime, so they end when Sky closes.
        prev = getattr(EMBED, "pending", None) if EMBED is not None else None
        if EMBED is not None:
            EMBED.pending = sky_key
        try:
            getattr(importlib.import_module(t["mod"]), t["entry"])(parent=ws)
        except Exception as e:
            import traceback
            try:
                with S.errfile(os.path.join(S.CACHE, "sky_%s.err" % t["label"].lower())) as fh:
                    traceback.print_exc(file=fh)
            except Exception:
                traceback.print_exc()
            tk.Label(ws, text="%s failed to load: %s" % (t["label"], str(e)[:80]),
                     bg=S.BG, fg=S.RED, font=F["sm"]).pack(pady=20)
        finally:
            if EMBED is not None:
                EMBED.pending = prev

    def show_tab(i):
        for j, t in enumerate(tabs):
            if j != i:
                t["frame"].pack_forget()
                ows = t.get("ws")
                if ows is not None and getattr(ows, "bar", None) is not None:
                    ows.bar.pack_forget()
                T.set_btn(t["btn"], kind="ghost")
        t = tabs[i]
        build_tab(t)
        t["frame"].pack(fill="both", expand=True)
        ws = t.get("ws")
        if ws is not None and getattr(ws, "bar", None) is not None:
            ws.bar.pack(fill="x")           # show this tab's top bar in the shared bar strip
        T.set_btn(t["btn"], kind="primary")
        if ws is not None:
            tabshell.active_tab = ws.key
            try:
                ws.focus_set()
            except Exception:
                pass

    def add_tab(label, mod, entry):
        i = len(tabs)
        frame = tk.Frame(body, bg=S.BG)
        btn = S.btn(barrow, label, lambda idx=i: show_tab(idx), F, padx=14, pady=5, kind="ghost")
        btn.pack(side="left", padx=((8 if i == 0 else 2), 2), pady=5)
        tabs.append({"label": label, "mod": mod, "entry": entry, "frame": frame,
                     "btn": btn, "ws": None, "built": False})

    for label, mod, entry in TABS:
        add_tab(label, mod, entry)

    def on_close():
        # Stop each built tab (its on_close releases the radio + saves), wait for the single
        # SDR to be handed back, then tear down.
        import time as _t
        for t in tabs:
            ws = t.get("ws")
            if ws is not None and ws.alive:
                try:
                    (ws.on_close or ws.destroy)()
                except Exception:
                    pass
                if ws.alive:
                    try:
                        ws.destroy()
                    except Exception:
                        pass
        t0 = _t.time()
        while S.radio_holder() is not None and _t.time() - t0 < 10:
            _t.sleep(0.1)
        try:
            root.destroy()
        except Exception:
            pass

    S.bind_quit(root, on_close)
    show_tab(0)      # build + show Aircraft; Balloons builds on first tap
    if os.environ.get("SKY_BUILD_ALL"):      # test hook: force every tab to build now
        for t in tabs:
            build_tab(t)
    root.mainloop()


if __name__ == "__main__":
    main()
