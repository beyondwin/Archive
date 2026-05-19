# Learning Log

Use this for execution-only learning events from `interactive` and `headless`
mode. `prompt` and `handoff` are not logging modes, although prompts exported
for future execution must carry this same contract.

After the v2.18 cutover, learning events are recorded directly to AgentLens
under the `kws-cpe.learning.<event>` namespace; the legacy
`scripts/append_learning_event.py` helper and the user-local sharded log
(`~/.codex/learning/kws-codex-plan-executor/runs/<date>/<run_id>/`) were
retired. Historical archives may still exist on disk for older runs but are no
longer written by this skill.

This stream is for improving `kws-codex-plan-executor` across repositories. It
is not the resume source of truth for a single run; the project-local
`.codex-orchestrator/runs/<run_id>/state.json` remains the per-run state file.
`.codex-orchestrator/state.json` may exist only as a backwards-compatible
latest-state copy or pointer.

Query the cross-repo learning stream by run with `agentlens events --run
"$ORCH_RUN_ID" --type 'kws-cpe.learning.*'`. Health reporters resolve a run's
terminal outcome from project-local
`.codex-orchestrator/runs/<run_id>/state.json` (the source of truth) and the
AgentLens `run-close` outcome; index/learning-log metadata is not consulted at
the post-cutover surface.

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

## Emit Lifecycle

Generate the run id and open the AgentLens orchestration run after the
worktree, plan, branch, and head are known:

```bash
RUN_ID="$(python3 scripts/generate_run_id.py \
  --repo-name "$REPO_NAME" --branch "$BRANCH" --head "$HEAD_SHA")"
RUN_DIR=".codex-orchestrator/runs/$RUN_ID"
STATE_PATH="$RUN_DIR/state.json"
ORCH_RUN_ID="$(agentlens run-open \
  --agent kws-cpe-orchestrator \
  --workspace "$WORKTREE_ABS" \
  --meta plan="$PLAN_REL" \
  --meta spec="${SPEC_REL:-}" \
  --meta mode="$MODE" \
  2>/dev/null || echo "")"
# Persist ORCH_RUN_ID as state.agentlens_orchestration_run at the first
# state.json write.
```

Emit a notable-boundary event when one occurs (`run-id`, `run_dir`, and
`state_path` belong in the payload so future agents can correlate back to the
run):

```bash
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens event append --run "$ORCH_RUN_ID" \
    --type "kws-cpe.learning.${EVENT_TYPE}" \
    --payload-json "$(cat /tmp/kws-codex-plan-executor-event.json)" \
    2>/dev/null || true
fi
```

Close the AgentLens orchestration run at the end or on whole-run halt:

```bash
if [ -n "${ORCH_RUN_ID:-}" ]; then
  agentlens run-close --run "$ORCH_RUN_ID" \
    --outcome "$OUTCOME" 2>/dev/null || true
fi
```

Valid `run-close` outcomes are `success`, `blocked`, and `aborted`.
AgentLens-emit failure must not block the user's primary implementation task.

Query recent runs and their outcomes:

```bash
agentlens runs --agent kws-cpe-orchestrator --latest 5
agentlens events --run "$ORCH_RUN_ID" --type 'kws-cpe.learning.*'
```

Compare a live run's project-local journal and historical user-local learning
log against the AgentLens stream with:

```bash
python3 scripts/compare_agentlens_events.py \
  --journal .codex-orchestrator/runs/<run_id>/events.jsonl \
  --learning ~/.codex/learning/kws-codex-plan-executor/runs/<date>/<run_id>/events.jsonl \
  <agentlens_run_dir>
```

The script reports matched / missing-in-agentlens / missing-in-legacy /
ordering-mismatch counts and exits non-zero if either layer drifts. The
embedded `--self-test` covers the rename contract (e.g.
`task_contract_recorded → kws-cpe.task_started`, `blocked → kws-cpe.blocker`,
`finished → kws-cpe.run_completed`) so mapping regressions fail fast.

## AgentLens Namespace Vocabulary

Active `kws-cpe.learning.<event>` types (clean prefix of legacy event types):

- `kws-cpe.learning.blocker`
- `kws-cpe.learning.error`
- `kws-cpe.learning.verification_failure`
- `kws-cpe.learning.recurring_issue`
- `kws-cpe.learning.user_correction`
- `kws-cpe.learning.successful_workaround`
- `kws-cpe.learning.completion_learning`

Headless `codex exec` spawns must propagate the parent id with
`AGENTLENS_PARENT_RUN_ID="$ORCH_RUN_ID"`. AgentLens failures are never
blocking. The legacy `scripts/append_learning_event.py` helper was removed at
the v2.18 cutover — AgentLens is the sole sink for these events.

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
