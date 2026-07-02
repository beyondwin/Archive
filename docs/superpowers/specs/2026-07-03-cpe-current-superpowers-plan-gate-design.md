# CPE Current Superpowers Plan Gate Design

작성일: 2026-07-03
상태: APPROVED DESIGN SPEC
대상 표면: `skills/kws-codex-plan-executor`

## Goal

`kws-codex-plan-executor`가 현재 설치된 Superpowers 계획/실행 계약을 더 엄격하고
정확하게 활용하도록 CPE 내부의 plan audit 계층을 개선한다.

Superpowers 스킬은 계속 업데이트되는 외부 라이브러리처럼 취급한다. CPE는
Superpowers 스킬 파일을 읽고 호환성을 검증할 수는 있지만, 이번 작업에서
`/Users/kws/.codex/skills` 아래 Superpowers 스킬을 수정하지 않는다.

## Evidence

검토 중 다음 명령과 표본 검증을 수행했다.

- `./evals/run.sh`: 통과
- `python3 scripts/audit_superpowers_compatibility.py --superpowers-root /Users/kws/.codex/skills --skill-root /Users/kws/source/private/Archive/skills/kws-codex-plan-executor`: 통과, `thin_stateful_bridge` 추천
- `python3 -m py_compile scripts/*.py evals/*.py`: 통과
- `git diff --check`: 통과
- `docs/superpowers/plans/*.md` 43개 전수 감사:
  - 41개 parse OK
  - 2개 parse fail
  - 31개 green
  - 1개 yellow
  - 9개 red

전수 감사에서 실제 결함이 재현됐다. 일부 non-docs task는
`acceptance_command_missing` 때문에 `block`이지만, `subagent_reason`이
`adaptive_policy_local_fast_path_small_scope`로 남았다. CPE는 실행을 차단하면서도
사용자에게 잘못된 local-fast-path 사유를 보여줄 수 있다.

또한 일부 과거 계획은 현재 Superpowers `writing-plans` 헤더나 CPE가 요구하는
task-level `Files` 계약을 만족하지 않는다. 이 작업은 그런 레거시 계획을 자동
지원하지 않는다.

## Non-Goals

- Superpowers `brainstorming`, `writing-plans`, `subagent-driven-development`,
  `verification-before-completion` 스킬을 수정하지 않는다.
- 레거시 plan 문서를 자동 정규화하거나 실행 가능하게 보정하지 않는다.
- missing `Files` block, 오래된 header, 파서 밖 task 구조를 best-effort로 추론하지
  않는다.
- CPE가 Superpowers 구현/리뷰 루프를 복제하지 않는다.
- 기존 worktree isolation, task contract, TDD, completion audit, state validation
  안전 게이트를 낮추지 않는다.

## Design

### 1. CPE-Only Compatibility Gate

CPE 내부에 현재 Superpowers plan gate를 둔다. 이 계층은 plan을 고치는 계층이
아니라, 실행 전 판정 계층이다.

입력:

- `scripts/parse_plan.py`가 만든 parsed plan JSON
- parsed plan JSON의 `plan` 경로에서 읽은 raw plan text
- optional task packet directory
- repo root
- 현재 설치된 Superpowers compatibility audit 결과

출력:

- 기존 `grade`, `passed`, `summary`, `tasks`
- task별 `subagent_fit`
- task별 `subagent_reason`
- task별 `blocking_issues`, `fixable_issues`
- 새 plan support classification

### 2. Plan Support Classification

`scripts/audit_plan_executability.py`는 각 task 또는 plan에 대해 다음 상태를
구분한다.

- `current_superpowers_compatible`: 현재 Superpowers/CPE 실행 계약을 만족한다.
- `cpe_fixable_metadata`: comma-joined write scope처럼 CPE가 안전한 suggestion을
  제공할 수 있는 경미한 metadata 문제다.
- `operator_review_required`: lockfile, security, infra, migration 등 위험 신호가
  있어 사람 검토가 필요하다.
- `blocked_unsupported_plan_shape`: 현재 Superpowers/CPE 실행 계약 밖의 계획이다.

`blocked_unsupported_plan_shape`는 자동 보정하지 않는다. CPE는 실행 전에 멈추고,
현재 Superpowers `writing-plans`로 plan을 다시 만들거나 명시적 `Files` block과
acceptance command를 추가하라고 안내한다.

