import json, os
F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "summary.jsonl")
for line in open(F):
    r = json.loads(line)
    if "error" in r:
        print("ERR ", r["id"], r["error"]); continue
    f = [x.split("::")[-1] for x in r["failed"]]
    cl1 = [x.split("::")[-1] for x in r["failed"] if "test_cl1_screen" in x]
    old = [x.split("::")[-1] for x in r["failed"] if "test_palisade_qt" in x]
    status = "KILLED " if r["failed"] or r["rc"] not in (0,) else "SURVIVED"
    print("%s %-38s rc=%s %ss cl1=%s old=%s | %s" % (status, r["id"], r["rc"], r["secs"], cl1[:6], old[:4], r["tail"][-60:]))
