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
        self._done = False             # set once terminate() verified everything gone: never
        prev = None                    # signal these (possibly reused) pgids again
        try:
            for i, argv in enumerate(self.stages):
                last = i == len(self.stages) - 1
                kw = dict(stdin=prev if prev is not None else subprocess.DEVNULL,
                          stdout=subprocess.PIPE,
                          stderr=(stderr_last if (last and stderr_last is not None)
                                  else subprocess.DEVNULL),
                          text=text, bufsize=bufsize, env=env,
                          start_new_session=True)         # every stage leads its own group: a
                p = subprocess.Popen(argv, **kw)          # process cannot join another session's
                if prev is not None:                      # group, so we kill each group instead
                    prev.close()                          # only the next stage reads it
                prev = p.stdout
                self.procs.append(p)
        except BaseException:
            # CL5-fix 9: stage N failed to start (binary missing …) -> stop the stages that did
            # start, or stage 1 (rtl_fm) is left holding the dongle with nobody reading it
            if prev is not None:
                try:
                    prev.close()
                except Exception:
                    pass
            self.sids = [p.pid for p in self.procs]
            self.stdout = self.stderr = None
            self.terminate()
            raise
        self.sids = [p.pid for p in self.procs]             # = each stage's pgid (setsid)
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
        """SIGTERM every stage's process group, wait `grace`, SIGKILL the groups if ANY member is
        left (a stage, or a child of one that ignores SIGTERM), wait `kill_after`, reap all.
        Returns True only if every stage is reaped AND every group is empty (CL5-fix 9: it used
        to report True with a surviving grandchild). Safe to call from several threads and more
        than once."""
        self._signal(signal.SIGTERM)
        self.wait(grace)
        if self._groups_alive(grace_s=0.0):
            self._signal(signal.SIGKILL)
            self.wait(kill_after)
        dead = not any(p.poll() is None for p in self.procs) and \
            not self._groups_alive(grace_s=min(1.0, kill_after))
        if dead:
            self._done = True
        for s in (self.stdout, self.stderr):
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass
        return dead

    kill = terminate

    def _signal(self, sig):
        """Signal every stage's GROUP, even one whose leader already exited (a stage that forked
        and exited leaves its child in the group — CL5-fix 9)."""
        if self._done:
            return
        for pg in self.sids:
            try:
                os.killpg(pg, sig)                        # the whole group (children of a stage too)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def _groups_alive(self, grace_s=0.0):
        """True if any stage group still has a live (non-zombie) member. Orphaned zombies are
        reaped by init, so give them grace_s to clear."""
        if self._done:
            return False
        end = time.monotonic() + grace_s
        while True:
            live = any(_group_has_live(pg) for pg in self.sids)
            if not live or time.monotonic() >= end:
                return live
            time.sleep(0.02)


def _group_has_live(pgid):
    """Does process group pgid have a member that is not a zombie? Uses /proc when present."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    if not os.path.isdir("/proc"):
        return True
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % d) as f:
                st = f.read()
        except OSError:
            continue
        rest = st[st.rfind(")") + 2:].split()       # state ppid pgrp …
        if len(rest) >= 3 and rest[2] == str(pgid) and rest[0] != "Z":
            return True
    return False


def terminate_async(proc):
    """Stop a Pipeline (or anything with terminate()) WITHOUT blocking the caller: the GUI thread
    calls this from a RUN / hide / revoke handler so a stage that ignores SIGTERM never freezes the
    UI (CL5-fix 6). The worker thread still calls proc.terminate() itself, which waits until every
    stage is gone, BEFORE it releases the radio — so the release ordering is unchanged."""
    if proc is None:
        return None
    import threading
    t = threading.Thread(target=_quiet_terminate, args=(proc,), name="pipe-terminate", daemon=True)
    t.start()
    return t


def _quiet_terminate(proc):
    try:
        proc.terminate()
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
