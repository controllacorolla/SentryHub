"""MESH — the Meshtastic link (owner 2026-11-18, decision: full layout MAP / NODES / CHAT / RADIO).

Connects the way the Tk mesh_dash does: meshtasticd on this machine (TCP 127.0.0.1:4403, the AIO
board's LoRa radio), else a USB-serial node. Reuses mesh_dash AS-IS for the TX gate
(authorize_send -> txguard: armed + unlocked + mesh tx_enabled + the region's licence-free band),
the region map, distances and the message log path.

  * MAP   — nodes at their reported positions on the satellite map, centred on this node (or HOME);
            a line to each node: solid = heard directly (coloured by SNR), dashed = relayed.
  * NODES — every node: name, SNR, hops, battery, last heard, distance / bearing; a node card.
  * CHAT  — the primary channel and direct messages; SEND goes through the TX gate and stays greyed
            with the gate's reason while it is closed (a send never fails silently).
  * RADIO — the link (how connected, or why not), this node, region / preset, channel use, gate.

Honest states: no meshtasticd and no USB node -> NO MESH LINK with the fix; linked with no node
heard -> LISTENING. Demo is a static, flagged mesh (no radio, no daemon thread).
Alerts to OPS: a new node heard, a direct message to this node, a node's battery under 20 %.
"""
import json
import math
import os
import queue
import socket
import sys
import time

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .app import PalisadeApp, stop_worker
from . import theme, eventbus
from .kit import FeedTable, DetailCard, MapPanel, micro
from .kit.components import note, Cover
from .worker import Worker
from .timebase import zulu

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from .kit.seams import offscreen as _offscreen  # noqa: E402

SUBVIEWS = ("MAP", "NODES", "CHAT", "RADIO")
LOW_BATT = 20                    # % — a node under this raises one alert to OPS
NODES_EVERY_S = 5.0
RETRY_S = 15.0
NO_LINK_FIX = ("start meshtasticd (sudo systemctl start meshtasticd) or plug in a Meshtastic node "
               "over USB")


def _settings():
    import mesh_dash
    try:
        import suite as S
        return S.settings("mesh", mesh_dash.DEFAULTS)[0]
    except Exception:
        return dict(mesh_dash.DEFAULTS)


def demo_mesh(now=None):
    """A flagged, static demo mesh: the shape mesh_dash.FakeIface uses, with positions and hops."""
    now = time.time() if now is None else now

    def mk(num, sid, short, long_, lat, lon, snr, hops, batt, heard, hw="HELTEC_V3"):
        return {"num": num, "user": {"id": sid, "shortName": short, "longName": long_,
                                     "hwModel": hw},
                "position": {"latitude": lat, "longitude": lon}, "snr": snr, "hopsAway": hops,
                "deviceMetrics": {"batteryLevel": batt, "voltage": 3.9,
                                  "channelUtilization": 7.5, "airUtilTx": 1.2},
                "lastHeard": now - heard}
    nodes = {
        "!00000001": mk(1, "!00000001", "ME", "uConsole (me)", 39.6205, -104.8701, None, 0, 82, 0,
                        "PORTDUINO"),
        "!a1b2c3d4": mk(2, "!a1b2c3d4", "KAPA", "Centennial Roof", 39.5702, -104.8490, 6.25, 0,
                        100, 40),
        "!b2c3d4e5": mk(3, "!b2c3d4e5", "GLDN", "Golden Ridge Rptr", 39.7555, -105.2211, -4.5, 2,
                        64, 300, "RAK4631"),
        "!c3d4e5f6": mk(4, "!c3d4e5f6", "BIKE", "Trail bike node", 39.65, -104.95, 2.0, 1, 18,
                        1500, "TBEAM"),
        "!d4e5f6a7": mk(5, "!d4e5f6a7", "HMB", "Home base", 39.7392, -104.9903, -11.0, 3, 101,
                        7200),
    }
    msgs = [{"fromId": "!a1b2c3d4", "toId": "^all", "channel": 0, "rxTime": now - 600,
             "decoded": {"text": "Anyone on the south mesh tonight?"}},
            {"fromId": "!b2c3d4e5", "toId": "^all", "channel": 0, "rxTime": now - 420,
             "decoded": {"text": "Copy, solid signal from Centennial"}},
            {"fromId": "!c3d4e5f6", "toId": "!00000001", "channel": 0, "rxTime": now - 60,
             "decoded": {"text": "Battery low on the bike node, heading back"}}]
    radio = {"link": "DEMO — simulated mesh, no radio", "my_id": "!00000001", "region": "US",
             "preset": "LONG_FAST", "channel": "LongFast"}
    return nodes, msgs, radio


