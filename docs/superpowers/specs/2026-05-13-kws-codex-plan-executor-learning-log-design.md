# KWS Codex Plan Executor Learning Log Design

Date: 2026-05-13
Owner: 김우승

## Purpose

이 문서는 `kws-codex-plan-executor`에 user-local learning loop를 추가하기 위한 설계안이다.

목표는 executor가 여러 repository에서 실제 계획을 실행하면서 마주친 실패, 오류, 사용자 정정, 반복 이슈, 좋은 해결 패턴을 구조화된 JSONL로 남기는 것이다. 이 로그는 개별 실행을 재개하기 위한 `.codex-orchestrator/state.json`과 다르다. `state.json`은 해당 worktree의 실행 상태를 복구하기 위한 자료이고, learning log는 나중에 Archive repository에서 executor skill 자체를 개선하기 위한 장기 학습 자료다.

선택한 방향은 `schema + helper script` 방식이다. 지시문만으로 로그를 남기면 agent마다 기록 품질이 흔들릴 수 있으므로, `kws-codex-plan-executor` 패키지 안에 schema 문서와 append helper를 두어 최소한의 품질과 privacy guard를 강제한다.

## Chosen Direction

적용 범위는 `execution-only`다.

- 기록 대상 모드: `interactive`, `headless`
- 제외 모드: `prompt`, `handoff`

기록 시점은 `notable-boundaries`다.

- `blocker`: plan/path/dirty worktree/unclear scope 때문에 멈춘 경우
- `error`: skill 절차나 실행 자체가 깨진 경우
- `verification_failure`: 테스트, lint, build, acceptance command가 실패한 경우
- `recurring_issue`: 같은 `ISSUE_KEY`가 다시 나온 경우
- `user_correction`: 사용자가 executor의 범위, 가정, 방향을 정정한 경우
- `successful_workaround`: 원인 기반 해결이나 좋은 절차 개선 신호가 나온 경우
- `completion_learning`: 최종 완료 시 executor 개선에 유의미한 관찰이 있는 경우

privacy 기준은 `redacted-context`다. agent가 나중에 맥락을 잃지 않고 개선 작업을 할 수 있을 정도의 요약과 증거 포인터는 남기되, 전체 대화, 긴 로그, secret, 절대 home path는 저장하지 않는다.

## File Structure

Create:

- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/learning-log.md`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/append_learning_event.py`

Modify:

- `ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/execution-cycle.md`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/headless-runner.md`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/change-protocol.md`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/common-mistakes.md`
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_skill_contract.py`
- release metadata and package docs required by `references/change-protocol.md`

Optional later, not required for the first implementation:

- `ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/validate_learning_log.py`
- aggregation/reporting command for reviewing recent learning events

## Storage Contract

The helper appends one JSON object per line to:

```text
~/.codex/learning/kws-codex-plan-executor/events.jsonl
```

The helper creates the parent directory if needed. It must append atomically enough for normal single-agent use. It does not write to the target repository unless the caller separately updates `.codex-orchestrator/state.json`.

The user-local log is intentionally outside project repositories because the learning target is the executor skill, not any individual repository where it ran.

## Event Schema

Each JSONL event must include:

```json
{
  "schema_version": "1",
  "timestamp": "2026-05-13T12:00:00Z",
  "skill": "kws-codex-plan-executor",
  "skill_version": "1.2.1",
  "mode": "interactive",
  "event_type": "verification_failure",
  "severity": "medium",
  "repo": {
    "name": "Archive",
    "remote_hash": null,
    "branch": "codex/example"
  },
  "execution": {
    "plan_path": "docs/superpowers/plans/example.md",
    "task_id": "task_2",
    "phase": "verification",
    "state_path": ".codex-orchestrator/state.json"
  },
  "summary": "Acceptance command failed because the plan declared docs-only verification but implementation changed a Python validator.",
  "context": {
    "user_intent": "Execute the approved implementation plan without touching unrelated files.",
    "agent_expectation": "Targeted docs verification would close the task.",
    "actual_outcome": "A code-path change required a broader Python check.",
    "root_cause": "The plan file block under-declared affected files.",
    "evidence": [
      {
        "kind": "command",
        "value": "python3 scripts/validate_state.py .codex-orchestrator/state.json"
      },
      {
        "kind": "relative_path",
        "value": "scripts/validate_state.py"
      }
    ]
  },
  "improvement": {
    "target": "references/execution-cycle.md",
    "proposal": "When task implementation touches validator code not declared in Files, require risk upgrade and broader verification before completion."
  },
  "privacy": {
    "redacted": true,
    "notes": "Home directory and raw output path omitted."
  }
}
```

Allowed `mode` values:

- `interactive`
- `headless`

Allowed `event_type` values:

- `blocker`
- `error`
- `verification_failure`
- `recurring_issue`
- `user_correction`
- `successful_workaround`
- `completion_learning`

Allowed `severity` values:

- `low`: useful improvement signal, no execution risk
- `medium`: caused retry, scope correction, verification change, or user correction
- `high`: blocked execution, risked wrong files, or exposed a hard contract gap

## Redaction Rules

