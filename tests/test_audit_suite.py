"""Regression tests for bugs fixed in suite.py during the code audit."""
import socket

import suite as S


class _FakeSock:
    def __init__(self, chunks=(), exc=None):
        self.chunks, self.exc, self.closed = list(chunks), exc, False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def sendall(self, b):
        pass

    def settimeout(self, t):
        pass

    def recv(self, n):
        if self.exc:
            raise self.exc
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


def test_gps_fix_closes_socket_on_recv_timeout(monkeypatch):
    sk = _FakeSock(exc=socket.timeout("timed out"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: sk)
    assert S.gps_fix(timeout=0.2) is None
    assert sk.closed, "socket leaked when recv() timed out"


def test_gps_fix_ignores_non_object_json(monkeypatch):
    sk = _FakeSock([b'1\n"x"\n{"class":"TPV","mode":3,"lat":39.6,"lon":-104.8}\n'])
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: sk)
    m = S.gps_fix(timeout=0.5)
    assert m and m["lat"] == 39.6
    assert sk.closed
