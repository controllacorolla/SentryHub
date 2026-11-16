"""CL2 — gate integrity. One regression test (or group) per audit PoC, for
G1 G2 G3 G4 G5 G8 G9 G10 G11 G12 G13 L1 S2 S3.

Ground rules (plan/briefs/CL2.md): nothing here emits. Every process / serial / HID boundary is
faked: the executor's spawner is injected (a harmless `python -c sleep` stands in for a tool when
a test needs a real process group to kill), serial ports and HID devices are recording fakes, and
DNS is an injected resolver. Strict owner-decision defaults are asserted, not assumed.
"""
import math
import os
import subprocess
import sys
import time

import pytest

SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

import engagement as E  # noqa: E402
import txguard as G  # noqa: E402

OP = "KD0ABC"                         # the operator identity the test profile resolves to
TXS = {"tx_enabled": True, "callsign": OP, "bench_conducted_ack": True}


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.delenv("SUITE_TX_LOCK", raising=False)
    monkeypatch.delenv("PALISADE_GATE_STATE", raising=False)
    monkeypatch.setattr(E, "_profile_operator", lambda: OP, raising=False)
    G.reset_session()
    E.reset()
    try:
        import executor
        executor.reset()
        monkeypatch.setattr(executor, "SERIAL_LOG", str(tmp_path / "serial_tx.jsonl"),
                            raising=False)
    except ImportError:
        pass
    yield
    try:
        import executor
        executor.kill_all("test teardown")
        executor.reset()
    except ImportError:
        pass
    G.reset_session()
    E.reset()


def _arm_unlock():
    G.arm(True)
    G.unlock_session(True)


def _sleeper_spawner(calls):
    """Stand-in for a real tool: records the authorized argv, runs a harmless sleep in its own
    process group so kill paths are exercised for real."""
    def spawn(argv, **kw):
        calls.append(list(argv))
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    return spawn


def _exit_spawner(calls, code, out="line one\nline two\n"):
    def spawn(argv, **kw):
        calls.append(list(argv))
        return subprocess.Popen([sys.executable, "-c",
                                 "import sys; sys.stdout.write(%r); sys.exit(%d)" % (out, code)],
                                start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    return spawn


def _wait_dead(proc, timeout=5.0):
    t0 = time.time()
    while proc.poll() is None and time.time() - t0 < timeout:
        time.sleep(0.02)
    return proc.poll() is not None


# ============================================================================ G1 — BENCH
def _qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _pump(ms=60):
    app = _qapp()
    t0 = time.time()
    while (time.time() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.005)


def test_g1_bench_checkbox_alone_does_not_enable_tx_poc(tmp_path, monkeypatch):
    """PoC: txguard disarmed, no engagement — ticking the conducted checkbox enabled the TX
    button and bench.transmit produced the hackrf_transfer command."""
    _qapp()
    import bench
    from palisade_qt.bench_app import BenchApp
    iq = tmp_path / "sig.iq"
    iq.write_bytes(b"\x00\x01" * 64)
    p = BenchApp(demo=False, mode="dark")
    try:
        p._saved = lambda: dict(bench.DEFAULTS)          # the saved bench settings: default (off)
        p.ack.setChecked(True)
        assert not p.tx_btn.isEnabled(), "one checkbox enabled the TX button"
        s = p._settings()
        assert s["tx_enabled"] is False, "bench forced tx_enabled=True over the saved setting"
        s["iq_file"] = str(iq)
        calls = []
        res = bench.transmit(s, spawner=_sleeper_spawner(calls))
        assert res[0] is False and calls == [], "bench.transmit produced a command while disarmed"
    finally:
        p.stop()


def test_g1_bench_has_no_121_5_preset():
    _qapp()
    from palisade_qt import bench_app
    assert all(f != 121_500_000 for _label, f in bench_app.BANDS)
    assert not any("121.5" in label for label, _f in bench_app.BANDS)


def test_g1_bench_conducted_protected_band_is_denied_strict_default():
    """Owner decision 1 (strict): conducted bench on a protected band is DENIED, as a named
    constant that can be relaxed later."""
    assert G.CONDUCTED_PROTECTED_ALLOWED is False
    _arm_unlock()
    for f in (1_090_000_000, 121_500_000, 1_575_420_000):
        ok, why, _p = G.authorize("bench", f, settings=TXS)
        assert not ok and "protected" in why.lower(), (f, why)
    ok, _why, _p = G.authorize("bench", 915_000_000, settings=TXS)
    assert ok


def test_g1_bench_needs_arm_unlock_and_reports_real_exit_code(tmp_path, monkeypatch):
    import bench
    import executor
    monkeypatch.setattr(bench, "TX_LOG", str(tmp_path / "bench.log"))
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 64)
    s = dict(TXS, freq_hz=915_000_000, iq_file=str(iq))
    calls = []
    ok, msg, code = bench.transmit(s, spawner=_exit_spawner(calls, 3))
    assert not ok and calls == [] and "kill switch" in msg.lower()       # disarmed
    G.arm(True)
    ok, msg, code = bench.transmit(s, spawner=_exit_spawner(calls, 3))
    assert not ok and calls == [] and "unlock" in msg.lower()            # armed, not unlocked
    G.unlock_session(True)
    ok, msg, code = bench.transmit(s, spawner=_exit_spawner(calls, 3))
    assert len(calls) == 1 and calls[0][0] == "hackrf_transfer"
    assert code == 3 and ok is False and "exit 3" in msg                 # the runner's real result
    assert "transmitting" not in msg.lower()
    ok, msg, code = bench.transmit(s, spawner=_exit_spawner(calls, 0))
    assert ok and code == 0
    assert executor.running() == []


def test_g1_bench_run_is_registered_and_stoppable(tmp_path, monkeypatch):
    import bench
    import executor
    monkeypatch.setattr(bench, "TX_LOG", str(tmp_path / "bench.log"))
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 64)
    _arm_unlock()
    calls = []
    ok, why, handle = bench.start_transmit(dict(TXS, freq_hz=915_000_000, iq_file=str(iq)),
                                           spawner=_sleeper_spawner(calls))
    assert ok and handle in executor.running()
    handle.stop()
    assert _wait_dead(handle.proc)
    assert handle.exit_code is not None and handle not in executor.running()


