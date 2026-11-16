#!/usr/bin/env python3
"""evidence.py — engagement evidence & reporting infrastructure (Phase 3f).

For authorized pen-test / RF-assessment engagements. Five pieces, all pure of Tk:

  Timeline       — chronological event log across all modules; filter/search/export
  EvidenceChain  — append-only, SHA-256 hash-chained captures; tamper-evident; optional GPG sign
  Vault          — age- or LUKS-encrypted directory for findings (command builders; tool-gated)
  QSOLog         — ham contact log with ADIF export (LoTW/QRZ/eQSL)
  report_html    — timeline + evidence + findings -> a templated HTML deliverable

The crypto/report binaries (age, cryptsetup, gpg, wkhtmltopdf) are shelled out only when present;
the module itself computes hashes and builds documents in pure Python so it is fully testable.
"""
import hashlib
import html as _html
import json
import os
import shutil
import time

GENESIS = "0" * 64


def sha256_bytes(b):
    return hashlib.sha256(b if isinstance(b, bytes) else str(b).encode()).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- Engagement timeline ------------------------------------------------------------------
class Timeline:
    def __init__(self, path=None):
        self.events = []
        self.path = path

    def add(self, module, etype, text, contact=None, ts=None, **extra):
        ev = {"ts": ts if ts is not None else time.time(), "module": module, "type": etype,
              "text": text, "contact": contact}
        ev.update(extra)
        self.events.append(ev)
        if self.path:
            try:
                with open(self.path, "a") as f:
                    f.write(json.dumps(ev) + "\n")
            except OSError:
                pass
        return ev

    def filter(self, module=None, etype=None, contact=None, since=None, until=None, query=None):
        out = []
        for e in self.events:
            if module and e["module"] != module:
                continue
            if etype and e["type"] != etype:
                continue
            if contact and e.get("contact") != contact:
                continue
            if since is not None and e["ts"] < since:
                continue
            if until is not None and e["ts"] > until:
                continue
            if query and query.lower() not in json.dumps(e, default=str).lower():
                continue
            out.append(e)
        return out

    def export_jsonl(self, path):
        with open(path, "w") as f:
            for e in sorted(self.events, key=lambda e: e["ts"]):
                f.write(json.dumps(e, default=str) + "\n")
        return path


