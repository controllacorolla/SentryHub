#!/usr/bin/env python3
"""mlat.py — MLAT contribution (Phase 7 #8).

Feeds the local ADS-B receiver's Mode-S data to community multilateration networks (adsbexchange,
OpenSky), which combine several receivers' timing to fix the position of aircraft that only send
Mode-S (no position). Builds the mlat-client command for a validated station; it does not transmit
RF. Pure config/validation is unit-testable.
"""
import os
import sys

MLAT_SERVERS = {
    "adsbexchange": {"host": "feed.adsbexchange.com", "port": 31090, "name": "ADSBExchange"},
    "opensky":      {"host": "feed.opensky-network.org", "port": 10004, "name": "OpenSky"},
}


def valid_station(lat, lon, alt_m):
    """A valid MLAT station needs a precise, plausible fixed location."""
    try:
        lat, lon, alt_m = float(lat), float(lon), float(alt_m)
    except (TypeError, ValueError):
        return False, "lat/lon/alt must be numbers"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False, "lat/lon out of range"
    if not (-430 <= alt_m <= 9000):
        return False, "altitude implausible for a ground station"
    if lat == 0 and lon == 0:
        return False, "null island — set your real receiver position"
    return True, ""


def mlat_client_argv(server, lat, lon, alt_m, user, input_port=30005, results_port=30105):
    """Build the mlat-client command feeding a dump1090 Beast stream to the chosen network."""
    if server not in MLAT_SERVERS:
        raise ValueError("unknown MLAT server: %r" % server)
    ok, why = valid_station(lat, lon, alt_m)
    if not ok:
        raise ValueError("invalid station: " + why)
    s = MLAT_SERVERS[server]
    return ["mlat-client", "--input-type", "dump1090",
            "--input-connect", "localhost:%d" % int(input_port),
            "--lat", "%.6f" % float(lat), "--lon", "%.6f" % float(lon),
            "--alt", "%dm" % int(alt_m), "--user", str(user),
            "--server", "%s:%d" % (s["host"], int(s["port"])),
            "--results", "beast,connect,localhost:%d" % int(results_port)]


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("MLAT")
    S.settings("mlat", {"server": "adsbexchange", "user": "", "alt_m": 1600})
    root, F = S.make_root("MLAT Feed", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "MLAT Feed", "Contribute ADS-B to multilateration")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Feeds your Mode-S data to a community MLAT network so aircraft without position "
                  "reporting can be located by timing across receivers. Needs a precise fixed "
                  "station position and a feeder account. No RF is transmitted.").pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
