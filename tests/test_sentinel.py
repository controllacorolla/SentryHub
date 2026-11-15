"""SENTINEL autonomous RF watch — the pure engine: baseline, stateful diff, honesty, storage.

Covers the brief's acceptance list at the engine level (no Qt, no hardware): baseline capture +
valid JSON, the watch diff (new / gone-after-grace / changed-RSSI) with evidence, honest per-domain
standby when a domain has no hardware (no fabricated inventory), OPSEC-armed does not block a
receive-only scan, storage/disk gating, and log rotation. Demo data is flagged throughout.
"""
import json
import os
import sys

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

import sentinel


# ---- helpers ----
def dom(available, status, **kw):
    d = {"available": available, "status": status}
    d.update(kw)
    return d


def seams(spectrum=None, wifi=None, ble=None, cellular=None, gnss=None):
    return {"spectrum": lambda c: spectrum if spectrum is not None else dom(False, "none"),
            "wifi": lambda c: wifi if wifi is not None else dom(False, "none"),
            "ble": lambda c: ble if ble is not None else dom(False, "none"),
            "cellular": lambda c: cellular if cellular is not None else dom(False, "none"),
            "gnss": lambda c: gnss}


def cfg(**over):
    c = dict(sentinel.DEFAULTS)
    c.update(over)
    return c


AP1 = {"bssid": "aa:bb:cc:00:00:01", "ssid": "BASE", "channel": 6, "signal": -50.0,
       "security": "WPA2/3"}
AP2 = {"bssid": "aa:bb:cc:00:00:02", "ssid": "NEW", "channel": 1, "signal": -60.0,
       "security": "open"}
BLE1 = {"address": "d0:00:00:00:00:01", "name": "Tag", "rssi": -55, "is_odid": False, "tags": []}


# ---- baseline ----
def test_baseline_captures_and_saves_valid_json(tmp_path):
    base = sentinel.capture_baseline(cfg(), seams(
        spectrum=dom(True, "ok", bins=[(100e6, -100.0), (101e6, -99.0)]),
        wifi=dom(True, "ok", aps={AP1["bssid"]: AP1}),
        ble=dom(True, "ok", devices={BLE1["address"]: BLE1})), now=1000.0)
    assert base["version"] == 1 and base["captured"] == 1000.0
    assert set(base["domains"]) == set(sentinel.DOMAINS)
    assert base["domains"]["wifi"]["aps"][AP1["bssid"]]["ssid"] == "BASE"
    ok, path = sentinel.save_baseline(str(tmp_path), base)
    assert ok and os.path.exists(path) and path.endswith(".json")
    loaded = sentinel.load_baseline(path)
    assert loaded == json.loads(json.dumps(base))     # round-trips as valid JSON
    assert "sentinel_baseline_" in os.path.basename(path)


# ---- watch diff: new / gone / changed ----
def test_new_device_alerts_once_with_evidence():
    base = sentinel.capture_baseline(cfg(), seams(wifi=dom(True, "ok", aps={AP1["bssid"]: AP1})),
                                     now=0.0)
    ws = sentinel.WatchState(base, cfg())
    scan = sentinel.scan_once(cfg(), seams(wifi=dom(True, "ok",
                                                    aps={AP1["bssid"]: AP1, AP2["bssid"]: AP2})),
                              now=60.0)
    evs = ws.observe(scan)
    new = [e for e in evs if e["kind"] == "new" and e["domain"] == "wifi"]
    assert len(new) == 1
    e = new[0]
    assert e["id"] == AP2["bssid"] and e["severity"] == "warn"
    assert e["field"] == "presence" and e["prev"] == "absent" and e["cur"] == "present"
    # second identical scan -> no repeat alert
    assert not [x for x in ws.observe(sentinel.scan_once(
        cfg(), seams(wifi=dom(True, "ok", aps={AP1["bssid"]: AP1, AP2["bssid"]: AP2})), now=120.0))
        if x["kind"] == "new"]


