# CPE Execution Boundary And Context Optimization Design

작성일: 2026-07-05
상태: APPROVED DESIGN SPEC
대상 표면: `skills/kws-codex-plan-executor`, subagent run evidence, task packet context,
run quality inspection, deterministic evals

## Problem

최근 `kws-codex-plan-executor` 자체 개선 실행 3개를 분석했다.

- `2026-07-05-cpe-operational-quality-signal-20260705-143128`
- `cpe-operational-quality-umbrella-20260704-163729`
- `cpe-current-superpowers-plan-gate-20260703-070629`

세 실행 모두 `lifecycle_outcome=finished`였고
`completion_audit.passed=true`였다. `validate_state.py` 기준 state validation도
통과했다. 즉 문제는 product verification failure가 아니라 CPE 실행 품질과 비용
신호가 반복적으로 남는 것이다.

가장 중요한 증거는 네 가지다.

1. `2026-07-05-cpe-operational-quality-signal-20260705-143128`의 Task 4는
   `operator_override_repeated_subagent_cwd_drift` 때문에 local fallback으로
   처리됐다. 기록상 이전 subagent가 execution worktree가 아니라 source `main`에
   커밋했다. 이는 단순한 yellow debt가 아니라 delegation 격리 안전성 문제다.
2. 같은 실행에서 task 1-3은 `full_spec_fallback_present`였다. 각 task packet은
   약 14.4K chars의 full spec을 반복 포함했고, `run_readiness.json`과
   `plan_executability_audit.json` 모두 3개의 fixable issue를 보고했다.
3. 같은 실행에서 task 2는 동일 write scope에 accepted subagent run이 3개, task 3은
   2개 남았다. 모두 `review_status=accepted`라 최종 채택본과 반복 시도가 상태상
   구분되지 않는다.
4. 세 실행 모두 `agentlens_missing`으로 yellow 계열 operational signal을 남겼고,
   완료 후 일부 execution worktree가 삭제된 실행은 read-only inspection에서
   `missing_execution_worktree`가 추가 관찰된다. 이는 현재 실행 실패라기보다
   관측/retention 정보인데 report에서 실제 수정 debt와 섞여 보인다.

CPE는 이미 dedicated worktree, state validation, task packet JSON source of truth,
Graphify audit, prompt cache audit, completion audit을 갖고 있다. 이번 설계는 그 안전
장치를 약화하지 않고, 최근 로그에서 드러난 세 병목을 줄인다.

- Delegated worker가 실제 어디서 작업했는지 증명한다.
- Full-spec fallback과 task packet 중복 컨텍스트를 줄인다.
- 중복 subagent 시도와 completion 후 관측 정보를 더 명확히 분류한다.

## Goals

- Delegated subagent의 실제 working directory, git root, head, dirty state가
  `execution_worktree` 경계 안에 있었음을 parent accept 전에 증명한다.
- Worker가 source workspace나 `main` checkout을 수정한 경우, finished state에서
  accepted delegation으로 남지 않게 한다.
- 동일 task와 write scope에 대해 여러 accepted subagent run이 남는 상태를
  `attempt_group`과 final accepted run으로 정규화한다.
- Full-spec fallback이 발생하기 전에 더 강한 spec section suggestion을 제공한다.
- Full-spec fallback이 필요하더라도 task packet마다 전체 spec을 반복 저장하는 비용을
  줄인다.
- `run_quality`는 durable product verification과 current inspection observation을
  구분해 operator가 "무엇을 고칠 수 있는가"를 빠르게 판단하게 한다.
- 기존 CPE hard boundaries, Superpowers bridge, task contract, TDD gate,
  `check_run_diffs.py`, `validate_state.py`, Graphify/prompt-cache evidence를 유지한다.

## Non-goals

- `completion_audit.passed`의 의미를 바꾸지 않는다.
- `subagents=on` 기본값이나 active Codex spawn policy를 우회하지 않는다.
- Full-spec fallback을 전면 금지하지 않는다.
- AgentLens unavailable 상태를 release blocker로 만들지 않는다.
- Finished run의 오래된 `state.json`을 자동 rewrite하지 않는다.
- Worktree cleanup을 자동 삭제 정책으로 확대하지 않는다.
- Waygent TypeScript runtime이나 Lens event schema를 변경하지 않는다.
- `components/agentlens/` 같은 legacy Python AgentLens tree를 되살리지 않는다.

