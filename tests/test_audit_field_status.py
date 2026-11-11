"""Regression tests for bugs fixed in field_status.py during the code audit."""
import socket

import field_status as FS


class FakeSock:
    def __init__(self, seq):
        self.seq = list(seq)

    def recv(self, n):
        v = self.seq.pop(0) if self.seq else b""
        if isinstance(v, Exception):
            raise v
        return v


def test_quiet_gpsd_is_waiting_not_dead(monkeypatch):
    monkeypatch.setitem(FS.GPS, "state", "waiting")
    FS.gps_read(FakeSock([socket.timeout(), socket.timeout()]))
    assert FS.GPS["state"] == "waiting"


def test_non_object_json_does_not_kill_reader(monkeypatch):
    monkeypatch.setitem(FS.GPS, "state", "waiting")
    FS.gps_read(FakeSock([b'[1,2]\n42\n{"class":"TPV","mode":3,"lat":39.6}\n']))
    assert FS.GPS["state"] == "fix" and FS.GPS["tpv"]["lat"] == 39.6


def test_throttled_survives_odd_vcgencmd_output(monkeypatch):
    monkeypatch.setattr(FS.shutil, "which", lambda n: "/usr/bin/vcgencmd")
    monkeypatch.setattr(FS.S, "run", lambda cmd, timeout=0: (0, "throttled=garbage"))
    assert FS.throttled() is None
