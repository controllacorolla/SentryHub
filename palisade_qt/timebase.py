"""One time base for every table (audit H19).

The top strip shows a Zulu (UTC) clock, so every time a page shows is UTC too and says so with a
trailing Z. Before CL4 the tables used local time under that Zulu clock.
"""
import time


def zulu(ts=None, secs=True):
    """'HH:MM:SSZ' (or 'HH:MMZ') in UTC for epoch ts (now if None)."""
    t = time.gmtime(time.time() if ts is None else ts)
    return time.strftime("%H:%M:%SZ" if secs else "%H:%MZ", t)


def age_text(seconds):
    """A short age: '42 s', '7 min', '3 h', '2 d'."""
    s = max(0, int(seconds))
    if s < 120:
        return "%d s" % s
    if s < 7200:
        return "%d min" % (s // 60)
    if s < 172800:
        return "%d h" % (s // 3600)
    return "%d d" % (s // 86400)
