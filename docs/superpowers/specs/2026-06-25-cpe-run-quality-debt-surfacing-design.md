# CPE Run Quality Debt Surfacing Design

작성일: 2026-06-25
상태: APPROVED DESIGN SPEC
대상 표면: `skills/kws-codex-plan-executor` run inspection, finished state quality summary, validator/eval coverage

## Problem

최근 CPE 실행 3개를 분석했다.

- `2026-06-25-readmates-lighthouse-diagnostic-20260625-060445`
- `2026-06-25-readmates-host-admin-member-defect-polish-20260625-045334`
- `agent-first-setup-contract-20260625-045310`

세 실행 모두 `lifecycle_outcome=finished`였고
`skills/kws-codex-plan-executor/scripts/validate_state.py`는 `state ok`를 반환했다.
제품 검증도 대체로 충분했다. 그러나 완료 상태가 운영 품질 부채를 일관되게
드러내지는 못했다.

반복 증상:

1. 전체 15개 task 중 readiness 기준 `delegate_ready` task가 8개였지만 실제
   delegated task는 0개였다. 모든 task가 세션 도구 정책의 명시적 위임 요청
   부재로 `local_fallback` 처리됐다.
2. 전체 15개 task 중 7개가 `full_spec_fallback` readiness issue를 가졌다.
   실행은 완료됐지만 task packet 품질 저하가 다음 실행 개선으로 충분히 연결되지
   않는다.
3. 세 실행 모두 `agentlens_orchestration_run`이 없었다. AgentLens 이벤트는
   best-effort이므로 실패가 실행을 막으면 안 되지만, replay/learning evidence
   공백은 품질 신호로 남아야 한다.
4. 완료 후 2개 실행의 `execution_worktree`가 사라졌다. `inspect_runs.py`는
   읽기 시점에 `missing_execution_worktree`를 계산할 수 있지만, embedded
   `run_quality.open_followups`와 inspection 결과가 달라질 수 있다.
5. 세 실행 모두 `run_readiness.passed=false`였지만 최종 `run_quality.grade`는
   green이었다. 이것은 제품 검증 성공과 executor 운영 부채가 같은 색으로
   묶이는 문제다.

이번 개선은 성공한 실행을 실패로 바꾸려는 작업이 아니다. `completion_audit`의
제품 검증 성공은 유지하면서, 나중에 inspection, resume, repair, 설계 회고를 할 때
운영 부채가 상태만 봐도 보이게 만든다.

## Goals

- Finished run의 `run_quality`가 제품 검증 성공과 운영 품질 부채를 분리해서
  표현한다.
- `completion_audit.passed=true`와 `run_quality.grade=yellow`가 정상적으로 공존할
  수 있음을 계약에 명시한다.
- `run_quality.open_followups`에 다음 신호를 자동 반영한다.
  - `agentlens_missing`
  - `missing_execution_worktree`
  - `readiness_fixable_issues`
  - `full_spec_fallback_present`
  - `delegation_policy_prevented_all_delegation`
- `inspect_runs.py`의 read-only 품질 계산과 finished state에 embedded된
  `run_quality`가 같은 분류 체계를 쓴다.
- Validator와 deterministic eval이 이 계약을 검증한다.

## Non-goals

- Subagent safety gate를 완화하지 않는다.
- `spawn_agent` 정책을 우회하지 않는다.
- `full_spec_fallback`이 있는 실행을 무조건 실패 처리하지 않는다.
- 기존 archived state를 자동으로 수정하지 않는다.
- AgentLens best-effort 이벤트를 hard blocker로 바꾸지 않는다.
- Worktree 삭제 자체를 금지하지 않는다. 삭제 여부가 품질 신호로 남게 만드는 것이
  이번 범위다.

## Reviewed Approaches

### A. Completion Audit를 더 엄격한 pass/fail로 바꾸기

`full_spec_fallback`, AgentLens 누락, worktree 누락이 있으면
`completion_audit.passed=false`로 처리한다.

장점:
- 부채가 절대 숨지 않는다.

단점:
- 제품 변경은 검증됐는데 executor 운영 증거만 부족한 실행을 실패로 오분류한다.
- 이미 "AgentLens는 best-effort"라는 CPE 계약과 충돌한다.

### B. Read-only Inspection에만 Warning 추가

`inspect_runs.py`가 최신 파일시스템 상태를 보고 warning을 계산하되, finished
state에는 반영하지 않는다.

장점:
- 기존 state compatibility가 가장 좋다.
- 구현 범위가 작다.

단점:
- state 파일만 공유되거나 worktree가 정리된 뒤에는 같은 품질 판단을 재현하기
  어렵다.
- 완료 당시 operator가 어떤 부채를 인정했는지 남지 않는다.

### C. Recommended: Run Quality Debt Surfacing

Finished state의 `run_quality`에 운영 부채 follow-up을 구조화해서 넣고,
`inspect_runs.py`는 같은 규칙으로 최신 관측을 재계산한다.

장점:
- 제품 검증 성공과 운영 품질 부채를 분리한다.
- 현재 CPE safety/validation 계약을 유지한다.
- 최근 3개 로그에서 반복된 문제를 작은 계약 변경으로 드러낸다.

단점:
- 점수/grade 계산 규칙을 문서와 eval에 함께 고정해야 한다.
- 기존 run_quality와 inspection output 간의 drift를 줄이는 테스트가 필요하다.

