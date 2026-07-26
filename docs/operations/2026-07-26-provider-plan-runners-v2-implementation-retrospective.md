# Provider plan runners v2 구현 회고

## 문서 상태

| 항목 | 값 |
| --- | --- |
| 대상 작업 | Codex/Claude plan runner thin-Superpowers-boundary v2 |
| 구현 기준 | 승인된 [설계](../superpowers/specs/2026-07-25-provider-plan-runners-thin-superpowers-boundary-design.md)와 [계획](../superpowers/plans/2026-07-25-provider-plan-runners-thin-superpowers-boundary.md) |
| 구현 기준 commit | `9049bb75465ab8ba2fdd55a5ad45b897031216d3` |
| 최종 구현 candidate | `81514db5d1480cb5ce76a859da94570c1aa8a8a0` |
| 로컬 main 병합 commit | `76c28ad8fc0a62539e8dd4b70f664d5f7523731a` |
| 회고 작성 시 main | `d427a9a6e0996546471d4012f235bf7c546c69a5` |
| 외부 provider 상태 | Claude 구독 종료로 live acceptance 미충족 |
| 릴리즈 상태 | `2.0.0` 코드와 문서는 준비됐지만 tag, publish, deploy는 수행하지 않음 |
| 원격 상태 | push와 PR 없음 |

이 문서는 제품 변경 설명인 CHANGELOG가 아니다. 구현 과정의 비용, 판단,
병목, 놓친 전제, 재발 방지책을 기록하는 운영 회고다. Claude live-provider
상태와 재개 조건의 권위 있는 기록은 별도의
[blocker ledger](./2026-07-26-plan-runner-2.0.0-claude-live-provider-blocker.md)에
있다.

## 1. 결론

구현의 기술적 방향은 옳았고 결과도 의미 있었다. Superpowers가 이미
소유하는 task, review, fix-loop 의미를 runner가 다시 저장하고 실행하던
중복 구조를 제거했다. Codex와 Claude는 독립 구현을 유지하면서 같은 v2
외부 계약을 만족했고, v1 상태는 실제 변경 없이 inspect-only로 보존했다.

그러나 실행 효율은 좋지 않았다. 4개 Task를 끝내는 데 구현 브랜치에 24개
커밋이 생겼고, 그중 17개가 `fix`였다. Task review 수정 라운드는
4 + 2 + 4 + 2회였고, 마지막 whole-branch review에서 다시 5개의 Important
finding을 고쳤다. 최종적으로 코어 runner는 크게 단순해졌지만 복잡도의
상당 부분이 2,967줄짜리 live-canary 하네스와 방대한 review evidence로
이동했다.

가장 큰 프로세스 실패는 외부 provider admission을 구현 시작 전의 독립
전제로 고정하지 않은 것이다. Claude CLI 로그인과 credential 존재는 실제
inference admission이 아니었고, 사용자는 결국 구독이 종료된 사실을
권위 있는 상태로 확인했다. 이 사실을 처음부터 release gate와 local merge
gate의 분리 조건으로 사용했다면 후반의 인증 추론, 일정 추정, release
상태 해석이 훨씬 단순했을 것이다.

따라서 다음 실행에서 유지할 핵심은 "얇은 runtime, 강한 외부 계약,
정직한 blocker"이고, 바꿔야 할 핵심은 "provider readiness의 선행 확정,
canary monolith 분해, review evidence 압축, 동시 main 변경을 고려한
integration contract"다.

## 2. 실제 결과

### 2.1 구현 결과

- Codex runner의 `engine.py`는 4,238줄에서 1,284줄로 2,954줄 줄었다.
- Claude runner의 `engine.py`는 2,771줄에서 1,879줄로 892줄 줄었다.
- 두 runner에서 task ledger, finding, finalization, final-review-fix 의미와
  관련 schema를 제거했다.
- 각 plan은 fresh root로 시작하고, recovery는 healthy root resume 1회와
  fresh-root fallback 1회로 제한했다.
