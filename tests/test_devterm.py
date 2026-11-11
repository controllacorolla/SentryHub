"""Dev terminal: BLE/MQTT/SSH pure helpers (no radio, no hardware)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devterm as D   # noqa: E402


def test_fmt_rssi_bands():
    assert D.fmt_rssi(-47) == ("-47", "▂▄▆█")
    assert D.fmt_rssi(-63)[1] == "▂▄▆"
    assert D.fmt_rssi(-80)[1] == "▂▄"
    assert D.fmt_rssi(-95)[1] == "▂"
    assert D.fmt_rssi(None) == ("—", "")


def test_char_props_order_and_filter():
    assert D.char_props(["read", "notify", "write"]) == "R W N"
    assert D.char_props(["write-without-response", "indicate"]) == "w I"
    assert D.char_props([]) == "" and D.char_props(None) == ""


def test_decode_char_text_vs_hex():
    assert D.decode_char(b"RF Reaper Labs") == "RF Reaper Labs"
    assert D.decode_char(b"\x00\x6a\xd8\x19") == "00 6a d8 19"
    assert D.decode_char(None) == "—"
    assert D.decode_char(b"ok\nline") == "ok\\nline"       # control shown as escape


def test_mqtt_value_shapes():
    assert D.mqtt_value(b'{"rf":"idle","heap":180000}') == '{"rf":"idle","heap":180000}'
    assert D.mqtt_value("21.4") == "21.4"
    assert D.mqtt_value(b"\xff\xfe\x01") == "ff fe 01"
    assert D.mqtt_value('{"a": 1}') == '{"a":1}'           # re-compacted
    assert D.mqtt_value("x" * 200).endswith("x") and len(D.mqtt_value("x" * 200)) == 80


def test_topic_leaf():
    assert D.topic_leaf("reaper/temp") == "temp"
    assert D.topic_leaf("a/b/c/") == "c"
    assert D.topic_leaf("solo") == "solo"


def test_parse_ssh_config():
    cfg = ("Host pi lab\n  HostName 10.0.0.5\n\n"
           "# a comment\n"
           "Host *\n  User x\n"
           "Host !bad prod\n  HostName example.com\n"
           "Host pi\n  Port 2222\n")           # duplicate 'pi' collapses
    assert D.parse_ssh_config(cfg) == ["pi", "lab", "prod"]


def test_ssh_hosts_merges_extra(tmp_path):
    p = tmp_path / "config"
    p.write_text("Host alpha\n  HostName 1.2.3.4\n")
    assert D.ssh_hosts(str(p), extra=["beta", "alpha"]) == ["alpha", "beta"]
    assert D.ssh_hosts(str(tmp_path / "nope"), extra=["only"]) == ["only"]


def test_demo_mqtt_publishes():
    import queue
    q = queue.Queue()
    m = D.DemoMqtt(q)
    import time
    time.sleep(1.2)
    m.close()
    kinds = []
    while not q.empty():
        kinds.append(q.get()[0])
    assert "status" in kinds and "msg" in kinds


def test_doctor_devterm_check():
    import doctor
    ok, detail, fix = doctor.chk_devterm(which=lambda n: "/usr/bin/" + n)
    assert "SSH" in detail
    ok, detail, fix = doctor.chk_devterm(which=lambda n: None)
    assert "openssh-client" in fix
