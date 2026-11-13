#!/usr/bin/env python3
"""plugins.py — plugin manifest + auto-discovery (Phase 3e).

A plugin is a module that registers itself through a manifest (JSON), so new modules drop into
the suite without editing hub.py. A manifest lives either as `<name>.plugin.json` or as
`manifest.json` inside a plugin subdirectory of a `plugins/` folder. Existing in-tree modules
are shimmed into the same shape with from_legacy(), so the old hub.MODS registration and the new
manifest API coexist (no rewrite of working modules).

Pure: JSON + filesystem reads only; no Tk.
"""
import json
import os

REQUIRED = ("key", "name", "module", "entry")
DEFAULTS = {"group": "Plugins", "icon": "⬚", "desc": "", "color": None,
            "tile": None, "health": None, "deps": [], "hardware": []}


def validate(manifest):
    """Return a normalized manifest (defaults filled). Raises ValueError if a required field is
    missing or malformed."""
    missing = [k for k in REQUIRED if not manifest.get(k)]
    if missing:
        raise ValueError("plugin manifest missing: " + ", ".join(missing))
    out = dict(DEFAULTS)
    out.update(manifest)
    if not isinstance(out["deps"], list) or not isinstance(out["hardware"], list):
        raise ValueError("plugin manifest 'deps'/'hardware' must be lists")
    return out


def load_manifest(path):
    with open(path) as f:
        m = json.load(f)
    m.setdefault("_path", path)
    return validate(m)


def discover(plugins_dir):
    """Find and load every valid manifest under plugins_dir. A malformed one is skipped, not
    fatal. Returns a list of normalized manifests (missing dir -> [])."""
    out = []
    try:
        names = sorted(os.listdir(plugins_dir))
    except OSError:
        return out
    for n in names:
        p = os.path.join(plugins_dir, n)
        cand = None
        if os.path.isdir(p):
            mf = os.path.join(p, "manifest.json")
            cand = mf if os.path.isfile(mf) else None
        elif n.endswith(".plugin.json"):
            cand = p
        if cand:
            try:
                out.append(load_manifest(cand))
            except (ValueError, OSError, json.JSONDecodeError):
                pass
    return out


def from_legacy(key, name, module, entry, desc="", group="Apps", icon="·", color=None):
    """Shim an existing hub.MODS/APPS entry into a manifest, so old modules present through the
    same API as plugins."""
    return validate({"key": key, "name": name, "module": module, "entry": entry,
                     "desc": desc, "group": group, "icon": icon, "color": color})


def missing_deps(manifest, have=None):
    """Which Python deps are not satisfied. If `have` (a set of names) is given it is used;
    otherwise importlib checks whether each is importable."""
    unmet = []
    for d in manifest.get("deps", []):
        if have is not None:
            if d not in have:
                unmet.append(d)
        else:
            import importlib.util
            if importlib.util.find_spec(d) is None:
                unmet.append(d)
    return unmet


def register_into(mods, manifests, on_conflict="skip"):
    """Merge manifests into a hub-style MODS dict {key: (module, entry)}. Returns (added, skipped).
    Existing keys are left alone (on_conflict='skip') so a plugin can't shadow a core module."""
    added, skipped = [], []
    for m in manifests:
        if m["key"] in mods and on_conflict == "skip":
            skipped.append(m["key"])
            continue
        mods[m["key"]] = (m["module"], m["entry"])
        added.append(m["key"])
    return added, skipped
