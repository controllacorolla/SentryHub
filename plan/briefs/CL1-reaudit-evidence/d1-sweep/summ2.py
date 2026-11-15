import json,sys,collections,glob,os
D=os.path.dirname(os.path.abspath(__file__))
agg=collections.OrderedDict()
for rep in sorted(glob.glob(D+"/renders/*/report.json")):
    name=rep.split("/")[-2]
    st = name.startswith("stress")
    if (sys.argv[1]=="stress") != st: continue
    r=json.load(open(rep))
    print(name, "hub_min max", max(v["hub_min"][0] for v in r.values()), max(v["hub_min"][1] for v in r.values()),
      "page_min max", max((v.get("page_min",[0,0])[0] for v in r.values())), max((v.get("page_min",[0,0])[1] for v in r.values())),
      "topbar(w,h,min,hint)", sorted(set(tuple(v["topbar"]) for v in r.values())), "grabs", set(tuple(v["grab"]) for v in r.values()))
    for tag,v in r.items():
        for k,d,x in v["issues"]:
            if k.startswith("INFO"): continue
            if "nav" in d and k=="SQUEEZED": continue
            if "STANDBY · no feed" in d: continue
            agg.setdefault((tag,k,d),[]).append((name,x))
for (tag,k,d),lst in agg.items():
    print("%-16s %-24s %s | n=%d e.g. %s %s"%(tag,k,d,len(lst),lst[0][0],lst[0][1]))
