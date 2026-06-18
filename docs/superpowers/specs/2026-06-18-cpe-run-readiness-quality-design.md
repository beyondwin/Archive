# CPE Run Readiness and Quality Audit

작성일: 2026-06-18
상태: APPROVED DESIGN SPEC
대상 표면: `skills/kws-codex-plan-executor`, execution state, task packets, pre-dispatch evidence, run quality audit

## 1. 배경

최근 `kws-codex-plan-executor` 실행 로그 2개를 분석했다.

- `2026-06-18-readmates-session-closing-flywheel-20260618-203859`
- `2026-06-18-readmates-member-record-reflection-loop-v2-20260618-172700`

두 실행 모두 최종 `lifecycle_outcome`은 `finished`였고,
`scripts/validate_state.py`도 `state ok`를 반환했다. 최종 검증 증거도 충분했다.
따라서 이번 개선은 실패한 실행을 복구하는 작업이 아니라, 성공한 실행의
사전 품질과 로그 설명력을 높이는 작업이다.

반복 증상은 세 가지다.

1. `acceptance_command_missing`이 pre-dispatch 단계에서 반복된다.
   첫 실행은 8개 task 중 6개가 이 사유로 local fallback을 기록했고,
   두 번째 실행은 dispatch decision 4개 전부가 이 사유를 포함했다.
   그런데 두 번째 실행의 최종 task state에는 task별 acceptance command가
   수동으로 채워져 있었다. packet 생성 시점의 acceptance 정보와 최종 state가
   어긋난 것이다.
2. `dispatch_decisions`와 최종 `tasks[task_id].subagent_strategy`가 불일치한다.
   두 번째 실행은 dispatch 로그에는 `acceptance_command_missing` 또는
   `write_scope_outside_allowed`가 남아 있지만, 최종 task strategy는
   `adaptive_policy_local_fast_path_*` reason으로 바뀌었다. 현재 validator는
   이 차이를 통과시킨다.
3. write scope가 delegation을 불필요하게 막는다. 한 task는 comma-joined
   glob 문자열처럼 기록되어 `write_scope_outside_allowed`가 났고, 다른 task는
   실제 task files보다 넓은 검증 파일을 건드리며 allowed scope 밖으로 나갔다.

이 설계의 핵심은 안전장치를 줄이는 것이 아니다. 기존 adaptive dispatch의
safety gate와 value gate는 유지하면서, 실행 전에 fixable metadata 결함을
드러내고 완료 상태에는 실제 판단과 증거가 맞물리도록 만든다.

## 2. 목표

성공 기준은 "더 많은 작업을 subagent로 보낸다"가 아니다. 실행 전에는
delegation 가능성을 정확히 판단하고, 실행 후에는 왜 local fallback 또는
delegation이 선택되었는지 상태만 봐도 설명되어야 한다.

구체 목표:

- task packet 생성 직후, 모든 task의 dispatch readiness를 dry-run으로 평가한다.
- acceptance command 누락, write scope mismatch, full-spec fallback 과다를
  edits 전에 fixable issue로 노출한다.
- 최종 state에서 `dispatch_decisions[task_id]`와
  `tasks[task_id].subagent_strategy`가 불일치하면 validator가 잡는다.
- 의도적인 strategy override는 별도 evidence field를 요구한다.
- `run_quality`가 단순 pass/fail이 아니라 성공한 실행의 효율 손실과 증거 품질을
  요약한다.
- 기존 `state ok` 실행을 깨지 않도록 migration/compatibility는 명확히 둔다.

## 3. Non-goals

- subagent-first 정책을 강제로 더 공격적으로 바꾸지 않는다.
- safety gate 실패를 자동으로 무시하지 않는다.
- dirty overlap, risky lockfile, broad write scope 차단을 완화하지 않는다.
- plan writer 전체를 새 포맷으로 갈아엎지 않는다.
- ReadMates 실행 결과 자체를 수정하지 않는다.
- Waygent runtime, Lens storage, provider adapter 동작을 변경하지 않는다.

## 4. 검토한 접근

### A. Pre-dispatch Readiness Gate

task packet을 만든 직후 모든 task에 대해 `preflight_dispatch.py`를 dry-run으로
돌리고, fixable metadata issue를 한 번에 요약한다. 일정 기준을 넘으면
TASK EXECUTION CONTRACT와 edits 전에 멈춘다.

장점:
- 최근 로그의 반복 원인인 missing acceptance, write scope mismatch,
  full-spec fallback을 가장 이른 시점에 잡는다.
- subagent delegation이 실제로 가능한 작업을 local fallback으로 접는 비율을
  줄인다.
- 기존 safety gate를 유지한다.

단점:
- 실행 준비 단계가 한 번 더 생긴다.
- 기존 plan이 acceptance command를 코드펜스로 잘 드러내지 않으면 초기에
  blocker처럼 보일 수 있다.

### B. Plan/Spec 작성 규칙 강화

plan parser와 plan template을 강화해서 task별 acceptance command와 spec refs가
항상 명시되도록 한다.