- 최종 verification은 plan별 sealed declaration의 순서 보존,
  중복 제거 union으로 제한했다.
- prior handoff ancestry, protected ref, clean HEAD, receipt identity,
  author/committer identity를 fail-closed로 검증했다.
- Codex와 Claude production runtime은 서로 import하지 않는 독립 구현으로
  유지했다.
- v1 run 8개는 모두 inspect-only로 읽었고, state SHA-256, inode, size,
  mtime이 바뀌지 않았음을 확인했다.
- `2.0.0` version, CHANGELOG, README, SKILL contract와 release metadata를
  구현 branch에서 준비했다.

### 2.2 최종 검증 결과

최종 구현 candidate와 병합 결과에서 확인된 증거는 다음과 같다.

| 검증 | 결과 |
| --- | --- |
| 전체 Bun suite | 819 pass, 10 opt-in skip, 0 fail |
| Codex deterministic runner eval | 189/189 pass |
| Claude deterministic runner eval | 108/108 pass |
| Root parity | PASS |
| Cutover self-test | 97/97 pass |
| Codex live ownership | PASS |
| Codex live interruption | PASS |
| Claude live ownership | final candidate PASS 없음; 이전 candidate 시도 실패 |
| Claude live interruption | 미수행; PASS 없음 |
| Post-merge canonical verifier | exit 0 |
| Push, PR, tag, publish, deploy | 수행하지 않음 |

Claude deterministic 결과와 Codex live 결과는 Claude live success의
대체물이 아니다. 사용자의 명시적 예외는 local main 병합에만 적용됐고
provider-backed release gate를 통과시킨 것이 아니다.

### 2.3 변경 규모

구현 기준에서 최종 candidate까지:

- 24 commits
- 62 files changed
- 10,057 insertions
- 15,054 deletions
- 순감소 4,997 lines
- commit 분류: `fix` 17, `test` 3, `refactor` 2, `docs` 1, `chore` 1

순감소는 thin boundary 목표가 실제 구조 단순화로 이어졌음을 보여 준다.
다만 line count만으로 복잡도 감소를 선언할 수는 없다. 같은 기간
`plan-runner-live-canary.py`는 1,893줄에서 2,967줄로 1,074줄 늘었고,
이 파일과 테스트를 건드린 커밋만 8개였다. 코어의 복잡도가 완전히
사라진 것이 아니라 일부가 acceptance infrastructure로 이동했다.

### 2.4 시간과 실행 비용

- 첫 구현 commit: 2026-07-25 12:28:41 +09:00
- 최종 candidate commit: 2026-07-26 07:52:26 +09:00
- commit timestamp span: 19시간 23분 45초
- Goal closeout telemetry: 38,607초, 2,498,579 tokens

commit span에는 비활성 시간도 포함되므로 실제 작업 시간과 같지 않다.
반대로 Goal telemetry는 Git에서 재구성할 수 없는 실행 세션 지표다. 두
수치를 분리해 보더라도 이 작업이 단일 기능 변경치고 지나치게 비쌌다는
결론은 같다.

## 3. 실행 타임라인

| 시점 | 사건 | 평가 |
| --- | --- | --- |
| 07-25 12:28 | Codex ownership cut 첫 commit | 올바른 시작 |
| 07-25 12:44-13:34 | Task 1 review fix 4회 | 품질 향상은 컸지만 Task 범위가 너무 넓었음 |
| 07-25 14:04-14:35 | Claude parity와 recovery fix | 독립 구현 parity 확보 |
| 07-25 15:00-16:02 | public contract, hostile Git 환경, canary assertions | 보안과 이식성에 높은 가치 |
| 07-25 16:10-17:00 | live scenario orchestration와 interruption evidence | 기존 계획의 "작은 assertion 추가" 예측이 깨짐 |
| 07-25 17:10 | `2.0.0` release preparation | 사용자 요구 충족, 그러나 아직 release-ready는 아님 |
| 07-25 18:14 | final review의 Important 5건 수정 | 가장 가치 높은 review wave |
| 07-26 04:47-07:52 | auth, admission, interruption observation 후속 수정 | provider와 canary 전제의 늦은 검증 비용 |
| 07-26 11:56 | local main non-FF merge | 동시 main 변경을 보존한 안전한 통합 |
| 07-26 12:15 | unrelated CPE path-portability branch 병합 | plan runner 결과가 아니라 동시 main 변화 |

