# CPE Run Quality Cleanup Umbrella Design

작성일: 2026-07-01
상태: DRAFT SPEC FOR REVIEW
대상 표면: `skills/kws-codex-plan-executor`, CPE deterministic eval harness, Superpowers plan/task-packet handoff

## Problem

최근 완료된 CPE 실행 5개를 읽기 전용으로 조사했다.

- `2026-06-30-readmates-frontend-observability-v2-20260630-140037`
- `2026-06-30-readmates-production-observability-v1-20260630-040540`
- `readmates-admin-workspace-switcher-20260630-104547`
- `memory-retrieval-20260630-091523`
- `2026-06-28-readmates-performance-budget-bundle-diet-20260628-020935`

모두 `completion_audit.passed=true`였고 제품 검증은 통과했다. 그러나 모두
`run_quality.grade=yellow`였다. `yellow` 자체는 실패가 아니다. CPE 계약상
제품 검증 성공과 executor 운영 품질 부채는 분리되어야 한다. 문제는 최근 실행들이
같은 부채를 반복해서 남긴다는 점이다.

반복 신호:

| 신호 | 관측 | 의미 |
| --- | ---: | --- |
| `agentlens_missing` | 5/5 | 제품 실패가 아니라 replay/learning evidence 공백 |
| `delegation_policy_prevented_all_delegation` | 5/5 | `subagents_requested=true`이지만 명시적 위임 의도가 없어 전부 local fallback |
| `full_spec_fallback_present` | 4/5, 총 13개 task | task-specific spec slicing 부족 |
| `readiness_fixable_issues` | 4/5 | 실행 전 metadata 품질이 낮지만 blocker는 아님 |
| plan audit artifact/state summary 불일치 | 최소 3/5 | 원본 audit count와 state embedded count가 drift됨 |
| prompt audit | 5/5 pass | prompt cache boundary 자체는 안정적 |
| Graphify | 5/5 fresh | Graphify 자체는 주요 blocker가 아님 |

현재의 안전장치는 대부분 맞게 작동한다. full-spec fallback은 실행을 막지 않고
품질 debt로 남긴다. tool policy 때문에 subagent를 못 쓰는 것도 안전한 local
fallback이다. Graphify와 prompt audit도 대체로 통과한다. 이번 개선은 안전장치를
낮추는 작업이 아니라, 반복되는 `yellow`를 더 정확하고 덜 noisy하게 만드는 작업이다.

## Goals

- 최근 5개 완료 런에서 반복된 `yellow` 원인을 줄이거나 더 정확히 분류한다.
- task packet의 full-spec fallback을 plan/spec 단계에서 줄인다.
- write scope와 dependency metadata를 CPE audit, dispatch, readiness가 같은 방식으로
  읽게 만든다.
- plan executability audit artifact와 `state.json` embedded summary의 drift를
  deterministic하게 검출한다.
- explicit delegation tool policy 때문에 예상된 local fallback은 executor debt와
  분리한다.
- Waygent/CME harness에서 검증된 normalized replay와 fixture coverage map 패턴을
  CPE에 맞게 가져온다.
- 기본 검증은 Python stdlib와 기존 Bash eval harness 안에서 deterministic하게 유지한다.

## Non-goals

- `spawn_agent` 정책을 우회하지 않는다.
- `subagents=on` 기본 계약을 제거하지 않는다.
- full-spec fallback이 있는 과거 실행을 실패로 재분류하지 않는다.
- AgentLens best-effort 이벤트를 hard blocker로 바꾸지 않는다.
- Waygent runtime을 CPE 내부 dependency로 가져오지 않는다.
- 외부 LangGraph, AutoGen, CrewAI, OpenHands, SWE-agent, Harness CLI를 CPE runtime
  dependency로 추가하지 않는다.
- LLM judge를 기본 eval gate로 넣지 않는다.
- baseline 파일을 기본 eval 실행에서 자동 갱신하지 않는다.
- raw transcript, full prompt, secret-bearing host output을 durable artifact에 저장하지
  않는다.

