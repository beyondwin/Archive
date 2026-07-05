# CPE Operational Quality Signal Design

작성일: 2026-07-05
상태: APPROVED DESIGN SPEC
대상 표면: `skills/kws-codex-plan-executor`, recent run analysis, dispatch policy evidence, run quality debt, deterministic evals

## Problem

최근 3개 `kws-codex-plan-executor` 실행을 분석했다.

- `2026-07-05-readmates-host-server-state-boundary-cleanup-20260705-133050`
- `2026-07-05-memory-corpus-review-deeplinks-20260705-132436`
- `2026-07-05-v1-trust-evidence-required-checks-umbrella-20260705-133108`

세 실행 모두 `lifecycle_outcome=finished`였고
`completion_audit.passed=true`였다. Graphify audit, prompt cache audit, verification
bundle evidence도 completion audit에 연결되어 있었다. 즉 문제는 product
verification failure가 아니라 CPE operational-quality signal의 분류와 설명력이다.

반복 신호는 세 가지다.

1. 세 실행 모두 `run_quality.grade=yellow`다.
2. 세 실행 모두 `agentlens_missing`을 가진다. `preflight_local_env.json`에서도
   `environment_capabilities.agentlens=absent`였다.
3. 세 실행 모두 `delegation_policy_expected_local_fallback`을 가진다. 모든
   dispatch decision은 `spawn_agent tool policy requires explicit user delegation
   intent` 또는 같은 의미의 failed prerequisite 때문에 `local_fallback`이었다.

추가로 `2026-07-05-memory-corpus-review-deeplinks-20260705-132436`에서는 task 6이
`weak_heuristic_match` 때문에 full-spec fallback을 사용했고,
`readiness_fixable_issues`, `plan_executability_fixable_issues`,
`full_spec_fallback_present`가 함께 남았다.

현재 CPE는 이 신호를 숨기지 않는다는 점에서 보수적이다. 그러나 정상적인 환경/도구
정책 상태와 실제 개선 가능한 품질 부채가 같은 yellow bucket에 섞인다. 그 결과
operator는 "완료는 통과했지만 무엇을 고쳐야 하는가"를 매번 수동으로 해석해야 한다.

## Goals

- Product verification success와 executor operational-quality followup을 유지하되,
  actionable followup과 informational followup을 구분한다.
- Spawn 정책 때문에 예상된 local fallback은 task마다 실패처럼 보이지 않고
  run-level capability 상태로 요약된다.
- Spawn 정책이 local fallback을 강제해도 safety gate와 value gate의 "would-have"
  판단을 기록해, 실제로 delegation 가치가 있었는지 나중에 분석할 수 있다.
- AgentLens 부재는 best-effort telemetry gap으로 유지하되, absent environment와
  emit failure를 구분한다.
- Full-spec fallback은 기존대로 yellow debt로 남기되, reason과 next action이
  plan/spec 작성자로 이어지게 한다.
- Recent-run rubric은 `green|yellow|red` 외에 actionable/informational breakdown을
  출력한다.
- 기존 CPE safety gates, dedicated worktree boundary, task packet JSON source of
  truth, completion audit, state validation, Graphify audit, prompt cache audit을
  약화하지 않는다.

## Non-goals

- `completion_audit.passed`의 의미를 바꾸지 않는다.
- `run_quality.yellow`를 무조건 green으로 바꾸지 않는다.
- `subagents=on` 기본값을 바꾸지 않는다.
- `spawn_agent` 도구 정책을 우회하지 않는다.
- 명시적 delegation 요청 없이 subagent를 강제로 spawn하지 않는다.
- AgentLens unavailable 상태를 blocking failure로 만들지 않는다.
- Full-spec fallback을 전면 금지하지 않는다.
- Archived run state를 자동 수정하지 않는다.
- Waygent TypeScript runtime이나 Lens event schema를 변경하지 않는다.

## Reviewed Approaches

### A. Recommended: Signal Taxonomy and Would-Have Dispatch Evidence