def test_device_gone_after_grace_period():
    base = sentinel.capture_baseline(cfg(grace_s=300), seams(
        wifi=dom(True, "ok", aps={AP1["bssid"]: AP1})), now=0.0)
    ws = sentinel.WatchState(base, cfg(grace_s=300))
    # AP1 absent, but only 2 min in -> within grace, no "gone"
    early = ws.observe(sentinel.scan_once(cfg(), seams(wifi=dom(True, "ok", aps={})), now=120.0))
    assert not [e for e in early if e["kind"] == "gone"]
    # past grace (6 min) -> "gone" once, with evidence
    late = ws.observe(sentinel.scan_once(cfg(), seams(wifi=dom(True, "ok", aps={})), now=360.0))
    gone = [e for e in late if e["kind"] == "gone"]
    assert len(gone) == 1 and gone[0]["id"] == AP1["bssid"] and gone[0]["severity"] == "info"
    assert gone[0]["prev"] == "present" and gone[0]["cur"] == "absent"
    # does not re-alert
    assert not [e for e in ws.observe(sentinel.scan_once(
        cfg(), seams(wifi=dom(True, "ok", aps={})), now=420.0)) if e["kind"] == "gone"]


def test_gone_timer_resets_on_reappearance_and_reflapping_realerts():
    """A baseline device that disappears, returns, then disappears again must have its gone-timer
    measured from the RETURN (not baseline), and a re-flap must re-alert."""
    base = sentinel.capture_baseline(cfg(grace_s=300),
                                     seams(wifi=dom(True, "ok", aps={AP1["bssid"]: AP1})), now=0.0)
    ws = sentinel.WatchState(base, cfg(grace_s=300))
    absent = seams(wifi=dom(True, "ok", aps={}))
    present = seams(wifi=dom(True, "ok", aps={AP1["bssid"]: AP1}))
    # absent at t=120 (within grace) -> no gone
    assert not [e for e in ws.observe(sentinel.scan_once(cfg(), absent, now=120.0))
                if e["kind"] == "gone"]
    ws.observe(sentinel.scan_once(cfg(), present, now=200.0))          # reappears at t=200
    # absent again at t=450: 450-200=250 < 300 -> still no gone (timer reset to the return)
    assert not [e for e in ws.observe(sentinel.scan_once(cfg(), absent, now=450.0))
                if e["kind"] == "gone"]
    # absent at t=520: 520-200=320 >= 300 -> gone fires now
    assert [e for e in ws.observe(sentinel.scan_once(cfg(), absent, now=520.0)) if e["kind"] == "gone"]
    # returns then gone again -> re-alerts (flapping)
    ws.observe(sentinel.scan_once(cfg(), present, now=540.0))
    again = ws.observe(sentinel.scan_once(cfg(), absent, now=900.0))
    assert [e for e in again if e["kind"] == "gone"], "a flapping device must re-alert gone"


def test_changed_realerts_after_return_to_baseline():
    """A device that deviates, returns to baseline, then re-deviates must re-alert (dedup re-arms)."""
    base = sentinel.capture_baseline(cfg(rssi_delta_db=12.0),
                                     seams(ble=dom(True, "ok", devices={BLE1["address"]: BLE1})), now=0.0)
    ws = sentinel.WatchState(base, cfg(rssi_delta_db=12.0))

    def ble_at(rssi, t):
        return ws.observe(sentinel.scan_once(
            cfg(), seams(ble=dom(True, "ok", devices={BLE1["address"]: dict(BLE1, rssi=rssi)})), now=t))
    assert [e for e in ble_at(-40, 60) if e["kind"] == "changed"]     # deviates (+15) -> alert
    assert not [e for e in ble_at(-55, 120) if e["kind"] == "changed"]  # back to baseline -> re-arm
    assert [e for e in ble_at(-40, 180) if e["kind"] == "changed"]    # re-deviates -> re-alert


