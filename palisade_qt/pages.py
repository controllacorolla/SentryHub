"""The composite pages of the 8-key structure (CL1 / D7).

Each is assembled from existing apps, moved mechanically — every worker keeps its owner class and
its behaviour; only the page that hosts it changed:

  ATLAS  (2 · map)       MAP <- AtlasApp · SKY DOME, PASSES <- OverwatchApp (OVERWATCH retired as a page)
  PROWL  (4 · listen)    SCAN, FM, NWR <- ProwlApp · DECODE <- BabelApp (BABEL folded in)
  SYSTEM (7 · settings)  SETTINGS, DOCTOR, SITREP <- MoreApp · BENCH <- BenchApp
  ASSISTANT (8), MESH (9) are pages of their own since 2026-11-17 (system.AssistantApp / mesh.MeshPage)
"""
from .app import CompositeApp
from .atlas import AtlasApp
from .overwatch import OverwatchApp
from .prowl import ProwlApp
from .babel import BabelApp
from .system import MoreApp
from .bench_app import BenchApp


class AtlasPage(CompositeApp):
    TITLE = "ATLAS"
    PARTS = ((AtlasApp, (("MAP", None),)),
             (OverwatchApp, (("SKY DOME", "SKY DOME"), ("PASSES", "PASSES"))))


class ProwlPage(CompositeApp):
    TITLE = "PROWL"
    PARTS = ((ProwlApp, (("SCAN", "SCAN"), ("FM", "FM"), ("NWR", "NWR"))),
             (BabelApp, (("DECODE", None),)))

    def tune_fm(self, mhz):
        self.switch_subtab("FM")
        self.child(ProwlApp).tune_fm(mhz)


class SystemPage(CompositeApp):
    TITLE = "SYSTEM"
    PARTS = ((MoreApp, (("SETTINGS", "SETTINGS"), ("DOCTOR", "DOCTOR"), ("SITREP", "SITREP"))),
             (BenchApp, (("BENCH", None),)))
