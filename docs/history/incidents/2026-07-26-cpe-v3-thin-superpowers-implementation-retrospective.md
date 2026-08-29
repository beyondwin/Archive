# CPE v3 Thin Superpowers Durability Capsule 구현 회고

## 문서 상태

| 항목 | 값 |
| --- | --- |
| 대상 작업 | CPE v3 Thin Superpowers Durability Capsule |
| 구현 계약 | 승인된 [설계](../../superpowers/specs/2026-07-25-cpe-v3-thin-superpowers-durability-capsule-design.md)와 [계획](../../superpowers/plans/2026-07-25-cpe-v3-thin-superpowers-durability-capsule.md) |
| companion 경계 | [Provider plan runners thin-Superpowers boundary](../../superpowers/specs/2026-07-25-provider-plan-runners-thin-superpowers-boundary-design.md) |
| implementation base | `9049bb75465ab8ba2fdd55a5ad45b897031216d3` |
| 시작 candidate | `82ef43adc83ae9c18029b4f5bdadb7716d5d5686` |
| 최종 candidate | `1012b5bcb3b5988b7399bd74e807fb417fde7f7f` |
| 최초 local main merge | `d66b20a45d888ddb294b2df185c88b2fc6e38533` |
| 최종 CPE fix merge | `d427a9a6e0996546471d4012f235bf7c546c69a5` |
| 회고 작성 시 local main | `1c5f38771fc1a6c0a936df9d26fe26db69991f2c` |
| 릴리즈 준비 | local v3.0.0 metadata, CHANGELOG, catalog, 22-file inventory 검증 완료 |
| 릴리즈 상태 | tag, publish, GitHub release, deploy 미수행 |
| 원격 상태 | push와 PR 없음, local main은 기록된 `origin/main`보다 118 commits 앞섬 |

이 문서는 CHANGELOG가 아니다. 구현 과정에서 실제로 지출한 시간과
검증 비용, reviewer가 발견한 결함, 잘못된 전제, 동시 작업으로 발생한
통합 비용, 다음 실행에서 줄여야 할 낭비를 기록하는 운영 회고다.

## 1. 결론

제품 결과는 성공이다. CPE는 clean-room format 5 / contract 3의 작은
durability capsule로 재구축됐고, Superpowers가 소유하는 task, review,
TDD, verification 의미를 다시 해석하지 않는다. 반복 가능한 ordered
`--document`, same-session resume, 명시적인 session missing/corrupt에만
허용되는 단 한 번의 generation fallback, mechanical `handed_off`,
legacy inspect-only, explicit worktree adoption 경계가 코드와 테스트로
고정됐다.

하지만 실행 과정은 얇지 않았다. candidate 구현에 38개 commit이 필요했고
그중 23개가 `fix`였다. post-merge correction 2개를 포함하면 merge commit을
제외한 변경 commit은 40개다. Task 1, 2, 3은 각각 5, 4, 4회의 fix round를
썼고, Task 8은 처음 완료 판정을 받은 뒤에도 whole-branch review,
canary, post-merge review에서 새로운 lifecycle defect가 연속으로 나왔다.

최종 production Python은 정확히 1,500줄이지만 eval surface는 6,575줄이다.
SDD workspace에는 Markdown 7,368줄과 review diff snapshot 25개,
32,800줄이 남았다. 제품보다 eval이 약 4.4배, bounded 운영 문서와
snapshot은 약 26.8배 크다. "thin CPE"는 달성했지만 복잡도가 사라진 것이
아니라 tests, canary, review evidence, integration procedure로 이동했다.

가장 큰 기술적 성과는 이 이동을 숨기지 않고 제품 경계를 지킨 것이다.
가장 큰 프로세스 문제는 review와 canary가 뒤늦게 invariant를 발굴하도록
Task를 구성해, 같은 범위를 여러 번 구현하고 검증한 것이다.

다음 실행에서 유지할 것은 강한 TDD와 독립 review다. 줄여야 할 것은
review 횟수가 아니라 reviewer가 처음 보는 invariant의 수, 복제되는
evidence의 양, final HEAD가 바뀔 때마다 전체 검증을 다시 시작하는
비구조화된 방식이다.

## 2. 실제 결과

### 2.1 제품 결과

- 입력은 하나의 전역 순서를 보존하는 repeatable `--document`로
  단순화됐다.
- 같은 basename 문서는 순서 기반 snapshot 이름으로 충돌 없이 보존된다.
- manifest, state, input snapshots, handoff는 bounded format 5 schema와
  immutable document bytes에 결합된다.
- run/worktree/branch/controller session/process와 마지막 Git facts만
  CPE가 소유한다.
- 기본 sandbox는 `workspace-write`이고 `danger-full-access`는 명시적이고
  immutable한 opt-in이다.
- 같은 controller session resume가 우선이며 session missing/corrupt
  관찰에만 generation 0에서 1로 fresh fallback을 한 번 허용한다.
- 일반 transport failure에는 자동 retry하지 않는다.
- engineering completion을 판정하는 `completed` 상태 대신
  mechanical `handed_off`를 사용한다.
- controller의 `completed`는 child-attested claim일 뿐이다.
- legacy format 1-4는 inspect-only다. migration command를 다시 만들지
  않았다.
- production run root는 `manifest.json`, `state.json`, `inputs/`,
  `run.lock`, 성공 시 `handoff.json`만 가진다.
- invocation receipt, event ledger, full transcript를 production
  persistence에 추가하지 않았다.
- CPE와 provider plan runner는 서로 호출하지 않는다.
- merge, push, PR, tag, publish, release, deploy 기능을 CPE에 넣지 않았다.

### 2.2 변경 규모

시작 candidate `82ef43ad`에서 최종 candidate `1012b5bc`까지:

