# Superpowers CPE Task Packet Quality Audit Design

작성일: 2026-06-25
상태: APPROVED DESIGN SPEC
대상 표면: `skills/kws-codex-plan-executor`, Superpowers `brainstorming` -> `writing-plans` -> CPE execution handoff

## Problem

현재 Superpowers와 CPE의 큰 방향은 맞다.

- `brainstorming`은 설계 승인 전 구현을 막고, 승인된 설계를 spec으로 남긴다.
- `writing-plans`는 agentic worker가 task-by-task로 실행할 수 있는 계획을 만든다.
- `subagent-driven-development`는 fresh implementer, task reviewer, final reviewer
  루프로 구현 품질을 지킨다.
- CPE는 approved interactive implementation plan에서 Superpowers loop를 우선
  사용하고, worktree, state, task packet, validation, completion audit evidence를
  보존하는 thin stateful bridge로 남는다.

하지만 두 시스템 사이에 남은 약점이 있다. Superpowers plan이 CPE task packet으로
변환될 때 실행 가능성 품질을 미리 판정하는 전용 게이트가 약하다. 그 결과 다음
문제가 뒤늦게 드러날 수 있다.

1. task별 file claim은 있지만 allowed/forbidden write glob으로 좁혀지지 않는다.
2. acceptance command가 모호해서 CPE가 honest substitute에 기대야 한다.
3. spec section과 task packet의 연결이 약해 full-spec fallback이 늘어난다.
4. task가 subagent 독립 실행에 적합한지, local fast path가 맞는지 사람이 매번
   판단해야 한다.
5. Graphify, prompt cache audit, run readiness 같은 CPE 증거 요구가 plan 작성
   단계에 충분히 반영되지 않는다.

이번 개선은 Superpowers 실행 루프를 CPE로 대체하려는 작업이 아니다. 반대로
Superpowers가 잘하는 설계/계획/구현 루프를 유지하면서, CPE가 실행 전에 소비할 수
있는 task packet 품질을 높이는 감사와 보강 표면을 추가한다.

## Goals

- Superpowers plan을 실행하기 전에 CPE task packet 적합성을 deterministic하게
  점수화한다.
- plan 작성자가 고칠 수 있는 문제와 CPE가 자동 보강할 수 있는 문제를 분리한다.
- CPE `interactive` readiness summary가 "왜 thin bridge인지", "어떤 task가
  delegate/local/block인지", "어떤 증거가 부족한지"를 한 번에 보여준다.
- `writing-plans` 산출물이 CPE의 `Files`, acceptance, write policy, risk marker,
  Graphify evidence 요구를 더 잘 충족하게 만든다.
- 안전장치는 낮추지 않는다. TDD, task contract, worktree isolation, state
  validation, run quality audit은 그대로 유지한다.

## Non-goals

- `brainstorming`의 hard gate를 완화하지 않는다.
- 설계 승인 없이 CPE 실행을 시작하지 않는다.
- Superpowers `subagent-driven-development`를 CPE 자체 구현 루프로 복제하지 않는다.
- `spawn_agent` 정책이나 explicit delegation requirement를 우회하지 않는다.
- full-spec fallback이 있는 실행을 무조건 실패 처리하지 않는다.
- 기존 plan/spec 문서를 자동 rewrite하지 않는다. 자동 보강은 새 run artifact와
  명시적 suggestion에 한정한다.

## Reviewed Approaches

### A. Superpowers Native Only

CPE를 거치지 않고 Superpowers `subagent-driven-development`만 사용한다.

장점:

- 구현 루프가 단순하다.
- Superpowers skill 계약과 가장 직접적으로 맞는다.

단점:

- CPE의 state, resume, headless, prompt/handoff, task packet, Graphify, prompt
  cache, run quality evidence를 잃는다.
- 실행 후 inspection과 repair 표면이 약해진다.

### B. CPE Primary Execution Loop

CPE가 task parsing부터 subagent dispatch, review, finalization까지 직접 소유한다.

장점:

- 모든 evidence가 CPE state 안에 들어간다.
- 기존 headless/prompt/handoff 구조와 일관된다.

단점:

- Superpowers가 이미 정의한 구현/리뷰 루프를 중복한다.
- operator cost가 높고, 스킬 지침이 서로 경쟁할 위험이 있다.

