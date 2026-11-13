#!/usr/bin/env python3
"""canbus.py — CAN / automotive bus assessment (hardware-hacking, pen-test).

Listens to a vehicle CAN bus via SocketCAN (can-utils: candump) and decodes the two protocols you
actually read off a car: OBD-II mode 01 live PIDs (SAE J1979) and UDS diagnostics (ISO 14229). Pure
parsing + decode + the bus model are unit-testable and never touch hardware.

SAFETY LINE: sniffing/decoding a capture is passive and ungated. **Any transmit onto the bus** —
every frame you send, including an OBD-II read *request* or a UDS service — leaves the tool and
affects a live vehicle, so it goes through the engagement gate (scoped, authorized, evidence-logged),
exactly like TX goes through txguard. Nothing is sent unless an authorized, in-scope engagement is
open. We build the cansend argv only after the gate says yes.
"""
import os
import shutil
import sys

import engagement

# ---- OBD-II mode 01 live PIDs (SAE J1979). (name, n_bytes, decoder(data_bytes)->(value, unit)) ----
def _obd_rpm(d):      return ((d[0] << 8) + d[1]) / 4.0, "rpm"
def _obd_speed(d):    return float(d[0]), "km/h"
def _obd_coolant(d):  return d[0] - 40.0, "C"
def _obd_intake(d):   return d[0] - 40.0, "C"
def _obd_load(d):     return d[0] * 100.0 / 255.0, "%"
def _obd_throttle(d): return d[0] * 100.0 / 255.0, "%"
def _obd_fuel(d):     return d[0] * 100.0 / 255.0, "%"
def _obd_maf(d):      return ((d[0] << 8) + d[1]) / 100.0, "g/s"

OBD_PIDS = {
    0x04: ("engine_load", 1, _obd_load),
    0x05: ("coolant_temp", 1, _obd_coolant),
    0x0C: ("rpm", 2, _obd_rpm),
    0x0D: ("speed", 1, _obd_speed),
    0x0F: ("intake_temp", 1, _obd_intake),
    0x10: ("maf", 2, _obd_maf),
    0x11: ("throttle", 1, _obd_throttle),
    0x2F: ("fuel_level", 1, _obd_fuel),
}
OBD_REQUEST_ID = 0x7DF      # functional broadcast request
OBD_RESPONSE_LO = 0x7E8     # ECU responses 0x7E8..0x7EF

# ---- UDS services (ISO 14229-1). Positive response SID = request SID | 0x40. ----
UDS_SERVICES = {
    0x10: "DiagnosticSessionControl", 0x11: "ECUReset", 0x14: "ClearDiagnosticInformation",
    0x19: "ReadDTCInformation", 0x22: "ReadDataByIdentifier", 0x23: "ReadMemoryByAddress",
    0x27: "SecurityAccess", 0x28: "CommunicationControl", 0x2E: "WriteDataByIdentifier",
    0x2F: "InputOutputControlByIdentifier", 0x31: "RoutineControl", 0x34: "RequestDownload",
    0x35: "RequestUpload", 0x36: "TransferData", 0x37: "RequestTransferExit", 0x3E: "TesterPresent",
}
UDS_NRC = {
    0x10: "generalReject", 0x11: "serviceNotSupported", 0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat", 0x22: "conditionsNotCorrect",
    0x31: "requestOutOfRange", 0x33: "securityAccessDenied", 0x35: "invalidKey",
    0x36: "exceedNumberOfAttempts", 0x37: "requiredTimeDelayNotExpired",
    0x78: "responsePending",
}
# UDS services that change state on the ECU (vs. a plain read). Shown so the operator sees the risk.
UDS_WRITE_SERVICES = {0x10, 0x11, 0x27, 0x28, 0x2E, 0x2F, 0x31, 0x34, 0x35, 0x36, 0x37, 0x14}


def parse_candump(line):
    """One candump text line -> frame dict, or None. Accepts the default format
    '  can0  123   [8]  DE AD BE EF' and the timestamped '(1700000000.0)  can0  123  [8] ...'.
    Standard IDs are <=3 hex digits (11-bit); longer / >0x7FF are flagged extended (29-bit)."""
    s = line.strip()
    if not s:
        return None
    toks = s.split()
    i = 0
    if toks and toks[0].startswith("(") and toks[0].endswith(")"):
        i = 1                                    # drop the (timestamp)
    if len(toks) < i + 2:
        return None
    iface = toks[i]
    idfield = toks[i + 1]
    if "#" in idfield:                           # candump '-' / log format: 123#DEADBEEF
        idhex, datahex = idfield.split("#", 1)
        rtr = datahex.upper().startswith("R")
        data = b"" if rtr else _hex_to_bytes(datahex)
    else:
        try:
            idhex = idfield
            # '[8]' dlc marker then that many byte tokens
            dlc_tok = toks[i + 2]
            dlc = int(dlc_tok.strip("[]"))
            data = bytes(int(b, 16) for b in toks[i + 3:i + 3 + dlc])
            rtr = False
        except (ValueError, IndexError):
            return None
    try:
        can_id = int(idhex, 16)
    except ValueError:
        return None
    ext = len(idhex.strip()) > 3 or can_id > 0x7FF
    return {"iface": iface, "id": can_id, "ext": ext, "rtr": rtr, "dlc": len(data), "data": data}