현재 followup string은 유지하되, run quality와 recent-run analysis에 두 계층을
추가한다.

- `actionable_followups`: plan/spec/context/validator 수정으로 다음 실행에서 줄일 수
  있는 항목.
- `informational_followups`: 현재 환경이나 세션 도구 정책 때문에 생긴 비차단 항목.

또한 `preflight_dispatch.py`가 spawn policy로 `local_fallback`을 선택하더라도,
task packet의 safety/value gate를 계속 계산해 `would_have_decision` evidence를 남긴다.

장점:

- 최근 3개 실행의 반복 yellow를 실제 원인별로 해석할 수 있다.
- Spawn 정책을 우회하지 않으면서 delegation 가치 분석을 보존한다.
- 기존 state compatibility를 유지할 수 있다.
- Full-spec fallback처럼 실제 개선 가능한 debt는 계속 선명하게 남는다.

단점:

- State와 normalized report에 optional evidence field가 늘어난다.
- `green` 판정 기준을 문서와 eval로 명확히 고정해야 한다.
- Older state와 newer state를 모두 읽는 validator compatibility가 필요하다.

선택한 접근은 A다.

### B. Strict Green Path

AgentLens unavailable과 expected local fallback을 green에 영향을 주지 않는 항목으로
완전히 제외한다.

장점:

- 최근 3개 실행의 yellow noise가 빠르게 줄어든다.
- 구현량이 작다.

단점:

- 관측성 gap과 세션 정책 제약이 상태에서 덜 보인다.
- "왜 subagent가 하나도 안 돌았는가"라는 운영 질문에 대한 증거가 약해진다.
- Full-spec fallback 같은 actionable debt와의 차이를 설명하지 못하면 단순 은폐처럼
  보일 수 있다.

이 접근은 너무 공격적이라 거부한다.

### C. Environment Bootstrap First

AgentLens 설치/부트스트랩 안내를 강화하고, spawn policy가 explicit-request-required일
때 사용자에게 delegation opt-in을 더 자주 묻는다.

장점:

- 실제 telemetry gap을 줄일 수 있다.
- 사용자가 원하면 subagent 활용률이 올라간다.

단점:

- AgentLens와 spawn policy는 환경/세션 정책에 좌우된다.
- CPE가 자동 설치나 자동 delegation opt-in을 하면 안전 경계가 흐려진다.
- 최근 로그의 핵심인 "품질 신호가 섞여 보이는 문제" 자체는 남는다.

이 접근은 보조 개선으로는 유효하지만 1순위가 아니다.

## Design

### 1. Followup Taxonomy

`run_quality`와 `analyze_recent_runs.py`는 기존 `open_followups`를 유지하고, 새
derived summary를 추가한다.

예상 shape:

```json
{
  "run_quality": {
    "grade": "yellow",
    "open_followups": [
      "agentlens_missing",
      "delegation_policy_expected_local_fallback",
      "full_spec_fallback_present"
    ],
    "followup_taxonomy": {
      "schema_version": "1",
      "actionable_followups": [
        "full_spec_fallback_present"
      ],
      "informational_followups": [
        "agentlens_missing",
        "delegation_policy_expected_local_fallback"
      ],
      "release_blocking_followups": []
    }
  }
}
```

Initial classification:

- `full_spec_fallback_present`: actionable.
- `readiness_fixable_issues`: actionable.
- `plan_executability_fixable_issues`: actionable.
- `delegation_policy_missing_dispatch_evidence`: actionable.
- `delegation_policy_prevented_all_delegation`: actionable unless the run records
  `spawn_policy=explicit-request-required` and no explicit delegation request.
- `delegation_policy_expected_local_fallback`: informational.
- `agentlens_missing`: informational when `agentlens_status.status=agentlens_unavailable`
  or preflight says `agentlens=absent`.
- `agentlens_missing`: actionable when `agentlens_status.status=agentlens_emit_failed`.
- `missing_execution_worktree`: informational for finished states observed after
  completion, actionable for active or non-terminal runs.

Grade semantics:

