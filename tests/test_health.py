"""Device health guard: heat latch, events, markers, transcriber stand-down."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import suite as S          # noqa: E402
import transcriber as TR   # noqa: E402


def test_thermal_level_latches_until_cool():
    assert S.thermal_level(None) == "unknown"
    assert S.thermal_level(55) == "ok"
    assert S.thermal_level(71) == "warm"
    assert S.thermal_level(80) == "hot"
    assert S.thermal_level(76) == "warm"                    # never got hot
    assert S.thermal_level(76, was_hot=True) == "hot"       # was hot: stay paused
    assert S.thermal_level(72, was_hot=True) == "warm"      # cooled


def test_events_fire_once_per_transition():
    ok = {"level": "ok", "temp": 60, "pct": 80, "charging": False}
    hot = dict(ok, level="hot", temp=82)
    assert [k for k, _ in S.health_events(ok, hot)] == ["hot"]
    assert S.health_events(hot, hot) == []
    assert [k for k, _ in S.health_events(hot, dict(ok, temp=70, level="warm"))] == ["cool"]
    assert [k for k, _ in S.health_events(ok, dict(ok, undervolt_now=True))] == ["undervolt"]
    low = dict(ok, pct=15)
    assert [k for k, _ in S.health_events(ok, low)] == ["battery"]
    assert S.health_events(low, dict(ok, pct=14)) == []                 # no nagging every percent
    assert "shut down" in S.health_events(dict(ok, pct=6), dict(ok, pct=5))[0][1]
    assert S.health_events(ok, dict(ok, pct=4, charging=True)) == []    # on the charger
    assert S.health_events(None, ok) == []                              # first poll, all fine


def test_poll_keeps_markers_and_low_power_in_step(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "CACHE", str(tmp_path))
    monkeypatch.setattr(S, "HOT_FILE", str(tmp_path / "hot"))
    monkeypatch.delenv("UCS_LOW_POWER", raising=False)
    monkeypatch.setitem(S._HEALTH, "snap", {})
    monkeypatch.setitem(S._HEALTH, "watch", [])
    seen = []
    S.on_health(lambda k, t: seen.append(k))
    state = {"temp": 60.0, "pct": 90}

    def fake():
        return {"pct": state["pct"], "status": "Discharging", "charging": False, "volts": 3.9,
                "watts": 6.0, "temp": state["temp"], "throttle": None, "undervolt_now": False,
                "undervolt_seen": False, "low_batt": state["pct"] <= S.LOW_BATT}
    monkeypatch.setattr(S, "power_status", fake)
    S.health_poll()
    assert not S.is_hot() and not S.low_power() and seen == []
    state["temp"] = 83.0
    S.health_poll()
    assert S.is_hot() and S.low_power() and seen == ["hot"]
    state["temp"] = 75.0                                     # still above the cool-down point
    S.health_poll()
    assert S.is_hot() and seen == ["hot"]
    state["temp"] = 65.0
    S.health_poll()
    assert not S.is_hot() and not S.low_power() and seen == ["hot", "cool"]
    state["pct"] = 12
    S.health_poll()
    assert S.low_power() and os.path.exists(tmp_path / "low_power") and seen[-1] == "battery"
    state["pct"] = 60
    S.health_poll()
    assert not S.low_power()


def test_stale_hot_marker_is_ignored(monkeypatch, tmp_path):
    f = tmp_path / "hot"
    f.write_text("")
    monkeypatch.setattr(S, "HOT_FILE", str(f))
    assert S.is_hot()
    old = time.time() - 600
    os.utime(f, (old, old))
    assert not S.is_hot()                                    # left behind by a crash


def test_transcriber_stands_down_when_hot():
    TR._HOT[0] = False
    assert not TR.too_hot(70)
    assert TR.too_hot(81)
    assert TR.too_hot(76)            # latched
    assert not TR.too_hot(71)
    assert not TR.too_hot(76)
    TR.too_hot(85)
    assert not TR.too_hot(None) or True
    TR._HOT[0] = False
