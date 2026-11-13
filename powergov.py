#!/usr/bin/env python3
"""powergov.py — power / thermal governor (uConsole-specific capability).

The uConsole browns out under sustained all-core load on battery, and throttles when hot. This
governor watches battery %, charge state, temperature and the Pi undervoltage flags, picks a power
mode, and hands each module a policy (how many radio workers may run at once, a CPU-thread cap, a
duty-cycle, and which modules are allowed) so an unattended field deployment survives on battery
instead of rebooting. Pure decision logic is unit-testable; it reads live state from suite helpers.
"""
import os
import sys

MODES = ("full", "reduced", "minimal", "critical")

# Per-mode operating policy.
#   max_workers : how many radio decoder workers may run concurrently
#   num_thread  : CPU-thread cap handed to decoders / inference
#   duty        : fraction of time heavy work may run (duty-cycling for unattended runs)
#   allow       : which modules may run — 'all', 'priority' (alerts/watch only), or 'none'
POLICY = {
    "full":     {"max_workers": 3, "num_thread": 4, "duty": 1.0, "allow": "all"},
    "reduced":  {"max_workers": 2, "num_thread": 2, "duty": 1.0, "allow": "all"},
    "minimal":  {"max_workers": 1, "num_thread": 2, "duty": 0.5, "allow": "priority"},
    "critical": {"max_workers": 0, "num_thread": 1, "duty": 0.15, "allow": "none"},
}


def decide_mode(battery_pct, charging, temp_c, undervolt=False, hot_c=78.0, warm_c=70.0):
    """Pick a power mode. Undervoltage or a near-dead battery -> critical; heat -> throttle; on
    battery -> conserve by charge level; plugged in and cool -> full."""
    if undervolt:
        return "critical"
    if temp_c is not None and temp_c >= hot_c:
        return "critical"
    if not charging and battery_pct is not None and battery_pct <= 10:
        return "critical"
    if temp_c is not None and temp_c >= warm_c:
        return "minimal"
    if charging:
        return "full"
    if battery_pct is None:
        return "reduced"
    if battery_pct > 60:
        return "reduced"
    if battery_pct > 25:
        return "minimal"
    return "critical"


def policy_for(mode):
    return dict(POLICY.get(mode, POLICY["reduced"]))


class PowerGovernor:
    """Tracks the chosen mode and notifies on change. Hysteresis avoids flapping at a threshold."""

    def __init__(self, hysteresis=1):
        self.mode = "full"
        self.on_change = None
        self._pending = None
        self._count = 0
        self.hysteresis = hysteresis

    def update(self, battery_pct, charging, temp_c, undervolt=False):
        """Feed current state; returns (mode, policy). Fires on_change only when the mode changes
        and has been stable for `hysteresis` consecutive updates (critical applies immediately)."""
        want = decide_mode(battery_pct, charging, temp_c, undervolt)
        if want == self.mode:
            self._pending, self._count = None, 0
        elif want == "critical" or want == self._pending:
            self._count += 1
            if want == "critical" or self._count >= self.hysteresis:
                self.mode, self._pending, self._count = want, None, 0
                if self.on_change:
                    self.on_change(self.mode, policy_for(self.mode))
        else:
            self._pending, self._count = want, 1
        return self.mode, policy_for(self.mode)

    def allows(self, module_priority="normal"):
        """May a module run now? priority='critical' modules run except in 'none'."""
        allow = POLICY[self.mode]["allow"]
        if allow == "all":
            return True
        if allow == "priority":
            return module_priority in ("priority", "critical")
        return module_priority == "critical"


def read_state():
    """Best-effort live power/thermal snapshot from the Pi/uConsole."""
    battery, charging, temp_c, undervolt = None, False, None, False
    try:
        base = "/sys/class/power_supply"
        for d in os.listdir(base):
            cap = os.path.join(base, d, "capacity")
            status = os.path.join(base, d, "status")
            if os.path.exists(cap):
                battery = int(open(cap).read().strip())
            if os.path.exists(status):
                charging = open(status).read().strip().lower() in ("charging", "full")
    except (OSError, ValueError):
        pass
    try:
        temp_c = int(open("/sys/class/thermal/thermal_zone0/temp").read().strip()) / 1000.0
    except (OSError, ValueError):
        pass
    try:
        import subprocess
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True,
                             timeout=3).stdout
        val = int(out.split("=")[1], 16) if "=" in out else 0
        undervolt = bool(val & 0x1) or bool(val & 0x10000)      # under-voltage now / occurred
    except Exception:
        pass
    return battery, charging, temp_c, undervolt


# ---- process-wide singleton so any module and the hub share one governor -----------------
_GOV = PowerGovernor()


def governor():
    return _GOV


def poll():
    """Update the shared governor from live state; returns (mode, policy). Safe on any platform."""
    bat, chg, temp, uv = read_state()
    return _GOV.update(bat, chg, temp, uv)


def gate(priority="normal"):
    """A module calls this before starting heavy work: (allowed, policy). Defaults permissive, so
    it never blocks until the governor has actually seen a constrained state."""
    return _GOV.allows(priority), policy_for(_GOV.mode)


def main(parent=None):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("PowerGov")
    S.settings("powergov", {})
    root, F = S.make_root("Power Governor", parent=parent)
    import tkinter as tk
    T = S.T
    gov = PowerGovernor()
    S.top_bar(root, F, "Power Governor", "Brownout-aware duty-cycling")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    lbl = tk.Label(body, text="", font=F["mono"], fg=S.TXT, bg=S.BG, anchor="w", justify="left",
                   wraplength=T.px(700), padx=T.px(12), pady=T.px(10))
    lbl.pack(fill="both", expand=True)

    def tick():
        bat, chg, temp, uv = read_state()
        mode, pol = gov.update(bat, chg, temp, uv)
        col = {"full": S.GREEN, "reduced": S.GREEN, "minimal": S.AMBER, "critical": S.RED}[mode]
        lbl.config(text="Mode: %s\nbattery %s%%  %s  %s°C%s\n\nworkers<=%d  threads<=%d  duty %d%%  "
                        "allow=%s" % (mode.upper(), bat, "charging" if chg else "on battery",
                                      round(temp) if temp else "?", "  UNDERVOLT" if uv else "",
                                      pol["max_workers"], pol["num_thread"], int(pol["duty"] * 100),
                                      pol["allow"]), fg=col)
        root.after(3000, tick)
    tick()
    S.bind_quit(root, lambda: root.destroy())
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
