# KWS Claude Multi-Agent Executor Learning Log Design

Date: 2026-05-13
Owner: 김우승
Sibling design: `2026-05-13-kws-codex-plan-executor-learning-log-design.md`

## Purpose

이 문서는 `kws-claude-multi-agent-executor`에 user-local learning loop를 추가하기 위한 설계안이다.

목표는 executor가 여러 repository에서 실제 계획을 실행하면서 마주친 실패, 오류, 사용자 정정, 반복 이슈, 좋은 해결 패턴을 구조화된 JSONL로 남기는 것이다. 이 로그는 단일 실행을 재개하기 위한 `state.json`과 다르다. `state.json`은 해당 worktree의 실행 상태를 복구하기 위한 자료이고, learning log는 나중에 Archive repository에서 executor skill 자체를 개선하기 위한 장기 학습 자료다.

Codex executor의 동일 4축 (`execution-only` × `notable-boundaries` × `redacted-context` × `schema + helper script`) 을 따르되, Claude Code 특성 — Opus 오케스트레이터 + Sonnet sub-agent (Agent 도구 + `claude -p` 두 dispatch 경로), git worktree 격리, 네이티브 hooks, `docs/experiments/` institutional memory — 을 반영해 다음 세 가지를 조정한다:

1. **모드 차원 대신 `phase` × `risk_tier`** — 이 skill엔 Codex와 같은 `interactive`/`headless`/`prompt`/`handoff` 모드 구분이 없다.
2. **per-run shard 디렉토리 레이아웃** — 동일 repo에서 multiple orchestrator 동시 실행을 무잠금으로 격리.
3. **검수 측 Skill 호출 보강** — Plan Reviewer / Reviewer / Verifier prompt에 superpowers Skill 호출을 추가 (현재 Implementer만 적극 활용).

## Chosen Direction

적용 범위는 `execution-only`다. 이 skill엔 모드 구분이 없으므로 적용 범위는 Phase 단위로 명시한다.

- 기록 대상 Phase: `Phase 0 (preflight)`, `Phase 1 (per-task)`, `Phase Transition`, `Phase 2 (final)`
- 기록 시점은 `notable-boundaries`다:
  - `blocker`: plan/path/dirty worktree/baseline 누락/spec 부재로 멈춘 경우
  - `error`: skill 절차 자체 실패 (state.json 손상, worktree 생성 실패, hook 거부 등)
  - `verification_failure`: Verifier가 FAIL 리턴 (per-task MID/HIGH 또는 batch LOW)
  - `reviewer_warn_or_fail`: Combined Reviewer가 WARN 또는 FAIL tier (SPEC<0.85 OR QUALITY<0.75)
  - `escalation`: sub-agent가 ESCALATE 리턴 (ENV_BLOCKER, SCOPE_AMBIGUITY, MID-RISK_CONCERN 등 — `references/escalation-playbook.md`의 어느 카테고리든)
  - `recurring_issue`: 같은 `ISSUE_KEY`가 다시 출현
  - `user_correction`: 사용자가 executor의 scope, allowed files, 가정, 방향을 정정
  - `parallel_dispatch_failure`: 웨이브 sub-worktree dispatch 실패 또는 머지 충돌 (P2)
  - `successful_workaround`: 원인 기반 해결이 재사용 가능한 절차 개선 신호
  - `completion_learning`: 최종 완료 시 executor 개선에 유의미한 actionable 관찰

privacy 기준은 `redacted-context`다. agent가 나중에 맥락을 잃지 않고 개선 작업을 할 수 있을 정도의 요약과 증거 포인터는 남기되, 전체 sub-agent transcript, 긴 raw log, secret, 절대 home path, 절대 worktree path는 저장하지 않는다.

## File Structure

Create:

- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/scripts/append_learning_event.py`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/check_learning_log.py`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/learning-log.md`

Modify:

- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/SKILL.md`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/implementer-prompt.md` (이미 4개 Skill 호출 있음 — learning-event emit 가이드 추가)
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/reviewer-prompt.md` (Skill 호출 추가 + learning-event emit 가이드)
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/verifier-prompt.md` (Skill 호출 추가 + learning-event emit 가이드)
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/plan-reviewer-prompt.md` (Skill 호출 추가)
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/references/escalation-playbook.md` (escalation → learning event 연결)
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/evals/run.sh`
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/ARCHITECTURE.md` (§14 Learning Log Contract 신설)
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/HISTORY.md` (v2.8.0 entry)
- `ai/skills/kws-skills/package/kws-claude-multi-agent-executor/AGENTS.md` (learning-log 운영 프로토콜)
- `ai/skills/kws-skills/manifest.json` (package + skill 버전 bump)
- `ai/skills/kws-skills/README.md`
- `ai/skills/kws-skills/CHANGELOG.md`