def test_disk_status_thresholds(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda p: (100, 96, 4))     # 4% free
    d = sentinel.disk_status("/")
    assert d["pct_free"] == 4.0 and d["ok"] is False and d["warn"] is True
    monkeypatch.setattr(shutil, "disk_usage", lambda p: (100, 92, 8))     # 8% free
    d = sentinel.disk_status("/")
    assert d["ok"] is True and d["warn"] is True
    monkeypatch.setattr(shutil, "disk_usage", lambda p: (100, 50, 50))    # 50% free
    d = sentinel.disk_status("/")
    assert d["ok"] is True and d["warn"] is False
    monkeypatch.setattr(shutil, "disk_usage", lambda p: (0, 0, 0))        # zero-total
    assert sentinel.disk_status("/")["pct_free"] == 100.0


def test_scan_once_interrupted_by_stop():
    """A stop mid-pass leaves the remaining domains unavailable+'interrupted' (no fabricated data)."""
    calls = {"n": 0}

    def counting(available):
        def seam(c):
            calls["n"] += 1
            return dom(available, "ok")
        return seam
    # stop() flips true after the first domain is scanned
    scan = sentinel.scan_once(cfg(), {d: counting(True) for d in sentinel.DOMAINS},
                              now=0.0, stop=lambda: calls["n"] >= 1)
    assert scan["domains"]["spectrum"]["available"] is True          # first ran
    assert all(scan["domains"][d]["status"] == "interrupted" for d in ("wifi", "ble", "cellular"))
    assert scan["gps"] is None


def test_rssi_delta_threshold_boundary():
    base = sentinel.capture_baseline(cfg(rssi_delta_db=12.0),
                                     seams(ble=dom(True, "ok", devices={BLE1["address"]: BLE1})),
                                     now=0.0)
    # below threshold (-55 -> -60 = 5 dB) -> no change event
    ws = sentinel.WatchState(base, cfg(rssi_delta_db=12.0))
    small = dict(BLE1, rssi=-60)
    assert not [e for e in ws.observe(sentinel.scan_once(
        cfg(), seams(ble=dom(True, "ok", devices={BLE1["address"]: small})), now=60.0))
        if e["kind"] == "changed"]
    # at/above threshold (-55 -> -43 = 12 dB) -> change event with prev/cur
    big = dict(BLE1, rssi=-43)
    evs = ws.observe(sentinel.scan_once(
        cfg(), seams(ble=dom(True, "ok", devices={BLE1["address"]: big})), now=120.0))
    ch = [e for e in evs if e["kind"] == "changed"]
    assert len(ch) == 1 and ch[0]["field"] == "rssi" and ch[0]["prev"] == -55 and ch[0]["cur"] == -43


def test_wifi_channel_change_is_evidence():
    base = sentinel.capture_baseline(cfg(), seams(wifi=dom(True, "ok", aps={AP1["bssid"]: AP1})),
                                     now=0.0)
    ws = sentinel.WatchState(base, cfg())
    moved = dict(AP1, channel=11)
    evs = ws.observe(sentinel.scan_once(cfg(), seams(wifi=dom(True, "ok",
                                                              aps={AP1["bssid"]: moved})), now=60.0))
    ch = [e for e in evs if e["kind"] == "changed"]
    assert ch and ch[0]["field"] == "channel" and ch[0]["prev"] == 6 and ch[0]["cur"] == 11


def test_spectrum_new_emitter_detected():
    base_bins = [(100e6 + k * 1e6, -105.0) for k in range(50)]
    cur_bins = list(base_bins)
    cur_bins[20] = (cur_bins[20][0], -40.0)             # a signal 65 dB over the floor
    base = sentinel.capture_baseline(cfg(spectrum_threshold_db=10.0),
                                     seams(spectrum=dom(True, "ok", bins=base_bins)), now=0.0)
    ws = sentinel.WatchState(base, cfg(spectrum_threshold_db=10.0))
    evs = ws.observe(sentinel.scan_once(cfg(), seams(spectrum=dom(True, "ok", bins=cur_bins)),
                                        now=60.0))
    sp = [e for e in evs if e["domain"] == "spectrum" and e["kind"] == "new"]
    assert len(sp) == 1 and sp[0]["field"] == "dbm" and sp[0]["cur"] == -40.0


