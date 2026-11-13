#!/usr/bin/env python3
"""zwave.py — Z-Wave assessment (Phase 6 #11/#29, authorized engagements).

Passively sniff Z-Wave traffic (sub-GHz, receive-only, ungated), and inside an authorized
engagement actively map the network and query nodes. The real value is the security assessment:
flag nodes using the legacy S0 framework (known weaknesses) or no encryption, versus S2. Pure
helpers (frequency plan, security grading) are unit-testable.
"""
import os
import sys

import engagement

# Regional Z-Wave frequencies (Hz).
REGION_FREQ = {"US": 908_420_000, "EU": 868_420_000, "ANZ": 921_420_000, "HK": 919_820_000}
# Security classes, weakest to strongest.
SEC_RANK = {"none": 0, "S0": 1, "S2_unauth": 2, "S2_auth": 3, "S2_access": 3}


def region_freq(region):
    return REGION_FREQ.get(str(region).upper())


def sniff_argv(region, out_pcap):
    f = region_freq(region) or REGION_FREQ["US"]
    return ["zwave-sniffer", "-f", str(int(f)), "-w", out_pcap]


def query_argv(region, node_id):
    return ["zwave-query", "-f", str(int(region_freq(region) or REGION_FREQ["US"])),
            "-n", str(int(node_id))]


def grade_node(node):
    """Grade one node's security: returns (level, note). node: {id, security}."""
    sec = str(node.get("security", "none")).lower().replace("/", "_").replace(" ", "_")
    sec = {"s0": "S0", "s2_unauthenticated": "S2_unauth", "s2_authenticated": "S2_auth",
           "s2_access_control": "S2_access"}.get(sec, node.get("security", "none"))
    rank = SEC_RANK.get(sec, 0)
    if rank == 0:
        return "weak", "no encryption — control frames in the clear"
    if rank == 1:
        return "weak", "S0 (legacy) — known key-exchange weakness"
    return "ok", "S2 — current security"


def assess(nodes):
    """Security assessment across nodes. Returns {weak: [...], ok: [...], summary}."""
    weak, ok = [], []
    for n in nodes:
        level, note = grade_node(n)
        (weak if level == "weak" else ok).append({"id": n.get("id"), "note": note})
    return {"weak": weak, "ok": ok,
            "summary": "%d of %d nodes weak (S0/none)" % (len(weak), len(nodes))}


def prepare(action, target="network", region="US", out="zw.pcap", node_id=1, evidence_chain=None):
    if action == "sniff":
        return True, "passive capture (ungated)", sniff_argv(region, out)
    if action == "map":
        argv = ["zwave-map", "-f", str(int(region_freq(region) or REGION_FREQ["US"]))]
    elif action == "query":
        argv = query_argv(region, node_id)
    else:
        return False, "unknown action %r" % (action,), None
    ok, why = engagement.authorize_action("zwave:" + action, target, evidence_chain)
    if not ok:
        return False, why, None
    return True, why, argv


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("ZWave")
    S.settings("zwave", {"region": "US"})
    root, F = S.make_root("Z-Wave", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Z-Wave", "Sub-GHz · map + S0/S2 security grade")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Passively sniff Z-Wave, and (in an authorized engagement) map the network and "
                  "grade each node's security — flagging S0/unencrypted nodes that an attacker "
                  "could control. Needs a sub-GHz Z-Wave sniffer.").pack(fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