def test_g1_bench_ui_reads_saved_settings_and_wording():
    _qapp()
    from palisade_qt.bench_app import BenchApp
    p = BenchApp(demo=False, mode="dark")
    try:
        p._saved = lambda: {"tx_enabled": True}          # the saved bench settings say yes
        _arm_unlock()
        p.ack.setChecked(True)
        p._refresh_gate()
        assert p.tx_btn.isEnabled() and "TX PERMITTED" in p.gate.text()
        assert "SAFE" not in p.gate.text()
        G.arm(False)
        _pump()
        assert not p.tx_btn.isEnabled() and "GATED" in p.gate.text()     # follows the engine
    finally:
        p.stop()


# ============================================================================ G2 + G3 — serial / Flipper
FLIPPER_EMIT_POCS = ["subghz chat 433920000", "ir universal tv power", "loader open Sub-GHz",
                     "input send ok short", "js /ext/apps/x.js", "rfid raw_emulate /ext/r",
                     "storage remove /ext/x", "device_info\rsubghz tx 0 433920000",
                     "device_info\nsubghz tx_from_file /ext/g.sub", "subghz tx 1 433920000",
                     "badusb run /ext/x.txt", "gpio set PA7 1"]


def test_g3_flipper_classifier_is_an_allowlist_poc():
    import flipper
    for cmd in FLIPPER_EMIT_POCS:
        assert flipper.classify_command(cmd) == "emit", cmd
    for cmd in ("device_info", "storage list /ext", "power info", "help", "uptime"):
        assert flipper.classify_command(cmd) == "read", cmd


def test_g3_emit_pocs_refused_without_engagement():
    import flipper
    for cmd in FLIPPER_EMIT_POCS:
        ok, why, ticket = flipper.prepare_command(cmd, device="usb:0483:5740", kind="flipper")
        assert not ok and ticket is None, cmd


def test_g3_cr_lf_refused_even_with_engagement():
    import flipper
    E.start("job", "ROE-1", ["usb:0483:5740"], OP)
    for cmd in ("device_info\rsubghz tx 0 1", "device_info\nstorage remove /x", "help\x03"):
        ok, why, ticket = flipper.prepare_command(cmd, device="usb:0483:5740", kind="flipper")
        assert not ok and ticket is None and "control" in why.lower(), cmd


def test_g3_allowlisted_read_passes_and_emit_is_label_only_with_engagement():
    import flipper
    ok, why, ticket = flipper.prepare_command("device_info", device="usb:0483:5740", kind="flipper")
    assert ok and ticket is not None and ticket.payload == b"device_info\r\n"
    E.start("job", "ROE-1", ["usb:0483:5740"], OP)
    G.arm(True)                      # CL2-fix N2: an RF emitter also needs the kill switch armed
    ok, why, ticket = flipper.prepare_command("subghz tx 0 433920000", device="usb:0483:5740",
                                              kind="flipper")
    assert ok and "label-only authorization" in why and ticket.binding == "label-only"


def test_g2_unknown_and_emitter_devices_are_read_only_until_engagement():
    import flipper
    for kind, dev in (("unknown", "usb:1a86:7523"), ("esp32", "usb:10c4:ea60"),
                      ("slcan", "usb:1d50:606f"), ("unknown", "port:ttyS0")):
        ok, why, ticket = flipper.prepare_command("AT", device=dev, kind=kind)
        assert not ok and ticket is None, (kind, why)
    E.start("job", "ROE-1", ["usb:10c4:ea60"], OP)
    G.arm(True)                      # CL2-fix N2: an RF emitter also needs the kill switch armed
    assert flipper.prepare_command("AT", device="usb:10c4:ea60", kind="esp32")[0] is True
    assert flipper.prepare_command("AT", device="usb:1a86:7523", kind="unknown")[0] is False


def test_g2_device_identified_by_usb_vid_pid(tmp_path):
    import flipper
    # fake sysfs: /sys/class/tty/ttyACM0/device -> ../../usbdev/1-1:1.0, idVendor in the parent
    usb = tmp_path / "devices" / "usb1" / "1-1"
    iface = usb / "1-1:1.0"
    iface.mkdir(parents=True)
    (usb / "idVendor").write_text("0483\n")
    (usb / "idProduct").write_text("5740\n")
    (usb / "product").write_text("Flipper Zero Virtual ComPort\n")
    tty = tmp_path / "class" / "tty" / "ttyACM0"
    tty.mkdir(parents=True)
    os.symlink(str(iface), str(tty / "device"))
    ident = flipper.identify_port("/dev/ttyACM0", sys_root=str(tmp_path))
    assert ident == ("flipper", "usb:0483:5740")
    # same VID:PID without the Flipper product string is NOT trusted as a Flipper
    (usb / "product").write_text("STM32 Virtual ComPort\n")
    assert flipper.identify_port("/dev/ttyACM0", sys_root=str(tmp_path))[0] == "unknown"
    assert flipper.identify_port("/dev/ttyS0", sys_root=str(tmp_path)) == ("unknown", "port:ttyS0")


class _FakePort:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    def read_lines(self):
        return []

    def close(self):
        pass


def test_g2_qt_serial_tab_never_writes_ungated_poc(monkeypatch):
    """PoC: the SERIAL tab wrote whatever was typed to any serial device."""
    _qapp()
    import flipper
    from palisade_qt import forge
    monkeypatch.setattr(flipper, "identify_port", lambda port, sys_root="/sys":
                        ("flipper", "usb:0483:5740"), raising=False)
    w = forge.SerialWorker(demo=False, port="/dev/ttyACM0")
    fake = _FakePort()
    w._open = lambda: fake
    rows = []
    w.row.connect(rows.append)
    w.write("subghz chat 433920000")
    w.write("device_info\nsubghz tx 0 433920000")
    w.step()
    _pump()
    assert fake.writes == [], "emit command reached the port with no engagement"
    w.write("device_info")
    w.step()
    assert fake.writes == [b"device_info\r\n"]
    w.stop()


def test_g2_every_sent_line_is_logged(monkeypatch, tmp_path):
    import executor
    import flipper
    import json
    port = _FakePort()
    ok, why, ticket = flipper.prepare_command("device_info", device="usb:0483:5740", kind="flipper")
    n = executor.write(ticket, port, port_name="/dev/ttyACM0")
    assert n == len(b"device_info\r\n") and port.writes == [b"device_info\r\n"]
    recs = [json.loads(x) for x in open(executor.SERIAL_LOG).read().splitlines()]
    assert recs[-1]["line"] == "device_info" and recs[-1]["port"] == "/dev/ttyACM0"
    assert recs[-1]["device"] == "usb:0483:5740"


