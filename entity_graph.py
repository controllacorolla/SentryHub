#!/usr/bin/env python3
"""entity_graph.py — multi-radio identity resolution: observations -> entities.

Not contacts — identities. A Wi-Fi probe, a BLE beacon and a TPMS sensor that keep arriving and
leaving together are ONE entity (a person in a car). The same entity seen at a different site days
later is recognised. This module is the PURE engine: it normalises event-bus 'contact' events into
Observations, correlates observations from DIFFERENT sources by temporal (+ spatial, when both have
GNSS) co-occurrence, promotes a repeatedly-co-occurring pair to a confirmed Entity, and recognises an
identifier seen in a prior session — deterministically, never on probability.

Every Entity carries its own evidence (the audit trail that answers "how do you know?" months later):
a stable UUID, per-source first/last-seen, the confirmation score and the resolver thresholds frozen
at promotion time, the full link history, recognition links to prior sessions, and a source
breakdown. Automated reporting cites these records directly.

Honesty: 'recognized' is set ONLY on a deterministic identifier re-match; a weak link stays 'candidate'
with an explicit score; spatial correlation is used only when both observations carry a position (no
GNSS -> temporal-only). It is a pure receive-only consumer — standard library only (uuid/json/math/
time), no Qt, no radio, no network, no OPSEC gating (listening is not emitting). The Qt layer feeds it
bus contacts, persists it, and flags demo.
"""
import json
import math
import time
import uuid

DEFAULTS = {
    "temporal_window_s": 90,      # two sightings this close in time may co-occur
    "spatial_window_m": 50,       # ...and this close in space, when both have GNSS
    "promotion_n": 3,             # co-occurrences required to confirm a link
    "promotion_m": 3,             # ...spread across this many distinct time windows
    "window_bucket_s": 600,       # a "distinct window" is a 10-minute bucket
    "ttl_s": 3600,                # a candidate not seen within this is dropped (decayed)
}


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def new_uuid():
    """Fresh entity UUID. A module function so tests can seed deterministic ids."""
    return "ent-" + uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- observation normalisation
def identifier_for(source, kind, payload):
    """The deterministic identity key for a contact: '<kind>:<id>'. The kind namespaces the raw id so
    the same string under two protocols never collides. None if there is no usable id."""
    raw = payload.get("hexid") or payload.get("uas_id") or payload.get("id")
    raw = str(raw).strip() if raw is not None else ""
    if not raw:
        return None
    return "%s:%s" % (kind or payload.get("kind") or "?", raw)


def observation_from_contact(event, demo=False):
    """eventbus 'contact' event -> Observation dict, or None. The Qt worker sets `demo` (it knows
    whether this session is demo); the bus event itself carries no demo flag."""
    if not isinstance(event, dict) or event.get("type") != "contact":
        return None
    pl = event.get("payload") or {}
    kind = pl.get("kind", "?")
    ident = identifier_for(event.get("source"), kind, pl)
    if not ident:
        return None
    return {"source": event.get("source", "?"), "identifier": ident, "kind": kind,
            "t": event.get("ts", time.time()), "lat": pl.get("lat"), "lon": pl.get("lon"),
            "rssi": pl.get("rssi"), "demo": bool(demo)}