회고 작성 시 `main`이 `76c28ad8`이 아닌 `d427a9a6`인 이유는 plan runner
병합 후 별도의 CPE 작업이 병합됐기 때문이다. 이를 plan runner의
post-merge defect로 해석하면 안 된다.

## 4. 유의미했던 활동

### 4.1 TDD RED/GREEN이 실제 결함을 드러냈다

형식적인 테스트 추가가 아니었다. 다음과 같은 중요한 실패가 먼저
재현된 뒤 production fix가 들어갔다.

- invented verification digest 수용
- prior handoff ancestry 누락
- protected ref drift 수용
- hostile `GIT_*` 환경과 template hook 상속
- author/committer identity drift
- 완료된 provider 결과를 restart 시 재실행
- recovery bound를 넘는 resume
- interruption 이후 잘못된 `session_action`
- task label이 다른 plan 사이에서 충돌할 가능성

특히 hostile Git environment와 nested `git init` mutation test는 일반
happy-path 테스트가 찾기 어려운 실제 공급망/환경 격리 위험을 막았다.
이 위험들은 추상적인 가정이 아니라 직전 v1에서 실제로 관찰된
[Git identity 격리](./2026-07-24-codex-plan-runner-git-identity-isolation-incident.md),
[완료 작업 replay](./2026-07-24-codex-plan-runner-progress-replay-and-duplicate-run-incident.md),
[sandbox와 volatile ref](./2026-07-24-codex-plan-runner-sandbox-and-volatile-ref-incidents.md),
[unsealed dirty worktree](./2026-07-24-codex-plan-runner-unsealed-dirty-worktree-incident.md)
incident의 재발 방지 계약이었다.

### 4.2 최종 whole-branch review는 비용 이상의 가치가 있었다

최종 review가 찾은 5개 Important finding은 사소한 스타일 문제가 아니었다.

- exact prior-handoff ancestry
- standalone semantic `branch_handoff`
- final-union provenance
- Claude sealed Git identity
- durable one-resume-per-plan bound

이 finding들은 모두 candidate 신뢰성에 직접 영향을 줬다. 따라서
"review가 많아서 비효율적이었다"는 결론으로 축약하면 안 된다. 문제는
review 자체가 아니라 Task review에서 같은 넓은 diff를 반복해서 읽는
방식과, 핵심 invariant를 계획 초기에 테스트 행렬로 충분히 고정하지 못한
것이다.

### 4.3 실패를 성공으로 꾸미지 않았다

Claude subscription 종료를 blocker로 분류하고 다음을 지켰다.

- CLI 로그인과 Keychain credential을 admission 증거로 사용하지 않음
- failed/missing canary를 deterministic PASS로 치환하지 않음
- token, credential, raw provider transcript를 문서에 남기지 않음
- 제품 CHANGELOG와 외부 환경 blocker를 분리함
- local merge 예외 범위를 push, tag, publish로 확대하지 않음

이 정직성은 기술 구현만큼 중요하다. release evidence 체계가 신뢰를
유지한 이유다.

### 4.4 v1 inspect-only 경계를 실제로 증명했다

단순히 "수정하지 않았다"고 주장하지 않고 8개 v1 state에 대해
SHA-256, inode, size, mtime을 전후 비교했다. 마이그레이션이나 recovery
context 재사용도 하지 않았다. 호환성 경계를 말이 아니라 부작용 부재로
검증한 좋은 사례다.

### 4.5 동시 main 변경을 파괴하지 않았다

feature fork 이후 main이 크게 전진해 fast-forward가 불가능했다. 기존
main과 feature 양쪽 history를 보존하는 non-FF merge를 만들고, feature
candidate가 main의 ancestor인지 확인한 뒤 post-merge verifier를 실행했다.
force, reset, user worktree 삭제를 사용하지 않은 판단이 옳았다.

