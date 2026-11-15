import sys, shutil, subprocess, os
W=os.path.dirname(os.path.abspath(__file__)); PY=sys.argv[1]
M={
 "baseline":[],
 "S_panel_table_fabricated":[("palisade_qt/panels.py","        rows = radios.inventory(owner_label=radio_arbiter.owner_label(), sys_root=self._sys_root)\n",'        rows = [{"radio": "RTL-SDR", "present": "PRESENT", "power": "ON", "owner": "FREE"}]\n')],
 "S_hard_block_reads_on":[("palisade_qt/radios.py",'            power = "BLOCKED (hardware switch)"','            power = "ON"')],
 "S_unknown_rfkill_reads_on":[("palisade_qt/radios.py",'            power = "UNKNOWN"','            power = "ON"')],
 "S_wifi_unknown_reports_present":[("palisade_qt/radios.py",'"present": "UNKNOWN (no rfkill on this host)"','"present": "PRESENT"')],
 "K_nosysfs_absent":[("palisade_qt/radios.py",'"present": "UNKNOWN (no USB sysfs on this host)"','"present": "ABSENT"')],
 "K_empty_present":[("palisade_qt/radios.py",'"present": "ABSENT"','"present": "PRESENT"')],
 "K_soft_on":[("palisade_qt/radios.py",'            power = "BLOCKED (rfkill)"','            power = "ON"')],
 "K_free_noop":[("palisade_qt/panels.py","            radio_arbiter.arbiter.release(owner)      #","            pass  #")],
 "K_takeover_enabled_free":[("palisade_qt/panels.py","            self.takeover_btn.setEnabled(False)","            self.takeover_btn.setEnabled(True)")],
 "K_picker_enabled":[("palisade_qt/panels.py","        self.device_pick.setEnabled(False)","        self.device_pick.setEnabled(True)")],
}
for name,edits in M.items():
    d=os.path.join(W,"m"); shutil.rmtree(d,ignore_errors=True); shutil.copytree(os.path.join(W,"base"),d)
    for f,a,b in edits:
        p=os.path.join(d,f); s=open(p).read(); assert s.count(a)==1,(name,s.count(a)); open(p,"w").write(s.replace(a,b))
    r=subprocess.run([PY,"-m","pytest","-q","tests/test_cl1_screen.py","tests/test_palisade_qt.py","-k","radio or Radio or overwatch or rfkill","-p","no:cacheprovider"],cwd=d,env=dict(os.environ,QT_QPA_PLATFORM="offscreen",HOME=os.path.join(W,"home")),capture_output=True,text=True)
    tail=[l for l in r.stdout.splitlines() if l.startswith("FAILED") or " passed" in l or " failed" in l or "error" in l.lower()][-3:]
    print(name, "rc=%d"%r.returncode, tail, flush=True)
