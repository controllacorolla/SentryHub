"""MESH (full layout, owner 2026-11-18) and ASSISTANT on a local model (owner 2026-11-18: "just use
a local model"). Headless (Qt offscreen), real hub at 1280x720. The local model is a real HTTP
server on 127.0.0.1 speaking Ollama's /api/tags + streaming /api/chat; the mesh is a fake
interface with the meshtastic shape. No network, no radio.
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE_DIR = os.path.dirname(HERE)
for p in (SUITE_DIR, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)


from test_cl1_screen import _pump, _hub, _isolate  # noqa: E402

_isolate = _isolate


def _wait(pred, ms=5000):
    t = 0
    while t < ms:
        _pump(50)
        if pred():
            return True
        t += 50
    return pred()


# ================================================================ a local "Ollama"
class _Ollama:
    def __init__(self, models=("llama3.2:3b",), reply=("The map ", "shows ", "3 aircraft.")):
        self.models, self.reply, self.chats = list(models), list(reply), []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"models": [{"name": m} for m in outer.models]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                outer.chats.append(json.loads(self.rfile.read(n)))
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for tok in outer.reply:
                    self.wfile.write((json.dumps({"message": {"content": tok},
                                                  "done": False}) + "\n").encode())
                    self.wfile.flush()
                self.wfile.write((json.dumps({"done": True}) + "\n").encode())

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def offline():
    import netpolicy
    netpolicy.reset_for_tests()
    netpolicy.set_mode("OFFLINE", persist=False)
    yield netpolicy
    netpolicy.reset_for_tests()


def test_assistant_only_ever_talks_to_this_device():
    from palisade_qt.system import local_hosts
    s = {"hosts": [{"name": "desk", "url": "http://100.64.0.9:11434"},
                   {"name": "me", "url": "http://127.0.0.1:11434"},
                   {"name": "lan", "url": "http://192.168.1.20:11434"}]}
    assert [h["name"] for h in local_hosts(s)] == ["me"]


def test_assistant_streams_a_local_answer_with_live_context_while_net_is_offline(offline):
    """The real worker against a real loopback server: NET OFFLINE allows loopback, the answer
    streams in, the live picture goes in the system prompt, nothing else is contacted."""
    from palisade_qt.system import AskWorker
    srv = _Ollama()
    try:
        s = {"hosts": [{"name": "me", "url": srv.url, "model": "llama3.2:3b"}],
             "local_threads": 2, "system": "x"}
        w = AskWorker(settings=s, power=lambda: {"pct": 30, "charging": False})
        rows = []
        w.row.connect(rows.append)
        w.ask("what is on the map?", "Contacts on the map: 3 aircraft.")
        w.step()
        _pump(50)
        kinds = [r["kind"] for r in rows]
        assert kinds[0] == "model" and "llama3.2:3b" in rows[0]["text"]
        assert "meta" in kinds and "Battery 30%" in next(r for r in rows if r["kind"] == "meta")["text"]
        assert "".join(r["text"] for r in rows if r["kind"] == "tok") == "The map shows 3 aircraft."
        assert kinds[-1] == "done"
        body = srv.chats[-1]
        assert body["model"] == "llama3.2:3b" and body["options"]["num_thread"] == 2
        assert "3 aircraft" in body["messages"][0]["content"]
        assert body["messages"][-1] == {"role": "user", "content": "what is on the map?"}
        hosts = {e[3] for e in offline.log()}
        assert hosts <= {"127.0.0.1"}, hosts
        # a follow-up carries the conversation
        w.ask("and alerts?", "")
        w.step()
        assert [m["role"] for m in srv.chats[-1]["messages"][1:]] == ["user", "assistant", "user"]
    finally:
        srv.close()


def test_assistant_says_why_when_there_is_no_model():
    from palisade_qt.system import AskWorker
    w = AskWorker(settings={"hosts": [{"name": "me", "url": "http://127.0.0.1:9"}]})
    found, why = w.find_model(w._settings)
    assert found is None and "Ollama is not running" in why and "ollama pull" in why
    srv = _Ollama(models=())
    try:
        found, why = w.find_model({"hosts": [{"name": "me", "url": srv.url,
                                              "model": "llama3.2:3b"}]})
        assert found is None and "ollama pull llama3.2:3b" in why
    finally:
        srv.close()
    found, why = w.find_model({"hosts": [{"name": "desk", "url": "http://100.64.0.9:11434"}]})
    assert found is None and "no Ollama server on this device" in why


def test_assistant_page_end_to_end(offline, monkeypatch):
    """Type a question on the page: the local model's answer streams into the log, the model line
    names it, ASK comes back. With no model the built-in answer still comes back."""
    from palisade_qt import system
    srv = _Ollama(reply=("Two ", "alerts."))
    url = srv.url
    monkeypatch.setattr(system.AskWorker, "_s", lambda self: {
        "hosts": [{"name": "me", "url": url, "model": "llama3.2:3b"}], "system": "x"})
    hub = _hub(demo=False)
    try:
        hub.open_callsign("ASSISTANT")
        _pump(200)
        a = hub.page_app("ASSISTANT")
        a.asst_input.setText("anything new?")
        a._ask()
        assert not a.asst_ask.isEnabled() and a.asst_stop.isEnabled()
        assert _wait(lambda: a.asst_ask.isEnabled(), 8000)
        assert "Two alerts." in a.asst_log.toPlainText()
        assert "LOCAL MODEL" in a.asst_model.text() and "llama3.2:3b" in a.asst_model.text()
        srv.close()
        srv = None
        a.asst_input.setText("any alerts?")
        a._ask()
        assert _wait(lambda: a.asst_ask.isEnabled(), 8000)
        assert "NO LOCAL MODEL" in a.asst_model.text()
        assert "alert" in a.asst_log.toPlainText().splitlines()[-1].lower()
    finally:
        if srv is not None:
            srv.close()
        hub.close()
        _pump(150)


def test_assistant_a_worker_failure_never_leaves_ask_stuck():
    from palisade_qt.system import AskWorker
    w = AskWorker(settings={"hosts": None})
    rows = []
    w.row.connect(rows.append)
    w.ask("x", "")
    w.step()
    assert rows and rows[-1]["kind"] == "error"


def test_live_summary_has_counts_and_alerts_but_no_engagement_detail():
    from palisade_qt.system import live_summary
    contacts = [{"payload": {"kind": "aircraft"}}, {"payload": {"kind": "aircraft"}},
                {"payload": {"kind": "vessel"}}]
    txt = live_summary([{"text": "drone inbound"}], contacts,
                       [{"source": "PROWL"}], True, "OFFLINE")
    assert "2 aircraft" in txt and "1 vessel" in txt and "drone inbound" in txt
    assert "1 from PROWL" in txt and "OFFLINE" in txt
    assert "scope" not in txt.lower() and "target" not in txt.lower()


# ================================================================ MESH
class FakeIface:
    def __init__(self, on_rx):
        from palisade_qt.mesh import demo_mesh
        self.on_rx = on_rx
        self.nodes, _m, _r = demo_mesh()
        self.sent = []
        self.closed = False
        self.localNode = None

    def getMyNodeInfo(self):
        return self.nodes["!00000001"]

    def sendText(self, text, destinationId="^all", channelIndex=0, wantAck=False):
        self.sent.append((text, destinationId))

    def close(self):
        self.closed = True


def test_mesh_link_worker_receives_lists_and_sends_only_through_the_gate(monkeypatch):
    import mesh_dash
    from palisade_qt.mesh import MeshLinkWorker
    made = []
    w = MeshLinkWorker(iface_factory=lambda rx: made.append(FakeIface(rx)) or made[-1],
                       settings={"lora_region": "US", "tx_enabled": False})
    rows, st = [], []
    w.row.connect(rows.append)
    w.status.connect(st.append)
    w.step()
    assert st[-1]["link"] == "connected"
    nodes = [r for r in rows if r["kind"] == "nodes"]
    assert nodes and len(nodes[-1]["nodes"]) == 5 and nodes[-1]["radio"]["my_id"] == "!00000001"
    made[0].on_rx({"fromId": "!a1b2c3d4", "toId": "^all", "channel": 0,
                   "decoded": {"portnum": "TEXT_MESSAGE_APP", "text": "hello"}})
    w.step()
    assert any(r["kind"] == "msg" and r["msg"]["decoded"]["text"] == "hello" for r in rows)
    # gate closed: refused with its reason, nothing keyed
    monkeypatch.setattr(mesh_dash, "authorize_send", lambda s, i=None: (False, "TX kill switch"))
    w.send("test 1")
    w.step()
    assert rows[-1]["kind"] == "refused" and "TX kill switch" in rows[-1]["why"]
    assert made[0].sent == []
    # gate open: it goes out, and is logged
    monkeypatch.setattr(mesh_dash, "authorize_send", lambda s, i=None: (True, ""))
    w.send("test 2", "!a1b2c3d4")
    w.step()
    assert made[0].sent == [("test 2", "!a1b2c3d4")] and rows[-1]["kind"] == "sent"
    # link lost -> says so, closes, reconnects
    w._on_lost()
    w.step()
    assert st[-1]["link"] == "none" and made[0].closed


def test_mesh_send_is_refused_by_the_real_gate_by_default():
    """No monkeypatch: the real txguard chain refuses (mesh tx_enabled defaults OFF)."""
    import mesh_dash
    ok, why = mesh_dash.authorize_send(dict(mesh_dash.DEFAULTS), None)
    assert not ok and why


def test_mesh_page_has_four_views_and_says_why_with_no_link():
    hub = _hub(demo=False)
    try:
        hub.open_callsign("MESH")
        _pump(300)
        m = hub.page_app("MESH")
        assert m.subtabs() == ["MAP", "NODES", "CHAT", "RADIO"]
        for v in m.subtabs():
            hub.open_callsign("MESH", v)
            _pump(80)
            assert m.current_subtab() == v
            assert hub.size().toTuple() == (1280, 720)
        assert _wait(lambda: m._link[0] == "none", 3000)
        assert m.map_nodes.showing_empty() and "NO MESH LINK" in m.map_nodes.empty.big.text()
        assert not m.send_btn.isEnabled() and "no mesh link" in m.gate_note.text().lower()
        assert "NO LINK" in m.radio_card.hero.text()
    finally:
        hub.close()
        _pump(150)


def test_mesh_page_demo_map_nodes_chat_and_alerts():
    from palisade_qt import eventbus
    hub = _hub(demo=True)
    try:
        hub.open_callsign("MESH")
        m = hub.page_app("MESH")
        assert _wait(lambda: len(m.map_nodes.model.rows) == 5, 3000)
        rows = m.node_table.model.rows
        bike = next(r for r in rows if r["short"] == "BIKE")
        assert bike["batt"] == "18%" and bike["_colors"].get("batt")
        assert bike["dist"].endswith("km") and bike["brg"].endswith("°")
        assert len(m.map_points) == 5
        assert len(m._lines) == 4                     # every node but this one
        styles = {str(ln.opts["pen"].style()) for ln in m._lines}
        assert len(styles) == 2, "direct and relayed links look different"
        text = m.chat_log.toPlainText()
        assert "Centennial Roof: Anyone on the south mesh" in text and "→ me" in text
        assert m.chat_to.count() == 5                  # everyone + 4 DMs
        m._select({"id": "!c3d4e5f6"})
        assert m.node_card.hero.text() == "BIKE"
        # SEND greyed with the gate's reason (TX not armed)
        hub.open_callsign("MESH", "CHAT")
        assert not m.send_btn.isEnabled() and "TX gate" in m.gate_note.text()
        m.chat_input.setText("hello")
        m._send()
        assert "NOT SENT" in m.chat_log.toPlainText()
        # demo raises no alerts to OPS
        assert not [a for a in eventbus.bus.recent(600, "alert") if a["source"] == "MESH"]
    finally:
        hub.close()
        _pump(150)


def test_mesh_alerts_new_node_dm_and_low_battery():
    from palisade_qt import eventbus
    from palisade_qt.mesh import MeshPage, demo_mesh
    p = MeshPage(demo=False)
    try:
        nodes, _m, radio = demo_mesh()
        p._on_link({"link": "connected", "text": "test"})
        first = {k: v for k, v in nodes.items() if k != "!d4e5f6a7"}
        got = []
        eventbus.bus.published.connect(lambda ev: got.append(ev))
        p._on_row({"kind": "nodes", "nodes": first, "radio": radio})
        p._on_row({"kind": "nodes", "nodes": nodes, "radio": radio})
        p._on_row({"kind": "nodes", "nodes": nodes, "radio": radio})
        p._on_row({"kind": "msg", "msg": {"fromId": "!a1b2c3d4", "toId": "!00000001",
                                          "rxTime": time.time(), "decoded": {"text": "ping"}}})
        _pump(50)
        texts = [e["payload"]["text"] for e in got if e["type"] == "alert" and e["source"] == "MESH"]
        assert sum("new mesh node heard: Home base" in t for t in texts) == 1
        assert sum("Trail bike node battery 18%" in t for t in texts) == 1, texts
        assert any("direct message from Centennial Roof: ping" in t for t in texts)
    finally:
        p.stop()
        p.deleteLater()
        _pump(50)


# ================================================================ RA-MESH follow-ups
def _live_page():
    from palisade_qt.mesh import MeshPage, demo_mesh
    p = MeshPage(demo=False)
    nodes, _m, radio = demo_mesh()
    p._on_link({"link": "connected", "text": "test"})
    return p, nodes, radio


def test_ra_mesh_m1_a_dm_never_falls_back_to_everyone():
    import copy
    p, nodes, radio = _live_page()
    try:
        p._on_row({"kind": "nodes", "nodes": nodes, "radio": radio})
        i = p.chat_to.findData("!c3d4e5f6")
        p.chat_to.setCurrentIndex(i)
        gone = copy.deepcopy(nodes)
        del gone["!c3d4e5f6"]
        p._on_row({"kind": "nodes", "nodes": gone, "radio": radio})
        assert p.chat_to.currentData() == "!c3d4e5f6"
        assert "not in the node list" in p.chat_to.currentText()
        p._on_row({"kind": "nodes", "nodes": {}, "radio": radio})     # list read failed / empty
        assert p.chat_to.currentData() == "!c3d4e5f6"
    finally:
        p.stop()
        p.deleteLater()
        _pump(50)


def test_ra_mesh_m2_the_map_says_which_nodes_it_cannot_place(monkeypatch):
    import copy
    from palisade_qt import eventbus
    p, nodes, radio = _live_page()
    try:
        some = copy.deepcopy(nodes)
        some["!c3d4e5f6"].pop("position", None)
        p._on_row({"kind": "nodes", "nodes": some, "radio": radio})
        assert "no position reported: BIKE" in p.map_where.text()
        # no reference at all: this node has no position and HOME is unset
        none = copy.deepcopy(nodes)
        none[radio["my_id"]].pop("position", None)
        monkeypatch.setattr(eventbus, "home", lambda: None)
        p._on_row({"kind": "nodes", "nodes": none, "radio": radio})
        assert "NOT ON THE MAP" in p.map_where.text() and p._map_cover.shown()
    finally:
        p.stop()
        p.deleteLater()
        _pump(50)


def test_ra_mesh_l3_l4_l5_new_node_once_bytes_not_chars_dropped_link_reason():
    import copy
    from palisade_qt import eventbus
    from palisade_qt.mesh import MeshLinkWorker
    p, nodes, radio = _live_page()
    try:
        got = []
        eventbus.bus.published.connect(lambda ev: got.append(ev))
        first = {k: v for k, v in nodes.items() if k != "!d4e5f6a7"}
        p._on_row({"kind": "nodes", "nodes": first, "radio": radio})
        p._on_row({"kind": "nodes", "nodes": nodes, "radio": radio})
        p._on_row({"kind": "nodes", "nodes": first, "radio": radio})      # it drops off …
        p._on_row({"kind": "nodes", "nodes": copy.deepcopy(nodes), "radio": radio})   # … and back
        _pump(50)
        texts = [e["payload"]["text"] for e in got if e["type"] == "alert"
                 and e["source"] == "MESH" and "new mesh node" in e["payload"]["text"]]
        assert len(texts) == 1, texts
        # 100 emoji = 400 bytes: refused, kept in the box
        sent = []
        p._link_w = type("W", (), {"send": lambda self, t, d: sent.append((t, d))})()
        p.chat_input.setText("📡" * 100)
        p._send()
        assert not sent and "too long: 400 bytes" in p.chat_log.toPlainText()
        assert p.chat_input.text() == "📡" * 100
        p._link_w = None
        # a send as the link drops: a readable reason
        w = MeshLinkWorker(demo=False, settings={})
        rows = []
        w.row.connect(rows.append)
        w._iface = None
        w.send("hi", "^all")
        w._drain_tx()
        assert rows and "no mesh link" in rows[-1]["why"] and "NoneType" not in rows[-1]["why"]
    finally:
        p.stop()
        p.deleteLater()
        _pump(50)


def test_ra_mesh_l2_stop_works_before_the_first_token(offline):
    """STOP (and page close) break a read that is still waiting for the model's first token."""
    from palisade_qt.system import AskWorker
    import http.server

    class Slow(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.end_headers()
            time.sleep(8)                              # no token for a long time

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        w = AskWorker(settings={"hosts": [{"name": "me", "url": url, "model": "m"}],
                                "system": "x"}, power=lambda: {"pct": 80, "charging": True})
        w.find_model = lambda s: ((url, "m"), "")
        rows = []
        w.row.connect(rows.append)
        threading.Timer(1.0, w.cancel).start()
        t0 = time.time()
        w.ask("q", "")
        w.step()
        _pump(50)
        assert time.time() - t0 < 5, "STOP waited for the model"
        assert rows and rows[-1]["kind"] == "done" and "[stopped]" in rows[-1]["text"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_ra_mesh_l9_l10_live_context_off_and_listen_address():
    from palisade_qt.system import local_hosts
    hs = local_hosts({"hosts": [{"name": "any", "url": "http://0.0.0.0:11434"}]})
    assert hs and hs[0]["url"] == "http://127.0.0.1:11434"
    from palisade_qt.system import AssistantApp
    pg = AssistantApp(demo=True)
    try:
        class W:
            def _s(self):
                return {"live_context": False}
        pg._askw = W()
        assert pg._live_context() == ""
    finally:
        pg._askw = None
        pg.stop()
        pg.deleteLater()
        _pump(50)


# ================================================================ RA-MESHb follow-ups
def test_ra_meshb_n2_stop_and_close_work_while_the_model_is_still_loading(offline):
    """Real Ollama sends no headers until the model has loaded: STOP and close must not wait."""
    from palisade_qt.system import AskWorker
    import socket
    lst = socket.socket()
    lst.bind(("127.0.0.1", 0))
    lst.listen(1)
    url = "http://127.0.0.1:%d" % lst.getsockname()[1]
    held = []
    threading.Thread(target=lambda: held.append(lst.accept()), daemon=True).start()  # silent
    try:
        w = AskWorker(settings={"hosts": [{"name": "me", "url": url, "model": "m"}],
                                "system": "x"}, power=lambda: {"pct": 80, "charging": True})
        w.find_model = lambda s: ((url, "m"), "")
        rows = []
        w.row.connect(rows.append)
        threading.Timer(1.0, w.cancel).start()
        t0 = time.time()
        w.ask("q", "")
        w.step()
        _pump(50)
        assert time.time() - t0 < 3, "STOP waited for the model to load"
        assert rows[-1]["kind"] == "done" and rows[-1]["text"].endswith("[stopped]")
        assert w._history == [], "a stopped turn is not kept"
        # close: the worker thread ends within its 3 s join
        w2 = AskWorker(settings={"hosts": [{"name": "me", "url": url, "model": "m"}],
                                 "system": "x"}, power=lambda: {"pct": 80, "charging": True})
        w2.find_model = lambda s: ((url, "m"), "")
        threading.Thread(target=lambda: held.append(lst.accept()), daemon=True).start()
        w2.start()
        w2.ask("q", "")
        _pump(800)
        t0 = time.time()
        w2.stop()
        w2.quit()
        assert w2.wait(3000) and time.time() - t0 < 3
    finally:
        lst.close()


def test_ra_meshb_n1_n3_kept_dm_keeps_its_name_and_no_reference_is_said():
    import copy
    from palisade_qt import eventbus
    p, nodes, radio = _live_page()
    try:
        p._on_row({"kind": "nodes", "nodes": nodes, "radio": radio})
        p.chat_to.setCurrentIndex(p.chat_to.findData("!c3d4e5f6"))
        gone = copy.deepcopy(nodes)
        del gone["!c3d4e5f6"]
        p._on_row({"kind": "nodes", "nodes": gone, "radio": radio})
        assert p.chat_to.currentText() == "DM Trail bike node (not in the node list now)"
        nopos = copy.deepcopy(nodes)
        for n in nopos.values():
            n.pop("position", None)
        old = eventbus.home
        eventbus.home = lambda: None
        try:
            p._on_row({"kind": "nodes", "nodes": nopos, "radio": radio})
        finally:
            eventbus.home = old
        assert "this node and HOME have no position" in p.map_where.text()
    finally:
        p.stop()
        p.deleteLater()
        _pump(50)
