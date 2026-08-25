# D003 — 서브에이전트 state.json Read 폐지 vs Fallback 유지

**Status**: Draft → 채택 (Fallback 옵션 유지)
**Date**: 2026-05-27

## 결정

서브에이전트 프롬프트에서 **"Read state.json" 지시를 제거**하고, 오케스트레이터가 dispatch 시점에 필요한 슬라이스를 user message에 inject한다.

단, **completely 제거하지는 않는다** — fallback 절차를 프롬프트 맨 뒤에 명시한다:

```
## Context (pre-resolved by orchestrator)
<여기에 슬라이스 inject>

## Context fallback (only if the above section is missing or malformed)
If you don't find the pre-resolved context block above, this is an orchestrator
bug. Read `{orch_dir}/state.json` and resolve the active tree using:
- `state.plan_chain` exists → `state.plan_chain[state.active_plan]`
- ...
Report this fallback usage in your STATUS output so the orchestrator can correct it.
```

## 근거

### Inject-only (fallback 없음)의 문제

- 오케스트레이터의 slice 계산 로직에 버그가 생기면 서브에이전트가 컨텍스트 없이 동작 → 잘못된 결과 / hallucination 위험
- v2.13 plan_chain 도입 시 active_plan 해상도 실수가 실제로 있었음 (HISTORY 참조) → 같은 종류 회귀 가능성

### Fallback 유지의 비용

- 프롬프트 토큰 추가: ~15줄 (~200 tokens). 무시할 수준.
- 서브에이전트가 실제 fallback을 타면 그게 알람 — 오케스트레이터 버그 감지 메커니즘
- 정상 케이스에선 슬라이스가 있으므로 Read tool 호출 안 함 → 토큰 절감 효과는 그대로

### 슬라이스 inject 포맷

오케스트레이터가 active tree 판별 후 다음을 user message에 inject:

```yaml
## Context (pre-resolved by orchestrator)
active_plan_index: 0    # plan_chain[0] (또는 단일 plan일 때 "single")
deps_for_this_task: [3, 5]
task_summaries:
  task_3:
    for_next_tasks: |
      <task 3가 다음 태스크들에 전달한 요약>
  task_5:
    for_next_tasks: |
      <task 5가 다음 태스크들에 전달한 요약>
shared_files:
  src/foo.py: [task_3, task_5]   # 이 파일을 같은 plan 안에서 건드린 다른 태스크들
global_constraints: |
  <오케스트레이터가 plan-wide로 강제하는 제약 — 있다면>
```

YAML 선택 이유: jq output을 그대로 쓸 수 있어 오케스트레이터 구현이 단순. JSON도 OK.

### shared_files 정책

`global_constraints.shared_files` 가 큰 경우(예: 50태스크 plan에 모든 태스크가 shared 파일 가짐) inject 자체가 비대해질 수 있음. 정책:

- 이 태스크의 `files_to_touch` 와 교집합이 있는 항목만 inject (현재도 implementer-prompt.md는 그 케이스만 보라고 함)
- 교집합 0이면 `shared_files: {}` 로 비워서 전달

## 변경 대상 파일

### `references/implementer-prompt.md`

L52~57 의 "Read state.json" 블록 → "Context (pre-resolved)" 블록 + fallback으로 치환.

### `references/reviewer-prompt.md`

reviewer는 현재 state.json을 직접 읽으라는 지시가 없음 (`decisions_register` 만 inject 받음) → 추가 변경 없음.

### `references/verifier-prompt.md`

verifier는 headless `claude -p` 호출. 별도 평가 — 현 PoC 범위 밖.

### `SKILL.md` Phase 1 Step 1 (Implementer 디스패치)

오케스트레이터가 다음 단계를 dispatch 직전에 수행하도록 명시:

```
1.b Slice resolution (v2.19):
    - Compute active tree per <active> resolution rule.
    - Read <active>.task_summaries for deps_for_this_task (read-only).
    - Compute shared_files filtered to files in this task's Files block.
    - Format as YAML "## Context (pre-resolved by orchestrator)" block.
    - Inject into the Implementer prompt's user message at the position
      currently occupied by the "## Context from Previous Tasks" section.
```

## 측정

T6 ablation 시 비교:

```
시나리오                              | task_N 의 input tokens 평균
v2.18 (Read state.json)              | ?
T1.2 (slice inject + fallback)       | ?  ← 기대: -1k ~ -3k / task
```

라운드트립 latency 절감은 token과 별도로 wall-clock 측정.

## Fallback 사용 시 알람

서브에이전트가 fallback Read를 탔는지 감지하려면 STATUS 출력에 한 줄 추가:

```
CONTEXT_SOURCE: pre-resolved | fallback-read
```

오케스트레이터가 fallback-read 케이스 카운트 → AgentLens `kws-cme.orchestrator_bug` 이벤트로 emit. 1회만 발생해도 즉시 슬라이스 inject 로직 점검 필요.

## 관련 결정

- D001 — T1.1 phase-1 추출 시점에 SKILL.md Phase 1 Step 1 절차가 phase-1-task-cycle.md로 이동. T1.2 변경은 그 이동 전에 SKILL.md에 적용한 뒤, T1.1에서 함께 phase-1 파일로 옮기는 게 충돌 적음.