def test_g2_tk_hwlab_send_goes_through_the_gate():
    import hwlab
    port = _FakePort()
    ok, msg = hwlab.gated_send(port, "subghz tx 0 1", device=("flipper", "usb:0483:5740"),
                               port_name="/dev/ttyACM0")
    assert not ok and port.writes == []
    ok, msg = hwlab.gated_send(port, "device_info", device=("flipper", "usb:0483:5740"),
                               port_name="/dev/ttyACM0")
    assert ok and port.writes == [b"device_info\r\n"]


# ============================================================================ G4 — scope matching
def _resolver(table):
    def resolve(host):
        if host not in table:
            raise OSError("NXDOMAIN")
        return list(table[host])
    return resolve


def test_g4_glob_and_wildcard_scope_rejected_poc():
    for bad in (["192.168.1.*"], ["*"], ["192.168.1.1/0"], ["192.168.1.0-255.0-255"],
                ["[ab]c"], ["Net-*"], ["10.0.0.0/4"], ["", "x"], [None]):
        ok, why = E.start("job", "ROE-1", bad, OP)
        assert not ok and not E.is_active(), (bad, why)


def test_g4_string_scope_does_not_become_characters_poc():
    ok, why = E.start("job", "ROE-1", "192.168.1.0/24", OP)
    assert not ok and "list" in why.lower()


def test_g4_netpent_poc_targets_out_of_scope(monkeypatch):
    import netpent
    monkeypatch.setattr(E, "_resolve", _resolver({"192.168.1.evil.example.com": ["203.0.113.9"],
                                                  "nas.lan": ["192.168.1.40"],
                                                  "split.lan": ["192.168.1.41", "8.8.8.8"]}))
    assert E.start("job", "ROE-1", ["192.168.1.0/24"], OP)[0]
    for t in ("192.168.1.1/0", "192.168.1.0-255.0-255", "192.168.1.evil.example.com",
              "192.168.0.0/16", "192.168.2.1", "split.lan", "nx.example", "*", "192.168.1.*"):
        ok, why, ticket = netpent.prepare("portscan", t)
        assert not ok and ticket is None, t
    for t in ("192.168.1.10", "192.168.1.0/25", "192.168.1.10-192.168.1.20", "nas.lan"):
        ok, why, ticket = netpent.prepare("portscan", t)
        assert ok and ticket is not None, (t, why)


def test_g4_ip_range_and_host_scope_entries(monkeypatch):
    monkeypatch.setattr(E, "_resolve", _resolver({"gw.lab": ["10.9.0.1"]}))
    assert E.start("job", "ROE-1", ["10.0.0.5-10.0.0.9", "gw.lab"], OP)[0]
    assert E.check("net:x", "10.0.0.7", kind="ip")[0]
    assert not E.check("net:x", "10.0.0.10", kind="ip")[0]
    assert E.check("net:x", "10.9.0.1", kind="ip")[0]          # the host entry's pinned address
    assert not E.check("net:x", "10.0.0.0/24", kind="ip")[0]


# ============================================================================ G5 — bind scope to the command
def test_g5_pmkid_command_carries_the_bssid_filter_poc():
    import wifipent
    E.start("job", "ROE-1", ["AA:BB:CC:DD:EE:FF"], OP)
    G.arm(True)                      # CL2-fix N2: an RF emitter also needs the kill switch armed
    ok, why, ticket = wifipent.prepare("pmkid", "AA:BB:CC:DD:EE:FF", out="cap")
    assert ok
    argv = list(ticket.argv)
    assert any(a.startswith("--filterlist_ap=") for a in argv) and "--filtermode=2" in argv
    fpath = [a.split("=", 1)[1] for a in argv if a.startswith("--filterlist_ap=")][0]
    assert ticket.files[fpath].strip().upper() == "AABBCCDDEEFF"


def test_g5_deauth_requires_and_scope_checks_the_client_poc():
    import wifipent
    E.start("job", "ROE-1", ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"], OP)
    G.arm(True)                      # CL2-fix N2: an RF emitter also needs the kill switch armed
    ok, why, t = wifipent.prepare("deauth", "AA:BB:CC:DD:EE:FF")
    assert not ok and t is None and "client" in why.lower()            # no broadcast
    ok, why, t = wifipent.prepare("deauth", "AA:BB:CC:DD:EE:FF", client="99:99:99:99:99:99")
    assert not ok and t is None
    ok, why, t = wifipent.prepare("deauth", "AA:BB:CC:DD:EE:FF", client="11:22:33:44:55:66")
    assert ok and "-c" in t.argv and "11:22:33:44:55:66" in t.argv


def test_g5_can_scope_is_interface_plus_id_range():
    import canbus
    E.start("job", "ROE-1", ["can0:0x700-0x7FF"], OP)
    assert canbus.prepare_send("can0", 0x7DF, b"\x02\x01\x0c")[0] is True
    assert canbus.prepare_send("can0", 0x100, b"\x00")[0] is False
    assert canbus.prepare_send("can1", 0x7DF, b"\x00")[0] is False


def test_g5_zigbee_scope_is_pan_and_channel():
    import zigbee
    E.start("job", "ROE-1", ["pan:0x1A2B@15"], OP)
    G.arm(True)                      # CL2-fix N2: an RF emitter also needs the kill switch armed
    assert zigbee.prepare("inject", pan=0x1A2B, channel=15)[0] is True
    assert zigbee.prepare("inject", pan=0x1A2B, channel=20)[0] is False
    assert zigbee.prepare("inject", pan=0x9999, channel=15)[0] is False
    ok, why, t = zigbee.prepare("discover", channel=15)
    assert ok and "15" in t.argv


def test_g5_proxmark_reads_back_uid_before_write():
    import proxmark
    E.start("job", "ROE-1", ["uid:DEADBEEF"], OP)
    G.arm(True)                      # CL2-fix N2: an RF emitter also needs the kill switch armed
    ok, why, t = proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="DEADBEEF",
                                  read_uid=lambda: "04A22B3C")
    assert not ok and t is None and "uid" in why.lower()
    ok, why, t = proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="DEADBEEF",
                                  read_uid=lambda: None)
    assert not ok and t is None                                         # no read-back: refuse
    ok, why, t = proxmark.prepare("hf_mf_sim", target="uid:DEADBEEF", uid="DEADBEEF",
                                  read_uid=lambda: "de ad be ef")
    assert ok and t is not None


def test_g5_unbindable_tools_say_label_only():
    import buslab
    import usbhid
    import zwave
    E.start("job", "ROE-1", ["LAPTOP-7", "ROUTER-1", "NODE-5"], OP)
    G.arm(True)                      # CL2-fix N2: an RF emitter also needs the kill switch armed
    for ok, why, t in (usbhid.prepare("STRING hi", "LAPTOP-7"),
                       buslab.prepare_flash_write("ch341a_spi", "fw.bin", target="ROUTER-1"),
                       zwave.prepare("query", target="NODE-5", node_id=5)):
        assert ok and "label-only authorization" in why and t.binding == "label-only"
    rec = E.actions()[-1]
    assert rec["binding"] == "label-only"