- `red`: completion failed, validation failed, blocking drift exists, or release-blocking
  residual risk exists.
- `yellow`: completion passed but actionable followups exist.
- `green-with-info`: completion passed, no actionable followups, informational followups
  exist.
- `green`: completion passed and no open followups remain.

For state compatibility, `run_quality.grade` remains one of `green|yellow|red`. The
new `green-with-info` value is a report-level display class in `analyze_recent_runs.py`,
not a replacement enum in `state.json`.

### 2. Run-Level Delegation Capability

CPE already records `delegation_capability` in newer states. This design makes it the
primary explanation for repeated expected local fallback.

Required fields:

```json
{
  "delegation_capability": {
    "schema_version": "1",
    "spawn_policy": "explicit-request-required",
    "explicit_user_delegation_request": false,
    "run_level_effective_mode": "local_fallback",
    "reason": "spawn_agent tool policy requires explicit user delegation intent",
    "informational": true
  }
}
```

Rules:

- `spawn_policy=explicit-request-required` with
  `explicit_user_delegation_request=false` is not a safety failure.
- Per-task `subagent_strategy.mode=local_fallback` remains required for write-capable
  tasks, but run quality counts this pattern once at run level.
- `dispatch_decisions` still record each task decision for replay and state alignment.
- If explicit delegation is requested, this informational fallback no longer applies and
  normal safety/value gate results decide the route.

### 3. Would-Have Dispatch Evidence

`preflight_dispatch.py` currently exits into `local_fallback` before value-gate analysis
when spawn policy requires explicit delegation intent. That preserves safety, but it
erases whether the task was otherwise delegation-worthy.

New dispatch payload shape:

```json
{
  "decision": "local_fallback",
  "reason": "spawn_agent tool policy requires explicit user delegation intent",
  "failed_prerequisites": ["spawn_policy_requires_explicit_user_request"],
  "delegation_policy": {
    "safety_gate": "passed",
    "value_gate": "skipped_by_spawn_policy",
    "effective_mode": "local_fallback",
    "would_have_decision": "delegate",
    "would_have_reason": "all pre-dispatch prerequisites passed",
    "signals": {
      "declared_file_count": 2,
      "allowed_write_glob_count": 2,
      "dependency_count": 0,
      "packet_budget_status": "green",
      "risk_markers": []
    }
  }
}
```

Rules:

- Hard safety blockers still set final `decision=block`.
- Dirty overlap, packet hash mismatch, broad write scope, forbidden write match, red
  context budget, and missing packet remain safety blockers or local fallback reasons as
  they do today.
- Would-have evidence is advisory. It does not authorize spawn.
- Existing `decision`, `reason`, `failed_prerequisites`, `delegation_policy.effective_mode`,
  and task `subagent_strategy` remain authoritative for lifecycle closure.

### 4. AgentLens Status Classification

AgentLens remains best-effort. The state should distinguish environment absence from
emission failure.

State shape remains:

```json
{
  "agentlens_status": {
    "schema_version": "1",
    "status": "agentlens_unavailable",
    "blocking": false
  }
}
```

Interpretation:

- `agentlens_unavailable`: informational followup. The CLI/runtime is absent.
- `agentlens_emit_failed`: actionable followup. CPE expected to emit but the emission
  failed.
- `agentlens_recorded`: no followup.
- `agentlens_not_applicable`: no followup for prompt/handoff or non-logging modes.

Completion audit residual risk may still mention AgentLens absence, but recent-run rubric
must not treat absent AgentLens as evidence failure when completion evidence is otherwise
complete.

### 5. Full-Spec Fallback Next Action

Full-spec fallback remains the primary actionable context-quality debt in the recent 3-run
sample. The goal is not to hide it, but to make the next fix obvious.

Task packet/readiness evidence should expose:

```json
{
  "spec": {
    "fallback_used": true,
    "mapping": {
      "fallback_reason": "weak_heuristic_match",
      "suggested_spec_refs": ["S6", "S6.1"],
      "next_action": "Add explicit spec_refs for task_6 in the implementation plan."
    }
  }
}
```

