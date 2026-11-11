import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import doctor as D  # noqa: E402
import suite as S  # noqa: E402


def fake_run(enabled=(), installed=("akrex-kernel",), held=()):
    def run(cmd, timeout=10):
        if cmd[:2] == ["systemctl", "is-enabled"]:
            return 0, "enabled" if cmd[2] in enabled else "disabled"
        if cmd[0] == "dpkg-query":
            return 0, "\n".join("%s install ok installed" % p for p in installed)
        if cmd[:2] == ["apt-mark", "showhold"]:
            return 0, "\n".join(held)
        return 1, ""
    return run


def test_updates_check_flags_the_configuration_that_bricked_the_device():
    ok, txt, fix = D.chk_updates(run=fake_run(enabled=("unattended-upgrades",)))
    assert ok is False and "not held" in txt and "apt-mark hold akrex-kernel" in fix
    ok, txt, _ = D.chk_updates(run=fake_run(held=("akrex-kernel",)))
    assert ok is True
    ok, txt, fix = D.chk_updates(run=fake_run())
    assert ok is None and "apt-mark hold" in fix
    ok, txt, _ = D.chk_updates(run=fake_run(enabled=("apt-daily-upgrade.timer",), held=("akrex-kernel",)))
    assert ok is None and "automatic updates are ON" in txt
    assert D.chk_updates(run=fake_run(installed=()))[0] is True      # not a uConsole kernel


def test_bootfiles_check(tmp_path):
    b = tmp_path / "fw"
    b.mkdir()
    m = tmp_path / "mounts"
    m.write_text("/dev/nvme0n1p2 / ext4 rw 0 0\n/dev/nvme0n1p1 %s vfat rw 0 0\n" % b)
    for f in ("config.txt", "cmdline.txt", "kernel8.img", "kernel_2712.img"):
        (b / f).write_text("x")
    assert D.chk_bootfiles(str(b), str(m))[0] is True
    (b / "kernel8.img.dpkg-new").write_text("x")                     # interrupted kernel install
    ok, txt, fix = D.chk_bootfiles(str(b), str(m))
    assert ok is False and "dpkg-new" in txt and "DO NOT reboot" in fix
    (b / "kernel8.img.dpkg-new").unlink()
    (b / "kernel8.img").write_text("")                               # zero-byte kernel
    assert D.chk_bootfiles(str(b), str(m))[0] is False
    (b / "kernel8.img").write_text("x")
    m.write_text("/dev/nvme0n1p2 / ext4 rw 0 0\n/dev/mmcblk0p1 %s vfat rw 0 0\n" % b)
    ok, txt, _ = D.chk_bootfiles(str(b), str(m))                     # card boot, NVMe root
    assert ok is None and "mmcblk0p1" in txt
    assert D.chk_bootfiles(str(tmp_path / "nope"))[0] is None


def test_doctor_has_no_h4m_rows():
    names = [n for _, rows in D.CHECKS for n, _ in rows]
    assert "H4M" not in names and "System updates" in names and "Boot files" in names


def test_acquire_waits_for_async_holder(monkeypatch, tmp_path):
    """Sky stops its scanner on a worker thread: the next app must wait for that release."""
    import threading
    monkeypatch.setattr(S, "LEASE_STATE", str(tmp_path / "lease.json"))
    monkeypatch.setattr(S, "adsb_device", lambda: "rtlsdr")
    monkeypatch.setattr(S, "sky_uses_rtl", lambda: False)
    monkeypatch.setattr(S.core, "pids_named", lambda n: [])
    monkeypatch.setattr(S.core, "service_state", lambda n: "inactive")
    a, b = S.RtlLease("Sky airband", log=lambda m: None), S.RtlLease("APRS", log=lambda m: None)
    a.acquire()
    order = []
    a.on_preempt = lambda: threading.Timer(0.4, lambda: (order.append("a released"), a.release())).start()

    pending = []

    class Root:                                   # a stand-in Tk loop: queue, then pump
        def after(self, ms, fn, *args):
            pending.append((fn, args))
    done = threading.Event()
    S.acquire_bg(Root(), b, lambda ok, v: (order.append("b acquired"), done.set()))
    t0 = time.time()
    while not done.is_set() and time.time() - t0 < 5:
        time.sleep(0.02)
        for fn, args in [pending.pop(0) for _ in range(len(pending))]:
            fn(*args)
    assert order == ["a released", "b acquired"] and S.radio_holder() == "APRS"
    b.release()