def _hex_to_bytes(h):
    h = h.strip()
    if len(h) % 2:
        h = "0" + h
    return bytes(int(h[k:k + 2], 16) for k in range(0, len(h), 2))


def decode_obd(frame):
    """Decode an OBD-II mode-01 request or response frame -> dict, or None if it isn't one."""
    d = frame["data"]
    if frame["id"] == OBD_REQUEST_ID and len(d) >= 3 and d[1] == 0x01:
        pid = d[2]
        name = OBD_PIDS.get(pid, (None,))[0]
        return {"kind": "obd_request", "mode": 1, "pid": pid, "name": name}
    if OBD_RESPONSE_LO <= frame["id"] <= OBD_RESPONSE_LO + 7 and len(d) >= 3 and d[1] == 0x41:
        pid = d[2]
        spec = OBD_PIDS.get(pid)
        out = {"kind": "obd_response", "mode": 1, "pid": pid, "ecu": frame["id"] - OBD_RESPONSE_LO}
        if spec and len(d) >= 3 + spec[1]:
            val, unit = spec[2](d[3:3 + spec[1]])
            out.update(name=spec[0], value=val, unit=unit)
        return out
    return None


def decode_uds(frame):
    """Decode a UDS request / positive / negative response -> dict, or None.

    Handles the ISO-TP single frame: byte 0 high-nibble 0 marks a single frame whose low nibble is
    the payload length, so the UDS service byte is at d[1]. Falls back to treating the whole data
    field as the UDS payload when there is no PCI byte (e.g. a pre-stripped capture)."""
    d = frame["data"]
    if len(d) < 2:
        return None
    if (d[0] >> 4) == 0 and 1 <= (d[0] & 0x0F) <= 7:
        payload = d[1:1 + (d[0] & 0x0F)]
    else:
        payload = d
    if not payload:
        return None
    sid = payload[0]
    if sid == 0x7F and len(payload) >= 3:
        return {"kind": "uds_negative", "service": UDS_SERVICES.get(payload[1], "0x%02X" % payload[1]),
                "nrc": UDS_NRC.get(payload[2], "0x%02X" % payload[2]), "nrc_code": payload[2]}
    if sid & 0x40 and (sid & ~0x40) in UDS_SERVICES:
        base = sid & ~0x40
        return {"kind": "uds_positive", "service": UDS_SERVICES[base], "sid": base}
    if sid in UDS_SERVICES:
        return {"kind": "uds_request", "service": UDS_SERVICES[sid], "sid": sid,
                "writes": sid in UDS_WRITE_SERVICES, "sub": payload[1] if len(payload) > 1 else None}
    return None


def decode(frame):
    """Best-effort protocol decode for one frame (OBD-II, then UDS, else raw)."""
    return decode_obd(frame) or decode_uds(frame) or {"kind": "raw"}


class Bus:
    """Live model of the bus: one entry per arbitration ID with count, period, last data, and which
    bytes have changed (useful for finding the frame that carries a control you care about)."""

    def __init__(self):
        self.ids = {}       # id -> {count, first_t, last_t, last_data, changed(set of byte idx)}

    def feed(self, frame, t):
        e = self.ids.get(frame["id"])
        if e is None:
            self.ids[frame["id"]] = {"count": 1, "first_t": t, "last_t": t,
                                     "last_data": frame["data"], "changed": set(), "ext": frame["ext"]}
            return
        for k in range(min(len(e["last_data"]), len(frame["data"]))):
            if e["last_data"][k] != frame["data"][k]:
                e["changed"].add(k)
        e.update(count=e["count"] + 1, last_t=t, last_data=frame["data"])

    def period_ms(self, can_id):
        e = self.ids.get(can_id)
        if not e or e["count"] < 2:
            return None
        return (e["last_t"] - e["first_t"]) * 1000.0 / (e["count"] - 1)

    def rows(self):
        return [{"id": i, "ext": e["ext"], "count": e["count"], "period_ms": self.period_ms(i),
                 "data": e["last_data"], "changed": sorted(e["changed"])}
                for i, e in sorted(self.ids.items())]


# ---- hardware argv (can-utils) -------------------------------------------------------------------
def candump_argv(iface="can0"):
    return ["candump", "-ta", iface]


def cansend_argv(iface, can_id, data, ext=None):
    """Build a cansend invocation. NEVER call this directly for a transmit — go through prepare_send,
    which gates it. Exposed only so the gated path and tests can build the string."""
    if ext is None:
        ext = can_id > 0x7FF
    width = 8 if ext else 3
    frame = "%0*X#%s" % (width, can_id, bytes(data).hex().upper())
    return ["cansend", iface, frame]


def prepare_send(iface, can_id, data, target, evidence_chain=None, ext=None):
    """Gate a transmit onto the bus. Returns (ok, reason, argv). argv is None unless an authorized,
    in-scope engagement is open — every frame that leaves the tool is scope-checked and logged."""
    ok, why = engagement.authorize_action("canbus:tx:0x%X@%s" % (can_id, iface), target, evidence_chain)
    if not ok:
        return False, why, None
    return True, why, cansend_argv(iface, can_id, data, ext=ext)