| 지표 | 값 |
| --- | ---: |
| candidate commits | 38 |
| files changed | 42 |
| insertions | 8,006 |
| deletions | 18,203 |
| net lines | -10,197 |
| `fix` commits | 23, 60.5% |
| `feat` commits | 5 |
| `refactor` commits | 4 |
| `test` commits | 4 |
| `docs` commits | 2 |
| post-merge narrow corrections | 2 |
| CPE merge commits | 3 |

큰 순감소는 legacy authority와 중복 workflow 의미를 실제로 제거했기
때문이다. 다만 deletion 수가 크다는 사실만으로 단순성을 증명하지는
못한다. 최종 구조의 단순성은 production line ceiling, architecture
guard, forbidden-command/authority tests, live canary가 함께 증명한다.

### 2.3 최종 크기

| 표면 | 크기 |
| --- | ---: |
| production Python modules | 6 |
| production Python | 1,500 lines |
| largest module | `state.py`, 381 lines |
| `cpe.py` | 123 lines |
| `cpe_runtime/` | 1,377 lines |
| eval surface | 6,575 lines |
| eval / production ratio | 4.38x |
| SDD Markdown | 7,368 lines |
| review diff snapshots | 25 files, 32,800 lines |
| bounded SDD evidence / production ratio | 26.78x |

4.38x의 eval 비율 자체는 실패가 아니다. process lifecycle, filesystem,
Git, crash recovery를 다루는 작은 orchestrator는 happy-path 코드보다
adversarial test가 훨씬 많아야 한다. 문제는 eval의 양보다 책임 분해와
검증 선택이 구조화돼 있지 않으면 이 표면이 두 번째 제품이 된다는 점이다.

### 2.4 검증 결과

최종 local main에서:

| 검증 | 결과 |
| --- | --- |
| CPE canonical eval | 151/151 pass |
| production architecture | 6 modules, 1,500 lines, max 381 |
| Python compile | pass |
| shell syntax | pass |
| CPE-bearing root verifier | `full-offline`, 18/18 non-opt-in pass |
| latest provider docs verifier | `docs`, 3/3 pass |
| candidate whole-branch review | Critical 0, Important 0 |
| final post-merge review | Critical 0, Important 0, Minor 1 |
| remote/release mutation | 없음 |

`claude-executor-eval`과 `waygent-live-provider-smoke`는 opt-in이라 실행하지
않았다. 이는 CPE live canary 미실행을 뜻하지 않는다. CPE의 세 live
canary는 모두 실제 provider-backed run으로 완료됐다.

### 2.5 시간과 실행 비용

- 첫 implementation commit: 2026-07-25 12:36:45 +09:00
- 최종 candidate commit: 2026-07-26 09:22:11 +09:00
- candidate commit span: 20시간 45분 26초
- 최종 CPE merge: 2026-07-26 12:15:35 +09:00
- Goal telemetry: 64,047초, 약 17시간 47분
- Goal token usage: 3,044,062

commit span은 비활성 시간을 포함하고 Goal telemetry는 Git에 나타나지
않는 review, test, wait 시간을 포함한다. 어느 수치를 사용해도
1,500줄 production capsule을 만드는 운영 비용으로는 크다.

## 3. 실행 타임라인

| 단계 | 사건 | 평가 |
| --- | --- | --- |
| Task 1-3 | state, Git, controller foundation 구현 | 핵심 경계는 맞았지만 Task당 4-5 review rounds 사용 |
| Task 4-5 | initial run, resume, one fallback, legacy inspect | 제품 의미가 처음 end-to-end로 연결됨 |
| Task 6 | public CLI cutover와 legacy authority 삭제 | thin boundary를 실제 코드 구조로 고정 |
| Task 7 | operator docs와 opt-in canary harness | 필요한 작업이었지만 evidence contract가 첫 구현에서 불완전 |
| Task 8 초기 | quota/credits와 함께 canary pre-output 실패 | 외부 blocker로 보였으나 이후 비인과적임이 확인됨 |
| Task 8 fix 1-2 | Structured Outputs와 diagnostic redaction 수정 | discarded diagnostics와 secret leakage를 동시에 닫음 |
| Task 8 fix 3-5 | handed-off, run lock, stale session race 수정 | 가장 가치 높은 concurrency hardening |
| release prep | v3.0.0 metadata와 22-file inventory | 실제 release와 preparation을 분리 |
| post-release review | orphan handoff crash window 발견 | "성공 파일 작성 후 state save 전 crash"를 복구 가능하게 만듦 |
| final candidate | terminal envelope ambiguity 수정 | 1,501줄 ceiling을 한 줄 압축해 1,500으로 맞춤 |
| first merge | candidate를 `d66b20a4`로 local main에 non-FF merge | 양쪽 history 보존 |
| post-merge fix 1 | resume evidence reference containment | absolute, `..`, symlink escape 차단 |
| concurrent merge | provider runner 작업을 `76c28ad8`로 보존 | 병행 작업을 덮어쓰지 않음 |
| post-merge fix 2 | checkout path의 `verification` false positive 수정 | test-only portability correction |
| final tail | provider retrospective 두 commit 추가 | CPE tree byte-identical 확인 후 docs-scope 검증 |

## 4. 유의미했던 활동

### 4.1 TDD가 실제 security와 durability 결함을 찾았다

RED/GREEN은 형식적인 ceremony가 아니었다. 다음 결함은 production 변경
전에 deterministic failure로 고정됐다.

- undeclared input symlink alias
- requested run ID와 다른 manifest open
- symlinked or nonregular persisted state
- FIFO open이 validation 전에 block하는 문제
- worktree claim/cleanup 사이의 TOCTOU와 foreign artifact 손실
- already-reaped process leader의 stale PGID 접근
- descendant pipe로 인한 controller shutdown hang
- oversized prompt backpressure
- explicit-null terminal envelope 처리
- healthy session과 fallback transition 혼동
- handed-off run resume
- state check와 run lock 사이의 terminal transition
- generation/session advance 뒤 stale pre-lock session 재사용
- handoff publish와 terminal state save 사이 crash window
- resume evidence reference의 absolute path, `..`, symlink escape
- checkout path 문자열이 semantic verification authority로 오인되는 문제

