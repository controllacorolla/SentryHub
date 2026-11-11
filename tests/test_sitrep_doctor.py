"""Sitrep brief rendering + TFR filtering, and Doctor check contracts."""
import json
import doctor
import sitrep


# ---- sitrep.template ---------------------------------------------------------
def test_template_reads_home_field_name(monkeypatch):
    # should say the field's name, not a hardcoded "Denver"
    monkeypatch.setattr(sitrep.core, "AIRPORTS", {"KAPA": {"name": "Centennial"}})
    d = {"time": "12:00", "metar": {"cat": "VFR", "temp": 14, "wind_dir": 270,
                                    "wind_spd": 8, "station": "KAPA"}}
    out = sitrep.template(d)
    assert "Centennial is clear" in out
    assert "Denver" not in out


def test_template_summarizes_tfrs():
    d = {"time": "12:00", "metar": None,
         "tfrs": [{"type": "VIP", "state": "CO"}, {"type": "VIP", "state": "CO"},
                  {"type": "HAZARDS", "state": "CO"}]}
    out = sitrep.template(d)
    assert "3 active flight restrictions" in out and "vip" in out


def test_template_handles_empty_dict():
    out = sitrep.template({"time": "00:00"})
    assert out.startswith("Situation report")


def test_tfr_filters_by_state(monkeypatch):
    sample = [{"type": "VIP", "state": "CO", "description": "Denver"},
              {"type": "HAZARDS", "state": "TX", "description": "Dallas"}]

    class FakeResp:
        def read(self):
            return json.dumps(sample).encode()

    monkeypatch.setattr(sitrep.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    out = sitrep._tfr(["CO"])
    assert len(out) == 1 and out[0]["state"] == "CO"


def test_tfr_network_failure_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("no net")
    monkeypatch.setattr(sitrep.urllib.request, "urlopen", boom)
    assert sitrep._tfr(["CO"]) is None


# ---- doctor check contracts --------------------------------------------------
def test_doctor_checks_return_triples():
    for fn in (doctor.chk_power, doctor.chk_sdcard, doctor.chk_firewall,
               doctor.chk_exposed_services):
        ok, detail, fix = fn()            # must be a 3-tuple, must not raise
        assert ok in (True, False, None)
        assert isinstance(detail, str) and isinstance(fix, str)


def test_listening_ports_returns_list():
    assert isinstance(doctor._listening_ports(), list)


# ---- field-readiness checks -------------------------------------------------

def test_chk_antenna_no_stats(monkeypatch, tmp_path):
    import doctor
    monkeypatch.setattr(doctor, "STATS_PATHS", [str(tmp_path / "missing.json")])
    ok, detail, hint = doctor.chk_antenna()
    assert ok is None


def test_chk_antenna_deaf(monkeypatch, tmp_path):
    import doctor, json
    p = tmp_path / "stats.json"
    p.write_text(json.dumps({"last1min": {"messages": 13}}))
    monkeypatch.setattr(doctor, "STATS_PATHS", [str(p)])
    ok, detail, hint = doctor.chk_antenna()
    assert ok is False and "13" in detail and "ANTENNA" in hint


def test_chk_antenna_healthy(monkeypatch, tmp_path):
    import doctor, json
    p = tmp_path / "stats.json"
    p.write_text(json.dumps({"last1min": {"messages": 840}}))
    monkeypatch.setattr(doctor, "STATS_PATHS", [str(p)])
    ok, detail, hint = doctor.chk_antenna()
    assert ok is True and "840" in detail


def test_chk_antenna_corrupt_stats(monkeypatch, tmp_path):
    import doctor
    p = tmp_path / "stats.json"
    p.write_text("not json {{")
    monkeypatch.setattr(doctor, "STATS_PATHS", [str(p)])
    ok, detail, hint = doctor.chk_antenna()
    assert ok is None


def test_chk_audio_reports_mute(monkeypatch):
    import doctor
    monkeypatch.setattr(doctor.core, "audio_output_name", lambda: "UACM Speaker")
    def fake_run(cmd, timeout=10):
        if "get-sink-mute" in cmd:
            return 0, "Mute: yes"
        if "get-sink-volume" in cmd:
            return 0, "Volume: front-left: 45875 /  70% / -9.3 dB"
        return 0, ""
    monkeypatch.setattr(doctor.core, "run", fake_run)
    ok, detail, hint = doctor.chk_audio()
    assert ok is False and "MUTED" in detail and "set-sink-mute" in hint


def test_chk_audio_ok(monkeypatch):
    import doctor
    monkeypatch.setattr(doctor.core, "audio_output_name", lambda: "UACM Speaker")
    def fake_run(cmd, timeout=10):
        if "get-sink-mute" in cmd:
            return 0, "Mute: no"
        if "get-sink-volume" in cmd:
            return 0, "Volume: front-left: 45875 /  70% / -9.3 dB"
        return 0, ""
    monkeypatch.setattr(doctor.core, "run", fake_run)
    ok, detail, hint = doctor.chk_audio()
    assert ok is True and "70%" in detail


def test_chk_audio_no_server(monkeypatch):
    import doctor
    monkeypatch.setattr(doctor.core, "audio_output_name", lambda: "no audio server")
    ok, detail, hint = doctor.chk_audio()
    assert ok is False and "PipeWire" in hint
