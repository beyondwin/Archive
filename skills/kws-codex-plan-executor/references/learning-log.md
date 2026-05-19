# Learning Log

Use this for execution-only learning events from `interactive` and `headless`
mode. `prompt` and `handoff` are not logging modes, although prompts exported
for future execution must carry this same contract.

The log is user-local and sharded by run:

```text
~/.codex/learning/kws-codex-plan-executor/
~/.codex/learning/kws-codex-plan-executor/runs/<YYYY-MM-DD>/<run_id>/events.jsonl
  index.jsonl
  runs/<YYYY-MM-DD>/<run_id>/
    meta.json
    events.jsonl
    final.json
```

This log is for improving `kws-codex-plan-executor` across repositories. It is
not the resume source of truth for a single run. Keep the project-local
`.codex-orchestrator/runs/<run_id>/state.json` as the per-run state file.
`.codex-orchestrator/state.json` may exist only as a backwards-compatible
latest-state copy or pointer.

`index.jsonl` is a run start index. Health reporters resolve status from
`runs/<date>/<run_id>/final.json` when present, then project-local
`.codex-orchestrator/runs/<run_id>/state.json` when available, then learning-log
metadata. A reporter may note that an index row still says `unknown`, but that
does not override a terminal `final.json` outcome.

## Run Identity

Every execution has a `run_id` shaped like:

```text
20260513T142233Z-archive-codex-example-7e884a0-a1b2c3
```

The id includes UTC time, repo slug, branch slug, head hash, and a random suffix.
Do not use timestamp alone; concurrent runs in the same project can start in the
same second.

## Event Types

Record only notable boundaries:

- `blocker`: plan, path, dirty worktree, resume ambiguity, or unclear scope
  stops execution.
- `error`: executor procedure fails independently of project code.
- `verification_failure`: test, lint, build, or acceptance command fails.
- `recurring_issue`: the same `ISSUE_KEY` appears again.
- `user_correction`: the user corrects executor scope, assumptions, allowed
  files, or direction.
- `successful_workaround`: a root-cause-based recovery reveals a reusable
  improvement.
- `completion_learning`: final completion reveals an actionable executor
  improvement.

Do not record routine task starts, routine task completions, or ordinary
success with no executor improvement.

`event_count=0` is normal for routine success because learning events are only
for notable boundaries. Do not treat a zero-event successful `final.json` as a
warning by itself.

A stale run is diagnostic, not a terminal lifecycle outcome. `meta.helper_pid`
and legacy `meta.pid` identify the helper process that wrote learning-log
metadata. They do not identify a durable Codex execution session, so health
reporters must not classify a run as stale from helper-pid liveness alone.
Missing `final.json` is normal while project-local state shows active task-loop
progress or pending final verification. Health reporting must not mutate project
state or user-local learning logs.

## redacted-context Rule

Store enough context for a future agent to improve the skill without reading
the original conversation. Do not store sensitive or bulky source material.

Allowed:

- repository name
- branch name
- relative plan path
- task id and phase
- relative file paths
- command names and arguments that do not expose secrets
- short failure excerpt
- root-cause summary
- proposed skill improvement target

Do not store secrets, tokens, API keys, cookies, credentials, private keys, or
authorization headers. Do not store full conversation transcripts. Do not store
long raw logs. Do not store absolute home paths such as
`/Users/<name>/<redacted>`. Do not store large file contents, unrelated user
files, or unrelated process details.

If a field cannot be safely summarized, omit the field or replace it with a
short redacted summary before calling the helper.

## Helper

Initialize the run after the worktree, plan, branch, and head are known:

```bash
RUN_ID="$(python3 scripts/append_learning_event.py init-run \
  --repo-root "$WORKTREE_ABS" \
  --repo-name "$REPO_NAME" \
  --branch "$BRANCH" \
  --head "$HEAD_SHA" \
  --plan-path "$PLAN_REL" \
  --spec-path "$SPEC_REL" \
  --mode "$MODE")"
RUN_DIR=".codex-orchestrator/runs/$RUN_ID"
STATE_PATH="$RUN_DIR/state.json"
```

Create an event candidate JSON file and append it:

```bash
python3 scripts/append_learning_event.py append \
  --run-id "$RUN_ID" \
  --event-json /tmp/kws-codex-plan-executor-event.json \
  --repo-root "$WORKTREE_ABS"
```

