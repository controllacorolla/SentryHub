import subprocess, sys, os, shutil
R=os.path.dirname(os.path.abspath(__file__)); PY=sys.argv[1]
src=os.path.join(R,"branch","palisade_qt"); dst=os.path.join(R,"mut","palisade_qt")
MUTS=[
 ("typing guard removed","shell.py","        if typing:\n            return False                # never steal characters from a text field\n","        if typing:\n            pass\n"),
 ("PANIC not while typing","shell.py","        if key == QtGui.QKeySequence(PANIC_KEY)[0].key():      # works everywhere, even while typing\n","        if key == QtGui.QKeySequence(PANIC_KEY)[0].key() and not typing:\n"),
 ("PANIC blocked by overlay","shell.py","        if key == QtGui.QKeySequence(PANIC_KEY)[0].key():      # works everywhere, even while typing\n","        if key == QtGui.QKeySequence(PANIC_KEY)[0].key() and overlay is None:\n"),
 ("panic skips engagement.end","shell.py","            was = engagement.end()\n","            was = None\n"),
 ("panic skips txguard.arm","shell.py","            txguard.arm(False)                     # also drops the session unlock\n","            pass\n"),
 ("panic skips kill","shell.py","        killed = [p for p in self._list_children() if self._kill(p)]\n","        killed = []\n"),
 ("panic: no try around arm","shell.py","        except Exception as e:\n            did.append(\"TX disarm FAILED: %s\" % e)\n","        except ZeroDivisionError as e:\n            did.append(\"TX disarm FAILED: %s\" % e)\n"),
 ("left/right disabled","shell.py","            return bool(page is not None and page.cycle_subtab(1 if key == K.Key_Right else -1))\n","            return False\n"),
 ("space disabled","shell.py","            return bool(page is not None and page.handle_key(\" \"))\n","            return False\n"),
 ("[]+- disabled","shell.py","        if text and text in \"[]+-=_\":\n            return bool(page is not None and page.handle_key(text))\n","        if text and text in \"[]+-=_\":\n            return False\n"),
 ("/ disabled","shell.py","        if text == \"/\":\n            self.open_panel(\"palette\")\n","        if text == \"/\":\n            pass\n"),
 ("? disabled","shell.py","        if text == \"?\":\n            self.open_panel(\"keys\")\n","        if text == \"?\":\n            pass\n"),
 ("esc w/ overlay doesn't close","shell.py","                overlay.close_overlay()\n                self.setFocus()\n","                pass\n"),
 ("esc doesn't go home","shell.py","            else:\n                self.show_page(\"OPS\")\n            return True\n","            return True\n"),
 ("overlay guard removed","shell.py","            return False                # the open panel gets the keyboard (Tab, arrows, typing)\n","            pass\n"),
 ("up/down disabled","shell.py","            return lst.move_cursor(1 if key == K.Key_Down else -1)\n","            return False\n"),
 ("enter primary disabled","shell.py","            return bool(page is not None and page.primary_action())\n","            return False\n"),
 ("R/E/A/M disabled","shell.py","        low = text.lower() if text else \"\"\n","        low = \"\"\n"),
 ("modifier guard removed","shell.py","        if mods & (K.ControlModifier | K.AltModifier | K.MetaModifier):\n            return False\n",""),
 ("FOLDED emptied","shell.py","    \"OVERWATCH\": (\"ATLAS\", \"SKY DOME\", OverwatchApp),\n    \"BABEL\": (\"PROWL\", \"DECODE\", BabelApp),\n    \"BENCH\": (\"SYSTEM\", \"BENCH\", BenchApp),\n    \"MORE\": (\"SYSTEM\", \"SETTINGS\", MoreApp),\n",""),
 ("nav labels blank","kit/topbar.py","        self.label = QtWidgets.QLabel(label)\n","        self.label = QtWidgets.QLabel('')\n"),
 ("BENCH tab dropped from SYSTEM","pages.py","                        (\"MESH\", \"MESH\"), (\"SITREP\", \"SITREP\"))),\n             (BenchApp, ((\"BENCH\", None),)))","                        (\"MESH\", \"MESH\"), (\"SITREP\", \"SITREP\"))),)"),
 ("RF tab dropped from RECON","recon.py","SUBTABS = (\"WIFI\", \"BLE\", \"NET\", \"RF\")","SUBTABS = (\"WIFI\", \"BLE\", \"NET\")"),
 ("is_key_target always true (double fire)","shell.py","            return obj is focus\n        return obj is self\n","            return True\n        return True\n"),
 ("show_page no setFocus","shell.py","        self.setFocus()        # keys go to the page, not to whichever nav key was last focused\n","        pass\n"),
 ("panic banner not shown","shell.py","        self._show_banner(text)\n        return did\n","        return did\n"),
]
only=sys.argv[2:] 
for name,f,old,new in MUTS:
    if only and not any(o in name for o in only): continue
    s=open(os.path.join(src,f)).read()
    if old not in s: print("!! pattern missing:",name); continue
    open(os.path.join(dst,f),"w").write(s.replace(old,new,1))
    env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1", HOME=os.path.join(R,"home"))
    p=subprocess.run([PY,"-m","pytest","-q","-x","-p","no:cacheprovider","tests/test_cl1_screen.py","tests/test_palisade_qt.py"],cwd=os.path.join(R,"mut"),capture_output=True,text=True,env=env)
    tail=[l for l in p.stdout.splitlines() if l.startswith("FAILED") or " passed" in l or " failed" in l or "error" in l.lower()]
    print("%-42s -> %s"%(name, " | ".join(t[:150] for t in tail[:2]) ))
    shutil.copy(os.path.join(src,f), os.path.join(dst,f))