특히 FIFO, symlink, process group, stale session race는 normal happy path
테스트가 찾기 어렵다. 이 제품의 핵심은 "일이 잘되면 실행된다"가 아니라
"crash와 hostile local state에서도 authority를 만들지 않는다"이므로,
이 테스트들은 높은 비용에도 직접적인 가치가 있었다.

### 4.2 fresh reviewer가 implementer의 시야 밖 결함을 반복해서 찾았다

가장 중요한 finding 다수는 implementer self-review가 아니라 fresh
review에서 나왔다.

- environment-prefixed secret redaction gap
- pre-lock handed-off race
- under-lock authoritative session 재계산 누락
- orphan handoff reconciliation
- evidence reference containment
- path-dependent test false positive

이는 subagent-driven development가 실제 품질을 높였다는 증거다. 반대로
같은 종류의 finding이 여러 단계에서 늦게 발견된 것은 invariant matrix가
초기에 충분하지 않았다는 증거다. 결론은 reviewer를 줄이는 것이 아니라,
reviewer가 볼 명시적 invariant와 negative-control matrix를 구현 전에
제공해야 한다는 것이다.

### 4.3 live canary가 offline tests의 blind spot을 드러냈다

첫 provider output 이전 실패는 처음에는 quota와 credits가 원인처럼
보였다. provider admission이 회복된 뒤 같은 실패가 재현되면서 실제
원인이 Structured Outputs의 required/null schema와 discarded subprocess
diagnostics라는 사실이 드러났다.

이 사건은 live canary의 가치와 위험을 동시에 보여 준다.

- 가치: 실제 provider contract가 offline fake와 다르다는 사실을 찾았다.
- 위험: 외부 quota signal과 local schema defect가 동시에 존재할 때
  상관관계를 원인으로 오인하기 쉽다.

diagnostic evidence를 보강한 뒤 세 시나리오는 최종 production commit에서
통과했다.

| 시나리오 | 최종 run | 결과 |
| --- | --- | --- |
| SDD multi-document | `cpe-b011990902b8ddab` | generation 0, handed off |
| explicit session loss | `cpe-b4f854a88ce347dd` | generation 1, fallback 1회, generation 2 없음 |
| legacy adoption | `cpe-5ea37d057c049388` | generation 0, legacy inventory 불변 |

세 handoff 모두 `integration=not_observed`였다. 이는 실패가 아니라 승인된
경계다. CPE는 engineering integration을 판정하지 않는다.

### 4.4 line budget이 production monolith를 억제했다

Task 1-3의 initial 구현은 module별 ceiling에 가까워졌고, 별도 refactor
commits가 다음 감소를 만들었다.

- `state.py`: 607에서 341줄로 축소한 뒤 최종 381줄
- `git.py`: 420에서 295줄
- `controller.py`: 446에서 330줄

이 compaction은 단순 minification이 아니라 역할 분리를 보존하면서
production budget을 되찾았다. hard maximum이 없었다면 초기 구현 위에
Task 4-8 behavior가 누적되어 450줄 이상 module이 여러 개 생겼을
가능성이 높다.

### 4.5 preservation discipline이 병행 작업 손실을 막았다

실행 중 다음 세 종류의 병행 상태가 있었다.

- modified recovery worktree 5개 파일
- source checkout의 provider-plan-runner 작업
- CPE merge 후 전진한 local main

controller는 이를 reset, stash, checkout, clean하지 않았다. provider
candidate `81514db5`는 merge `76c28ad8`로 보존됐고, recovery worktree의
HEAD와 5개 dirty paths는 digest까지 유지됐다. incident report 세 파일도
byte-for-byte 보존됐다.

이 작업에서는 "코드를 맞게 구현하는 것"과 "다른 사람의 state를 잃지
않는 것"이 같은 중요도였다. 후자를 별도 acceptance condition으로 둔
판단이 옳았다.

### 4.6 release preparation과 release를 분리했다

v3.0.0 metadata, CHANGELOG, catalog, source/install documentation,
정확한 22-file inventory를 준비했지만 tag, publish, GitHub release를
하지 않았다. release 준비가 끝났다는 사실을 release됐다는 사실로
바꾸지 않았다.

이 분리는 local-only main, opt-in gate, remote 권한 부재가 동시에 있는
상황에서 중요하다.

### 4.7 모델 effort 상한이 불필요한 escalation을 억제했다

강한 구현과 review는 우선 `gpt-5.6-sol` `xhigh`로 수행했고, `max`는
Task 8 stale-authority class가 xhigh round에서 실제로 닫히지 않았다는
증거 뒤 한 번만 사용했다. "중요한 작업이므로 max"가 아니라
"동일한 구체 작업의 xhigh 실패 증거"를 escalation 조건으로 쓴 것은
재현 가능한 운영 규칙이다.

## 5. 병목과 근본 원인

### 5.1 Task 1-3이 review 가능한 최소 invariant보다 컸다

명시적 fix round는 Task 1에서 5회, Task 2와 3에서 각각 4회였다.
state, Git, controller를 각각 한 Task로 나눈 것은 파일 경계로는
자연스러웠지만 failure mode 경계로는 너무 넓었다.

예를 들어 Task 1에는 다음이 함께 있었다.

- immutable document snapshot
- persisted schema
- run identity
- symlink/FIFO/regular-file validation
- lock lifecycle
- line budget

한 finding을 고치면 reviewer가 다른 filesystem layer의 finding을 새로
발견했다. Task는 파일이나 module이 아니라 독립적으로 증명 가능한
invariant 묶음이어야 한다.

