import json,sys,collections
d=json.load(open(sys.argv[1]))
print("min",d["min"],"topbar_h",d["topbar_h"],"topbar_minw",d["topbar_minw"])
c=collections.Counter()
ex=collections.defaultdict(set); vw=collections.defaultdict(set)
for view,name,cls,obj,t,px,w,h in d["rows"]:
    k=(px,name,cls,obj)
    c[k]+=1; 
    if len(ex[k])<4: ex[k].add(t)
    vw[k].add(view.split("/")[0])
for k in sorted(c):
    if k[0]<18 or len(sys.argv)>2:
        print(k[0],"px",k[1],"class=%r"%k[2],"obj=%r"%k[3],"n=%d"%c[k],sorted(vw[k]),sorted(ex[k])[:4])
