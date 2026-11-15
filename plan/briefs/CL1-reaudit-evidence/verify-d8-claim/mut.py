import subprocess, sys, os, shutil
D=os.path.dirname(os.path.abspath(__file__)); C=D+"/copy"; f=C+"/palisade_qt/shell.py"
orig=open(f).read()
PY=sys.argv[1]
muts={
 "panic_only_if_no_overlay":("        if key == QtGui.QKeySequence(PANIC_KEY)[0].key():","        if overlay is None and key == QtGui.QKeySequence(PANIC_KEY)[0].key():"),
 "arm_try_narrowed":("        except Exception as e:\n            did.append(\"TX disarm FAILED: %s\" % e)","        except ImportError as e:\n            did.append(\"TX disarm FAILED: %s\" % e)"),
 "overlay_guard_removed":("            return False                # the open panel gets the keyboard (Tab, arrows, typing)","            pass"),
 "modifier_guard_removed":("        if mods & (K.ControlModifier | K.AltModifier | K.MetaModifier):\n            return False\n",""),
 "CONTROL_typing_guard_removed":("        if typing:\n            return False                # never steal characters from a text field\n",""),
 "CONTROL_panic_removed":("            self.panic()\n            return True","            return True"),
}
for name,(a,b) in muts.items():
    assert orig.count(a)==1,(name,orig.count(a))
    open(f,"w").write(orig.replace(a,b))
    r=subprocess.run([PY,"-m","pytest","-q","-x","-p","no:cacheprovider","tests/test_cl1_screen.py","tests/test_palisade_qt.py"],cwd=C,capture_output=True,text=True,env=dict(os.environ,QT_QPA_PLATFORM="offscreen"))
    print(name,"->",r.stdout.strip().splitlines()[-1], "|", [l for l in r.stdout.splitlines() if l.startswith("FAILED")][:2])
open(f,"w").write(orig)
r=subprocess.run([PY,"-m","pytest","-q","-p","no:cacheprovider","tests/test_cl1_screen.py","tests/test_palisade_qt.py"],cwd=C,capture_output=True,text=True,env=dict(os.environ,QT_QPA_PLATFORM="offscreen"))
print("BASELINE ->",r.stdout.strip().splitlines()[-1])
