# CPE 근거 기반 실행 최적화 설계

**상태:** 승인된 설계

**작성일:** 2026-07-17

**대상:** `skills/kws-codex-plan-executor` 2.0

**대체 대상:** `kws-codex-plan-executor` 1.3.2

**독자:** CPE 구현 에이전트, 리뷰어, 릴리스 담당자

## 1. 결정 요약

CPE 2.0은 승인된 Superpowers spec과 plan을 지금과 같은 방식으로 받아
순서대로 실행한다. 사용자는 execution bundle이나 별도 manifest를 작성하지
않는다. Superpowers skill, `writing-plans`, plan 형식, hook도 수정하지 않는다.

CPE가 내부 준비 단계에서 immutable plan snapshot을 읽고 private
`compiled-run-index.json`을 자동 생성한다. 이 인덱스와 실행 중 구조화된
ledger를 사용해 다음 낭비를 줄인다.

1. 환경이 바뀌지 않았는데 동일 blocker로 controller를 다시 실행하는 낭비
2. 작업이 전진 중인 장기 plan을 고정 timeout 실패로 처리하는 낭비
3. result envelope 형식 오류 때문에 제품 작업과 전체 검증을 반복하는 낭비
4. 동일한 HEAD, 환경, 단계, 입력에서 deterministic 검증을 다시 실행하는 낭비
5. 완료 task와 review evidence를 resume controller가 다시 읽고 재수행하는 낭비
6. 실행 근거가 부족해 다음 개선 감사를 매번 수작업으로 재구성하는 낭비

CPE는 product task mapper, semantic reviewer, merge engine, dashboard가 되지
않는다. 구현, TDD, task review, finding 수정, final whole-branch review는
계속 Superpowers controller가 소유한다. CPE는 실행 인덱스, process와
checkpoint, 기계적 evidence key, 중복 방지, recovery, 관측과 리포트만
소유한다.

이 설계는 format-version-1 runtime compatibility를 제공하지 않는다. 2.0은
새 state, result, ledger 계약만 지원한다. 기존 private run directory는
삭제하지 않지만 2.0의 inspect, resume, acceptance 대상으로 해석하지 않는다.

## 2. 문제 정의와 근거

### 2.1 이미 존재하는 올바른 품질 경계

현재 launcher prompt와 README는 이미 다음 lean-quality 방향을 선언한다.

- task worker는 plan-declared focused RED/GREEN을 실행한다.
- task마다 자동 full-suite를 실행하지 않는다.
- reviewer는 기록된 test evidence를 재사용한다.
- finding은 한 번에 모아 한 번의 consolidated fix로 해결한다.
- finding fix 뒤에는 finding delta와 affected evidence만 재검토한다.
- 모든 task 뒤 whole-branch full review를 한 번 실행한다. 그 review가 finding을
  열어 HEAD가 바뀌면 full review 전체를 replay하지 않고 finding delta를
  재검토해 새 HEAD에 final approval을 결속한다.
- final full verification은 evidence key마다 성공 PASS를 한 번만 보존한다.
  Product fix로 HEAD가 바뀌거나 transient observation이 실패한 경우의 재실행은
  정당한 새 observation이다.
- 같은 HEAD에서 같은 normalized command를 이유 없이 두 번 실행하지 않는다.

따라서 관측된 비용 문제의 해법은 reviewer 수를 줄이거나 검증을 생략하는
것이 아니다. 현재 선언만 되어 있는 lean contract를 구조적으로 기록하고,
resume과 recovery가 그 근거를 실제로 재사용하게 만드는 것이 해법이다.

### 2.2 직접 확인된 CPE 실행 낭비

2026-07-17에 format-version-1 CPE run 네 개와 현재 source를 확인했다.
현재 deterministic gate는 다음과 같이 통과했다.

```text
./evals/run.sh
35 runner tests passed
7 CLI tests passed
2 suites passed
```

즉 현재 결함은 기존 process/state safety test가 깨진 문제가 아니다. 그
안전 경계 밖의 장기 실행, 환경 capability, evidence 재사용과 사후 관측
계약이 부족한 문제다.

Canvas run `cpe-d783e575720a4f81`에서는 다음이 확인됐다.

| 항목 | 관측값 |
|---|---:|
| plan attempt | 12 |
| 정확히 3,600초에 종료된 timeout | 5 |
| 수동 resume | 6 |
| result integrity failure | 2 |
| plan blocked | 2 |
| attempt 누적 실행 시간 | 약 7시간 21분 |
| run wall time | 약 9시간 9분 |
| 관측 가능한 input token 하한 | 27,043,347 |
| usage가 없는 attempt | 5, 모두 timeout |

Plan 01과 Plan 02는 timeout 사이에 HEAD가 전진했지만 두 번째 timeout이
다시 `timeout`으로 분류되어 수동 resume을 요구했다. Plan 01과 Plan 02의
완료 HEAD에서는 제품 작업이 끝난 뒤 workflow artifact 경로 또는 result
shape 문제 때문에 별도 controller attempt가 추가됐다.

또 다른 Canvas run `cpe-96f171c004ac49b8`의 Plan 02는 17 attempts에
도달했다. 다음 문자열처럼 표현만 다른 동일 계열 blocker가 반복됐다.

```text
listen EPERM 127.0.0.1:3114
sandbox-EPERM-localhost-and-graphify
managed-environment EPERM: listen 127.0.0.1:3115 and graphify rebuild
managed_environment_eperm_loopback_127.0.0.1:3114_and_graphify_rebuild
```

모델 controller를 다시 실행해도 sandbox의 loopback bind 권한이나 Graphify
write capability는 생기지 않는다. free-form signature와 수동 resume이
동일 환경에서 큰 attempt를 반복하게 만들었다.

### 2.3 live integration drift

1.3.0 deterministic release 뒤 다음 두 실환경 호환 수정이 별도 commit으로
필요했다.