The helper must reject or sanitize unsafe input before append.

Required protections:

- Do not store secrets, tokens, API keys, cookies, credentials, private keys, or authorization headers.
- Do not store full conversation transcripts.
- Do not store long raw logs. Use a short excerpt or a relative raw-output path when available.
- Do not store absolute home paths such as `/Users/<name>/<redacted>`; convert workspace paths to repository-relative paths where possible.
- Do not store large file contents.
- Do not store unrelated user files or unrelated process details.

Allowed context:

- repository name
- branch name
- relative plan path
- task id and phase
- relative file paths
- command names and arguments when they do not expose secrets
- short failure excerpt
- root-cause summary
- proposed skill improvement target

If the helper cannot confidently sanitize a field, it should fail closed and tell the caller what field needs to be summarized manually.

## Helper Interface

The first implementation should keep the script simple and explicit.

Example call:

```bash
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/append_learning_event.py \
  --event-json /tmp/kws-codex-plan-executor-event.json
```

Supported options:

- `--event-json <path>`: required path to a JSON event candidate
- `--log-path <path>`: optional override for tests; default is `~/.codex/learning/kws-codex-plan-executor/events.jsonl`
- `--repo-root <path>`: optional root used to relativize paths
- `--dry-run`: validate and print sanitized JSON without appending

The script should:

1. Load JSON.
2. Validate required fields and enum values.
3. Redact or reject unsafe path and secret-like values.
4. Add `timestamp` if missing.
5. Ensure `skill` is `kws-codex-plan-executor`.
6. Append one compact JSON line to the log path.
7. Print the appended event id or sanitized summary.

The event id can be deterministic enough for reference, for example a short hash of timestamp, repo name, event type, task id, and summary.

## Runtime Flow

`interactive` and `headless` execution should call the helper at notable boundaries.

Preflight:

- If plan parsing fails, record `blocker`.
- If related dirty files block execution, record `blocker`.
- If `resume=latest` is ambiguous, record `blocker`.

Task loop:

- If verification fails, record `verification_failure` after raw output is preserved.
- If the same `ISSUE_KEY` recurs, record `recurring_issue`.
- If user correction changes scope, allowed files, or assumptions, record `user_correction`.
- If an error comes from executor procedure rather than project code, record `error`.
- If a root-cause-based workaround reveals a reusable improvement, record `successful_workaround`.

Finish:

- Record `completion_learning` only when there is an actionable executor improvement. Do not log routine successful completions.

The helper call should not replace `.codex-orchestrator/state.json`, checkpoint, or final summary. It is an additional long-term learning signal.

## Error Handling

Learning-log failure must not fail the user's primary implementation task.

If helper validation fails:

- report the logging failure briefly
- continue or stop based on the original executor state, not the logging failure
- do not weaken the original blocker, verification, or retry rules

If the log path cannot be written:

- preserve the event candidate under `.codex-orchestrator/raw/` if that directory exists
- mention the write failure in the checkpoint or final summary
- do not retry indefinitely

If an event contains unsafe content:

- reject the event and request a summarized replacement from the agent's own context
- never append known-sensitive data

## Prompt And Headless Alignment

The runtime instructions and prompt export template must stay aligned.

Although `prompt` and `handoff` modes do not write learning events themselves, prompts generated for a future execution session should include the same execution-only learning-log contract. Otherwise prompt-exported runs would drift from interactive runs.

`headless-runner.md` must state that the helper writes to user-local `~/.codex/learning/kws-codex-plan-executor/events.jsonl`, while headless artifacts such as `headless.jsonl` and `headless-final.md` remain under `.codex-orchestrator/`.

## Testing

Add deterministic checks for the new behavior.

Script-level checks:

- valid event appends one JSONL line
- `--dry-run` validates without writing
- missing required fields fail
- invalid `mode`, `event_type`, or `severity` fail
- absolute home paths are rejected or sanitized
- secret-like fields are rejected
- `--log-path` override works for temp-dir tests

Contract checks:

- `check_skill_contract.py` verifies `SKILL.md` references execution-only learning log behavior
- `check_skill_contract.py` verifies `references/learning-log.md` exists
- `check_skill_contract.py` verifies `templates/fresh-session-prompt.txt` includes the execution-mode learning-log contract
- `check_skill_contract.py` verifies prompt/handoff modes are not themselves logging modes

Package validation:

- `python3 scripts/append_learning_event.py --help`
- existing `parse_plan.py`, `validate_state.py`, prompt, execution, state schema, and skill contract checks
- skill quick validation and package sync tests from `references/change-protocol.md`

## Non-Goals

This design does not add:

- automatic skill self-modification
- cross-machine log syncing
- repository-local learning logs
- full transcript capture
- broad telemetry
- all-skills global logging
- logging for `prompt` and `handoff` generation itself

## Success Criteria

The implementation is successful when:

- execution runs can append contextual, redacted learning events to user-local JSONL
- event quality is enforced by a helper script rather than prose alone
- logging failures do not derail the user's primary plan execution
- generated prompt contracts remain aligned with runtime execution contracts
- deterministic tests catch schema drift, missing helper references, and privacy guard regressions
