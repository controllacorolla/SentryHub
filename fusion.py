#!/usr/bin/env python3
"""fusion.py — cross-band contact fusion (Phase 3d).

Different decoders see the same real-world thing on different bands: an aircraft shows up on
ADS-B (position), ACARS and VDL2 (datalink), all for one flight; a drone shows up on Remote ID
(BLE), and could also surface as a Wi-Fi/BLE MAC. This engine correlates those source contacts
into a single unified "card" so the map shows one marker with several source badges.

Correlation, strongest first:
  1. shared strong identifier — callsign / ICAO hex / UAS id / BLE addr / MMSI / flight
     (this also covers "frequency association": give the shared tag the same key on both sides)
  2. position + time proximity — same place within pos_tol_nm and time_tol_s

Pure: no Tk, no I/O. submit() a source-contact dict; contacts() returns the active unified cards.
"""
import time

import geo

# Identifier keys that, if equal and non-empty on two contacts, mean "same entity".
STRONG_KEYS = ("callsign", "icao", "hex", "uas_id", "ble_addr", "wifi_mac", "mmsi", "flight", "assoc")
# Fields copied onto the card when a source provides them (latest wins).
CARRY = ("lat", "lon", "alt_m", "speed_mps", "heading_deg", "callsign")


class FusionEngine:
    def __init__(self, pos_tol_nm=0.5, time_tol_s=30, stale_s=120):
        self.cards = []
        self.pos_tol_nm = pos_tol_nm
        self.time_tol_s = time_tol_s
        self.stale_s = stale_s
        self._n = 0

    def submit(self, contact, now=None):
        """Fold one source contact into the matching card (creating one if none matches)."""
        now = contact.get("ts") or now or time.time()
        card = self._match(contact, now)
        if card is None:
            self._n += 1
            card = {"id": "fused%d" % self._n, "sources": {}, "ids": {},
                    "first": now, "last": now, "lat": None, "lon": None}
            self.cards.append(card)
        self._merge(card, contact, now)
        return card

    def _match(self, contact, now):
        cids = {k: contact.get(k) for k in STRONG_KEYS if contact.get(k)}
        for card in self.cards:
            if now - card["last"] > self.stale_s:
                continue
            if any(card["ids"].get(k) == v for k, v in cids.items()):
                return card
        lat, lon = contact.get("lat"), contact.get("lon")
        if lat is not None and lon is not None:
            best, best_d = None, self.pos_tol_nm
            for card in self.cards:
                if now - card["last"] > self.time_tol_s or card.get("lat") is None:
                    continue
                # don't merge-by-proximity two contacts that carry conflicting strong ids
                if any(k in card["ids"] and k in contact and card["ids"][k] != contact[k]
                       for k in STRONG_KEYS):
                    continue
                d = geo.dist_nm(card["lat"], card["lon"], lat, lon)
                if d <= best_d:
                    best, best_d = card, d
            return best
        return None

    def _merge(self, card, contact, now):
        src = contact.get("source", "?")
        card["sources"][src] = contact
        for k in STRONG_KEYS:
            if contact.get(k):
                card["ids"][k] = contact[k]
        for k in CARRY:
            if contact.get(k) is not None:
                card[k] = contact[k]
        card["last"] = now
        card["badges"] = sorted(card["sources"].keys())
        card["label"] = (card["ids"].get("callsign") or card["ids"].get("flight")
                         or card["ids"].get("icao") or card["ids"].get("uas_id")
                         or card["ids"].get("mmsi") or card["ids"].get("ble_addr") or card["id"])

    def contacts(self, now=None):
        now = time.time() if now is None else now
        return [c for c in self.cards if now - c["last"] <= self.stale_s]

    def prune(self, now=None):
        now = time.time() if now is None else now
        self.cards = [c for c in self.cards if now - c["last"] <= self.stale_s]
