"""Regression tests for bugs fixed in doctor.py during the code audit."""
import sys

import doctor as D

REAL = """Matching Defaults entries for dragon on raspberrypi:
    env_reset, mail_badpass, secure_path=/usr/local/sbin\\:/usr/bin

User dragon may run the following commands on raspberrypi:
    (ALL : ALL) ALL
    (root) NOPASSWD: /usr/bin/systemctl start readsb, /usr/bin/systemctl stop readsb
    (root) NOPASSWD: /usr/bin/systemctl start readsb, /bin/systemctl stop readsb
"""


def test_sudoers_scope_from_sudo_l_listing_ok():
    ok, detail, _ = D.chk_sudoers_scope(REAL)
    assert ok is True, detail          # password-protected (ALL) ALL is not a NOPASSWD grant


def test_sudoers_scope_flags_broad_nopasswd():
    broad = REAL + "    (root) NOPASSWD: /usr/bin/systemctl *\n    (root) NOPASSWD: ALL\n"
    ok, detail, _ = D.chk_sudoers_scope(broad)
    assert ok is False and "systemctl *" in detail


def test_sdcard_check_sees_nvme_root_ro_and_ignores_remount_ro(tmp_path):
    m = tmp_path / "mounts"
    m.write_text("/dev/root / ext4 rw,noatime 0 0\n"
                 "/dev/nvme0n1p1 /boot/firmware vfat rw,relatime,errors=remount-ro 0 0\n")
    assert D.chk_sdcard(str(m))[0] is True      # was a false READ-ONLY on mmcblk layouts
    m.write_text("/dev/root / ext4 ro,noatime 0 0\n")
    assert D.chk_sdcard(str(m))[0] is False     # was invisible: /dev/root isn't mmcblk


def test_py_check_does_not_import_the_package(tmp_path, monkeypatch):
    (tmp_path / "heavy_pkg_probe.py").write_text("raise RuntimeError('imported!')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert D._py("heavy_pkg_probe") is True
    assert "heavy_pkg_probe" not in sys.modules
    assert D._py("no_such_pkg_xyz") is False