## Reviewed Approaches

### A. Recommended: Boundary Attestation Plus Context Optimizer

Subagent execution boundary evidence를 먼저 강화하고, task packet context를 줄이며,
run-quality display를 정리한다.

장점:

- 최근 3개 로그에서 가장 위험한 CWD drift 사례를 직접 막는다.
- Delegation을 더 많이 쓰더라도 source checkout 오염 가능성을 낮춘다.
- Full-spec fallback 비용과 readiness yellow debt를 줄인다.
- 현재 CPE 상태/검증 모델 위에 필드를 추가하는 방식이라 migration risk가 낮다.

단점:

- `subagent_runs` schema와 validator/eval surface가 늘어난다.
- Parent accept 단계가 더 엄격해져 일부 기존 worker 결과가 rejected/superseded로
  남을 수 있다.
- Spec mapping 개선은 plan/spec 작성 품질과 함께 가야 효과가 크다.

이 접근을 선택한다.

### B. Context Optimizer Only

`build_task_packet.py`, `audit_run_readiness.py`, `audit_plan_executability.py`만 고쳐
full-spec fallback을 줄인다.

장점:

- 구현 범위가 비교적 작다.
- Packet 크기와 yellow readiness debt가 빠르게 줄어든다.

단점:

- 7월 5일 CWD drift 같은 execution boundary 문제는 그대로 남는다.
- Delegation을 늘릴수록 source workspace 오염 위험이 다시 드러날 수 있다.

이 접근은 안전성 우선순위가 낮아 1순위로 두지 않는다.

### C. Reporting Cleanup Only

`agentlens_missing`, `missing_execution_worktree`, expected local fallback을
`green-with-info`로 더 명확히 분리한다.

장점:

- Operator report가 읽기 쉬워진다.
- Product verification과 environment info가 덜 섞인다.

단점:

- 실제 worker boundary와 packet context 비용을 줄이지 못한다.
- Report가 좋아졌을 뿐 실행 품질은 그대로일 수 있다.

이 접근은 A의 마지막 단계로 포함한다.

## Design

### Phase 1. Subagent Boundary Attestation

`subagent_runs[]`에 worker boundary evidence를 추가한다. 새 필드는 parent가 worker
결과를 `accepted`로 바꾸기 전에 채워야 한다.

예상 shape:

```json
{
  "id": "019f30c6-a100-7512-bd95-809a9deb2aa5",
  "owner_task": "task_1",
  "mode": "fork_context",
  "write_scope": ["skills/kws-codex-plan-executor/scripts/run_quality_debt.py"],
  "status": "completed",
  "review_status": "accepted",
  "boundary_attestation": {
    "schema_version": "1",
    "execution_worktree": "~/.codex/worktrees/<run_id>",
    "worker_cwd": "~/.codex/worktrees/<run_id>",
    "worker_git_root": "~/.codex/worktrees/<run_id>",
    "worker_head_before": "<sha>",
    "worker_head_after": "<sha>",
    "source_workspace": "/Users/kws/source/private/Archive",
    "source_workspace_head_before": "<sha>",
    "source_workspace_head_after": "<sha>",
    "execution_worktree_match": true,
    "source_workspace_unchanged": true,
    "dirty_scope_after": []
  }
}
```

Validation rules:

- `review_status=accepted` requires `boundary_attestation`.
- `boundary_attestation.execution_worktree_match` must be `true`.
- `worker_git_root` must equal the state `execution_worktree`, after redaction-safe path
  normalization.
- `source_workspace_unchanged` must be `true` unless an explicit
  `operator_boundary_override` explains why source workspace changed.
- `changed_files` must still match `write_scope`; existing write-scope validation remains
  mandatory.

Compatibility rule:

- Existing finished states without `boundary_attestation` remain readable.
- New states opt into strict validation through a schema/version marker such as
  `subagent_boundary_schema_version=1` or an implementation-version gate documented in
  `references/state-schema.md`.
