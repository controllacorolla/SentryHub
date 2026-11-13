"""Tests for the plugin API (Phase 3e)."""
import json

import plugins
import pytest


def test_validate_fills_defaults():
    m = plugins.validate({"key": "x", "name": "X", "module": "x_mod", "entry": "main"})
    assert m["group"] == "Plugins" and m["icon"] == "⬚" and m["deps"] == []


def test_validate_requires_fields():
    with pytest.raises(ValueError):
        plugins.validate({"key": "x", "name": "X"})          # no module/entry


def test_load_manifest_from_file(tmp_path):
    p = tmp_path / "foo.plugin.json"
    p.write_text(json.dumps({"key": "foo", "name": "Foo", "module": "foo", "entry": "main",
                             "deps": ["numpy"], "hardware": ["hackrf"]}))
    m = plugins.load_manifest(str(p))
    assert m["key"] == "foo" and m["deps"] == ["numpy"] and m["_path"].endswith("foo.plugin.json")


def test_discover_file_and_dir_manifests(tmp_path):
    (tmp_path / "a.plugin.json").write_text(json.dumps(
        {"key": "a", "name": "A", "module": "a", "entry": "main"}))
    sub = tmp_path / "bee"
    sub.mkdir()
    (sub / "manifest.json").write_text(json.dumps(
        {"key": "b", "name": "B", "module": "b", "entry": "run"}))
    (tmp_path / "broken.plugin.json").write_text("{ not json")
    (tmp_path / "incomplete.plugin.json").write_text(json.dumps({"key": "c"}))
    found = {m["key"] for m in plugins.discover(str(tmp_path))}
    assert found == {"a", "b"}                 # broken + incomplete skipped, not fatal


def test_discover_missing_dir_is_empty():
    assert plugins.discover("/no/such/plugins/dir") == []


def test_from_legacy_shim():
    m = plugins.from_legacy("aprs", "APRS", "aprs", "main", desc="pos net", group="Apps", icon="◇")
    assert m["key"] == "aprs" and m["module"] == "aprs" and m["entry"] == "main"


def test_missing_deps_with_have_set():
    m = plugins.validate({"key": "x", "name": "X", "module": "x", "entry": "main",
                          "deps": ["numpy", "nonesuch_pkg"]})
    assert plugins.missing_deps(m, have={"numpy"}) == ["nonesuch_pkg"]


def test_register_into_skips_existing():
    mods = {"aprs": ("aprs", "main")}
    ms = [plugins.from_legacy("new1", "N1", "n1", "main"),
          plugins.from_legacy("aprs", "dup", "evil", "main")]
    added, skipped = plugins.register_into(mods, ms)
    assert added == ["new1"] and skipped == ["aprs"]
    assert mods["aprs"] == ("aprs", "main")          # core not shadowed