def _jsonable(d):
    """A node dict safe to hand across threads (meshtastic's dicts can hold protobuf objects)."""
    try:
        return json.loads(json.dumps(d, default=str))
    except Exception:
        return {}


class MeshLinkWorker(Worker):
    """Owns the Meshtastic interface. Emits rows: {"kind": "nodes", nodes, radio} every few
    seconds, {"kind": "msg", msg} per received text, {"kind": "sent"|"refused", ...} per send.
    status: {"link": "connected"|"connecting"|"none"|"error"|"demo", "text": ...}."""

    PAUSE_WHEN_HIDDEN = False            # messages and new-node alerts arrive while hidden

    def __init__(self, demo=False, parent=None, iface_factory=None, settings=None):
        super().__init__(demo=demo, interval_ms=500, parent=parent)
        self._iface = None
        self._rxq = queue.Queue()
        self._txq = queue.Queue()
        self._factory = iface_factory          # tests: a fake interface
        self._settings = settings
        self._last_nodes = 0.0
        self._next_try = 0.0
        self._demo_sent = False
        self._subscribed = False

    # ---- GUI thread -> worker ----
    def send(self, text, dest="^all"):
        self._txq.put((text, dest))
        self.poke()

    # ---- pubsub callbacks (meshtastic's thread) ----
    def _on_receive(self, packet, interface=None):
        self._rxq.put(("rx", packet))

    def _on_lost(self, interface=None):
        self._rxq.put(("lost", None))

    def s(self):
        return self._settings if self._settings is not None else _settings()

    def _connect(self):
        """(iface, how) or (None, reason)."""
        if self._factory is not None:
            return self._factory(self._on_receive), "test interface"
        if _offscreen():
            return None, "no mesh link under the test platform"
        try:
            from pubsub import pub
            import meshtastic.tcp_interface
            import meshtastic.serial_interface
            import meshtastic.util
        except ImportError:
            return None, ("the meshtastic Python package is missing — re-run the installer "
                          "(pip install meshtastic)")
        if not self._subscribed:
            pub.subscribe(self._on_receive, "meshtastic.receive")
            pub.subscribe(self._on_lost, "meshtastic.connection.lost")
            self._subscribed = True
        s = self.s()
        mode = s.get("connect", "auto")
        if mode in ("auto", "tcp"):
            try:
                socket.create_connection((s["tcp_host"], int(s["tcp_port"])), timeout=2).close()
                return (meshtastic.tcp_interface.TCPInterface(
                    hostname=s["tcp_host"], portNumber=int(s["tcp_port"]), timeout=30),
                    "meshtasticd @ %s:%s" % (s["tcp_host"], s["tcp_port"]))
            except OSError:
                pass
        if mode in ("auto", "serial"):
            port = s.get("serial_port") or None
            if not port:
                ports = meshtastic.util.findPorts(True)
                port = ports[0] if ports else None
            if port:
                return meshtastic.serial_interface.SerialInterface(devPath=port, timeout=30), \
                    "USB " + port
        return None, "no meshtasticd on %s:%s and no USB node — %s" % (
            s.get("tcp_host"), s.get("tcp_port"), NO_LINK_FIX)

    def step(self):
        if self.demo:
            self._demo_step()
            return
        now = time.time()
        if self._iface is None:
            if now < self._next_try:
                return
            self.status.emit({"link": "connecting", "text": "connecting to the mesh…"})
            try:
                self._iface, how = self._connect()
            except Exception as e:
                self._iface, how = None, "connect failed: %s (another app may hold the radio)" \
                    % " ".join(str(e).split())[:120]
            if self._iface is None:
                self._next_try = now + RETRY_S
                self.status.emit({"link": "none", "text": how})
                return
            self.status.emit({"link": "connected", "text": how})
            self._last_nodes = 0.0
        self._drain_rx()
        self._drain_tx()
        if self._iface is not None and now - self._last_nodes >= NODES_EVERY_S:
            self._last_nodes = now
            self.row.emit({"kind": "nodes", "nodes": self._nodes(), "radio": self._radio()})

    def _drain_rx(self):
        while True:
            try:
                kind, p = self._rxq.get_nowait()
            except queue.Empty:
                return
            if kind == "lost":
                self._close_iface()
                self._next_try = time.time() + 2
                self.status.emit({"link": "none", "text": "mesh link lost — reconnecting"})
                return
            dec = (p or {}).get("decoded") or {}
            if dec.get("portnum") in ("TEXT_MESSAGE_APP", 1) or "text" in dec:
                msg = {"fromId": p.get("fromId"), "toId": p.get("toId"),
                       "channel": p.get("channel", 0), "rxTime": p.get("rxTime") or time.time(),
                       "rxSnr": p.get("rxSnr"), "decoded": {"text": dec.get("text", "")}}
                self._log(msg)
                self.row.emit({"kind": "msg", "msg": msg})

    def _drain_tx(self):
        import mesh_dash
        while True:
            try:
                text, dest = self._txq.get_nowait()
            except queue.Empty:
                return
            if self._iface is None:            # the link dropped just now (RA-MESH L5)
                self.row.emit({"kind": "refused", "text": text,
                               "why": "no mesh link (it dropped): not sent"})
                continue
            ok, why = mesh_dash.authorize_send(self.s(), self._iface)
            if not ok:
                self.row.emit({"kind": "refused", "text": text, "why": why})
                continue
            try:
                self._iface.sendText(text, destinationId=dest, channelIndex=0, wantAck=False)
            except Exception as e:
                self.row.emit({"kind": "refused", "text": text,
                               "why": "send failed: %s" % " ".join(str(e).split())[:120]})
                continue
            msg = {"fromId": self._my_id(), "toId": dest, "channel": 0, "rxTime": time.time(),
                   "decoded": {"text": text}, "mine": True}
            self._log(msg)
            self.row.emit({"kind": "sent", "msg": msg})

    def _log(self, msg):
        try:
            import mesh_dash
            with open(mesh_dash.MSG_LOG, "a") as f:
                f.write(json.dumps({"t": msg.get("rxTime"), "from": msg.get("fromId"),
                                    "to": msg.get("toId"), "ch": msg.get("channel"),
                                    "text": msg["decoded"].get("text", "")}) + "\n")
        except Exception:
            pass

    def _my_id(self):
        try:
            info = self._iface.getMyNodeInfo() or {}
            return (info.get("user") or {}).get("id")
        except Exception:
            return None

    def _nodes(self):
        try:
            return {k: _jsonable(v) for k, v in dict(self._iface.nodes or {}).items()}
        except Exception:
            return {}

    def _radio(self):
        import mesh_dash
        r = {"my_id": self._my_id(), "region": mesh_dash.node_region(self._iface)}
        try:
            lora = self._iface.localNode.localConfig.lora
            preset = getattr(lora, "modem_preset", None)
            name = getattr(preset, "name", None)
            if name is None and preset is not None:
                from meshtastic.protobuf import config_pb2
                name = config_pb2.Config.LoRaConfig.ModemPreset.Name(preset)
            r["preset"] = name
        except Exception:
            r["preset"] = None
        return r

    def _demo_step(self):
        if self._demo_sent:
            self._drain_demo_tx()
            return
        self._demo_sent = True
        nodes, msgs, radio = demo_mesh()
        self.status.emit({"link": "demo", "text": radio["link"]})
        self.row.emit({"kind": "nodes", "nodes": nodes, "radio": radio})
        for m in msgs:
            self.row.emit({"kind": "msg", "msg": m})

    def _drain_demo_tx(self):
        import mesh_dash
        while True:
            try:
                text, dest = self._txq.get_nowait()
            except queue.Empty:
                return
            ok, why = mesh_dash.authorize_send(self.s(), None)
            if not ok:
                self.row.emit({"kind": "refused", "text": text, "why": why})
                continue
            self.row.emit({"kind": "sent", "msg": {
                "fromId": "!00000001", "toId": dest, "channel": 0, "rxTime": time.time(),
                "decoded": {"text": text + " (demo — not transmitted)"}, "mine": True}})

    def _close_iface(self):
        it, self._iface = self._iface, None
        if it is not None:
            try:
                it.close()
            except Exception:
                pass

    def run(self):
        try:
            super().run()
        finally:
            self._close_iface()
            if self._subscribed:
                try:
                    from pubsub import pub
                    pub.unsubscribe(self._on_receive, "meshtastic.receive")
                    pub.unsubscribe(self._on_lost, "meshtastic.connection.lost")
                except Exception:
                    pass