- Once a run uses the new marker, every accepted delegated run in that state must carry
  boundary evidence.

Parent accept flow:

1. Worker returns summary and changed files.
2. Parent records worker boundary evidence.
3. Parent runs skill-local `scripts/check_run_diffs.py` against
   `execution_worktree`.
4. Parent checks source workspace did not receive unexpected commits or dirty files.
5. Parent accepts only if both diff scope and boundary evidence pass.

This directly prevents a repeat of the Task 4 override where previous workers polluted source
`main`.

### Phase 2. Attempt Lineage For Duplicate Subagents

Multiple workers may legitimately be retried or compared, but finished state must distinguish
attempts from the final accepted result.

New optional fields:

```json
{
  "attempt_group": "task_2:skills/kws-codex-plan-executor/scripts/preflight_dispatch.py",
  "attempt_index": 2,
  "supersedes": ["019f30d2-1f34-7f11-81af-07aac5cbb1e0"],
  "superseded_by": "019f30de-8944-7230-9dce-d5f16e9a8f0e",
  "accepted_as_final": true
}
```

Rules:

- Finished state may have multiple completed attempts for the same task/write scope, but only
  one can have `accepted_as_final=true`.
- Task `subagent_strategy.run_ids` should point only to final accepted runs.
- Superseded accepted attempts should either use a new documented
  `review_status=superseded` enum or keep the existing `review_status=rejected` value with
  `superseded_by`. The implementation plan must choose one path and update
  `validate_state.py`, docs, and eval fixtures together.
- `run_quality.dispatch_consistency` reports duplicate final attempts as actionable debt.

This keeps retry history inspectable without making the state look as if three independent
accepted implementations were merged for the same task.

### Phase 3. Spec Mapping Optimizer

`build_task_packet.py` currently maps task to spec in this order:

1. Explicit task `spec_refs`.
2. `spec_manifest.task_to_sections`.
3. Heuristic file/id matching.
4. Full-spec fallback.

The optimizer keeps this order but strengthens step 3 and makes step 4 cheaper.

Changes:

- Score section headings, file path tokens, referenced script/test names, task title tokens,
  and acceptance command tokens together.
- When no section reaches the slice threshold, return the top candidate section ids with
  scores and reasons instead of an empty `suggested_spec_refs`.
- Generate a copy-pasteable plan patch suggestion:

```json
{
  "fallback_reason": "weak_heuristic_match",
  "suggested_spec_refs": ["S1.3", "S1.5"],
  "suggested_plan_patch": "spec_refs: [\"S1.3\", \"S1.5\"]",
  "next_action": "Add explicit spec_refs to task_2 using one of: S1.3, S1.5"
}
```

Packet-size optimization:

- Full-spec fallback remains available, but `context_components` marks the full spec as
  reducible and stores a bounded excerpt plus source hash when the packet is for
  readiness/dispatch analysis.
- Execution/handoff modes that truly need full spec can still materialize it from
  `spec.source_path` and `sha256`.
- Human-readable task packet views show fallback reason, candidate refs, and next action
  without dumping the full spec body.

Acceptance target:

- A plan/spec pair like `2026-07-05-cpe-operational-quality-signal` should produce non-empty
  `suggested_spec_refs` for task 1-3 instead of generic "Add or correct section ids" guidance.
- Repeated 14K-char full-spec payloads should shrink in readiness/dispatch artifacts.

### Phase 4. Run Quality Observation Split

Durable `state.json` should keep the state-intrinsic result. Read-only inspection may add
current observations without implying the original run was lower quality at completion time.

Shape:

```json
{
  "run_quality": {
    "grade": "yellow",
    "open_followups": ["agentlens_missing"],
    "inspection_observations": {
      "schema_version": "1",
      "observed_at": "2026-07-05T16:00:00Z",
      "missing_execution_worktree": true,
      "observed_after_completion": true,
      "display_class": "green-with-info"
    }
  }
}
```

Rules:

- `missing_execution_worktree` after a finished run is informational unless the run is being
  resumed or repaired.
- `agentlens_missing` stays informational when `agentlens_status.status=agentlens_unavailable`.
- `agentlens_emit_failed`, schema drift, unresolved dispatch mismatch, and duplicate final
  subagent attempts remain actionable.
