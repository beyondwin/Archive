# 사용자 가이드

`kws-codex-plan-executor`는 구현 계획 파일을 받아 Codex에서 실행하거나,
새 세션에 붙여넣을 prompt/handoff 문서를 만드는 스킬입니다. 최신 CPE는
interactive 구현에서는 Superpowers 실행 루프를 우선 활용하고, CPE는
worktree, 상태, task packet, audit, resume, inspection 증거를 남기는
stateful bridge 역할을 합니다.

## 언제 쓰나

- 이미 승인된 구현 계획을 Codex에서 실행할 때
- 구현 세션을 새로 열기 위한 prompt나 handoff 문서를 만들 때
- 진행 중이거나 오래된 CPE 실행 상태를 inspection/resume 해야 할 때
- 실행 전 plan이 task packet, write scope, acceptance command 관점에서
  실제 실행 가능한지 확인해야 할 때

Waygent 실행 요청은 `skills/waygent/SKILL.md`가 우선입니다. CPE는 KWS
executor skill 자체의 계획 실행, prompt export, 상태 점검 표면입니다.

## 기본 실행

```text
/kws-codex-plan-executor plan=plans/example.md
```

기본값:

- `mode=interactive`
- `subagents=on`
- `headless_sandbox=workspace-write`
- `context_mode=auto`
- `context_budget=60000`
- `manifest_fallback=full_spec_on_blocker`

`plan=`은 실행 계획 경로입니다. 필요하면 `spec=`, `docs=`, `workspace=`를
함께 넘깁니다.

```text
/kws-codex-plan-executor plan=docs/superpowers/plans/feature.md spec=docs/superpowers/specs/feature.md docs=README.md,AGENTS.md
```

## 실행 모드

| 모드 | 용도 | 파일 수정 |
| --- | --- | --- |
| `interactive` | 현재 Codex 세션에서 구현 | 전용 worktree에서만 허용 |
| `headless` | headless runner나 eval 환경에서 구현 | sandbox 설정에 따름 |
| `prompt` | 새 세션용 prompt 생성 | 수정 없음 |
| `handoff` | 이어받기용 handoff prompt 생성 | 수정 없음 |

`prompt`와 `handoff`는 export-only입니다. worktree, state, context snapshot,
orchestrator artifact를 만들지 않습니다.

## Subagent 옵션

`subagents=on`이 기본값입니다. 이 값은 단순 허가가 아니라 adaptive
subagent-first 정책입니다. CPE는 task packet과 disjoint write scope가 준비된
write-capable task를 먼저 평가한 뒤 다음 중 하나를 선택합니다.

| 결과 | 의미 |
| --- | --- |
| `delegate` | task packet 기반으로 subagent에 맡길 수 있음 |
| `local_fallback` | 작고 낮은 위험이거나 정책상 spawning 가치가 낮아 로컬 실행 |
| `block` | dirty overlap, broad write scope, risky path, packet drift 같은 차단 사유 |

`subagents=auto`는 사용자가 subagent, delegation, parallel work를 명시한
경우에만 spawning을 허용하는 보수 모드입니다. `subagents=off`는 local-only
입니다.

`local_fallback`은 품질 게이트를 생략하지 않습니다. task contract,
unit manifest, RED/GREEN 증거, diff review, acceptance command,
reconciliation, state validation은 그대로 필요합니다.

## Superpowers Bridge

최신 Superpowers 스킬이 설치된 approved interactive 구현에서는 먼저
다음을 실행합니다.

```bash
python3 scripts/audit_superpowers_compatibility.py \
  --superpowers-root "$SUPERPOWERS_ROOT" \
  --skill-root "$CPE_SKILL_ROOT"
```

결과가 `thin_stateful_bridge`이면 구현/리뷰 루프는 Superpowers
`subagent-driven-development`를 우선 사용합니다. CPE는 다음 표면을 계속
소유합니다.

