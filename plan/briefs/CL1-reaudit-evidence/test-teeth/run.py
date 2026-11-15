"""Mutation runner. usage: run.py <nworkers> [ids...]  — each worker has its own tree copy."""
import json, os, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
import queue

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = "/Users/daltonhayes/SentryHub/.claude/worktrees/wf_aa62e8f8-bfc-8"
PY = "/private/tmp/claude-501/-Users-daltonhayes-SentryHub/f893c360-320b-4c7c-9dc4-e3ab8ef11055/scratchpad/venv312/bin/python"
sys.path.insert(0, HERE)
from muts import M

OUT = os.path.join(HERE, "results")
os.makedirs(OUT, exist_ok=True)
TESTS = os.environ.get("MUT_TESTS", "tests").split()


def make_tree(i):
    d = os.path.join(HERE, "trees", "%s%d" % (os.environ.get("MUT_PREFIX", "w"), i))
    if os.path.isdir(d):
        shutil.rmtree(d)
    subprocess.run(["rsync", "-a", "--exclude", ".git", "--exclude", "plan/briefs/CL1-renders",
                    "--exclude", "__pycache__", "--exclude", ".pytest_cache", SRC + "/", d + "/"], check=True)
    return d


def run_one(mid, tree):
    edits = M[mid]
    touched = set()
    try:
        for e in edits:
            f, old, new = e[0], e[1], e[2]
            cnt = e[3] if len(e) > 3 else 1
            p = os.path.join(tree, f)
            s = open(p, encoding="utf-8").read()
            if s.count(old) != cnt:
                return {"id": mid, "error": "old string count %d != %d in %s" % (s.count(old), cnt, f)}
            open(p, "w", encoding="utf-8").write(s.replace(old, new))
            touched.add(f)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
        t0 = time.time()
        r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x" if os.environ.get("MUT_X") else "-q",
                            "--tb=line", "-rf"] + TESTS, cwd=tree, env=env, capture_output=True, text=True, timeout=1500)
        out = r.stdout + r.stderr
        failed = sorted(set(re.findall(r"^(?:FAILED|ERROR) (\S+)", out, re.M)))
        tail = out.strip().splitlines()[-1] if out.strip() else ""
        open(os.path.join(OUT, mid + ".log"), "w").write(out)
        return {"id": mid, "rc": r.returncode, "failed": failed, "tail": tail, "secs": round(time.time() - t0)}
    except Exception as ex:
        return {"id": mid, "error": repr(ex)}
    finally:
        for f in touched:
            shutil.copyfile(os.path.join(SRC, f), os.path.join(tree, f))


def main():
    n = int(sys.argv[1])
    ids = sys.argv[2:] or list(M)
    trees = queue.Queue()
    for i in range(n):
        trees.put(make_tree(i))

    def job(mid):
        t = trees.get()
        try:
            res = run_one(mid, t)
        finally:
            trees.put(t)
        with open(os.path.join(OUT, "summary.jsonl"), "a") as f:
            f.write(json.dumps(res) + "\n")
        print(json.dumps(res), flush=True)
        return res

    with ThreadPoolExecutor(n) as ex:
        list(ex.map(job, ids))


if __name__ == "__main__":
    main()
