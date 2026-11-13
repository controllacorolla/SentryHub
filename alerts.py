#!/usr/bin/env python3
"""alerts.py — configurable alert engine (Phase 3c).

Any module feeds "events" (a dict describing a contact or a value, with an 'id' and a 'ts');
rules evaluate them and fire deliveries (visual banner, audio tone, spoken). Rule types:

  threshold  — a field crosses a value         params: field, op (< <= > >= == !=), value
  presence   — a new entity matching a filter   params: match {field: value}  (optional)
  geofence   — entity enters/exits/sits in zone params: lat, lon, radius_nm, mode enter|exit|inside
  anomaly    — value deviates from its baseline params: field, k (sigmas), min_samples
  compound   — several rules fired within a window  params: rules [id,...], window_s

Pure: no Tk, no I/O beyond optional JSON load/save. Delivery is an injected callback, so the
engine is unit-testable and the UI decides how an alert is shown/spoken.
"""
import json
import time

import geo

RULE_TYPES = ("threshold", "presence", "geofence", "anomaly", "compound")
DELIVERY_PATHS = ("banner", "tone", "speak")
_OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


def _get(event, path):
    """Dotted lookup into a possibly-nested event dict ('contact.alt_m')."""
    cur = event
    for k in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur


def _matches(event, flt):
    return all(_get(event, k) == v for k, v in (flt or {}).items())


class AlertEngine:
    def __init__(self, deliver=None):
        self.rules = []                 # list of rule dicts
        self.deliver = deliver or (lambda alert: None)
        self._seen = {}                 # rule_id -> set of entity ids (presence)
        self._inside = {}               # rule_id -> {entity_id: bool} (geofence)
        self._stats = {}                # rule_id -> [n, mean, M2] (anomaly, Welford)
        self._last_fire = {}            # rule_id -> ts (for compound windows)

    # ---- rule management ------------------------------------------------------------------
    def add_rule(self, rule):
        if rule.get("type") not in RULE_TYPES:
            raise ValueError("bad rule type: %r" % rule.get("type"))
        rule.setdefault("id", "rule%d" % (len(self.rules) + 1))
        rule.setdefault("enabled", True)
        rule.setdefault("delivery", ["banner"])
        self.rules.append(rule)
        return rule

    def remove_rule(self, rule_id):
        self.rules = [r for r in self.rules if r.get("id") != rule_id]

    def set_enabled(self, rule_id, on):
        for r in self.rules:
            if r.get("id") == rule_id:
                r["enabled"] = bool(on)

    # ---- evaluation -----------------------------------------------------------------------
    def feed(self, event, now=None):
        """Evaluate every enabled rule against one event. Returns the list of alerts fired."""
        now = time.time() if now is None else now
        fired = []
        for r in self.rules:
            if not r.get("enabled", True) or r.get("type") == "compound":
                continue
            ok, detail = self._eval(r, event, now)
            if ok:
                fired.append(self._fire(r, event, now, detail))
        # compound rules look at what fired recently (including this event's fires)
        for r in self.rules:
            if r.get("enabled", True) and r.get("type") == "compound":
                ok, detail = self._eval_compound(r, now)
                if ok:
                    fired.append(self._fire(r, event, now, detail))
        return fired

    def _eval(self, rule, event, now):
        t = rule["type"]
        p = rule.get("params", {})
        if t == "threshold":
            v = _get(event, p.get("field"))
            if v is None or p.get("op") not in _OPS:
                return False, ""
            try:
                return (_OPS[p["op"]](v, p.get("value")),
                        "%s %s %s (=%s)" % (p.get("field"), p["op"], p.get("value"), v))
            except TypeError:
                return False, ""
        if t == "presence":
            if not _matches(event, p.get("match")):
                return False, ""
            eid = event.get("id")
            seen = self._seen.setdefault(rule["id"], set())
            if eid in seen:
                return False, ""
            seen.add(eid)
            return True, "new %s" % (eid,)
        if t == "geofence":
            lat, lon = _get(event, p.get("lat_field", "lat")), _get(event, p.get("lon_field", "lon"))
            if lat is None or lon is None:
                return False, ""
            if p.get("lat") is None or p.get("lon") is None:
                return False, ""          # malformed rule (no centre): skip it, don't crash every rule
            d = geo.dist_nm(p["lat"], p["lon"], lat, lon)
            inside = d <= p.get("radius_nm", 1.0)
            eid = event.get("id")
            prev = self._inside.setdefault(rule["id"], {}).get(eid, False)
            self._inside[rule["id"]][eid] = inside
            mode = p.get("mode", "enter")
            if mode == "inside":
                return inside, "%s inside zone (%.2f nm)" % (eid, d)
            if mode == "enter":
                return (inside and not prev), "%s entered zone" % (eid,)
            if mode == "exit":
                return (prev and not inside), "%s left zone" % (eid,)
            return False, ""
        if t == "anomaly":
            v = _get(event, p.get("field"))
            if v is None:
                return False, ""
            st = self._stats.setdefault(rule["id"], [0, 0.0, 0.0])
            n, mean, m2 = st
            fired = False
            detail = ""
            if n >= p.get("min_samples", 8):
                std = (m2 / n) ** 0.5 if n else 0.0
                if std > 0:
                    if abs(v - mean) > p.get("k", 3.0) * std:
                        fired = True
                        detail = "%s=%.3g deviates %.1fσ" % (p.get("field"), v, abs(v - mean) / std)
                elif abs(v - mean) > p.get("min_delta", 1e-6):
                    # perfectly flat baseline (std 0): any real move off it is anomalous
                    fired = True
                    detail = "%s=%.3g off flat baseline %.3g" % (p.get("field"), v, mean)
            n += 1                       # Welford update
            delta = v - mean
            mean += delta / n
            m2 += delta * (v - mean)
            self._stats[rule["id"]] = [n, mean, m2]
            return fired, detail
        return False, ""

    def _eval_compound(self, rule, now):
        p = rule.get("params", {})
        window = p.get("window_s", 10)
        refs = p.get("rules", [])
        if not refs:
            return False, ""
        times = [self._last_fire.get(rid) for rid in refs]
        if any(t is None for t in times):
            return False, ""
        if max(times) - min(times) <= window and (now - max(times)) <= window:
            # don't re-fire for the same coincidence
            if self._last_fire.get(rule["id"], -1) >= max(times):
                return False, ""
            return True, "rules %s within %ds" % (", ".join(refs), window)
        return False, ""

    def _fire(self, rule, event, now, detail):
        self._last_fire[rule["id"]] = now
        alert = {"rule_id": rule["id"], "name": rule.get("name", rule["id"]),
                 "text": rule.get("name", rule["id"]) + (": " + detail if detail else ""),
                 "detail": detail, "delivery": rule.get("delivery", ["banner"]),
                 "ts": now, "event": event}
        try:
            self.deliver(alert)
        except Exception:
            pass
        return alert

    # ---- persistence / sharing ------------------------------------------------------------
    def export_rules(self):
        return [dict(r) for r in self.rules]

    def import_rules(self, rules, replace=False):
        if replace:
            self.rules = []
        for r in rules:
            self.add_rule(dict(r))

    def save(self, path):
        try:
            with open(path, "w") as f:
                json.dump({"rules": self.export_rules()}, f, indent=2)
            return True
        except OSError:
            return False

    def load(self, path, replace=True):
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, ValueError):
            return False
        self.import_rules(d.get("rules", []), replace=replace)
        return True