Optional later, not required for this implementation:

- `scripts/aggregate_events.py` — 최근 N일 이벤트 그룹화 → 다음 experiment 후보 도출
- `references/hooks/learning-log-prestage.sh.template` — SubagentStop hook이 이벤트 후보 자동 pre-stage

## Storage Contract — Per-Run Sharded Layout

The helper does **not** append to a shared file. Each orchestrator run gets
its own directory under user-local storage:

```text
~/.claude/learning/kws-claude-multi-agent-executor/runs/<YYYY-MM-DD>/<run_id>/
├── meta.json
└── events.jsonl
```

This sits alongside Claude Code's other user-local data (`~/.claude/projects/`,
`~/.claude/tasks/`, `~/.claude/sessions/`) — the same level as Codex's
`~/.codex/learning/...` directory.

The `run_id` format:

```text
<UTC-compact-timestamp>-<session_short>-<pid>
example: 20260513T143321Z-188042f4-48211
```

- `<UTC-compact-timestamp>` = `YYYYMMDDTHHMMSSZ` (lexically sortable)
- `<session_short>` = first 8 hex chars of `$CLAUDE_SESSION_ID` (joins the
  Claude Code transcript at `~/.claude/projects/<encoded-cwd>/<full-uuid>.jsonl`).
  Falls back to `nosession` when the env var is unavailable.
- `<pid>` = orchestrator process id (disambiguates same-second starts)

**Sub-agents never invoke the helper directly.** They prepare event candidate
JSON files under `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json`.
The orchestrator — which owns `MAE_LEARNING_RUN_ID` — reads candidates and
calls `append`. This is a single-writer contract: only the orchestrator
process invokes the helper, regardless of which sub-agent surfaced the
boundary.

`MAE_LEARNING_RUN_ID` env inheritance is relevant only for `claude -p` dispatch
paths the orchestrator runs **itself** (Plan Reviewer / Verifier / Docs Updater
/ Resume Chain handoff). For those, the orchestrator passes the var explicitly
via `env MAE_LEARNING_RUN_ID="$MAE_LEARNING_RUN_ID" nohup ...` if those
subprocesses ever need to read it (currently they do not — the orchestrator
reads their result JSON and emits events on their behalf).

Agent-tool sub-agents (Implementer / Reviewer) do not need env propagation
because they only write candidate files, never call the helper.

Concurrent runs in the same repository write to distinct run directories — no
file locking is required because no two writers ever touch the same file.

The user-local log is outside the project repository because the learning
target is the executor skill itself, not any individual repository.

## meta.json Schema

Written once at `init-run`, updated at `close-run`:

```json
{
  "schema_version": "1",
  "run_id": "20260513T143321Z-188042f4-48211",
  "skill": "kws-claude-multi-agent-executor",
  "skill_version": "2.8.0",
  "host": "kws-mac.local",
  "pid": 48211,
  "session_id": "188042f4-d69e-45d2-91ad-91ad...",
  "session_ids": ["188042f4-d69e-45d2-91ad-91ad..."],
  "repo": {
    "name": "Archive",
    "branch": "feature/x",
    "remote_hash": null
  },
  "plan_path": "docs/superpowers/plans/<plan>.md",
  "spec_path": "docs/superpowers/specs/<spec>.md",
  "worktree_path": "../worktrees/plan-20260513-143321",
  "started_at": "2026-05-13T14:33:21Z",
  "ended_at": "2026-05-13T15:02:11Z",
  "outcome": "success",
  "event_count": 3
}
```

`outcome` values: `success` | `blocked` | `aborted` | `unknown`.
A run with zero events still leaves `meta.json` — `outcome=success` + `event_count=0`
is a positive negative-signal ("this plan executed without notable boundaries").

`session_id` is the initial Claude Code session UUID at `init-run` time.
`session_ids[]` is the running array of all session UUIDs that have continued
this run (includes the initial one, plus any Resume Chain handoffs). When a
Resume Chain spawns a new `claude -p` subprocess with a different `--session-id`,
the new orchestrator appends its session UUID to `session_ids[]` instead of
calling `init-run`. This preserves the "one plan execution = one run record"
invariant across multi-session resume chains.

