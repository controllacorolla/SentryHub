"""argsafe — values from settings files become argv tokens only after a strict check (audit L4).

Settings files (`~/.config/uconsole-suite/*.json`) are data a restored backup can write. Before
CL8 a pager.json frequency of `929.6M -M fm; id > /tmp/x #` reached `sh -c`. Now:

  * every decoder pipeline is a list of argv lists — no shell, ever (`spawn_pipeline`);
  * a frequency or gain from settings must match a strict pattern, or the decoder refuses to
    start with a ValueError that the page shows (never a silent default).

No third-party or Tk imports: the Qt pages and the legacy Tk apps both use this module.
"""
import re
import subprocess

# 929.6M · 162.400M · 145800000 · 88.5e6 · 433.92M · 1090M  (Hz, or k/M/G suffixed)
class SettingsRefused(ValueError):
    """A settings value failed its check. A ValueError, so old callers still catch it; pages
    catch this one by name so a parser's ValueError is never mistaken for a settings fault."""


_FREQ_RE = re.compile(r"^\d{1,10}(\.\d{1,6})?([eE][+]?\d{1,2})?[kKMG]?$")
# no '/' and no leading '~' or '.': a template may not point the decoder at a file path outside
# its working directory (rtl_433 -w, acarsdec --output …:path=). Documented limit: a pinned
# program may still be given a bare relative filename.
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_,:=+-][A-Za-z0-9_.,:=+-]*$")


def freq_arg(value):
    """A frequency from settings -> the exact string handed to rtl_fm/rtl_433. Raises ValueError
    for anything that is not a plain number with an optional k/M/G suffix."""
    if isinstance(value, bool):
        raise SettingsRefused("bad frequency: %r" % (value,))
    if isinstance(value, (int, float)):
        if not (0 < float(value) < 1e11):
            raise SettingsRefused("frequency out of range: %r" % (value,))
        return ("%d" % value) if float(value).is_integer() else repr(float(value))
    s = str(value).strip()
    if not _FREQ_RE.match(s):
        raise SettingsRefused("bad frequency in settings: %r (want e.g. 929.6M or 162400000)" % (s,))
    return s


def gain_arg(value):
    """A gain from settings -> int dB in 0..60 (0 = auto). Raises ValueError otherwise."""
    if isinstance(value, bool):
        raise SettingsRefused("bad gain: %r" % (value,))
    try:
        g = float(value)
    except (TypeError, ValueError):
        raise SettingsRefused("bad gain in settings: %r" % (value,))
    if not (0 <= g <= 60):
        raise SettingsRefused("gain out of range: %r" % (value,))
    return int(g)


def safe_tokens(argv, program=None):
    """Check an argv built from a settings template: every token is a plain word (no shell
    metacharacters, no spaces, no path separator), and argv[0] is `program` when given.
    Returns argv or raises SettingsRefused."""
    argv = list(argv)
    if not argv:
        raise SettingsRefused("empty command")
    if program is not None and argv[0] != program:
        raise SettingsRefused("settings may not change the program (%r, want %r)" % (argv[0], program))
    for t in argv:
        if not _SAFE_TOKEN.match(str(t)):
            raise SettingsRefused("unsafe argument in settings: %r" % (t,))
    return argv


class PipeGroup:
    """A list of argv stages run as one process group (no shell): stage 1 leads a new process
    group, later stages join it, stdout of each feeds the next. Quacks like the Popen the legacy
    Tk apps used (`.stdout`, `.pid` = the group id for `suite.stop_group`, `poll`, `wait`)."""

    def __init__(self, stages, stdout=subprocess.PIPE, stderr=None, **kw):
        if not stages:
            raise SettingsRefused("a pipeline needs at least one stage")
        self.procs = []
        prev = None
        try:
            for i, argv in enumerate(stages):
                last = i == len(stages) - 1
                opts = dict(stdin=prev if prev is not None else subprocess.DEVNULL,
                            stdout=stdout if last else subprocess.PIPE,
                            stderr=stderr if last else subprocess.DEVNULL)
                if last:
                    opts.update(kw)
                # stage 1 leads a NEW process group in our session (process_group=0); later
                # stages join it. (start_new_session would put stage 1 in another session,
                # and setpgid() across sessions fails with EPERM.)
                opts["process_group"] = 0 if i == 0 else self.procs[0].pid
                p = subprocess.Popen(list(argv), **opts)
                if prev is not None:
                    prev.close()
                prev = p.stdout if not last else None
                self.procs.append(p)
        except BaseException:
            if prev is not None:
                prev.close()
            for p in self.procs:
                try:
                    p.kill()
                    p.wait(2)
                except Exception:
                    pass
            raise
        self.pid = self.procs[0].pid           # the group id: os.killpg(pid, …) stops every stage
        self.stdout = self.procs[-1].stdout
        self.stderr = self.procs[-1].stderr

    def poll(self):
        codes = [p.poll() for p in self.procs]
        return next((c for c in codes if c is not None), None) if all(
            c is not None for c in codes) else None

    def wait(self, timeout=None):
        for p in self.procs:
            p.wait(timeout=timeout)
        return self.poll()


def spawn_pipeline(stages, **kw):
    return PipeGroup(stages, **kw)
