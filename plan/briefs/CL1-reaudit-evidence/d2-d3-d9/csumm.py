import json,sys,collections
d=json.load(open(sys.argv[1])); thr=float(sys.argv[2])
agg=collections.defaultdict(list)
for view,kind,cls,st,t,bg,fg,k in d["res"]:
    if k<thr: agg[(kind,cls,st,bg,fg,k)].append((view,t))
for key in sorted(agg,key=lambda z:z[5]):
    v=agg[key]; print(key, len(v), v[:3])
print("GREEN:")
g=collections.defaultdict(set)
for view,kind,cls,t in d["green"]: g[(kind,cls,t)].add(view.split("+")[0])
for k in sorted(g): print(k, sorted(g[k])[:4])
print("NONGRAY:", d["nongray"][:40])