- `bf9c2d9`: strict structured-output schema compatibility
- `09346a6`: linked-worktree Git common directory write access

Fast deterministic eval은 유지할 가치가 있지만, 실제 Codex schema,
sandbox, linked-worktree 경계를 독립적으로 증명하지는 않는다. 이 설계는
일반 gate를 느리게 만들지 않고 opt-in live canary로 그 경계를 분리한다.

### 2.4 직접 CPE evidence가 아닌 비교 사례

ReadMates Spring AI 2.0 작업과 GasStation Urban Signal 작업은 현재 CPE
1.3.2 run이 아니다. 따라서 CPE 성공 또는 실패 통계로 사용하지 않는다.
두 사례는 각각 다음 사각지대를 보여주는 비교 근거로만 사용한다.

- 15-task, 약 10시간 43분 실행의 one-controller 부적합성
- full conversation 상속과 agent polling 비용
- moving local `main`으로 인한 integration 재검증
- Docker, Testcontainers, loopback, Android device 같은 host capability
- Goal에만 있는 remote prohibition, cleanup, merged-main verification 계약
- 기존 dirty worktree를 계속해야 하는 요청과 clean-worktree CPE의 부적합성

이 provenance 구분은 모든 자동 리포트에도 적용한다. CPE receipt가 없는
작업은 CPE 실행 사례로 표시할 수 없다.

## 3. 목표

1. 사용자에게 추가 문서 작성이나 bundle 작성을 요구하지 않는다.
2. 기존 `--spec`, `--plan`, `--workspace` 실행 경험을 유지한다.
3. Superpowers upstream을 수정하거나 그 내부 형식에 patch를 유지하지 않는다.
4. 동일 품질을 유지하면서 의미 없는 retry, context 재로딩, 검증 중복을 줄인다.
5. 작업이 전진 중인 장기 plan을 정상 checkpoint continuation으로 처리한다.
6. environment blocker는 capability 변화 전까지 zero-model-call로 멈춘다.
7. 기계적 result-envelope 오류를 제품 작업과 분리해 복구한다.
8. task, review, verification, recovery의 원인과 결과를 bounded evidence로 남긴다.
9. plan/run 종료 때 원인, 증상, 영향, 대응, 결과, 개선 후보를 자동 생성한다.
10. 사실, child 주장, derived 판단, hypothesis를 구분한다.
11. CPE와 direct Superpowers, Waygent의 적합성 경계를 실행 전에 알려준다.
12. 기존 lock, atomic state, process-group cleanup, bounded log, exact HEAD,
    clean-worktree, ancestry 안전성을 유지한다.

## 4. 비목표

- Superpowers `SKILL.md`, `writing-plans`, template 또는 hook 수정
- 자연어 plan을 CPE task graph의 새로운 source of truth로 변환
- shared worktree parallel scheduler
- CPE의 semantic code review 또는 Superpowers review 재수행
- task마다 broad full-suite 자동 실행
- 검증 생략을 통한 속도 개선
- 자동 local-main merge, push, PR, deploy
- Waygent queue, dashboard, policy engine 복제
- raw Codex transcript, prompt 본문, source diff 또는 secret 저장
- broad `danger-full-access` child sandbox
- format-version-1 inspect, resume, migration 또는 dual-schema runtime
- 부분 Windows support

## 5. 사용자 경험

### 5.1 실행 명령

사용자는 현재와 같은 입력만 제공한다.

```bash
python3 scripts/cpe.py run \
  --spec /abs/spec-a.md --spec /abs/spec-b.md \
  --plan /abs/plan-01.md --plan /abs/plan-02.md \
  --workspace /abs/repository

python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py inspect --run-id RUN_ID
```

내부 index, ledger schema, evidence key는 사용자 입력이 아니다.

### 5.2 CPE skill 호출과 operator contract

CPE skill을 통해 실행할 때 현재 사용자 요청에서 CPE가 소유해야 할 운영
조건만 private operator contract로 snapshot한다.

- workspace와 source commit
- plan 순서
- remote mutation policy
- branch completion 이후 handoff 범위
- 명시된 capability와 external blocker policy
- 최종 보고 요구

이는 CPE skill 자체의 동작이며 Superpowers 산출물이나 upstream skill을
수정하지 않는다. CLI를 직접 실행해 별도 contract가 없으면 다음 안전한
기본값을 사용한다.

- isolated clean worktree 생성
- CPE branch completion까지만 소유
- merge, push, PR, deploy 금지
- 외부 capability가 불명확하면 자동 권한 확대 금지

전체 사용자 prompt는 저장하지 않는다. CPE skill이 allowlisted operational
field만 추출해 contract로 기록하며, 나머지 대화와 prompt 본문은 run artifact에
포함하지 않는다.

### 5.3 실행 단계

```text
spec/plan 전달
  -> immutable snapshot
  -> private compiled run index
  -> deterministic source validation
  -> fit/capability preflight
  -> isolated worktree
  -> Superpowers plan controller
  -> checkpoint/recovery/evidence reuse
  -> mechanical acceptance
  -> optimization report와 finish handoff
```

## 6. 책임 경계

| 관심사 | 소유자 |
|---|---|
| product architecture와 task 의미 | 승인된 spec/plan |
| task mapping, TDD, 구현, task review | Superpowers controller |
| finding 수정과 delta review | Superpowers controller |
| final whole-branch review | Superpowers controller |
| input snapshot과 internal run index | CPE |
| worktree, process, timeout, checkpoint, resume | CPE |
| verification evidence key와 reuse decision | CPE helper/parent |
| blocker canonicalization과 capability probe | CPE |
| structured execution observation과 report | CPE |
| long multi-agent scheduling과 rich run UX | Waygent |
| local merge/apply | 별도 finishing workflow 또는 Waygent apply |
| push, PR, deploy | 별도 명시적 권한을 받은 workflow |

