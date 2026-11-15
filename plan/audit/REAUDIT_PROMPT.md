# Re-audit prompt (run in a fresh chat, no prior context, per cluster)

Replace `<BRANCH>` and `<IDS>` and paste.

```
I'm the author of https://github.com/controllacorolla/SentryHub. An independent audit of main
(plan/audit/PALISADE_full_audit_report_2026-11-15.pdf — read it first, and
plan/audit/AUDIT_INDEX.md) produced 93 findings. Branch <BRANCH> claims to fix this set:

  <IDS>

Your job is to falsify that claim, finding by finding. For each ID:
  - Re-run or re-derive the report's PoC against <BRANCH>. Does it still reproduce?
  - If fixed: say so, cite file:line of the fix, and name the regression test that pins it.
    If there is no test, the finding is NOT closed.
  - If not fixed, partially fixed, or fixed in a way that introduces a new problem: say
    exactly what remains, with a PoC.
  - Check for regressions the fix introduced elsewhere: run the suite headless, render every
    page at exactly 1280×720 (dark, light, sun · live, demo), and diff behaviour against main
    for anything the branch touched.

Then, separately: anything NEW you find on this branch that was not in the 93, with the same
severity scale (Critical = bypass to a real emission, false all-clear in the safety-critical
use, or unusable on the target screen; High = gate or display wrong in a way an operator would
rely on; Medium = wrong but fails safe; Low = hygiene).

Deliverable: a table — ID · CLOSED / OPEN / PARTIAL / REGRESSED · evidence · test name — then
new findings, then a one-line verdict: MERGE or DO NOT MERGE. Be adversarial. The previous
round's self-review missed all 93 of these.
```
