"""netpolicy — the one door for outbound HTTP (audit L3).

Every outbound request in the suite goes through `urlopen()` here. It checks a global mode,
logs the request, and tells listeners (the NET slot in the top strip) what happened:

    OFFLINE  nothing leaves the device; only loopback (readsb, ollama on 127.0.0.1) is allowed
    LAN      loopback + private / link-local addresses (a desktop on the same network)
    ONLINE   anything

The default is OFFLINE: a field device fetches nothing until the operator says so. The mode
lives in ~/.config/uconsole-suite/net.json ({"mode": "ONLINE"}); PALISADE_NET overrides it for
one process. A refused request raises NetBlocked, a URLError, so callers that already handle a
dead network keep working and show their own "offline" state.

No third-party or Tk imports: the Qt pages and the legacy Tk apps both use this module.
"""
import collections
import ipaddress
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MODES = ("OFFLINE", "LAN", "ONLINE")
DEFAULT_MODE = "OFFLINE"

_lock = threading.Lock()
_log = collections.deque(maxlen=200)          # (t, mode, verdict, host, purpose)
_listeners = []
_override = None                              # set_mode(..., persist=False) for this process


class NetBlocked(urllib.error.URLError):
    """The network mode refused this request. A URLError, so `except URLError` still works."""

    def __init__(self, host, mode, purpose=""):
        self.host, self.mode, self.purpose = host, mode, purpose
        super().__init__("NET %s: %s blocked (%s)" % (mode, host or "?", purpose or "request"))


def _cfg_path():
    return os.path.join(os.path.expanduser("~"), ".config", "uconsole-suite", "net.json")


def mode():
    """The current mode. An unreadable or unknown setting reads as OFFLINE (fail closed)."""
    if _override in MODES:
        return _override
    env = (os.environ.get("PALISADE_NET") or "").strip().upper()
    if env:
        return env if env in MODES else DEFAULT_MODE
    try:
        with open(_cfg_path()) as f:
            m = str(json.load(f).get("mode", DEFAULT_MODE)).strip().upper()
        return m if m in MODES else DEFAULT_MODE
    except (OSError, ValueError, AttributeError):
        return DEFAULT_MODE


def set_mode(m, persist=True):
    """Set the mode (the NET slot calls this). persist=False changes it for this process only."""
    global _override
    m = str(m).strip().upper()
    if m not in MODES:
        raise ValueError("unknown network mode %r" % m)
    if persist:
        path = _cfg_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"mode": m}, f)
        os.replace(tmp, path)
        _override = None
    else:
        _override = m
    _notify(("mode", m, "", ""))
    return m


def reset_for_tests():
    global _override
    _override = None
    with _lock:
        _log.clear()
        del _listeners[:]


def add_listener(fn):
    """fn(event) for every request and mode change: event = (kind, mode, host, purpose) with
    kind 'allowed' | 'blocked' | 'mode'. Called on the requesting thread: queue it."""
    with _lock:
        _listeners.append(fn)


def remove_listener(fn):
    with _lock:
        if fn in _listeners:
            _listeners.remove(fn)


def log():
    with _lock:
        return list(_log)


def _notify(ev):
    with _lock:
        fns = list(_listeners)
    for fn in fns:
        try:
            fn(ev)
        except Exception:
            pass


def _host_of(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_loopback_name(host):
    if host in ("localhost", "localhost.localdomain", "ip6-localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _addresses(host):
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return []
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0].split("%", 1)[0]))
        except ValueError:
            pass
    return out


def _lan_ok(addr):
    return addr.is_loopback or addr.is_private or addr.is_link_local


def allowed(host, m=None):
    """May a request to `host` leave the device in mode m (default: the current mode)?
    OFFLINE never resolves a name: only a literal loopback name/address passes. LAN resolves
    and requires EVERY address to be loopback, private or link-local."""
    m = m or mode()
    host = (host or "").strip("[]").lower()
    if not host:
        return False
    if m == "ONLINE":
        return True
    if _is_loopback_name(host):
        return True
    if m == "LAN":
        addrs = _addresses(host)
        return bool(addrs) and all(_lan_ok(a) for a in addrs)
    return False


def check(url_or_host, purpose=""):
    """Raise NetBlocked unless the current mode allows this URL (or bare host). Logs it."""
    host = _host_of(url_or_host) if "://" in str(url_or_host) else str(url_or_host).lower()
    m = mode()
    ok = allowed(host, m)
    with _lock:
        _log.append((time.time(), m, "allowed" if ok else "blocked", host, purpose))
    _notify(("allowed" if ok else "blocked", m, host, purpose))
    if not ok:
        raise NetBlocked(host, m, purpose)
    return host


def urlopen(req, timeout=10, purpose="", **kw):
    """urllib.request.urlopen behind the mode check. `req` is a URL or a Request."""
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise NetBlocked(_host_of(url), mode(), "scheme %s refused" % scheme)
    if not purpose:
        try:
            import sys
            purpose = sys._getframe(1).f_globals.get("__name__", "")
        except Exception:
            purpose = ""
    check(url, purpose)
    _install_opener()
    return urllib.request.urlopen(req, timeout=timeout, **kw)


class _NoCrossModeRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is a new request: it goes through the mode check too (a LAN host may not
    bounce the client to the internet)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check(newurl, "redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_installed = []


def _install_opener():
    """urllib's global opener follows redirects through _NoCrossModeRedirect. Installed once,
    lazily, so importing this module changes nothing."""
    if not _installed:
        urllib.request.install_opener(urllib.request.build_opener(_NoCrossModeRedirect))
        _installed.append(True)