선택한 접근은 C다.

## Design

### 1. Quality Dimensions

`run_quality`는 다음 차원을 유지한다.

- `readiness`: run readiness summary와 issue counts
- `dispatch_consistency`: dispatch decision과 final task strategy 일치 여부
- `context_quality`: full-spec fallback, context budget, packet scope 품질
- `verification_quality`: completion audit, residual risk, command observation 품질

여기에 `operational_debt` summary를 추가한다.

필수 하위 신호:

- `agentlens_missing`: execution mode인데 `agentlens_orchestration_run`이 없다.
- `missing_execution_worktree`: `execution_worktree` 경로가 더 이상 존재하지 않는다.
- `readiness_fixable_issues`: `run_quality.readiness.fixable_issue_count > 0`.
- `full_spec_fallback_present`: `context_quality.full_spec_fallback_count > 0`.
- `delegation_policy_prevented_all_delegation`: `subagents_requested=true`, write-capable
  task가 있었고, 모든 dispatch decision이 명시적 위임 요청 부재나 spawn policy
  사유로 `local_fallback`이 됐다.

각 신호는 `run_quality.open_followups`에도 stable string으로 들어간다.

### 2. Grade Semantics

Grade는 제품 검증 성공과 독립된 운영 품질 요약이다.

- `green`: completion audit이 통과했고 열린 운영 follow-up이 없다.
- `yellow`: completion audit은 통과했지만 non-blocking follow-up이 하나 이상 있다.
- `red`: schema drift, blocking validation issue, failed completion audit, unreconciled
  dispatch block 같은 실행 신뢰 문제다.

`completion_audit.passed=true`와 `run_quality.grade=yellow`는 정상이다. 이 조합은
"구현 검증은 통과했지만 executor 운영 증거 또는 효율에 후속 조치가 있다"를 뜻한다.

### 3. Embedded State와 Inspection의 관계

Finished state finalization은 완료 당시의 `run_quality`를 embedded한다.
`inspect_runs.py`는 state를 수정하지 않고 최신 파일시스템 상태를 반영한
read-only `run_quality`를 계산한다.

두 값이 달라질 수 있는 대표 사례는 완료 후 worktree 삭제다. 이때 inspection은
`missing_execution_worktree`를 보고하고, embedded state는 완료 당시 worktree가
있었다면 해당 follow-up이 없을 수 있다. 이 차이는 허용하되, inspection output의
current quality에는 `observed_after_completion=true` provenance를 둔다.

### 4. Validator Contract

`validate_state.py`는 finished operational-quality state에 대해 다음을 검증한다.

- `run_quality.open_followups`는 list다.
- `run_quality.grade`는 `green|yellow|red`다.
- `completion_audit.passed=true`와 `run_quality.grade=yellow` 조합을 허용한다.
- `run_quality.context_quality.full_spec_fallback_count > 0`이면
  `open_followups`에 `full_spec_fallback_present`가 있어야 한다.
- `agentlens_orchestration_run`이 없는 execution-mode finished state는
  `open_followups`에 `agentlens_missing` 또는 명시적 best-effort unavailable
  사유를 남겨야 한다.

Validator는 `missing_execution_worktree`를 finished state의 hard error로 만들지
않는다. worktree 존재 여부는 시간이 지나며 바뀌므로 inspection이 최신 신호를
계산한다.

### 5. Inspection Contract

`inspect_runs.py --quality-report`는 다음을 출력한다.

- embedded `run_quality`가 있으면 보존한다.
- read-only observation으로 계산한 current quality를 함께 낸다.
- current quality가 embedded quality보다 더 나쁜 follow-up을 발견하면
  `open_followups`에 추가해서 보고한다.
- `--jsonl` 출력은 machine-readable JSONL만 stdout에 둔다.

### 6. Eval Coverage

새 deterministic fixtures를 추가한다.

1. `completion_passed_yellow_quality`: completion audit은 통과했지만
   `full_spec_fallback_present`와 `agentlens_missing` 때문에 grade가 yellow인
   finished state.
2. `inspection_missing_worktree`: embedded quality는 green이지만 inspection이
   missing worktree를 current follow-up으로 보고하는 state.
3. `all_local_due_to_spawn_policy`: delegate-ready task가 있었지만 explicit request
   policy 때문에 모든 task가 local fallback인 state.
4. `invalid_missing_followup`: `full_spec_fallback_count > 0`인데
   `open_followups`가 비어 있어 validator가 실패해야 하는 state.

## Acceptance Criteria

- 최근 3개 실행에서 관측된 반복 부채를 새 `run_quality` 분류로 모두 표현할 수
  있다.
- 제품 검증 성공을 실패로 오분류하지 않는다.
- `inspect_runs.py --jsonl --quality-report`는 stdout을 JSONL로 유지한다.
- Existing v2.22 operational-quality fixtures는 필요한 follow-up만 추가해 통과한다.
- 문서, validator, eval이 같은 stable follow-up string을 쓴다.

## Verification

- `python3 skills/kws-codex-plan-executor/evals/check_state_schema.py`
- `python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
- `python3 skills/kws-codex-plan-executor/evals/run.sh`
- `python3 -m py_compile skills/kws-codex-plan-executor/scripts/*.py skills/kws-codex-plan-executor/evals/*.py`
- `bash -n skills/kws-codex-plan-executor/evals/run.sh`
- `git diff --check`
