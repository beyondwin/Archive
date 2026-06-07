# CPE 서브에이전트 품질 개선 구현 문서

작성일: 2026-06-07
대상: `skills/kws-codex-plan-executor`
설계 문서: `docs/superpowers/specs/2026-06-07-cpe-subagent-quality-improvement-design.md`
상태: 구현 완료

## 목적

이 문서는 `kws-codex-plan-executor`의 다음 고도화 작업을 실제 구현 가능한
단위로 쪼갠다. 핵심 목표는 세 가지다.

- 메인 에이전트가 전체 plan/spec/log를 계속 들고 있지 않아도 되게 한다.
- 작업 중 실패가 발생하면 정해진 정책으로 다음 행동을 고르게 한다.
- 실행이 끝난 뒤 state/log만 보고 스킬 개선 지점을 찾을 수 있게 한다.

외부 오케스트레이션 프레임워크를 의존성으로 추가하지 않는다. LangGraph,
Magentic-One, CrewAI, AutoGen, OpenHands, SWE-agent에서 확인한 패턴은 CPE의
기존 worktree/state/script 구조 위에 얇게 반영한다.

## 변경 프로토콜

런타임 동작을 바꾸는 각 task는 다음 순서를 따른다.

1. 먼저 deterministic eval을 추가하거나 갱신한다.
2. 관련 script, reference, docs, template, `SKILL.md`를 함께 갱신한다.
3. task 단위로 가장 작은 eval을 실행한다.
4. 전체 구현 완료 전 다음을 실행한다.

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
cd /Users/kws/source/private/Archive
git diff --check
```

이 문서 작성 시점에는 문서-only 제안이었고, 2026-06-07 구현 단계에서 아래
전체 eval과 hygiene 검증을 수행했다.

## 구현 완료 요약

구현 커밋: `9a4bb6b Improve CPE subagent quality controls`

로컬 병합 상태: `main`에 포함됨

주요 반영 사항:

- Phase 0-3: `Phase N` plan parsing, acceptance command extraction,
  component-level task packet budget, spec section signal/mapping evidence,
  decision filtering, unit manifest를 반영했다.
- Phase 4: `preflight_dispatch.py`가 packet quality, full spec fallback,
  missing acceptance, broad write scope, packet hash mismatch, dirty overlap을
  deterministic gate로 판단한다.
- Phase 5-7: structured blocker/failure state, headless result schema,
  recovery helper, resume inspection output을 갱신했다.
- Phase 8-9: append-only trajectory projection helper와 progress ledger helper를
  추가했다.
- Phase 10: README, architecture, Korean guide, state/logging, eval/reference
  문서를 실제 구현과 맞게 갱신했다.

리뷰 후 닫은 리스크:

- skill-relative path literal이 repo-root task path와 매칭되지 않던 문제를
  suffix/root-aware matching으로 수정했다.
- state의 packet hash drift를 preflight가 놓칠 수 있던 문제를
  `task_packet_hash_mismatch` block으로 수정했다.
- `inspect_runs.py` output에 recovery/blocker summary가 부족하던 문제를
  `last_completed_task`, `current_blocker_category`, `next_action_kind`,
  `handoff_ready`, `context_budget_status`로 보강했다.
- headless blocked/failed JSON schema가 blocker/failure decision을 충분히
  요구하지 않던 문제를 보강했다.

## 전체 단계

| Phase | 목적 | 핵심 산출물 |
| --- | --- | --- |
| 0 | baseline/fixture 준비 | 새 fixture와 현재 eval 기준선 |
| 1 | context component accounting | packet component budget |
| 2 | spec mapping/decision filtering | 더 작은 packet |
| 3 | acceptance/unit manifest | worker done 조건 명확화 |
| 4 | dispatch quality gate | 나쁜 packet delegation 차단 |
| 5 | structured failure state | blocked/failed 구분 |
| 6 | recovery policy helper | bounded retry/bootstrap/block |
| 7 | resume checkpoint/inspect | 재개와 active run 선택 개선 |
| 8 | trajectory projection | 사후 분석용 JSONL |
| 9 | progress ledger | 진행/정체/replan 판단 |
| 10 | 문서 통합 | 한글 guide와 architecture 갱신 |

## Phase 0: Baseline And Fixtures

목표: 현재 동작을 깨지 않고 새 정책을 검증할 fixture를 만든다.

수정 파일:

- `skills/kws-codex-plan-executor/evals/fixtures/*`
- `skills/kws-codex-plan-executor/evals/check_eval_harness.py`
- `skills/kws-codex-plan-executor/docs/verification-log.md`

작업:

1. 현재 deterministic baseline을 기록한다.
2. 다음 fixture를 추가한다.
   - 큰 spec + 명시 section refs
   - 큰 spec + section mapping 실패
   - acceptance command 누락
   - dirty overlap
   - allowed globs 밖 generated artifact
   - 같은 root signature command failure 반복
   - blocked headless result
   - unknown command observation이 있는 finished state
3. 처음에는 fixture만 추가하고 기존 eval을 깨지 않게 둔다.

검증:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
```

## Phase 1: Context Component Accounting

목표: task packet이 어떤 context를 얼마나 포함했는지 설명하게 한다.

수정 파일:

- `scripts/build_task_packet.py`
- `scripts/build_context_snapshot.py`
- `references/context-budget.md`
- `references/context-intelligence.md`
- `evals/check_task_packet.py`
- 새 파일 `evals/check_task_packet_context_components.py`

구현:

1. `build_task_packet.py`에 component helper를 추가한다.

```python
def component(role, source_path, source_ref, text, inclusion_reason, reducible):
    return {
        "role": role,
        "source_path": source_path,
        "source_ref": source_ref,
        "chars": len(text),
        "estimated_tokens": max(1, len(text) // 4),
        "sha256": sha256_text(text),
        "inclusion_reason": inclusion_reason,
        "reducible": reducible,
    }
```

2. 다음 component를 기록한다.
   - task summary/body
   - selected spec section
   - full spec fallback
   - filtered decisions
   - write policy
   - acceptance contract
3. `context_budget`에 `largest_component`와 `component_totals`를 추가한다.
4. `build_context_snapshot.py`의 Markdown section parsing을
   `build_spec_manifest.py` 수준으로 맞춘다. fenced code 내부 heading을
   section으로 오인하지 않아야 한다.

Eval:

- packet에 `context_components`가 존재한다.
- component hash가 안정적이다.
- full spec fallback은 `spec_full_fallback` 역할로 표시된다.
- 가장 큰 component가 budget에 표시된다.
- fenced heading을 잘못 section으로 잡지 않는다.

## Phase 2: Spec Mapping And Decision Filtering

목표: task packet에서 무관한 spec/decision context를 줄인다.

수정 파일:

- `scripts/build_spec_manifest.py`
- `scripts/build_task_packet.py`
- `scripts/update_decisions_register.py`
- `references/context-intelligence.md`
- `docs/decisions.md`
- `evals/check_spec_manifest.py`
- `evals/check_task_packet.py`
- `evals/check_decisions_register.py`

구현:

1. `spec_manifest.sections[*].signals`를 추가한다.

```json
{
  "signals": {
    "title_tokens": ["recovery", "policy"],
    "path_literals": ["scripts/validate_state.py"],
    "code_identifiers": ["current_blocker", "recovery_attempts"],
    "task_ids": ["task_3"]
  }
}
```

2. section scoring을 추가한다.
   - explicit `Spec Refs`: 최고 우선순위
   - path literal match: high
   - code identifier match: medium
   - title token match: low
   - no match: fallback policy
3. packet에 mapping evidence를 남긴다.

```json
{
  "spec": {
    "mapping": {
      "selected_section_ids": ["S4"],
      "candidate_scores": [
        {"section_id": "S4", "score": 9, "signals": ["path_literal"]}
      ],
      "mapping_reason": "Matched task file scripts/validate_state.py.",
      "requires_parent_mapping": false
    }
  }
}
```

4. `decisions_register`를 현재 task 기준으로 필터링한다.
5. packet에는 `included`, `omitted_count`, `selection_reason`을 남긴다.

Eval:

- explicit spec refs는 해당 section만 선택한다.
- unknown spec ref는 blocker다.
- path literal match가 약한 title match보다 우선한다.
- unrelated decision은 packet에 들어가지 않는다.
- superseded decision은 audit 필요가 없으면 제외된다.

## Phase 3: Acceptance And Unit Manifest

목표: worker가 검증 기준을 추론하지 않게 한다.

수정 파일:

- `scripts/parse_plan.py`
- `scripts/build_task_packet.py`
- `references/unit-context-manifest.md`
- `references/pre-dispatch-pipeline.md`
- `templates/fresh-session-prompt.txt`
- `evals/check_parse_plan.py`
- `evals/check_task_packet.py`

구현:

1. plan parsing 단계에서 acceptance command 또는 honest substitute 후보를
   보존한다.
2. packet `acceptance`를 채운다.

```json
{
  "acceptance": {
    "has_acceptance_criteria": true,
    "command": "python3 evals/check_recovery_policy.py",
    "source": "plan.acceptance",
    "honest_substitute_allowed": true
  }
}
```

3. packet에 `unit_manifest`를 포함한다.

```json
{
  "unit_manifest": {
    "unit_type": "execute-task",
    "context_mode": "focused",
    "required_skills": ["using-superpowers", "test-driven-development"],
    "tool_policy": "implementation",
    "allowed_write_globs": ["scripts/validate_state.py", "evals/check_state_schema.py"],
    "forbidden_write_globs": [".git/**", "graphify-out/**"],
    "artifact_policy": "inline-summary",
    "max_context_chars": 60000
  }
}
```

4. Worker prompt는 packet acceptance를 우선 사용하고, 없을 때만 honest
   substitute를 쓰도록 한다.

Eval:

- parser가 acceptance command를 보존한다.
- packet acceptance command가 null로 남지 않는다.
- write-capable unit manifest는 non-empty allowed globs를 가진다.
- acceptance가 없는 task는 missing 상태로 표시된다.

## Phase 4: Dispatch Quality Gate

목표: 품질이 낮은 packet을 서브에이전트에 넘기지 않는다.

수정 파일:

- `scripts/preflight_dispatch.py`
- `references/pre-dispatch-pipeline.md`
- `references/subagent-run-store.md`
- `scripts/validate_state.py`
- `evals/check_preflight_dispatch.py`

구현:

1. `preflight_dispatch.py`에 다음 gate를 추가한다.
   - `context_budget.status == "red"` -> `local_fallback` 또는 `block`
   - `spec.fallback_used == true`이고 packet이 green이 아님 -> `local_fallback`
   - medium/high risk write task인데 acceptance command 없음 -> `local_fallback`
   - write scope가 `**`, `.`, repo root처럼 너무 넓음 -> `block`
   - task packet hash가 state와 불일치 -> `block`
   - active subagent write scope overlap에 rationale 없음 -> `block`
2. 현재 dirty overlap은 계속 `block`으로 둔다.
3. 실패 prerequisite 이름을 표준화한다.

```text
packet_context_budget_red
full_spec_fallback_not_delegable
acceptance_command_missing
write_scope_too_broad
task_packet_hash_mismatch
active_subagent_overlap
dirty_overlap:<files>
```

4. `local_fallback`이면 task `subagent_strategy.reason`에 정확한 prerequisite을
   기록한다.

Eval:

- red packet은 delegate되지 않는다.
- full spec fallback은 위험 조건에서 delegate되지 않는다.
- missing acceptance는 local fallback이다.
- broad write scope는 block이다.
- dirty overlap은 기존처럼 block이다.

## Phase 5: Structured Failure Decision State

목표: `blocked`와 `failed`를 상태로 구분한다.

수정 파일:

- `references/state-schema.md`
- `references/command-observations.md`
- `scripts/validate_state.py`
- `templates/headless-output-schema.json`
- `references/headless-result-schema.md`
- `evals/check_state_schema.py`
- `evals/check_headless_result.py`

구현:

1. optional top-level fields를 추가한다.
   - `current_blocker`
   - `failure_decision`
   - `recovery_attempts`
   - `resume_checkpoint`
2. validation enum을 추가한다.

```python
VALID_BLOCKER_CATEGORIES = {
    "operator_input_required",
    "workspace_precondition",
    "plan_contract_gap",
    "diff_scope_gap",
    "execution_source_failure",
    "transient_tooling_or_resource",
    "state_integrity_drift",
    "subagent_coordination",
    "observability_degraded",
}
```

3. Finished validation:
   - blocking `current_blocker`가 남아 있으면 실패
   - unknown observation은 residual risk에 연결되어야 함
   - open recovery attempt가 있으면 실패
4. Non-success validation:
   - `blocked`는 recoverable blocker가 필요함
   - `failed`는 `failure_decision` 또는 non-recoverable blocker가 필요함
   - `handoff_reason`은 사람이 읽는 요약으로 유지하되 유일한 machine field가
     아니어야 함

Eval:

- `blocked`인데 `current_blocker`가 없으면 실패한다.
- `failed`인데 failure decision이 없으면 실패한다.
- `finished`인데 active blocker가 있으면 실패한다.
- unknown observation이 residual risk에 없으면 실패한다.
- headless failed JSON은 blocker와 next action을 포함한다.

## Phase 6: Recovery Policy Helper

목표: command observation을 bounded next action으로 바꾼다.

수정 파일:

- 새 파일 `scripts/classify_recovery.py`
- 새 파일 또는 확장 `scripts/record_command_observation.py`
- `references/command-observations.md`
- `references/execution-cycle.md`
- 새 파일 `evals/check_recovery_policy.py`

CLI:

```bash
python3 scripts/classify_recovery.py \
  --state "$STATE_PATH" \
  --task-id "$TASK_ID" \
  --observation "$RUN_DIR/observations/test-fail.json" \
  --output "$RUN_DIR/recovery-$TASK_ID.json"
```

출력 예시:

```json
{
  "decision": "retry",
  "category": "transient_tooling_or_resource",
  "subtype": "flaky_test",
  "root_signature": "bun-test:foo.test.ts:timeout",
  "retry_count": 1,
  "retry_budget": 2,
  "next_action_kind": "retry",
  "next_command": "bun test foo.test.ts"
}
```

정책:

- dependency bootstrap: 문서화된 bootstrap command를 1회만 허용
- timeout/flaky: bounded retry
- source failure: RED/GREEN fix loop
- permission/sandbox: block
- diff scope gap: block
- unknown: bounded investigation 후 residual risk 또는 fail

Eval:

- dependency bootstrap은 한 번만 선택된다.
- 같은 root signature는 retry budget을 소진하면 failed/block으로 간다.
- permission failure는 block이다.
- generated artifact outside scope는 block이다.
- source failure는 implementation loop로 남는다.

## Phase 7: Resume Checkpoint And Inspect Runs

목표: resume과 active run 선택을 쉽게 만든다.

수정 파일:

- `scripts/inspect_runs.py`
- `references/mode-contracts.md`
- `references/state-schema.md`
- `docs/state-and-logging.md`
- `evals/check_inspect_runs.py`

구현:

1. semantic boundary마다 `resume_checkpoint`를 갱신한다.
2. `inspect_runs.py` 출력에 다음을 추가한다.
   - `run_id`
   - `lifecycle_outcome`
   - `current_task`
   - `last_completed_task`
   - `current_blocker.category`
   - `next_action_kind`
   - `handoff_ready`
   - `context_budget.status`
   - `state_path`
3. `resume=latest`가 여러 active run을 만나면 이 정보를 보여주고 멈춘다.
4. inspect는 state를 mutate하지 않는다.

Eval:

- multiple active runs report가 blocker/next action을 포함한다.
- explicit state path resume은 계속 동작한다.
- invalid state는 명확한 error를 낸다.

## Phase 8: Trajectory Projection

목표: transcript 없이 실행 흐름을 분석할 수 있게 한다.

수정 파일:

- 새 파일 `scripts/append_trajectory_event.py`
- `references/event-journal.md`
- `references/learning-log.md`
- `docs/state-and-logging.md`
- `scripts/validate_state.py`
- 새 파일 `evals/check_trajectory_projection.py`

구현:

1. state에 `trajectory_path`를 추가한다.
2. append-only JSONL helper를 만든다.
3. event 필수 필드:
   - `schema_version`
   - `seq`
   - `event`
   - `at`
   - `task_id` when relevant
   - `state_ref`
   - `summary`
   - `evidence_refs`
   - redacted context budget metadata
4. raw full prompt는 기본 저장하지 않는다.
5. AgentLens event id가 있으면 연결하되, 로컬 trajectory도 독립적으로 유효해야
   한다.

Eval:

- JSONL이 valid하다.
- `seq`가 증가한다.
- required field가 있다.
- home path가 redacted된다.
- raw prompt field가 없다.

## Phase 9: Progress Ledger

목표: 진행, 정체, retry, block, replan 판단을 보이게 한다.

수정 파일:

- `references/state-schema.md`
- `references/execution-cycle.md`
- `scripts/validate_state.py`
- 새 파일 `scripts/update_progress_ledger.py`
- 새 파일 `evals/check_progress_ledger.py`

상태 예시:

```json
{
  "progress_ledger": {
    "task_2": {
      "goal_satisfied": false,
      "progress_made": true,
      "stall_count": 0,
      "last_progress_at": "2026-06-07T12:35:00Z",
      "next_action": "Run GREEN verification.",
      "needs_operator": false
    }
  }
}
```

업데이트 시점:

- packet build
- dispatch decision
- subagent completion
- verification failure
- recovery decision
- task completion

Replan 제한:

- independent not-started task 순서 변경 가능
- local fallback 선택 가능
- 더 좁은 verification 선택 가능
- file claim/acceptance 확장은 operator decision 없이는 불가

Eval:

- progress made는 stall count를 reset한다.
- 같은 root failure는 stall count를 증가시킨다.
- threshold를 넘으면 blocker 또는 failure decision이 생긴다.

## Phase 10: 문서 통합

목표: 구현된 동작을 사용자와 미래 에이전트가 바로 이해하게 한다.

수정 파일:

- `docs/user-guide.ko.md`
- `docs/how-it-works.md`
- `docs/state-and-logging.md`
- `docs/evals-and-verification.md`
- `docs/risks-limitations-deferrals.md`
- `ARCHITECTURE.md`
- `README.md`
- `SKILL.md`

작업:

1. 한글 user guide를 확장한다.
   - 실행 layout
   - task packet
   - subagent dispatch 조건
   - blocked/failed 차이
   - log inspection 방법
2. `ARCHITECTURE.md`에 context/recovery/trajectory 흐름도를 추가한다.
3. `README.md`에는 operator-facing summary만 둔다.
4. `SKILL.md`는 짧게 유지하고 상세는 references로 보낸다.
5. 새 scripts/evals 목록을 `docs/evals-and-verification.md`에 반영한다.

검증:

```bash
cd skills/kws-codex-plan-executor
rg 'current_blocker|recovery_attempts|trajectory|progress_ledger|context_components' SKILL.md README.md ARCHITECTURE.md docs references scripts evals
```

## 구현 시 서브에이전트 분할

| Workstream | 담당 | Write scope | 비고 |
| --- | --- | --- | --- |
| Context packet accounting | worker | `scripts/build_task_packet.py`, `evals/check_task_packet*.py`, `references/context-*.md` | Phase 0 이후 독립 가능 |
| Dispatch quality gate | worker | `scripts/preflight_dispatch.py`, `evals/check_preflight_dispatch.py`, `references/pre-dispatch-pipeline.md` | packet field에 의존 |
| State schema/validation | worker | `scripts/validate_state.py`, `references/state-schema.md`, `evals/check_state_schema.py` | enum 이름 조율 필요 |
| Recovery helper | worker | `scripts/classify_recovery.py`, `evals/check_recovery_policy.py`, `references/command-observations.md` | schema 이후 |
| Trajectory projection | worker | `scripts/append_trajectory_event.py`, `evals/check_trajectory_projection.py`, `docs/state-and-logging.md` | recovery와 병렬 가능 |
| Docs consolidation | main | `SKILL.md`, `README.md`, `ARCHITECTURE.md`, `docs/*.md` | 최종 일관성은 main이 소유 |

서브에이전트는 겹치는 write scope를 가져서는 안 된다. Parent는 모든 diff를
리뷰하고 관련 eval을 실행한 뒤 output을 accept해야 한다.

## 최종 검증

전체 구현이 끝나면 최소 다음을 실행한다.

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
cd /Users/kws/source/private/Archive
git diff --check
```

문서 구조나 스크립트 관계가 의미 있게 바뀌면 repository 규칙에 따라
Graphify도 갱신한다.

```bash
cd /Users/kws/source/private/Archive
graphify update .
```

`graphify-out/`이 tracked인지 ignored인지 확인한 뒤 commit 포함 여부를
결정한다.

2026-06-07 완료 시점 검증 결과:

- `./evals/run.sh` 통과
- `python3 -m py_compile scripts/*.py evals/*.py` 통과
- `bash -n evals/run.sh` 통과
- `git diff --check` 통과
- `graphify update .` 실행 후 tracked `graphify-out/` 갱신 포함
- `scripts/check_graphify_freshness.py --update-ran` 통과
- `scripts/reconcile_state.py --check` 통과
- `scripts/validate_state.py <run-state>` 통과
- 독립 코드 리뷰에서 남은 Critical/Important merge blocker 없음 확인

## 출시 결과

초기 계획은 세 묶음 출시였지만, 구현은 deterministic eval과 review gate를
통과한 단일 release commit으로 반영됐다. 이후 변경은 이 문서의 Phase 구분을
유지하되, 실제 동작 기준은 `skills/kws-codex-plan-executor`의 scripts,
references, evals를 우선한다. Phase 10 문서 통합도 같은 release commit에
포함됐다.

## 주요 리스크

- 필수 state field가 너무 많아지면 run state 작성이 brittle해질 수 있다.
  새 field는 optional로 시작하고 eval fixture를 충분히 만든 뒤 strict하게
  만든다.
- trajectory가 사실상 transcript dump가 되면 보안 리스크가 생긴다. raw prompt
  저장은 기본 금지한다.
- recovery policy는 보수적이어야 한다. plan scope, approval, sandbox 정책은
  executor가 자동으로 바꾸지 않는다.
- context reduction이 과하면 품질이 떨어질 수 있다. spec mapping evidence와
  fallback reason을 반드시 남긴다.
- helper script가 많아지면 유지보수가 어려워진다. 입력/출력이 좁은
  deterministic helper만 추가한다.