CPE는 task review가 수행됐다는 구조와 evidence reference를 기록할 수 있다.
그러나 reviewer처럼 diff를 읽고 verdict를 다시 내리지 않는다. review 품질을
향상한다는 이유로 CPE reviewer를 추가하지 않는다.

## 7. CPE-owned compiled run index

### 7.1 위치와 권위

```text
~/.codex/orchestrator/<run-id>/compiled-run-index.json
```

Index는 CPE가 자동 생성하는 private derivative다. 원본 spec/plan snapshot과
operator contract가 계속 권위 입력이다. Index가 원문과 충돌하면 원문이
이기며 해당 index는 거절된다.

### 7.2 compiler 실행 계약

Compiler는 CPE 내부의 bounded read-only Codex invocation이다.

- snapshot path만 읽는다.
- product repository file을 수정하지 않는다.
- subagent를 생성하지 않는다.
- Git mutation과 network를 사용하지 않는다.
- strict output schema를 사용한다.
- 한 번의 Codex turn만 사용한다.
- 전체 snapshot input은 최대 512 KiB, compiler timeout은 300초,
  structured output은 최대 1 MiB로 제한한다.
- plan별 task ID와 순서, 검증 command text, capability hint, plan 크기,
  source line span, source text digest만 반환한다.
- 원문에 없는 task, command, authority를 추가할 수 없다.

Compiler 결과는 다음 cache key가 같을 때 재사용한다.

```text
spec_snapshot_digests
+ ordered_plan_snapshot_digests
+ operator_contract_digest
+ compiler_schema_version
+ cpe_version
```

### 7.3 deterministic source validation

모든 extracted item은 다음을 만족해야 한다.

- snapshot의 실제 line range 안에 있다.
- normalized source text digest가 일치한다.
- task 순서는 원문 순서와 같다.
- command text는 원문에 실제로 존재한다.
- capability는 source command 또는 contract reference를 가진다.
- 같은 task ID와 command ID가 중복되지 않는다.

Compiler 결과가 schema 또는 source validation을 통과하지 못하면 한 번만
fresh repair compile을 수행한다. 두 번째에도 선택적 항목이 불확실하면 그
항목을 `unknown`으로 기록하고 관련 최적화만 끈 채 실행한다.

다음 안전 필드는 `unknown` fallback을 허용하지 않는다.

- workspace와 repository identity
- source commit
- ordered plan identity
- remote mutation policy
- 명시적 destructive action authority

이 필드가 불확실하면 product model call 전에 중단한다.

### 7.4 fit 결과

Index와 contract를 사용해 다음 enum 중 하나를 출력한다.

```text
fit_cpe
prefer_direct_superpowers
split_or_checkpoint_required
handoff_to_waygent
unsupported_existing_worktree
capability_blocked
```

권고는 실행기를 강제로 바꾸지 않는다. 단, 현재 CPE 안전 경계와 충돌하는
dirty existing worktree, repository mismatch, remote authority conflict는
model call 전에 중단한다.

## 8. Optimization flight recorder

### 8.1 저장 구조

기본 run root는 유지한다.

```text
~/.codex/orchestrator/<run-id>/
  state.json
  events.jsonl
  run.lock
  compiled-run-index.json
  inputs/
  results/
  logs/
  evidence/
    plan-01/
      execution-ledger.jsonl
      verification-index.json
      evidence-manifest.json
  reports/
    optimization-report.json
    optimization-report.md
```

실행 중 controller artifact는 다음 worktree path에 존재할 수 있다.

```text
~/.codex/worktrees/<run-id>/.superpowers/sdd/
```

Plan acceptance 전에 보존 대상만 run root의 `evidence/`로 bounded ingest하고
SHA-256을 기록한 뒤 read-only로 seal한다. Worktree cleanup 뒤에도 private
evidence는 남는다.

### 8.2 source of truth

- `state.json`: run과 plan 상태의 유일한 권위 상태
- `events.jsonl`: CPE parent가 기록한 append-only lifecycle observation
- worktree execution ledger: controller가 보고한 실행 활동
- sealed evidence: 특정 HEAD에서 수락한 ledger와 receipt snapshot
- optimization report JSON/Markdown: 위 근거에서 생성한 derivative

Markdown report는 state나 acceptance를 변경하지 않는다.

### 8.3 신뢰 수준

모든 observation과 report finding은 다음 중 하나를 가진다.

| 수준 | 의미 |
|---|---|
| `parent_observed` | CPE가 process, Git, file, probe로 직접 확인 |
| `child_attested` | controller가 보고했지만 CPE가 의미를 독립 검증하지 않음 |
| `derived` | parent/child evidence에서 deterministic rule로 계산 |
| `hypothesis` | agent가 제안한 원인으로 사실로 확정되지 않음 |

`hypothesis`만 있는 항목은 자동 blocker, cache reuse, completion 판정의
근거가 될 수 없다.

### 8.4 event envelope

```json
{
  "event_id": "bounded-unique-id",
  "at": "RFC3339 timestamp",
  "source": "parent_observed",
  "run_id": "cpe-...",
  "plan_id": "plan-01",
  "attempt": 2,
  "task_id": "task-05",
  "category": "verification",
  "action": "reused",
  "reason_code": "same_evidence_key",
  "head_before": "40-char-sha",
  "head_after": "40-char-sha",
  "command_id": "final-static",
  "evidence_key": "sha256:...",
  "duration_ms": 0,
  "result": "pass",
  "evidence_refs": ["evidence/plan-01/verification-index.json"]
}
```

Event는 content-free metadata와 bounded references만 포함한다. Command의
raw environment, full output, transcript는 저장하지 않는다.

### 8.5 자동 리포트

Plan terminal state와 run terminal state마다 다음을 생성한다.

