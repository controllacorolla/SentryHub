"""Mutation list: id -> list of (file, old, new[, count])."""
P = "palisade_qt/"
M = {}

# ---------------- D1
M["d1_detail_nowrap_widen"] = [(P + "kit/components.py",
    "            val.setWordWrap(True)\n            val.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)\n",
    "            val.setWordWrap(False)\n")]
M["d1_detail_clip_not_wrap"] = [(P + "kit/components.py",
    "            val.setWordWrap(True)\n            val.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)\n",
    "            val.setWordWrap(False)\n            val.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)\n")]
M["d1_bench_gate_in_bar"] = [
    (P + "bench_app.py", "        ackrow.addWidget(self.ack)\n", "        self.bar.lay.addWidget(self.ack)\n"),
    (P + "bench_app.py", "        ackrow.addWidget(self.gate)\n", "        self.bar.lay.addWidget(self.gate)\n")]
M["d1_skydome_360"] = [(P + "overwatch.py", "self.setMinimumSize(160, 160)", "self.setMinimumSize(360, 360)")]
M["d1_sstv_240"] = [(P + "babel.py", "self.view.setMinimumHeight(80)", "self.view.setMinimumHeight(240)")]
M["d1_strip_64"] = [(P + "kit/topbar.py", "STRIP_H = 40\n", "STRIP_H = 64\n")]
M["d1_left_rail_back_renamed"] = [(P + "shell.py", "        vbox.addWidget(self.stack, 1)\n",
    "        _h = QtWidgets.QHBoxLayout()\n        _r = QtWidgets.QFrame()\n        _r.setFixedWidth(150)\n"
    "        _h.addWidget(_r)\n        _h.addWidget(self.stack, 1)\n        vbox.addLayout(_h, 1)\n")]
M["d1_footer_back_renamed"] = [(P + "shell.py", "        vbox.addWidget(self.stack, 1)\n",
    "        vbox.addWidget(self.stack, 1)\n        _f = QtWidgets.QFrame()\n        _f.setFixedHeight(40)\n        vbox.addWidget(_f)\n")]

# ---------------- D2
M["d2_status_13"] = [(P + "theme.py", "FONT_STATUS = 16\n", "FONT_STATUS = 13\n")]
M["d2_body_14"] = [(P + "theme.py", "FONT_BODY = 18\n", "FONT_BODY = 14\n")]
M["d2_note_12"] = [(P + "theme.py", "QLabel.note   {{ color: {muted}; font-size: {status}px; }}", "QLabel.note   {{ color: {muted}; font-size: 12px; }}")]
M["d2_slotval_11"] = [(P + "theme.py", "QLabel.slotval {{ color: {text}; font-size: {status}px;", "QLabel.slotval {{ color: {text}; font-size: 11px;")]
M["d2_header_10"] = [(P + "theme.py", "border-bottom: {bw} solid {hairline}; padding: 6px 8px;\n                        font-size: {status}px; }}",
                      "border-bottom: {bw} solid {hairline}; padding: 6px 8px;\n                        font-size: 10px; }}")]
M["d2_table_12"] = [(P + "theme.py", "alternate-background-color: {row_alt}; font-size: {body}px;", "alternate-background-color: {row_alt}; font-size: 12px;")]
M["d2_rowh_24"] = [(P + "theme.py", "ROW_H = 40\n", "ROW_H = 24\n")]
M["d2_scope_tick_10"] = [(P + "kit/scope.py", "tick_font.setPixelSize(16)", "tick_font.setPixelSize(10)")]
M["d2_map_labels_10"] = [(P + "kit/mappanel.py", "_f.setPixelSize(16)", "_f.setPixelSize(10)", 3)]
M["d2_ppi_label_10"] = [(P + "kit/ppi.py", "_f.setPixelSize(16)", "_f.setPixelSize(9)")]
M["d2_scale_not_called_in_main"] = [(P + "shell.py", "        theme.configure_scale(os.environ)      # must run before the QApplication exists\n", "        pass\n")]
M["d2_navcall_11"] = [(P + "theme.py", "QLabel.navcall {{ color: {text}; font-size: {status}px;", "QLabel.navcall {{ color: {text}; font-size: 11px;")]
M["d2_pstat_11"] = [(P + "theme.py", "QLabel.pstat {{ color: {muted}; font-size: {status}px; }}", "QLabel.pstat {{ color: {muted}; font-size: 11px; }}")]
M["d2_button_12"] = [(P + "theme.py", "padding: 5px 12px; color: {text}; font-size: {status}px; min-height: 26px; }}", "padding: 5px 12px; color: {text}; font-size: 12px; min-height: 26px; }}")]
M["d2_clock_11"] = [(P + "theme.py", "QLabel#dtg {{ color: {text}; font-size: {status}px; }}", "QLabel#dtg {{ color: {text}; font-size: 11px; }}")]