개선:

- state schema, path object safety, file-descriptor lifecycle을 별도
  review unit으로 나눈다.
- Task가 fix round 2회를 넘으면 승인 설계를 다시 여는 대신 남은
  finding을 후속 execution slice로 recut한다.
- reviewer package에 해당 Task의 negative-control matrix를 포함한다.

### 5.2 Task 8이 모든 늦은 불확실성을 흡수하는 integration sink가 됐다

Task 8은 원래 final gates, live canary, whole-diff review를 소유했다.
실제로는 다음까지 흡수했다.

- provider admission 진단
- Structured Outputs schema
- subprocess diagnostic redaction
- handed-off lifecycle
- lock interleaving
- stale session authority
- release preparation
- orphan handoff recovery
- terminal envelope clarification
- 1,500-line ceiling repair

Task 8의 fix round 5회가 끝난 뒤에도 whole review와 canary가 두 개의
추가 product defect를 찾았다. 이는 final gate가 나빴다는 뜻이 아니라,
앞선 Task들이 "local behavior complete"만 증명하고 "assembled lifecycle
complete"를 늦게 확인했다는 뜻이다.

개선:

- Task 4 직후 initial end-to-end fake-provider lifecycle probe를 둔다.
- Task 5 직후 lock/session concurrency matrix를 실행한다.
- Task 7에서 live provider를 호출하기 전에 Structured Outputs schema를
  실제 provider validator와 동형인 offline guard로 검증한다.
- release preparation은 Task 8 내부가 아니라 runtime freeze 이후 별도
  non-production stream으로 유지한다.

### 5.3 evidence가 너무 많이 복제됐다

SDD workspace의 evidence는 다음 규모다.

- Markdown 7,368줄
- diff snapshots 25개, 32,800줄
- Task별 brief와 interface supplement
- Task reports, release report, orphan handoff report, post-merge reports

감사 가능성은 높지만 source of truth가 Git range와 report 양쪽으로
중복됐다. fresh reviewer가 매번 전체 대화는 받지 않았지만, 같은 diff를
다른 snapshot과 narrative로 반복 소비했다. 3,044,062 tokens의 상당 부분은
구현 코드보다 이 evidence 재독해와 상태 전달에 쓰였다.

개선:

- diff 파일을 복제하지 않고 immutable Git range를 evidence ID로 쓴다.
- review ledger는 finding ID, severity, invariant, file/line, fix commit,
  disposition만 기록한다.
- full narrative는 Task당 150줄을 기본 상한으로 둔다.
- exact command output은 bounded JSON receipt로 만들고 report에는 hash와
  summary만 둔다.
- full branch diff는 Task 8 whole review와 post-merge review에서만 읽는다.

### 5.4 final-HEAD canary 규칙이 반복 실행을 유발했다

retained Task 8과 post-merge reports에는 fixed legacy run을 제외하고
16개의 distinct v3 run ID가 나타난다. 일부는 diagnostic failure,
일부는 당시 final HEAD의 authoritative success였다.

HEAD가 바뀌면 이전 live pass를 최종 증거로 사용할 수 없으므로 재실행은
정직한 선택이었다. 문제는 "어떤 변경이 canary를 invalidate하는가"가
초기에 구조화돼 있지 않아 full three-scenario set를 반복한 것이다.

개선:

- canary receipt에 production scripts/templates tree digest를 저장한다.
- 변경 경로와 tree digest로 impact selection을 자동화한다.
- eval-only change는 production tree equivalence가 증명되면 canary를
  재실행하지 않는다.
- runtime/controller/schema change는 영향 scenario만 재실행한다.
- final report는 각 scenario의 마지막 authoritative success 하나와
  이전 diagnostic failures를 분리한다.

post-merge path-portability fix에서 production tree equivalence로 canary를
생략한 판단은 이 개선 모델의 좋은 예다.

### 5.5 root verifier의 실행 관찰성이 약했다

두 가지 낭비가 있었다.

1. isolated worktree에 `node_modules`가 없어 첫 root verifier가
   `tsc` unavailable, exit 127로 끝났다.
2. final `d427` verifier의 huge output과 hidden session ID 때문에
   controller가 완료 여부를 확신하지 못해 동일 immutable range의
   duplicate verifier를 하나 더 실행했다.

두 번째 실행도 자연 종료했고 결과는 green이었지만 한 번의 full-offline
suite를 불필요하게 더 돌렸다.

개선:

- verifier 시작 전에 frozen dependency availability를 preflight한다.
- missing tool은 product failure가 아니라 typed
  `verification_environment`로 보고한다.
- verifier는 stdout stream과 별개로 command, range, scope, start/end,
  exit, selected checks를 담은 atomic JSON receipt를 기록한다.
- controller는 process list나 truncated terminal output이 아니라 receipt와
  child exit status로 완료를 판단한다.
- 동일 range와 verifier version에 active/completed receipt가 있으면
  duplicate launch를 막는다.

### 5.6 exact 1,500-line ceiling이 한계에서 잘못된 최적화를 만들었다

terminal-envelope correction 뒤 production이 1,501줄이 되자 의미 변화
없이 두 줄 문장을 한 줄로 합쳐 1,500을 맞췄다. 계약은 지켰지만 이
행동은 line count가 readability보다 우선되는 gaming 신호다.

hard ceiling은 초기 monolith를 억제할 때는 유의미했다. 경계에서 한 줄
압축을 요구할 때는 한계효용이 낮았다.

개선:

- 1,500줄은 hard alert로 유지하되 20줄 이내 초과는 whole-review 승인과
  복잡도 근거로 판단한다.
- line count와 함께 function length, cyclomatic branch count, public API
  count, module responsibility를 본다.
