"""Apply ALL 'survivor' mutations at once to the scratch copy; print what applied. Restore with `restore`."""
import os, sys, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "mutate.py")).read().split("only = sys.argv")[0]
ns = {"__file__": os.path.join(HERE, "mutate.py")}
exec(src, ns)
M, BASE = ns["M"], ns["BASE"]
names = sys.argv[1:]
for name in names:
    path, old, new = M[name]
    fp = os.path.join(BASE, path)
    s = open(fp).read()
    assert s.count(old) == 1, (name, s.count(old))
    open(fp, "w").write(s.replace(old, new))
    print("applied", name)
