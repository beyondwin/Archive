# CPE Completion Quality Normalization Design

작성일: 2026-06-25
상태: APPROVED DESIGN SPEC
대상 표면: `skills/kws-codex-plan-executor` state validation, static eval runner, completion audit, run quality

## Problem

최근 CPE run state 분석에서 제품 검증 자체는 대체로 통과했지만 완료 상태의 운영
품질이 흔들리는 패턴이 확인됐다.

- `completion_audit.residual_risk`가 list가 아니라 string/null인 run이 남아
  downstream 집계가 문자 단위로 쪼개질 수 있다.
- finished state에 v2.22 operational fields가 있어도 `run_quality`가 없거나
  inspection 시점에만 재계산되는 경우가 있다.
- `full_spec_fallback`은 readiness에서 fixable issue로 보이지만 finished state에
  품질 요약으로 남지 않으면 다음 실행 개선으로 이어지기 어렵다.

## Goals

- Finished `completion_audit`는 list-shaped fields만 허용한다.
- v2.22 operational-quality finished state는 embedded `run_quality`를 요구한다.
- `run_quality`는 최소한 readiness, dispatch consistency, context quality,
  verification quality를 담는다.
- 기존 v2.19/v2.20 state compatibility는 유지한다. operational fields를 쓰는
  finished state만 강화한다.

## Non-goals

- Subagent dispatch policy를 더 공격적으로 바꾸지 않는다.
- Safety gate, dirty overlap, lockfile/risk marker blocking을 완화하지 않는다.
- 기존 archived state를 자동 변환하지 않는다.

## Design

`validate_state.py`가 finished state의 completion audit shape를 명시적으로 검증한다.
`prompt_to_artifact_checklist`, `verification_evidence`, `residual_risk`는 모두 list여야
한다. 알려진 잔여 리스크가 없으면 `residual_risk: []`를 쓴다.

Operational-quality state는 `source_workspace`, `execution_worktree`,
`command_cwd_evidence`, `delegation_policy`, `preflight_bootstrap`, `run_quality` 중 하나를
가진 state로 판단한다. 이런 state가 `lifecycle_outcome=finished`이면 `run_quality`를
필수로 요구한다. 이 요약은 `readiness`, `dispatch_consistency`, `context_quality`,
`verification_quality`를 포함해야 한다.

Static eval runner도 같은 shape를 생성한다. 그래야 harness가 만드는 deterministic
state가 실제 완료 계약을 계속 대표한다.

## Verification

- `python3 skills/kws-codex-plan-executor/evals/check_state_schema.py`
- `python3 skills/kws-codex-plan-executor/evals/check_operational_run_quality.py`
- `python3 skills/kws-codex-plan-executor/evals/run.sh`
- `python3 -m py_compile skills/kws-codex-plan-executor/scripts/*.py skills/kws-codex-plan-executor/evals/*.py`
- `bash -n skills/kws-codex-plan-executor/evals/run.sh`
- `git diff --check`
