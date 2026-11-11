"""Shared pytest setup for the uConsole suite.

These tests cover the pure, display-free logic: parsers, the SDR-lease-free helpers,
power status, backup/restore, the session log, the Wi-Fi detector, TFR filtering, and
the sitrep template. Anything needing a live radio, gpsd, or a Tk display is out of scope.
"""
import os
import sys

# the suite modules live one level up from tests/
SUITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)
