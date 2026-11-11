"""Signals decoders: ACARS, VDL2, rtl_433 sensors, and command building."""
import json
import signals


# ---- parse_acars -------------------------------------------------------------
def test_acars_json_tail_and_text():
    line = json.dumps({"tail": "N827NN", "flight": "AAL123", "label": "H1", "text": "OPS NORMAL"})
    d = signals.parse_acars(line)
    assert d["reg"] == "N827NN"
    assert d["flight"] == "AAL123"
    assert d["label"] == "H1"
    assert d["text"] == "OPS NORMAL"


def test_acars_json_registration_alias():
    # the parser accepts registration/tail/reg interchangeably
    d = signals.parse_acars(json.dumps({"registration": "N1", "fid": "DAL9", "message": "hi"}))
    assert d["reg"] == "N1" and d["flight"] == "DAL9" and d["text"] == "hi"


def test_acars_comment_lines_are_dropped():
    assert signals.parse_acars("# a comment") is None
    assert signals.parse_acars("[frame]") is None
    assert signals.parse_acars("ab") is None   # too short


def test_acars_freeform_fallback_keeps_text():
    d = signals.parse_acars("something not matching the oneline grammar")
    assert d is not None and d["text"].startswith("something")


# ---- parse_vdl2 --------------------------------------------------------------
def test_vdl2_extracts_nested_acars():
    line = json.dumps({"vdl2": {"avlc": {"acars": {
        "reg": "N1", "flight": "UAL1", "label": "5Z", "msg_text": "REQ"}}}})
    d = signals.parse_vdl2(line)
    assert d["reg"] == "N1" and d["flight"] == "UAL1" and d["text"] == "REQ"


def test_vdl2_frame_without_acars_is_terse():
    d = signals.parse_vdl2(json.dumps({"vdl2": {"avlc": {"src": {"addr": "ABC123"}}}}))
    assert d["label"] == "VDL2" and "ABC123" in d["text"]


def test_vdl2_rejects_non_json():
    assert signals.parse_vdl2("not json") is None
    assert signals.parse_vdl2("") is None


# ---- parse_sensor ------------------------------------------------------------
def test_sensor_requires_model():
    assert signals.parse_sensor(json.dumps({"id": 5})) is None
    assert signals.parse_sensor("garbage") is None


def test_sensor_builds_key_and_fields():
    line = json.dumps({"model": "Acurite", "id": 42, "temperature_C": 21.5, "humidity": 55})
    rec = signals.parse_sensor(line)
    assert rec["key"] == "Acurite/42"
    labels = dict(rec["fields"])
    assert "temp" in labels and "hum" in labels


# ---- build_argv --------------------------------------------------------------
def test_build_argv_switches_on_source():
    base = dict(signals.DEFAULTS)
    base["source"] = "acars"
    assert "acarsdec" in signals.build_argv(base)[0]
    base["source"] = "sensors"
    assert "rtl_433" in signals.build_argv(base)[0]
    base["source"] = "vdl2"
    assert "dumpvdl2" in signals.build_argv(base)[0]


def test_build_argv_interpolates_gain():
    base = dict(signals.DEFAULTS, source="sensors", gain=33)
    assert "33" in signals.build_argv(base)
