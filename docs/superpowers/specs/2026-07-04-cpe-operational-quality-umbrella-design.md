# CPE Operational Quality Umbrella Design

작성일: 2026-07-04
상태: DRAFT SPEC FOR REVIEW
대상 표면: `skills/kws-codex-plan-executor`, recent run inspection, task packet context, state validation, deterministic evals

## Problem

최근 5개 `kws-codex-plan-executor` 실행은 모두 `finished`이고
`completion_audit.passed=true`였다. `evals/run.sh`와 repo-level `bun run check`
도 통과했다. 즉 현재 문제는 product verification failure가 아니라 executor 운영
품질과 비용 신호가 반복적으로 노란색으로 남는 것이다.

반복 신호는 세 가지다.

- `run_quality.grade=yellow`가 완료 run의 기본 상태처럼 남는다.
- `full_spec_fallback_present`, `readiness_fixable_issues`,
  `plan_executability_fixable_issues`가 task packet context 품질을 낮춘다.
- `spawn_agent tool policy requires explicit user delegation intent`가 task마다
  반복되어 delegation 판단 비용과 state noise가 커진다.

코드 구조상 이 신호들은 실제 계약 위치와 연결된다.

- `build_task_packet.py`는 explicit `spec_refs`, manifest mapping, heuristic mapping
  이후에도 매핑이 안 되면 full-spec fallback을 사용한다.
- `audit_run_readiness.py`와 `audit_plan_executability.py`는 fallback과 metadata
  문제를 fixable issue로 기록한다.
- `preflight_dispatch.py`는 spawn policy, safety gate, value gate를 task 단위로
  판단한다.
- `run_quality_debt.py`는 이 operational debt를 stable followup으로 분류한다.
- `validate_state.py`는 completion, graphify, plan audit, run quality,
  delegation, subagent strategy 검증을 한 파일에서 모두 담당한다.
- `normalize_cpe_run.py`는 replay-friendly summary를 제공하지만 recent-run rubric
  runner는 아직 없다.

이번 umbrella는 세 개선 축을 한 번에 다룬다.

1. Recent-run rubric harness를 먼저 만들어 현재 품질 기준을 고정한다.
2. 그 기준으로 run quality green path를 개선한다.
3. 이후 validator를 모듈화해 다음 변경 비용을 낮춘다.

## Goals

- 최근 N개 CPE run을 deterministic JSON으로 분석하는 rubric harness를 추가한다.
- Finished/pass run에서 product verification과 executor operational debt를 분리해
  operator가 green/yellow 의미를 바로 이해하게 한다.
- Full-spec fallback 원인을 `missing_spec_refs`, `manifest_gap`,
  `weak_heuristic_match`, `intentional_operator_reviewed`처럼 actionable하게
  분류한다.
- Repeated expected local fallback을 task-level noise가 아니라 run-level capability
  state로 요약한다.
- `validate_state.py`를 기능별 validator module로 나눠도 기존 CLI와 state contract는
  유지한다.
- 모든 변경은 기존 CPE safety gates, task packet JSON source of truth, completion
  audit, state validation, Graphify evidence, prompt cache audit을 약화하지 않는다.

## Non-goals

- `completion_audit.passed`의 의미를 바꾸지 않는다.
- `run_quality.yellow`를 단순히 숨기거나 green으로 강등하지 않는다.
- Full-spec fallback을 무조건 금지하지 않는다. operator-reviewed fallback은 허용된다.
- `subagents=on` 기본값을 바꾸지 않는다.
- `spawn_agent` 정책을 우회하거나 명시적 delegation 요구를 무시하지 않는다.
- AgentLens unavailable 상태를 blocking failure로 만들지 않는다.
- `validate_state.py` refactor 중 state schema를 breaking change하지 않는다.
- Waygent runtime의 TypeScript orchestrator로 CPE Python skill을 즉시 통합하지 않는다.

