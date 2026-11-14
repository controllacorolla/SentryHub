"""Regression tests for the bugs fixed in the proactive bug hunt."""
import threading

import hwlab
import sitrep
import sstv
import tiles


def test_bulk_download_stays_active_when_second_request_is_all_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(tiles, "CACHE_ROOT", str(tmp_path))
    t = tiles.TileLayer(workers=0)
    t.bulk_keys = {("dark", 9, 1, 1)}
    t.bulk = {"total": 5, "done": 2, "active": True}
    monkeypatch.setattr(t, "bbox_keys", lambda *a: [])      # everything already on disk
    assert t.download_bbox("dark", 0, 0, 1, 1, 9, 9) == 0
    assert t.bulk == {"total": 5, "done": 2, "active": True}


def test_bulk_download_with_nothing_to_fetch_is_inactive(monkeypatch, tmp_path):
    monkeypatch.setattr(tiles, "CACHE_ROOT", str(tmp_path))
    t = tiles.TileLayer(workers=0)
    monkeypatch.setattr(t, "bbox_keys", lambda *a: [])
    t.download_bbox("dark", 0, 0, 1, 1, 9, 9)
    assert t.bulk["active"] is False


def test_eta_text_keeps_the_whole_eta():
    assert sstv.eta_text(1000 + 12 * 60, 1000) == "in 12 min"
    assert sstv.eta_text(1000 + 125 * 60, 1000) == "in 2h05"
    assert sstv.pass_line({"aos": 1000 + 720, "los": 1000 + 1300, "max": 40}, 1000).endswith("in 12 min")


def test_serial_reader_keeps_raw_bytes_for_hex_view():
    r = object.__new__(hwlab.SerialReader)          # no port: just the buffering
    r.lock, r.inbuf, r.raw = threading.Lock(), bytearray(b"\x00\x01ab\r\nxy"), bytearray()
    r.framer = hwlab.LineFramer()
    assert len(r.read_lines()) == 1
    assert r.take_raw() == b"\x00\x01ab\r\nxy"
    assert r.take_raw() == b""


def test_demo_serial_has_raw_bytes_too():
    d = hwlab.DemoSerial()
    lines = d.read_lines()
    raw = d.take_raw()
    assert lines and raw.startswith(lines[0].encode() + b"\r\n")


def test_sitrep_speech_cannot_be_parsed_as_options(monkeypatch):
    seen = []
    monkeypatch.setattr(sitrep.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(sitrep.S, "fire_and_forget", seen.append)
    sitrep.speak("- First item.")
    assert seen[0][-2:] == ["--", "- First item."]


def test_hub_app_keys_are_unique():
    """Two apps sharing a key ("pass") made one tile open the other app."""
    import ast
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hub.py"),
               encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            assert len(keys) == len(set(keys)), "duplicate key in dict at hub.py:%d" % node.lineno


def test_settings_keeps_a_corrupt_file_instead_of_erasing_it(tmp_path, monkeypatch):
    import suite
    monkeypatch.setattr(suite, "CFG", str(tmp_path))
    p = tmp_path / "demo.json"
    p.write_text('{"channels": [1,2,3],}')          # trailing comma: a hand edit gone wrong
    s, path = suite.settings("demo", {"gain": 7})
    assert s["gain"] == 7                            # started on defaults
    assert (tmp_path / "demo.json.corrupt").read_text() == '{"channels": [1,2,3],}'


def test_settings_missing_file_leaves_no_corrupt_sidecar(tmp_path, monkeypatch):
    import suite
    monkeypatch.setattr(suite, "CFG", str(tmp_path))
    suite.settings("fresh", {"gain": 7})
    assert not (tmp_path / "fresh.json.corrupt").exists()


def test_backup_includes_sky_settings_and_data(tmp_path, monkeypatch):
    import os
    import tarfile
    import suite
    home = tmp_path
    monkeypatch.setattr(suite, "HOME", str(home))
    monkeypatch.setattr(suite, "CFG", str(home / ".config" / "uconsole-suite"))
    monkeypatch.setattr(suite, "CACHE", str(home / ".cache" / "uconsole-suite"))
    for rel in (".config/uconsole-suite/fm.json", ".config/sky-app/settings.json",
                ".local/share/uconsole-suite/sky_coverage.json",
                ".local/share/uconsole-suite/logbook/lifetime.json",
                ".cache/sky-app/bingo.json"):
        f = home / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}")
    dest, _ = suite.backup_configs(dest=str(home / "b.tar.gz"))
    members = set(tarfile.open(dest).getnames())
    for rel in (".config/sky-app/settings.json", ".local/share/uconsole-suite/sky_coverage.json",
                ".local/share/uconsole-suite/logbook/lifetime.json", ".cache/sky-app/bingo.json"):
        assert rel in members, rel


def test_lease_release_without_restart_frees_the_lease(tmp_path, monkeypatch):
    import suite
    monkeypatch.setattr(suite, "LEASE_STATE", str(tmp_path / "lease.json"))
    restarted = []
    monkeypatch.setattr(suite.core, "sudo_systemctl", lambda *a: restarted.append(a) or (0, ""))
    lease = suite.RtlLease("TestApp")
    lease.held = True
    lease._write(paused=["readsb"])
    suite._HOLDER[0] = lease
    lease.release(restart=False)
    assert lease.held is False
    assert suite._HOLDER[0] is None
    assert restarted == []                           # readsb was NOT restarted


def test_aprs_compressed_altitude_is_decoded():
    """The altitude branch was dead: the course/speed catch-all always won first."""
    import aprs
    t_alt = chr(33 + 0b10000)        # type byte: ((ord(t)-33)>>3)&3 == 2 -> altitude in c/s bytes
    r = aprs._compressed("/ABCDEFGHX" + "AB" + t_alt + "comment")
    assert "alt_ft" in r and "course" not in r
    t_cs = chr(33 + 0b01000)         # type byte not flagging altitude -> course/speed
    r2 = aprs._compressed("/ABCDEFGHX" + "AB" + t_cs + "x")
    assert "course" in r2 and "alt_ft" not in r2


def test_alerts_geofence_rule_without_centre_does_not_crash():
    import alerts
    eng = alerts.AlertEngine()
    eng.add_rule({"id": "b", "type": "geofence", "params": {}})                       # no centre
    eng.add_rule({"id": "g", "type": "geofence",
                  "params": {"lat": 39.0, "lon": -104.0, "radius_nm": 5, "mode": "enter"}})
    # the malformed rule must not raise and must not stop the good rule from firing
    out = eng.feed({"id": "ac1", "lat": 39.0, "lon": -104.0})
    assert [a for a in out if a["rule_id"] == "g"]
