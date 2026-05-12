# Escalation Playbook

Read when a sub-agent sends `ESCALATE`, or when ENV_BLOCKER triage is needed.

## ESCALATE message format (from sub-agent)

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

## Orchestrator response

1. **Increment `task.escalation_count`.** If `> 3` for this task: halt **that task only** (not the entire run):
   ```
   HALTED: Task <N> exceeded maximum escalations (3).
   Last escalation: <blocker text>
   Branch: <branch name>
   State file: <worktree_path>/.orchestrator/state.json
   Manual intervention required for Task <N>.
   ```
   Record the task as SKIPPED in state.json with the escalation reason. The orchestrator continues with subsequent tasks (subject to SKIPPED propagation from Phase 0 Step 6).

2. **Reset to pre-task state** using the literal SHA recorded for this task:
   ```bash
   git -C <worktree_path> reset --hard <pre_task_sha>
   ```

3. **Act based on type:**

   | Type | Action |
   |------|--------|
   | `SPEC_BLOCKER` | Make the smallest spec edit that resolves the contradiction. Re-read the spec. Re-dispatch Implementer from clean state. |
   | `ENV_BLOCKER` | Run the ENV_BLOCKER Triage Playbook below before escalating to the user. |
   | `AMBIGUITY` | Edit the plan with an explicit decision that resolves the ambiguity. Re-read the plan. Re-dispatch Implementer from clean state. |

4. **After resolving:** return to Step 1 of the task and re-run all steps in sequence. Do NOT skip Combined Review or Verification.

## ENV_BLOCKER Triage Playbook

Work through these in order before escalating to the user:

**Step 1 — Can the test suite run at all?**
Run the `test_command` from state.json. If it fails with command-not-found, config error, or missing file (not a test failure): that is the environment issue — continue to Step 2.

**Step 2 — Is a dependency missing?**
Check `package.json` / `pyproject.toml` / `Cargo.toml` / `build.gradle` against the installed state. If missing: run the install command (`npm install`, `pip install -e .`, `cargo fetch`, etc.) and retry the test command.

**Step 3 — Is a path or configuration wrong?**
Compare the error's file path against the worktree. If a symlink, path alias, or config reference is broken: fix it directly (create symlink, update config path) and retry.

**Step 4 — Does the test require a running service?**
Check if the failure mentions a DB, server, or external service. If needed and startable: start it and retry. If not startable in this environment: escalate to the user with `SKIPPED` rationale and full diagnostic output from each step.

If none of the 4 steps resolve it: record the task as `SKIPPED` in state.json and report to the user with the full diagnostic log.

## Document-update rules

- You (Orchestrator) update all documents yourself. Never delegate spec or plan updates to a sub-agent.
- After updating any document, re-read it fully before building the next sub-agent prompt.