`parse_plan.py`가 execution mode에서 plan을 파싱하기 전에 실패하는 경우도 같은
정책으로 취급한다. audit script가 invalid parsed JSON을 추론하려고 하지 않는다.
호출 계층은 parse failure를 `blocked_unsupported_plan_shape`로 보고하고 편집 전에
멈춘다.

### 3. Block Reason Priority

`subagent_fit == "block"`이면 `subagent_reason`은 반드시 실제 blocker에서 온다.
local fast path value-gate reason이 blocker를 덮거나 유지되면 안 된다.

우선순위는 다음과 같다.

1. `blocked_unsupported_plan_shape`
2. `acceptance_command_missing`
3. `files_missing`
4. `allowed_write_globs_empty`
5. `write_scope_too_broad`
6. `risk_marker_requires_operator_review`
7. 기타 deterministic blocking issue

Risky path는 레거시/unsupported가 아니다. `operator_review_required` 또는
`risk_marker_requires_operator_review`로 분류한다.

### 4. Error Handling

에러 처리는 자동 복구보다 정확한 차단을 우선한다.

- 최신 header 또는 실행 계약이 없으면 `blocked_unsupported_plan_shape`.
- task에 `Files` block이나 `yaml waygent-task.file_claims`가 없으면 실행 전 차단.
- non-docs task에 acceptance command가 없으면 `acceptance_command_missing` red/block.
- docs-only task에 acceptance command가 없으면 yellow/fixable.
- lockfile/security/infra/migration path는 operator review required.
- malformed write scope는 yellow/fixable suggestion을 내되, CPE가 자동으로 write
  scope를 바꾸지 않는다.

사용자 메시지는 짧고 행동 가능해야 한다.

```text
Plan blocked: unsupported current Superpowers/CPE plan shape.
Reason: task_7 has no Files block.
Next: regenerate the plan with current Superpowers writing-plans, or add an explicit Files block and acceptance command.
```

### 5. Documentation Contract

문서에는 다음 계약을 반영한다.

- Superpowers는 외부 계약이며 CPE가 수정하지 않는다.
- CPE는 current Superpowers-compatible plan만 실행한다.
- 레거시 plan 자동 지원은 하지 않는다.
- plan audit가 red/block이면 task contract와 파일 수정 전에 멈춘다.
- operator review required는 unsupported와 구분한다.

영향 파일 후보:

- `skills/kws-codex-plan-executor/SKILL.md`
- `skills/kws-codex-plan-executor/README.md`
- `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- `skills/kws-codex-plan-executor/HISTORY.md`
- `skills/kws-codex-plan-executor/references/execution-cycle.md`
- `skills/kws-codex-plan-executor/docs/user-guide.ko.md`
- `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
- `skills/kws-codex-plan-executor/docs/verification-log.md`

## Eval Coverage

Add deterministic CPE eval coverage before behavior changes.

Required cases:

1. `block_reason_prioritizes_acceptance_missing`: non-docs task with missing
   acceptance returns `subagent_fit=block` and
   `subagent_reason=acceptance_command_missing`.
2. `unsupported_plan_shape_missing_required_header`: plan without current
   Superpowers `REQUIRED SUB-SKILL` header is classified as
   `blocked_unsupported_plan_shape`.
3. `unsupported_plan_shape_missing_files_block`: task without `Files` or
   `waygent-task.file_claims` is unsupported and blocked before edits.
4. `risk_marker_operator_review_not_unsupported`: lockfile/security/infra paths
   are classified as operator review required, not legacy unsupported.
5. `docs_only_missing_acceptance_stays_fixable`: docs-only missing acceptance
   stays yellow/fixable.

`check_skill_contract.py` should assert the durable contract strings:

- CPE does not modify external Superpowers skills.
- Legacy plan auto-support is not provided.
- Unsupported current plan shape blocks before task contracts or edits.
- Block reason must come from a real blocking issue.

## Verification

Implementation is complete when these commands pass:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_plan_executability_audit.py
python3 evals/check_skill_contract.py --skill SKILL.md
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
cd /Users/kws/source/private/Archive
git diff --check
```

Optional supporting evidence:

```bash
python3 skills/kws-codex-plan-executor/scripts/audit_superpowers_compatibility.py \
  --superpowers-root /Users/kws/.codex/skills \
  --skill-root /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
```

After code or meaningful documentation-structure changes, refresh Graphify per
repo instructions and record the result in CPE verification evidence.
