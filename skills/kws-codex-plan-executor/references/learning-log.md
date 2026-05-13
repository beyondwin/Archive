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

The helper validates required fields, enum values, redaction constraints, and
secret-like strings before appending one compact JSON object per line. It also
rejects candidates whose `run_id` does not match `--run-id`.

## Minimal Event Shape

```json
{
  "schema_version": "1",
  "run_id": "20260513T142233Z-archive-codex-example-7e884a0-a1b2c3",
  "skill": "kws-codex-plan-executor",
  "skill_version": "1.7.0",
  "mode": "interactive",
  "event_type": "verification_failure",
  "severity": "medium",
  "repo": {"name": "Archive", "remote_hash": null, "branch": "codex/example"},
  "execution": {
    "plan_path": "docs/superpowers/plans/example.md",
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
