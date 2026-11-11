"""RtlLease handoff race (found on-device 2026-11-08): stopping readsb while it is
still opening the tuner wedges it for ~30 s and the next app gets
usb_claim_interface -6. These pin the fix."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import suite as S  # noqa: E402


class FakeSystemd:
    """Minimal readsb lifecycle: state, start time, scripted stop behaviour."""

    def __init__(self, state="active", up_s=60.0, stop_rc=(0, ""), exit_after=0.0):
        self.state = state
        self.t_active = time.monotonic() - up_s
        self.stop_rc = stop_rc
        self.exit_after = exit_after
        self.stop_called_at = None
        self.stops = 0

    def service_state(self, name):
        if self.stop_called_at is not None and self.state in ("active", "deactivating"):
            if time.monotonic() - self.stop_called_at >= self.exit_after:
                self.state = "inactive"
            else:
                self.state = "deactivating"
        return self.state if name == "readsb" else "inactive"

    def run(self, cmd, timeout=10):
        if "ActiveEnterTimestampMonotonic" in cmd:
            return 0, str(int(self.t_active * 1e6))
        return 0, ""

    def sudo_systemctl(self, action, name, timeout=20):
        if action == "stop":
            self.stops += 1
            self.stop_called_at = time.monotonic()
            self.stop_uptime = time.monotonic() - self.t_active
        return self.stop_rc


def _lease(monkeypatch, tmp_path, fake):
    monkeypatch.setattr(S, "LEASE_STATE", str(tmp_path / "lease.json"))
    monkeypatch.setattr(S, "adsb_device", lambda: "rtlsdr")
    monkeypatch.setattr(S, "sky_uses_rtl", lambda: False)
    monkeypatch.setattr(S.core, "pids_named", lambda n: [])
    monkeypatch.setattr(S.core, "service_state", fake.service_state)
    monkeypatch.setattr(S.core, "run", fake.run)
    monkeypatch.setattr(S.core, "sudo_systemctl", fake.sudo_systemctl)
    L = S.RtlLease("Test", log=lambda m: None)
    L.SETTLE_S, L.EXIT_WAIT_S = 0.6, 1.5
    return L


def test_waits_for_fresh_readsb_to_settle(monkeypatch, tmp_path):
    fake = FakeSystemd(up_s=0.1)          # readsb was *just* restarted
    L = _lease(monkeypatch, tmp_path, fake)
    L.acquire()
    assert fake.stops >= 1
    assert fake.stop_uptime >= 0.55        # stop was deferred past the settle window
    assert "readsb" in L.paused


def test_sudo_timeout_still_waits_for_exit(monkeypatch, tmp_path):
    fake = FakeSystemd(stop_rc=(1, "Command timed out"), exit_after=0.4)
    L = _lease(monkeypatch, tmp_path, fake)
    L.acquire()                            # must not raise: readsb did exit
    assert fake.state == "inactive"


def test_refuses_handoff_while_readsb_holds_radio(monkeypatch, tmp_path):
    fake = FakeSystemd(stop_rc=(1, "timed out"), exit_after=99)   # never exits
    L = _lease(monkeypatch, tmp_path, fake)
    try:
        L.acquire()
        raised = False
    except RuntimeError as e:
        raised = "still holding" in str(e)
    assert raised
    assert "readsb" in L.paused            # debt recorded so release() restores it


def test_deactivating_readsb_is_waited_on(monkeypatch, tmp_path):
    fake = FakeSystemd(state="deactivating", exit_after=0.3)
    fake.stop_called_at = time.monotonic()  # a stop from someone else is in flight
    L = _lease(monkeypatch, tmp_path, fake)
    L.acquire()
    assert fake.stops == 0 and fake.state == "inactive"


def test_two_workspaces_one_process_takeover(monkeypatch, tmp_path):
    """In the workstation every app shares one pid. When B takes the radio from A, A's
    late release() must not hand the dongle back to readsb underneath B."""
    fake = FakeSystemd()
    a = _lease(monkeypatch, tmp_path, fake)
    a.who = "Scanner"
    b = S.RtlLease("APRS", log=lambda m: None)
    b.SETTLE_S, b.EXIT_WAIT_S = 0.6, 1.5
    starts = []
    real = fake.sudo_systemctl
    monkeypatch.setattr(S.core, "sudo_systemctl",
                        lambda action, name, timeout=20: (starts.append((action, name)),
                                                          real(action, name, timeout))[1])
    a.acquire()
    b.acquire()                                   # same pid, different owner
    assert S.lease_holder()[0] == "APRS"
    a.release()                                   # A notices its pipeline died
    assert S.lease_holder()[0] == "APRS"          # B still owns it
    assert ("start", "readsb") not in starts      # plane map NOT restarted under B
    b.release()
    assert ("start", "readsb") in starts and S.lease_holder()[0] is None


def test_holder_is_asked_to_stop_and_plane_map_stays_paused(monkeypatch, tmp_path):
    """Radio manager: B asks, A's own stop runs (no decoder killed underneath it), A's
    release does not restart readsb, B's release does."""
    fake = FakeSystemd()
    a = _lease(monkeypatch, tmp_path, fake)
    a.who = "Scanner"
    b = S.RtlLease("APRS", log=lambda m: None)
    b.SETTLE_S, b.EXIT_WAIT_S = 0.6, 1.5
    starts = []
    real = fake.sudo_systemctl
    monkeypatch.setattr(S.core, "sudo_systemctl",
                        lambda action, name, timeout=20: (starts.append((action, name)),
                                                          real(action, name, timeout))[1])
    stopped = []
    a.on_preempt = lambda: (stopped.append(1), a.release())     # the app's Stop
    a.acquire()
    assert S.radio_holder() == "Scanner"
    assert S._yield_radio(b) == "Scanner" and stopped == [1]
    assert ("start", "readsb") not in starts and not a.held      # handed over, map still paused
    b.acquire()
    assert S.radio_holder() == "APRS" and "readsb" in b.paused
    assert S._yield_radio(b) is None                             # never asks itself
    b.release()
    assert ("start", "readsb") in starts and S.radio_holder() is None
    # a lease that yielded works normally the next time
    a.acquire()
    assert S.radio_holder() == "Scanner" and a.handover is False
    a.release()
    assert S.radio_holder() is None and S.lease_holder()[0] is None


def test_h4m_is_off_everywhere():
    assert S.core.H4M_ENABLED is False
    assert S.core.hackrf_status() == "absent"
    assert S.adsb_device() == "rtlsdr"
    s = S.core.load_settings()
    assert s["airband_device"] == "rtlsdr"