def detect(which=shutil.which):
    """Are the SocketCAN user tools present?"""
    return bool(which("candump") and which("cansend"))


class Demo:
    """Synthetic candump lines: a couple of body frames plus live OBD RPM and speed responses."""

    def __init__(self):
        self.i = 0

    def line(self):
        self.i += 1
        rpm = 800 + (self.i * 37) % 3000
        a, b = (rpm * 4) >> 8, (rpm * 4) & 0xFF
        speed = (self.i * 3) % 120
        seq = [
            "  can0  3B2   [8]  %02X 00 10 00 00 00 00 00" % (self.i & 0xFF),   # body/control frame
            "  can0  7E8   [8]  04 41 0C %02X %02X 00 00 00" % (a, b),           # OBD RPM response
            "  can0  7E8   [8]  03 41 0D %02X 00 00 00 00" % speed,              # OBD speed response
            "  can0  1A0   [8]  7F 22 31 00 00 00 00 00",                        # UDS neg (requestOutOfRange)
        ]
        return seq[self.i % len(seq)]


def main(parent=None):
    import queue
    import threading
    import time
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("CANbus")
    s, spath = S.settings("canbus", {"iface": "can0"})
    root, F = S.make_root("CAN Bus", parent=parent)
    import tkinter as tk
    T = S.T
    demo = ("--demo" in sys.argv) or not detect()
    bus = Bus()
    q = queue.Queue()
    st = {"on": False, "gen": 0}

    top = S.top_bar(root, F, "CAN Bus", "Automotive · sniff ungated · transmit gated")
    pill = S.pill(top, F, "Off")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    lb = tk.Listbox(body, bg=T.SURFACE, fg=T.TXT, font=F["map"], bd=0, highlightthickness=0,
                    activestyle="none")
    lb.pack(fill="both", expand=True, padx=T.px(6), pady=T.px(6))
    info = tk.Label(root, text="sniffing is passive — any transmit needs an open engagement",
                    font=F["map"], fg=T.TXT_3, bg=T.SURFACE, anchor="w")
    info.pack(side="bottom", fill="x")

    def render():
        lb.delete(0, "end")
        for r in bus.rows()[:200]:
            idtxt = ("%08X" if r["ext"] else "%03X") % r["id"]
            per = ("%5.0fms" % r["period_ms"]) if r["period_ms"] else "   --  "
            dec = decode({"id": r["id"], "data": r["data"], "ext": r["ext"], "rtr": False, "dlc": len(r["data"])})
            tag = ""
            if dec["kind"].startswith("obd") and dec.get("name"):
                tag = "  %s=%.0f%s" % (dec["name"], dec.get("value", 0), dec.get("unit", ""))
            elif dec["kind"].startswith("uds"):
                tag = "  UDS %s" % dec.get("service", "")
            lb.insert("end", "%s x%-5d %s  %s%s" % (idtxt, r["count"], per, r["data"].hex(" "), tag))

    def worker(gen):
        if demo:
            dm = Demo()
            while st["on"] and st["gen"] == gen:
                fr = parse_candump(dm.line())
                if fr:
                    q.put(fr)
                time.sleep(0.15)
            return
        with S.errfile(os.path.join(S.CACHE, "canbus.err")) as err:
            p = S.spawn(" ".join(candump_argv(s.get("iface", "can0"))), shell=True,
                        stdout=__import__("subprocess").PIPE, stderr=err, text=True)
        try:
            for line in p.stdout:
                if not st["on"] or st["gen"] != gen:
                    break
                fr = parse_candump(line)
                if fr:
                    q.put(fr)
        finally:
            S.stop_group(p, grace=1.0)

    def pump():
        got = False
        try:
            for _ in range(200):
                bus.feed(q.get_nowait(), time.time())
                got = True
        except queue.Empty:
            pass
        if got:
            render()
        root.after(300, pump)

    def toggle(_=None):
        if st["on"]:
            st["on"] = False
            st["gen"] += 1
            pill.config(text="Off", bg=S.DIM)
            T.set_btn(btn, "Sniff", kind="primary")
        else:
            st["on"] = True
            st["gen"] += 1
            pill.config(text="Sniffing" + (" (demo)" if demo else ""), bg=S.GREEN)
            T.set_btn(btn, "Stop", kind="danger")
            threading.Thread(target=worker, args=(st["gen"],), daemon=True).start()

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    btn = S.btn(bar, "Sniff", toggle, F, padx=14, pady=5, kind="primary")
    btn.pack(side="left", padx=(10, 6), pady=6)
    if not parent:
        S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))
    root.bind("<space>", toggle)

    def on_close():
        st["on"] = False
        st["gen"] += 1
        try:
            S.save_json(spath, s)
        except Exception:
            pass
        root.destroy()
    S.bind_quit(root, on_close)
    pump()
    if "--demo" in sys.argv:
        root.after(300, toggle)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