## Reviewed Approaches

### A. Recommended: Rubric First, Green Path Second, Validator Modularization Third

먼저 recent-run rubric을 만들어 현재 품질 신호를 정량화한다. 그 다음 full-spec
fallback과 expected local fallback을 줄이거나 더 명확히 분류한다. 마지막으로
validator를 모듈화해 다음 운영 품질 변경을 작게 만든다.

장점:

- 실제 최근 5개 run에서 반복된 문제를 직접 줄인다.
- 개선 전후를 같은 rubric으로 비교할 수 있다.
- Safety contract를 바꾸기 전에 관측 기준을 고정한다.
- Validator refactor가 behavior change와 섞이지 않는다.

단점:

- 작업이 세 단계라 단일 patch보다 길다.
- New rubric output과 기존 `normalize_cpe_run.py` 사이의 중복을 조심해야 한다.
- Validator 모듈화는 regression surface가 넓어 focused eval이 필요하다.

이 접근을 선택한다.

### B. Validator Modularization First

먼저 `validate_state.py`를 나누고 이후 run quality 개선을 넣는다.

장점:

- 코드 구조가 먼저 좋아져 후속 변경이 깔끔하다.
- 1,300줄 validator에 새 로직을 더 얹지 않는다.

단점:

- 사용자 체감 문제인 yellow-quality 반복을 바로 줄이지 못한다.
- Refactor 중 현재 반복 증상을 검증할 rubric이 없어 회귀 판단이 흐려진다.
- Large refactor가 먼저 오면 실제 개선보다 mechanical churn이 커질 수 있다.

이 접근은 순서를 뒤로 미룬다.

### C. Green Path Heuristics Only

Full-spec fallback, expected local fallback, AgentLens missing 분류만 빠르게 조정한다.

장점:

- 구현량이 작다.
- 최신 5개 run의 yellow 신호를 빠르게 줄일 수 있다.

단점:

- 루브릭 없이 green 전환 기준이 임의적이 된다.
- Validator 구조 부채가 그대로 남는다.
- 이후 같은 문제가 다른 followup 이름으로 반복될 수 있다.

이 접근은 단기 patch로는 가능하지만 umbrella 목표에는 부족하다.

## Design

### Phase 1. Recent Run Rubric Harness

새 script는 recent CPE run state를 읽고 normalized operational-quality report를 만든다.

예상 CLI:

```bash
python3 scripts/analyze_recent_runs.py \
  --codex-home ~/.codex \
  --recent 5 \
  --include-finished \
  --output /tmp/cpe-recent-run-rubric.json
```

입력:

- `~/.codex/orchestrator/*/state.json`
- optional run dir artifacts:
  - `run_readiness.json`
  - `plan_executability_audit.json`
  - `prompt_cache_audit.json`
  - `graphify_audit*.json`
  - `task_packets/*.json`

출력 shape:

```json
{
  "schema_version": "1",
  "run_count": 5,
  "summary": {
    "finished_passed_count": 5,
    "green_count": 0,
    "yellow_count": 5,
    "red_count": 0,
    "full_spec_fallback_count": 7,
    "expected_local_fallback_count": 16
  },
  "rubric": {
    "safety": "green",
    "context": "yellow",
    "delegation_efficiency": "yellow",
    "evidence": "green",
    "validator_maintainability": "yellow"
  },
  "runs": []
}
```

Rubric dimensions:

- Safety: `validate_state.py` passes, no red plan audit, no release-blocking residual risk.
- Context: full-spec fallback ratio is low or every fallback is operator-reviewed.
- Delegation efficiency: expected spawn-policy fallback is summarized once at run level, not repeated as task-level surprise.
- Evidence: Graphify, prompt audit when applicable, verification bundles, and completion audit are connected.
- Validator maintainability: state validator modules pass parity tests against existing validator.

`analyze_recent_runs.py` should reuse `normalize_cpe_run.py` functions where useful instead of re-parsing every field independently.