# ---- honesty ----
def test_no_hardware_is_honest_standby_not_fabricated():
    base = sentinel.capture_baseline(cfg(), seams(
        spectrum=dom(False, "standby-no-rtl_power"),
        wifi=dom(False, "standby-no-wifi-adapter"),
        ble=dom(False, "standby-no-bleak")), now=0.0)
    for d in ("spectrum", "wifi", "ble"):
        assert base["domains"][d]["available"] is False
        assert "aps" not in base["domains"][d] and "devices" not in base["domains"][d]
    # an unavailable domain in a later scan yields no events (claims nothing)
    ws = sentinel.WatchState(base, cfg())
    evs = ws.observe(sentinel.scan_once(cfg(), seams(
        wifi=dom(False, "standby-no-wifi-adapter")), now=60.0))
    assert evs == []


def test_opsec_armed_does_not_block_sentinel():
    """SENTINEL is receive-only, so an RF-dark posture must NOT stop it listening."""
    import opsec
    opsec.reset()
    try:
        opsec.arm(operator="KD0ABC")
        scan = sentinel.scan_once(cfg(), seams(wifi=dom(True, "ok", aps={AP1["bssid"]: AP1})),
                                  now=10.0)
        assert scan["domains"]["wifi"]["available"] is True
        assert AP1["bssid"] in scan["domains"]["wifi"]["aps"]
    finally:
        opsec.reset()


def test_domain_status_recorded_so_log_reflects_gaps():
    """A radio-busy spectrum sweep is recorded as unavailable with its status — the log reflects the
    gap honestly, no fabricated bins."""
    scan = sentinel.scan_once(cfg(), seams(spectrum=dom(False, "radio-busy")), now=0.0)
    assert scan["domains"]["spectrum"]["available"] is False
    assert scan["domains"]["spectrum"]["status"] == "radio-busy"
    assert "bins" not in scan["domains"]["spectrum"]


# ---- storage / disk / log ----
def test_resolve_dir_default_and_override():
    assert sentinel.resolve_dir(cfg()) == sentinel.default_dir()
    assert sentinel.resolve_dir(cfg(storage_dir="/mnt/nvme/x")) == "/mnt/nvme/x"


def test_disk_gate_warns_and_refuses(monkeypatch):
    monkeypatch.setattr(sentinel, "disk_status",
                        lambda p: {"total": 100, "free": 3, "pct_free": 3.0,
                                   "ok": False, "warn": True, "unknown": False})
    ok, msg = sentinel.disk_gate("/x")
    assert ok is False and "too low" in msg
    monkeypatch.setattr(sentinel, "disk_status",
                        lambda p: {"total": 100, "free": 8, "pct_free": 8.0,
                                   "ok": True, "warn": True, "unknown": False})
    ok, msg = sentinel.disk_gate("/x")
    assert ok is True and "low" in msg


def test_log_rotation(tmp_path):
    path = str(tmp_path / "sentinel_log.jsonl")
    log = sentinel.SentinelLog(path, rotate_bytes=120)
    for i in range(6):
        log.append({"i": i, "pad": "x" * 40})
    assert log.rotations >= 1, "log should rotate past the size cap"
    assert os.path.exists(path + ".1")
    assert os.path.exists(path)


# ---- demo ----
def test_demo_is_flagged_throughout():
    d = sentinel.Demo()
    now = 1000.0
    base = d.baseline(cfg(), now)
    assert base["demo"] is True
    ws = sentinel.WatchState(base, cfg())
    evs = ws.observe(d.scan(cfg(), now + 60))
    assert evs, "demo scan should produce diff events"
    assert all(e["demo"] is True for e in evs), "every demo event must be flagged demo"


def test_summarize_counts():
    evs = [{"kind": "new", "severity": "warn"}, {"kind": "gone", "severity": "info"},
           {"kind": "new", "severity": "warn"}]
    s = sentinel.summarize(evs, duration_s=600, sweeps=10)
    assert s["events"] == 3 and s["by_kind"]["new"] == 2 and s["deviation_score"] == 2
    assert s["duration_s"] == 600 and s["sweeps"] == 10