# ---- Evidence chain (append-only, hash-chained, tamper-evident) ---------------------------
class EvidenceChain:
    """LEGACY (pre-CL3) in-memory chain. Kept for existing tests / exports only; the authoritative,
    durable, keyed chain is `chain.Chain` (one per engagement). Do not use for new evidence."""

    def __init__(self, path=None):
        self.records = []
        self.path = path

    @staticmethod
    def _chain_hash(prev, content_hash, name, ts):
        return sha256_bytes("%s|%s|%s|%.6f" % (prev, content_hash, name, ts))

    def add(self, name, data=None, file_path=None, meta=None, ts=None):
        """Record a capture by content hash (of bytes `data` or of a file). Each record chains to
        the previous one, so altering any past record breaks verify()."""
        content_hash = sha256_file(file_path) if file_path else sha256_bytes(data or b"")
        prev = self.records[-1]["chain"] if self.records else GENESIS
        ts = time.time() if ts is None else ts
        rec = {"seq": len(self.records), "ts": ts, "name": name, "sha256": content_hash,
               "file": file_path, "prev": prev, "meta": meta or {}}
        rec["chain"] = self._chain_hash(prev, content_hash, name, ts)
        self.records.append(rec)
        if self.path:
            try:
                with open(self.path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
            except OSError:
                pass
        return rec

    def verify(self):
        """(ok, bad_seq). Recomputes the chain; returns the first broken seq, or None if intact."""
        prev = GENESIS
        for r in self.records:
            if r["prev"] != prev:
                return False, r["seq"]
            if self._chain_hash(prev, r["sha256"], r["name"], r["ts"]) != r["chain"]:
                return False, r["seq"]
            prev = r["chain"]
        return True, None

    def gpg_sign_argv(self, out_path, key=None):
        """Command to detach-sign the chain file with GPG (optional, tool-gated by the caller)."""
        argv = ["gpg", "--batch", "--yes"]
        if key:
            argv += ["--local-user", key]
        argv += ["--detach-sign", "--armor", "--output", out_path, self.path or ""]
        return argv


# ---- Encrypted vault (age or LUKS) --------------------------------------------------------
class Vault:
    """An encrypted directory for engagement findings. 'age' backend encrypts a tar to a .age
    file; 'luks' backend maps a LUKS container. Command builders are pure; mount/unmount shell
    out via the caller only when the backend tool is present."""

    def __init__(self, path, backend="age"):
        self.path = path
        self.backend = backend
        self.mounted = False

    def available(self, which=shutil.which):
        return bool(which("age" if self.backend == "age" else "cryptsetup"))

    def lock_argv(self, src_dir, recipient):
        """age: tar src_dir and encrypt to self.path for `recipient`. Returns a LIST OF ARGV LISTS
        to be connected by a pipe (audit C2: never a `sh -c` string built from paths and the
        recipient). LUKS: a single argv."""
        if self.backend == "age":
            return [["tar", "-C", str(src_dir), "-cf", "-", "."],
                    ["age", "-r", str(recipient), "-o", self.path]]
        return [["cryptsetup", "luksClose", os.path.basename(self.path)]]

    def unlock_argv(self, dest_dir, identity):
        if self.backend == "age":
            return [["age", "-d", "-i", str(identity), self.path],
                    ["tar", "-C", str(dest_dir), "-xf", "-"]]
        return [["cryptsetup", "luksOpen", self.path, os.path.basename(self.path)]]

    @staticmethod
    def run_pipeline(stages, popen=None):
        """Run argv stages connected stdout→stdin with no shell. Returns the last exit code (or
        the first non-zero one). `popen` is injectable for tests."""
        import subprocess
        popen = popen or subprocess.Popen
        procs, prev = [], None
        for i, argv in enumerate(stages):
            last = i == len(stages) - 1
            p = popen(list(argv), stdin=prev, stdout=None if last else subprocess.PIPE)
            if prev is not None:
                prev.close()
            prev = p.stdout
            procs.append(p)
        codes = [p.wait() for p in procs]
        return next((c for c in codes if c), 0)


# ---- QSO / contact logger + ADIF ----------------------------------------------------------
def adif_field(name, value):
    v = "" if value is None else str(value)
    return "<%s:%d>%s" % (name.upper(), len(v), v)


# ADIF field name for each QSO key we support.
_ADIF_MAP = [("call", "CALL"), ("band", "BAND"), ("mode", "MODE"), ("freq_mhz", "FREQ"),
             ("qso_date", "QSO_DATE"), ("time_on", "TIME_ON"), ("rst_sent", "RST_SENT"),
             ("rst_rcvd", "RST_RCVD"), ("gridsquare", "GRIDSQUARE"), ("my_gridsquare", "MY_GRIDSQUARE"),
             ("name", "NAME"), ("comment", "COMMENT")]


def qso_to_adif(qso):
    out = []
    for key, adif in _ADIF_MAP:
        if qso.get(key) not in (None, ""):
            out.append(adif_field(adif, qso[key]))
    out.append("<EOR>")
    return "".join(out)


def adif_export(qsos, header=True):
    parts = []
    if header:
        parts.append("Sentry QSO log\n%s<EOH>\n" % adif_field("PROGRAMID", "SentryHub"))
    for q in qsos:
        parts.append(qso_to_adif(q) + "\n")
    return "".join(parts)


class QSOLog:
    def __init__(self, path=None):
        self.qsos = []
        self.path = path

    def add(self, **qso):
        qso.setdefault("qso_date", time.strftime("%Y%m%d"))
        qso.setdefault("time_on", time.strftime("%H%M%S"))
        self.qsos.append(qso)
        return qso

    def to_adif(self):
        return adif_export(self.qsos)

    def write_adif(self, path):
        with open(path, "w") as f:
            f.write(self.to_adif())
        return path


# ---- Report generator (HTML; PDF optional) ------------------------------------------------
def report_html(title, timeline_events=None, evidence_records=None, findings=None, meta=None):
    """Templated engagement report: exec summary (meta), methodology/timeline, findings, and an
    evidence appendix with hashes. Returns an HTML string."""
    e = _html.escape
    meta = meta or {}
    findings = findings or []
    parts = ["<!doctype html><html><head><meta charset='utf-8'><title>%s</title>" % e(title),
             "<style>body{font:14px/1.5 system-ui,sans-serif;margin:2em;max-width:60em}"
             "h1,h2{border-bottom:1px solid #ccc}table{border-collapse:collapse;width:100%}"
             "td,th{border:1px solid #ddd;padding:4px 8px;text-align:left;font-size:12px}"
             "code{font-family:monospace;font-size:11px}</style></head><body>"]
    parts.append("<h1>%s</h1>" % e(title))
    if meta:
        parts.append("<h2>Summary</h2><table>")
        for k, v in meta.items():
            parts.append("<tr><th>%s</th><td>%s</td></tr>" % (e(str(k)), e(str(v))))
        parts.append("</table>")
    if findings:
        parts.append("<h2>Findings</h2><ol>")
        for f in findings:
            if isinstance(f, dict):
                parts.append("<li><b>%s</b> — %s</li>" % (e(str(f.get("title", "finding"))),
                                                          e(str(f.get("detail", "")))))
            else:
                parts.append("<li>%s</li>" % e(str(f)))
        parts.append("</ol>")
    if timeline_events:
        parts.append("<h2>Engagement timeline</h2><table><tr><th>Time</th><th>Module</th>"
                     "<th>Type</th><th>Event</th></tr>")
        for ev in sorted(timeline_events, key=lambda x: x.get("ts", 0)):
            parts.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                e(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ev.get("ts", 0)))),
                e(str(ev.get("module", ""))), e(str(ev.get("type", ""))), e(str(ev.get("text", "")))))
        parts.append("</table>")
    if evidence_records:
        parts.append("<h2>Evidence appendix</h2><table><tr><th>#</th><th>Name</th>"
                     "<th>SHA-256</th><th>Chain</th></tr>")
        for r in evidence_records:
            parts.append("<tr><td>%d</td><td>%s</td><td><code>%s</code></td>"
                         "<td><code>%s</code></td></tr>" % (
                             r.get("seq", 0), e(str(r.get("name", ""))),
                             e(str(r.get("sha256", "")))[:16] + "…",
                             e(str(r.get("chain", "")))[:16] + "…"))
        parts.append("</table>")
    parts.append("</body></html>")
    return "".join(parts)


