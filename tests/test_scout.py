"""Scout: the passive Wi-Fi detector and its baseline persistence."""
import scout


BASE = {"bssids": {"AA:BB:CC:00:00:01": {"ssid": "HomeNet", "sec": "WPA2"}}}


def _ap(ssid, bssid, sec="WPA2", sig=70, chan="6"):
    return {"ssid": ssid, "bssid": bssid, "sec": sec, "signal": sig, "chan": chan}


def test_no_findings_for_known_ap():
    aps = [_ap("HomeNet", "AA:BB:CC:00:00:01")]
    assert scout.wifi_findings(aps, BASE) == []


def test_new_ap_flagged_against_baseline():
    aps = [_ap("Cafe", "11:22:33:44:55:66", sec="open")]
    sevs = {f[0] for f in scout.wifi_findings(aps, BASE)}
    assert "new" in sevs


def test_evil_twin_same_ssid_two_bssids():
    aps = [_ap("HomeNet", "AA:BB:CC:00:00:01"), _ap("HomeNet", "DE:AD:BE:EF:00:01", sec="open")]
    msgs = [m for _, _, m in scout.wifi_findings(aps, BASE)]
    assert any("BSSIDs" in m for m in msgs)


def test_open_network_impersonating_secured_name():
    aps = [_ap("HomeNet", "DE:AD:BE:EF:00:01", sec="open")]
    sevs = {f[0] for f in scout.wifi_findings(aps, BASE)}
    assert "alert" in sevs   # open AP using a normally-secured SSID


def test_no_baseline_means_no_new_flags():
    # with an empty baseline, nothing is "new" (we don't cry wolf before a baseline exists)
    aps = [_ap("Whatever", "99:99:99:99:99:99")]
    sevs = {f[0] for f in scout.wifi_findings(aps, {})}
    assert "new" not in sevs


def test_baseline_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(scout, "BASELINE_PATH", str(tmp_path / "baseline.json"))
    aps = [_ap("HomeNet", "AA:BB:CC:00:00:01"), _ap("Shop", "22:22:22:22:22:22", sec="open")]
    scout.save_baseline(aps)
    loaded = scout.load_baseline()
    assert "AA:BB:CC:00:00:01" in loaded["bssids"]
    # after baseline, a brand-new BSSID is flagged, the saved ones are not
    findings = scout.wifi_findings(aps + [_ap("Rogue", "FF:FF:FF:FF:FF:FF")], loaded)
    assert any(b == "FF:FF:FF:FF:FF:FF" and s == "new" for s, b, _ in findings)


def test_load_baseline_missing_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(scout, "BASELINE_PATH", str(tmp_path / "nope.json"))
    assert scout.load_baseline() == {}