# ---------------- D3
M["d3_subtabs_horizontal_row"] = [
    (P + "app.py", "            mid.addWidget(self._rail)\n", "            root.addWidget(self._rail)\n"),
    (P + "kit/subtabs.py", "self._lay = QtWidgets.QVBoxLayout(self)", "self._lay = QtWidgets.QHBoxLayout(self)"),
    (P + "kit/subtabs.py", "self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)",
     "self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)")]
M["d3_focus_rule_invisible"] = [(P + "theme.py", "QPushButton:focus {{ border: {focus_w} solid {focus}; }}", "QPushButton:focus {{ border: {bw} solid {hairline}; }}"),
                                (P + "theme.py", "QTableView:focus {{ border: {focus_w} solid {focus}; }}", "QTableView:focus {{ border: {bw} solid transparent; }}")]
M["d3_checked_invisible"] = [(P + "theme.py", "QPushButton:checked {{ background: {check_bg}; color: {check_fg}; border: {bw} solid {accent};\n                       font-weight: 600; }}",
                              "QPushButton:checked {{ background: {p2}; }}")]

# ---------------- D4
M["d4_page_writes_slot"] = [(P + "app.py", "        self._last_status[key] = {\"text\": text, \"state\": state, \"ok\": ok}\n",
    "        self._last_status[key] = {\"text\": text, \"state\": state, \"ok\": ok}\n"
    "        _w = self.window()\n"
    "        if hasattr(_w, \"topbar\") and key in (\"sdr\", \"tx\"):\n"
    "            _w.topbar.slots[\"mode\" if key == \"sdr\" else \"tx\"].set(text or \"\", \"dot\", \"#ffffff\")\n")]
M["d4_tx_ignores_txguard"] = [(P + "chrome.py", "        if txguard.is_armed():\n", "        if False and txguard.is_armed():\n")]
M["d4_eng_always_none"] = [(P + "chrome.py", "    if not info.get(\"active\"):\n", "    if True:\n")]
M["d4_radio_signal_unwired"] = [(P + "chrome.py", "        radio_arbiter.arbiter.changed.connect(self._on_radio)\n", "        pass\n")]
M["d4_topbar_armed_shows_off"] = [(P + "kit/topbar.py", "        if tx == \"ARMED\":\n", "        if tx == \"ARMEDX\":\n")]
M["d4_bench_tx_safe_back"] = [(P + "bench_app.py", "\"▲ TX PERMITTED · conducted\"", "\"▲ TX SAFE · conducted\"")]
M["d4_bench_no_permit_report"] = [(P + "bench_app.py", "        chrome.report_tx_permit(\"BENCH\", ok)", "        pass")]
M["d4_no_demo_border"] = [(P + "shell.py", "self.demo_border = panels.DemoBorder(mode, central) if demo else None", "self.demo_border = None")]
M["d4_demo_border_paints_nothing"] = [(P + "panels.py", "        p = QtGui.QPainter(self)\n        w, h, b = self.width(), self.height(), self.WIDTH\n",
                                       "        return\n        p = QtGui.QPainter(self)\n        w, h, b = self.width(), self.height(), self.WIDTH\n")]
M["d4_mode_slot_live_in_demo"] = [(P + "chrome.py", "self.mode = \"DEMO\" if demo else \"LIVE\"", "self.mode = \"LIVE\"")]
M["d4_disabled_not_dashed"] = [(P + "theme.py", "QPushButton:disabled {{ color: {disabled}; border: {bw} dashed {disabled}; background: transparent; }}",
                                "QPushButton:disabled {{ color: {text}; border: {bw} solid {hairline}; }}")]