- whitespace 압축이나 compound statement로 ceiling을 맞추는 변경은
  architecture checker가 경고한다.
- 목표는 1,350줄 이하로 운영 여유를 남기고 1,500은 emergency ceiling으로
  사용한다.

### 5.7 release contract 검증이 Markdown mini-parser로 비대해졌다

release preparation은 4회의 fix round를 썼다. false-green class는
실제였다.

- duplicate metadata
- malformed or nested HTML comments
- quoted metadata key
- inline hidden release claim
- unordered or duplicated inventory

그러나 이 문제를 Markdown parsing으로 해결하면서 release test가 또 하나의
bounded parser가 됐다. CPE production이 문서를 해석하지 않는다는 경계는
지켰지만, release tooling의 복잡도는 증가했다.

개선:

- machine-readable `release-evidence.json`을 단일 권위로 둔다.
- version, candidate HEAD, inventory, deterministic gate, live canary,
  publish readiness를 구조화한다.
- README와 CHANGELOG는 manifest에서 생성하거나 exact fact를 링크한다.
- tests는 Markdown의 모든 표현 변형을 파싱하지 않고 manifest와
  generated section의 digest를 검증한다.

### 5.8 moving main이 post-merge closeout을 반복시켰다

CPE merge 뒤 main은 다음 순서로 전진했다.

1. `d66b20a4`: original candidate merge
2. `e4624b0b`: evidence-reference fix merge
3. `76c28ad8`: concurrent provider-plan-runner merge
4. `d427a9a6`: path-portability fix merge
5. `61f4acf5`: provider retrospective 추가
6. `1c5f3877`: retrospective 용어 수정

마지막 두 commit은 CPE와 무관한 docs-only 변화였지만 "latest local main"
완료 조건 때문에 verifier와 fresh review 범위를 다시 확장해야 했다.
안전했지만 비용이 컸다.

개선:

- integration 시작 시 main owner와 짧은 merge lease를 기록한다.
- lease가 불가능하면 final CPE merge commit을 기준점으로 고정하고,
  이후 tail commit은 scope-sensitive delta review로 다룬다.
- CPE tree digest가 동일하고 tail이 docs-only이면 full whole-branch
  review를 재시작하지 않고 fresh delta reviewer 한 번으로 닫는다.
- 완료 직전 main HEAD를 두 번, 짧은 quiet window를 두고 확인한다.
- concurrent owner가 commit할 계획이면 예상 tail 범위를 먼저 공유한다.

## 6. 유의미하지 않았거나 한계효용이 낮았던 활동

### 6.1 명백한 낭비

- 동일 Git range verifier를 terminal-output 불확실성 때문에 중복 실행한 것
- 같은 diff를 25개의 snapshot 파일로 복제한 것
- 1,501줄을 의미 없는 물리적 한 줄 압축으로 1,500에 맞춘 것
- docs-only main tail마다 전체 closeout narrative를 다시 확장한 것
- 최종 판단에 직접 쓰이지 않는 intermediate run의 긴 prose를 계속
  누적한 것

### 6.2 필요했지만 비싸게 수행한 활동

- Task별 fresh review: 결함을 찾았지만 Task 범위가 넓어 round가 많았다.
- final-HEAD canary: HEAD-bound evidence에는 필요했지만 impact selection이
  늦게 정립됐다.
- full-offline root verifier: 최종 통합에는 필요했지만 dependency preflight와
  receipt가 없어 environment failure와 duplicate 실행을 만들었다.
- release contract adversarial tests: false-green을 닫았지만 Markdown
  structure를 직접 parsing하는 비용이 커졌다.
- 두 차례 final post-merge fresh review: moving main을 안전하게 따라갔지만
  CPE byte equivalence가 이미 증명된 docs-only tail에는 과했다.

### 6.3 하지 않은 것이 올바른 활동

- quota가 의심될 때 자동 retry하지 않았다.
- session missing/corrupt가 아닌 transport failure에 fresh fallback하지
  않았다.
- failed canary를 success로 재분류하지 않았다.
- legacy run을 migrate하거나 resume하지 않았다.
- protected recovery worktree를 clean/reset/stash하지 않았다.
- provider branch의 병행 변경을 CPE merge conflict 해결 재료로 사용하지
  않았다.
- tag, push, PR, publish, release, deploy를 권한 없이 수행하지 않았다.

이 항목들은 "미실행"이지만 누락이 아니라 제품 경계를 지킨 결과다.

## 7. 놓치기 쉬운 사각지대

### 7.1 canary receipt가 durable repository evidence가 아니다

최종 review 시 temporary canary roots는 filesystem에서 더 이상 발견되지
않았다. SDD report에는 run ID, session, generation, HEAD, handoff hash가
남았지만 원본 receipt를 다시 해시할 수 없었다.

현재 증거 연결은 다음에 의존한다.

- 당시 reviewer의 receipt/handoff 검증
- report에 기록된 hash
- canary production scripts/templates와 final main의 tree equivalence

이는 모순은 아니지만 독립 재감사 가능성이 약하다.

권장:

- raw transcript 없이 bounded canary evidence bundle을 별도 durable
  directory에 저장한다.
- bundle에는 run metadata, receipt/handoff hash, production tree digest,
  provider exit classification, redaction version만 넣는다.
- machine-local absolute path와 credential material은 제외한다.
- bundle retention 기간과 cleanup owner를 명시한다.

### 7.2 `handed_off`와 실제 integration 사이에는 의도적인 관찰 공백이 있다

세 canary 모두 `integration=not_observed`다. CPE가 integration을 판정하지
않는 것은 올바른 설계다. 그러나 operator가 `handed_off`를 "작업 완료"로
오해할 가능성은 남는다.

권장:

- CPE 외부의 Superpowers/controller closeout report가 handoff, review,
  merge, post-merge verification을 별도 상태로 표시한다.
