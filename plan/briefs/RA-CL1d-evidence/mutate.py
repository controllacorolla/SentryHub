"""RA-CL1d mutations against tests/test_cl1_fix3.py. usage: mutate.py <scratch worktree at 91d5870> <python>"""
import subprocess, sys, os
WT, PY = sys.argv[1], sys.argv[2]
M = {
 "m16_no_viewport_refit": ("palisade_qt/kit/feed.py", "            self._fit.start()\n        return super().eventFilter", "            pass\n        return super().eventFilter", "test_feed_table_refits"),
 "f1_old_side_ring": ("palisade_qt/theme.py", "border-width: {bw} {bw} {focus_under} {bw}; border-radius: 0; }}\nQPushButton.navkey_on {{", "border-width: {bw} {focus_w} {focus_under} {focus_w}; border-radius: 0; }}\nQPushButton.navkey_on {{", "test_nav_key_focus_cue"),
 "f1_old_side_ring_coloured": ("palisade_qt/theme.py", "border-color: {focus} transparent;\n                            border-width: {bw} {bw} {focus_under} {bw};", "border-color: {focus};\n                            border-width: {bw} {focus_w} {bw} {focus_w};", "test_nav_key_focus_cue"),
 "f1_on_side_ring": ("palisade_qt/theme.py", "border-color: {focus_on} {accent};\n                               border-width: {bw} {bw} {focus_under} {bw};", "border-color: {focus_on} {accent};\n                               border-width: {bw} {focus_w} {focus_under} {focus_w};", "test_nav_key_focus_cue"),
 "f1_no_cue": ("palisade_qt/theme.py", "border-color: {focus} transparent;", "border-color: transparent transparent;", "test_nav_key_focus_cue"),
 "f1_thick_under_sun": ("palisade_qt/theme.py", '"focus_on": "#FFFFFF", "focus_under": "3px"', '"focus_on": "#FFFFFF", "focus_under": "6px"', "test_nav_key_focus_cue"),
 "f2_no_cap": ("palisade_qt/chrome.py", "    if len(scope) > SCOPE_MAX:", "    if False:", "scope_summary_caps or test_strip_fits"),
 "f2_long_cap": ("palisade_qt/chrome.py", 'return "%d+ tgts" % SCOPE_MAX', 'return "%d+ targets" % SCOPE_MAX', "scope_summary_caps or test_strip_fits"),
 "f4_no_lost": ("palisade_qt/atlas.py", "            self._show_lost()\n", "            pass\n", "vanished"),
 "f4_lost_keeps_rows": ("palisade_qt/atlas.py", '        self.detail.set_rows([("STATUS", "LOST")])\n', "", "vanished"),
 "f4_lost_label_only": ("palisade_qt/atlas.py", '"LOST · no longer reported"', '"aircraft"', "vanished"),
}
for name, (f, old, new, k) in M.items():
    p = os.path.join(WT, f); src = open(p).read()
    assert src.count(old) == 1, (name, src.count(old))
    open(p, "w").write(src.replace(old, new))
    try:
        r = subprocess.run([PY, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "tests/test_cl1_fix3.py", "-k", k],
                           cwd=WT, capture_output=True, text=True, env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        tail = r.stdout.strip().splitlines()[-1]
        print("%-22s %s   (%s)" % (name, "CAUGHT" if r.returncode else "SURVIVED", tail))
    finally:
        open(p, "w").write(src)