- 증상
- 관측 또는 분류된 원인 code
- 영향
- 대응
- 대응 결과
- recurrence count
- 사용된 wall time과 token lower bound
- usage unknown attempt count
- 제거 가능한 중복
- 정당한 재실행과 그 이유
- 다음 개선 후보
- evidence reference
- 신뢰 수준

Cross-run 분석은 두 개 이상의 독립 run에서 같은 canonical signal이
반복되거나, 단일 run에서 같은 signal이 3회 이상 반복되면서 관측된 누적
duration이 30분 이상인 경우에만 backlog 후보로 승격한다. Usage가
불완전하면 token 수가 아니라 duration 기준만 사용한다. 자동으로 source
code나 policy를 수정하지 않는다.

### 8.6 coordination telemetry

Codex event stream이 제공하는 경우 content를 저장하지 않고 다음 bounded
metadata만 집계한다.

- agent spawn count와 depth
- task ID와 implementer/reviewer role
- `fork_turns` policy
- wait, list, send, followup count
- agent duration
- context compaction count
- usage available 여부와 unavailable reason

Implementer와 reviewer의 기본은 `fork_turns=none`이다. 필요한 context는
task brief, implementer report, review package의 path와 digest로 전달한다.
`fork_turns=all`은 plan task가 이전 대화 전체를 직접 요구하고 compiler
index가 그 예외를 source reference와 함께 기록한 경우에만 허용한다.

CPE가 event stream에서 실제 `fork_turns`를 관측할 수 없으면 이 항목을
`child_attested`로 표시한다. 관측할 수 없는 agent separation이나 context
policy를 독립 증명했다고 보고하지 않는다.

## 9. 최적화 정책

### 9.1 동일 environment blocker 차단

Free-form failure signature 대신 typed blocker를 사용한다.

```json
{
  "kind": "verification_environment",
  "code": "loopback_bind_denied",
  "resource": "loopback_tcp",
  "operation": "bind",
  "errno": "EPERM",
  "retry_condition": "capability_probe_passes",
  "fingerprint": "sha256:..."
}
```

CPE가 controlled fields로 fingerprint를 계산한다. 의미가 같은 port variation은
plan이 port identity를 요구하지 않는 한 같은 capability로 canonicalize한다.

Resume 전 probe 결과와 fingerprint가 이전 blocker와 같으면 다음이 적용된다.

- child launch 0회
- attempt count 증가 없음
- model usage 0
- `next_action=fix_environment_then_resume`
- 마지막 probe와 필요한 변화 조건을 inspect에 표시

`--retry-failed`도 동일 환경 fingerprint를 무시할 수 없다. Operator가
환경이 바뀌었다고 주장하면 probe가 그 변화를 확인해야 한다.

### 9.2 progress-aware checkpoint

Attempt 전후 다음 progress fingerprint를 계산한다.

```text
HEAD
+ completed task IDs
+ current task ID
+ accepted review evidence IDs
+ closed finding IDs
```

다음 규칙을 적용한다.

| 관측 | 결과 |
|---|---|
| timeout/context budget + fingerprint 전진 | `progress_checkpoint` |
| controller voluntary checkpoint + fingerprint 전진 | `progress_checkpoint` |
| timeout + fingerprint 동일 | `stalled_timeout` |
| dirty file만 있고 commit/ledger 전진 없음 | progress로 인정하지 않음 |
| plan total budget 초과 | `budget_exhausted` |

`progress_checkpoint`는 failure retry allowance를 소비하지 않는다. 새 controller는
sealed ledger와 current HEAD에서 다음 미완료 task부터 자동으로 이어간다.

Run creation 때 다음 budget을 snapshot한다.

- controller slice timeout
- plan당 최대 checkpoint 수
- plan 총 wall-time budget
- plan 총 model-attempt budget

명시적 operator override가 없을 때의 기본값은 다음과 같다.

```text
controller_slice_timeout_seconds = 3600
max_progress_checkpoints_per_plan = 6
plan_wall_budget_seconds = 21600
max_controller_launches_per_plan = 8
```

Compiler가 plan이 이 범위를 넘을 가능성이 높다고 분류하면 CPE는 실행을
막지 않고 `split_or_checkpoint_required`를 표시한다. Host resource, moving
integration target, 장시간 multi-agent coordination이 함께 요구되면
`handoff_to_waygent`를 권고한다. 실제 실행은 위 hard budget을 넘지 않는다.

Compiler가 정확한 task 수를 알 수 없으면 보수적인 default budget을 사용하고
실행 중 ledger에서 관측된 progress만 신뢰한다.

### 9.3 verification run-and-record

CPE는 plan-declared command를 실행하는 범용 helper를 controller에게 제공한다.
이 helper는 Superpowers를 수정하지 않고 CPE launcher prompt와 run-private
tool path로만 노출한다.

```text
run-and-record
  --command-id ID
  --phase PHASE
  --input-digest DIGEST
  -- argv...
```

Evidence key는 다음이다.

```text
command_id
+ exact argv digest
+ cwd identity
+ HEAD
+ environment fingerprint
+ phase
+ input digest
+ mutable-state policy
```

다음 조건이 모두 참일 때만 기존 PASS를 재사용한다.

- 같은 run 안의 sealed 또는 current verified evidence다.
- evidence key가 byte-for-byte 같다.
- command가 deterministic으로 선언됐다.
- 이전 result가 PASS다.
- output artifact가 필요하면 digest가 여전히 일치한다.

다음은 항상 새로 실행한다.

- HEAD가 바뀜
- environment 또는 dependency fingerprint가 바뀜
- task phase와 final phase가 다름
- branch phase와 merged-main phase가 다름
- mutable external state를 검증함
- 이전 observation이 transient failure 또는 incomplete임
- contract가 명시적으로 path revalidation을 요구함

Helper 자체가 실패하면 검증을 skip하지 않는다. Cache를 사용하지 않고 실제
명령을 실행한 뒤 `verification_helper_fallback`을 기록한다.

