"""Regression tests for bugs fixed in signals.py during the code audit."""
import time

import signals as G


def test_default_acars_cmd_uses_acarsdec4_cli_and_json():
    argv = G.build_argv(dict(G.DEFAULTS, source="acars", gain=40))
    assert argv[0] == "acarsdec"
    assert "-o" not in argv and "-r" not in argv          # 3.x options, rejected by v4
    assert "--rtlsdr" in argv and "--output" in argv
    assert argv[argv.index("--output") + 1].startswith("json:")


def test_acars_json_line_parses():
    d = G.parse_acars('{"tail":".N123AB","flight":"UA0123","label":"H1","text":"HELLO"}')
    assert d["flight"] == "UA0123" and d["text"] == "HELLO"


def test_vdl2_default_has_no_duplicate_channel():
    argv = G.build_argv(dict(G.DEFAULTS, source="vdl2", gain=40))
    freqs = [a for a in argv if a.isdigit() and len(a) == 9]
    assert len(freqs) == len(set(freqs)) and "136700000" in freqs


def test_migrate_upgrades_only_old_verbatim_defaults():
    s = dict(G.DEFAULTS, acars_cmd=G.OLD_DEFAULTS["acars_cmd"][0])
    assert G.migrate(s) and s["acars_cmd"] == G.DEFAULTS["acars_cmd"]
    custom = dict(G.DEFAULTS, acars_cmd="acarsdec --my-own-flags {freqs}")
    assert not G.migrate(custom) and custom["acars_cmd"] == "acarsdec --my-own-flags {freqs}"


class FailLease:
    def __init__(self):
        self.events = []

    def acquire(self, keep=()):
        self.events.append("acquire")
        raise RuntimeError("readsb is still holding the SDR")

    def release(self):
        self.events.append("release")


def test_decoder_releases_lease_when_acquire_fails():
    st = []
    d = G.Decoder(lambda l: None, lambda k, m: st.append(k))
    d.lease = FailLease()
    d.start(["true"])
    # the release must come AFTER the failed acquire (which may have paused readsb),
    # and start() must not bounce readsb with a release before acquiring
    assert d.lease.events == ["acquire", "release"]
    assert "error" in st and d.proc is None


class OkLease:
    def __init__(self):
        self.released = 0

    def acquire(self, keep=()):
        pass

    def release(self):
        self.released += 1


def test_decoder_survives_non_utf8_output():
    lines, st = [], []
    d = G.Decoder(lines.append, lambda k, m: st.append(k))
    d.lease = OkLease()
    d.start(["printf", "ok\\n\\xff\\xfe bad bytes\\nafter\\n"])
    end = time.time() + 5
    while "stopped" not in st and "error" not in st and time.time() < end:
        time.sleep(0.05)
    assert "after" in lines, "reader thread died on a bad byte"
    assert d.lease.released >= 1