# ---------------------------------------------------------------- pure helpers (tested)

MAX_TEXT_BYTES = 200


def node_rows(nodes, me_pos=None, now=None, warn="#E5A13A"):
    """Table rows for every node, newest first. Distance / bearing from this node's position."""
    import mesh_dash
    now = time.time() if now is None else now
    rows = []
    for nid, n in nodes.items():
        u = n.get("user") or {}
        dm = n.get("deviceMetrics") or {}
        pos = n.get("position") or {}
        lat, lon = pos.get("latitude"), pos.get("longitude")
        dist = brg = "—"
        if me_pos and lat is not None and lon is not None and (lat, lon) != tuple(me_pos):
            d = mesh_dash.dist_km(me_pos, (lat, lon))
            dist = "%.1f km" % d
            y = math.sin(math.radians(lon - me_pos[1])) * math.cos(math.radians(lat))
            x = (math.cos(math.radians(me_pos[0])) * math.sin(math.radians(lat)) -
                 math.sin(math.radians(me_pos[0])) * math.cos(math.radians(lat)) *
                 math.cos(math.radians(lon - me_pos[1])))
            brg = "%03d°" % (round(math.degrees(math.atan2(y, x))) % 360)
        batt = dm.get("batteryLevel")
        heard = n.get("lastHeard")
        rows.append({
            "id": u.get("id") or nid, "short": u.get("shortName", "?"),
            "long": u.get("longName", ""),
            "snr": "%.1f" % n["snr"] if isinstance(n.get("snr"), (int, float)) else "—",
            "hops": str(n["hopsAway"]) if isinstance(n.get("hopsAway"), int) else "—",
            "batt": ("PWR" if batt is not None and batt > 100 else "%d%%" % batt)
            if isinstance(batt, (int, float)) else "—",
            "heard": (mesh_dash.ago(heard) + " ago") if heard else "—",
            "dist": dist, "brg": brg, "_n": n, "_heard": heard or 0,
            "_colors": {"batt": warn} if isinstance(batt, (int, float)) and batt < LOW_BATT
            else {}})
    rows.sort(key=lambda r: -r["_heard"])
    return rows