## 5. 병목과 근본 원인

### 5.1 Task가 리뷰 가능한 최소 단위보다 컸다

Task 1과 Task 3은 각각 4개의 review fix round를 사용했다. 최대 5회 제한에
거의 도달했다.

Task 1은 한 번에 다음을 함께 다뤘다.

- state/schema vocabulary 제거
- provider result 축소
- recovery semantics
- verification union
- v1 boundary
- regression coverage 복원

Task 3도 public docs, parity fixture, disposable Git identity, object format,
template isolation, nested provider Git behavior를 함께 묶었다.

이렇게 서로 다른 failure mode가 한 Task에 들어가면 reviewer가 한 finding을
고친 뒤 다른 층의 finding을 새로 발견하게 된다. 순차 fix round가 늘어난
주된 이유다.

개선:

- future Task는 "상태 계약", "recovery", "Git 격리", "public contract"처럼
  독립 invariant 단위로 나눈다.
- 한 Task가 fix round 2회를 넘거나 500줄 이상의 예상 밖 변경을 만들면
  사용자 응답을 기다리지 않고 deviation note를 기록하고 남은 범위를
  후속 Task로 재분할한다.
- 승인된 설계를 다시 여는 것이 아니라 실행 단위를 줄이는 것으로
  취급한다.

### 5.2 canary가 작은 assertion 작업이 아니라 두 번째 복잡한 시스템이 됐다

승인 계획은 기존 disposable repository와 helper를 재사용해 "missing
canary assertions only"를 추가하라고 했다. 실제로는 scenario mode 노출,
multi-plan orchestration, process-group interruption, checkpoint observation,
auth environment, admission classification까지 필요했다.

그 결과:

- canary production script가 1,074줄 증가
- 관련 commit 8개
- `interruption_boundary_not_reached` flake 1회
- 이후 interruption boundary와 observation을 위한 별도 fix 2개
- early-exit 경로의 unclosed `Popen` pipe `ResourceWarning` 잔여

이는 기존 하네스가 요구 행동을 충분히 표현한다는 계획 전제가 틀렸다는
뜻이다. 런타임 중복 제거에는 성공했지만, process orchestration 복잡도가
하나의 canary 파일에 집중됐다.

개선:

- scenario description, provider launch, process control, evidence
  normalization, acceptance validation을 별도 모듈로 분리한다.
- SIGINT 시점을 polling deadline으로 추측하지 말고 runner가 durable
  boundary marker를 기록하고 harness가 그 marker를 확인한 뒤 signal을
  보내는 acknowledgement protocol을 사용한다.
- test harness가 production workflow 의미를 소유하지 않도록 acceptance
  predicate는 fixture 기반 순수 함수로 유지한다.
- `ResourceWarning`을 정리하고 interruption deterministic stress를 release
  전 별도 bounded gate로 둔다.

### 5.3 외부 provider readiness를 너무 늦게 분리했다

Claude subscription이 끝난 상태에서는 OAuth credential 존재, Keychain
상태, `claude auth status`가 모두 실제 inference admission을 보장하지
않는다. 이 구분이 live stage에서 명시되면서 이전 ETA와 release gate
해석이 무효가 됐다.

개선된 4단계 모델:

1. executable 존재
2. credential material 존재
3. 명시적으로 승인된 auth route 존재
4. provider가 실제 inference를 admit

release acceptance는 4번만 만족해야 한다. 1-3번은 diagnostic fact일 뿐이다.

다음 Goal은 구현 시작 전에 provider readiness declaration을 남겨야 한다.
실제 subscription이 없다고 operator가 확인하면:

- deterministic implementation은 계속한다.
- provider-backed release gate는 처음부터 blocked로 표시한다.
- local merge 가능 여부는 별도 operator policy로 다룬다.
- provider availability를 전제로 한 ETA를 제시하지 않는다.
- 같은 Claude canary를 반복하지 않는다.

