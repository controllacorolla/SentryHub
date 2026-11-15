import os, sys
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0,"/Users/daltonhayes/SentryHub")
from palisade_qt.kit import topbar
orig=topbar.StatusSlot.set
def mut(self, word, shape, color, detail=""):
    orig(self, word, shape, color, detail)
    self.value.setText(word)      # mutation: paint ONLY the state word, never scope/owner
topbar.StatusSlot.set=mut
import pytest
sys.exit(pytest.main(["-q","-p","no:cacheprovider","/Users/daltonhayes/SentryHub/tests/test_cl1_screen.py"]))
