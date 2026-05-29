# Escalation Protocol

> **Loaded by**: `references/phases/phase-1-task-cycle.md` (and the Parallel
> Sub-Flow) — Read when any sub-agent returns `STATUS: ESCALATE`.
>
> **Scope**: the orchestrator's response to ESCALATE signals (AMBIGUITY,
> SPEC_BLOCKER, ENV_BLOCKER, and the escalation cap), plus the ENV_BLOCKER triage
> pointer to `references/escalation-playbook.md`. The ESCALATE enum summary stays
> in SKILL.md's safety-gates section; this file holds the full response procedure.
>
> **Why extracted**: escalation handling is invoked by reference from Phase 1 and
> the Parallel Sub-Flow rather than run inline every task. v2.21 D005.

---

## Escalation Protocol

### When a sub-agent sends ESCALATE

```
ESCALATE
type: SPEC_BLOCKER | ENV_BLOCKER | AMBIGUITY
task: <task id>
blocker: <one-sentence description>
attempted: <what was tried>
cause: <suspected root cause>
options:
  A: <option>
  B: <option>
  C: <option>
```

### Your response

1. Increment **both** counters via atomic R-M-W of state.json:
   - **Run-level transient:** `state.current_escalation_count += 1` (carries across resume so the cap survives orchestrator restart mid-task).
   - **Task-level persistent:** `<active>.tasks.task_<N>.escalations += 1` (the final value recorded with the task; visible in the Final Summary Report's Escalations column).

   Both fields track the same logical counter and MUST move together — divergence is a bug. The cap check below uses the run-level field (`current_escalation_count`) since that's what's live in the orchestrator's working state; on resume the value is re-read from state.json.

   If `current_escalation_count > 3`: halt **that task only** (not the entire run):
   ```
   HALTED: Task <N> exceeded maximum escalations (3).
   Last escalation: <blocker text>
   Branch: <branch name>
   State file: <orch_dir>/state.json
   Manual intervention required for Task <N>.
   ```
   Record the task as SKIPPED in state.json with the escalation reason. The orchestrator continues with subsequent tasks (subject to SKIPPED propagation rules from Phase 0 Step 6).

   **Run close (v2.17):** if this exhausted-escalation halt aborts the entire run (whole-orchestrator halt, not just task skip), emit a `kws-cme.blocker` event and close the AgentLens run before exiting:
   ```bash
   if [ -n "${ORCH_RUN_ID:-}" ]; then
     agentlens event append --run "$ORCH_RUN_ID" \
       --type kws-cme.blocker \
       --payload-json "$(jq -nc --arg task "task_<N>" --arg reason "escalation_exhausted" '{task:$task, reason:$reason}')" 2>/dev/null || true
     agentlens run-close --run "$ORCH_RUN_ID" --outcome aborted 2>/dev/null || true
   fi
   ```

   For the more common case (task-only halt that lets the orchestrator continue), do NOT close-run — the run is still alive. Phase 2 Step 2 closes it with `outcome=success` if subsequent tasks finish, or the final hard-halt block does so with `outcome=blocked` if the orchestrator gives up entirely.

2. Reset to pre-task state using the literal SHA from your notes:
   ```bash
   git -C <worktree_path> reset --hard <pre_task_sha>
   ```

3. Act based on type:

| Type | Your action |
|------|-------------|
| `SPEC_BLOCKER` | Make the smallest possible edit to the spec that resolves the contradiction. Re-read the spec. Re-dispatch Implementer from clean state. |
| `ENV_BLOCKER` | Run the **ENV_BLOCKER Triage Playbook** below before escalating to the user. |
| `AMBIGUITY` | Edit the plan with an explicit decision that resolves the ambiguity. Re-read the plan. Re-dispatch Implementer from clean state. |

4. After resolving: return to Step 1 and re-run all steps in sequence. Do NOT skip Combined Review or Verification.

### ENV_BLOCKER Triage Playbook

See `references/escalation-playbook.md` (the ENV_BLOCKER Triage section). Read it at the moment an `ENV_BLOCKER` arrives. The same file also contains the canonical orchestrator response procedure and the document-update rules referenced above.

**Rule (kept here for prominence):** You (Orchestrator) update all documents yourself. Never delegate spec or plan updates to a sub-agent. After updating any document, re-read it fully before building the next sub-agent prompt.