### 5.4 evidence 양이 판단 속도를 떨어뜨렸다

plan-scoped SDD workspace에는:

- review diff snapshot 18개
- review diff 합계 64,688 lines
- Task report와 final report 합계 1,879 lines

가 남았다. 감사 가능성은 높지만 매 round마다 큰 diff와 긴 report를 다시
읽게 해 context와 token을 소비했다. 구현 branch 전체 변경이
10,057 insertions/15,054 deletions였다는 점을 고려하면 review snapshot의
누적 line 수가 실제 최종 diff보다 훨씬 컸다.

개선:

- Git range 자체를 source of truth로 사용하고 diff 파일 복사본은 만들지
  않는다.
- review ledger에는 finding ID, severity, invariant, file/line, disposition,
  fix commit만 남긴다.
- 재검토는 전체 diff 대신 finding별 changed range와 영향 테스트만 읽는다.
- Task report는 RED, GREEN, finding disposition, residual risk만 포함하는
  150줄 이내 구조를 기본으로 한다.
- 전체 branch diff는 final review에서 한 번만 읽는다.

### 5.5 "정확히 한 번" 규칙이 실패 복구와 충돌했다

원 실행 계약은 최종 HEAD에서 live canary 두 개와 canonical verifier 한
번을 요구했다. 그러나 canary나 verifier가 실제 결함을 발견해 HEAD가
바뀌면 다음 중 하나를 선택해야 하는 모순이 생긴다.

- 다시 실행해 "한 번" 규칙을 위반한다.
- 고친 HEAD를 검증하지 않고 이전 증거를 사용한다.

이번 실행은 candidate가 바뀌면 이전 증거를 폐기하고 새 HEAD를 검증하는
정직한 쪽을 택했다. 향후 문구는 횟수가 아니라 권위 있는 증거를 정의해야
한다.

권장 문구:

> 각 mode마다 final candidate에서 성공한 authoritative run은 하나만
> 보존한다. 실패한 diagnostic run은 숨기지 않으며 candidate 또는 외부
> admission 조건이 바뀐 뒤에만 재시도한다. HEAD가 바뀌면 이전 passing
> evidence는 최종 증거가 아니다.

### 5.6 main integration 전제가 실제 worktree 상태와 맞지 않았다

실행 계약은 같은 checkout에서 main으로 전환하고 fast-forward 후 main
HEAD가 candidate와 같음을 기대했다. 실제로 main은 이미 별도 worktree에서
checkout돼 있었고, feature fork 이후 동시 작업으로 전진했다.

따라서 안전한 merge commit의 main HEAD는 candidate와 같을 수 없다. 올바른
검증은 다음이었다.

- merge commit의 두 parent가 기존 main과 candidate인지
- candidate가 merged main의 ancestor인지
- worktree가 clean인지
- post-merge canonical verifier가 통과하는지

향후 integration contract는 fast-forward만 정상 경로로 가정하지 말고
이 ancestry 기반 조건을 기본으로 가져야 한다. Task가 끝날 때마다 main
drift를 read-only로 확인하면 마지막 통합 surprise도 줄어든다.

## 6. 유의미하지 않았거나 한계효용이 낮았던 활동

### 6.1 명백히 유의미하지 않았던 것

- credential 존재를 subscription/admission 가능성의 대리 지표로 생각한 것
- 외부 provider availability를 확인하지 않은 상태에서 live stage ETA를
  추정한 것
- 같은 Git range의 큰 diff를 review round마다 파일로 복제한 것
- 최종 판단에 쓰이지 않는 긴 narrative report를 반복 확장한 것
- release metadata가 존재한다는 사실을 release readiness와 가깝게
  해석한 것

### 6.2 필요했지만 지나치게 비쌌던 것

- 독립 Codex/Claude 구현: vendor independence에는 필요하지만 모든
  invariant를 두 번 구현하고 두 번 고쳐야 했다.
- Task별 focused review: 결함을 찾았지만 Task 경계가 넓어 round 수가
  늘었다.
