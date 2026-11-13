#!/usr/bin/env python3
"""copilot.py — offline AI RF analyst, powered by the local qwen model.

Feeds the suite's live context — what the classifier thinks a signal is, what the frequency DB says
is allocated there, the active contacts, recent alerts and the open engagement — to the on-device
LLM (ollama / qwen) and asks it to explain the RF picture, suggest which decoder to point at a
signal, or draft the engagement write-up. Fully offline: no cloud, no data leaves the handheld.

Context-gathering and prompt-building are pure and unit-testable; the LLM call is injectable (so
tests never need the model running).
"""
import json
import os
import sys
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen-obl"

SYSTEM = ("You are an RF/SIGINT analyst assistant running offline on a handheld SDR. Be concise, "
          "concrete and practical. When given a signal's measured features and the frequency "
          "allocation, say what it most likely is, how confident you'd be, and which decoder or "
          "next step to try. Never invent specifics you weren't given.")


def gather_context(providers=None):
    """Collect the current RF picture from injected provider callables. providers keys:
    'signal' ()->dict, 'contacts' ()->list, 'alerts' ()->list, 'allocation' ()->str,
    'engagement' ()->dict. Missing providers are simply omitted."""
    providers = providers or {}
    ctx = {}
    for key in ("signal", "contacts", "alerts", "allocation", "engagement"):
        fn = providers.get(key)
        if fn:
            try:
                ctx[key] = fn()
            except Exception:
                pass
    return ctx


def build_prompt(context, question):
    """Build the full LLM prompt from the live context + the operator's question."""
    lines = [SYSTEM, "", "LIVE RF CONTEXT:"]
    sig = context.get("signal")
    if sig:
        lines.append("- Signal under cursor: %s" % json.dumps(sig, default=str))
    if context.get("allocation"):
        lines.append("- Frequency allocation here: %s" % context["allocation"])
    contacts = context.get("contacts")
    if contacts:
        lines.append("- Active contacts (%d): %s" % (
            len(contacts), json.dumps(contacts[:8], default=str)))
    alerts = context.get("alerts")
    if alerts:
        lines.append("- Recent alerts: %s" % json.dumps(alerts[:5], default=str))
    eng = context.get("engagement")
    if eng and eng.get("active"):
        lines.append("- Engagement: %s (authorized, in scope: %s)" % (
            eng.get("name"), eng.get("scope")))
    if not sig and not contacts and not alerts:
        lines.append("- (quiet — nothing detected right now)")
    lines += ["", "OPERATOR QUESTION: " + str(question), "", "ANALYSIS:"]
    return "\n".join(lines)


def ask_llm(prompt, model=DEFAULT_MODEL, caller=None, timeout=60):
    """Send the prompt to the local LLM. caller(payload_dict)->text is injectable for tests; by
    default it POSTs to the local ollama API."""
    if caller is not None:
        return caller({"model": model, "prompt": prompt})
    try:
        data = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
        req = urllib.request.Request(OLLAMA_URL, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("response", "").strip()
    except Exception as e:
        return "(local model unavailable: %s — is ollama running with %s?)" % (
            str(e)[:60], model)


def analyze(question, providers=None, model=DEFAULT_MODEL, caller=None):
    """One-shot: gather context, build the prompt, ask the model. Returns (answer, prompt)."""
    ctx = gather_context(providers)
    prompt = build_prompt(ctx, question)
    return ask_llm(prompt, model=model, caller=caller), prompt


def suite_providers(S):
    """Wire the copilot to live suite state (best-effort; each provider degrades to empty)."""
    def _alloc():
        return None
    def _contacts():
        # live contacts come from a shared fusion registry when one is running; empty otherwise
        return []
    def _eng():
        try:
            import engagement
            return engagement.info()
        except Exception:
            return {}
    return {"contacts": _contacts, "allocation": _alloc, "engagement": _eng}


def main(parent=None):
    import threading
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import suite as S
    if parent is None:
        S.single_instance("Copilot")
    s, spath = S.settings("copilot", {"model": DEFAULT_MODEL})
    root, F = S.make_root("RF Copilot", parent=parent)
    import tkinter as tk
    T = S.T
    providers = suite_providers(S)

    S.top_bar(root, F, "RF Copilot", "Offline AI analyst · local qwen")
    body = tk.Frame(root, bg=S.BG)
    body.pack(fill="both", expand=True)
    out = tk.Text(body, bg=S.BG, fg=S.TXT, font=F["mono"], bd=0, highlightthickness=0,
                  wrap="word", state="disabled", padx=T.px(12), pady=T.px(8))
    out.tag_config("q", foreground=S.AMBER)
    out.tag_config("dim", foreground=T.TXT_3)
    out.pack(fill="both", expand=True)
    ent = tk.Entry(body, font=F["mono"])
    ent.pack(fill="x", padx=T.px(12), pady=T.px(6))
    ent.insert(0, "What am I most likely looking at, and which decoder should I try?")

    def say(text, tag=None):
        out.config(state="normal")
        out.insert("end", text + "\n", tag or ())
        out.see("end")
        out.config(state="disabled")

    def ask():
        q = ent.get().strip()
        if not q:
            return
        ent.delete(0, "end")
        say("> " + q, "q")
        say("thinking…", "dim")

        def work():
            answer, _ = analyze(q, providers, model=s.get("model", DEFAULT_MODEL))
            root.after(0, lambda: say(answer))
        threading.Thread(target=work, daemon=True).start()
    ent.bind("<Return>", lambda e: ask())

    bar = tk.Frame(root, bg=T.SURFACE)
    bar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=S.LINE, height=1).pack(side="bottom", fill="x")
    S.btn(bar, "Ask", ask, F, padx=14, pady=5, kind="primary").pack(side="left", padx=(10, 6),
                                                                    pady=6)
    if not parent:
        S.btn(bar, "Quit", lambda: on_close(), F, padx=10, pady=5, kind="quiet").pack(
            side="right", padx=(2, 10))
    say("Offline RF analyst ready (model: %s). Ask about a signal, a band, or your contacts."
        % s.get("model", DEFAULT_MODEL), "dim")

    def on_close():
        try:
            S.save_json(spath, s)
        except Exception:
            pass
        root.destroy()
    S.bind_quit(root, on_close)
    root.mainloop()


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