# ---------------------------------------------------------------- the graph
class EntityGraph:
    """Incremental identity resolver + evidence store. Pure and deterministic: feed it the same
    observations (with explicit timestamps) and it yields the same entities and the same
    entity_update events every time."""

    def __init__(self, config=None, session=None, historical=None):
        self.cfg = dict(DEFAULTS)
        self.cfg.update(config or {})
        self.session = session or time.strftime("%Y%m%d")
        self._entities = {}        # uuid -> entity dict
        self._ident_uuid = {}      # identifier -> uuid (current session)
        self._links = {}           # frozenset{i,j} -> link record
        self._buffer = []          # recent observations, for co-occurrence pairing
        self._historical = historical or {}   # identifier -> {entity_uuid, session} from prior sessions

    # -- public API -------------------------------------------------------------------------
    def ingest(self, obs):
        """Fold one Observation in. Returns a list of entity_update events (recognized/confirmed)."""
        events = []
        ident = obs["identifier"]
        uuid_ = self._ensure_entity(obs, events)
        self._record(self._entities[uuid_], obs)
        self._prune_buffer(obs["t"])
        for prev in self._buffer:                      # co-occurrence with DIFFERENT-source sightings
            if prev["source"] == obs["source"] or prev["identifier"] == ident:
                continue
            if self._co_occur(prev, obs):
                events += self._link(prev, obs)
        self._buffer.append(obs)
        return events

    def ingest_contact(self, event, demo=False):
        obs = observation_from_contact(event, demo=demo)
        return self.ingest(obs) if obs else []

    def decay(self, now=None):
        """Drop candidate entities not seen within the TTL. Returns 'disappeared' events."""
        now = time.time() if now is None else now
        events = []
        for uuid_ in list(self._entities):
            ent = self._entities.get(uuid_)
            if not ent or ent["status"] == "confirmed":
                continue
            last = max(ent["last_seen"].values(), default=0)
            if now - last >= self.cfg["ttl_s"]:
                events.append({"change": "disappeared", "entity_uuid": uuid_,
                               "entity": dict(ent)})
                for i in list(ent["identifiers"]):
                    self._ident_uuid.pop(i, None)
                del self._entities[uuid_]
        return events

    def entities(self):
        return [dict(e) for e in self._entities.values()]

    def entity(self, uuid_):
        e = self._entities.get(uuid_)
        return dict(e) if e else None

    def lookup(self, identifier):
        """Deterministic: the entity currently carrying this identifier, or None."""
        u = self._ident_uuid.get(identifier)
        return dict(self._entities[u]) if u else None

    def candidate_progress(self, uuid_):
        """(co_occurrences, windows, need_n, need_m) — the best in-progress link for a candidate, so
        the UI can honestly show 'candidate — 1 of 3 required co-occurrences'."""
        ent = self._entities.get(uuid_)
        best = (0, 0)
        if ent:
            idents = set(ent["identifiers"])
            for key, link in self._links.items():
                if key & idents:
                    best = max(best, (len(link["cooc"]), len(link["windows"])))
        return best[0], best[1], self.cfg["promotion_n"], self.cfg["promotion_m"]

    # -- persistence ------------------------------------------------------------------------
    def to_dict(self):
        return {"version": 1, "session": self.session, "saved": time.time(),
                "config": dict(self.cfg),
                "entities": {u: _jsonable(e) for u, e in self._entities.items()}}

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)
        return path

    @classmethod
    def load(cls, path):
        with open(path) as f:
            data = json.load(f)
        g = cls(config=data.get("config"), session=data.get("session"))
        for u, e in data.get("entities", {}).items():
            g._entities[u] = e
            for i in e.get("identifiers", {}):
                g._ident_uuid[i] = u
        return g

    # -- internals --------------------------------------------------------------------------
    def _ensure_entity(self, obs, events):
        ident = obs["identifier"]
        if ident in self._ident_uuid:
            return self._ident_uuid[ident]
        hist = self._historical.get(ident)                 # deterministic match-on-return
        if hist and hist["entity_uuid"] in self._entities:
            uuid_ = hist["entity_uuid"]                     # a sibling identifier already adopted it
            self._ident_uuid[ident] = uuid_
            self._entities[uuid_]["recognition_links"].append(
                {"entity_uuid": hist["entity_uuid"], "identifier": ident, "t": obs["t"],
                 "session": hist.get("session")})
            events.append({"change": "recognized", "entity_uuid": uuid_,
                           "entity": self._entities[uuid_], "identifier": ident})
            return uuid_
        uuid_ = hist["entity_uuid"] if hist else new_uuid()
        ent = {"entity_uuid": uuid_, "status": "candidate", "confirmation_score": 0,
               "first_seen": {}, "last_seen": {}, "identifiers": {}, "source_breakdown": {},
               "link_history": [], "recognition_links": [],
               "resolver_thresholds_at_promotion": None, "positions": [],
               "demo": bool(obs.get("demo"))}
        self._entities[uuid_] = ent
        self._ident_uuid[ident] = uuid_
        if hist:
            ent["recognition_links"].append({"entity_uuid": hist["entity_uuid"], "identifier": ident,
                                             "t": obs["t"], "session": hist.get("session")})
            events.append({"change": "recognized", "entity_uuid": uuid_, "entity": ent,
                           "identifier": ident})
        return uuid_

    def _record(self, ent, obs):
        s, ident, t = obs["source"], obs["identifier"], obs["t"]
        ent["first_seen"].setdefault(s, t)
        ent["last_seen"][s] = t
        rec = ent["identifiers"].setdefault(ident, {"source": s, "kind": obs["kind"], "count": 0})
        rec["count"] += 1
        ent["source_breakdown"][s] = ent["source_breakdown"].get(s, 0) + 1
        if obs.get("lat") is not None and obs.get("lon") is not None:
            ent["positions"].append({"t": t, "lat": obs["lat"], "lon": obs["lon"]})
            del ent["positions"][:-500]

    def _prune_buffer(self, now):
        horizon = now - self.cfg["temporal_window_s"]
        self._buffer = [o for o in self._buffer if o["t"] >= horizon]

    def _co_occur(self, a, b):
        if abs(a["t"] - b["t"]) > self.cfg["temporal_window_s"]:
            return False
        if None not in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
            return haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]) <= self.cfg["spatial_window_m"]
        return True                                        # temporal-only (no GNSS on a side)

    def _link(self, a, b):
        key = frozenset({a["identifier"], b["identifier"]})
        link = self._links.get(key)
        if link is None:
            link = {"cooc": [], "windows": set(), "spatial": False,
                    "sources": {a["identifier"]: a["source"], b["identifier"]: b["source"]}}
            self._links[key] = link
        link["cooc"].append(b["t"])
        link["windows"].add(int(b["t"] // self.cfg["window_bucket_s"]))
        if None not in (a.get("lat"), b.get("lat")):
            link["spatial"] = True
        if not link.get("confirmed") and len(link["windows"]) >= self.cfg["promotion_m"] \
                and len(link["cooc"]) >= self.cfg["promotion_n"]:
            link["confirmed"] = True
            return self._confirm(a, b, link)
        return []

    def _confirm(self, a, b, link):
        ent = self._merge(self._ident_uuid[a["identifier"]], self._ident_uuid[b["identifier"]])
        promoting = ent["status"] != "confirmed"
        ent["status"] = "confirmed"
        ent["confirmation_score"] = max(ent["confirmation_score"], len(link["cooc"]))
        if ent["resolver_thresholds_at_promotion"] is None:    # frozen at FIRST promotion, not rewritten
            ent["resolver_thresholds_at_promotion"] = {
                "temporal_window_s": self.cfg["temporal_window_s"],
                "spatial_window_m": self.cfg["spatial_window_m"],
                "promotion_n": self.cfg["promotion_n"], "promotion_m": self.cfg["promotion_m"],
                "spatial_used": link["spatial"], "at": b["t"]}
        ent["link_history"].append({"t": b["t"], "identifier": b["identifier"],
                                    "co_with": [a["identifier"]], "windows": sorted(link["windows"]),
                                    "co_occurrences": len(link["cooc"])})
        return [{"change": "confirmed" if promoting else "linked", "entity_uuid": ent["entity_uuid"],
                 "entity": ent}]

    def _merge(self, ua, ub):
        if ua == ub:
            return self._entities[ua]
        a, b = self._entities[ua], self._entities[ub]
        keep, drop = (a, b) if len(a["identifiers"]) >= len(b["identifiers"]) else (b, a)
        for ident, rec in drop["identifiers"].items():
            keep["identifiers"].setdefault(ident, rec)
            self._ident_uuid[ident] = keep["entity_uuid"]
        for s, c in drop["source_breakdown"].items():
            keep["source_breakdown"][s] = keep["source_breakdown"].get(s, 0) + c
        for s, t in drop["first_seen"].items():
            keep["first_seen"][s] = min(keep["first_seen"].get(s, t), t)
        for s, t in drop["last_seen"].items():
            keep["last_seen"][s] = max(keep["last_seen"].get(s, t), t)
        keep["link_history"] += drop["link_history"]
        keep["recognition_links"] += drop["recognition_links"]
        keep["positions"] = sorted(keep["positions"] + drop["positions"], key=lambda p: p["t"])[-500:]
        keep["confirmation_score"] = max(keep["confirmation_score"], drop["confirmation_score"])
        if drop.get("demo"):
            keep["demo"] = True
        del self._entities[drop["entity_uuid"]]
        return keep


# ---------------------------------------------------------------- evidence export + history
def export_entity(entity, engagement_uuid=None, now=None):
    """The 'Export entity evidence' payload: the entity plus every evidence field, tagged for the
    reporting pipeline (and the engagement when one is active)."""
    now = time.time() if now is None else now
    return {"exported": now, "exported_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)),
            "engagement_uuid": engagement_uuid, "entity": _jsonable(entity)}


def historical_index(graphs):
    """Build an identifier -> {entity_uuid, session} index from prior-session graph dicts, for
    deterministic match-on-return. Later sessions win on a collision (most recent UUID)."""
    index = {}
    for g in sorted(graphs, key=lambda d: d.get("saved", 0)):
        session = g.get("session")
        for u, e in g.get("entities", {}).items():
            for ident in e.get("identifiers", {}):
                index[ident] = {"entity_uuid": u, "session": session}
    return index


def _jsonable(entity):
    """Entity copy with any set() fields (link windows) turned into sorted lists for JSON."""
    e = json.loads(json.dumps(entity, default=lambda o: sorted(o) if isinstance(o, set) else str(o)))
    return e


if __name__ == "__main__":
    g = EntityGraph(config={"promotion_n": 3, "promotion_m": 3})
    base = 1_000_000
    for w in range(3):                                 # 3 windows, 10 min apart, co-located
        t = base + w * 700
        for src, kind, raw in (("WiFi", "wifi", "AA:BB:CC:00:00:01"),
                               ("BLE", "ble", "d0:11:22:33:44:55"),
                               ("TPMS", "tpms", "TPMS-9001")):
            ev = g.ingest({"source": src, "identifier": "%s:%s" % (kind, raw), "kind": kind,
                           "t": t, "lat": 47.61, "lon": -122.33, "rssi": -50, "demo": True})
            for u in ev:
                print("  [%s] %s (%d identifiers)" % (u["change"], u["entity_uuid"],
                                                      len(u["entity"]["identifiers"])))
    for e in g.entities():
        print("entity", e["entity_uuid"], e["status"], "score", e["confirmation_score"],
              "sources", e["source_breakdown"])