# ============================================================================ G8 — one gate
def test_g8_decide_is_private_and_lora_never_bypasses_poc(monkeypatch):
    assert not hasattr(G, "decide"), "decide() is still a public, arm-less entry point"
    assert G.EXEMPT_SERVICES == ()
    # PoC: service="lora" passed for any frequency with tx_enabled false
    ok, why, _p = G.authorize("lora", 1_090_000_000, settings={"tx_enabled": False})
    assert not ok
    _arm_unlock()
    ok, why, _p = G.authorize("lora", 1_090_000_000, settings={"tx_enabled": True})
    assert not ok and "protected" in why.lower()
    ok, why, _p = G.authorize("lora", 915_000_000, settings={"tx_enabled": False})
    assert not ok
    ok, why, _p = G.authorize("lora", None, settings={"tx_enabled": True})
    assert not ok


def test_g8_every_public_tx_entry_refuses_when_disarmed(tmp_path, monkeypatch):
    import bench
    import digimodes
    import loopback
    import mesh_dash
    import radio
    import replay
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 64)
    calls = []
    sp = _sleeper_spawner(calls)
    assert bench.transmit(dict(TXS, freq_hz=915_000_000, iq_file=str(iq)), spawner=sp)[0] is False
    assert replay.prepare_replay(str(iq), 915_000_000, 2_000_000, True, settings=TXS)[0] is False
    assert digimodes.prepare("ft8", callsign=OP, settings=TXS, which=lambda t: "/bin/" + t)[0] is False
    assert loopback.hardware_loopback_plan("aprs", 144_390_000, TXS,
                                           devices=[{"id": "hackrf", "name": "HackRF", "tx": True,
                                                     "freq_hz": (1e6, 6e9), "power_dbm_max": 15}])[0] is False
    assert radio.TxRequest("aprs", 144_390_000, callsign=OP, settings=TXS).authorize(
        devices=[{"id": "hackrf", "name": "HackRF", "tx": True, "freq_hz": (1e6, 6e9)}])[0] is False
    assert mesh_dash.authorize_send({"tx_enabled": True, "lora_region": "US"})[0] is False
    assert calls == []
    # and with the kill switch armed + unlocked, the same mesh send passes the one chain
    _arm_unlock()
    assert mesh_dash.authorize_send({"tx_enabled": True, "lora_region": "US"})[0] is True
    assert mesh_dash.authorize_send({"tx_enabled": True, "lora_region": "XX"})[0] is False


def test_g8_unlock_is_a_real_ui_control():
    _qapp()
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=False, mode="dark")
    hub.resize(1280, 720)
    hub.show()
    try:
        hub._list_children = lambda: []
        hub.open_panel("tx")
        panel = hub.tx_panel
        assert panel.isVisible()
        assert not panel.unlock_btn.isEnabled()                  # unlock needs arm first
        panel.arm_btn.click()
        _pump()
        assert G.is_armed() and panel.unlock_btn.isEnabled()
        panel.unlock_btn.click()
        _pump()
        assert G.session_unlocked()
        assert hub.topbar.slots["tx"].text().startswith("UNLOCKED")
        panel.arm_btn.click()                                     # disarm drops the unlock
        _pump()
        assert not G.is_armed() and not G.session_unlocked()
    finally:
        hub.close()
        _pump(100)


# ============================================================================ G9 — power / gain
def test_g9_replay_gain_is_derived_and_clamped_poc(tmp_path):
    import replay
    _arm_unlock()
    s = {"tx_enabled": True, "tx_region": "US"}
    cap_gain = G.gain_for_power(G.TX_PROFILES["replay"]["power_dbm_max"])
    assert cap_gain < 47
    for asked in (47, 999):
        ok, why, t = replay.prepare_replay("b.iq", 915_000_000, 2_000_000, True, settings=s,
                                           tx_gain=asked)
        if ok:
            gain = int(t.argv[t.argv.index("-x") + 1])
            assert gain <= cap_gain, (asked, gain)
    for bad in (float("nan"), float("inf"), "nan", -1, 3.5):
        ok, why, t = replay.prepare_replay("b.iq", 915_000_000, 2_000_000, True, settings=s,
                                           tx_gain=bad)
        assert not ok and t is None, bad


def test_g9_nonfinite_power_and_bad_sample_rate_denied():
    import replay
    _arm_unlock()
    s = {"tx_enabled": True}
    for p in (float("nan"), float("inf"), float("-inf"), "x"):
        assert G.authorize("replay", 915_000_000, power_dbm=p, settings=s)[0] is False, p
    assert G.authorize("replay", float("nan"), settings=s)[0] is False
    for sr in (100_000_000, 0, -1, float("nan"), 1_000):
        assert replay.prepare_replay("b.iq", 915_000_000, sr, True, settings=s)[0] is False, sr
    ok, why, power = G.authorize("replay", 915_000_000, power_dbm=40, settings=s)
    assert ok and power == 10
    assert math.isfinite(power)


# ============================================================================ G10 — fail-open details
def test_g10_tx_enabled_must_be_exactly_true_poc():
    for v in ("yes", 1, "true", "True", [1], {"x": 1}):
        assert G.tx_locked({"tx_enabled": v})[0] is True, v
    assert G.tx_locked({"tx_enabled": True})[0] is False
    assert G.tx_locked("not a dict")[0] is True


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "on", "anything"])
def test_g10_any_truthy_tx_lock_locks_poc(monkeypatch, val):
    monkeypatch.setenv("SUITE_TX_LOCK", val)
    _arm_unlock()
    ok, why, _p = G.authorize("aprs", 144_390_000, callsign=OP, settings=TXS)
    assert not ok and "SUITE_TX_LOCK" in why


@pytest.mark.parametrize("val", ["", "0", "false", "no", "off"])
def test_g10_falsy_tx_lock_does_not_lock(monkeypatch, val):
    monkeypatch.setenv("SUITE_TX_LOCK", val)
    _arm_unlock()
    assert G.authorize("aprs", 144_390_000, callsign=OP, settings=TXS)[0] is True


