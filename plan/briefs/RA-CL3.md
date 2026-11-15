# RA-CL3 — cold re-audit of CL3 (`fix/cl3-evidence` @ 3208b70+)

**FRESH session.** Mythos preferred (`/model claude-opus-5-5` on a safeguard block). Auditor only.
Own worktree (`git worktree add ../wt-RA-CL3 origin/fix/cl3-evidence`). Token budget per
`README.md`. Read the PDF §5 G6/G7, H9, C2, E5 and `plan/briefs/CL3-report.md` only at step 3.

1. Re-derive every audit PoC against `chain.py` + `engagement.py` + `executor.py`:
   rewrite each field of a record (operator, engagement, seq, file/argv, target, exit code) →
   must fail verification; drop last / middle record; re-forge with a guessed key; delete or
   edit `.head`; swap two chains' files; restart → no second genesis; write failure → raises
   AND the gate refuses (authorize_action, executor.issue) with nothing minted; refusals and
   executions (exit code, kills) present; one chain shared by RECON/FORGE and by a real bound
   child process (`gatestate.child_env`), concurrent appends from 2+ processes verify.
2. Attack the design: key/head/jsonl permissions; symlink or pre-existing file at the chain path
   at create; a `.key` shorter than 32 bytes or world-readable; TOCTOU between verify and append
   under `flock`; what a same-user attacker with the key can still do (state it plainly);
   `canonical()` collisions (unicode, floats, key order); records with user-controlled strings
   containing newlines; a chain id with `/` or `..`; the session chain for TX-only tickets;
   END while a process is running (kill record lands in the right chain).
3. H9: the ENGAGEMENT panel shows AUTHORIZED vs EXECUTED/FAILED/KILLED/REFUSED from the chain and
   never from memory; render at 1280×720 dark+sun, no clipping / no h-scroll; caption says
   NOT VERIFIED when the file is tampered. C2: no `sh -c` anywhere in `evidence.py`. E5: report
   written from a verified chain only; refuses on a tampered one.
4. Regression: `tests/test_cl3_evidence.py`, `test_engagement.py`, `test_evidence.py`,
   `test_cl2_*.py`, then the full suite once on Python 3.12; diff denial assertions vs `93aaf27`.
5. Write `plan/briefs/RA-CL3-report.md` on the branch, push, remove the worktree. Table per ID +
   new findings + one line MERGE / DO NOT MERGE. A forgeable or silently-lossy trail, or an
   authorization without a record, blocks; hygiene is a follow-up.

Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` +
`Claude-Session: https://claude.ai/code/session_01DNwALPN1Ydsu8Kidx4CrT4`