## Event Schema (events.jsonl line)

Each JSONL line embeds the run_id (for global glob analysis) but **not** the
full run metadata (that lives in `meta.json`). Required fields:

```json
{
  "schema_version": "1",
  "event_id": "a1b2c3d4e5f6g7h8",
  "run_id": "20260513T143321Z-188042f4-48211",
  "timestamp": "2026-05-13T14:35:12.482910Z",
  "skill": "kws-claude-multi-agent-executor",
  "skill_version": "2.8.0",
  "phase": "phase_1",
  "risk_tier": "MID",
  "event_type": "reviewer_warn_or_fail",
  "severity": "medium",
  "execution": {
    "task_id": "task_3",
    "wave": 2,
    "compaction_index": 1,
    "issue_key": "review_retry_quality_low"
  },
  "scores": {
    "spec_score": 0.82,
    "quality_score": 0.71,
    "tier": "WARN"
  },
  "subagent": {
    "role": "reviewer",
    "model": "sonnet",
    "dispatch": "agent_tool"
  },
  "summary": "Combined Reviewer returned WARN tier; quality_score below 0.75 due to missing input-validation tests for the new public API.",
  "context": {
    "user_intent": "Add JSON config parsing per spec §3.",
    "agent_expectation": "Reviewer would PASS at first pass.",
    "actual_outcome": "WARN tier — quality below threshold; spec partially met.",
    "root_cause": "Implementer wrote happy-path tests only; spec language was ambiguous about validation coverage.",
    "evidence": [
      {"kind": "relative_path", "value": "src/config.py"},
      {"kind": "issue_key", "value": "review_retry_quality_low"},
      {"kind": "scores_delta", "value": "spec=0.82 quality=0.71"}
    ]
  },
  "improvement": {
    "target": "references/reviewer-prompt.md",
    "proposal": "When QUALITY_SCORE < 0.75 cite a specific missing test category, not just 'tests insufficient'.",
    "experiment_link": null
  },
  "privacy": {
    "redacted": true,
    "notes": "Worktree path relativized; reviewer transcript not included."
  }
}
```

### Field allowed values

`phase`:

- `phase_0` (preflight, plan parsing, worktree setup, plan review)
- `phase_1` (per-task implementation cycle)
- `phase_transition` (LOW batch verifier, phase docs, state anchor)
- `phase_2` (final docs, summary report)

`risk_tier`: `LOW` | `MID` | `HIGH` | `null` (when event is orchestrator-level, not task-level)

`event_type`: 10 values listed in §Chosen Direction.

`severity`:

- `low`: useful improvement signal, no execution risk
- `medium`: caused retry, escalation handled, scope correction, verification fix
- `high`: blocked execution, risked wrong files, exposed a hard contract gap, or
  required user intervention

`subagent.role`: `implementer` | `reviewer` | `verifier` | `documenter` |
`plan_reviewer` | `orchestrator` (when the event is orchestrator-level)

`subagent.dispatch`: `agent_tool` | `claude_p` | `orchestrator` (n/a for self)

`subagent.model`: `sonnet` | `opus` | `haiku` | `unknown`

`scores` is optional and present only for events with quality data
(`reviewer_warn_or_fail` always, `verification_failure` when scoring applies).

`improvement.experiment_link` is optional — set to a path under
`docs/experiments/...` when the event extends or connects to an existing
experiment finding.

## Redaction Rules

The helper rejects or sanitizes unsafe input before append. Same baseline
as the Codex helper, plus two Claude-specific rules:

- Do not store secrets, tokens, API keys, cookies, credentials, private keys, or
  authorization headers.
- Do not store full conversation transcripts. This applies especially to
  sub-agent transcripts from `~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`
  and `~/.claude/tasks/<uuid>/` — reference by `session_id` (already in
  `meta.json`) instead.
- Do not store long raw logs. Use a short excerpt or a relative raw-output path
  when available.
- Do not store absolute home paths such as `/Users/<name>/...`; convert
  workspace paths to repository-relative paths.
- **Do not store absolute worktree paths** such as `/Users/<name>/.../worktrees/<branch>/<file>` — relativize to the worktree root and store as `<file>` relative path. The worktree path is recorded once in `meta.json` and not duplicated per event.
- Do not store large file contents.
- Do not store unrelated user files or unrelated process details.