### C. Recommended: Executability Audit Before Thin Bridge

Superpowers loop는 그대로 두고, CPE가 실행 전에 plan -> task packet 품질을 감사한다.
감사는 read-only로 실행되며, fixable issue와 auto-enhancement suggestion을 만든다.
실행은 compatibility audit이 통과하면 thin stateful bridge로 진행한다.

장점:

- 현재 통과하는 Superpowers/CPE 계약을 깨지 않는다.
- CPE가 필요한 evidence 품질을 plan 단계에서 끌어올린다.
- small/local, delegate-worthy, block-worthy task 구분을 사람이 덜 반복한다.
- headless/prompt/handoff/resume/inspection은 계속 CPE가 소유한다.

단점:

- 감사 결과와 task packet 생성 결과가 drift되지 않도록 eval을 추가해야 한다.
- plan 작성 단계에서 CPE 용어가 과하게 노출되지 않도록 user-facing 출력은
  간결해야 한다.

선택한 접근은 C다.

## Design

### 1. New Executability Audit

새 read-only 감사 스크립트를 추가한다.

```text
skills/kws-codex-plan-executor/scripts/audit_plan_executability.py
```

입력:

- plan path
- optional spec path
- optional docs paths
- repo root
- generated task packet directory가 있으면 그 경로

출력:

```json
{
  "schema_version": "1",
  "passed": true,
  "grade": "green",
  "summary": "6 tasks audited, 5 executable, 1 fixable",
  "tasks": [
    {
      "task_id": "task_1",
      "files_status": "green",
      "acceptance_status": "green",
      "write_policy_status": "yellow",
      "subagent_fit": "local_fast_path",
      "risk_markers": [],
      "fixable_issues": ["allowed_write_globs_can_be_narrowed"],
      "blocking_issues": [],
      "suggested_write_scopes": ["skills/kws-codex-plan-executor/scripts/**"]
    }
  ],
  "global_followups": []
}
```

Grade semantics:

- `green`: 모든 write-capable task가 executable이고 blocking issue가 없다.
- `yellow`: 실행은 가능하지만 fixable issue나 quality follow-up이 있다.
- `red`: missing files, missing plan tasks, broad write scope, risky unreviewed path,
  missing acceptance on mid/high-risk task 같은 blocker가 있다.

### 2. Audit Dimensions

감사는 task별로 다음 차원을 평가한다.

- `files_status`: `Files` 또는 fenced `yaml waygent-task`/`agentrunway-task`가
  실제 repo path 안에 있고 비어 있지 않은가.
- `acceptance_status`: acceptance command가 task 위험도에 맞게 구체적인가.
- `write_policy_status`: allowed/forbidden write globs가 너무 넓지 않은가.
- `spec_mapping_status`: spec section이나 decision이 task와 연결되는가.
- `subagent_fit`: `delegate`, `local_fast_path`, `local_only`, `operator_review`,
  `block` 중 어떤 실행 방식이 적합한가.
- `evidence_status`: Graphify, prompt cache, run readiness, state validation 등
  CPE completion evidence가 plan에 반영 가능한가.

감사는 `scripts/preflight_dispatch.py`의 reason vocabulary와 충돌하지 않게 같은
reason string을 재사용한다. 예를 들어 docs-only small task는
`adaptive_policy_local_fast_path_docs_only`를 제안하고, lockfile/security/infra는
`risk_marker_requires_operator_review`를 제안한다.

### 3. Writing Plans Guidance

`writing-plans` 자체를 직접 수정하지 않고, CPE skill 문서와 user guide에
"CPE-friendly Superpowers plan" 규칙을 추가한다.

권장 plan task 형식:

- `**Files:**` 아래에 create/modify/test path를 정확히 적는다.
- task마다 acceptance command 또는 honest substitute를 적는다.
- risk가 있는 task는 `risk_markers`를 명시한다.
- write scope가 넓어질 수 있는 task는 fenced `yaml waygent-task`에
  `file_claims`를 넣는다.
- Graphify-aware repo에서 code 또는 docs structure를 바꾸면 `graphify update .`
  필요 여부를 Verification에 적는다.

이 문서는 Superpowers plan을 CPE 전용 문서로 바꾸지 않는다. Superpowers가 읽기
쉬운 plan 형식을 유지하되, CPE가 deterministic하게 실행 가능성을 판정할 수 있는
필드를 자연스럽게 채운다.