def test_g10_433_is_amateur_in_us_and_ism_elsewhere_poc():
    _arm_unlock()
    us = {"tx_enabled": True, "tx_region": "US"}
    eu = {"tx_enabled": True, "tx_region": "EU"}
    assert G.classify(433_920_000, region="US") == "ham"
    assert G.classify(433_920_000, region="EU") == "ism"
    assert G.authorize("replay", 433_920_000, settings=us)[0] is False    # ISM-only mode refused
    assert G.authorize("replay", 433_920_000, settings=eu)[0] is True
    assert G.authorize("aprs", 433_920_000, settings=us)[0] is False      # ham needs a callsign
    assert G.authorize("aprs", 433_920_000, callsign=OP, settings=us)[0] is True
    # unknown / missing region falls back to the strict US table
    assert G.authorize("replay", 433_920_000, settings={"tx_enabled": True})[0] is False
    assert G.authorize("replay", 433_920_000, settings={"tx_enabled": True,
                                                        "tx_region": "MARS"})[0] is False


# ============================================================================ G11 — tickets + executor
def _netpent_ticket():
    import netpent
    E.start("job", "ROE-1", ["10.0.0.0/24"], OP)
    ok, why, ticket = netpent.prepare("portscan", "10.0.0.5")
    assert ok
    return ticket


def test_g11_ticket_is_single_use():
    import executor
    t = _netpent_ticket()
    calls = []
    r = executor.run(t, spawner=_exit_spawner(calls, 0))
    assert r.exit_code == 0 and len(calls) == 1
    with pytest.raises(executor.TicketRefused):
        executor.run(t, spawner=_exit_spawner(calls, 0))
    assert len(calls) == 1


def test_g11_altered_argv_refused():
    import executor
    t = _netpent_ticket()
    calls = []
    with pytest.raises(executor.TicketRefused):
        executor.run(t, argv=["nmap", "-sS", "-p", "1-1024", "8.8.8.8"],
                     spawner=_exit_spawner(calls, 0))
    with pytest.raises((AttributeError, TypeError)):
        t.argv[4] = "8.8.8.8"                                            # immutable
    with pytest.raises(AttributeError):
        t.argv = ("nmap", "8.8.8.8")
    assert calls == []


def test_g11_forged_ticket_refused():
    import executor
    calls = []
    fake = executor.Ticket.__new__(executor.Ticket)
    with pytest.raises(executor.TicketRefused):
        executor.run(fake, spawner=_exit_spawner(calls, 0))
    with pytest.raises(executor.TicketRefused):
        executor.run(["nmap", "10.0.0.5"], spawner=_exit_spawner(calls, 0))
    assert calls == []


def test_g11_expired_ticket_refused(monkeypatch):
    import executor
    t = _netpent_ticket()
    now = time.monotonic()
    monkeypatch.setattr(executor, "_mono", lambda: now + executor.TICKET_TTL_S + 1)
    calls = []
    with pytest.raises(executor.TicketRefused):
        executor.run(t, spawner=_exit_spawner(calls, 0))
    assert calls == []


def test_g11_gate_rechecked_at_spawn():
    import executor
    t = _netpent_ticket()
    E.end()
    calls = []
    with pytest.raises(executor.TicketRefused):
        executor.run(t, spawner=_exit_spawner(calls, 0))
    assert calls == []


def test_g11_end_engagement_kills_running_process():
    import executor
    t = _netpent_ticket()
    calls = []
    h = executor.start(t, spawner=_sleeper_spawner(calls))
    assert h.proc.poll() is None and h in executor.running()
    E.end()
    assert _wait_dead(h.proc), "END left the authorized process running"
    assert h not in executor.running()


def test_g11_disarm_kills_running_process(tmp_path, monkeypatch):
    import bench
    import executor
    monkeypatch.setattr(bench, "TX_LOG", str(tmp_path / "bench.log"))
    iq = tmp_path / "s.iq"
    iq.write_bytes(b"\x00" * 64)
    _arm_unlock()
    ok, why, h = bench.start_transmit(dict(TXS, freq_hz=915_000_000, iq_file=str(iq)),
                                      spawner=_sleeper_spawner([]))
    assert ok and h.proc.poll() is None
    G.arm(False)
    assert _wait_dead(h.proc), "disarm left the transmitter running"
    assert executor.running() == []


def test_g11_exit_code_goes_to_the_cl3_record_hook(monkeypatch):
    import executor
    got = []
    monkeypatch.setattr(executor, "record", lambda event, **kw: got.append((event, kw)))
    t = _netpent_ticket()
    executor.run(t, spawner=_exit_spawner([], 4))
    assert ("exit", 4) in [(e, kw.get("exit_code")) for e, kw in got]


def test_g11_argv_builders_are_private():
    import bench
    import blepent
    import canbus
    import netpent
    import replay
    import wifipent
    import zigbee
    import zwave
    for mod, names in ((replay, ["replay_argv"]), (bench, ["tx_argv"]),
                       (netpent, ["ping_sweep_argv", "port_scan_argv", "service_enum_argv",
                                  "os_fingerprint_argv", "arp_scan_argv", "survey_argv"]),
                       (wifipent, ["handshake_capture_argv", "pmkid_capture_argv", "deauth_argv"]),
                       (canbus, ["cansend_argv"]), (zigbee, ["discover_argv", "inject_argv"]),
                       (zwave, ["query_argv"]), (blepent, ["gatt_argv"])):
        for n in names:
            assert not hasattr(mod, n), "%s.%s is still public" % (mod.__name__, n)


# ============================================================================ G12 — UI follows engine
def test_g12_engagement_and_txguard_emit_change_signals():
    seen = []
    E.subscribe(lambda: seen.append("eng"))
    G.subscribe(lambda: seen.append("tx"))
    E.start("job", "ROE-1", ["10.0.0.1"], OP)
    G.arm(True)
    G.unlock_session(True)
    G.arm(False)
    E.end()
    assert seen.count("eng") >= 2 and seen.count("tx") >= 3


def test_g12_forge_cards_follow_end_without_a_manual_refresh_poc():
    _qapp()
    from palisade_qt.forge import ForgeApp, EngagementCard
    E.start("job", "ROE-1", ["can0:0x700-0x7FF"], OP)
    forge = ForgeApp(demo=False, mode="dark")
    try:
        cards = [c for c in forge._cards if isinstance(c, EngagementCard)]
        assert cards and all(c._btn.isEnabled() for c in cards)
        E.end()
        _pump()
        for c in cards:
            assert not c._btn.isEnabled()
            assert "engagement active" not in c.state.text()
    finally:
        forge.stop()