Close the run at the end or on whole-run halt:

```bash
python3 scripts/append_learning_event.py close-run \
  --run-id "$RUN_ID" \
  --outcome success
```

Valid outcomes are `success`, `blocked`, `error`, and `unknown`. For tests,
pass `--log-root <temp-root>`. For preflight validation, pass `--dry-run` to
`append`.

Summarize recent run health without mutating logs:

```bash
python3 scripts/check_learning_log_health.py --latest 5 --json
```

The health report uses public statuses `success`, `blocked`, `error`, `failed`,
`in_progress`, `needs_finalization`, `stale_candidate`, and `unknown`. It
includes `project_state` when the project-local state file is readable and
`git_state` when the recorded worktree can be inspected. The legacy top-level
`warnings` array mirrors `diagnostics.warnings`; new callers should prefer
`diagnostics.info` and `diagnostics.warnings`.

The helper validates required fields, enum values, redaction constraints, and
secret-like strings before appending one compact JSON object per line. It also
rejects candidates whose `run_id` does not match `--run-id`.

## AgentLens Dual-Write (parity window)

During the parity window, every `append` call also mirrors to AgentLens under
the `kws-cpe.learning.<event>` namespace. The orchestration run id is opened at
execution init with `agentlens run-open --agent kws-cpe-orchestrator
--workspace "$WORKTREE_ABS" --meta plan=...` and is persisted as the run-level
`agentlens_orchestration_run` field in
`.codex-orchestrator/runs/<run_id>/state.json`. Guard every emit:

```bash
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens event append --run "$ORCH_RUN_ID" \
    --type "kws-cpe.learning.${EVENT_TYPE}" \
    --payload-json "$(cat /tmp/kws-codex-plan-executor-event.json)" \
    2>/dev/null || true
fi
```

Expected `kws-cpe.learning.<event>` mirror types:

- `kws-cpe.learning.blocker`
- `kws-cpe.learning.error`
- `kws-cpe.learning.verification_failure`
- `kws-cpe.learning.recurring_issue`
- `kws-cpe.learning.user_correction`
- `kws-cpe.learning.successful_workaround`
- `kws-cpe.learning.completion_learning`

At `close-run` time, also call `agentlens run-close --run "$ORCH_RUN_ID"
--outcome <success|blocked|aborted> 2>/dev/null || true`. Headless `codex exec`
spawns must propagate the parent id with
`AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID"`. The legacy `append_learning_event.py`
helper stays in place alongside the AgentLens append until parity is verified.
AgentLens failures are never blocking.

## Minimal Event Shape

```json
{
  "schema_version": "1",
  "run_id": "20260513T142233Z-archive-codex-example-7e884a0-a1b2c3",
  "skill": "kws-codex-plan-executor",
  "skill_version": "1.8.1",
  "mode": "interactive",
  "event_type": "verification_failure",
  "severity": "medium",
  "repo": {"name": "Archive", "remote_hash": null, "branch": "codex/example"},
  "execution": {
    "plan_path": "skills/kws-codex-plan-executor/docs/experiments/example/PLAN.md",
    "task_id": "task_2",
    "phase": "verification",
    "run_dir": ".codex-orchestrator/runs/20260513T142233Z-archive-codex-example-7e884a0-a1b2c3",
    "state_path": ".codex-orchestrator/runs/20260513T142233Z-archive-codex-example-7e884a0-a1b2c3/state.json"
  },
  "summary": "Acceptance command failed after the implementation touched validator code.",
  "context": {
    "user_intent": "Execute the approved implementation plan.",
    "agent_expectation": "Targeted verification would close the task.",
    "actual_outcome": "A broader Python check was required.",
    "root_cause": "The plan under-declared affected files.",
    "evidence": [{"kind": "command", "value": "python3 scripts/validate_state.py state.json"}]
  },
  "improvement": {
    "target": "references/execution-cycle.md",
    "proposal": "Require risk upgrade when implementation touches files outside the declared block."
  },
  "privacy": {"redacted": true, "notes": "Home directory omitted."}
}
```

## Failure Policy

Learning-log failure must not fail the user's primary implementation task. If
the helper fails, mention the logging failure briefly in the checkpoint or final
summary and continue according to the original executor state. Do not weaken the
original blocker, verification, or retry rules.
