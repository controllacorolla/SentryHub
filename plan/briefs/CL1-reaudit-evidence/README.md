# RA-CL1 evidence (copied from the implementer's scratchpad, 2026-11-15)

`reaudit_result.json` is the full RA-CL1 workflow result: per auditor, the CLOSED verdicts,
the non-closed verdicts with an independent verifier's `check`, verified new findings, and
unverified Low findings. Each subdirectory holds the PoC scripts and text output of one
auditor or verifier, named by topic.

Not copied: rendered PNGs (`*.png` is git-ignored) and the 64 full source-tree copies the
auditors made for mutation testing (main / base / mutant trees). Scripts that reference
those trees by absolute scratchpad path will need the tree re-created with
`git archive <rev> | tar -x -C <dir>`.
