"""Mutation check: break one fix in a copy of the working tree, run the named test, expect FAIL."""
import os, shutil, subprocess, sys
REPO = "/Users/daltonhayes/SentryHub"
SP = "/private/tmp/claude-501/-Users-daltonhayes-SentryHub/f893c360-320b-4c7c-9dc4-e3ab8ef11055/scratchpad"
PY = SP + "/venv312/bin/python"
MUTS = [
 ("rail-returns", "palisade_qt/shell.py",
  "        self.stack = QtWidgets.QStackedWidget()\n        vbox.addWidget(self.stack, 1)",
  "        self.stack = QtWidgets.QStackedWidget()\n        _h = QtWidgets.QHBoxLayout(); _r = QtWidgets.QFrame(); _r.setFixedWidth(150); _h.addWidget(_r); _h.addWidget(self.stack, 1); vbox.addLayout(_h, 1)",
  "test_cl1_fix.py::test_no_rail_the_page_starts_at_the_window_edge"),
 ("no-wrap", "palisade_qt/kit/components.py",
  "            val.setWordWrap(True)", "            val.setWordWrap(False)",
  "test_cl1_fix.py::test_detail_values_wrap_instead_of_widening"),
 ("horizontal-rail", "palisade_qt/kit/subtabs.py",
  "self._lay = QtWidgets.QVBoxLayout(self)", "self._lay = QtWidgets.QHBoxLayout(self)",
  "test_cl1_fix.py::test_sub_tabs_are_a_vertical_rail_left_of_the_page"),
 ("no-r-key", "palisade_qt/shell.py", '        if low == "r":', '        if low == "r-disabled":',
  "test_cl1_fix.py::test_r_e_m_keys_and_panic_with_a_panel_open"),
 ("panic-dead-with-panel", "palisade_qt/shell.py",
  "        did = []\n        try:\n            import txguard",
  "        did = []\n        if self.top_overlay() is not None:\n            return did\n        try:\n            import txguard",
  "test_cl1_fix.py::test_r_e_m_keys_and_panic_with_a_panel_open"),
 ("no-bracket", "palisade_qt/prowl.py", '        elif self._submode == "FM" and text in "[]":',
  '        elif self._submode == "FM-x" and text in "[]":',
  "test_cl1_fix.py::test_bracket_keys_step_prowl_scan_bank_and_fm_frequency"),
 ("detectors-never-start", "palisade_qt/sweep.py", "            w.start()\n", "            pass\n",
  "test_cl1_fix.py::test_detectors_start_when_sweep_opens_and_not_before"),
 ("armed-green", "palisade_qt/kit/topbar.py",
  '            self.slots["tx"].set("ARMED", "square", t["alert"])',
  '            self.slots["tx"].set("ARMED", "square", t["live"])',
  "test_cl1_fix.py::test_armed_and_active_slots_are_never_green"),
 ("active-green", "palisade_qt/kit/topbar.py",
  '            self.slots["engagement"].set(scope or "ACTIVE", "diamond", t["warn"])',
  '            self.slots["engagement"].set(scope or "ACTIVE", "diamond", t["live"])',
  "test_cl1_fix.py::test_armed_and_active_slots_are_never_green"),
 ("ops-card-empty", "palisade_qt/ops.py", "        shown = sorted(items, key=lambda a: a[\"acked\"])[:4]",
  "        shown = []", "test_cl1_fix.py::test_ops_alert_card_shows_newest_unacknowledged_alerts"),
 ("babel-dark-colours", "palisade_qt/babel.py", '"AIS": "#4DA6FF"', '"AIS": "#203040"',
  "test_cl1_fix.py::test_babel_protocol_colours_are_readable"),
 ("panic-clears-permit", "palisade_qt/shell.py",
  "        # PANIC has no API to revoke", "        chrome.reset()\n        # PANIC has no API to revoke",
  "test_cl1_fix.py::test_panic_leaves_tx_slot_on_the_real_bench_gate_and_says_ack_not_revoked"),
 ("caption-13", "palisade_qt/theme.py", "FONT_CAPTION = 16", "FONT_CAPTION = 13",
  "test_cl1_fix.py::test_rendered_text_is_16px_or_more_everywhere_including_captions_headers_and_plots"),
 ("header-10", "palisade_qt/theme.py", "QHeaderView {{ font-size: {status}px; }}", "QHeaderView {{ font-size: 10px; }}",
  "test_cl1_fix.py::test_rendered_text_is_16px_or_more_everywhere_including_captions_headers_and_plots"),
 ("axis-9", "palisade_qt/kit/scope.py", "tick_font.setPixelSize(16)", "tick_font.setPixelSize(9)",
  "test_cl1_fix.py::test_rendered_text_is_16px_or_more_everywhere_including_captions_headers_and_plots"),
 ("ops-ghost-rows", "palisade_qt/ops.py", "                w.hide()\n                w.setParent(None)\n", "",
  "test_cl1_fix.py::test_ops_alert_card_shows_newest_unacknowledged_alerts"),
 ("card-never-collapses", "palisade_qt/kit/components.py",
  "        self._outer.setStretch(0, 0 if empty else 1)\n        self._outer.setStretch(1, 1 if empty else 0)\n",
  "        self._outer.setStretch(0, 1)\n        self._outer.setStretch(1, 0)\n        self.box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)\n",
  "test_cl1_fix.py::test_empty_detail_cards_collapse_in_live_pages"),
]
only = sys.argv[1:]
res = []
for name, path, old, new, test in MUTS:
    if only and name not in only:
        continue
    d = os.path.join(SP, "cl1fix", "mut", name)
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(REPO, d, ignore=shutil.ignore_patterns(".git", ".claude", "*.png", "__pycache__",
                                                           "CL1-reaudit-evidence"))
    f = os.path.join(d, path)
    s = open(f).read()
    if old not in s:
        res.append((name, "MUTATION NOT APPLIED"))
        continue
    open(f, "w").write(s.replace(old, new, 1))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    p = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", "tests/" + test],
                       cwd=d, capture_output=True, text=True, env=env, timeout=600)
    last = (p.stdout.strip().splitlines() or ["?"])[-1]
    res.append((name, "KILLED" if p.returncode != 0 else "SURVIVED", last))
    shutil.rmtree(d, ignore_errors=True)
for r in res:
    print(" | ".join(r))