M["d4_slot_visible_text_blank"] = [(P + "kit/topbar.py", "        self.value.setText(text)\n", "        self.value.setText(\"\")\n")]
M["d4_glyph_paints_nothing"] = [(P + "kit/topbar.py", "    def paintEvent(self, ev):\n        p = QtGui.QPainter(self)\n        p.setRenderHint(QtGui.QPainter.Antialiasing)\n        col = QtGui.QColor(self._color)",
                                 "    def paintEvent(self, ev):\n        return\n        p = QtGui.QPainter(self)\n        p.setRenderHint(QtGui.QPainter.Antialiasing)\n        col = QtGui.QColor(self._color)")]
M["d4_no_poll_timer"] = [(P + "chrome.py", "        self._timer.start(poll_ms)\n", "        pass\n")]
M["d4_shell_ignores_state_changes"] = [(P + "shell.py", "        self.state.changed.connect(self._on_state)\n", "        pass\n")]
M["d4_permit_hides_armed"] = [(P + "chrome.py", "    return \"PERMITTED\" if _permits else \"OFF\"", "    return \"OFF\"")]

# ---------------- D7
M["d7_children_always_active"] = [(P + "app.py", "c.set_active(bool(self._active and c is cur))", "c.set_active(True)")]
M["d7_navlabel_hidden"] = [(P + "kit/topbar.py", "        self.setToolTip(\"%d — %s: %s\" % (number, callsign, label))\n",
                            "        self.setToolTip(\"%d — %s: %s\" % (number, callsign, label))\n        self.label.setVisible(False)\n")]

# ---------------- D8
S = P + "shell.py"
M["d8_no_digits"] = [(S, "        if text and text in \"12345678\":\n", "        if False:\n")]
M["d8_no_leftright"] = [(S, "        if key in (K.Key_Left, K.Key_Right):\n", "        if False:\n")]
M["d8_no_updown"] = [(S, "        if key in (K.Key_Up, K.Key_Down):\n", "        if False:\n")]
M["d8_detail_not_follow_cursor"] = [(P + "kit/feed.py", "        self.view.selectionModel().currentRowChanged.connect(self._row_changed)\n", "        pass\n")]
M["d8_no_restore_row"] = [(P + "kit/feed.py", "        self.model.modelReset.connect(self._restore_row)\n", "        pass\n")]
M["d8_typing_stolen"] = [(S, "        if typing:\n            return False                # never steal", "        if False:\n            return False                # never steal")]
M["d8_no_panic_key"] = [(S, "        if key == QtGui.QKeySequence(PANIC_KEY)[0].key():", "        if False:")]
M["d8_panic_no_disarm"] = [(S, "            txguard.arm(False)                     # also drops the session unlock\n", "            pass\n")]
M["d8_panic_no_end_engagement"] = [(S, "            was = engagement.end()\n", "            was = None\n")]
M["d8_panic_no_kill"] = [(S, "        killed = [p for p in self._list_children() if self._kill(p)]\n", "        killed = []\n")]
M["d8_panic_not_while_typing"] = [(S, "        if key == QtGui.QKeySequence(PANIC_KEY)[0].key():", "        if key == QtGui.QKeySequence(PANIC_KEY)[0].key() and not typing:")]
M["d8_panic_not_with_overlay_open"] = [(S, "        if key == QtGui.QKeySequence(PANIC_KEY)[0].key():", "        if key == QtGui.QKeySequence(PANIC_KEY)[0].key() and overlay is None:")]
M["d8_no_help_key"] = [(S, "        if text == \"?\":\n", "        if False:\n")]
M["d8_no_palette_key"] = [(S, "        if text == \"/\":\n", "        if False:\n")]
M["d8_no_r_key"] = [(S, "        if low == \"r\":\n", "        if False:\n")]
M["d8_no_e_key"] = [(S, "        if low == \"e\":\n", "        if False:\n")]
M["d8_no_m_key"] = [(S, "        if low == \"m\":\n", "        if False:\n")]
M["d8_no_a_key"] = [(S, "        if low == \"a\":\n", "        if False:\n")]
M["d8_no_space"] = [(S, "        if text == \" \":\n", "        if False:\n")]
M["d8_no_brackets_prowl"] = [(P + "prowl.py", "            if text in \"[]\":\n                n = self.bank_combo.count()", "            if False:\n                n = self.bank_combo.count()"),
                             (P + "prowl.py", "        elif self._submode == \"FM\" and text in \"[]\":", "        elif False:")]