장점:
- 원인을 upstream에서 줄인다.
- packet 품질이 전반적으로 좋아진다.

단점:
- 과거 plan과 hand-written plan에 대한 compatibility 처리가 필요하다.
- readiness 결과 없이 format만 강화하면 실제 runtime drift는 계속 남을 수 있다.

### C. Completion-only Run Quality Report

완료 후 `run_quality`에 warning을 남기고, validator는 기존처럼 통과시킨다.

장점:
- 구현 범위가 작다.
- 기존 실행 state와 충돌이 적다.

단점:
- 문제를 edits 전에 막지 못한다.
- 운영자가 최종 리포트를 읽기 전까지 비효율이 반복된다.

선택한 접근은 A를 중심으로 하고, B와 C의 작은 부분을 포함한다.
즉, pre-dispatch readiness gate를 추가하고, 그 결과를 `run_quality`와 validator가
소비하게 만든다.

## 5. 설계 개요

새 흐름은 다음과 같다.

```text
parse plan
  -> build task packets
  -> run readiness audit for all task packets
  -> block or continue
  -> per-task TASK EXECUTION CONTRACT
  -> dispatch decision
  -> local or delegated execution
  -> post-task state update
  -> final consistency validation
  -> run_quality summary
```

readiness audit는 실행 권한을 갖는 단계가 아니다. 파일을 수정하지 않고 현재
packet과 state를 읽어 "이대로 실행하면 subagent path가 왜 막히는지"를 보여준다.

## 6. 구성요소

### 6.1 `scripts/audit_run_readiness.py`

새 스크립트를 추가한다.

입력:

- `--state <state.json>`
- `--task-packet-dir <dir>`
- `--repo-root <worktree>`
- `--output <run_dir>/run_readiness.json`
- `--requested-subagents on|auto|off`
- `--requested-source default|explicit|natural_language|resume_state`
- `--spawn-policy available|unavailable|explicit-request-required|unknown`
- `--explicit-delegation-requested true|false`

동작:

- task packet directory의 packet을 task id 순서로 읽는다.
- 각 packet의 `files`, `write_policy.allowed_write_globs`,
  `acceptance.command`, `spec.fallback_used`, `context_budget`,
  `depends_on`을 분석한다.
- `preflight_dispatch.py`와 같은 safety/value 용어를 사용해 issue를 분류한다.
- write scope는 기본적으로 packet files를 사용하되, comma-joined glob 같은
  명백한 formatting error는 별도 issue로 잡는다.
- 결과는 `run_readiness` JSON으로 저장한다.

출력 예시:

```json
{
  "schema_version": "1",
  "passed": false,
  "summary": {
    "task_count": 4,
    "delegate_ready_count": 0,
    "local_fast_path_count": 2,
    "fixable_issue_count": 4,
    "blocking_issue_count": 0
  },
  "issues": [
    {
      "task_id": "task_1",
      "severity": "fixable",
      "kind": "acceptance_command_missing",
      "message": "Task packet has no acceptance command before dispatch."
    }
  ]
}
```

### 6.2 `run_quality`

`run_quality`는 read-only inspection과 finished state 모두에서 쓸 수 있는
요약이다.

필드:

- `score`: 0부터 100 사이의 정수
- `grade`: `green`, `yellow`, `red`
- `readiness`: readiness audit summary
- `dispatch_consistency`: dispatch/state consistency summary
- `context_quality`: full-spec fallback, oversize packet, missing spec refs summary
- `verification_quality`: completion audit와 command observations summary
- `recommendations`: 다음 run에서 고칠 수 있는 짧은 액션 목록

완료 상태에서 `completion_audit.passed=true`와 `run_quality.grade=yellow`는 공존할
수 있다. 이것은 "제품 변경 검증은 통과했지만 executor 운영 품질 개선 여지가 있다"는
의미다.

### 6.3 Dispatch/Strategy Consistency Check

`validate_state.py`에 finished-state consistency check를 추가한다.

규칙:

- 각 completed write-capable task는 `subagent_strategy`를 가져야 한다.
- 같은 task id의 latest `dispatch_decisions`가 있으면, 최종
  `subagent_strategy.mode`와 reason은 dispatch result와 일치해야 한다.
- 다르면 task에 `subagent_strategy_override`가 있어야 한다.
- override에는 다음 필드가 필요하다.
  - `from_reason`
  - `to_reason`
  - `changed_at`
  - `evidence`
  - `operator_decision`
- override 없이 불일치하면 finished state validation은 실패한다.

이 규칙은 두 번째 최근 실행에서 보인 "dispatch는 acceptance missing인데 최종 task는
adaptive local fast path"인 상태를 앞으로 잡는다.

### 6.4 Acceptance Extraction Improvement

`parse_plan.py`는 현재 task body의 첫 command fence를 acceptance command로
사용한다. 최근 plan들은 단계별 "Run:" command가 있지만, parsed result에는
`acceptance_command=null`이 많았다. 이 설계에서는 parser를 대폭 바꾸지 않고
작게 확장한다.

추출 우선순위:

1. fenced `yaml waygent-task` 또는 `yaml agentrunway-task`의 `verify` /
   `acceptance` / `verification`
2. task body의 `Acceptance`, `Verification`, `Done when`, `검증`, `완료 기준`
   섹션 아래 command fence
3. task body의 마지막 `Run:` 또는 `실행:` 블록 아래 command fence
4. 기존 첫 command fence fallback

추출 결과에는 `acceptance.source`를 남긴다.

- `plan.yaml.verify`
- `plan.acceptance_section`
- `plan.last_run_block`
- `plan.command_fence_fallback`
- `missing`

### 6.5 Write Scope Normalization

readiness audit는 다음을 구분한다.

- `write_scope_format_invalid`: comma-joined glob처럼 하나의 문자열에 여러 scope가
  들어간 경우
- `write_scope_outside_allowed`: scope가 valid하지만 allowed glob 밖인 경우
- `write_scope_expansion_needed`: acceptance/e2e/doc update 파일이 task files 밖에
  있으나 plan body에서 명시적으로 요구된 경우

자동으로 allowed scope를 넓히지는 않는다. 대신 readiness output에 추천 patch
방향을 제공한다. 실제 scope 확장은 plan 작성 또는 executor operator가 명시적으로
반영해야 한다.

## 7. Error Handling

- readiness audit 스크립트 자체가 packet을 읽지 못하면 `blocking` issue로 기록하고
  non-zero로 종료한다.
- `preflight_dispatch.py`가 개별 task에서 block을 반환하면 readiness는 그 task를
  `blocking`으로 분류한다.
- fixable issue만 있는 경우 기본 정책은 계속 가능하지만, `subagents=on`이고
  explicit delegation request가 있는 실행에서는 edits 전에 operator에게 요약을
  보여준다.
- validator consistency failure는 finished lifecycle outcome을 막는다.
- 오래된 state에는 `run_quality`가 없어도 허용한다. 새 finished state에
  `run_quality`가 있으면 schema를 검증한다.

## 8. Testing

Focused evals:

- `check_preflight_dispatch.py`
  - acceptance command가 있는 packet은 `acceptance_command_missing`을 내지 않는다.
  - missing acceptance는 기존처럼 local fallback issue로 남는다.
  - comma-joined write scope는 format issue로 분리된다.
- 새 `check_run_readiness.py`
  - 최근 실행 패턴을 축소 fixture로 재현한다.
  - fixable issue count와 task별 issue 종류를 검증한다.
  - no-edit/read-only 동작을 검증한다.
- `check_state_schema.py`
  - dispatch/state reason mismatch without override는 실패한다.
  - override evidence가 있으면 통과한다.
  - `run_quality` grade와 score schema를 검증한다.
- `check_parse_plan.py` 또는 기존 parser eval 확장
  - `Verification` 섹션 command extraction
  - 마지막 `Run:` block extraction
  - 기존 command fence fallback compatibility

Full verification:

```bash
cd skills/kws-codex-plan-executor && ./evals/run.sh
git diff --check
```

Graphify:

- code 또는 meaningful documentation structure 변경 후에는 repo instruction에 따라
  `graphify update .`를 실행한다.
- `graphify-out/`이 ignored라면 completion evidence에 command-only update로 남긴다.

## 9. Compatibility and Migration

- 기존 state files는 `run_quality`가 없어도 valid하다.
- 새 finished state에서 `run_quality`를 기록할 때만 schema 검증을 적용한다.
- dispatch/strategy consistency는 latest dispatch decision이 있는 completed
  write-capable task에만 적용한다.
- 과거 실행처럼 수동으로 strategy를 고친 경우에는 새 `subagent_strategy_override`
  evidence가 필요하다.
- prompt/handoff mode에는 readiness artifact를 만들지 않는다. prompt export는
  실행 artifact를 만들지 않는다는 기존 계약을 유지한다.

## 10. Acceptance Criteria

- 최근 두 실행에서 발견된 세 패턴을 fixture로 재현하고 eval로 막는다.
  - acceptance command missing despite runnable task instructions
  - write scope formatting or allowed mismatch
  - dispatch decision and final strategy mismatch
- `scripts/audit_run_readiness.py`가 task packet directory를 읽고 deterministic JSON
  report를 생성한다.
- `validate_state.py`가 finished-state dispatch/strategy mismatch를 override 없이
  통과시키지 않는다.
- `run_quality`가 completion success와 별개로 executor 운영 품질을 yellow/green으로
  설명한다.
- `SKILL.md`, `references/pre-dispatch-pipeline.md`, `references/state-schema.md`,
  `references/execution-cycle.md`가 새 contract와 맞는다.
- focused evals와 `./evals/run.sh`가 통과한다.

## 11. Self-review Notes

- Placeholder 없음.
- 이 설계는 executor runtime 품질에만 집중하며 ReadMates 제품 코드를 변경하지 않는다.
- safety gate 완화가 아니라 readiness와 consistency 강화다.
- 구현 범위는 단일 implementation plan으로 충분하다.