def test_g12_replay_banner_agrees_with_engine_poc():
    _qapp()
    from palisade_qt.forge import ForgeApp
    forge = ForgeApp(demo=False, mode="dark")
    try:
        card = forge.replay_card
        card._saved = lambda: {"tx_enabled": True, "tx_region": "US"}
        for armed in (False, True):
            for unlocked in (False, True):
                G.arm(armed)
                G.unlock_session(unlocked)
                _pump(20)
                card.refresh()
                engine_ok = G.authorize("replay", int(card.freq.value() * 1e6),
                                        settings=card._saved())[0]
                says_armed = "armed + unlocked" in card.state.text()
                assert says_armed == engine_ok, (armed, unlocked, card.state.text())
        # armed + unlocked but a band the engine refuses: banner must not claim permission
        G.arm(True)
        G.unlock_session(True)
        card.freq.setValue(1090.0)
        card.refresh()
        assert "armed + unlocked" not in card.state.text() and "DENIED" in card.state.text()
    finally:
        forge.stop()


def test_g12_topbar_tx_slot_is_driven_by_the_engine_not_a_poll():
    _qapp()
    from palisade_qt.shell import PalisadeHub
    hub = PalisadeHub(demo=False, mode="dark")
    try:
        hub._list_children = lambda: []
        hub.state._timer.stop()                                    # no poll: signals only
        G.arm(True)
        _pump()
        assert hub.topbar.slots["tx"].text() == "ARMED"
        E.start("job", "ROE-1", ["10.0.0.1"], OP)
        _pump()
        # CL1-fix: the scope IS the word; ACTIVE lives in the tooltip (amber diamond = active)
        assert hub.topbar.slots["engagement"].glyph.shape() == "diamond"
        assert "ACTIVE" in hub.topbar.slots["engagement"].toolTip()
        G.arm(False)
        E.end()
        _pump()
        assert hub.topbar.slots["tx"].text() == "OFF"
        assert hub.topbar.slots["engagement"].text() == "NONE"
    finally:
        hub.close()
        _pump(100)


# ============================================================================ G13 — engagement lifecycle
def test_g13_second_start_refused_first_kept_poc():
    assert E.start("first", "ROE-1", ["10.0.0.1"], OP)[0]
    E.authorize_action("net:x", "10.0.0.1")
    ok, why = E.start("second", "ROE-2", ["10.0.0.2"], OP)
    assert not ok and "already" in why.lower()
    info = E.info()
    assert info["name"] == "first" and info["scope"] == ["10.0.0.1"]
    assert len(E.actions()) == 1                                         # trail not wiped


def test_g13_expired_engagement_denies(monkeypatch):
    assert E.ENGAGEMENT_HOURS_DEFAULT == 8
    t0 = time.time()
    monkeypatch.setattr(E, "_now", lambda: t0)
    assert E.start("job", "ROE-1", ["10.0.0.1"], OP)[0]
    assert E.info()["expires"] == pytest.approx(t0 + 8 * 3600)
    assert E.authorize_action("net:x", "10.0.0.1")[0]
    monkeypatch.setattr(E, "_now", lambda: t0 + 8 * 3600 + 1)
    ok, why = E.authorize_action("net:x", "10.0.0.1")
    assert not ok and "expired" in why.lower()
    assert not E.is_active() and E.info()["expired"]


def test_g13_expiry_is_configurable_but_bounded():
    assert not E.start("job", "ROE-1", ["10.0.0.1"], OP, hours=float("nan"))[0]
    assert not E.start("job", "ROE-1", ["10.0.0.1"], OP, hours=0)[0]
    assert not E.start("job", "ROE-1", ["10.0.0.1"], OP, hours=24 * 30)[0]
    assert E.start("job", "ROE-1", ["10.0.0.1"], OP, hours=2)[0]


def test_g13_operator_comes_from_the_profile(monkeypatch):
    ok, why = E.start("job", "ROE-1", ["10.0.0.1"], "SOMEONE-ELSE")
    assert not ok and "profile" in why.lower()
    monkeypatch.setattr(E, "_profile_operator", lambda: None)
    ok, why = E.start("job", "ROE-1", ["10.0.0.1"], None)
    assert not ok and "profile" in why.lower()
    monkeypatch.setattr(E, "_profile_operator", lambda: OP)
    ok, why = E.start("job", "ROE-1", ["10.0.0.1"])
    assert ok and E.info()["operator"] == OP


def test_g13_panel_operator_is_read_only_and_auth_not_prefilled(monkeypatch):
    _qapp()
    import opprofile
    monkeypatch.setattr(opprofile, "load", lambda fn, name="operator":
                        {"callsign": OP, "authorization": "ROE-SAVED-LAST-TIME"})
    from palisade_qt import panels
    p = panels.EngagePanel("dark")
    assert p.eng_operator.isReadOnly() and p.eng_operator.text() == OP
    assert p.eng_auth.text() == ""


# ============================================================================ L1 — one gate state across processes
def test_l1_child_sees_parent_arm_and_disarm(tmp_path):
    import gatestate
    pub = gatestate.Publisher(str(tmp_path / "gate.json"))
    try:
        pub.publish(armed=True, unlocked=False, engagement=None)
        st = gatestate.read(str(tmp_path / "gate.json"), nonce=pub.nonce)   # CL2-fix N3: bound
        assert st["armed"] is True and st["unlocked"] is False              # to THIS hub
        pub.publish(armed=False, unlocked=False, engagement=None)
        assert gatestate.read(str(tmp_path / "gate.json"), nonce=pub.nonce)["armed"] is False
    finally:
        pub.close()
    assert not os.path.exists(str(tmp_path / "gate.json"))                # removed on hub exit


_CHILD = r"""
import json, sys
sys.path.insert(0, %r)
import txguard, engagement
print(json.dumps({"armed": txguard.is_armed(), "unlocked": txguard.session_unlocked(),
                  "eng": engagement.is_active(),
                  "auth": engagement.check("net:x", "10.0.0.1", kind="ip")[0],
                  "arm_self": (txguard.arm(True), txguard.is_armed())[1]}))
"""