- UI와 문서에서 `handed_off`를 `completed`와 같은 색이나 용어로
  표현하지 않는다.
- release evidence manifest는 CPE handoff와 engineering integration을
  별도 필드로 둔다.

### 7.3 local main은 remote main보다 118 commits 앞서 있다

no-push 계약을 정확히 지킨 결과지만 운영 위험이 있다.

- 다른 machine과 CI는 CPE v3를 볼 수 없다.
- local disk 손실 시 merge와 release-prep evidence를 잃을 수 있다.
- 이후 한 번의 push가 큰 batch가 되어 review와 rollback 단위가 나빠진다.
- "main에 병합됨"이 local인지 remote인지 빠지면 오해가 생긴다.

이 회고는 push를 승인하지 않는다. 다음 release decision은 remote
publication을 별도 one-way gate로 다뤄야 한다.

### 7.4 temporary worktree와 branch가 많이 남아 있다

완료 시점 이후에도 candidate, 두 post-merge fix worktree, 여러 detached
verification worktree, 과거 recovery worktree가 남아 있다. 일부는
forensic evidence라 반드시 보존해야 하지만 일부는 단순 verification
scratch다.

위험:

- 다음 실행이 어느 main/worktree가 authoritative한지 다시 찾는 비용
- disk와 dependency cache 누적
- 오래된 detached HEAD를 최신 결과로 오인
- branch cleanup 시 protected evidence를 함께 지울 위험

권장:

- worktree마다 `protected`, `evidence-until`, `owner`, `cleanup-safe-after`
  metadata를 별도 local registry에 기록한다.
- post-merge review 뒤 non-protected verification worktree만 bounded cleanup
  대상으로 제안한다.
- 자동 cleanup은 dirty/protected/unknown worktree를 절대 제거하지 않는다.

### 7.5 same-UID operator tampering은 threat model 밖이다

최종 reviewer의 유일한 Minor는 persisted `approval_policy`,
`integration_policy`, `remote_action_policy`가 canonical exact value가
아닌 bounded string도 허용하고, restored blocker가 normalized exact
schema가 아닌 Mapping 수준에서 먼저 수용된다는 점이다.

정상 writer는 canonical value만 쓰고 storage permission도 private라
승인 blocker는 아니다. 다만 같은 OS user 권한의 plugin, script,
operator mistake는 noncanonical state를 만들 수 있다.

권장:

- restore 시 exact enum과 blocker schema를 검증한다.
- same-UID malicious actor를 막는다고 주장하지 말고 accidental corruption
  detection으로 범위를 명시한다.
- state file signature나 encryption을 추가하기 전에 실제 threat model과
  key ownership을 먼저 설계한다.

### 7.6 `danger-full-access`는 explicit이라고 안전해지지 않는다

immutable opt-in은 silent privilege escalation을 막는다. 하지만 선택된
실행 자체의 filesystem blast radius는 여전히 크다.

권장:

- handoff와 inspect에 sandbox mode를 항상 노출한다.
- `danger-full-access` run에는 별도 operator reason과 immutable start-time
  acknowledgement를 요구한다.
- canary와 docs 예시는 `workspace-write`만 사용한다.
- future provider가 sandbox flag semantics를 바꾸면 contract probe가
  실패하도록 한다.

### 7.7 POSIX process와 filesystem semantics 의존

process group, signal, `O_NOFOLLOW`, FIFO, file mode, atomic replace에 대한
검증은 현재 macOS/POSIX 환경에서 강하다. 다음은 별도 증거가 없다.

- Windows process tree termination
- network filesystem의 rename/locking semantics
- case-insensitive path collision의 모든 조합
- unusual mount에서 symlink와 inode observation
- container/user namespace 경계

현재 제품이 POSIX-only라면 문서에 명시해야 한다. cross-platform을
약속하려면 stdlib-only라는 사실만으로 충분하지 않다.

### 7.8 provider의 session-loss 신호가 바뀔 수 있다

fresh fallback은 provider가 session missing/corrupt를 명시할 때만
허용된다. 현재 adapter와 canary는 지금의 provider behavior를 검증한다.
provider CLI가 exit code, error envelope, wording을 바꾸면 다음 두 위험이
있다.

- 실제 missing session을 ordinary transport failure로 분류해 recovery를
  거부
- ordinary error를 missing으로 잘못 분류해 fresh fallback 수행

권장:

- provider version과 capability probe를 run manifest에 기록한다.
- missing/corrupt classification을 free-form substring보다 structured
  provider signal에 결합한다.
- provider upgrade 때 contract canary를 먼저 실행한다.

### 7.9 deterministic race tests가 schedule 공간 전체를 증명하지 않는다

run lock과 stale-session tests는 발견된 interleaving을 정확히 재현한다.
하지만 가능한 모든 crash point와 process schedule을 탐색하지 않는다.

권장:

- state transition model을 순수 함수로 추출해 property/state-machine
  testing을 추가한다.
- atomic write 전후, lock 획득 전후, controller start/reap 전후 fault
  injection matrix를 유지한다.
- stress test는 deterministic seed와 bounded repetition을 기록한다.

### 7.10 same-basename의 upstream Superpowers 표현은 아직 외부 책임이다

CPE는 same-basename document bytes를 순서 기반 snapshot으로 보존한다.
그러나 upstream Superpowers workspace가 두 문서를 operator에게 어떻게
표시하고 구분하는지는 이 canary가 완전히 증명하지 않는다.

권장:

- CPE snapshot identity와 Superpowers-visible label을 혼동하지 않는다.
- upstream UI/brief가 basename만 표시한다면 ordinal과 source hash를
  같이 보여 주는 별도 개선을 한다.

### 7.11 exact release inventory는 future extension에 마찰을 만든다

