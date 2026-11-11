"""Backup/restore and the session log."""
import json
import os
import suite as S


def test_backup_restore_roundtrip(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cfg = home / ".config" / "uconsole-suite"
    cfg.mkdir(parents=True)
    (cfg / "fm.json").write_text(json.dumps({"freq": 101.5}))
    monkeypatch.setattr(S, "HOME", str(home))
    monkeypatch.setattr(S, "CFG", str(cfg))
    monkeypatch.setattr(S, "CACHE", str(home / ".cache" / "uconsole-suite"))

    dest = str(tmp_path / "backup.tar.gz")
    path, n = S.backup_configs(dest)
    assert os.path.exists(path) and n >= 1

    (cfg / "fm.json").unlink()   # simulate loss
    S.restore_configs(path)
    assert json.loads((cfg / "fm.json").read_text())["freq"] == 101.5


def test_restore_rejects_paths_outside_home(tmp_path, monkeypatch):
    # a malicious archive with ../ escape must not write outside HOME
    import tarfile
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(S, "HOME", str(home))
    eviltar = str(tmp_path / "evil.tar.gz")
    payload = tmp_path / "payload"
    payload.write_text("x")
    with tarfile.open(eviltar, "w:gz") as tf:
        tf.add(str(payload), arcname="../escape.txt")
    S.restore_configs(eviltar)
    assert not (tmp_path / "escape.txt").exists()


def test_sessionlog_event_and_recent(tmp_path, monkeypatch):
    monkeypatch.setattr(S.SessionLog, "DIR", str(tmp_path / "sessions"))
    lg = S.SessionLog("sky", dedup_window=300)
    lg.event("emergency", "UAL1 emergency", id="a1", squawk="7700")
    lg.event("acars", "DAL9 OFF", id="r1")
    rows = S.SessionLog.recent(50)
    assert len(rows) == 2
    assert rows[0]["app"] == "sky" and rows[0]["kind"] == "emergency"


def test_sessionlog_dedups_within_window(tmp_path, monkeypatch):
    monkeypatch.setattr(S.SessionLog, "DIR", str(tmp_path / "sessions"))
    lg = S.SessionLog("sky", dedup_window=300)
    lg.event("emergency", "UAL1 emergency", id="a1")
    lg.event("emergency", "UAL1 emergency", id="a1")   # same key, suppressed
    assert len(S.SessionLog.recent(50)) == 1


def test_sessionlog_recent_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(S.SessionLog, "DIR", str(tmp_path / "none"))
    assert S.SessionLog.recent(10) == []


def test_typed_value_wrong_types_fall_back():
    import suite
    assert suite.typed_value(40, "high") == 40
    assert suite.typed_value(40, 32) == 32
    assert suite.typed_value(40, True) == 40            # bool is not a number here
    assert suite.typed_value("NOAA Wx", 7) == "NOAA Wx"
    assert suite.typed_value([], "notalist") == []
    assert suite.typed_value({"nm": 5}, "far") == {"nm": 5}
    assert suite.typed_value({"nm": 5}, {"nm": "far", "extra": 1}) == {"nm": 5, "extra": 1}


def test_settings_sanitizes_on_load(tmp_path, monkeypatch):
    import suite, json, os
    monkeypatch.setattr(suite, "CFG", str(tmp_path))
    p = tmp_path / "scanner.json"
    p.write_text(json.dumps({"gain": "high", "squelch": None, "bank": 9,
                             "custom": "oops", "dwell": 0.4}))
    s, _ = suite.settings("scanner", {"bank": "NOAA Wx", "gain": 40, "squelch": 1500,
                                      "dwell": 0.4, "hold": 2.5, "custom": []})
    assert s["gain"] == 40 and s["squelch"] == 1500
    assert s["bank"] == "NOAA Wx" and s["custom"] == [] and s["hold"] == 2.5