- canary orchestration: live evidence에는 필요하지만 한 파일에 너무 많은
  process semantics를 모았다.
- pre/post-commit 동일 suite 반복: HEAD-bound evidence에는 일부 필요하지만
  tree가 바뀌지 않은 일반 테스트까지 모두 반복하는 것은 한계효용이 낮다.

### 6.3 반복하지 않은 것이 올바른 활동

Claude subscription blocker가 확정된 뒤 같은 실제 Claude canary를
무의미하게 반복하지 않은 것은 좋은 절제였다. 미실행 evidence를 PASS로
꾸미지 않은 것도 마찬가지다. "실행하지 않음"은 이 경우 누락이 아니라
올바른 안전 결정이다.

## 7. 놓치기 쉬운 사각지대

### 7.1 Python top-level package 이름 충돌

Codex와 Claude runner는 모두 top-level package 이름 `plan_runner`를
사용한다. Task 4 evidence에서 두 focused suite를 같은 Python process에
넣으면 import module-cache collision이 발생해 별도 process로 실행해야
했다.

현재 canonical verifier가 process isolation을 지키면 문제없지만, IDE,
coverage aggregation, future monorepo test discovery, notebook import에서는
잘못된 provider module이 재사용될 수 있다.

권장:

- 단기: 모든 cross-provider 검증이 subprocess isolation을 강제하는
  regression을 유지한다.
- 장기: major version에서 package namespace를
  `kws_codex_plan_runner`와 `kws_claude_plan_runner`로 분리한다.

### 7.2 fixture 파일 이름과 내용 version 불일치

다음 파일 이름은 `v1`이지만 내용은 version 2다.

- `scripts/agent/fixtures/plan-runner-contract-v1.json`
- `scripts/agent/fixtures/plan-runner-parity-v1.json`

실제 JSON은 각각 `contract_version: 2`, `fixture_version: 2`를 가진다.
기존 경로 호환을 위해 유지한 것으로 보이지만, 미래 작업자가 v1
compatibility fixture로 오해할 수 있다.

권장:

- 현재 경로를 유지해야 한다면 파일 첫 metadata에
  `legacy_path_name: true`와 설명을 추가한다.
- 다음 breaking cleanup에서는 `*-v2.json`으로 이동하고 명시적 alias
  또는 migration test를 둔다.

### 7.3 release candidate와 released version의 구분 부족

`__version__ = "2.0.0"`과 CHANGELOG가 존재하지만 provider-backed release
gate는 미완료이고 tag/publish도 없다. 코드만 보는 소비자는 이를 이미
released된 버전으로 오해할 수 있다.

CHANGELOG에 외부 subscription incident를 섞는 것은 옳지 않다. 대신
machine-readable release evidence manifest가 필요하다.

예:

```json
{
  "version": "2.0.0",
  "candidate_head": "81514db5d1480cb5ce76a859da94570c1aa8a8a0",
  "deterministic_gate": "passed",
  "codex_live": "passed",
  "claude_live": "blocked_external",
  "publish_ready": false
}
```

이 manifest는 credential이나 transcript 없이 release operator가 현재
상태를 한 번에 판단하게 한다.

### 7.4 independent implementation의 장기 drift 비용

production code 공유를 금지한 결정은 provider independence를 지킨다.
하지만 final review에서 같은 invariant가 두 구현에서 다르게 빠진 사실은
장기 drift 위험을 보여 준다.

공유 production runtime을 만들 필요는 없다. 대신 다음은 공유해도
independence를 훼손하지 않는다.

- language-neutral external conformance vectors
- 같은 invariant ID를 가진 provider별 test matrix
- fixture generator가 아니라 literal, reviewable expected facts
- parity checker가 보고하는 "어느 provider가 어느 invariant를 놓쳤는지"
  구조화된 결과

### 7.5 local main과 remote main의 큰 거리

