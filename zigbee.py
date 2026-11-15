#!/usr/bin/env python3
"""zigbee.py — Zigbee / 802.15.4 assessment (Phase 6 #10/#28, authorized engagements).

With a CC2531/killerbee radio: passively sniff a channel (receive-only, ungated), and — inside an
authorized engagement — actively discover networks (beacon requests), enumerate devices, and
assess key exposure / injection. Active discovery/inject touches the network, so it is gated on an
in-scope engagement (PAN id / channel) and logged. Pure helpers are unit-testable.
"""
import os
import sys

import engagement

CHANNELS = list(range(11, 27))          # 2.4 GHz 802.15.4 channels 11..26


def channel_to_mhz(ch):
    return 2405 + 5 * (int(ch) - 11) if 11 <= int(ch) <= 26 else None


def sniff_argv(channel, out_pcap, iface=0):
    """Passive channel capture (receive-only)."""
    return ["zbdump", "-c", str(int(channel)), "-w", out_pcap]


def _discover_argv(channel, iface=0):
    """Active network discovery (sends beacon requests on one channel) — ACTIVE."""
    return ["zbstumbler", "-i", str(iface), "-c", str(int(channel))]


def _inject_argv(channel, pcap, iface=0):
    """Replay/inject frames for an injection-tolerance assessment — ACTIVE."""
    return ["zbreplay", "-c", str(int(channel)), "-r", pcap]


def prepare(action, target=None, channel=15, out="zb.pcap", evidence_chain=None, iface=0,
            pan=None):
    """'sniff' is passive/ungated. 'discover'/'inject' are active and gated on an engagement whose
    scope lists the PAN and channel (pan:0x1A2B@15) — audit G5. discover (no PAN known yet) needs
    a scoped entry on that channel. Returns (ok, reason, ticket|argv for sniff)."""
    try:
        ch = int(channel)
    except (TypeError, ValueError):
        return False, "channel must be a number", None
    if ch not in CHANNELS:
        return False, "channel %r is not an 802.15.4 2.4 GHz channel (11-26)" % (channel,), None
    if action == "sniff":
        return True, "passive capture (ungated)", sniff_argv(ch, out, iface)
    if action == "discover":
        argv, tgt = _discover_argv(ch, iface), (None, ch)
    elif action == "inject":
        if pan is None:
            return False, "inject needs the target PAN id (scope pan:0xNNNN@channel)", None
        try:
            tgt = (int(pan), ch)
        except (TypeError, ValueError):
            return False, "PAN id must be a number", None
        argv = _inject_argv(ch, out, iface)
    else:
        return False, "unknown action %r" % (action,), None
    return engagement.issue("zigbee:" + action, tgt, argv=argv, kind="zigbee",
                            evidence_chain=evidence_chain, label="zigbee:" + action)


def main(parent=None):
    import shutil
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Zigbee")
    S.settings("zigbee", {})
    root, F = S.make_root("Zigbee", parent=parent)
    import tkinter as tk
    T = S.T
    have = bool(shutil.which("zbdump") or shutil.which("zbstumbler"))
    S.top_bar(root, F, "Zigbee", "802.15.4 · sniff ungated · active gated")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text=("Passive channel sniffing (receive-only), plus active network discovery and "
                   "injection assessment inside an authorized engagement (logged). Needs a "
                   "CC2531/killerbee radio. " + ("killerbee present." if have
                                                 else "Install killerbee + a CC2531."))).pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