- `analyze_recent_runs.py` should aggregate durable followups and current observations
  separately.

This makes reports clearer without weakening completion gates.

## Data Flow

```text
plan/spec
  -> parse_plan.py
  -> build_spec_manifest.py
  -> build_task_packet.py
      -> spec mapping optimizer
      -> task packet JSON and markdown view
  -> audit_run_readiness.py
  -> audit_plan_executability.py
  -> preflight_dispatch.py
  -> worker task packet
      -> worker boundary evidence
      -> parent diff and source-workspace check
  -> subagent_runs attempt lineage
  -> reconcile_state.py
  -> validate_state.py
  -> inspect_runs.py / analyze_recent_runs.py
```

State remains authoritative. Markdown task views, recent-run reports, and inspection
observations remain derived evidence.

## Error Handling

- Missing boundary evidence on an accepted subagent run is a validation error for new schema
  versions.
- Boundary mismatch blocks parent acceptance and records `subagent_strategy.mode=local_fallback`
  or rejected worker result.
- Source workspace commit or dirty drift blocks acceptance unless an explicit
  `operator_boundary_override` records files, reason, and verification.
- Full-spec fallback with no candidate refs remains yellow actionable debt.
- Multiple final accepted attempts for one task/write scope is actionable dispatch consistency
  debt.
- Inspection-only missing worktree after finished state is not a release blocker.

## Testing

Focused deterministic coverage from `skills/kws-codex-plan-executor`:

- `evals/check_state_schema.py`
  - accepted subagent without boundary evidence fails.
  - boundary evidence outside execution worktree fails.
  - source workspace drift without override fails.
  - exactly one final accepted attempt per task/write scope passes.
- `evals/check_preflight_dispatch.py`
  - delegation decision remains unchanged; boundary attestation is parent-accept evidence, not
    a pre-dispatch shortcut.
- `evals/check_task_packet.py`
  - weak heuristic fallback emits non-empty candidate refs when sections have partial matches.
  - readiness/dispatch packet context avoids repeated full-spec body where safe.
- `evals/check_run_readiness.py`
  - full-spec fallback issue includes `suggested_plan_patch` and deterministic `next_action`.
- `evals/check_operational_run_quality.py`
  - duplicate final accepted attempts are actionable.
  - finished missing worktree is informational when observed after completion.
- `evals/check_recent_run_rubric.py`
  - durable followups and inspection observations aggregate separately.

Full CPE verification bundle:

```bash
cd skills/kws-codex-plan-executor
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 scripts/audit_superpowers_compatibility.py \
  --superpowers-root /Users/kws/.codex/skills \
  --skill-root /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
cd /Users/kws/source/private/Archive
bun run check
git diff --check
```

Graphify evidence remains required after code or meaningful documentation-structure changes.

## Rollout

1. Add eval fixtures for boundary attestation and attempt lineage before implementation.
2. Add schema and validator support for optional fields while preserving compatibility with
   existing finished states.
3. Tighten accepted-run validation for new schema states.
4. Improve spec mapping suggestions and packet-size behavior.
5. Update docs: `SKILL.md`, `references/subagent-run-store.md`,
   `references/pre-dispatch-pipeline.md`, `references/state-schema.md`,
   `docs/state-and-logging.md`, `docs/evals-and-verification.md`,
   `docs/risks-limitations-deferrals.md`.
6. Run focused evals, full CPE evals, Graphify freshness check, and repo-level checks.

## Acceptance Criteria

- A delegated worker result cannot be accepted without boundary evidence proving it operated in
  the execution worktree.
- A worker that changes source workspace or `main` cannot be recorded as accepted without an
  explicit operator override.
- A finished run cannot present multiple final accepted subagent runs for the same task/write
  scope.
- Full-spec fallback reports candidate refs and a concrete plan patch suggestion when any
  plausible section candidates exist.
- Recent-run reports distinguish actionable executor debt from informational observation.
- Existing successful states remain readable, and new strictness applies through schema-aware
  validation/eval fixtures.
- The final implementation keeps CPE's dedicated worktree boundary, task packet JSON authority,
  completion audit, Graphify audit, prompt cache audit, and state validation intact.
