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
   State file: <orch_dir>/state.json
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
   **Before running install:** check `state.preflight_warnings` for `dependencies_likely_stale` — if present, the suggested install command is pre-identified; run it directly.

**Step 3 — Is a path or configuration wrong?**
Compare the error's file path against the worktree. If a symlink, path alias, or config reference is broken: fix it directly (create symlink, update config path) and retry.

**Step 4 — Does the test require a running service?**
Check if the failure mentions a DB, server, or external service. If needed and startable: start it and retry. If not startable in this environment: escalate to the user with `SKIPPED` rationale and full diagnostic output from each step.

If none of the 4 steps resolve it: record the task as `SKIPPED` in state.json and report to the user with the full diagnostic log.

## ENV_BLOCKER Category Triage (v2.11)

When the 4-step generic triage produces a clear root cause, classify it into a category. The category becomes the `root_cause_category` field on the `verification_failure` learning event.

| Category | Symptom signature | Diagnostic | Resolution |
|----------|-------------------|------------|------------|
| `docker_oom` | Container exit code 137, "Killed" in build log, BuildKit step terminated without error message after long pause | `docker inspect <container-id> --format '{{.State.OOMKilled}}'` — `true` confirms; `docker stats` snapshot if container still alive | Increase Docker Desktop memory or set `--memory` flag higher; do NOT re-classify as compile failure |
| `gradle_daemon_disappearance` | "Daemon disappeared", "Gradle build daemon disappeared unexpectedly", "Could not connect to Gradle daemon" | Read `~/.gradle/daemon/<version>/daemon-*.out.log`; last 50 lines reveal sub-cause | If log says OOMError → `gradle_metaspace` (below) or heap; if "JVM crashed" → daemon crash, retry once with `--no-daemon` |
| `gradle_metaspace` | "java.lang.OutOfMemoryError: Metaspace" in daemon log or stderr | grep daemon log for `Metaspace` | Set `org.gradle.jvmargs=-Xmx2g -XX:MaxMetaspaceSize=1g` in `gradle.properties`; retry |
| `node_heap_oom` | "JavaScript heap out of memory", "FATAL ERROR: Reached heap limit Allocation failed" | `node --version`; `echo $NODE_OPTIONS` | `export NODE_OPTIONS=--max-old-space-size=4096`; retry |
| `service_unreachable` | "ECONNREFUSED", "connection refused", "no route to host", "host unreachable" | `nc -z <host> <port>`; `curl --max-time 2 <url>` | Start the service or escalate to user with the unreachable host:port pair |
| `other` | None of the above patterns match | n/a | Fall through to standard SKIPPED with full diagnostic log |

**Recording:** When a category resolves an ENV_BLOCKER, write the resolution to the learning log via a candidate event with `event_type: "verification_failure"` and `context.root_cause_category: "<category>"`. The orchestrator's standard Phase 1 Step 3.5 scan forwards it.

**Never re-classify based on a category:** `docker_oom` is not a code defect, regardless of how the build error reads in the log. If the category is established, do not Implementer-retry as a code issue.

<!-- for_next_tasks: Task 8 may append additional ENV_BLOCKER triage content or new playbook sections below this point -->

## Document-update rules

- You (Orchestrator) update all documents yourself. Never delegate spec or plan updates to a sub-agent.
- After updating any document, re-read it fully before building the next sub-agent prompt.

## Learning log: ESCALATE → event mapping (v2.8)

When a sub-agent ESCALATEs, it writes a candidate JSON to
`<orch_dir>/learning_events/task_<N>-<role>.json`. The
orchestrator's Phase 1 Step 3.5 scan picks it up and forwards to `append`.

Severity mapping by ESCALATE type:

| Type | severity | Notes |
|---|---|---|
| `SPEC_BLOCKER` | `medium` | Resolvable by orchestrator spec-edit; learning value is which ambiguity recurred |
| `ENV_BLOCKER` | `high` if Triage steps 1-4 all fail; `medium` if Triage resolves | Learning value is the missing env knowledge |
| `AMBIGUITY` | `medium` | Resolvable by orchestrator plan-edit; learning value is which plan section is consistently unclear |

If the same ISSUE_KEY recurs across retries (same task, same root cause), the
orchestrator additionally emits a `recurring_issue` event AFTER the
`escalation` event — that pattern is the strongest "fix the prompt" signal
the skill has.

If the orchestrator's ESCALATE handling (spec edit / plan edit / triage)
resolves the blocker and execution continues, that recovery is a
`successful_workaround` signal IF the resolution generalizes (e.g., "spec
section X always needs clarification of Y"). The Implementer prompt
instructs sub-agents to write this candidate themselves — see
`implementer-prompt.md` §Learning log emit.
