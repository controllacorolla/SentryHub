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


def _proxy_for(url, host):
    """The proxy host urllib would use for this URL, or None (no proxy / host bypassed)."""
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    proxy = urllib.request.getproxies().get(scheme)
    if not proxy:
        return None
    try:
        if urllib.request.proxy_bypass(host):
            return None
    except Exception:
        pass
    return _host_of(proxy if "://" in proxy else "http://" + proxy) or proxy


def check(url_or_host, purpose=""):
    """Raise NetBlocked unless the current mode allows this URL (or bare host). Logs it."""
    is_url = "://" in str(url_or_host)
    host = _host_of(url_or_host) if is_url else str(url_or_host).lower()
    m = mode()
    ok = allowed(host, m)
    if ok and is_url and m != "ONLINE":
        # RA-CL8: urllib honours http_proxy/https_proxy, so a loopback request in OFFLINE could
        # still go to a proxy on another host. The proxy is where the bytes go: it must pass too.
        proxy = _proxy_for(str(url_or_host), host)
        if proxy is not None and not allowed(proxy, m):
            host, ok = "%s (via proxy %s)" % (host, proxy), False
    with _lock:
        _log.append((time.time(), m, "allowed" if ok else "blocked", host, purpose))
    _notify(("allowed" if ok else "blocked", m, host, purpose))
    if not ok:
        raise NetBlocked(host, m, purpose)
    return host


# Hosts an operator grant may reach (RA-S2 N4): a module that offers a one-tap download names its
# hosts here; urlopen(granted=True) to any other host is refused like any blocked request.
GRANTABLE = {}


def allow_grant(hosts, purpose):
    with _lock:
        for h in hosts:
            if h:
                GRANTABLE[h.lower()] = purpose


def grant(url, purpose):
    """An operator's one-tap exception to the mode for ONE request (owner 2026-11-18: "one-tap
    download on the map" while NET stays OFFLINE). Only an explicit operator action may pass this
    (never a background fetch); it is logged as 'granted' with the mode it overrode."""
    host = _host_of(url)
    m = mode()
    with _lock:
        _log.append((time.time(), m, "granted", host, purpose))
    _notify(("granted", m, host, purpose))
    return host


def urlopen(req, timeout=10, purpose="", granted=False, **kw):
    """urllib.request.urlopen behind the mode check. `req` is a URL or a Request. granted=True:
    the operator explicitly asked for this one request (see grant()); it is logged, not checked."""
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
    if granted:
        host = (_host_of(url) or "").lower()
        if host not in GRANTABLE:
            raise NetBlocked(host, mode(), "no operator grant for this host")
        grant(url, purpose)
    else:
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