- `~/.codex/worktrees/<run_id>` 전용 worktree 경계
- `~/.codex/orchestrator/<run_id>/state.json`
- `context.json`, `spec_manifest.json`, `task_packets/`
- prompt/handoff/headless/resume/inspection
- run readiness, plan executability, Graphify, prompt cache audit
- completion audit와 state validation

Superpowers compatibility audit가 실패하면 CPE-owned fallback을 명시하거나
차단 사유를 남기고 중단합니다. 추측으로 compatibility를 통과 처리하지
않습니다.

## 실행 전 Readiness

Interactive/headless 실행은 task contract나 파일 수정 전에 두 가지 read-only
audit를 거칩니다.

1. `scripts/audit_run_readiness.py`
   - task packet 형식, write scope, acceptance command, packet budget을 확인합니다.
   - comma-joined write scope는 `suggested_write_scopes`와
     `normalized_write_globs`를 보고 수정합니다.

2. `scripts/audit_plan_executability.py`
   - parsed plan JSON과 task packet을 비교합니다.
   - `thin_stateful_bridge` 기준으로 task별 `delegate`, `local_fast_path`,
     `operator_review`, `block` 적합도를 요약합니다.
   - `files_missing`, `allowed_write_globs_empty`, `write_scope_too_broad`,
     risky path, lockfile 같은 차단 사유를 task contract 전에 잡습니다.

이 audit는 현재 Superpowers-compatible plan만 실행 대상으로 봅니다. Superpowers는
외부 계약이므로 CPE가 `/Users/kws/.codex/skills` 아래 스킬을 수정하지 않습니다.
오래된 header, 누락된 `Files` block, 파서 계약 밖 task 구조는
`blocked_unsupported_plan_shape`로 차단되며 legacy plan auto-support is not
provided. lockfile, security, infra, migration 같은 위험 신호는 legacy가 아니라
`operator_review_required`로 분리됩니다. `block` 결과의 `subagent_reason`은 항상
실제 blocking issue에서 와야 하며 local fast path reason으로 덮이지 않습니다.

짧은 readiness summary에는 route, task 수, delegate-ready 수,
local-fast-path 수, fixable issue 수, blocker 수가 들어갑니다. 세부 JSON은
`$RUN_DIR/plan_executability_audit.json`에 저장되고, state에는
`plan_executability_audit.grade`, `blocking_issue_count`,
`fixable_issue_count`가 기록됩니다. operator review로 blocker를 낮춘 경우에는
`raw_blocking_issue_count`, `raw_fixable_issue_count`,
`operator_reviewed_blocking_issues`, `operator_decision`도 함께 남겨 원본 audit와
effective count를 구분합니다. finished state는 red audit를 남길 수 없습니다.

## 상태와 파일 위치

실행 시 코드는 `~/.codex/worktrees/<run_id>`에, 상태와 로그는
`~/.codex/orchestrator/<run_id>`에 생성됩니다.

주요 inspection 파일:

- `state.json`: 실행의 권위 소스입니다.
- `context.json`: plan/spec/docs와 task packet index의 snapshot입니다.
- `spec_manifest.json`: spec section, mapping signal, fallback policy입니다.
- `task_packets/task_<N>.json`: task body, spec slice, filtered decisions,
  acceptance command, unit manifest, context component budget입니다.
- `run_readiness.json`: task packet 실행 준비 상태입니다.
- `plan_executability_audit.json`: plan/task packet 실행 가능성 audit입니다.
- `trajectory.jsonl`: transcript 없이 보는 compact 실행 흐름입니다.

`blocked`는 recoverable `current_blocker`가 있는 상태이고, `failed`는
`failure_decision` 또는 non-recoverable blocker가 필요한 상태입니다.
`recovery_attempts`는 같은 root signature의 retry/bootstrap 예산을 추적합니다.

## Run Quality 읽는 법

`run_quality.grade`는 구현 성공 여부가 아니라 운영 증거 품질입니다.
`completion_audit.passed=true`와 `run_quality.grade=yellow`는 동시에 성립할
수 있습니다. 이 경우 제품 검증은 통과했지만 executor 증거나 효율성 후속
작업이 남았다는 뜻입니다.

