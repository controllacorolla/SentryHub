"""The CL8 device check must say plainly when pytest is missing on the device.

The app installer ships no pytest, so on a fresh uConsole the "CL8 regression tests" check used to
FAIL with "(no output)" (the error was on stderr). It now names the missing module and the fix.
"""
import importlib.util
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "plan", "briefs", "device_check_cl8.py")


def _load():
    spec = importlib.util.spec_from_file_location("device_check_cl8", PATH)
    mod = importlib.util.module_from_spec(spec)
    cwd = os.getcwd()
    spec.loader.exec_module(mod)
    assert os.getcwd() == cwd, "importing the check must not run it or change directory"
    return mod


def test_import_runs_no_checks():
    mod = _load()
    assert mod.results == []


def test_missing_pytest_is_named_with_the_fix(monkeypatch):
    mod = _load()
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a: None if name == "pytest" else real(name, *a))
    ok, detail = mod.tests()
    assert ok is False
    assert "pytest is not installed" in detail
    assert "pip install --user --break-system-packages pytest" in detail


def test_stderr_tail_is_shown_when_stdout_is_empty(monkeypatch):
    mod = _load()

    class R:
        returncode = 1
        stdout = ""
        stderr = "Traceback...\nModuleNotFoundError: No module named 'PySide6'\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    ok, detail = mod.tests()
    assert ok is False and "No module named 'PySide6'" in detail
