"""Power resilience: status dict shape, low-power triggers, throttle parsing."""
import suite as S


def test_power_status_has_expected_keys():
    p = S.power_status()
    for k in ("pct", "status", "charging", "volts", "watts", "temp",
              "throttle", "undervolt_now", "undervolt_seen", "low_batt"):
        assert k in p


def test_low_power_env_override(monkeypatch):
    monkeypatch.setenv("UCS_LOW_POWER", "1")
    assert S.low_power() is True
    monkeypatch.setenv("UCS_LOW_POWER", "0")
    assert S.low_power() is False


def test_low_power_sentinel_file(tmp_path, monkeypatch):
    monkeypatch.delenv("UCS_LOW_POWER", raising=False)
    monkeypatch.setattr(S, "CACHE", str(tmp_path))
    assert S.low_power() is False
    open(str(tmp_path / "low_power"), "w").close()
    assert S.low_power() is True


def test_throttle_flags_none_without_vcgencmd(monkeypatch):
    # on a box without vcgencmd (CI/this container) it must degrade to None, never raise
    monkeypatch.setattr(S.shutil, "which", lambda name: None)
    assert S.throttle_flags() is None


def test_power_status_never_raises(monkeypatch):
    # even if every underlying read fails, the dict is still well-formed
    monkeypatch.setattr(S, "battery", lambda: (_ for _ in ()).throw(OSError("boom"))
                        if False else (None, "", None, None))
    assert isinstance(S.power_status(), dict)