Allowed `next_action` values are generated from deterministic fields:

- Missing task refs: add explicit `spec_refs` to the task.
- Manifest gap: update `spec_manifest` mapping or section ids.
- Weak heuristic match: add or correct section ids in the spec/plan pair.
- Operator-reviewed fallback: record `operator_decision` and keep context budget evidence.

### 6. Recent-Run Analysis Output

`analyze_recent_runs.py` should keep the current JSON report shape and add summary fields.

New report fields:

```json
{
  "summary": {
    "run_count": 3,
    "finished_passed_count": 3,
    "green_count": 0,
    "green_with_info_count": 2,
    "yellow_count": 1,
    "red_count": 0,
    "actionable_followup_count": 1,
    "informational_followup_count": 6
  },
  "rubric": {
    "safety": "green",
    "context": "yellow",
    "delegation_efficiency": "green-with-info",
    "evidence": "green",
    "validator_maintainability": "green"
  }
}
```

Rules:

- A run with only informational followups may be reported as `green-with-info` in
  aggregate analysis.
- The embedded `state.json` grade remains backward compatible.
- `validator_maintainability` must be computed from actual validation/eval evidence or
  omitted. It must not be hard-coded yellow.
- Report-level dimensions can use `green-with-info`; state-level `run_quality.grade`
  cannot.

## Data Flow

```text
state.json + run artifacts
  -> normalize_cpe_run.py
  -> run_quality_debt taxonomy
  -> analyze_recent_runs.py rubric
  -> operator summary

task packet + state + write scope
  -> preflight_dispatch.py
  -> final decision + would-have dispatch evidence
  -> state dispatch_decisions + task subagent_strategy
  -> validate_state.py consistency checks
```

## Error Handling

- If a state lacks `followup_taxonomy`, analysis derives it from `open_followups`.
- If a dispatch lacks `would_have_decision`, analysis treats it as older-state compatible
  and does not fail.
- If `agentlens_status` is absent but `agentlens_orchestration_run` is also absent in an
  execution mode, analysis keeps the backward-compatible `agentlens_missing` followup.
- If `agentlens_emit_failed` appears, it is actionable even though it is non-blocking.
- If a state has `green-with-info` inside `run_quality.grade`, validation fails because
  state grade remains `green|yellow|red`.

## Acceptance Criteria

- Running recent-run analysis on the 3 inspected 2026-07-05 states separates:
  - informational AgentLens absence,
  - informational expected local fallback caused by explicit-request policy,
  - actionable full-spec fallback in `memory-corpus-review-deeplinks`.
- A finished run with only `agentlens_missing` and
  `delegation_policy_expected_local_fallback` can be reported as `green-with-info` in
  aggregate analysis without changing `completion_audit.passed`.
- A run with unreviewed `full_spec_fallback_present` remains yellow/actionable.
- Dispatch payloads preserve final local fallback decisions while recording would-have
  safety/value evidence when spawn policy blocks actual delegation.
- Existing state validation remains backward compatible with older finished runs.
- Deterministic evals cover old-state compatibility, expected local fallback, AgentLens
  status classification, full-spec fallback actionability, and report-level
  `green-with-info`.

## Verification

Implementation should prove the behavior with:

```bash
cd skills/kws-codex-plan-executor
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_skill_contract.py --skill SKILL.md
./evals/run.sh
cd /Users/kws/source/private/Archive
bun run check
git diff --check
```

When the implementation changes code or meaningful documentation structure, run Graphify
freshness commands according to repository instructions and record the result in completion
evidence.

## Self-Review

- Placeholder scan: no placeholders or unfinished markers remain.
- Internal consistency: state-level grades stay `green|yellow|red`; `green-with-info` is
  report-level only.
- Scope check: the design is one implementation plan focused on CPE operational-quality
  signal classification, dispatch evidence, and eval coverage.
- Ambiguity check: AgentLens absence, expected local fallback, and full-spec fallback each
  have distinct classifications and acceptance criteria.