def _run_child(env):
    out = subprocess.run([sys.executable, "-c", _CHILD % SUITE_DIR], env=env, capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    import json
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_l1_real_child_process_follows_the_hub(tmp_path):
    import gatestate
    path = str(tmp_path / "gate.json")
    pub = gatestate.Publisher(path)
    try:
        E.start("job", "ROE-1", ["10.0.0.0/24"], OP)
        G.arm(True)
        G.unlock_session(True)
        pub.publish_from_engines()
        env = gatestate.child_env(path, base=dict(os.environ))
        assert "SUITE_TX_LOCK" not in env                               # armed: no hard lock
        got = _run_child(env)
        assert got["armed"] and got["unlocked"] and got["eng"] and got["auth"]
        # the Tk master kill switch / power auto-disarm -> the child loses authorization
        G.arm(False)
        E.end()
        pub.publish_from_engines()
        env = gatestate.child_env(path, base=dict(os.environ))
        assert env["SUITE_TX_LOCK"] == "1"                              # exported while disarmed
        env.pop("SUITE_TX_LOCK")                                        # the file alone must do it
        got = _run_child(env)
        assert not got["armed"] and not got["eng"] and not got["auth"]
        assert got["arm_self"] is False                                 # a child cannot arm itself
    finally:
        pub.close()


def test_l1_stale_state_from_dead_hub_fails_closed(tmp_path):
    import json
    path = str(tmp_path / "gate.json")
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    with open(path, "w") as f:
        json.dump({"pid": dead.pid, "nonce": "x", "t": time.time(), "armed": True,
                   "unlocked": True, "engagement": {"name": "j", "authorization": "a",
                                                    "scope": ["10.0.0.0/24"], "operator": OP,
                                                    "started": time.time(),
                                                    "expires": time.time() + 3600}}, f)
    os.chmod(path, 0o600)
    env = dict(os.environ, PALISADE_GATE_STATE=path)
    env.pop("SUITE_TX_LOCK", None)
    got = _run_child(env)
    assert not got["armed"] and not got["unlocked"] and not got["eng"] and not got["auth"]
    # bound to a hub but the file is missing: also closed
    env["PALISADE_GATE_STATE"] = str(tmp_path / "missing.json")
    got = _run_child(env)
    assert not got["armed"] and not got["eng"]


def test_l1_tk_hub_kill_switch_and_power_disarm_publish():
    import hub
    src = open(hub.__file__).read()
    assert "gatestate" in src
    import gatestate
    assert callable(getattr(gatestate, "child_env", None))


# ============================================================================ S2 — Scout / dev terminal
def test_s2_scout_starts_no_scan_without_engagement_poc():
    import scout
    calls = []
    ok, why = scout.scan_network(lambda h: None, lambda t, f: None, None,
                                 spawner=_sleeper_spawner(calls),
                                 local_net=lambda: "192.168.4.0/22")
    assert not ok and calls == [] and "engagement" in why.lower()


def test_s2_scout_uses_real_netmask_and_netpent_gate():
    import scout
    assert scout.network_from_ip_addr(
        "2: wlan0    inet 192.168.5.23/22 brd 192.168.7.255 scope global wlan0") == "192.168.4.0/22"
    E.start("job", "ROE-1", ["192.168.4.0/22"], OP)
    calls = []
    ok, why = scout.scan_network(lambda h: None, lambda t, f: None, None,
                                 spawner=_exit_spawner(calls, 0, out=""),
                                 local_net=lambda: "192.168.4.0/22", wait=True)
    assert ok and calls and calls[0][0] == "nmap" and calls[0][-1] == "192.168.4.0/22"
    assert any(a["action"].startswith("net:") for a in E.actions())
    # an engagement on a /24 does not cover the real /22
    E.end()
    E.start("job2", "ROE-2", ["192.168.5.0/24"], OP)
    calls.clear()
    ok, why = scout.scan_network(lambda h: None, lambda t, f: None, None,
                                 spawner=_exit_spawner(calls, 0, out=""),
                                 local_net=lambda: "192.168.4.0/22")
    assert not ok and calls == []


def test_s2_devterm_ble_mqtt_ssh_are_gated():
    import devterm
    assert devterm.authorize_ble_connect("AA:BB:CC:DD:EE:FF")[0] is False
    assert devterm.authorize_mqtt_publish("10.0.0.7")[0] is False
    ok, why, t = devterm.prepare_ssh("10.0.0.7", "uname -a")
    assert not ok and t is None
    E.start("job", "ROE-1", ["AA:BB:CC:DD:EE:FF", "10.0.0.7"], OP)
    assert devterm.authorize_ble_connect("AA:BB:CC:DD:EE:FF")[0] is True
    assert devterm.authorize_mqtt_publish("10.0.0.7")[0] is True
    ok, why, t = devterm.prepare_ssh("10.0.0.7", "uname -a")
    assert ok and t.argv[0] == "ssh" and t.argv[-1] == "uname -a"
    assert devterm.prepare_ssh("10.0.0.8", "id")[0] is False


# ============================================================================ S3 — Tk USB-HID honesty
class _FakeHid:
    def __init__(self, fail=False):
        self.writes = []
        self.fail = fail

    def __call__(self, path, mode="rb"):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write(self, data):
        if self.fail:
            raise OSError("EPIPE")
        self.writes.append(bytes(data))
        return len(data)

    def flush(self):
        pass


def test_s3_usbhid_never_claims_sent_without_writes_poc():
    import usbhid
    E.start("job", "ROE-1", ["LAPTOP-7"], OP)
    dev = _FakeHid(fail=True)
    ok, text, n = usbhid.run_payload("STRING hi\nENTER", "LAPTOP-7", gadget=True, opener=dev)
    assert n == 0 and "sent" not in text.lower().replace("not sent", "")
    ok, text, n = usbhid.run_payload("STRING hi\nENTER", "LAPTOP-7", gadget=False, opener=dev)
    assert n == 0 and dev.writes == [] and "not sent" in text.lower()
    dev = _FakeHid()
    ok, text, n = usbhid.run_payload("STRING hi\nENTER", "LAPTOP-7", gadget=True, opener=dev)
    assert ok and n == len(dev.writes) > 0 and ("sent %d" % n) in text.lower()


def test_s3_usbhid_no_engagement_no_writes():
    import usbhid
    dev = _FakeHid()
    ok, text, n = usbhid.run_payload("STRING hi", "LAPTOP-7", gadget=True, opener=dev)
    assert not ok and n == 0 and dev.writes == []


# ============================================================================ one gate — static proof
GATED_MODULES = [
    "txguard.py", "engagement.py", "bench.py", "replay.py", "netpent.py", "wifipent.py",
    "blepent.py", "canbus.py", "proxmark.py", "zigbee.py", "zwave.py", "usbhid.py", "buslab.py",
    "flipper.py", "hwlab.py", "scout.py", "devterm.py", "passaudit.py", "digimodes.py",
    "loopback.py", "radio.py", "mesh_dash.py", "cw.py", "rtty.py", "opprofile.py", "gatestate.py",
    "rfemit.py",
    "palisade_qt/forge.py", "palisade_qt/recon.py", "palisade_qt/bench_app.py",
    "palisade_qt/panels.py", "palisade_qt/chrome.py",
]

# Reviewed exceptions: (file, enclosing function, call) -> justification. A new entry needs a line,
# and an entry that no longer matches a call fails the second test (no silent drift).
SPAWN_ALLOWLIST = {
    ("canbus.py", "worker", "S.spawn"):
        "candump: passive receive-only CAN monitor (no frames sent)",
    ("scout.py", "arp_hosts", "subprocess.run"): "`ip neigh`: reads the local ARP cache",
    ("scout.py", "local_network", "subprocess.run"): "`ip -o -4 addr`: reads own interface + mask",
    ("scout.py", "wifi_scan", "subprocess.run"): "nmcli Wi-Fi list: passive, no target contact",
    ("scout.py", "run_sweep", "subprocess.Popen"):
        "RF tab: rtl_power receive-only spectrum survey (RX, no TX, no target contact)",
    ("scout.py", "work", "subprocess.run"): "harden.sh --dry-run: prints the plan, changes nothing",
    ("radio.py", "_run", "subprocess.run"): "SDR enumeration (hackrf_info / SoapySDRUtil --find)",
    ("palisade_qt/recon.py", "_run_scan", "subprocess.run"):
        "passive survey commands (iw scan / bluetoothctl) — no target contact",
    ("devterm.py", "ssh_open", "subprocess.Popen"):
        "opens an interactive terminal; the host passed devterm.authorize_ssh_host first",
}
WRITE_ALLOWLIST = {
    ("txguard.py", "log_tx", "f.write"): "append to the local TX log file",
    ("bench.py", "append_log", "f.write"): "append to the local bench log file",
    ("hwlab.py", "write", "?.write"):
        "SerialReader.write: the port object the executor writes through (never called directly)",
    ("hwlab.py", "append", "?.write"): "local session capture file (st['logf'])",
    ("mesh_dash.py", "log_msg", "f.write"): "append to the local message log",
    ("gatestate.py", "_write", "fh.write"): "atomic write of the session gate-state file",
    ("palisade_qt/forge.py", "_serial_send", "w.write"):
        "SerialWorker.write only queues text; its drain sends every line via hwlab.gated_send",
}


def _calls(path):
    import ast
    src = open(os.path.join(SUITE_DIR, path)).read()
    tree = ast.parse(src)
    out = []

    class V(ast.NodeVisitor):
        def __init__(self):
            self.stack = ["<module>"]

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()
        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, node):
            self.stack.append("<lambda>")
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node):
            f = node.func
            name = None
            if isinstance(f, ast.Attribute):
                base = f.value
                if isinstance(base, ast.Name):
                    name = "%s.%s" % (base.id, f.attr)
                elif isinstance(base, ast.Call) and getattr(base.func, "id", "") == "__import__":
                    name = "__import__.%s" % f.attr
                else:
                    name = "?.%s" % f.attr
            elif isinstance(f, ast.Name):
                name = f.id
            if name:
                out.append((self.stack[-1], name, node.lineno))
            self.generic_visit(node)
    V().visit(tree)
    return out, src