### Phase 2. Run Quality Green Path

This phase improves repeated yellow states without hiding real risk.

#### Full-Spec Fallback Diagnosis

Extend task packet/readiness evidence so fallback has a reason and next action.

New task packet mapping fields:

```json
{
  "spec": {
    "fallback_used": true,
    "mapping": {
      "source": "fallback",
      "fallback_reason": "missing_spec_refs",
      "requires_parent_mapping": true,
      "suggested_spec_refs": ["design-goals", "validation-matrix"]
    }
  }
}
```

Allowed fallback reasons:

- `missing_spec_refs`: plan task did not declare `spec_refs`.
- `manifest_gap`: manifest could not map task id or file claims to spec sections.
- `weak_heuristic_match`: heuristic candidates existed but scored below threshold.
- `intentional_operator_reviewed`: operator explicitly accepted full spec context for this task.

Rules:

- `intentional_operator_reviewed` requires explicit state evidence.
- Unreviewed fallback remains yellow.
- Reviewed fallback can be green for context quality if context budget is not red.
- `manifest_fallback=halt_on_blocker` still blocks unmapped tasks.

#### Run-Level Delegation Capability

Add a run-level delegation capability preflight before per-task dispatch.

State shape:

```json
{
  "delegation_capability": {
    "schema_version": "1",
    "spawn_policy": "explicit-request-required",
    "explicit_user_delegation_request": false,
    "run_level_effective_mode": "local_fallback",
    "reason": "spawn_agent tool policy requires explicit user delegation intent"
  }
}
```

Rules:

- If run-level capability says all task spawning is policy-disabled, per-task
  dispatch can still record a compact `local_fallback`, but run quality counts it
  once as expected policy state.
- If explicit delegation is requested later, per-task adaptive dispatch resumes.
- Safety checks still run locally: task contract, unit manifest, RED/GREEN where
  applicable, post-diff review, acceptance, reconciliation, validation.

#### AgentLens Status Clarification

AgentLens remains best-effort, but run quality should distinguish:

- `agentlens_unavailable`: CLI or runtime not installed.
- `agentlens_emit_failed`: AgentLens was expected but event emission failed.
- `agentlens_not_applicable`: prompt/handoff or other non-logging mode.

`agentlens_missing` can remain a backward-compatible followup, but new reports should expose the specific status.

### Phase 3. Validator Modularization

Split `validate_state.py` into domain modules while preserving the existing CLI.

Proposed layout:

```text
scripts/cpe_state_validation/
  __init__.py
  common.py
  completion.py
  graphify.py
  plan_audit.py
  prompt_cache.py
  run_quality.py
  delegation.py
  tasks.py
  context.py
  recovery.py
```

`scripts/validate_state.py` remains the public entry point:

```python
from cpe_state_validation import validate
```

Rules:

- Error messages stay byte-stable where existing evals assert them.
- Public CLI remains `python3 scripts/validate_state.py <state>`.
- Shared constants move to `common.py`.
- Domain modules append errors to the same list and do not exit independently.
- Initial implementation keeps behavior identical, then adds new green-path fields.

Migration order:

1. Extract common helpers and constants.
2. Extract completion and residual risk validation.
3. Extract plan audit, graphify, prompt audit validation.
4. Extract run quality and delegation validation.
5. Extract task/subagent strategy validation.
6. Run parity tests after each extraction.

## Data Flow

```text
state.json + run artifacts
  -> normalize_cpe_run.py
  -> analyze_recent_runs.py
  -> rubric summary
  -> targeted green-path changes
  -> modular validate_state parity
```

The authoritative state remains `state.json`. Task packet JSON remains the source
of truth for task context. Markdown views and rubric reports are derived evidence.

## Error Handling

- Missing run dirs are reported as `missing_run_artifact`, not fatal for the
  whole recent-run report.
