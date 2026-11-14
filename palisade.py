#!/usr/bin/env python3
"""PALISADE — Qt launcher.

    python3 palisade.py            # dark, live (needs rtl_power etc. for real data)
    python3 palisade.py --demo     # synthetic feeds, no hardware
    python3 palisade.py --light    # light theme

Needs PySide6 + pyqtgraph + numpy (see requirements). The legacy Tk hub (hub.py) stays runnable
during migration; this is the Qt shell with the 9 callsigns as embedded pages.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palisade_qt.shell import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
