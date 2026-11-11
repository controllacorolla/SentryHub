"""Regression tests for bugs fixed in sitrep.py during the code audit."""
import urllib.error

import sitrep


def test_template_says_charging_for_sysfs_status():
    txt = sitrep.template({"time": "12:00", "battery": {"pct": 80, "status": "Charging"}})
    assert "charging" in txt


def test_brief_uses_llm_host_tuple(monkeypatch):
    import assistant
    monkeypatch.setattr(sitrep, "gather", lambda: {"time": "12:00"})
    monkeypatch.setattr(assistant, "pick_host",
                        lambda s: ("desk", "http://10.0.0.2:11434", "llama3.2:3b"))
    seen = {}

    def http_json(url, body, timeout=0):
        seen["url"], seen["model"] = url, body["model"]
        return {"message": {"content": "All quiet."}}
    monkeypatch.setattr(assistant, "http_json", http_json)
    txt, src = sitrep.brief()
    assert src == "llm" and txt == "All quiet."
    assert seen == {"url": "http://10.0.0.2:11434/api/chat", "model": "llama3.2:3b"}


def test_metar_stops_after_network_failure(monkeypatch):
    calls = []

    def urlopen(req, timeout=0):
        calls.append(req.full_url)
        raise urllib.error.URLError("network unreachable")
    monkeypatch.setattr(sitrep.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sitrep, "_tfr", lambda st: None)
    monkeypatch.setattr(sitrep.core, "AIRPORTS",
                        {k: {"name": k} for k in ("KAPA", "KDEN", "KBKF", "KBJC", "KFTG")})
    d = sitrep.gather()
    assert d["metar"] is None
    assert len([u for u in calls if "metar" in u]) == 1, "kept timing out on every airport"
