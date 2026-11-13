#!/usr/bin/env python3
"""headless.py — remote/headless mode: web dashboard + JSON API + webhook alerts (Phase 7 #7).

For a field-deployed box left on site and watched remotely: a small Flask server exposes a status
dashboard and a JSON API (/api/status, /api/contacts), and alerts can be pushed out via webhook.
Data is supplied by injected provider callbacks, so the server is decoupled from the suite and
unit-testable (Flask test client). Read-only HTTP; bind to localhost/VPN in the field.
"""
import json
import os
import sys
import time
import urllib.request


def dashboard_html():
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Sentry</title>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>body{font:14px system-ui,sans-serif;background:#0c1014;color:#e8eaed;margin:0;"
        "padding:1.2em}h1{font-size:18px}table{border-collapse:collapse;width:100%}"
        "td,th{border-bottom:1px solid #223;padding:5px 8px;text-align:left;font-size:12px}"
        ".tag{color:#e8a33d}</style></head><body><h1>Sentry — remote</h1>"
        "<div id='status'>loading…</div><h2>Contacts</h2><table id='contacts'></table>"
        "<script>async function tick(){"
        "let s=await (await fetch('/api/status')).json();"
        "document.getElementById('status').textContent="
        "'active '+(s.active_contacts||0)+' · '+(s.radio||'')+' · '+new Date().toLocaleTimeString();"
        "let c=await (await fetch('/api/contacts')).json();"
        "document.getElementById('contacts').innerHTML=c.contacts.map(x=>"
        "'<tr><td class=tag>'+(x.id||'?')+'</td><td>'+(x.type||'')+'</td><td>'+"
        "(x.lat!=null?x.lat.toFixed(3)+','+x.lon.toFixed(3):'')+'</td></tr>').join('');"
        "}tick();setInterval(tick,5000);</script></body></html>")


def make_app(providers=None):
    """Build the Flask app. providers: {'status': ()->dict, 'contacts': ()->list}."""
    from flask import Flask, jsonify, Response
    providers = providers or {}
    app = Flask("sentry-remote")

    @app.route("/")
    def index():
        return Response(dashboard_html(), mimetype="text/html")

    @app.route("/health")
    def health():
        return jsonify({"ok": True, "ts": time.time()})

    @app.route("/api/status")
    def status():
        return jsonify((providers.get("status") or (lambda: {}))())

    @app.route("/api/contacts")
    def contacts():
        return jsonify({"contacts": (providers.get("contacts") or (lambda: []))()})

    return app


def webhook_payload(alert, source="sentry"):
    return {"text": str(alert), "source": source, "ts": time.time()}


def post_webhook(url, alert, poster=None, timeout=5):
    """POST an alert to a webhook URL. poster injectable for tests. Returns True on success."""
    if not url:
        return False
    data = json.dumps(webhook_payload(alert)).encode()
    if poster is not None:
        return bool(poster(url, data))
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def serve(app, host="127.0.0.1", port=8731):
    """Blocking server (use in a thread). Returns the werkzeug server for clean shutdown."""
    from werkzeug.serving import make_server
    srv = make_server(host, port, app)
    srv.serve_forever()
    return srv


def main(parent=None):
    import threading
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Headless")
    s, spath = S.settings("headless", {"host": "127.0.0.1", "port": 8731, "webhook": ""})
    root, F = S.make_root("Remote Mode", parent=parent)
    import tkinter as tk
    T = S.T
    st = {"srv": None}

    def providers_status():
        return {"active_contacts": 0, "radio": S.radio_holder() or "idle",
                "time": time.strftime("%H:%M:%S")}
    app = make_app({"status": providers_status, "contacts": lambda: []})

    S.top_bar(root, F, "Remote Mode", "Web dashboard + API + webhook alerts")
    status = tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["mono"], anchor="w", justify="left",
                      wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
                      text="Stopped. Serves a dashboard + /api/status + /api/contacts for remote "
                           "monitoring; pushes alerts to a webhook.")
    status.pack(fill="both", expand=True)

    def toggle():
        if st["srv"]:
            try:
                st["srv"].shutdown()
            except Exception:
                pass
            st["srv"] = None
            status.config(text="Stopped.")
            return
        from werkzeug.serving import make_server
        host, port = s.get("host", "127.0.0.1"), int(s.get("port", 8731))
        try:
            srv = make_server(host, port, app)
        except OSError as e:
            status.config(text="Could not bind %s:%d — %s" % (host, port, e), fg=S.RED)
            return
        st["srv"] = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        status.config(text="Serving at http://%s:%d/  (dashboard + API)" % (host, port), fg=S.GREEN)

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "Start/Stop server", toggle, F, padx=14, pady=5, kind="primary").pack(
        side="left", padx=(10, 6), pady=6)

    def on_close():
        if st["srv"]:
            try:
                st["srv"].shutdown()
            except Exception:
                pass
        try:
            S.save_json(spath, s)
        except Exception:
            pass
        root.destroy()
    S.bind_quit(root, on_close)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
