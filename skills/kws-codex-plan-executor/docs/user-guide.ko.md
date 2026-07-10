# CPE v3 사용자 가이드

CPE v3는 구현 계획을 별도 Git worktree에서 실행하고, 모든 상태 변화를
해시 체인 이벤트로 남기는 독립 실행기입니다.

## 실행과 내보내기

```bash
python3 scripts/cpe.py run --plan /abs/plan.md --spec /abs/spec.md \
  --workspace /abs/repo --mode interactive
python3 scripts/cpe.py resume --run-id RUN_ID

python3 scripts/cpe.py export --plan /abs/plan.md \
  --workspace /abs/repo --mode prompt
python3 scripts/cpe.py export --plan /abs/plan.md \
  --workspace /abs/repo --mode handoff
```

`run`과 `resume`은 실행 명령입니다. `prompt`와 `handoff` 내보내기는
실행하지 않으며 worktree나 실행 상태를 만들지 않습니다.

## 고정 모델 정책

- 조정, 구현, 리뷰, 검증 판단, 수리, 완료 판단은 항상 Sol/high입니다.
- Terra/high는 쓰기와 품질 판정이 금지된 제한적 읽기 전용 조사에만
  사용할 수 있습니다.
- 모델·추론 강도·프로필·별칭·대체 경로는 실행 인자로 고를 수 없습니다.
- 실제 실행 인자와 attestation이 맞지 않으면 완료할 수 없습니다.

## 실행 데이터

```text
~/.codex/worktrees/<run_id>/       제품 코드 작업
~/.codex/orchestrator/<run_id>/    실행 기록
  run_manifest.json                변경되지 않는 입력 해시
  events.jsonl                     권위 있는 이벤트 이력
  state.json                       재생성 가능한 현재 상태
  artifacts/                       해시로 검증되는 증거
```

스펙을 제공했다면 각 작업에 명시적인 `spec_refs`가 있어야 합니다. 매핑이
없거나 충돌하면 수정 전에 중단합니다. 쓰기 작업은 한 번에 하나씩 실행하고,
독립적인 읽기 전용 조사만 제한적으로 동시에 실행할 수 있습니다.

## 점검과 복구

```bash
python3 scripts/validate_state.py ~/.codex/orchestrator/RUN_ID
python3 scripts/reconcile_state.py --run-dir ~/.codex/orchestrator/RUN_ID --check
python3 scripts/repair_runs.py --run-id RUN_ID --action ACTION
python3 scripts/inspect_runs.py --codex-home ~/.codex --all-plans
python3 scripts/analyze_recent_runs.py --codex-home ~/.codex --recent 20
```

수리는 기본적으로 계획만 보여 줍니다. 실제 적용에는 허용된 정확한 action과
`--apply`가 필요합니다. 손상된 이벤트를 덮어쓰거나 성공 증거를 만들어 내지
않습니다. 이전 스키마는 `unsupported_schema`로만 표시하고 파일을 바꾸지
않습니다.

## 릴리스 상태

현재 3.0.0 메타데이터 상태는 `deterministic-ready; paid-live-pending`입니다.
결정론적 검사와 유료 평가의 dry-run 계획은 통과했지만, 실제 4개 treatment ×
8개 case 평가는 실행하지 않았습니다. 동일 세션에서 비용을 명시적으로 승인한
뒤 `$50.00` 상한 안에서 실행하고 release gate가 통과하기 전에는 유료 라이브
릴리스 완료로 말할 수 없습니다.