## Reviewed Approaches

### A. Make Yellow Strictly Blocking

`full_spec_fallback`, `agentlens_missing`, delegation local fallback이 있으면 finished
state를 실패로 만든다.

장점:

- 품질 부채가 절대 묻히지 않는다.

단점:

- 제품 검증이 통과한 실행을 실패로 오분류한다.
- AgentLens best-effort 계약과 충돌한다.
- tool policy상 정상적인 local fallback까지 blocker가 된다.

이 접근은 거부한다.

### B. Only Improve Operator Documentation

현재 `yellow` 의미를 문서에 더 잘 설명하고 코드는 유지한다.

장점:

- 구현 위험이 낮다.
- 기존 state compatibility가 가장 좋다.

단점:

- full-spec fallback, audit drift, dependency key mismatch 같은 실제 반복 원인을
  줄이지 못한다.
- 다음 실행도 같은 yellow를 만들 가능성이 높다.

이 접근도 충분하지 않다.

### C. Recommended: Metadata Parity And Replay-Backed Quality Cleanup

기존 CPE safety gate는 유지하고, 세 층을 보강한다.

1. plan/spec/task packet metadata를 더 잘 매핑한다.
2. readiness, plan executability, dispatch, state validation이 같은 helper와 같은
   reason vocabulary를 쓰게 한다.
3. finished run을 normalized replay fixture로 검증해 state, audit, final output drift를
   재현 가능한 eval로 만든다.

장점:

- 제품 검증 성공과 executor 운영 debt를 계속 분리한다.
- 최근 로그에서 반복된 실질 원인을 줄인다.
- Harness/Waygent/CME에서 검증된 deterministic replay 패턴을 dependency 없이 전이한다.
- 기존 v2.24 계약 위에 좁게 쌓을 수 있다.

단점:

- helper 공유와 state validation 추가로 eval surface가 늘어난다.
- state summary의 원본 count와 operator-applied count를 구분해야 해 schema 설명이
  조금 더 복잡해진다.

선택한 접근은 C다.

## Design

### 1. Spec Mapping And Task Packet Metadata

현재 CPE는 `Spec Refs:` 같은 visible markdown label에서 `S1`, `S2.1` 형식의
section id를 읽는다. structured `yaml waygent-task` 안의 `spec_refs`는 아직
실행 계약으로 쓰이지 않는다. 또한 `build_task_packet.py`는 manifest가 가진
task-to-section mapping을 사용하지 않고 explicit refs, heuristic, full fallback 순서로
떨어진다.

새 규칙:

1. `parse_plan.py`는 fenced `yaml waygent-task`와 `yaml agentrunway-task`에서
   `spec_refs` 배열을 읽는다.
2. visible markdown `Spec Refs:`와 hidden fenced/comment 차단 동작은 유지한다.
3. `build_task_packet.py`의 section resolution 순서는 다음과 같다.
   - explicit task `spec_refs`
   - spec manifest의 `task_to_sections[task_id]`
   - 기존 file/title/task signal heuristic
   - fallback policy
4. task packet은 `depends_on`과 `dependencies`를 같은 값으로 함께 기록한다.
5. packet mapping evidence에는 `mapping_reason`, `selected_section_ids`,
   `candidate_scores`, `source=explicit|manifest|heuristic|fallback`을 남긴다.

이 변경의 목적은 full-spec fallback을 무조건 없애는 것이 아니다. 계획이 실제로
매핑 정보를 줄 수 있는데 CPE가 놓쳐서 full fallback이 되는 경우를 줄이는 것이다.

### 2. Shared Audit Semantics

현재 `audit_run_readiness.py`, `audit_plan_executability.py`, `preflight_dispatch.py`는
비슷한 로직을 각자 구현한다. 특히 write scope malformed 판단, dependency count,
local fast path 판단이 조금씩 다르다.

새 shared helper를 추가한다.

