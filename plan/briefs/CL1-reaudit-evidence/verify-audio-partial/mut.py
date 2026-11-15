import shutil, subprocess, sys, os
D=os.path.dirname(os.path.abspath(__file__)); PY=sys.argv[1]
T="palisade_qt/kit/topbar.py"; A="palisade_qt/kit/audio.py"
muts={
 "baseline":(T,None,None),
 "slider_signal_unwired":(T,"        self.volume.valueChanged.connect(lambda _v: self._vol_timer.start())\n",""),
 "debounce_unwired":(T,"        self._vol_timer.timeout.connect(self._apply_volume)\n",""),
 "volume_ignores_rc":(A,"        return bool(argv) and self._run(argv)[0] == 0\n\n    def set_mute","        self._run(argv) if argv else None\n        return bool(argv)\n\n    def set_mute"),
 "get_failure_zero_ok":(A,"        if rc != 0:\n            return None, None\n","        if rc != 0:\n            return 0, False\n"),
 "wpctl_get_broken":(A,'"[MUTED]" in out','False'),
 "wpctl_get_vol_broken":(A,'r"Volume:\\s*([0-9.]+)"','r"NOPE:\\s*([0-9.]+)"'),
 "initial_mute_ignored":(T,"        if muted:\n","        if False:\n"),
 "KILLCHK_apply_noop":(T,"            self.audio.set_volume(self.volume.value())","            pass"),
 "KILLCHK_on_mute_noop":(T,"            self.audio.set_mute(muted)","            pass"),
 "KILLCHK_no_init":(T,"        self.volume.setValue(vol if vol is not None else 0)\n","        self.volume.setValue(0)\n"),
}
for name,(f,old,new) in muts.items():
    w=os.path.join(D,"work"); shutil.rmtree(w,ignore_errors=True); shutil.copytree(os.path.join(D,"base"),w)
    if old is not None:
        p=os.path.join(w,f); s=open(p).read(); assert s.count(old)==1,(name,s.count(old)); open(p,"w").write(s.replace(old,new))
    r=subprocess.run([PY,"-m","pytest","-q","tests/test_cl1_screen.py","-k","audio or volume or sink","-p","no:cacheprovider"],cwd=w,capture_output=True,text=True,env=dict(os.environ,QT_QPA_PLATFORM="offscreen"))
    print(name, "rc=%d"%r.returncode, r.stdout.strip().splitlines()[-1][:150]); 
    if r.returncode: print("   ", [l for l in r.stdout.splitlines() if l.startswith("FAILED")][:2])
