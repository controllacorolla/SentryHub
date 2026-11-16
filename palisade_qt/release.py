"""What this release ships (v0.1 launch line, confirmed by the owner 2026-11-16).

v0.1 = CL1-CL5 + CL8. SWEEP (counter-surveillance) and tools that are not finished are hidden:
not on the strip, not on a number key, not in the command palette, not openable by name. Their
code stays in the tree for v0.2 (CL6/CL7). `PALISADE_SHOW_HIDDEN=1` shows them for development
and for their own tests; it is never set by the installer.
"""
import os

VERSION = "0.1"
HIDDEN_PAGES = frozenset({"SWEEP"})


def show_hidden():
    return os.environ.get("PALISADE_SHOW_HIDDEN") == "1"


def page_hidden(name):
    return name in HIDDEN_PAGES and not show_hidden()