M["d8_no_esc_home"] = [(S, "            else:\n                self.show_page(\"OPS\")\n            return True", "            else:\n                pass\n            return True")]
M["d8_no_enter_ack_in_drawer"] = [(S, "                self.alerts_drawer.ack_selected()\n                return True", "                return True")]
M["d8_no_setfocus_on_nav"] = [(S, "        self.setFocus()        # keys go to the page, not to whichever nav key was last focused\n", "        pass\n")]
M["d8_key_target_any_widget"] = [(S, "        focus = QtWidgets.QApplication.focusWidget()\n        if focus is not None and focus.window() is self:\n            return obj is focus\n        return obj is self",
                                  "        return True")]
M["d8_palette_no_freq"] = [(P + "panels.py", "        if mhz is not None and self._freq_actions is not None and 0.001 <= mhz <= 6000:", "        if False:")]
M["d8_prism_no_plus_minus"] = [(P + "prism.py", "        if text in \"+=\":", "        if False:")]
M["d8_no_modifier_guard"] = [(S, "        if mods & (K.ControlModifier | K.AltModifier | K.MetaModifier):\n            return False\n", "")]
M["d8_subtab_not_focusable"] = [(P + "kit/subtabs.py", "b.setFocusPolicy(QtCore.Qt.TabFocus)", "b.setFocusPolicy(QtCore.Qt.NoFocus)")]

# ---------------- D9
T = P + "theme.py"
M["d9_sun_muted_grey"] = [(T, "\"hairline\": \"#000000\", \"text\": \"#000000\", \"muted\": \"#333333\"", "\"hairline\": \"#000000\", \"text\": \"#000000\", \"muted\": \"#888888\"")]
M["d9_light_live_old"] = [(T, "\"accent\": \"#5A4790\", \"live\": \"#1E7A48\", \"warn\": \"#7A5200\", \"alert\": \"#A8322C\"", "\"accent\": \"#5A4790\", \"live\": \"#2E9E63\", \"warn\": \"#9A6B12\", \"alert\": \"#B5443E\"")]
M["d9_dark_hairline_old"] = [(T, "\"hairline\": \"#5A6472\"", "\"hairline\": \"#272B31\"")]
M["d9_sun_bw_1px"] = [(T, "\"focus\": \"#000000\", \"focus_w\": \"4px\", \"bw\": \"2px\"", "\"focus\": \"#000000\", \"focus_w\": \"4px\", \"bw\": \"1px\"")]
M["d9_forge_engagement_green"] = [(P + "forge.py", "self._tok[\"warn\"])     # amber: armed, not healthy", "self._tok[\"live\"])     # amber: armed, not healthy")]
M["d9_forge_txarmed_green"] = [(P + "forge.py", "self._tok[\"alert\"])    # red: armed, never green", "self._tok[\"live\"])    # red: armed, never green")]
M["d9_forge_result_green"] = [(P + "forge.py", "(self._tok[\"warn\"] if ok else self._tok[\"muted\"]))\n        if ok:\n            tail", "(self._tok[\"live\"] if ok else self._tok[\"muted\"]))\n        if ok:\n            tail")]
M["d9_recon_authorized_green"] = [(P + "recon.py", "self._tok[\"warn\"])        # AUTHORIZED is amber (D9)", "self._tok[\"live\"])        # AUTHORIZED is amber (D9)")]
M["d9_bench_permitted_green"] = [(P + "bench_app.py", "            self.gate.setStyleSheet(\"color:%s;\" % self._tok[\"warn\"])", "            self.gate.setStyleSheet(\"color:%s;\" % self._tok[\"live\"])")]
M["d9_engage_panel_active_green"] = [(P + "panels.py", "        self.eng_msg.setStyleSheet(\"color:%s;\" % self._tok[\"warn\"])", "        self.eng_msg.setStyleSheet(\"color:%s;\" % self._tok[\"live\"])")]
M["d9_slots_armed_active_green"] = [(P + "kit/topbar.py", "self.slots[\"tx\"].set(\"ARMED\", \"square\", t[\"alert\"])", "self.slots[\"tx\"].set(\"ARMED\", \"square\", t[\"live\"])"),
                                     (P + "kit/topbar.py", "self.slots[\"engagement\"].set(\"ACTIVE\", \"diamond\", t[\"warn\"], scope)", "self.slots[\"engagement\"].set(\"ACTIVE\", \"diamond\", t[\"live\"], scope)")]

