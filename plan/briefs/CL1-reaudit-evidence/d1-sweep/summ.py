import json,sys,collections,glob,os
D=os.path.dirname(os.path.abspath(__file__))
for rep in sorted(glob.glob(D+"/renders/*/report.json")):
    name=rep.split("/")[-2]
    if len(sys.argv)>1 and sys.argv[1] not in name: continue
    r=json.load(open(rep))
    print("=====",name, "max hub_min", max(v["hub_min"][0] for v in r.values()), max(v["hub_min"][1] for v in r.values()),
          "max page_min", max((v.get("page_min",[0,0])[0] for v in r.values())), max((v.get("page_min",[0,0])[1] for v in r.values())),
          "topbar", sorted(set(tuple(v["topbar"]) for v in r.values())))
    for tag,v in r.items():
        iss=[i for i in v["issues"] if not i[0].startswith("INFO")]
        if len(sys.argv)>2:
            iss=[i for i in iss if sys.argv[2] in i[0]]
        if iss:
            print(" --",tag, "page", v.get("page_size"), "min", v.get("page_min"), v.get("overlay",""))
            seen=set()
            for k,d,x in iss:
                key=(k,d)
                if key in seen: continue
                seen.add(key)
                print("    ",k,"|",d,"|",x)
