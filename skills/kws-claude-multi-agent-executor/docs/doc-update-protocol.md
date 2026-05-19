# 문서 갱신 프로토콜

변경을 출하할 때 *정확히* 어떤 문서를 건드릴지 알려주는 변경 종류별 체크리스트. 목표: 누가 "뭘 갱신해야 하지?" 를 기억하지 않아도 문서가 최신 유지 — 프로토콜이 알려줍니다.

이 파일은 인지 보조; [`../evals/check_doc_freshness.py`](../evals/check_doc_freshness.py) 가 자동화된 가드 (이 프로토콜이 건너뛰어졌어도 가장 회귀되기 쉬운 드리프트 잡음).

더 넓은 기여 프로토콜은 [`../AGENTS.md`](../AGENTS.md) 참조.

---

## 목차

- [빠른 조회: 어떤 변경 타입인가?](#빠른-조회)
- [변경 타입별 상세 체크리스트](#상세-체크리스트)
- [신선도 eval — 자동화된 것](#신선도-eval)
- [실제 예시들](#실제-예시들)

---

## 빠른 조회

| 변경 대상 | 필수 갱신 | 상세 |
|-----------|-----------|------|
| 스킬 동작 (SKILL.md 편집) | SKILL.md 버전 + README + HISTORY + ARCHITECTURE | [스킬 동작](#스킬-동작-변경) |
| 서브에이전트 프롬프트 | references/<role>-prompt.md + 구조 변경 시 check_skill_contract.py + ≥50줄 시 실험 기록 | [서브에이전트 프롬프트](#서브에이전트-프롬프트-변경) |
| 헬퍼 스크립트 | scripts/compare_agentlens_events.py (rename contract + --self-test) + 스키마 변경 시 references/learning-log.md (v2.17 cutover: append_learning_event.py / check_learning_log.py 제거됨) | [헬퍼 스크립트](#헬퍼-스크립트-변경) |
| 학습 로그 이벤트 타입 추가 | [extend-event-type.md](./how-to/extend-event-type.md) 의 5곳 모두 | [이벤트 타입 추가](#이벤트-타입-추가) |
| Eval 픽스처 추가 | evals/fixtures/<N>.yaml + baselines/v<X>.json + 필요 시 HISTORY 항목 | [픽스처 추가](#픽스처-추가) |
| 새 리스크 발견 | docs/risks-and-limitations.md (항상) + 액션 연기 시 deferred-candidates 에 추적 | [리스크 발견](#리스크-발견) |
| 알려진 리스크 종결 | docs/risks-and-limitations.md (CLOSED 로 이동) + 출하된 수정이면 HISTORY 항목 | [리스크 종결](#리스크-종결) |
| 설계 결정 | docs/experiments/<v>/decisions/D###-*.md + decision-log.md 인덱스 행 | [설계 결정](#설계-결정) |
| 후보 연기 | docs/deferred-candidates.md (재방문 기준과 함께 추가) | [후보 연기](#후보-연기) |
| 버전 번프 (어떤 버전이든) | SKILL.md frontmatter + README + HISTORY + snapshots/ (minor+) | [버전 번프](#버전-번프) |
| 새 실험 | docs/experiments/v<X>-<name>/ + docs/experiments/README.md 인덱스 + HISTORY §3 행 | [새 실험](#새-실험) |
| 실험 종결 | finalize findings/ + JOURNAL 마감 + HISTORY §3 행 갱신 + 출하 시 decision-log | [실험 종결](#실험-종결) |
| 메이저 리팩터 / 재구조화 | 위 모든 것 + docs/snapshots/ 의 새 스냅샷 | [메이저 리팩터](#메이저-리팩터) |
| 자명한 수정 (오타, 포매팅) | 그냥 커밋. 문서 갱신 없음. | [자명한 변경](#자명한-변경) |

---

## 상세 체크리스트

### 스킬 동작 변경

**정의**: 런타임 의미를 바꾸는 `SKILL.md` 편집 (단계 스텝, 디스패치 로직, 채점 임계, 에스컬레이션 라우팅).

**필수 갱신**:

- [ ] `SKILL.md` — 편집 자체 + frontmatter `metadata.version` 번프
- [ ] `README.md` — 현재 버전 라인
- [ ] `skills/README.md` — Archive 수준 스킬 인벤토리가 변경된 경우만
- [ ] `HISTORY.md` §1 — 새 버전 항목: 무엇이 변경됐나, 왜, 무엇이 테스트됐나, 무엇이 변경 안 되고/연기됐나
- [ ] `ARCHITECTURE.md` — 변경에 영향받는 섹션 동기화 (AGENTS.md "ARCHITECTURE.md sync (REQUIRED on behavior changes)" 규칙)
- [ ] 계약 관련이면: 새 동작을 고정하는 체크로 `evals/check_skill_contract.py` 확장

**선택이지만 권장**:
- [ ] ≥50줄 또는 가설 있으면 실험 기록
- [ ] 마이너 버전 번프면 `docs/snapshots/v<X>.md` 스냅샷 파일

### 서브에이전트 프롬프트 변경

**정의**: 어떤 `references/<role>-prompt.md` 편집.

**필수 갱신**:

- [ ] 프롬프트 파일
- [ ] `evals/check_skill_contract.py` — 변경이 주장된 토큰에 영향이면 (예: `Skill(...)` 호출 추가/제거, 출력 포맷 변경) 계약 체크 확장
- [ ] `references/learning-log.md` — 프롬프트의 후보 발산 계약이 변경된 경우

**선택**:
- [ ] HISTORY.md 항목 — 사용자 가시 동작 변경 시
- [ ] 실험 기록 — 비자명한 경우 (예: v2.9.0 Spec Coverage Walk)

### 헬퍼 스크립트 변경

**정의**: `scripts/compare_agentlens_events.py` (legacy → `kws-cme.*` rename 계약 + `--self-test`) 편집. v2.17 cutover에서 `scripts/append_learning_event.py` 와 `evals/check_learning_log.py` 는 제거되었으므로 더 이상 갱신 대상이 아닙니다.

**필수 갱신**:

- [ ] 스크립트 자체 (`--self-test` 케이스 포함)
- [ ] `references/learning-log.md` — 이벤트 타입/페이로드 스키마 변경 시 (cutover 이전 헬퍼 호출 예시는 *historical diagnostic procedures* 로 보존; 새 동작 가이드는 AgentLens emit 사이트로 작성)
- [ ] `ARCHITECTURE.md` §14 — 발산 사이트 또는 candidate-drain 흐름이 바뀐 경우

**선택**:
- [ ] HISTORY.md 항목 — 사용자 가시면
- [ ] 실험 기록 — 스키마 깨는 경우

### 이벤트 타입 추가

[`how-to/extend-event-type.md`](./how-to/extend-event-type.md) 의 완전한 단계별 사용.

**필수 (4곳)** — v2.17 cutover 이후 AgentLens 단독 싱크:

- [ ] `references/learning-log.md` — 스키마 문서
- [ ] `evals/check_skill_contract.py` — `EVENT_TYPES` 리스트
- [ ] `scripts/compare_agentlens_events.py` — legacy → `kws-cme.*` rename 계약 + `--self-test` 케이스
- [ ] 적어도 하나의 `references/<role>-prompt.md` — 발산자 (서브에이전트면 후보 JSON; 오케스트레이터면 `agentlens event append` 직접 호출)

### 픽스처 추가

[`how-to/add-a-fixture.md`](./how-to/add-a-fixture.md) 의 완전한 단계별 사용.

**필수**:

- [ ] `evals/fixtures/0N-<slug>.yaml` — 픽스처
- [ ] `evals/baselines/v<current>.json` — 캡처된 첫 실행 베이스라인
- [ ] 스펙 vs 루브릭 감사 (숨은 가정 없음)

**선택**:
- [ ] `evals/README.md` — 포맷 문서 변경 시 인덱스 갱신
- [ ] HISTORY.md 항목 — 버전과 함께 출하 시

### 리스크 발견

**필수**:

- [ ] `docs/risks-and-limitations.md` — 상태, 표현, 완화, 추적 포인터와 함께 새 항목 추가
- [ ] 리스크가 연기된 액션 필요면: 재방문 기준과 함께 `docs/deferred-candidates.md` 에도 추가

### 리스크 종결

**필수**:

- [ ] `docs/risks-and-limitations.md` — 항목을 "Closed/resolved" 섹션으로 이동, `verified by` 링크와 함께
- [ ] `HISTORY.md` 항목 — 종결이 버전 번프의 일부로 출하된 경우

### 설계 결정

**필수**:

- [ ] `docs/experiments/<v>/decisions/D###-<slug>.md` — ADR 자체
- [ ] `docs/decision-log.md` — 실험 섹션에 행 추가
- [ ] 결정이 이전 ADR 을 번복하면: decision-log.md 의 "Overturned" 표도 갱신

### 후보 연기

**필수**:

- [ ] `docs/deferred-candidates.md` — 제안된 변경, 기원, 연기 이유, 재방문 기준 (구체적 트리거) 와 함께 섹션 추가

**선택**:
- [ ] 이전 결정을 대체하면 `docs/decision-log.md` overturned 표

### 버전 번프

패치 / 마이너 / 메이저 번프 어느 것이든:

**필수**:

- [ ] `SKILL.md` frontmatter `metadata.version`
- [ ] `README.md` 현재 버전 라인
- [ ] `skills/README.md` — Archive 수준 인벤토리 변경 시만
- [ ] `HISTORY.md` §1 — 새 항목

**마이너+ 번프 (예: 2.8 → 2.9)**:
- [ ] `docs/snapshots/v<X>.md` — 출하 시점 전체 상태 스냅샷

**메이저 번프 (예: 2.X → 3.0)**:
- [ ] 위 모두 + HISTORY.md 에 migration 노트

### 새 실험

**필수**:

- [ ] `docs/experiments/v<X>-<name>/{README.md, JOURNAL.md, decisions/, findings/}` — `docs/experiments/_template/` 에서 생성
- [ ] `docs/experiments/README.md` — 인덱스 표에 행 추가
- [ ] `HISTORY.md` §3 — 실험 행 추가 (상태, 링크)

### 실험 종결

**필수**:

- [ ] `docs/experiments/<v>/findings/F00N-<close-out>.md` — 최종 findings 문서
- [ ] `docs/experiments/<v>/JOURNAL.md` — outcome, 배운 것, 잔여 리스크와 함께 마감 섹션
- [ ] `docs/experiments/<v>/README.md` — 상태 필드 CLOSED 와 outcome 으로 갱신
- [ ] `docs/experiments/README.md` — 인덱스 상태 갱신
- [ ] `HISTORY.md` §3 — 실험 행 갱신
- [ ] 출하된 변경: "스킬 동작 변경" 체크리스트도 수행
- [ ] 결정 번복: decision-log.md Overturned 표 갱신

### 메이저 리팩터

복합 변경으로 다루기: 위 모든 관련 체크리스트 + 추가로:

- [ ] 새 상태 캡처하는 새 `docs/snapshots/v<X>.md` 추가
- [ ] 아직 안 했으면 v<X>-refactor 실험 기록 열기
- [ ] 커밋 전 풀 preflight + 적어도 2 픽스처 reps 실행

### 자명한 변경

오타, 공백, 포매팅, 주석 수정:

- [ ] 그냥 커밋. 문서 갱신 불필요.

자명한지 확실치 않으면 → 자명한 게 아님. 위 중 하나 적용.

---

## 신선도 eval

[`../evals/check_doc_freshness.py`](../evals/check_doc_freshness.py) 가 가장 회귀되기 쉬운 드리프트를 결정론적으로 체크:

1. **버전 일치** — `SKILL.md` frontmatter 버전이 스킬 README 의 현재 버전 라인과 일치.
2. **내부 markdown 링크** — 모든 ``[text](./path.md)`` 또는 ``[text](../path.md)`` 참조가 존재하는 파일로 해결.
3. **HISTORY.md 항목 존재** — 현재 `SKILL.md` 버전에 대해 `HISTORY.md` §1 에 일치하는 항목.
4. **최신 스냅샷 존재** — 현재 마이너 버전 (예: 2.9.0 에 대해 2.9.X) 에 대해 `docs/snapshots/v2.9.0.md` 존재.
5. **결정 로그가 ADR 인덱싱** — `docs/experiments/*/decisions/` 하위 모든 D### 파일이 `docs/decision-log.md` 에 나타남.
6. **Stale 마커** — `docs/` 와 `references/` 하위 `TODO`, `FIXME`, `XXX`, `WIP:` 카운트. 카운트 보고; 실패시키지 않음.

Eval 은 **기본적으로 비차단**: 드리프트 보고하고 exit code 0 으로 `evals/run.sh` 가 계속. 차단으로 만들려면 하네스 실행 전 shell 에서 `DOC_FRESHNESS_STRICT=1` 설정.

독립 실행:

```bash
python3 evals/check_doc_freshness.py
# 또는 strict 모드로
DOC_FRESHNESS_STRICT=1 python3 evals/check_doc_freshness.py
```

---

## 실제 예시들

### 예시 1 — 사용자가 "Reviewer 프롬프트 오타 수정" 요청

- `references/reviewer-prompt.md` 편집.
- 자명한 변경. 커밋. 문서 갱신 없음.

### 예시 2 — 사용자가 "Step 7.5 를 필수로 승격" 요청 (실제 v2.8.1)

스킬 동작 변경. 체크리스트:

- [x] `SKILL.md` Step 7.5 편집됨
- [x] Frontmatter 버전 2.8.0 → 2.8.1
- [x] `README.md` 현재 버전 라인 번프
- [x] `HISTORY.md` §1 v2.8.1 항목 추가 (무엇 + 왜 + verified-by 포함)
- [x] `evals/check_skill_contract.py` 18번째 체크 추가
- [x] `evals/run.sh` 준수 마커 grep 추가 (eval 이 계약 인접)
- [x] `docs/risks-and-limitations.md` "★★ Adherence" 완화 갱신
- [x] 실험 기록 불필요 (경험적 수정, 인라인 근거)
- [x] 스냅샷 불필요 (패치 번프, 마이너 아님)

### 예시 3 — 사용자가 "동시성 엣지 케이스 픽스처 추가" 요청

픽스처 추가. 체크리스트:

- [ ] 결정 감사: 측정된 증거 있나?
- [ ] 있으면: `evals/fixtures/09-concurrency-edge-cases.yaml` 작성
- [ ] Preflight + 첫 실행; 베이스라인 캡처
- [ ] 스펙 vs 루브릭 감사
- [ ] 커밋
- [ ] 선택: 비자명한 설계면 실험 기록 열기

### 예시 4 — 사용자가 "`subagent_dispatched` 이벤트 타입 추가" 요청

이벤트 타입 추가. [`how-to/extend-event-type.md`](./how-to/extend-event-type.md) 사용:

- [ ] `references/learning-log.md` — 스키마 문서 갱신 (이제 11개 이벤트 타입)
- [ ] `evals/check_skill_contract.py` — `EVENT_TYPES` 리스트 확장
- [ ] `scripts/compare_agentlens_events.py` — 새 타입의 legacy → `kws-cme.*` rename 케이스 + `--self-test`
- [ ] 적어도 하나의 `references/<role>-prompt.md` — 발산자 연결 (후보 JSON 작성 또는 orchestrator `agentlens event append` 호출)
- [ ] 버전 번프 (스키마 확장이므로 마이너)
- [ ] HISTORY.md 항목
- [ ] 마이너 번프면 스냅샷

---

## 프로토콜이 틀렸을 때

이 프로토콜은 휴리스틱입니다. 다음 상황을 발견하면:

- 사용자 가시 동작 변경 없이 버전 번프 — 프로토콜이 너무 처방적; 번프 떨어뜨려.
- 다음 메이저 리팩터까지 읽히지 않을 문서 갱신 — 프로토콜이 노이즈 강제; 요구사항 다운그레이드.
- "분명해 보여서" 스텝 건너뛰기 — 그게 프로토콜이 일하는 모습; 건너뛰지 마.

마찰이 너무 높으면: 완화 + 근거와 함께 이 파일 수정하는 PR 열기. 문서 프로토콜은 신성하지 않음; 도구임.
