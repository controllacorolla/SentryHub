"""Situation report: gather everything the suite already knows (ADS-B, weather, radar, GPS, mesh,
battery, next satellite pass) into a short brief.  An Ollama host, if reachable, reads it back in a
deadpan radio cadence; otherwise a plain template is spoken.  All inputs are local or already fetched
by the apps - this adds no new data source.
"""
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suite as S  # noqa: E402

core = S.core


def _tfr(states):
    """Active FAA TFRs filtered to the given state codes. The FAA list API has no geometry,
    so this is an advisory list (type + description), not a map overlay - honest about what
    the data actually supports."""
    try:
        url = "https://tfr.faa.gov/tfrapi/exportTfrList"
        req = urllib.request.Request(url, headers={"User-Agent": "uconsole-suite"})
        data = json.loads(urllib.request.urlopen(req, timeout=6).read())
        want = {s.upper() for s in states}
        out = []
        for t in data if isinstance(data, list) else []:
            if str(t.get("state", "")).upper() in want:
                out.append({"type": t.get("type", ""), "state": t.get("state", ""),
                            "desc": (t.get("description") or "").strip()})
        return out
    except Exception:
        return None


def _metar(ident="KDEN"):
    try:
        url = "https://aviationweather.gov/api/data/metar?ids=%s&format=json" % ident
        req = urllib.request.Request(url, headers={"User-Agent": "uconsole-suite"})
        obs = json.loads(urllib.request.urlopen(req, timeout=6).read())
        if obs:
            o = obs[0]
            return {"cat": o.get("fltCat"), "temp": o.get("temp"), "wind_dir": o.get("wdir"),
                    "wind_spd": o.get("wspd"), "raw": o.get("rawOb", "")}
    except urllib.error.HTTPError:
        return None          # the server answered: just no data for this station
    except OSError:
        return False         # network down/timeout: the other stations will fail the same way
    except Exception:
        return None


def gather():
    """Everything the brief draws on, as a plain dict."""
    d = {"time": time.strftime("%H:%M"), "date": time.strftime("%A %d %B")}
    # aircraft
    try:
        # the user's saved sources, not the defaults - they may have repointed the feed
        try:
            feed_src = core.load_settings().get("adsb_sources") or core.DEFAULT_SETTINGS["adsb_sources"]
        except Exception:
            feed_src = core.DEFAULT_SETTINGS["adsb_sources"]
        acs = None
        for src in feed_src:
            try:
                if src.startswith("http"):
                    data = json.loads(urllib.request.urlopen(src + "/aircraft.json", timeout=2).read())
                else:
                    with open(os.path.join(src, "aircraft.json")) as f:
                        data = json.load(f)
                acs = [a for a in data.get("aircraft", []) if a.get("seen", 99) < 60]
                break
            except Exception:
                continue
        if acs is not None:
            air = [a for a in acs if "lat" in a and a.get("alt_baro") not in (None, "ground")]
            d["aircraft_total"] = len(acs)
            d["aircraft_airborne"] = len(air)
            if air:
                hi = max(air, key=lambda a: a.get("alt_baro", 0) if isinstance(a.get("alt_baro"), (int, float)) else 0)
                d["highest"] = {"cs": (hi.get("flight") or "").strip(), "alt": hi.get("alt_baro")}
                fast = max(air, key=lambda a: a.get("gs", 0) or 0)
                d["fastest"] = {"cs": (fast.get("flight") or "").strip(), "gs": fast.get("gs")}
            emerg = [a for a in acs if str(a.get("squawk")) in ("7500", "7600", "7700")]
            d["emergencies"] = [(a.get("flight") or a["hex"]).strip() + " " + str(a.get("squawk")) for a in emerg]
    except Exception:
        pass
    # records today
    try:
        recs = core.load_records()
        d["records"] = core.record_lines(recs, "today")
    except Exception:
        d["records"] = []
    # weather
    # home field first (AIRPORTS is ordered home -> regional), fall back down the list
    d["metar"] = None
    for ident in list(core.AIRPORTS) or ["KDEN"]:
        d["metar"] = _metar(ident)
        if d["metar"] is False:     # offline: don't wait out a 6 s timeout per airport
            d["metar"] = None
            break
        if d["metar"]:
            d["metar"]["station"] = ident
            break
    # active TFRs in the configured state(s)
    try:
        states = core.load_settings().get("tfr_states") or ["CO"]
    except Exception:
        states = ["CO"]
    d["tfrs"] = _tfr(states)
    # gps
    try:
        tpv = S.gps_fix(timeout=1.5)
        if tpv and tpv.get("mode", 0) >= 2:
            d["gps"] = {"lat": tpv["lat"], "lon": tpv["lon"], "mode": tpv["mode"]}
    except Exception:
        pass
    # mesh node count
    try:
        mp = os.path.join(S.DATA, "mesh_messages.jsonl")
        if os.path.exists(mp):
            cutoff = time.time() - 86400
            nodes = set()
            with open(mp) as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        if r.get("t", 0) > cutoff and r.get("from"):
                            nodes.add(r["from"])
                    except ValueError:
                        pass
            d["mesh_nodes_24h"] = len(nodes)
    except Exception:
        pass
    # power
    cap, bst, volts, watts = S.battery()
    d["battery"] = {"pct": cap, "status": bst, "watts": watts}
    # next weather-sat pass (uses the cached predictions the Weather Sats app wrote, if any)
    try:
        pj = os.path.join(S.CACHE, "wx_passes.json")
        if os.path.exists(pj):
            passes = json.load(open(pj))
            now = time.time()
            up = [p for p in passes if p.get("aos", 0) > now]
            if up:
                p = min(up, key=lambda x: x["aos"])
                mins = int((p["aos"] - now) / 60)
                d["next_pass"] = {"sat": p.get("sat"), "in_min": mins, "max": p.get("max")}
    except Exception:
        pass
    # weather balloons: live sondes (Balloons app cache) and the next NWS launch
    try:
        sj = json.load(open(os.path.join(S.CACHE, "sondes.json")))
        now = time.time()
        live = [b for b in sj.get("sondes", []) if now - float(b.get("t", 0)) < 900]
        if live:
            b = max(live, key=lambda x: x.get("t", 0))
            d["sonde"] = {"id": str(b.get("id", ""))[:16], "alt_m": b.get("alt"),
                          "phase": b.get("phase")}
    except Exception:
        pass
    try:
        import balloons
        d["next_launch_min"] = int(balloons.next_launch() / 60)
    except Exception:
        pass
    # APRS stations heard in the last day (APRS app cache)
    try:
        import aprs
        st = aprs.load_stations(os.path.join(S.CACHE, "aprs_stations.json"), time.time())
        if st.s:
            d["aprs_24h"] = len(st.s)
    except Exception:
        pass
    # network
    try:
        d["net"] = S.network_status()
    except Exception:
        pass
    return d