Cross-run verification PASS는 자동 재사용하지 않는다. Cross-run data는
최적화 분석에만 사용한다.

### 9.4 review 중복 방지

Review 계약은 다음으로 고정한다.

1. task implementation diff에 task review 한 번
2. finding set을 한 번에 모아 consolidated fix 한 번
3. fix 뒤 finding delta와 affected evidence만 재검토
4. 모든 task 뒤 final whole-branch review 한 번
5. CPE는 review receipt의 구조와 HEAD binding만 기록
6. CPE가 semantic reviewer를 추가 실행하지 않음

새 HEAD에서 수정된 영역이 이전 review scope 밖이면 affected task review가
다시 필요한 것은 정당한 재실행이다. 같은 diff와 같은 evidence를 reviewer가
다시 읽는 것은 duplicate candidate로 기록한다.

Task 사이에 일시적인 compatibility bridge, deferred cleanup, follow-up
verification이 생기면 structured obligation으로 기록한다.

```json
{
  "obligation_id": "remove-temporary-compatibility-bridge",
  "opened_by_task": "task-01",
  "must_close_by_task": "task-07",
  "status": "open",
  "closure_evidence_id": "no-legacy-bridge-scan"
}
```

Open obligation과 deferred finding은 checkpoint와 resume에 그대로 전달한다.
Deadline task가 완료됐는데 obligation이 열려 있으면 다음 task를 진행하지
않고 typed blocker로 중단한다. 이는 plan prose를 CPE가 재해석하는 기능이
아니라 controller가 명시적으로 남긴 transition debt를 유실하지 않는 기능이다.

### 9.5 result-envelope 전용 복구

다음 조건을 모두 만족하면 model-free repair가 가능하다.

- worktree HEAD가 result의 candidate HEAD와 같다.
- worktree가 clean이다.
- product verification evidence key와 digest가 변하지 않았다.
- review verdict와 finding state가 변하지 않는다.
- 오류가 allowlisted wire/path normalization에만 해당한다.

허용되는 repair 예시는 exact owned worktree 내부의 safe absolute artifact
path를 상대경로로 변환하는 것이다. 다음은 repair할 수 없다.

- status
- HEAD
- verification result 또는 exit code
- review verdict
- open finding
- commit ancestry
- remote policy

원본 result는 immutable로 보존한다. Repaired result는 새 파일로 작성하고
original digest, repaired digest, normalization rule을 append-only event에
기록한다.

## 10. 상태와 데이터 흐름

### 10.1 run 상태

Format-2 run은 다음 상태만 사용한다.

```text
preparing
ready
running
checkpointed
blocked
failed
completed
```

`preparing`은 input snapshot과 compiled index 준비를 포함한다. `ready`는
source validation과 preflight가 끝나 worktree/controller launch가 가능한
상태다. `checkpointed`는 실패가 아니라 다음 controller slice를 기다리는
durable continuation 상태다.

### 10.2 plan 실행 흐름

1. Input과 operator contract snapshot
2. Internal compiler 실행 또는 cache reuse
3. Deterministic source validation
4. Fit/capability preflight
5. Worktree creation
6. Plan controller launch
7. Task/review/verification ledger 기록
8. Attempt 종료 시 progress와 blocker classification
9. Checkpoint continuation, blocked stop 또는 mechanical acceptance
10. Evidence ingest/hash/seal
11. Plan optimization report 갱신
12. 다음 ordered plan 실행
13. Run report와 branch-completion handoff 생성

## 11. 오류 처리

| 상황 | 동작 |
|---|---|
| 선택적 index 항목 불확실 | `unknown`, 관련 최적화만 비활성화, 실행 계속 |
| 안전 필드 불확실 | product model call 전에 중단 |
| compiler 첫 결과 invalid | bounded fresh repair compile 한 번 |
| compiler 두 번째도 선택적 invalid | 해당 필드 없이 보수 실행 |
| evidence cache key 불완전 | cache miss로 처리하고 실제 명령 실행 |
| evidence digest mismatch | cache miss와 tamper event, 실제 명령 실행 |
| helper 내부 오류 | 실제 명령 실행, fallback event |
| unchanged capability blocker | zero-model-call blocked 유지 |
| progressing timeout | checkpoint continuation |
| stalled timeout 반복 | bounded stop |
| envelope-only allowlisted 오류 | model-free repair |
| semantic result 오류 | fail closed, 자동 repair 금지 |
| derived Markdown report 실패 | structured event 기록, product completion 유지 |
| authoritative state/event write 실패 | fail closed |
| evidence ingest size 초과 | completion 차단, bounded manifest에 초과 정보 기록 |

Derived report 실패가 product completion을 뒤집지 않는 이유는 report가
source of truth가 아니기 때문이다. 반면 authoritative state와 sealed evidence
실패는 이후 resume과 dedup 판단을 신뢰할 수 없으므로 fail closed한다.

## 12. CLI와 운영 가시성

기존 명령은 유지하고 다음 read-only surface를 추가한다.

```bash
python3 scripts/cpe.py doctor \
  --spec /abs/spec.md --plan /abs/plan.md --workspace /abs/repo

python3 scripts/cpe.py list --workspace /abs/repo
python3 scripts/cpe.py inspect --run-id RUN_ID --efficiency
python3 scripts/cpe.py report --run-id RUN_ID
python3 scripts/cpe.py analyze --workspace /abs/repo
```

`inspect --efficiency`는 다음을 표시한다.

- current plan/task/attempt
- active, checkpointed, blocked, stalled 구분
- current HEAD와 last progress HEAD
- attempt elapsed와 last activity
- blocker code, recurrence, fingerprint, last probe
- verification executed/reused/fallback counts
- duplicate review/verification candidates
- usage lower bound와 unknown attempt count
- next action enum
- logs, evidence, report path