# ---------------- D10
M["d10_store_cap_3"] = [(P + "panels.py", "def __init__(self, parent=None, cap=500):", "def __init__(self, parent=None, cap=3):")]
M["d10_ack_deletes"] = [(P + "panels.py", "            self.items[index][\"acked\"] = True\n            self.changed.emit()", "            del self.items[index]\n            self.changed.emit()")]
M["d10_prism_send_disabled"] = [(P + "prism.py", "        self.send_btn.setEnabled(True)\n", "        self.send_btn.setEnabled(False)\n")]
M["d10_no_collapse"] = [(P + "kit/components.py", "        self.hero.setVisible(self.hero.text().strip() not in (\"\", \"—\"))", "        self.hero.setVisible(True)")]
M["d10_ops_card_shows_none"] = [(P + "ops.py", "        shown = sorted(items, key=lambda a: a[\"acked\"])[:4]", "        shown = []")]
M["d10_tune_fm_wrong_freq"] = [(P + "prowl.py", "        self.fm_freq.setValue(float(mhz))", "        self.fm_freq.setValue(float(mhz) + 5.0)")]

# ---------------- RADIOS
R = P + "radios.py"
M["r_nosys_reports_absent"] = [(R, "\"present\": \"UNKNOWN (no USB sysfs on this host)\"", "\"present\": \"ABSENT\"")]
M["r_soft_block_reads_on"] = [(R, "            power = \"BLOCKED (rfkill)\"", "            power = \"ON\"")]
M["r_hard_block_reads_on"] = [(R, "            power = \"BLOCKED (hardware switch)\"", "            power = \"ON\"")]
M["r_empty_reports_present"] = [(R, "rows.append({\"radio\": \"SDR dongle\", \"present\": \"ABSENT\"", "rows.append({\"radio\": \"SDR dongle\", \"present\": \"PRESENT\"")]
M["r_panel_table_fabricated"] = [(P + "panels.py", "        rows = radios.inventory(owner_label=radio_arbiter.owner_label(), sys_root=self._sys_root)\n",
                                  "        rows = [{\"radio\": \"RTL-SDR\", \"present\": \"PRESENT\", \"power\": \"ON\", \"owner\": \"FREE\"}]\n")]
M["r_free_noop"] = [(P + "panels.py", "            radio_arbiter.arbiter.release(owner)      # free the dongle; the next layer acquires it\n", "            pass\n")]
M["r_takeover_enabled_when_free"] = [(P + "panels.py", "            self.holder.set_rows([(\"STATE\", \"FREE — any layer may acquire\")])\n            self.takeover_btn.setEnabled(False)",
                                      "            self.holder.set_rows([(\"STATE\", \"FREE — any layer may acquire\")])\n            self.takeover_btn.setEnabled(True)")]
M["r_device_pick_enabled"] = [(P + "panels.py", "        self.device_pick.setEnabled(False)\n", "        self.device_pick.setEnabled(True)\n")]
M["r_slot_click_wrong_panel"] = [(S, "{\"radio\": \"radios\", \"engagement\": \"engagement\"", "{\"radio\": \"keys\", \"engagement\": \"engagement\"")]
M["r_unknown_rfkill_reads_on"] = [(R, "            power = \"UNKNOWN\"", "            power = \"ON\"")]
M["r_wifi_unknown_reports_present"] = [(R, "\"present\": \"UNKNOWN (no rfkill on this host)\"", "\"present\": \"UNKNOWN PRESENT\"")]

