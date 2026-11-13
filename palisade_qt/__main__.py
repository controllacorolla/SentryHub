"""Run the PALISADE Qt Hub:  python3 -m palisade_qt [--demo] [--light]"""
import sys

from .shell import main

if __name__ == "__main__":
    sys.exit(main())
