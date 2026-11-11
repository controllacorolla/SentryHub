"""An ISS element set for offline tests: the published 2008 ISS TLE with its epoch moved
to 'now' and checksums recomputed. Real ISS orbit shape, NOT real pass times."""
import time


def _ck(line):
    return str(sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in line[:68]) % 10)


def iss_tle(now=None):
    t = time.gmtime(now or time.time())
    epoch = "%02d%012.8f" % (t.tm_year % 100, t.tm_yday + (t.tm_hour * 3600 + t.tm_min * 60) / 86400.0)
    l1 = "1 25544U 98067A   %s -.00002182  00000-0 -11606-4 0  292" % epoch
    l2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.7212539156353"
    l1, l2 = l1[:68], l2[:68]
    return "ISS (ZARYA)\n%s%s\n%s%s\n" % (l1, _ck(l1), l2, _ck(l2))