SPAWN_NAMES = {"subprocess.Popen", "subprocess.run", "subprocess.call", "subprocess.check_call",
               "subprocess.check_output", "os.system", "os.popen", "os.execv", "os.execvp",
               "os.spawnv", "S.run", "S.spawn", "suite.run", "suite.spawn", "Popen"}


def test_one_gate_no_spawn_or_device_write_outside_the_executor():
    bad = []
    for path in GATED_MODULES:
        calls, src = _calls(path)
        if "__import__(\"subprocess\")" in src or "__import__('subprocess')" in src:
            bad.append("%s: __import__('subprocess') hides a spawn" % path)
        for func, name, line in calls:
            if name in SPAWN_NAMES and (path, func, name) not in SPAWN_ALLOWLIST:
                bad.append("%s:%d %s() calls %s" % (path, line, func, name))
            if name.endswith(".write") and not name.startswith("executor."):
                if (path, func, name) not in WRITE_ALLOWLIST:
                    bad.append("%s:%d %s() calls %s" % (path, line, func, name))
    assert not bad, "ungated spawn/write sites:\n" + "\n".join(bad)


def test_one_gate_allowlist_entries_have_justifications_and_exist():
    for table in (SPAWN_ALLOWLIST, WRITE_ALLOWLIST):
        for key, why in table.items():
            assert isinstance(why, str) and len(why) > 10, key
    live = set()
    for path in GATED_MODULES:
        calls, _ = _calls(path)
        for func, name, _l in calls:
            live.add((path, func, name))
    stale = [k for k in list(SPAWN_ALLOWLIST) + list(WRITE_ALLOWLIST) if k not in live]
    assert not stale, "allowlist entries that no longer match a call (remove them): %s" % stale


def test_g11_only_a_gate_may_issue_a_ticket():
    """A module that is not a gate cannot mint its own 'authorization' with a recheck that always
    passes (runtime check + static check below)."""
    import executor
    with pytest.raises(executor.TicketRefused):
        executor.issue(argv=["nmap", "8.8.8.8"], recheck=lambda: (True, "trust me"), label="x")
    issuers = set()
    for path in GATED_MODULES + ["hub.py", "palisade_qt/shell.py", "palisade_qt/system.py"]:
        calls, _ = _calls(path)
        if any(name == "executor.issue" for _f, name, _l in calls):
            issuers.add(os.path.splitext(os.path.basename(path))[0])
    assert issuers <= set(executor.ISSUERS), issuers


def test_owner_decision_constants_are_strict_and_wired(monkeypatch):
    """The three owner decisions are single named constants at the strict answer, and each is
    actually consulted (relaxing it would change behaviour) — flag, do not decide."""
    import opprofile
    assert G.CONDUCTED_PROTECTED_ALLOWED is False
    assert G.EXEMPT_SERVICES == ()
    assert opprofile.CALLSIGN_ENABLES_TX is False
    assert opprofile.tx_settings({"callsign": OP})["tx_enabled"] is False
    # wired: relaxing decision 2 lets LoRa skip arm/unlock — but never tx_enabled or the band
    monkeypatch.setattr(G, "EXEMPT_SERVICES", ("lora",))
    assert G.authorize("lora", 915_000_000, settings={"tx_enabled": True})[0] is True
    assert G.authorize("lora", 915_000_000, settings={"tx_enabled": False})[0] is False
    assert G.authorize("lora", 1_090_000_000, settings={"tx_enabled": True})[0] is False
    monkeypatch.setattr(opprofile, "CALLSIGN_ENABLES_TX", True)
    assert opprofile.tx_settings({"callsign": OP})["tx_enabled"] is True