# ---------------- audio
A = P + "kit/audio.py"
M["a_volume_pretends_no_backend"] = [(A, "        argv = self.set_volume_argv(pct)\n        return bool(argv) and self._run(argv)[0] == 0", "        argv = self.set_volume_argv(pct)\n        return True")]
M["a_mute_pretends_no_backend"] = [(A, "        argv = self.set_mute_argv(muted)\n        return bool(argv) and self._run(argv)[0] == 0", "        argv = self.set_mute_argv(muted)\n        return True")]
M["a_volume_ignores_mixer_rc"] = [(A, "        argv = self.set_volume_argv(pct)\n        return bool(argv) and self._run(argv)[0] == 0", "        argv = self.set_volume_argv(pct)\n        return bool(argv) and (self._run(argv) is not None)")]
M["a_controls_enabled_without_sink"] = [(P + "kit/topbar.py", "                w.setEnabled(False)\n                w.setToolTip(\"NO AUDIO SINK", "                w.setEnabled(True)\n                w.setToolTip(\"NO AUDIO SINK")]
M["a_slider_signal_unwired"] = [(P + "kit/topbar.py", "        self.volume.valueChanged.connect(lambda _v: self._vol_timer.start())\n", "        pass\n")]
M["a_debounce_timer_unwired"] = [(P + "kit/topbar.py", "        self._vol_timer.timeout.connect(self._apply_volume)\n", "        pass\n")]
M["a_apply_volume_noop"] = [(P + "kit/topbar.py", "            self.audio.set_volume(self.volume.value())\n", "            pass\n")]
M["a_mute_noop"] = [(P + "kit/topbar.py", "            self.audio.set_mute(muted)\n", "            pass\n")]
M["a_initial_volume_fake"] = [(P + "kit/topbar.py", "        self.volume.setValue(vol if vol is not None else 0)\n", "        self.volume.setValue(50)\n")]
M["a_wpctl_get_broken"] = [(A, "            return (int(round(float(m.group(1)) * 100)) if m else None), \"[MUTED]\" in out", "            return None, False")]
M["a_initial_mute_ignored"] = [(P + "kit/topbar.py", "        if muted:\n            self.mute.blockSignals(True)", "        if False:\n            self.mute.blockSignals(True)")]
M["a_get_failure_shows_zero_ok"] = [(A, "        if rc != 0:\n            return None, None", "        if rc != 0:\n            return 77, False")]

# ---------------- edited existing tests: gate/safety
M["x_engage_panel_bypass_refusal"] = [(P + "panels.py", "        self.eng_msg.setText((\"ACTIVE — \" if ok else \"REFUSED — \") + why)", "        self.eng_msg.setText(\"ACTIVE — \" + why)")]
M["x_recon_cards_unlocked_without_engagement"] = None  # filled in after reading recon
M["x_sweep_demo_publishes_to_bus"] = None
M["x_bench_tx_btn_enabled_when_gated"] = [(P + "bench_app.py", "        self.tx_btn.setEnabled(ok)\n", "        self.tx_btn.setEnabled(True)\n")]
M = {k: v for k, v in M.items() if v is not None}
M["z_noop_a"] = []
M["z_noop_b"] = []

# ---------------- second batch
M["x_sweep_stop_leaks_workers"] = [(P + "sweep.py", "        for w in getattr(self, \"_workers\", []):\n            w.stop()\n            w.quit()\n            w.wait(3000)\n        self._workers = []\n", "        self._workers = []\n")]
M["x_sweep_demo_publishes_to_bus"] = [(P + "sweep.py", "        if not msg.get(\"demo\"):", "        if True:")]
M["x_recon_cards_enabled_without_engagement"] = [(P + "recon.py", "            b.setEnabled(active)\n        self.target.setEnabled(active)\n", "            b.setEnabled(True)\n        self.target.setEnabled(True)\n")]
M["x_recon_ignores_shell_gate_change"] = [(P + "recon.py", "    def on_gate_changed(self):\n        self._refresh_gate()", "    def on_gate_changed(self):\n        pass")]
M["x_sweep_real_alert_not_published"] = [(P + "sweep.py", "        if not msg.get(\"demo\"):", "        if False:")]
M["d2_caption_6"] = [(P + "theme.py", "FONT_CAPTION = 13\n", "FONT_CAPTION = 6\n")]
M["d2_navlabel_5"] = [(P + "theme.py", "QLabel.navlabel {{ color: {muted}; font-size: 11px; }}", "QLabel.navlabel {{ color: {muted}; font-size: 5px; }}")]