회고 preflight 시점의 로컬 main은 remote main보다 116 commits 앞섰다.
이번 docs commit 후에는 하나 더 늘어난다. 이는 사용자 지시인 no-push를
정확히 지킨 결과지만 다음 위험을 만든다.

- 다른 machine이나 CI는 이 구현을 볼 수 없다.
- local disk 손실 시 release candidate와 merge evidence가 사라질 수 있다.
- 나중의 push가 매우 큰 batch가 되어 review와 rollback 단위가 나빠진다.
- "main에 있다"는 표현이 local인지 remote인지 빠지면 오해가 생긴다.

현재 작업이 remote push를 승인하지는 않는다. 다만 이후 release 의사결정
시 local-only 상태를 별도 선행 조건으로 확인해야 한다.

### 7.6 canary success와 실제 장기 안정성은 다르다

ownership/interruption canary는 대표 시나리오 증거이지 다음을 보장하지
않는다.

- 긴 provider latency 분포
- OS별 signal/process-group 차이
- 네트워크 half-open
- provider가 자식 process를 detach하는 경우
- macOS 외 플랫폼
- long-running worktree에서의 disk pressure

특히 interruption은 timing-sensitive하다. 단일 PASS보다 durable boundary
marker, deterministic stress, platform matrix가 더 중요하다.

### 7.7 local ignored ledger의 보존성

SDD reports와 review diffs는 `.superpowers/` 아래 git-ignored evidence다.
이번 회고에는 유용했지만 repository clone이나 다른 machine에서는
사라진다. 반대로 전부 commit하면 transcript와 local path가 들어갈 위험이
있다.

권장 보존 경계:

- commit: bounded metrics, finding summary, final commands, residual risks
- local-only: full diffs, raw provider output, process logs, machine paths
- 금지: credential, token, raw transcript

이 회고 문서가 그 bounded summary 역할을 한다.

## 8. 다음 실행의 권장 절차

### Phase 0: authority와 환경 preflight

1. 현재 checkout, branch, HEAD, worktree owner, main owner를 확인한다.
2. main drift와 예상 integration 방식(ff 또는 merge commit)을 기록한다.
3. provider별 executable, auth route, subscription/admission declaration을
   분리 기록한다.
4. deterministic completion, local merge, provider release, remote publish
   gate를 각각 분리한다.
5. provider unavailable이면 일정 추정에서 live stage를 제외하고 blocker
   재개 조건만 기록한다.

### Phase 1: invariant matrix

구현 전에 설계를 다시 열지 말고 approved requirement를 다음 표로만
변환한다.

| Invariant | Codex test | Claude test | Parity fact | Live evidence |
| --- | --- | --- | --- | --- |
| fresh plan ownership | required | required | `session_action` | ownership |
| bounded recovery | required | required | status/action | interruption |
| Git identity | required | required | handoff identity | none |
| final union | required | required | digest/count | ownership |
| v1 inspect-only | required | required | version refusal | cutover |

이 표가 있으면 final review에서 처음 발견되는 twin-runtime 누락을 줄일 수
있다.

### Phase 2: 작은 Task와 review budget

1. state/schema cut
2. recovery/evidence cut
3. Claude independent implementation
4. parity/Git isolation
5. public docs/release contract
6. canary harness

각 Task는:

- focused RED 1회
- minimal GREEN
- self-review
- reviewer 1회
- finding fix/re-review 최대 2회

를 기본으로 한다. 2회를 넘으면 남은 finding을 별도 Task로 recut한다.

### Phase 3: canary와 release candidate

1. deterministic canary predicate를 순수 fixture test로 통과시킨다.
2. interruption boundary stress를 provider-free로 통과시킨다.
3. version metadata와 release evidence manifest를 만든다.
4. admission available provider만 승인된 횟수로 실행한다.
5. unavailable provider는 재시도하지 않고 blocker로 남긴다.
6. final candidate의 authoritative verifier를 실행한다.

### Phase 4: integration

