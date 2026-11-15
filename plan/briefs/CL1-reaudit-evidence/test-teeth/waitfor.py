import json, os, sys, time
F = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "summary.jsonl")
target, maxs = int(sys.argv[1]), int(sys.argv[2])
t0 = time.time()
n = 0
while time.time() - t0 < maxs:
    n = sum(1 for _ in open(F)) if os.path.exists(F) else 0
    if n >= target:
        break
    time.sleep(5)
print("results:", n)