- Unreadable JSON marks the affected run `red` and records the path.
- A failed `validate_state.py` result makes Safety red for that run.
- Missing optional prompt audit is `not_applicable` unless the mode requires prompt cache evidence.
- Missing Graphify audit is yellow only when repo instructions require Graphify.
- Validator module import failure makes `validate_state.py` exit nonzero.

## Testing

Focused tests:

- `evals/check_cpe_replay.py`: normalized replay includes new tri-state evidence without raw prompts.
- New `evals/check_recent_run_rubric.py`: synthetic recent runs cover green, yellow, red, missing artifacts, and repeated expected local fallback.
- `evals/check_run_readiness.py`: fallback reasons and suggested spec refs are reported.
- `evals/check_task_packet.py`: fallback mapping fields are deterministic.
- `evals/check_preflight_dispatch.py`: run-level policy fallback is counted once while task safety gates remain intact.
- `evals/check_state_schema.py`: new optional fields validate.
- New `evals/check_validate_state_modular_parity.py`: old fixture states produce the same pass/fail outcomes through the public CLI.

Full gates:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
cd ../..
git diff --check
bun run check
```

Graphify-aware closeout:

```bash
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py \
  --repo-root . \
  --update-ran \
  --output /tmp/cpe-operational-quality-graphify.json
```

## Acceptance Criteria

- Recent 5-run report can be generated without reading raw transcripts.
- The report separates product verification status from executor operational debt.
- Finished/pass synthetic states with only reviewed full-spec fallback can grade context green.
- Repeated explicit-request spawn-policy fallback is summarized as run-level expected local fallback.
- Unreviewed full-spec fallback remains visible and yellow.
- `validate_state.py` CLI remains backward-compatible.
- Existing CPE eval harness and repo-level check pass.
- Docs and `SKILL.md` contract are updated if runtime behavior or public workflow changes.

## Implementation Order

1. Add recent-run rubric harness and replay fixtures.
2. Add fallback reason/suggestion evidence to task packet and readiness audits.
3. Add run-level delegation capability evidence and update run quality debt.
4. Add AgentLens status clarification and normalized replay fields.
5. Modularize `validate_state.py` behind the existing CLI.
6. Update `SKILL.md`, `README.md`, `ARCHITECTURE.md`, `references/state-schema.md`,
   `references/execution-cycle.md`, `docs/evals-and-verification.md`, and
   `HISTORY.md` where behavior changes.
7. Run focused evals, full CPE eval harness, Graphify freshness, and repo-level check.

## Risks And Mitigations

- Risk: Green path hides useful warnings.
  - Mitigation: Only reviewed or not-applicable debt can become green; unreviewed fallback stays yellow.
- Risk: Validator refactor changes behavior silently.
  - Mitigation: Add public-CLI parity eval before changing validation behavior.
- Risk: Rubric duplicates `inspect_runs.py` and `normalize_cpe_run.py`.
  - Mitigation: Reuse normalization helpers and keep the rubric as aggregation/reporting.
- Risk: Run-level delegation capability weakens per-task safety.
  - Mitigation: Capability only changes noise accounting; task execution still requires all local quality gates.
- Risk: More state fields make the contract harder to understand.
  - Mitigation: Optional additive fields only, documented in `state-schema.md`, with normalized replay summaries.

## Scope Decisions

- Recent-run rubric starts as CPE-only Python under
  `skills/kws-codex-plan-executor/scripts/`. A later Waygent TypeScript
  inspection surface may consume its JSON, but that is outside this umbrella.
- `agentlens_emit_failed` remains yellow. `agentlens_unavailable` is
  informational when preflight explicitly records the capability as unavailable,
  because AgentLens is best-effort and state remains authoritative.
- Validator modularization is part of this umbrella but comes after rubric and
  green-path behavior. It may ship in the same minor release only if public CLI
  parity is proven before behavior changes are layered on top.