```text
skills/kws-codex-plan-executor/scripts/cpe_audit_common.py
```

책임:

- list-like string extraction
- comma/newline joined write-scope detection
- suggested write-scope normalization
- dependency aliases: `dependencies` 우선, 없으면 `depends_on`
- risky path marker classification
- docs-only/small-scope/linear-task helper
- stable reason vocabulary constants

정책:

- malformed write scope를 조용히 허용하지 않는다.
- audit/readiness 출력은 `suggested_write_scopes`를 낸다.
- dispatch path는 여전히 반복 `--write-scope <glob>` 형태를 정상 입력으로 본다.
- newline-joined path도 comma-joined path와 같은 fixable formatting issue로 본다.

### 3. Plan Audit Artifact And State Parity

최근 실행 중 일부는 `plan_executability_audit.json` 원본의 fixable/blocking count와
`state.json`에 embedded된 compact summary가 다르게 보였다. operator decision으로
blocking을 review 처리하는 것은 허용해야 하지만, 원본 count와 decision-applied count가
섞이면 나중에 inspection에서 원인을 재구성하기 어렵다.

새 state summary shape:

```json
{
  "plan_executability_audit": {
    "path": "/Users/example/.codex/orchestrator/run/plan_executability_audit.json",
    "grade": "yellow",
    "raw_grade": "red",
    "blocking_issue_count": 0,
    "fixable_issue_count": 3,
    "raw_blocking_issue_count": 2,
    "raw_fixable_issue_count": 3,
    "operator_reviewed_blocking_issues": [
      "task_1:risk_marker_requires_operator_review"
    ],
    "operator_decision": "Proceed locally after reading repo deployment guides."
  }
}
```

Validation rules:

- `raw_*` fields are optional for older states.
- If `raw_*` fields are present, they must match the artifact file when the file is
  readable.
- `blocking_issue_count` may be lower than `raw_blocking_issue_count` only when
  `operator_reviewed_blocking_issues` and `operator_decision` are present.
- finished state cannot retain effective red audit unless it is blocked/failed.
- if `fixable_issue_count > 0`, `run_quality.open_followups` includes
  `plan_executability_fixable_issues`.
- if `run_quality.readiness.plan_executability_fixable_issue_count` is present, it
  equals `plan_executability_audit.fixable_issue_count`.

### 4. Delegation Policy Classification

최근 5개 완료 실행은 모두 `subagents_requested=true`였지만
`explicit_user_delegation_request=false`였고, tool policy 때문에 local fallback이
발생했다. 이것은 안전한 fallback이지만 매번
`delegation_policy_prevented_all_delegation`으로 남으면 실제 개선 대상과 정상 정책
결과가 섞인다.

새 분류:

- `delegation_policy_expected_local_fallback`: 세션 tool policy가 explicit request를
  요구하고, 사용자가 명시적으로 위임을 요청하지 않았고, 실행이 local path를 계획대로
  따랐다.
- `delegation_policy_prevented_all_delegation`: delegate-worthy task가 있었고,
  operator가 subagent/delegation을 명시 요청했거나 `subagents=on`을 explicit하게
  지정했는데도 모든 dispatch가 policy fallback으로 접혔다.
- `delegation_policy_missing_dispatch_evidence`: finished write-capable task가 있는데
  dispatch decision이 없어 delegation 결과를 설명할 수 없다.

Completion semantics:

- expected local fallback은 `run_quality.grade=yellow`를 강제하지 않는다.
- missing dispatch evidence는 yellow follow-up이다.
- explicit delegation 요청이 있었는데 전부 policy fallback이면 yellow follow-up이다.
- safety gate 실패로 local fallback이 난 것은 계속 task `subagent_strategy.reason`에
  남는다.

### 5. AgentLens And Lens Evidence

Archive의 active product direction은 Waygent/Lens다. CPE state에는 아직
`agentlens_orchestration_run` best-effort evidence가 남아 있고, tool이 없으면
`agentlens_missing`이 반복된다.