대표 follow-up:

| follow-up | 의미 |
| --- | --- |
| `agentlens_missing` | AgentLens CLI나 run id가 없어 replay evidence가 빠짐 |
| `missing_execution_worktree` | inspection 시점에 실행 worktree가 없음 |
| `readiness_fixable_issues` | run readiness의 수정 가능 이슈가 남음 |
| `plan_executability_fixable_issues` | plan executability audit의 yellow 이슈가 남음 |
| `full_spec_fallback_present` | task packet이 spec slice 대신 full spec fallback을 사용 |
| `delegation_policy_expected_local_fallback` | explicit request가 필요한 spawn policy 때문에 예상대로 local fallback |
| `delegation_policy_prevented_all_delegation` | 명시적 delegation 요청이 있었지만 모든 dispatch가 policy fallback |
| `delegation_policy_missing_dispatch_evidence` | finished write-capable task의 dispatch evidence가 없음 |

`completion_audit.residual_risk`는 문자열 또는 structured residual risk 객체를
담을 수 있습니다. 객체는 `owner`, `class`, `summary`, `blocks_release`를
포함하며, `blocks_release=true`인 항목은 passed finished completion 뒤에 숨길 수
없습니다.

정규화된 replay는 raw transcript 없이 상태를 비교할 때 사용합니다.

```bash
python3 scripts/normalize_cpe_run.py \
  --state "$RUN_DIR/state.json" \
  --output "$RUN_DIR/replay.json"
```

출력에는 run-quality grade, open followups, plan audit count, dispatch reason,
residual risk class, forbidden pattern 결과가 들어갑니다.

최근 실행을 확인하려면:

```bash
python3 scripts/inspect_runs.py \
  --codex-home ~/.codex \
  --all-plans \
  --recent 10 \
  --validate-state \
  --quality-report
```

JSONL로 다른 도구에 넘기려면 `--jsonl`을 추가합니다.

## 오래된 실행 복구

inspection은 read-only입니다. stale non-terminal run을 직접 고치려면 별도
repair flow를 사용합니다.

먼저 dry-run:

```bash
python3 scripts/repair_runs.py \
  --codex-home ~/.codex \
  --recent 20 \
  --stale-hours 24 \
  --output /tmp/cpe-repair-plan.json
```

적용은 의도적으로 좁습니다.

```bash
python3 scripts/repair_runs.py \
  --codex-home ~/.codex \
  --run-id <run_id> \
  --action mark-blocked-stale \
  --apply
```

이 작업은 선택한 stale non-terminal run 하나를 `blocked`로 표시할 뿐입니다.
worktree, run directory, finished state를 삭제하거나 임의로 고치지 않습니다.

## Graphify와 로컬 Skill 경로

로컬 skill 파일을 직접 읽어야 할 때는 현재 세션의 skill registry/root
mapping을 기준으로 경로를 해석합니다. `.system` 같은 특정 root를 하드코딩하지
않습니다.

repo가 Graphify 지침을 제공하면 `graphify-out/GRAPH_REPORT.md`의
`Built from commit`을 현재 HEAD와 비교합니다. 코드 변경이나 의미 있는 문서
구조 변경 후에는 `graphify update .`를 실행하고,
`scripts/check_graphify_freshness.py` 결과를 `graphify_audit`와
`completion_audit.verification_evidence`에 연결합니다.

## 검증 명령

skill 변경 후 기본 검증:

```bash
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 evals/check_operational_run_quality.py
python3 evals/check_cpe_replay.py
python3 evals/check_superpowers_compatibility.py
python3 evals/check_plan_executability_audit.py
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
git diff --check
```

Graphify가 있는 repo에서 코드나 문서 구조가 바뀌었으면:

```bash
graphify update .
python3 scripts/check_graphify_freshness.py \
  --repo-root "$REPO_ROOT" \
  --update-ran \
  --output /tmp/cpe-graphify-audit.json
```
