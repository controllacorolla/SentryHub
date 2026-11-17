"""The one offscreen/offline check (C5: it was copied into nine modules).

Under tests/CI (QT_QPA_PLATFORM=offscreen) or with PALISADE_OFFLINE set, the device seams (radio
pipelines, scans, tile fetches) open nothing. Read at call time, so a test can open a seam by
changing the environment. Removing these seams from production code is CL9 (T1).
"""
import os


def offscreen():
    return bool(os.environ.get("PALISADE_OFFLINE") or
                os.environ.get("QT_QPA_PLATFORM") == "offscreen")
