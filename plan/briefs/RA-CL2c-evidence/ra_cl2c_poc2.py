"""RA-CL2c probe 2: scoped link-local self target end to end; R5 armed; hostname self."""
import json, os, socket, subprocess, sys
sys.path.insert(0, os.getcwd())
import engagement as E, executor, txguard as G, devterm, proxmark  # noqa
OP = "KD0ABC"; E._profile_operator = lambda: OP
OUT = {}
def fresh(scope):
    os.environ.pop("SUITE_TX_LOCK", None); G.reset_session(); E.reset(); executor.reset()
    return E.start("job", "ROE-1", scope, OP)
ll = sys.argv[1]                                   # this device's own link-local, e.g. fe80::…%en0
for scope in (["fe80::/10"], [ll.split("%")[0]], [ll], ["::/0"]):
    st = fresh(scope)
    os.environ["SUITE_TX_LOCK"] = "1"
    ok, why, t = devterm.prepare_ssh(ll, "hackrf_trans''fer -t x.iq -f 1090000000 -x 47")
    OUT["ssh %s scope=%s" % (ll, scope)] = {"start": st[:2], "issued": ok, "why": why,
                                            "argv": list(t.argv) if t else None}
h = socket.gethostname()
OUT["hostname %s" % h] = devterm._self_target(h)
for h in ("::127.0.0.1",):
    fresh(["::/96"]); ok, why, t = devterm.prepare_ssh(h, "uname -a")
    OUT["ssh %s" % h] = {"issued": ok, "why": why}
# R5 armed: label-only in trail + ticket
r5 = {}
for op, kw in (("lf_t55_write", {"block": "1", "data": "00148040"}), ("hf_mf_restore", {}),
               ("hf_iclass_clone", {})):
    fresh(["uid:2006F623AE"]); G.arm(True); G.unlock_session(True)
    ok, why, t = proxmark.prepare(op, "uid:2006F623AE", read_uid=lambda: "2006F623AE", **kw)
    r5[op] = {"issued": ok, "why": why, "ticket_binding": getattr(t, "binding", None),
              "trail_binding": (E.actions()[-1].get("binding") if E.actions() else None)}
OUT["r5"] = r5
json.dump(OUT, open(os.path.join(os.path.dirname(__file__), "ra_cl2c_poc2.json"), "w"), indent=1,
          default=str)
print(json.dumps(OUT, indent=1, default=str))