Worktree가 없으면 `observed_head`는 `null`이다. `source_commit`을 현재
worktree HEAD처럼 대신 표시하지 않는다. 마지막으로 확인한 값은 별도
`last_known_head`에만 표시한다.

Completed run은 다음 branch-completion handoff를 생성한다.

```json
{
  "completion_scope": "cpe_branch_completed",
  "source_commit": "40-char-sha",
  "accepted_head": "40-char-sha",
  "integration_target": "refs/heads/main",
  "observed_target_head": "40-char-sha-or-null",
  "base_drift": true,
  "remote_policy": "forbidden",
  "optimization_report_digest": "sha256:...",
  "evidence_manifest_digest": "sha256:..."
}
```

이 handoff는 merge를 수행하지 않는다. 별도 finishing workflow의 integration
receipt가 없으면 CPE branch 완료를 local-main integration 또는 전체 Goal
완료로 보고할 수 없다.

JSON mode는 machine output만 stdout에 쓴다. Human mode는 명시적으로
선택한다. Inspect, list, report, analyze는 Git이나 run state를 mutate하지 않는다.

## 13. 보안과 보존

- Run directory는 `0700`이다.
- Mutable private files은 `0600`이다.
- Accepted result와 sealed evidence는 `0400`이다.
- Symlink, parent traversal, outside-run-root artifact를 거부한다.
- Attempt log는 현재 bounded tail 정책을 유지한다.
- Sealed evidence는 plan당 최대 128개 파일, 파일당 1 MiB, 총 8 MiB로
  제한한다.
- Optimization report JSON과 Markdown은 각각 최대 1 MiB로 제한한다.
- Environment fingerprint는 version과 capability metadata만 포함한다.
- Token, password, cookie, provider key, full environment value를 저장하지 않는다.
- Raw Codex JSONL, prompt, transcript를 durable evidence로 저장하지 않는다.
- Product source diff를 evidence bundle에 복사하지 않는다.
- Worktree cleanup은 private evidence seal 뒤에만 허용한다.
- 기존 format-version-1 run directory는 자동 삭제하거나 rewrite하지 않는다.

## 14. 구현 순서

### Wave 0 — Format-2와 evidence fixture

1. Canvas direct-run evidence를 sanitized deterministic fixture로 축소한다.
2. ReadMates와 GasStation은 non-CPE comparative fixture로 명시한다.
3. Format-2 state/result/event schema를 정의한다.
4. Format-version-1 runtime compatibility code와 test 요구를 제거한다.
5. 기존 process/state safety fixture를 format-2로 이식한다.

### Wave 1 — Internal compiler와 flight recorder

1. CPE-owned bounded compiler
2. `compiled-run-index.json` schema와 source validator
3. Compiler cache와 one-repair policy
4. Structured execution ledger와 trust levels
5. Evidence ingest/hash/seal
6. Optimization report JSON/Markdown

### Wave 2 — 즉시 비용 절감

1. Typed blocker와 canonical capability fingerprint
2. Zero-model-call resume guard
3. Progress fingerprint와 checkpoint continuation
4. Stalled timeout stop
5. Result-envelope diagnostics와 allowlisted repair

### Wave 3 — 검증과 review evidence 재사용

1. `run-and-record` helper
2. Exact evidence key와 same-run cache
3. Helper fallback
4. Verification reason taxonomy
5. Review/finding/delta lifecycle ledger
6. Duplicate candidate reporting

### Wave 4 — 적합성, 운영 UX, cross-run 분석

1. `doctor` fit result
2. `list`와 efficiency inspect
3. Read-only report/analyze
4. Branch-completion finish handoff
5. Opt-in live canary
6. Behavior fixture가 고정된 뒤 runner/launcher 내부 책임 분리

### Planning decomposition

이 설계를 하나의 monolithic implementation plan으로 만들지 않는다.
`writing-plans` 단계는 Wave 0부터 Wave 4까지 다섯 개의 ordered plan 문서를
생성한다. 모든 plan은 이 spec 하나를 참조하고, 앞 plan의 accepted HEAD에서
다음 plan이 시작된다.

- Wave 0 plan은 format-2 contract와 기존 safety fixture 이식만 소유한다.
- Wave 1 plan은 compiler, ledger, sealed evidence, report만 소유한다.
- Wave 2 plan은 blocker, checkpoint, envelope repair만 소유한다.
- Wave 3 plan은 verification/review evidence reuse만 소유한다.
- Wave 4 plan은 doctor, inspect, analyze, live canary와 내부 refactor를 소유한다.

각 plan은 독립적으로 deterministic gate를 통과하고 clean commit을 남겨야
한다. 뒤 wave가 앞 wave의 실패를 숨기기 위해 scope를 흡수하지 않는다.

## 15. 파일 변경 지도

| 파일 또는 영역 | 변경 |
|---|---|
| `scripts/cpe.py` | doctor/list/report/analyze, format-2 CLI와 output mode |
| `scripts/cpe_runtime/state.py` | format-2 state와 validation |
| `scripts/cpe_runtime/launcher.py` | compiler/controller mode, budget, ledger path, helper exposure |
| `scripts/cpe_runtime/runner.py` | prepare, preflight, checkpoint, blocker, repair, acceptance |
| `scripts/cpe_runtime/compiler.py` | bounded read-only plan compiler와 cache |
| `scripts/cpe_runtime/evidence.py` | ledger ingest, evidence key, seal, repair |
| `scripts/cpe_runtime/reporting.py` | optimization JSON/Markdown와 cross-run analysis |
| `scripts/cpe_runtime/capabilities.py` | typed probe와 environment fingerprint |
| `scripts/cpe_runtime/verification.py` | run-and-record와 same-run evidence reuse |
| `templates/compiled-run-index.schema.json` | internal index contract |
| `templates/plan-result-schema.json` | format-2 checkpoint/blocker/evidence reference |
| `templates/execution-ledger.schema.json` | task/review/verification event contract |
| `templates/optimization-report.schema.json` | report source contract |
| `evals/` | focused optimization, fallback, process, state fixtures |
| `README.md`, `SKILL.md` | 사용자 경험, ownership, storage, support boundary |

