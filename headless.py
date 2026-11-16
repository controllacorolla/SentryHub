#!/usr/bin/env python3
"""headless.py — remote/headless mode: web dashboard + JSON API + webhook alerts (Phase 7 #7).

For a field-deployed box left on site and watched remotely: a small Flask server exposes a status
dashboard and a JSON API (/api/status, /api/contacts), and alerts can be pushed out via webhook.
Data is supplied by injected provider callbacks, so the server is decoupled from the suite and
unit-testable (Flask test client). Read-only HTTP; bind to localhost/VPN in the field.

Every route except /health needs the access token (audit C1): `Authorization: Bearer <token>`,
or `?token=<token>` on the dashboard URL (the page then sends the header itself). The token is
generated once and kept in headless.json; a server is never started without one.
"""
import hmac
import json
import os
import secrets
import sys
import time
import urllib.request

TOKEN_MIN = 16


def new_token():
    return secrets.token_urlsafe(24)


def valid_token(tok):
    return isinstance(tok, str) and len(tok) >= TOKEN_MIN and tok.isprintable() and " " not in tok


def dashboard_html():
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Sentry</title>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>body{font:14px system-ui,sans-serif;background:#0c1014;color:#e8eaed;margin:0;"
        "padding:1.2em}h1{font-size:18px}table{border-collapse:collapse;width:100%}"
        "td,th{border-bottom:1px solid #223;padding:5px 8px;text-align:left;font-size:12px}"
        ".tag{color:#e8a33d}</style></head><body><h1>Sentry — remote</h1>"
        "<div id='status'>loading…</div><h2>Contacts</h2><table id='contacts'></table>"
        # contact fields come off the air (ADS-B callsigns): build cells with textContent, never
        # innerHTML, so a crafted callsign cannot inject script into the remote dashboard (S1)
        # C1: the token arrives once in the URL; keep it in memory, drop it from the address
        # bar, send it as a header on every API call
        "<script>const TOK=new URLSearchParams(location.search).get('token')||'';"
        "history.replaceState(null,'',location.pathname);"
        "const H={headers:{'Authorization':'Bearer '+TOK}};"
        "async function tick(){"
        "let s=await (await fetch('/api/status',H)).json();"
        "document.getElementById('status').textContent="
        "(s.feed||'')+' · active '+(s.active_contacts||0)+' · '+(s.radio||'')+' · '+(s.time||'');"
        "let c=await (await fetch('/api/contacts',H)).json();"
        "let t=document.getElementById('contacts');t.replaceChildren();"
        "for(const x of c.contacts){let r=t.insertRow();"
        "for(const [v,k] of [[x.id||'?','tag'],[x.label||'',''],[x.type||'',''],"
        "[x.lat!=null?Number(x.lat).toFixed(3)+','+Number(x.lon).toFixed(3):'','']]){"
        "let d=r.insertCell();d.textContent=String(v);if(k)d.className=k;}}"
        "}tick();setInterval(tick,5000);</script></body></html>")


def make_app(providers=None, token=None):
    """Build the Flask app. providers: {'status': ()->dict, 'contacts': ()->list}.
    token: required (C1) — every route but /health answers 401 without it."""
    from flask import Flask, jsonify, Response, request, abort
    if not valid_token(token):
        raise ValueError("Remote Mode needs an access token (>= %d chars)" % TOKEN_MIN)
    providers = providers or {}
    app = Flask("sentry-remote")

    def _authorized():
        got = ""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            got = auth[7:].strip()
        elif request.path == "/":
            got = request.args.get("token", "")
        return bool(got) and hmac.compare_digest(got.encode(), token.encode())

    @app.before_request
    def _gate():
        if request.path != "/health" and not _authorized():
            abort(401)

    @app.after_request
    def _headers(resp):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'")
        return resp

    @app.route("/")
    def index():
        return Response(dashboard_html(), mimetype="text/html")

    @app.route("/health")
    def health():
        return jsonify({"ok": True})

    @app.route("/api/status")
    def status():
        return jsonify((providers.get("status") or (lambda: {}))())

    @app.route("/api/contacts")
    def contacts():
        return jsonify({"contacts": (providers.get("contacts") or (lambda: []))()})

    return app