### 4. Interactive Readiness Summary

CPE interactive route는 compatibility audit 이후, task contract 전 단계에서
executability audit summary를 출력한다.

예시:

```text
CPE readiness:
- route: thin_stateful_bridge
- tasks: 6 total, 4 delegate-ready, 1 local-fast-path, 1 fixable
- blockers: none
- fixable: task_3 acceptance command missing; honest substitute available
- evidence: Graphify required after code/doc structure changes
```

이 summary는 operator-facing 출력이다. raw JSON은
`~/.codex/orchestrator/<run_id>/plan_executability_audit.json`에 저장한다.

### 5. State and Run Quality Link

`state.json`에는 다음 필드를 추가한다.

```json
{
  "plan_executability_audit": {
    "path": "~/.codex/orchestrator/<run_id>/plan_executability_audit.json",
    "grade": "yellow",
    "blocking_issue_count": 0,
    "fixable_issue_count": 1
  }
}
```

Finished run의 `run_quality.readiness`는 이 감사 결과를 참조한다. 감사 grade가
yellow인데 실행을 계속한 경우, completion audit의 `residual_risk`나
`verification_evidence`에 operator decision이 남아야 한다.

### 6. Error Handling

- Missing plan: 기존 CPE stop rule대로 blocker다.
- Missing file blocks: `red` audit이고 execution mode는 편집 전에 멈춘다.
- Acceptance missing:
  - docs-only low-risk task면 `yellow`와 honest substitute suggestion을 낸다.
  - behavior/security/infra task면 `red`로 멈춘다.
- Broad write scope: `red`로 멈추고 normalized write scope suggestion을 출력한다.
- Risk marker present: `operator_review` 또는 `block`으로 분기한다.
- Audit script failure: CPE 실행 실패가 아니라 preflight blocker다. traceback 대신
  unreadable input, invalid JSON, missing task packet 같은 구체 사유를 기록한다.

### 7. Eval Coverage

새 deterministic eval을 추가한다.

```text
skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py
```

필수 fixture:

1. `green_superpowers_plan`: 정확한 files, acceptance, narrow write scope가 있는 plan.
2. `yellow_fixable_acceptance`: docs-only task에 acceptance command가 없지만 honest
   substitute가 가능한 plan.
3. `red_missing_files`: executable task인데 file block이 없는 plan.
4. `red_broad_scope`: `**/*` 같은 broad write scope가 있는 plan.
5. `risk_marker_operator_review`: lockfile/security/infra path가 포함된 plan.
6. `thin_bridge_summary`: compatibility audit 통과 후 readiness summary가 route와
   task counts를 포함하는 fixture.

기존 eval과 연결:

- `check_skill_contract.py`는 새 audit script와 readiness summary 계약을 확인한다.
- `check_preflight_dispatch.py`는 reason string 호환성을 유지한다.
- `check_operational_run_quality.py`는 audit follow-up이 run_quality에 연결되는지
  확인한다.

## Acceptance Criteria

- Superpowers plan을 실행하기 전에 task packet 적합성을 deterministic JSON으로
  볼 수 있다.
- `thin_stateful_bridge` route가 유지되고, CPE가 Superpowers 구현 루프를 중복하지
  않는다.
- Missing files, broad write scope, risky lockfile/security/infra changes는 편집 전
  red/block으로 드러난다.
- Low-risk docs-only task는 필요한 경우 yellow/local fast path로 진행할 수 있다.
- Completion audit과 run quality가 plan executability audit 결과를 참조한다.
- User-facing 출력은 짧은 readiness summary이고, 세부 JSON은 orchestrator artifact로
  보존된다.

## Verification

- `python3 skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`
- `python3 skills/kws-codex-plan-executor/evals/check_skill_contract.py --skill skills/kws-codex-plan-executor/SKILL.md`
- `python3 skills/kws-codex-plan-executor/evals/check_superpowers_compatibility.py`
- `python3 skills/kws-codex-plan-executor/evals/check_preflight_dispatch.py`
- `python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
- `python3 -m py_compile skills/kws-codex-plan-executor/scripts/*.py skills/kws-codex-plan-executor/evals/*.py`
- `bash -n skills/kws-codex-plan-executor/evals/run.sh`
- `git diff --check`