22-file exact inventory는 hidden file이나 누락을 잡는다. 동시에 legitimate
file 추가가 release test failure를 만들고, 작업자가 왜 목록이 바뀌는지
모른 채 test를 업데이트할 위험이 있다.

권장:

- inventory entry마다 역할과 포함 이유를 machine-readable manifest에
  둔다.
- 파일 추가/삭제 시 version policy와 compatibility effect를 함께 review한다.
- glob으로 느슨하게 만들기보다 manifest diff를 사람이 읽을 수 있게 한다.

### 7.12 stdlib-only는 dependency risk를 줄이지만 correctness를 보장하지 않는다

외부 Python package 공급망과 설치 문제는 줄었다. 대신 JSON/schema,
locking, subprocess, path containment 같은 민감한 기능을 직접 구현한다.
stdlib-only를 단순성의 대리 지표로 사용하면 안 된다.

권장:

- 직접 구현한 security-sensitive primitive 목록을 architecture report에
  유지한다.
- standard library API라도 platform-specific behavior를 regression으로
  고정한다.

## 8. 이번 실행이 만든 잘못된 유인

### 8.1 "fix commit이 많을수록 품질이 높다"는 착시

23개의 candidate fix commit은 실제 결함을 닫았다. 동시에 initial task
brief가 충분히 세밀했다면 일부는 첫 구현에 포함될 수 있었다. fix 수는
review가 작동했다는 증거이지 실행이 효율적이었다는 증거가 아니다.

### 8.2 "production 1,500줄이면 전체 시스템도 얇다"는 착시

제품은 얇지만 eval과 evidence는 훨씬 크다. 전체 운영 복잡도는
production + eval + canary + reports + integration protocol로 봐야 한다.

### 8.3 "테스트가 모두 green이면 증거가 durable하다"는 착시

151/151과 canary pass는 behavior를 증명한다. temporary receipt root가
사라지면 나중의 auditor가 같은 증거 chain을 재구성할 수 있다는 뜻은
아니다.

### 8.4 "local main에 있으면 shipped"라는 착시

local merge는 완료됐지만 remote, CI, tag, release에는 반영되지 않았다.
local integration, remote publication, release availability를 별도 상태로
유지해야 한다.

### 8.5 "최종 review 한 번이면 충분하다"는 착시

첫 final review 뒤 orphan handoff, post-merge review 뒤 evidence path
containment이 발견됐다. final review는 강력하지만 assembled runtime과
integration environment가 바뀌면 이전 review가 보지 못한 경계가 생긴다.

## 9. 다음 실행의 권장 절차

### Phase 0: authority와 environment preflight

1. source, candidate, main, protected recovery worktree owner를 기록한다.
2. main drift 예상과 integration 방식(ff 또는 merge commit)을 기록한다.
3. Python, Bun, `tsc`, provider CLI availability를 typed preflight로
   확인한다.
4. provider executable, credential route, admission을 분리한다.
5. deterministic completion, live evidence, local merge, remote release를
   별도 gate로 둔다.
6. canary evidence retention path와 cleanup owner를 먼저 정한다.

### Phase 1: invariant matrix

승인 설계를 다시 검토하지 않고 requirement를 test matrix로 투영한다.

| Invariant | Offline RED | Concurrency/Fault | Live | Final review |
| --- | --- | --- | --- | --- |
| document byte/order | required | duplicate basename | SDD multi-doc | required |
| persisted object safety | symlink/FIFO/size | crash points | none | required |
| session continuity | state transitions | stale session | session-loss | required |
| terminal handoff | claim schema | lock/crash | all scenarios | required |
| legacy inspect-only | mutation digest | none | legacy adoption | required |
| sandbox/remote boundary | CLI/architecture | none | receipt fact | required |

이 matrix가 task brief와 reviewer package의 공통 source가 되어야 한다.

### Phase 2: Task recut

권장 execution slices:

1. format/schema와 document ordering
2. persisted object/path safety
3. Git claim/adoption/cleanup
4. controller process lifecycle
5. run/handoff atomicity
6. resume/fallback transition
7. CLI/legacy cutover
8. docs/release manifest
9. canary harness와 evidence retention
10. final gates/integration

각 slice는:

- focused RED
- minimal GREEN
- affected regression
- self-review
- fresh scoped review
- 최대 2회 fix/re-review

를 기본으로 한다. 두 번을 넘으면 남은 finding을 다음 slice로 recut한다.

### Phase 3: impact-aware evidence

1. 모든 test/canary receipt에 source tree digest를 기록한다.
2. change classifier가 production, schema, canary, eval-only, docs-only를
   구분한다.
3. production-equivalent change는 live canary를 재실행하지 않는다.
4. schema/controller change는 영향 scenario만 재실행한다.
5. final candidate에서 각 scenario의 authoritative success 하나를
   지정한다.
6. diagnostic failures는 별도 history로 보존한다.

### Phase 4: verifier receipt

root verifier는 다음 atomic receipt를 남긴다.

```json
{
  "base": "<commit>",
  "head": "<commit>",
  "scope": "full-offline",
  "verifier_version": "<digest>",
  "started_at": "<timestamp>",
  "finished_at": "<timestamp>",
  "exit_code": 0,
  "selected_commands": 18,
  "passed_commands": 18,
  "opt_in_skipped": [
    "claude-executor-eval",
    "waygent-live-provider-smoke"
  ]
}
```

이 receipt가 있으면 terminal output truncation 때문에 같은 verifier를
중복 실행할 필요가 없다.

### Phase 5: integration closeout

1. current main을 다시 읽고 merge lease 또는 expected tail을 기록한다.
2. candidate를 normal merge commit으로 통합한다.
3. merge parents, ancestry, tree preservation을 확인한다.
4. CPE-bearing range에서 full verifier를 실행한다.
5. 이후 main drift는 delta scope로 분류한다.
6. CPE tree-identical docs-only tail은 docs verifier와 fresh delta review로
   닫는다.
