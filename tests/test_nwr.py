"""Tests for the NWR SAME/EAS decoder (Phase 4 #10)."""
import nwr


def test_parse_same_tornado_multi_area():
    a = nwr.parse_same("EAS: ZCZC-WXR-TOR-020121-020127+0045-3181700-KICT/NWS-")
    assert a["org"] == "WXR" and a["org_name"].startswith("National Weather")
    assert a["event"] == "TOR" and a["event_name"] == "Tornado Warning"
    assert a["areas"] == ["020121", "020127"]
    assert a["purge"] == "0045" and a["issue"] == "3181700"
    assert a["station"] == "KICT/NWS" and a["urgent"] is True


def test_parse_same_single_area():
    a = nwr.parse_same("EAS: ZCZC-WXR-SVR-048201+0100-3181830-KFWS/NWS-")
    assert a["areas"] == ["048201"] and a["event"] == "SVR"


def test_parse_same_test_not_urgent():
    a = nwr.parse_same("EAS: ZCZC-WXR-RWT-048000+0015-3181200-KFWS/NWS-")
    assert a["event_name"] == "Required Weekly Test" and a["urgent"] is False


def test_unknown_event_code_passes_through():
    a = nwr.parse_same("EAS: ZCZC-WXR-ZZZ-048000+0015-3181200-KFWS/NWS-")
    assert "unknown code" in a["event_name"] and a["urgent"] is False


def test_parse_same_rejects_junk():
    assert nwr.parse_same("random noise") is None


def test_purge_minutes():
    assert nwr.purge_minutes("0045") == 45
    assert nwr.purge_minutes("0100") == 60
    assert nwr.purge_minutes("0130") == 90
    assert nwr.purge_minutes("xxxx") is None


def test_alerts_fires_callback_and_orders_recent():
    fired = []
    al = nwr.Alerts()
    al.on_alert = lambda a: fired.append(a["event"])
    al.add(nwr.parse_same("EAS: ZCZC-WXR-TOR-020121+0045-3181700-KICT/NWS-"), now=1)
    al.add(nwr.parse_same("EAS: ZCZC-WXR-SVR-048201+0100-3181830-KFWS/NWS-"), now=2)
    assert fired == ["TOR", "SVR"]
    assert al.recent()[0]["event"] == "SVR"       # most recent first


def test_demo_lines_all_parse():
    dm = nwr.Demo()
    for _ in range(len(nwr.Demo.LINES)):
        assert nwr.parse_same(dm.lines()[0]) is not None