def snr_color(tok, snr):
    if not isinstance(snr, (int, float)):
        return tok["muted"]
    return tok["live"] if snr >= 0 else tok["warn"] if snr >= -10 else tok["alert"]


class MeshPage(PalisadeApp):
    TITLE = "MESH"
    LEASE = None
    SUBTABS = SUBVIEWS

    def __init__(self, demo=False, mode="dark", parent=None, embedded=False):
        self._view = "MAP"
        self._nodes = {}
        self._radio = {}
        self._link = ("connecting", "")
        self._seen_nodes = None              # node ids known before (None until the first list)
        self._ever_seen = set()              # every node id heard this session (alerts once)
        self._low_alerted = set()
        self._msgs = []
        self._sel = None
        super().__init__(demo=demo, mode=mode, parent=parent, embedded=embedded)

    def current_subtab(self):
        return self._view

    def switch_subtab(self, name):
        if name in self._pages:
            self._view = name
            self.stack.setCurrentWidget(self._pages[name])
            self._sync_rail()

    def build_body(self):
        self._tok = theme.tokens(self.mode)
        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QtWidgets.QStackedWidget()
        self._pages = {"MAP": self._map_page(), "NODES": self._nodes_page(),
                       "CHAT": self._chat_page(), "RADIO": self._radio_page()}
        for v in SUBVIEWS:
            self.stack.addWidget(self._pages[v])
        lay.addWidget(self.stack, 1)
        self._gate_timer = QtCore.QTimer(self)
        self._gate_timer.timeout.connect(self._refresh_gate)
        self._gate_timer.start(2000)
        self._refresh_gate()
        QtCore.QTimer.singleShot(0, self._render)      # once the page frame (status) exists
        return body

    # ---- pages ----
    def _map_page(self):
        page = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        h = eventbus.home() or eventbus.DEMO_HOME
        self.map = MapPanel(span_nm=20, mode=self.mode, home_lat=h[0], home_lon=h[1])
        self.map.legend.hide()          # the track-type key is ATLAS's; MESH has its own (right)
        self._lines = []
        self._map_cover = Cover(self.map, "offline", "NO MESH LINK", NO_LINK_FIX)
        row.addWidget(self.map, 1)
        side = QtWidgets.QWidget()
        side.setMinimumWidth(360)
        side.setMaximumWidth(440)
        sv = QtWidgets.QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(8)
        self.map_key = note("solid line = heard directly (green good · amber fair · red weak "
                            "SNR) · dashed = relayed")
        self.map_key.setWordWrap(True)
        sv.addWidget(self.map_key)
        self.map_where = note("")          # which nodes are on the map, and why the rest are not
        self.map_where.setWordWrap(True)
        sv.addWidget(self.map_where)
        sv.addWidget(micro("NODES"))
        self.map_nodes = FeedTable([("short", "NODE"), ("snr", "SNR"), ("hops", "HOP"),
                                    ("batt", "BATT"), ("heard", "HEARD")], fit_viewport=True)
        self.map_nodes.selected.connect(self._select)
        sv.addWidget(self.map_nodes, 1)
        self.map_card = DetailCard("NODE")
        sv.addWidget(self.map_card)
        row.addWidget(side)
        self.make_collapsible(self.map, [side])
        return page

    def _nodes_page(self):
        page = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.node_table = FeedTable([("short", "NODE"), ("long", "NAME"), ("snr", "SNR"),
                                     ("hops", "HOPS"), ("batt", "BATT"), ("heard", "LAST HEARD"),
                                     ("dist", "DIST"), ("brg", "BRG")], fit_viewport=True)
        self.node_table.selected.connect(self._select)
        row.addWidget(self.node_table, 1)
        self.node_card = DetailCard("NODE")
        self.node_card.setMinimumWidth(320)
        self.node_card.setMaximumWidth(380)
        row.addWidget(self.node_card)
        return page

    def _chat_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(micro("TO"))
        self.chat_to = QtWidgets.QComboBox()
        self.chat_to.addItem("everyone · primary channel", "^all")
        top.addWidget(self.chat_to, 1)
        pl.addLayout(top)
        self.chat_log = QtWidgets.QPlainTextEdit()
        self.chat_log.setReadOnly(True)
        pl.addWidget(self.chat_log, 1)
        row = QtWidgets.QHBoxLayout()
        self.chat_input = QtWidgets.QLineEdit()
        self.chat_input.setPlaceholderText("message…")
        self.chat_input.setMaxLength(1000)         # checked in bytes at SEND (RA-MESH L4)
        self.chat_input.returnPressed.connect(self._send)
        row.addWidget(self.chat_input, 1)
        self.send_btn = QtWidgets.QPushButton("SEND")
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.send_btn)
        pl.addLayout(row)
        self.gate_note = note("")
        self.gate_note.setWordWrap(True)
        pl.addWidget(self.gate_note)
        return page

    def _radio_page(self):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        self.radio_card = DetailCard("MESH RADIO")
        pl.addWidget(self.radio_card)
        pl.addStretch(1)
        return page

    # ---- lifecycle ----
    def start(self):
        if self._started:
            return
        super().start()
        self._link_w = MeshLinkWorker(demo=self.demo)
        self._link_w.row.connect(self._on_row)
        self._link_w.status.connect(self._on_link)
        self._link_w.start()

    def stop(self):
        if self._stopped:
            return
        if hasattr(self, "_gate_timer"):
            self._gate_timer.stop()
        stop_worker(getattr(self, "_link_w", None), self.TITLE)
        self._link_w = None
        super().stop()

    def primary_action(self):
        if self._view == "CHAT":
            self._send()
            return True
        return False

    # ---- worker outputs ----
    def _on_link(self, st):
        self._link = (st.get("link"), st.get("text", ""))
        self._render()

    def _on_row(self, r):
        k = r["kind"]
        if k == "nodes":
            self._radio = r.get("radio") or {}
            self._nodes_in(r["nodes"])
        elif k in ("msg", "sent"):
            self._msgs.append(r["msg"])
            self._msgs = self._msgs[-500:]
            self._show_msg(r["msg"])
            me = self._radio.get("my_id")
            m = r["msg"]
            if k == "msg" and me and m.get("toId") == me and not self.demo:
                eventbus.bus.publish(eventbus.alert(
                    "MESH", "direct message from %s: %s" % (self._name(m.get("fromId")),
                                                           m["decoded"].get("text", "")[:80]),
                    severity="warn"))
        elif k == "refused":
            self.chat_log.appendPlainText("✕ NOT SENT — %s: %s" % (r["why"], r["text"]))
        self._render()

    def _nodes_in(self, nodes):
        me = self._radio.get("my_id")
        if self._seen_nodes is not None and not self.demo:
            for nid in nodes:
                # once per node per session: a node that drops off the list and comes back is
                # not "new" (RA-MESH L3)
                if nid not in self._seen_nodes and nid not in self._ever_seen and nid != me:
                    eventbus.bus.publish(eventbus.alert(
                        "MESH", "new mesh node heard: %s" % self._name(nid, nodes),
                        severity="info"))
        for nid, n in nodes.items():
            b = (n.get("deviceMetrics") or {}).get("batteryLevel")
            if isinstance(b, (int, float)) and b < LOW_BATT and nid != me \
                    and nid not in self._low_alerted:
                self._low_alerted.add(nid)
                if not self.demo:
                    eventbus.bus.publish(eventbus.alert(
                        "MESH", "mesh node %s battery %d%%" % (self._name(nid, nodes), b),
                        severity="warn"))
        self._seen_nodes = set(nodes)
        self._ever_seen |= set(nodes)
        self._nodes = nodes
        # DM targets
        cur = self.chat_to.currentData()
        self.chat_to.blockSignals(True)
        self.chat_to.clear()
        self.chat_to.addItem("everyone · primary channel", "^all")
        for nid in sorted(nodes, key=lambda i: self._name(i).lower()):
            if nid != me:
                self.chat_to.addItem("DM %s" % self._name(nid), nid)
        i = self.chat_to.findData(cur)
        if i < 0 and cur and cur != "^all":
            # the DM target dropped off the node list: keep it, marked, never fall back to
            # everyone (RA-MESH M1: a private message went to the whole mesh)
            self.chat_to.addItem("DM %s (not in the node list now)" % self._name(cur), cur)
            i = self.chat_to.count() - 1
        self.chat_to.setCurrentIndex(max(0, i))
        self.chat_to.blockSignals(False)

    def _name(self, nid, nodes=None):
        n = (nodes or self._nodes).get(nid) or {}
        u = n.get("user") or {}
        return u.get("longName") or u.get("shortName") or str(nid)

    def _show_msg(self, m):
        frm = "me" if m.get("mine") else self._name(m.get("fromId"))
        to = m.get("toId")
        where = "" if to in (None, "^all") else " → %s" % ("me" if to == self._radio.get("my_id")
                                                            else self._name(to))
        snr = m.get("rxSnr")
        tail = "  (SNR %.1f)" % snr if isinstance(snr, (int, float)) else ""
        self.chat_log.appendPlainText("%s  %s%s: %s%s" % (
            zulu(m.get("rxTime"), secs=False), frm, where, m["decoded"].get("text", ""), tail))

    # ---- send ----
    def gate(self):
        import mesh_dash
        try:
            return mesh_dash.authorize_send(_settings(), None)
        except Exception as e:
            return False, "TX gate unavailable: %s" % str(e)[:80]

    def _refresh_gate(self):
        ok, why = self.gate()
        linked = self._link[0] in ("connected", "demo")
        can = ok and linked
        self.send_btn.setEnabled(can)
        self.send_btn.setToolTip("" if can else (why if not ok else "no mesh link"))
        if not linked:
            self.gate_note.setText("SEND is off: no mesh link — %s" % NO_LINK_FIX)
        elif not ok:
            self.gate_note.setText("SEND is off — TX gate: %s" % why)
        else:
            self.gate_note.setText("TX gate open: a send keys the LoRa radio and is logged.")
        self.gate_note.setStyleSheet("color:%s;" % (self._tok["muted"] if can
                                                    else self._tok["warn"]))
        self._gate = (ok, why)

    def _send(self):
        text = self.chat_input.text().strip()
        if not text:
            return
        n = len(text.encode("utf-8"))
        if n > MAX_TEXT_BYTES:              # one Meshtastic text packet; kept in the box to edit
            self.chat_log.appendPlainText("✕ NOT SENT — too long: %d bytes, a mesh text is %d "
                                          "bytes at most (emoji count 4)" % (n, MAX_TEXT_BYTES))
            return
        self._refresh_gate()
        if not self.send_btn.isEnabled():
            self.chat_log.appendPlainText("✕ NOT SENT — %s: %s" % (
                self.send_btn.toolTip() or "gate closed", text))
            return
        w = getattr(self, "_link_w", None)
        if w is None:
            return
        self.chat_input.clear()
        w.send(text, self.chat_to.currentData() or "^all")    # the worker re-checks the gate

    # ---- render ----
    def _me_pos(self):
        me = self._nodes.get(self._radio.get("my_id")) or {}
        p = me.get("position") or {}
        if p.get("latitude") is not None and p.get("longitude") is not None:
            return (p["latitude"], p["longitude"])
        return eventbus.home()

    def _select(self, row):
        self._sel = row.get("id")
        self._render_card()

    def _render_card(self):
        n = None
        for nid, nd in self._nodes.items():
            if ((nd.get("user") or {}).get("id") or nid) == self._sel:
                n = nd
        for c in (self.map_card, self.node_card):
            if n is None:
                c.set_hero("—", "select a node")
                c.set_rows([])
                continue
            u = n.get("user") or {}
            dm = n.get("deviceMetrics") or {}
            pos = n.get("position") or {}
            c.set_hero(u.get("shortName", "?"), u.get("longName", ""))
            c.set_rows([
                ("ID", u.get("id", "—")), ("HARDWARE", str(u.get("hwModel", "—"))),
                ("SNR", "%.1f dB" % n["snr"] if isinstance(n.get("snr"), (int, float)) else "—"),
                ("HOPS", str(n.get("hopsAway", "—"))),
                ("BATTERY", "%s%%" % dm.get("batteryLevel") if dm.get("batteryLevel") is not None
                 else "—"),
                ("VOLTAGE", "%.2f V" % dm["voltage"] if isinstance(dm.get("voltage"), (int, float))
                 else "—"),
                ("CH UTIL", "%.1f%%" % dm["channelUtilization"]
                 if isinstance(dm.get("channelUtilization"), (int, float)) else "—"),
                ("POSITION", "%.4f, %.4f" % (pos["latitude"], pos["longitude"])
                 if pos.get("latitude") is not None else "not reported"),
                ("LAST HEARD", zulu(n["lastHeard"], secs=False) if n.get("lastHeard") else "—")])

    def _render(self):
        link, text = self._link
        linked = link in ("connected", "demo")
        rows = node_rows(self._nodes, self._me_pos(), warn=self._tok["warn"]) if linked else []
        for t in (self.map_nodes, self.node_table):
            t.model.set_rows(rows)
            if not linked:
                t.set_empty("offline", "NO MESH LINK" if link != "connecting" else "CONNECTING",
                            text or NO_LINK_FIX)
            elif not rows:
                t.set_empty("watching", "LISTENING", "linked (%s) — no node heard yet" % text)
        self._map_cover.show(not linked, title="NO MESH LINK" if link != "connecting"
                             else "CONNECTING", detail=text or NO_LINK_FIX)
        self._draw_map(rows if linked else [])
        self._render_card()
        self._render_radio()
        if hasattr(self, "send_btn"):
            self._refresh_gate()
        # "connecting" is not a fault: only a real failure becomes a warning (and a notice)
        st = "warn" if link in ("none", "error") else "neutral"
        self.set_chip("mesh", ("MESH %s · %d nodes" % ("DEMO" if link == "demo" else "LINKED",
                                                        len(rows))) if linked else
                      "link: " + (text or "none"), state=st)

    def _draw_map(self, rows):
        for ln in self._lines:
            self.map.plot.removeItem(ln)
        self._lines = []
        me = self._me_pos()
        if me:
            self.map.set_home(me[0], me[1], known=True)
        pts, labels, colors = [], [], []
        for r in rows:
            n = r["_n"]
            pos = n.get("position") or {}
            if pos.get("latitude") is None or not me:
                continue
            x, y = eventbus.to_xy(pos["latitude"], pos["longitude"], home=me)
            pts.append((x, y))
            labels.append("%s %s" % (r["short"], r["batt"]))
            colors.append(snr_color(self._tok, n.get("snr")))
            if (x, y) == (0.0, 0.0):
                continue
            direct = n.get("hopsAway") == 0
            pen = pg.mkPen(snr_color(self._tok, n.get("snr")) if direct else self._tok["muted"],
                           width=2 if direct else 1,
                           style=QtCore.Qt.SolidLine if direct else QtCore.Qt.DashLine)
            ln = pg.PlotDataItem([0, x], [0, y], pen=pen)
            self.map.plot.addItem(ln)
            self._lines.append(ln)
        self.map.set_contacts(pts, labels=labels, colors=colors)
        self.map_points = pts
        self._explain_map(rows, me, len(pts))

    def _explain_map(self, rows, me, placed):
        """Say what is on the map and what is not (RA-MESH M2): no reference position at all, or
        the nodes that report none."""
        my_id = self._radio.get("my_id")
        others = [r for r in rows if r["id"] != my_id]
        with_pos = [r for r in others if (r["_n"].get("position") or {}).get("latitude") is not None]
        without = [r["short"] for r in others if r not in with_pos]
        linked = self._link[0] in ("connected", "demo")
        if linked and not me and with_pos:
            text = ("NOT ON THE MAP: this node and HOME have no position, so %d node(s) that report "
                    "one cannot be placed. Set HOME in SYSTEM › SETTINGS." % len(with_pos))
            self._map_cover.show(True, title="NO REFERENCE POSITION",
                                 detail="this radio reports no position and HOME is not set — "
                                        "set HOME in SYSTEM › SETTINGS")
            warn = True
        elif linked and others:
            text = "%d node(s) on the map" % placed
            if without:
                shown = ", ".join(without[:6]) + (" +%d more" % (len(without) - 6)
                                                  if len(without) > 6 else "")
                text += " · no position reported: %s" % shown
            warn = bool(without)
        else:
            text, warn = "", False
        self.map_where.setText(text)
        self.map_where.setStyleSheet("color:%s;" % (self._tok["warn"] if warn
                                                    else self._tok["muted"]))

    def _render_radio(self):
        link, text = self._link
        ok, why = getattr(self, "_gate", (False, ""))
        me = self._nodes.get(self._radio.get("my_id")) or {}
        u = me.get("user") or {}
        dm = me.get("deviceMetrics") or {}
        self.radio_card.set_hero({"connected": "LINKED", "demo": "DEMO", "connecting":
                                  "CONNECTING"}.get(link, "NO LINK"), text or "")
        self.radio_card.set_rows([
            ("LINK", text or "—"),
            ("THIS NODE", "%s (%s)" % (u.get("longName", "—"), u.get("id", "—")) if u else "—"),
            ("REGION", self._radio.get("region") or "—"),
            ("PRESET", self._radio.get("preset") or "—"),
            ("BATTERY", "%s%%" % dm.get("batteryLevel") if dm.get("batteryLevel") is not None
             else "—"),
            ("CH UTIL", "%.1f%%" % dm["channelUtilization"]
             if isinstance(dm.get("channelUtilization"), (int, float)) else "—"),
            ("AIR TX", "%.1f%%" % dm["airUtilTx"] if isinstance(dm.get("airUtilTx"), (int, float))
             else "—"),
            ("NODES", str(max(0, len(self._nodes) - (1 if u else 0)))),
            ("TX GATE", "OPEN" if ok else "CLOSED — %s" % why),
            ("FIX", NO_LINK_FIX if link in ("none", "error") else "—")])


# the shell imports this name
MeshApp = MeshPage