def ensure_token(s):
    """The settings dict's token, generated (and returned as changed=True) when absent/weak."""
    tok = s.get("token")
    if valid_token(tok):
        return tok, False
    s["token"] = new_token()
    return s["token"], True


def webhook_payload(alert, source="sentry"):
    return {"text": str(alert), "source": source, "ts": time.time()}


def adsb_providers(feed, radio=lambda: "idle", now=time.time):
    """L5: real providers for Remote Mode — the ADS-B receiver (readsb/dump1090 aircraft.json via
    sky_app.AdsbFeed), the one feed this standalone process can read without the Qt event bus.
    Aircraft are served only while the feed is LIVE; a stale or absent feed serves none and the
    status says so with the data age. Returns {'status': fn, 'contacts': fn} for make_app."""
    def _snap():
        if feed is None:
            return [], "none", None
        try:
            aircraft, _trails, state, _rcv = feed.snapshot()
        except Exception:
            return [], "none", None
        data_t = getattr(feed, "data_t", None)
        return aircraft, state, (now() - data_t) if data_t else None

    def contacts():
        aircraft, state, _age = _snap()
        if state != "live":
            return []
        out = []
        for a in aircraft:
            if a.get("lat") is None or a.get("lon") is None:
                continue
            out.append({"id": a.get("hex", "?"), "label": (a.get("flight") or "").strip(),
                        "type": "aircraft", "lat": a["lat"], "lon": a["lon"],
                        "alt": a.get("alt_baro")})
        return out

    def status():
        aircraft, state, age = _snap()
        feed_txt = {"live": "ADS-B LIVE", "stale": "ADS-B STALE", "none": "ADS-B NO FEED"}.get(
            state, "ADS-B NO FEED")
        if age is not None and state != "live":
            feed_txt += " (last data %ds ago)" % int(age)
        n = len(contacts()) if state == "live" else 0
        return {"active_contacts": n, "feed": feed_txt, "feeds": {"adsb": state},
                "data_age_s": age, "radio": radio() or "idle",
                "time": time.strftime("%H:%M:%SZ", time.gmtime(now()))}
    return {"status": status, "contacts": contacts}


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


def _save_private(path, s):
    """Write headless.json readable by the owner only: it holds the access token."""
    try:
        fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(s, f, indent=1)
        os.chmod(path + ".tmp", 0o600)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def main(parent=None):
    import threading
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Headless")
    s, spath = S.settings("headless", {"host": "127.0.0.1", "port": 8731, "webhook": "", "token": ""})
    token, changed = ensure_token(s)
    if changed:
        _save_private(spath, s)
    root, F = S.make_root("Remote Mode", parent=parent)
    import tkinter as tk
    T = S.T
    st = {"srv": None}

    feed = None
    try:
        import sky_app
        feed = sky_app.AdsbFeed(list(sky_app.DEFAULT_SETTINGS.get("adsb_sources")
                                     or ["/run/readsb"]))
    except Exception:
        feed = None                      # no engine: status reports ADS-B NO FEED, never zero-as-OK
    app = make_app(adsb_providers(feed, radio=S.radio_holder), token=token)

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
        status.config(text="Serving at http://%s:%d/?token=%s\n(dashboard; the API needs "
                           "'Authorization: Bearer <token>')" % (host, port, token), fg=S.GREEN)

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "Start/Stop server", toggle, F, padx=14, pady=5, kind="primary").pack(
        side="left", padx=(10, 6), pady=6)

    def on_close():
        if feed is not None:
            feed.stopped = True          # end the ADS-B poll thread with the window
        if st["srv"]:
            try:
                st["srv"].shutdown()
            except Exception:
                pass
        _save_private(spath, s)
        root.destroy()
    S.bind_quit(root, on_close)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