Allowed context:

- repository name + branch
- relative plan/spec path
- task id, wave, compaction_index, issue_key, phase
- relative file paths (relative to worktree root)
- command names and arguments when they do not expose secrets
- short failure excerpt (≤ 400 chars)
- root-cause summary
- proposed improvement target (a file path inside the skill package)

If the helper cannot confidently sanitize a field, it fails closed and tells
the caller what field needs to be summarized manually.

## Helper Interface

Three subcommands, all idempotent.

### `init-run`

Creates the run directory and writes `meta.json`. Echoes the `run_id` so the
orchestrator can export it as `MAE_LEARNING_RUN_ID`.

```bash
python3 ai/skills/kws-skills/package/kws-claude-multi-agent-executor/scripts/append_learning_event.py init-run \
  --repo-root "$WORKTREE_ABS" \
  --repo-name Archive \
  --branch feature/x \
  --plan-path docs/superpowers/plans/X.md \
  --spec-path docs/superpowers/specs/X.md \
  --session-id "$CLAUDE_SESSION_ID"
# stdout: 20260513T143321Z-188042f4-48211
```

If `meta.json` already exists, validate it matches the current invocation and
return the existing `run_id` (idempotent).

### `append`

Validates and appends one event line. If the run directory or `meta.json`
does not exist (init-run was skipped), creates them with `outcome=unknown`.

```bash
python3 .../append_learning_event.py append \
  --run-id "$MAE_LEARNING_RUN_ID" \
  --event-json /tmp/event-candidate.json
```

Supported options:

- `--run-id <id>`: required
- `--event-json <path>`: required, path to candidate JSON file
- `--log-root <path>`: optional override for tests; default `~/.claude/learning/kws-claude-multi-agent-executor/`
- `--repo-root <path>`: used to relativize absolute file paths
- `--dry-run`: validate and print sanitized event without appending

Steps the helper performs:

1. Load JSON.
2. Validate required fields and enum values.
3. Redact or reject unsafe path and secret-like values.
4. Add `timestamp` (microsecond ISO) if missing.
5. Ensure `skill` is `kws-claude-multi-agent-executor`.
6. Ensure `run_id` matches the directory.
7. Append one compact JSON line to `runs/<date>/<run_id>/events.jsonl`.
8. Print the appended `event_id`.

### `close-run`

Updates `meta.json` with `ended_at`, `outcome`, and `event_count`.

```bash
python3 .../append_learning_event.py close-run \
  --run-id "$MAE_LEARNING_RUN_ID" \
  --outcome success
```

