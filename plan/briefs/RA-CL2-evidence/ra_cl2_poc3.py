#!/usr/bin/env python3
"""RA-CL2 — re-run of the G9 power/sample-rate probe without the string sample rate (which crashes
prepare_replay — recorded separately), plus the string case isolated."""
import os, sys, traceback
sys.path.insert(0, os.getcwd())
import txguard as G, replay  # noqa: E402
G.reset_session(); G.arm(True); G.unlock_session(True)
s = {"tx_enabled": True}
p = [G.authorize("replay", 915_000_000, power_dbm=v, settings=s)[0] for v in (float("nan"), float("inf"), "x", True, -200)]
sr = [replay.prepare_replay("b.iq", 915_000_000, v, True, settings=s)[0] for v in (100_000_000, 0, -1, float("nan"), 1_000)]
ok, why, pw = G.authorize("replay", 915_000_000, power_dbm=40, settings=s)
print("G9 power denials (all should be False):", p)
print("G9 sample-rate denials (all should be False):", sr)
print("G9 power 40 dBm -> allowed:", ok, "clamped to", pw)
print("PASS" if not any(p) and not any(sr) and ok and pw == 10 else "FAIL")
for v in ("2e6", "2000000", 2e6):
    try:
        print("sample_rate=%r ->" % (v,), replay.prepare_replay("b.iq", 915_000_000, v, True, settings=s)[:2])
    except Exception as e:
        print("sample_rate=%r -> EXCEPTION %s: %s" % (v, type(e).__name__, e))
G.reset_session()
