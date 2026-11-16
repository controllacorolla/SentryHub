"""E3 on Linux/BlueZ (the uConsole's backend) with bleak installed: does the passive DRONES scan run?"""
import time

import _harness as H
import bleak  # noqa: F401
from importlib.metadata import version
from palisade_qt.atlas import RidSource

r = RidSource(on_fault=lambda m: H.log("FAULT surfaced:", m))
r.start()
time.sleep(2.0)
H.log("bleak %s ; RidSource.state=%s" % (version("bleak"), r.state))
r.stop()
