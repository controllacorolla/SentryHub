from common import *
h = hub(demo=False)
h.open_callsign("RECON", "WIFI"); pump(200)
seen = set()
for i in range(40):
    pump(250); seen.add(h.current_page().page_status().get("sdr"))
print("RECON/WIFI status texts over 10s:", seen)
h.open_callsign("SWEEP"); seen = set()
for i in range(30):
    pump(200); seen.add(h.current_page().page_status().get("sdr"))
print("SWEEP status texts over 6s:", seen)
h.open_callsign("SYSTEM", "SETTINGS"); pump(1500)
print("SYSTEM/SETTINGS:", h.current_page().page_status())
h.open_callsign("FORGE", "SERIAL"); seen = set()
for i in range(30):
    pump(200); seen.add(h.current_page().page_status().get("sdr"))
print("FORGE/SERIAL:", seen)
h.close(); pump(200)
