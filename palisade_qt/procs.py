"""Process-tree stop for PANIC: signal, wait, verify, and report only what is verifiably gone.

The decoders this app starts are shell pipelines (`sh -c 'rtl_fm … | multimon-ng …'`). Signalling
only the direct child kills the `sh` wrapper and leaves the pipeline members running, and counting
"signals sent" as "processes killed" then reports a stop that did not happen (RA-CL1). So:

  * each direct child is expanded to its whole tree — its descendants, and every member of its
    process group when it leads one (decoders are started with start_new_session=True);
  * the tree gets SIGTERM, then SIGKILL for anything still alive after a short wait;
  * a process counts as stopped only if it no longer exists or is a zombie (exited, not yet
    reaped). Survivors are reported by pid.

This never signals this app's own process group or its own pid. `run` is injectable for tests.
"""
import os
import signal
import subprocess
import time


def _run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _pids(out):
    return [int(x) for x in out.split() if x.isdigit()]


def child_pids(pid=None, run=_run):
    """Direct children of `pid` (default: this process)."""
    pid = os.getpid() if pid is None else pid
    return _pids(run(["pgrep", "-P", str(pid)]))


def descendants(pid, run=_run):
    out, todo = [], [pid]
    while todo:
        for c in child_pids(todo.pop(), run=run):
            if c not in out and c != pid:
                out.append(c)
                todo.append(c)
    return out


def group_members(pgid, run=_run):
    return _pids(run(["pgrep", "-g", str(pgid)]))


def alive(pid, run=_run):
    """False once the process is gone or is a zombie (it has exited; only the reap is pending)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    stat = run(["ps", "-o", "stat=", "-p", str(pid)]).strip()
    return bool(stat) and not stat.startswith("Z")


def _wait_gone(pids, timeout, run):
    end = time.monotonic() + timeout
    left = [p for p in pids if alive(p, run=run)]
    while left and time.monotonic() < end:
        time.sleep(0.05)
        left = [p for p in left if alive(p, run=run)]
    return left


def stop_tree(roots, term_wait=1.5, kill_wait=1.0, run=_run):
    """Stop every process under `roots`. Returns {"targets", "stopped", "survivors"} (pid lists).
    `stopped` holds only pids verified gone; nothing is counted because a signal was sent."""
    me, own_group = os.getpid(), os.getpgrp()
    targets, groups = [], []
    for r in roots:
        try:
            pg = os.getpgid(r)
        except OSError:
            pg = None
        members = []
        if pg is not None and pg == r and pg != own_group:
            groups.append(pg)
            members = group_members(pg, run=run)
        for p in [r] + descendants(r, run=run) + members:
            if p != me and p not in targets:
                targets.append(p)

    def send(sig, pids):
        for g in groups:
            try:
                os.killpg(g, sig)
            except OSError:
                pass
        for p in pids:
            try:
                os.kill(p, sig)
            except OSError:
                pass

    send(signal.SIGTERM, targets)
    left = _wait_gone(targets, term_wait, run)
    if left:
        send(signal.SIGKILL, left)
        left = _wait_gone(left, kill_wait, run)
    return {"targets": targets, "stopped": [p for p in targets if p not in left],
            "survivors": left}


def describe(result):
    """One honest line for the PANIC banner."""
    n, ok, bad = len(result["targets"]), len(result["stopped"]), result["survivors"]
    if not n:
        return "no child processes were running"
    text = "%d of %d child process(es) stopped (verified gone)" % (ok, n)
    if bad:
        text += " · %d SURVIVED: pid %s" % (len(bad), ", ".join(str(p) for p in bad))
    return text
