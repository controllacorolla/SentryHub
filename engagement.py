#!/usr/bin/env python3
"""engagement.py — engagement authorization gate for active assessment.

Active pen-test actions (RFID write/clone, Zigbee/Z-Wave enumeration & injection assessment, IQ
replay, anything that touches a target rather than just listening) are gated here, the way TX is
gated by txguard. An action is allowed only inside an AUTHORIZED ENGAGEMENT: a named engagement
with a written-authorization reference, an explicit target SCOPE (only these devices/networks), and
an operator. Every gated action is scope-checked and recorded to the evidence chain, so the
assessment is bounded and auditable. The operator remains responsible for the legal authorization;
this makes it explicit, in-scope-only, and logged.

Passive/receive-only features do NOT go through this gate — only actions against a target. In-memory
per session; never persisted (an engagement is opened deliberately each time). Pure + testable.
"""
import fnmatch
import os
import sys
import time

_ENG = {"active": False, "name": None, "authorization": None, "scope": [], "operator": None,
        "started": None}
_ACTIONS = []                      # in-session audit trail (also mirrored to the evidence chain)


def start(name, authorization, scope, operator):
    """Open an engagement. Requires a name, a non-empty authorization reference (ticket/ROE/owner
    consent), a non-empty target scope, and an operator. Returns (ok, reason)."""
    if not name:
        return False, "engagement needs a name"
    if not authorization:
        return False, "engagement needs an authorization reference (scope/ROE/owner consent)"
    if not scope:
        return False, "engagement needs an explicit target scope (no open-ended testing)"
    if not operator:
        return False, "engagement needs an operator"
    _ENG.update(active=True, name=name, authorization=str(authorization),
                scope=list(scope), operator=operator, started=time.time())
    _ACTIONS.clear()
    return True, "engagement '%s' active (%d targets in scope)" % (name, len(scope))


def end():
    was = _ENG["name"]
    _ENG.update(active=False, name=None, authorization=None, scope=[], operator=None, started=None)
    return was


def is_active():
    return _ENG["active"]


def info():
    return dict(_ENG)


def in_scope(target):
    """Is target within the engagement scope? Scope entries may be exact or fnmatch wildcards
    (e.g. 'AA:BB:CC:*' for a MAC OUI, 'MyNet-*' for SSIDs)."""
    t = str(target)
    return any(fnmatch.fnmatch(t, str(s)) or t == str(s) for s in _ENG["scope"])


def authorize_action(action, target, evidence_chain=None):
    """Gate one active action against `target`. Returns (ok, reason). On success, records the action
    to the in-session trail and, if given, to the evidence chain (hash-chained, tamper-evident)."""
    if not _ENG["active"]:
        return False, "no active engagement — open an authorized engagement first"
    if not in_scope(target):
        return False, "%r is not in the engagement scope — refusing (out of authorization)" % (target,)
    rec = {"t": time.time(), "action": action, "target": str(target),
           "engagement": _ENG["name"], "operator": _ENG["operator"]}
    _ACTIONS.append(rec)
    if evidence_chain is not None:
        try:
            evidence_chain.add("%s:%s" % (action, target),
                               data=("%s|%s|%s" % (action, target, _ENG["authorization"])).encode(),
                               meta=rec)
        except Exception:
            pass
    return True, "authorized: %s on %s (engagement '%s')" % (action, target, _ENG["name"])


def actions():
    return list(_ACTIONS)


def reset():
    """Drop any engagement + trail (startup and tests)."""
    end()
    _ACTIONS.clear()


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Engagement")
    S.settings("engagement", {})
    root, F = S.make_root("Engagement", parent=parent)
    import tkinter as tk
    T = S.T
    S.top_bar(root, F, "Engagement", "Scoped authorization for active assessment")
    tk.Label(root, bg=S.BG, fg=T.TXT_3, font=F["sm"], anchor="w", justify="left",
             wraplength=T.px(700), padx=T.px(12), pady=T.px(10),
             text="Open a scoped, authorized engagement before any active test. Every action is "
                  "checked against the target scope and logged to the evidence chain, so the "
                  "assessment stays in-bounds and auditable. Passive monitoring does not need this.").pack(
        fill="both", expand=True)
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