`--outcome` allowed values: `success` | `blocked` | `aborted` | `unknown`.
Idempotent — running close-run twice produces the same `meta.json` (the later
call's `ended_at` wins).

### `append-session-id` (Resume Chain handoff)

Appends a new session UUID to `meta.session_ids[]` without changing
`started_at`. Called by the chained orchestrator immediately after it
inherits a run via `MAE_LEARNING_RUN_ID`.

```bash
python3 .../append_learning_event.py append-session-id \
  --run-id "$MAE_LEARNING_RUN_ID" \
  --session-id "$CLAUDE_SESSION_ID"
```

Idempotent — appending the same session_id twice is a no-op.

## Runtime Flow

Each orchestrator run goes through the following lifecycle. The orchestrator
is the **only** process that invokes the helper — sub-agents write candidate
JSON files that the orchestrator reads and forwards.

```
Phase 0 setup ──▶ init-run (export MAE_LEARNING_RUN_ID)
              │
Phase 0–2 ────▶ orchestrator reads sub-agent candidate JSON files from
              │   <worktree>/.orchestrator/learning_events/ then calls append
              │
Phase 2 final ▶ close-run
```

`close-run` is required on **every** orchestrator exit path, not only Phase 2:

- Phase 2 success → `outcome=success`
- ESCALATE that halts the orchestrator → `outcome=blocked`
- User abort, hook denial, or HEADLESS_HALTED → `outcome=aborted`
- Hard crash / unhandled exception → `close-run` cannot run; `outcome=unknown`
  is the honest residue (no recovery attempted)

The orchestrator must funnel every halt path through a single exit section
that calls `close-run` with the appropriate outcome before any process exit.

### Phase 0

- After worktree setup, before plan parsing: `init-run`. Capture `run_id`,
  export `MAE_LEARNING_RUN_ID`.
- If plan parsing fails → `blocker`.
- If baseline.json or spec is missing/invalid → `blocker`.
- If Plan Reviewer returns advisory issues that the orchestrator treats as
  blocking → `blocker`.

### Phase 1

- Per task, after each dispatch + review cycle:
  - Reviewer WARN/FAIL → `reviewer_warn_or_fail` (severity = WARN→`medium`, FAIL→`high`)
  - Verifier FAIL (MID/HIGH) → `verification_failure`
  - Sub-agent ESCALATE → `escalation` (severity by `references/escalation-playbook.md` category)
  - Same ISSUE_KEY recurs → `recurring_issue`
  - Parallel wave dispatch failure / merge conflict → `parallel_dispatch_failure`
  - Root-cause-based recovery worth reusing → `successful_workaround`
- User intervenes mid-run (scope/files/assumptions) → `user_correction`

### Phase Transition

- Batch Verifier FAIL on LOW tasks → `verification_failure` (risk_tier=LOW, batch context in execution.compaction_index)
- Phase Docs Updater ESCALATE → `escalation` (subagent.role=documenter)

### Phase 2

- Final Docs Updater ESCALATE → `escalation`
- Genuinely actionable executor-improvement observation → `completion_learning`
  (only when actionable; do NOT log routine successful completions)

### Always

- `close-run` at the end with `outcome` reflecting the final state, regardless
  of whether any events were recorded. See §Runtime Flow for the per-exit-path
  outcome mapping.

### Resume Chain handoff

When SKILL.md's Resume Chain spawns a new `claude -p` subprocess
(`compaction_points ≥ 2 AND complete ≥ 8`):

- The current orchestrator passes `MAE_LEARNING_RUN_ID` explicitly via
  `env MAE_LEARNING_RUN_ID="$MAE_LEARNING_RUN_ID" nohup claude -p ...`.
- The current orchestrator does NOT call `close-run` (the run is continuing).
- The chained orchestrator does NOT call `init-run`. Instead it calls
  `append-session-id --run-id "$MAE_LEARNING_RUN_ID" --session-id "$CLAUDE_SESSION_ID"`.
- One plan execution = one run record, even across multiple Claude sessions.

If the chained orchestrator finds `MAE_LEARNING_RUN_ID` unset (env var not
propagated), it logs a warning and proceeds without learning-log support
rather than calling `init-run` (which would fragment the run record).

The helper call must not replace `state.json`, headless artifacts, or final
summary. It is an additional long-term learning signal.

## Sub-agent Skill-Invocation Additions

Currently only Orchestrator (2 sites) and Implementer (4 sites) invoke
superpowers. v2.8 adds:

- `references/plan-reviewer-prompt.md`: `Skill("superpowers:writing-plans")`
  before evaluating the plan, so the reviewer applies the same plan-quality
  rubric the orchestrator implicitly assumes.
- `references/reviewer-prompt.md`: `Skill("superpowers:requesting-code-review")`
  before scoring spec/quality. The skill's review checklist informs the rubric.
- `references/verifier-prompt.md`: `Skill("superpowers:verification-before-completion")`
  before running verification commands. The skill's evidence-before-assertion
  guidance directly improves the Verifier's standard of proof.

These are single-line additions in each prompt's preamble. Recorded here so
the addition is tracked alongside the learning-log scope rather than as a
silent prompt drift.

## Error Handling

Learning-log failure must not fail the user's primary plan execution.

If helper validation fails:

- report the logging failure briefly to the orchestrator's running notes
- continue or stop based on the original executor state, not the logging failure
- do not weaken the original blocker, verification, or retry rules

If the log path cannot be written:

- preserve the event candidate under `<worktree>/.orchestrator/raw/` if that
  directory exists
- mention the write failure in the checkpoint or final summary
- do not retry indefinitely

If an event contains unsafe content:

- reject the event and request a summarized replacement from the agent's own context
- never append known-sensitive data

## Testing

Add deterministic checks for the new behavior.

Script-level checks (`evals/check_learning_log.py`):

1. `init-run` creates run directory and `meta.json` with expected fields; echoes run_id.
2. `init-run` is idempotent — second call with same args returns same run_id and does not overwrite `started_at`.
3. `append` after `init-run` writes one valid JSONL line.
4. `append` without prior `init-run` self-heals (creates `meta.json` with outcome=unknown).
5. `close-run` updates `ended_at`, `outcome`, `event_count`.
6. `close-run` is idempotent.
7. `--dry-run` on `append` validates without writing.
8. Missing required fields fail.
9. Invalid `phase`, `event_type`, or `severity` fail.
10. Absolute home paths in `evidence` are rejected with a clear message.
11. Absolute worktree paths in `evidence` are relativized when `--repo-root` is given.
12. Secret-like fields (`Authorization: Bearer ...`, `api_key=`, `sk-...`) are rejected.
13. `concurrent_runs_isolated`: 4 subprocesses with distinct `run_id`s appending 100 events each — all 400 events land in their respective `events.jsonl` files with no cross-contamination.

Add helper subcommand checks:

14. `close-run` updates `ended_at`, `outcome`, `event_count`; idempotent on second call.
15. `close-run` after a partial run (init-run + 0 appends) correctly sets `event_count=0` and `outcome` to the supplied value.
16. `append-session-id` extends `meta.session_ids[]` without changing `started_at`; idempotent for the same session id.

Contract checks (extend or create `evals/check_skill_contract.py`):

- `SKILL.md` references execution-mode learning log behavior and the helper script.
- `SKILL.md` describes calling `close-run` from every exit path (success / blocked / aborted).
- `references/learning-log.md` exists with required sections.
- `references/{plan-reviewer,reviewer,verifier}-prompt.md` each contain at least
  one `Skill("superpowers:..."` invocation (per the §Sub-agent Skill-Invocation Additions).
- `references/{implementer,reviewer,verifier,plan-reviewer}-prompt.md` describe
  emitting event candidates as JSON files under
  `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json` (NOT calling
  the helper directly).
- `evals/check_learning_log.py` passes from `evals/run.sh`.

Smoke / integration verification (F001):

Run two fixtures end-to-end with learning log enabled:

- Smoke A: `evals/fixtures/01-trivial-typo.yaml` (LOW, happy path). Expect
  `meta.outcome=success`, `meta.event_count=0`. Validates init-run + close-run
  on a clean path.
- Smoke B: `evals/fixtures/08-subtle-input-validation.yaml` (MID, known
  WARN-prone from v2.7). Expect `meta.event_count ≥ 1` with at least one
  `event_type=reviewer_warn_or_fail`. Validates the `append` path under real
  conditions.

F001 close-out finding PASSes iff both smokes meet their expectations and the
event JSONL is well-formed.

Package validation:

- `python3 scripts/append_learning_event.py --help`
- `python3 scripts/append_learning_event.py {init-run,append,close-run,append-session-id} --help`
- existing eval suite (rubric.py, fixtures, judge)
- skill quick validation
- `printenv CLAUDE_SESSION_ID` from inside a `claude -p` subprocess (one-time
  pre-T2 check; if empty, the helper's `session_short` falls back to `nosession`
  and run_id loses one disambiguation dimension — acceptable).

## Non-Goals

This design does not add:

- automatic skill self-modification
- cross-machine log syncing
- repository-local learning logs (the project repo never receives logs)
- full transcript capture
- broad telemetry
- aggregator / reporting CLI (deferred to v2.9+)
- headless `--model` flag fix (separate v2.8.x mini-PR)
- learning-log → experiment auto-trigger (deferred to v2.9+)
- skill-invocation enforcement (we add the Skill calls in prompts but do not
  hook-enforce them; the learning log will surface non-invocation patterns)

## Success Criteria

The implementation is successful when:

- Phase 0 init-run creates a run directory; sub-agents inherit `MAE_LEARNING_RUN_ID`.
- Notable-boundary events from orchestrator, Implementer, Reviewer, Verifier,
  Plan Reviewer, Docs Updater all land in the same run's `events.jsonl`.
- Concurrent runs in the same repo produce distinct run directories with no
  cross-contamination.
- Phase 2 close-run updates `meta.json` with final outcome and event count.
- Logging failures do not derail the user's primary plan execution.
- Reviewer / Verifier / Plan Reviewer prompts invoke their respective superpowers
  Skills at the documented preamble.
- Deterministic tests catch schema drift, missing helper references, privacy
  guard regressions, and missing Skill invocations.
- The smoke run (existing fixture, end-to-end) produces a complete run record
  (meta.json + at least one event line when triggered) under the user-local
  path.