이번 범위에서는 AgentLens를 hard dependency로 만들지 않는다. 대신 evidence debt를
분류한다.

- `agentlens_missing_optional`: tool absent 또는 ignored by policy. 제품 검증 실패가
  아니며 yellow를 강제하지 않는다.
- `agentlens_missing_required`: run이 AgentLens/Lens replay evidence를 acceptance로
  요구했는데 누락됨. yellow 또는 red가 될 수 있다.
- `lens_replay_available`: Waygent/Lens 경로에서 normalized replay evidence를 읽을 수
  있음.

이 분류는 CPE가 Waygent runtime을 호출한다는 뜻이 아니다. CPE는 자기 state와
orchestrator artifacts를 먼저 보고, Lens/AgentLens는 best-effort evidence ref로만
다룬다.

### 6. Structured Residual Risk

현재 `completion_audit.residual_risk`는 문자열 배열이다. operator-owned external
dependency와 제품 미검증 위험이 같은 문장 배열에 섞인다.

새 shape는 backward-compatible하게 문자열 배열을 허용하면서 객체 배열을 지원한다.

```json
{
  "owner": "operator",
  "class": "external_credentials",
  "summary": "Production metrics deploy requires VM_PUBLIC_IP and SSH_KEY.",
  "blocks_release": false,
  "unblocks_when": "Operator provides production deployment credentials and reruns deploy smoke.",
  "evidence_ref": "completion_audit.verification_evidence[12]"
}
```

Allowed `owner`:

- `executor`
- `operator`
- `product`
- `environment`

Allowed `class`:

- `external_credentials`
- `deployment`
- `monitoring`
- `executor_evidence`
- `environment_unavailable`
- `product_followup`

Validation:

- string residual risks remain valid for old states.
- object residual risks require `owner`, `class`, `summary`, and `blocks_release`.
- `blocks_release=true` with `completion_audit.passed=true` is invalid unless
  `lifecycle_outcome` is `blocked` or `failed`.

### 7. Normalized CPE Replay Harness

Waygent scenario harness normalizes runtime output into a compact replay shape before
asserting expected behavior. CME harness documents coverage and avoids treating harness bugs
as skill regressions. CPE should import that pattern without importing the runtime.

New script:

```text
skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py
```

Input:

- `--state <state.json>`
- optional `--run-dir <dir>`
- optional `--context <context.json>`
- optional `--final-output <file>`

Output:

```json
{
  "schema_version": "1",
  "run_id": "example",
  "terminal_state": "finished",
  "completion_passed": true,
  "run_quality_grade": "yellow",
  "open_followups": ["full_spec_fallback_present"],
  "task_count": 4,
  "full_spec_fallback_count": 2,
  "dispatch_decision_reasons": {
    "spawn_agent tool policy requires explicit user delegation intent": 4
  },
  "plan_executability": {
    "grade": "yellow",
    "raw_grade": "yellow",
    "fixable_issue_count": 2,
    "raw_fixable_issue_count": 2
  },
  "prompt_audit_passed": true,
  "graphify_fresh": true,
  "residual_risk_classes": ["external_credentials"],
  "forbidden_patterns_found": []
}
```

New eval:

```text
skills/kws-codex-plan-executor/evals/check_cpe_replay.py
```

It uses synthetic state fixtures and recent-run-shaped fixtures. It does not read private
full transcripts. It asserts subset fields, exact fields where stable, and forbidden patterns
such as home directory leaks, tokens, and full prompt text.

Coverage map:

```text
skills/kws-codex-plan-executor/docs/eval-coverage-cpe.md
```

It maps deterministic evals to failure modes:

- spec mapping fallback
- write-scope formatting
- dependency alias drift
- plan audit/state parity
- delegation policy expected fallback
- structured residual risk
- prompt audit reference
- Graphify command-only evidence
- normalized replay forbidden patterns

## Data Flow