def export_engagement_report(out_dir=None, chain_id=None):
    """E5: write <reports>/<chain id>.html from the durable evidence chain (CL3). The open
    engagement's chain by default; any chain by id. Returns the path. Raises if the chain does
    not verify — a report is never written from a trail that fails its own check."""
    import chain as _chain
    import suite
    if chain_id:
        ch = _chain.Chain.open(chain_id)
    else:
        import engagement
        info = engagement.chain_info()
        if not info:
            raise RuntimeError("no engagement chain is open")
        ch = _chain.Chain.open(info["id"])
    ok, why = ch.verify()
    if not ok:
        raise RuntimeError("chain does not verify: %s" % why)
    out_dir = out_dir or os.path.join(suite.DATA, "reports")
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    opened = next((r for r in ch.records if r.get("event") == "engagement.open"), {})
    states = ch.states()
    findings = [{"title": "%s · %s" % (r["state"], r["action"]),
                 "detail": "%s %s %s" % (r["target"], r.get("binding") or "", r["detail"])}
                for r in states]
    timeline = [{"ts": r["t"], "module": r.get("event", ""), "type": r.get("event", ""),
                 "text": " ".join("%s=%s" % (k, v) for k, v in r.items()
                                  if k not in ("h", "prev", "seq", "t", "mono_ns", "event"))[:200],
                 "contact": None} for r in ch.records]
    doc = report_html(opened.get("name") or ch.id, timeline_events=timeline,
                      evidence_records=[{"seq": r["seq"], "ts": r["t"], "name": r.get("event", ""),
                                         "sha256": r["h"], "file": None} for r in ch.records],
                      findings=findings,
                      meta={"Operator": opened.get("operator", ""), "Chain": ch.id,
                            "Authorization": opened.get("authorization", ""),
                            "Scope": ", ".join(opened.get("scope", []) or []),
                            "Records": str(len(ch.records)), "Verified": why})
    path = os.path.join(out_dir, ch.id + ".html")
    with open(path, "w") as f:
        f.write(doc)
    return path


def write_report(path, *args, **kw):
    doc = report_html(*args, **kw)
    with open(path, "w") as f:
        f.write(doc)
    return path


def pdf_from_html_argv(html_path, pdf_path, which=shutil.which):
    """Build a command to render the HTML report to PDF, if a renderer is installed."""
    if which("wkhtmltopdf"):
        return ["wkhtmltopdf", "-q", html_path, pdf_path]
    if which("weasyprint"):
        return ["weasyprint", html_path, pdf_path]
    return None