def template(d):
    """Plain-language brief without an LLM."""
    parts = ["Situation report, %s." % d["time"]]
    m = d.get("metar")
    if m and m.get("cat"):
        wind = ""
        if m.get("wind_dir") is not None and m.get("wind_spd") is not None:
            wind = ", wind %03d at %d" % (m["wind_dir"], m["wind_spd"]) if isinstance(m["wind_dir"], int) else ""
        temp = ", %d degrees" % m["temp"] if isinstance(m.get("temp"), (int, float)) else ""
        st = m.get("station", "")
        place = core.AIRPORTS.get(st, {}).get("name") or st or "Field"
        parts.append("%s is %s%s%s." % (place, {"VFR": "clear", "MVFR": "marginal", "IFR": "low",
                                                "LIFR": "very low"}.get(m["cat"], m["cat"]), wind, temp))
    if "aircraft_airborne" in d:
        parts.append("%d aircraft airborne." % d["aircraft_airborne"])
        if d.get("highest") and isinstance(d["highest"].get("alt"), (int, float)):
            parts.append("Highest, %s at %s feet." % (d["highest"]["cs"] or "unknown",
                                                      format(int(d["highest"]["alt"]), ",")))
    if d.get("emergencies"):
        parts.append("Alert: %s." % ", ".join(d["emergencies"]))
    tfrs = d.get("tfrs")
    if tfrs:
        kinds = {}
        for t in tfrs:
            kinds[t["type"]] = kinds.get(t["type"], 0) + 1
        summ = ", ".join("%d %s" % (n, k.lower()) for k, n in sorted(kinds.items()))
        parts.append("%d active flight restriction%s nearby: %s." %
                     (len(tfrs), "" if len(tfrs) == 1 else "s", summ))
    if d.get("next_pass"):
        np = d["next_pass"]
        parts.append("Next weather satellite, %s, in %d minutes." % (np["sat"], np["in_min"]))
    if d.get("sonde") and isinstance(d["sonde"].get("alt_m"), (int, float)):
        sd = d["sonde"]
        parts.append("Weather balloon %s %s at %s metres." % (
            sd["id"], sd.get("phase") or "aloft", format(int(sd["alt_m"]), ",")))
    elif isinstance(d.get("next_launch_min"), int) and d["next_launch_min"] <= 90:
        parts.append("Next weather balloon launch in %d minutes." % d["next_launch_min"])
    if d.get("aprs_24h"):
        parts.append("%d APRS stations heard today." % d["aprs_24h"])
    if d.get("mesh_nodes_24h"):
        parts.append("%d mesh nodes in the last day." % d["mesh_nodes_24h"])
    b = d.get("battery", {})
    if b.get("pct") is not None:
        parts.append("Battery %d percent%s." % (b["pct"], ", charging" if str(b.get("status", "")).lower() == "charging" else ""))
    parts.append("End of report.")
    return " ".join(parts)


def brief(use_llm=True):
    """Returns (text, source) where source is 'llm' or 'template'."""
    d = gather()
    if use_llm:
        try:
            import assistant
            s, _ = S.settings("assistant", assistant.DEFAULTS)
            host = assistant.pick_host(s)   # (name, url, model) or None
            if host:
                _name, url, model = host
                facts = json.dumps({k: v for k, v in d.items() if k != "net"}, default=str)
                prompt = ("Read this data as a 30-second spoken situation report in the calm, clipped "
                          "cadence of a shipping-forecast announcer. Plain sentences, no markdown, no "
                          "lists, no preamble. Mention weather, air traffic, any alerts, the next "
                          "satellite pass, and battery. Be concise.\n\nDATA:\n" + facts)
                body = assistant.chat_body(s, url, model or "llama3.2:3b",
                                           [{"role": "user", "content": prompt}], stream=False)
                r = assistant.http_json(url.rstrip("/") + "/api/chat", body, timeout=60)
                txt = (r.get("message") or {}).get("content", "").strip()
                if txt:
                    return txt, "llm"
        except Exception:
            pass
    return template(d), "template"


def speak(text):
    if shutil.which("espeak-ng"):
        S.fire_and_forget(["espeak-ng", "-s", "148", text])


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="print only, don't speak")
    ap.add_argument("--sitrep", action="store_true", help=argparse.SUPPRESS)  # ignored (hub passthrough)
    a, _ = ap.parse_known_args()
    txt, src = brief(use_llm=not a.no_llm)
    print(txt)
    if not a.quiet:
        speak(txt)


if __name__ == "__main__":
    main()