```text
parse_plan.py
  -> parsed plan with markdown/yaml spec_refs and depends_on
build_spec_manifest.py
  -> sections and optional task_to_sections
build_task_packet.py
  -> task packet with spec mapping evidence, depends_on, dependencies
audit_run_readiness.py
audit_plan_executability.py
preflight_dispatch.py
  -> shared cpe_audit_common semantics
state.json
  -> raw and operator-applied plan audit summary
validate_state.py
  -> parity, delegation evidence, residual risk schema
normalize_cpe_run.py
  -> deterministic replay payload
check_cpe_replay.py
  -> fixture coverage proof
```

## Error Handling

- Missing spec mapping stays fixable unless `manifest_fallback=halt_on_blocker`.
- Unknown explicit `spec_refs` remains blocking.
- Malformed write scope remains fixable in audit/readiness and blocking in actual dispatch
  when it would make the write boundary unsafe.
- Missing dispatch evidence on a write-capable finished task is a yellow follow-up, not a
  product verification failure.
- Audit artifact unreadable during validation is a schema warning for non-terminal states
  and a validation error for finished operational-quality states that claim parity.
- `agentlens_missing_optional` is not a hard blocker.
- Structured residual risk with `blocks_release=true` cannot be hidden behind a passing
  completion audit.

## Acceptance Criteria

- `parse_plan.py` extracts `spec_refs` from visible `yaml waygent-task` and
  `yaml agentrunway-task` blocks while preserving hidden fenced/comment exclusion.
- `build_task_packet.py` selects spec sections in this order:
  explicit refs, manifest `task_to_sections`, heuristic, fallback.
- task packets emit both `depends_on` and `dependencies` with identical values.
- `preflight_dispatch.py`, `audit_run_readiness.py`, and
  `audit_plan_executability.py` use shared dependency and write-scope helpers.
- newline-joined and comma-joined write scopes produce `write_scope_format_invalid` with
  deterministic `suggested_write_scopes`.
- finished state validation detects plan audit artifact/state count mismatch when raw
  fields are present.
- operator-reviewed audit blockers preserve both raw blocker count and effective blocker
  count.
- expected local fallback due explicit-request-required tool policy does not by itself
  force `delegation_policy_prevented_all_delegation`.
- explicit user delegation request plus all-policy fallback still records
  `delegation_policy_prevented_all_delegation`.
- finished write-capable tasks without dispatch evidence record
  `delegation_policy_missing_dispatch_evidence`.
- structured residual risk objects validate, and `blocks_release=true` cannot coexist with
  a passing finished outcome.
- `normalize_cpe_run.py` produces deterministic JSON for synthetic finished and blocked
  states.
- `check_cpe_replay.py` is wired into `evals/run.sh` and does not mutate tracked baselines.
- `docs/eval-coverage-cpe.md` maps each new fixture to the failure mode it protects.
- Existing focused evals continue to pass:
  `check_task_packet.py`, `check_run_readiness.py`, `check_plan_executability_audit.py`,
  `check_preflight_dispatch.py`, `check_operational_run_quality.py`.

## Verification

Run from `/Users/kws/source/private/Archive/skills/kws-codex-plan-executor`:

```bash
python3 evals/check_parse_plan.py
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
python3 evals/check_plan_executability_audit.py
python3 evals/check_preflight_dispatch.py
python3 evals/check_state_schema.py
python3 evals/check_operational_run_quality.py
python3 evals/check_cpe_replay.py
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

Run from `/Users/kws/source/private/Archive`:

```bash
git diff --check
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root . --update-ran
```

## Self-Review

- Placeholder scan: no placeholder markers or unspecified owner remains in this spec.
- Scope check: this is one umbrella because the three original improvements share the same
  CPE state/eval contract. The implementation plan still splits work into independently
  reviewable tasks.
- Consistency check: the design keeps CPE as Python stdlib + deterministic Bash evals and
  does not import Waygent runtime or external harness dependencies.
- Ambiguity check: expected local fallback and prevented delegation are separate named
  follow-ups so future implementers do not collapse policy behavior into product failure.
