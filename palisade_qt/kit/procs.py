"""Decoder pipelines as argv lists in ONE process session, killed as a group, always waited (A4).

The audit found APRS/AIS/NWR spawned `sh -c "rtl_fm … | multimon-ng …"` and terminated only the
shell, so the radio process survived the release and the dongle stayed busy; PRISM never waited
and left zombies. This helper is the one way a Qt page runs a decoder:

    pipe = Pipeline([["rtl_fm", …], ["multimon-ng", …]])      # no shell, no strings
    for line in pipe.stdout: …
    pipe.terminate()           # SIGTERM the whole session, wait, SIGKILL, wait — never a zombie

Every stage leads its own session (setsid) and terminate() signals every stage's group, so PANIC
and the arbiter can kill the lot; stderr goes to DEVNULL unless a stage asks for it.
"""
import os
import signal
import subprocess
import time


class Pipeline:
    def __init__(self, stages, text=True, stderr_last=None, bufsize=1, env=None):
        if not stages:
            raise ValueError("a pipeline needs at least one stage")
        self.stages = [list(s) for s in stages]
        self.procs = []
        prev = None
        for i, argv in enumerate(self.stages):
            last = i == len(self.stages) - 1
            kw = dict(stdin=prev if prev is not None else subprocess.DEVNULL,
                      stdout=subprocess.PIPE,
                      stderr=(stderr_last if (last and stderr_last is not None)
                              else subprocess.DEVNULL),
                      text=text, bufsize=bufsize, env=env,
                      start_new_session=True)             # every stage leads its own group: a
            p = subprocess.Popen(argv, **kw)              # process cannot join another session's
            if prev is not None:                          # group, so we kill each group instead
                prev.close()                              # only the next stage reads it
            prev = p.stdout
            self.procs.append(p)
        self.sids = [p.pid for p in self.procs]
        self.sid = self.sids[0]
        self.stdout = self.procs[-1].stdout
        self.stderr = self.procs[-1].stderr
        self.pid = self.procs[-1].pid

    # ---- liveness ----
    def poll(self):
        """None while every stage runs; else the first non-None returncode (leader first)."""
        codes = [p.poll() for p in self.procs]
        for c in codes:
            if c is not None:
                return c
        return None

    def alive(self):
        return all(p.poll() is None for p in self.procs)

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        for p in self.procs:
            rem = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                p.wait(timeout=rem)
            except subprocess.TimeoutExpired:
                return None
        return self.poll()

    # ---- stop ----
    def terminate(self, grace=1.0, kill_after=2.0):
        """SIGTERM the session, wait `grace`, SIGKILL survivors, wait `kill_after`, reap all.
        Returns True if everything is dead (no zombies left)."""
        self._signal(signal.SIGTERM)
        if self.wait(grace) is None:
            self._signal(signal.SIGKILL)
            self.wait(kill_after)
        dead = not any(p.poll() is None for p in self.procs)
        for s in (self.stdout, self.stderr):
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass
        return dead

    kill = terminate

    def _signal(self, sig):
        for p in self.procs:
            if p.poll() is not None:
                continue
            try:
                os.killpg(p.pid, sig)                     # its whole group (children of a stage too)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    p.send_signal(sig)
                except Exception:
                    pass


def split_shell_pipeline(cmd):
    """For legacy modules that still hand back `a | b` strings: split on '|' into argv lists with
    shlex, dropping `2>/dev/null` redirections (stderr is DEVNULL by default here). Refuses
    anything else shell-ish."""
    import shlex
    stages = []
    for part in str(cmd).split("|"):
        toks = shlex.split(part)
        toks = [t for t in toks if t not in ("2>/dev/null", "2>&1")]
        if not toks or any(t in (";", "&&", "||", ">", "<", "`", "$(") for t in toks):
            raise ValueError("not a plain pipeline: %r" % cmd)
        stages.append(toks)
    return stages