7. local/remote/release 상태를 세 줄로 분리 보고한다.
8. non-protected temporary worktree cleanup 후보를 기록하되 자동 삭제하지
   않는다.

## 10. 우선순위별 개선

### P0 - 다음 CPE 변경 전에

1. **Verifier atomic receipt와 duplicate suppression**
   - hidden session ID와 output truncation 문제를 제거한다.

2. **Durable bounded canary evidence bundle**
   - temporary root가 사라져도 handoff hash와 tree binding을 재감사할 수
     있게 한다.

3. **Task fix-round recut rule**
   - 2회 초과 시 파일 단위가 아닌 invariant 단위로 남은 scope를 분리한다.

4. **Release evidence manifest**
   - prepared, live-verified, locally-merged, remotely-published를 분리한다.

5. **Main drift delta protocol**
   - CPE tree equivalence가 있는 docs-only tail에 전체 review를 반복하지
     않는다.

### P1 - 다음 major durability program 전에

1. state transition property/fault-injection matrix
2. provider session-loss structured capability probe
3. exact policy/blocker restore validation
4. eval/canary modules의 responsibility 분해
5. worktree evidence registry와 retention policy
6. production target 1,350줄, hard ceiling 1,500줄로 여유 확보
7. Markdown release parser를 generated manifest 방식으로 교체

### P2 - 장기 유지보수

1. POSIX-only 지원 경계를 public docs에 명시
2. macOS/Linux process and filesystem matrix
3. same-basename Superpowers UI contract probe
4. `danger-full-access` operator reason과 audit field
5. local/remote main divergence 경고
6. non-protected verification worktree cleanup 도구

## 11. 다음 실행에서 측정할 지표

| 지표 | 이번 값 | 다음 목표 |
| --- | ---: | ---: |
| candidate commits | 38 | 25 이하를 경보 기준으로 사용 |
| candidate fix ratio | 60.5% | 45% 미만 |
| Task 1-3 fix rounds | 13 | Task당 최대 2 |
| 전체 correction waves | 약 31 | 18 이하 |
| final Important findings | 여러 단계에서 반복 | candidate whole review 0-2, post-merge 0 |
| review diff snapshots | 25개, 32,800줄 | 0개, Git range 사용 |
| SDD Markdown | 7,368줄 | Task당 150줄 이내 |
| eval / production ratio | 4.38x | 절대 감소보다 module ownership과 실행시간 추적 |
| distinct retained v3 canary runs | 16 | authoritative 3 + 필요한 diagnostics |
| duplicate root verifier | 1회 | 0 |
| environment-preflight verifier failure | 1회 | 0 |
| production budget slack | 0줄 | 최소 100줄 |
| Goal tokens | 3,044,062 | Task별 증가 원인과 evidence 비중 측정 |
| Goal elapsed | 17시간 47분 | 절대 단축보다 fix/review wait 비율 분리 |

수치는 품질을 낮추기 위한 quota가 아니다. 초과하면 review를 생략하는 대신
Task 경계, evidence 형식, canary invalidation 규칙이 다시 비대해졌다는
조기 경보로 사용한다.

## 12. 유지, 변경, 중단

### 유지

- 승인된 design/plan을 다시 해석하지 않는 실행 방식
- Superpowers와 CPE의 thin ownership 경계
- RED-first TDD
- task별 fresh independent review
- concurrency와 hostile filesystem regression
- live provider canary
- candidate whole-branch review와 post-merge review
- 병행 worktree와 incident evidence 보존
- local merge와 remote release 권한 분리
- xhigh 우선, 구체적 실패 뒤에만 max escalation

### 변경

- 파일 단위 Task를 invariant 단위 Task로 recut
- diff snapshot을 structured finding ledger로 교체
- canary를 tree-digest 기반 impact selection으로 전환
- root verifier에 dependency preflight와 atomic receipt 추가
- release docs parsing을 machine-readable manifest로 전환
- exact line ceiling을 architecture/complexity 지표와 함께 사용
- moving main을 full restart가 아닌 delta review로 처리

### 중단

- terminal output만 보고 long-running verifier 완료를 추측하는 것
- 같은 immutable range verifier를 중복 실행하는 것
- final 판단에 쓰이지 않는 narrative를 계속 확장하는 것
- receipt가 temporary root에만 있는데 durable evidence라고 표현하는 것
- local merge, release preparation, release publication을 한 상태로 묶어
  말하는 것
- 외부 quota signal 하나로 pre-output failure의 원인을 확정하는 것

## 13. 최종 평가

이번 작업은 CPE를 얇게 만드는 데 성공했다. 더 중요한 성공은 얇음을
위해 durability, security, recovery 증거를 생략하지 않았다는 점이다.
symlink, FIFO, process group, stale session, lock interleaving, crash window,
evidence path escape까지 닫은 결과는 실제 운영 가치가 있다.

동시에 실행 방식은 아직 얇지 않다. 1,500줄 제품을 완성하는 데 40개의
변경 commit, 약 31개의 correction wave, 6,575줄 eval, 40,000줄이 넘는
bounded SDD evidence, 300만 tokens가 필요했다. 이것을 "철저해서 당연한
비용"으로 정당화하면 다음 실행도 같은 패턴을 반복한다.

다음 개선의 목표는 test나 review를 줄이는 것이 아니다. invariant를 더
일찍 고정하고, evidence를 복제하지 않고, final HEAD 변화가 어떤 증거를
무효화하는지 기계적으로 판단하며, verifier와 canary가 스스로 durable
receipt를 남기게 만드는 것이다.

한 문장으로 요약하면:

> CPE 제품은 얇아졌지만 실행과 증거 시스템은 두꺼워졌다. 다음 단계는
> 품질을 줄이지 않고 그 두께를 구조화하는 것이다.
