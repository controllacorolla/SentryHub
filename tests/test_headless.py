"""Tests for headless/remote mode (Phase 7 #7). Uses Flask's test client — no real server."""
import json

import headless


def _app():
    return headless.make_app({
        "status": lambda: {"active_contacts": 3, "radio": "aprs"},
        "contacts": lambda: [{"id": "UAS-1", "type": "drone", "lat": 39.6, "lon": -104.9}],
    })


def test_health_endpoint():
    c = _app().test_client()
    r = c.get("/health")
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_status_api_uses_provider():
    c = _app().test_client()
    d = c.get("/api/status").get_json()
    assert d["active_contacts"] == 3 and d["radio"] == "aprs"


def test_contacts_api_uses_provider():
    c = _app().test_client()
    d = c.get("/api/contacts").get_json()
    assert d["contacts"][0]["id"] == "UAS-1" and d["contacts"][0]["type"] == "drone"


def test_dashboard_served():
    c = _app().test_client()
    r = c.get("/")
    assert r.status_code == 200 and b"Sentry" in r.data and b"/api/status" in r.data


def test_empty_providers_are_safe():
    c = headless.make_app().test_client()
    assert c.get("/api/status").get_json() == {}
    assert c.get("/api/contacts").get_json() == {"contacts": []}


def test_webhook_payload_shape():
    p = headless.webhook_payload("drone detected")
    assert p["text"] == "drone detected" and p["source"] == "sentry" and "ts" in p


def test_post_webhook_uses_poster_and_skips_empty_url():
    sent = {}
    ok = headless.post_webhook("http://x/hook", "alert!",
                               poster=lambda url, data: sent.update(url=url, data=data) or True)
    assert ok and sent["url"] == "http://x/hook"
    assert json.loads(sent["data"])["text"] == "alert!"
    assert headless.post_webhook("", "alert", poster=lambda u, d: True) is False