1. main owner worktree와 branch worktree를 다시 확인한다.
2. main drift를 확인한다.
3. ff 가능하면 ff, 아니면 양쪽 history를 보존하는 merge commit을 사용한다.
4. candidate ancestry와 merge parents를 확인한다.
5. post-merge verifier를 실행한다.
6. local/remote 상태를 별도로 보고한다.
7. push, tag, publish는 별도 권한 없이는 수행하지 않는다.

## 9. 우선순위별 후속 개선

### P0 - 다음 provider-backed release 전에 필요

1. **Release evidence manifest**
   - deterministic, provider live, publish readiness를 분리한다.
   - blocker ledger를 사람만 찾는 문제를 없앤다.

2. **Canary acknowledgement boundary**
   - polling 기반 interruption timing을 durable marker 기반으로 바꾼다.
   - `ResourceWarning` cleanup을 포함한다.

3. **Cross-provider process isolation regression**
   - 두 `plan_runner` package가 같은 interpreter에 섞이지 않게 canonical
     commands를 고정한다.

4. **Integration acceptance 수정**
   - `main HEAD == candidate` 대신 ancestry, parents, clean state,
     post-merge verification을 사용한다.

### P1 - 다음 major implementation program 전에 필요

1. Task review fix round 2회 초과 시 자동 recut
2. full diff snapshot 대신 structured finding ledger
3. canary monolith를 process control/evidence/predicate로 분리
4. provider readiness declaration을 Goal preflight에 추가
5. "exactly once" 대신 "final HEAD의 authoritative passing evidence" 사용
6. Task report 길이와 evidence 종류 제한

### P2 - 유지보수 개선

1. `*-v1.json` legacy filename 정리 또는 명시적 metadata 추가
2. provider별 package namespace 분리 검토
3. local main과 remote main divergence 경고
4. provider-free interruption stress를 Linux/macOS matrix로 확대
5. 릴리즈 후 bounded retrospective metrics 자동 생성

## 10. 다음 작업에서 측정할 지표

| 지표 | 이번 값 | 다음 목표 |
| --- | ---: | ---: |
| 전체 commits | 24 | 작업 크기 축소를 통해 감소 |
| `fix` commit 비율 | 70.8% | 50% 미만 |
| Task review fix rounds | 12 | Task당 최대 2 |
| final Important findings | 5 | 0-2 |
| review diff snapshot | 18개, 64,688줄 | snapshot 0개 |
| Task/final reports | 1,879줄 | Task당 150줄 이내 |
| canary script 순증가 | +1,074줄 | 단일 파일 +500줄 미만 |
| interruption deterministic flake | 최소 1회 | 0 |
| provider readiness 확정 시점 | live stage | 구현 시작 전 |
| Goal tokens | 2,498,579 | 절대값보다 Task별 budget과 증가 원인 추적 |

목표치는 품질을 낮추기 위한 할당량이 아니다. 초과 시 설계가 틀렸다고
단정하는 대신 Task 경계, evidence 형식, harness 구조가 다시 비대해졌다는
조기 경보로 사용한다.

## 11. 최종 평가

### 유지해야 할 것

- Superpowers와 runner의 ownership 경계를 명확히 한 설계
- Codex/Claude 독립 구현과 외부 parity contract
- 실제 RED/GREEN과 hostile environment regression
- final whole-branch review
- v1 inspect-only proof
- 실패를 성공으로 바꾸지 않는 evidence discipline
- 사용자 변경과 동시 main history를 보존한 integration

### 바꿔야 할 것

- provider readiness를 확인하는 시점
- 너무 넓은 Task와 반복 review 방식
- canary 한 파일에 집중된 process orchestration
- exact-count 중심의 verification 규칙
- fast-forward만 정상으로 보는 integration 문구
- release metadata와 release readiness의 표현

### 한 문장 회고

이번 작업은 runner를 얇게 만드는 데는 성공했지만, 그 대가로 검증과
운영 절차가 두꺼워졌다. 다음 개선의 목표는 테스트를 줄이는 것이 아니라
검증 복잡도를 구조화하고, 외부 provider와 Git integration의 불확실성을
구현 시작 전에 분리하는 것이다.