파일 분리는 behavior fixture가 먼저 생긴 뒤 수행한다. 처음부터 대규모
refactor와 contract 변경을 한 commit에 섞지 않는다.

## 16. 검증 전략

### 16.1 필수 deterministic gate

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py resume --help
python3 scripts/cpe.py inspect --help
python3 scripts/cpe.py doctor --help
python3 scripts/cpe.py report --help
python3 scripts/cpe.py analyze --help
```

Gate는 sequential, credential-free, network-free, model-free를 유지한다.
Hard ceiling은 15초, 개발 환경 target은 12초 이하로 유지한다. Compiler는
fake strict-output fixture로 테스트하고 실제 model compiler는 live canary로
분리한다.

### 16.2 필수 최적화 fixture

1. 동일 blocker를 열 번 resume해도 launcher call 0회
2. port/signature variation이 같은 capability fingerprint로 canonicalize
3. product test failure가 environment blocker로 오분류되지 않음
4. HEAD 또는 completed task가 전진한 timeout은 checkpoint
5. progress 없는 반복 timeout은 bounded stop
6. checkpoint 뒤 completed task를 redispatch하지 않음
7. safe envelope repair는 model attempt 0회
8. semantic result 변경 repair는 거부
9. 같은 evidence key PASS는 command execution 0회
10. HEAD 변경은 cache miss
11. environment 변경은 cache miss
12. phase 변경은 cache miss
13. mutable external command는 항상 실행
14. helper failure는 실제 command fallback
15. same diff review repetition은 duplicate candidate
16. finding delta review는 정당한 재실행
17. compiler source span/digest mismatch 거부
18. optional compiler ambiguity는 conservative fallback
19. safety-field ambiguity는 pre-model stop
20. report가 unknown usage를 0으로 합산하지 않음
21. child hypothesis가 blocker나 reuse decision을 만들지 못함
22. worktree 삭제 뒤 sealed evidence와 report 검증 가능
23. transcript/secret-shaped content가 evidence에 들어가지 않음
24. CPE semantic reviewer launch가 없음
25. implementer/reviewer 기본 `fork_turns=none`과 예외 provenance
26. open transition obligation이 checkpoint/resume 뒤 유지됨
27. obligation deadline 통과가 typed blocker를 생성
28. missing worktree의 `observed_head`가 `null`
29. branch completion이 integration completion으로 표시되지 않음

### 16.3 opt-in live canary

실제 installed Codex를 사용하는 canary는 다음만 검증한다.

- strict structured output
- linked-worktree commit
- internal compiler output과 source validation
- one bounded controller execution
- run-and-record helper
- result/evidence seal

일반 deterministic gate에 포함하지 않는다. CLI, schema, sandbox, Git metadata,
output handling을 변경하거나 CPE release compatibility를 주장할 때 실행한다.

### 16.4 repository closeout

```bash
git diff --check
bun run check
```

문서 또는 구조 변경이 repo graph에 영향을 주면 현재 checkout에 존재하는
Graphify freshness 절차를 확인한 뒤 실행한다. 삭제된 과거 command를 추정해
복원하지 않는다.

## 17. 정량 수용 기준

- 동일 environment blocker 10회 resume에서 추가 child launch 0회
- progressing timeout은 manual resume 없이 다음 controller로 자동 연결
- stalled timeout은 두 번째 no-progress observation에서 중단
- envelope-only 오류는 추가 model attempt 0회
- envelope-only 오류는 product verification 재실행 0회
- same evidence key PASS 재사용 시 command execution 0회
- HEAD, environment, phase, input 중 하나가 바뀌면 새 command observation 생성
- 하나의 task finding set당 consolidated fix 1회와 delta review 1회
- final whole-branch full review 1회; finding fix가 있으면 affected delta만 재검토
- accepted final evidence key당 successful final full verification PASS 1개
- CPE semantic reviewer 실행 0회
- implementer/reviewer의 근거 없는 `fork_turns=all` 사용 0회
- checkpoint/resume에서 open obligation 유실 0건
- missing worktree에서 source commit을 observed HEAD로 표시하는 경우 0건
- integration receipt 없이 overall Goal completed로 표시하는 경우 0건
- report의 모든 finding에 evidence reference와 trust level 존재
- usage 누락 시 exact total 표기 0회
- deterministic gate 15초 이하
- raw transcript와 secret value의 durable 저장 0건
- 기존 lock/state/process cleanup safety fixture 전부 통과

## 18. Release와 support boundary

이 변경은 public state/result semantics와 runtime lifecycle을 바꾸므로 CPE
2.0.0으로 release한다.

- 1.3.x run은 2.0에서 inspect/resume하지 않는다.
- 1.3.x private directory는 그대로 보존한다.
- 2.0 CLI는 1.3.x run ID를 받으면 `unsupported_legacy_run`을 반환한다.
- Migration command와 dual-write는 제공하지 않는다.
- POSIX `fcntl`, process group, signal, `start_new_session` 의존을 명시한다.
- Windows support는 별도 설계와 real-process evidence 없이는 추가하지 않는다.
- Push, PR, deploy 권한은 release 이후에도 암묵적으로 확대하지 않는다.

## 19. 완료 정의

다음이 모두 충족되어야 구현 완료다.

- 기존 spec/plan/workspace 입력만으로 end-to-end 실행된다.
- Superpowers upstream file 변경이 없다.
- Internal index가 자동 생성되고 source validation된다.
- Index ambiguity가 안전 필드와 선택 필드를 다르게 처리한다.
- Flight recorder와 sealed evidence가 worktree 수명과 독립적이다.
- 동일 blocker, progressing timeout, stalled timeout이 구분된다.
- Result-envelope 오류가 제품 실행과 분리된다.
- Exact-key verification reuse와 legitimate rerun이 구분된다.
- CPE가 Superpowers review를 재수행하지 않는다.
- Plan/run optimization report가 자동 생성된다.
- Cross-run analyze가 evidence 없는 hypothesis를 승격하지 않는다.
- Format-version-1 compatibility code가 남지 않는다.
- Deterministic gate와 opt-in live canary가 각자의 계약을 통과한다.
- `SKILL.md`, `README.md`, schema, tests, tracked inventory가 동작과 일치한다.

## Appendix A. Canvas 직접 CPE run 근거

### A.1 `cpe-d783e575720a4f81`

이 run은 Canvas UI/UX Product Polish Waves 1–3의 직접 CPE evidence다.

핵심 관측:

- 12 attempts 중 5회가 정확히 3,600초 timeout
- Plan 01과 Plan 02에서 timeout 사이 HEAD 전진
- 동일 `timeout` signature 때문에 operator resume 필요
- `unsafe_workflow_artifact`와 `invalid_result`로 envelope correction attempt 추가
- Plan 03에서 loopback bind와 Graphify write EPERM 반복
- accepted Plan 01 result는 required browser/manual verification이 blocked였음을
  summary에 기록했지만 mechanical completion으로 수락
- worktree cleanup 뒤 receipt target을 재감사하기 어려움

이 설계가 직접 대응하는 항목:

| 관측 | 설계 대응 |
|---|---|
| progressing timeout | progress-aware checkpoint |
| repeated EPERM | typed capability fingerprint와 zero-model resume guard |
| result-only correction | allowlisted envelope repair |
| usage 없는 timeout | lower-bound report |
| worktree-local receipt | sealed evidence ingest |
| opaque run identity | list/inspect/report |

원본 근거:

```text
~/.codex/orchestrator/cpe-d783e575720a4f81/state.json
~/.codex/orchestrator/cpe-d783e575720a4f81/events.jsonl
~/.codex/orchestrator/cpe-d783e575720a4f81/results/
~/.codex/orchestrator/cpe-d783e575720a4f81/logs/
```

### A.2 `cpe-96f171c004ac49b8`

이 run의 Plan 02는 17 attempts까지 진행됐다. Loopback/Graphify 환경 blocker가
port와 문구만 바뀐 채 반복됐다. 동일 환경에서 controller resume이 capability를
바꾸지 못한다는 가장 강한 비용 근거다.

이 사례는 blocker canonicalization, unchanged-environment guard, recurrence
inspect의 regression fixture로 축소한다. Full result나 transcript를 repo에
복사하지 않는다.

## Appendix B. ReadMates 비교 근거

ReadMates Spring AI 2.0 observability 구현은 CPE 1.3.2 run이 아니다. 실제
provenance는 direct Codex Desktop Goal이었다. 따라서 CPE 실행 성공이나
비용 통계에 합산하지 않는다.

비교 근거:

| 항목 | 관측값 |
|---|---:|
| plan 크기 | 92,251 bytes, 1,745 lines |
| task 수 | 15 |
| 실행 시간 | 약 10시간 43분 |
| controller compaction | 3회 |
| root agent spawn | 22회 |
| root wait | 785회 |
| root full-context spawn | 8회 |

Task review는 permit race, retry state loss, privacy gap, accounting 오류 등
실제 Important 결함을 찾았다. 이 때문에 review를 줄이는 최적화는 거부한다.
대신 file-backed handoff, context-free worker, finding delta review, evidence
reuse를 적용한다.

실행 중 local `main`이 이동한 뒤 integration에서 새 회귀가 발견됐으므로
branch verification과 merged-main verification은 중복이 아니다. Evidence
key의 `phase`가 이 차이를 보존한다.

## Appendix C. GasStation 비교 근거

GasStation Urban Signal 작업도 CPE 1.3.2 run이 아니다. 발견된 과거
orchestration state는 다른 schema였으며 CPE format-version-1 provenance가
없었다.

비교 근거:

- 2,167-line, 8-task Android UI plan
- Roborazzi record/inspection
- Android connected test와 AVD discovery/start 필요
- 기존 dedicated dirty worktree와 uncommitted Task 1 보존 요구
- local `main` integration과 merged-main verification 요구
- remote mutation 금지와 worktree cleanup 순서 요구

현재 clean-worktree CPE가 이 요청을 그대로 받으면 사용자 변경을 누락하거나
잘못된 worktree를 만들 수 있다. 2.0 doctor는 이를
`unsupported_existing_worktree`로 model call 전에 분류한다. 자동 adoption은
이 설계에 포함하지 않는다.

Android SDK, `adb`, AVD, emulator, writable cache 같은 host capability는
compiler가 원문 reference를 가진 경우에만 preflight한다. 불확실한 capability를
이유로 child sandbox를 broad access로 확대하지 않는다.

## Appendix D. 구현 에이전트가 피해야 할 잘못된 개선

- Superpowers plan generator나 upstream skill을 수정하지 않는다.
- 사용자가 별도 bundle을 작성하게 만들지 않는다.
- Markdown heading 전용 brittle parser를 contract로 만들지 않는다.
- Timeout만 길게 늘려 one-controller 문제를 숨기지 않는다.
- Reviewer를 줄여 token을 절약하지 않는다.
- 모든 반복 검증을 duplicate로 분류하지 않는다.
- Same command string만으로 cache key를 만들지 않는다.
- Child-reported hypothesis를 parent-observed cause처럼 표시하지 않는다.
- Report 생성을 새로운 authoritative state로 만들지 않는다.
- Cross-run PASS를 자동 verification cache로 사용하지 않는다.
- Broad host access를 model child에 부여하지 않는다.
- Format-version-1 compatibility를 다시 추가하지 않는다.
- CPE 안에 merge, push, deploy 또는 Waygent scheduler를 넣지 않는다.
