# 결정 로그 — ADR 교차 인덱스

이 스킬의 모든 실험에서 만들어진 Architecture/Design Decision Record (ADR) 의 평탄 인덱스. ADR은 부모 실험 디렉터리(`docs/experiments/<version>-<name>/decisions/D###-<slug>.md`) 안에 살고 있는데 *국지적으로 의미가 있기* 때문입니다 — 그렇지만 "채점에 대해 어떤 설계 선택을 했나?" 같은 가로지르는 질문에 답하긴 어렵습니다.

이 파일이 그 가로지르는 뷰입니다. 사용 용도:

- 현재 설계를 설명하는 ADR 찾기 (행마다 링크).
- 어떤 대안이 검토되었는지 보기.
- 어느 실험이 그 결정을 만들었는지 찾기.
- 결정이 재검토 / 번복되었는지 감사.

---

## v2.7 — Quality-mode 실험 (종료; `quality_plus` 는 부정 결과, 루브릭 인프라는 긍정)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Floor level](../docs/experiments/v2.7-quality-mode/decisions/D001-floor-level.md) | 비교용 v2.6.0 베이스라인 floor 설정 위치 | **결정** |
| [D002 Judge model](../docs/experiments/v2.7-quality-mode/decisions/D002-judge-model.md) | LLM-as-judge용 Sonnet vs Opus | **결정**: Opus + rubric.py 하이브리드 |
| [D003 Rubric runner](../docs/experiments/v2.7-quality-mode/decisions/D003-rubric-runner.md) | 결정론적 정확성 측정 인프라 | **결정**: rubric.py |
| [D004 Pilot scope](../docs/experiments/v2.7-quality-mode/decisions/D004-pilot-scope.md) | 파일럿용 rep 수 + 픽스처 수 | **결정**: baseline-variance probe 먼저 |
| [D005 Experimental branch](../docs/experiments/v2.7-quality-mode/decisions/D005-experimental-branch.md) | 실험용 브랜치 전략 | **결정** |
| [D006 Pilot first](../docs/experiments/v2.7-quality-mode/decisions/D006-pilot-first.md) | 풀 실험 빌드 전 파일럿 | **결정**: 파일럿 우선; 1.5일+ 절약 |
| [D007 Fixture realistic spec](../docs/experiments/v2.7-quality-mode/decisions/D007-fixture-realistic-spec.md) | 픽스처 난도 증폭 멈추기 | **결정**: 멈추기, 확증 편향 회피 |
| [D008 quality_plus SKILL changes](../docs/experiments/v2.7-quality-mode/decisions/D008-quality-plus-skill-changes.md) | best-of-3 + judge용 SKILL.md 150줄 변경 | **설계됐지만 출하 안 됨** — F002 ceiling 이 죽임 |

**v2.7 마감**: [F002-close-out.md](../docs/experiments/v2.7-quality-mode/findings/F002-close-out.md) 참조. `quality_plus` 가설에서 부정 결과 (가장 어려운 픽스처에서 marginal gain 0.05, 표면 면적에 비해 가치 없음). 루브릭 인프라는 main으로 출하.

## v2.8 — 학습 로그 (출하, 풀 픽스처 smoke PARTIAL)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Initial design](../docs/experiments/v2.8-learning-log/decisions/D001-initial-design.md) | 실행별 샤드 레이아웃, run_id 포맷, 헬퍼 서브커맨드, 범위 | **결정** + 4개 advisor-patch 수정 (Q4 단일 작성자, Q5 모든 종료 경로 close-run, Q6 Resume Chain 핸드오프, Q7 두 smoke 픽스처) |

**v2.8 마감**: [F001-smoke.md](../docs/experiments/v2.8-learning-log/findings/F001-smoke.md) 참조. Smoke A 클린 PASS; Smoke B 가 멀티 태스크 계획에서 오케스트레이터 준수 갭 폭로. v2.8.1 후속이 갭을 닫음.

## v2.8.1 — Step 7.5 강제 (출하, n=4 검증)

실험 서브디렉터리 없음 — 이건 HISTORY.md 항목과 인라인 근거로 직접 출하된 경험적 수정. 결정 본체는 v2.8.1 HISTORY.md 항목과 `4afca2e` 커밋 메시지에 살아 있음.

| 변경 | 이유 |
|------|------|
| Step 7.5 헤딩을 MANDATORY 로 승격 | Smoke B에서 advisory 표현이 선택사항으로 읽혔음 |
| `LEARNING_LOG_INIT:` 마커를 양쪽 경로에서 발산 | 사후 준수 감사 신호 |
| 헬퍼 호출에서 `2>/dev/null` 제거 | 스크립트 깨졌을 때 헬퍼 stderr 노출 |
| `evals/run.sh` 가 픽스처별로 마커 grep | 준수가 측정 가능한 속성이 됨 |
| `check_skill_contract.py` 의 18번째 계약 체크 | MANDATORY 표현을 자리에 고정 |

## v2.9 — Reviewer Spec Coverage Walk (출하 2026-05-14)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Initial design](../docs/experiments/v2.9-reviewer-spec-coverage/decisions/D001-initial-design.md) | single-pass walk vs 멀티 관점 디스패치; omc 7-아이템 shortlist 에서 증거 선택; **§Q3 critical post-advisor-pre-check patch** — 메타 규칙용 적대적 생성 추가 | **결정** |

**v2.9 findings**:
- [F001-T4.5-dry-run.md](../docs/experiments/v2.9-reviewer-spec-coverage/findings/F001-T4.5-dry-run.md) — 1-rep 파일럿; walk 메커니즘 PASSED, 실패 모드 이동 (silent miss → spec 모호성 노출)
- [F002-T5-n4-results.md](../docs/experiments/v2.9-reviewer-spec-coverage/findings/F002-T5-n4-results.md) — v2.8.1 + 명확화된 스펙 + v2.9 프롬프트 아래 n=4 reps; 네 개 통과 기준 모두 만족; SHIP

## v2.12 — Implementer 모델 선택 (출하 2026-05-15)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Hold Reviewer on Sonnet](../docs/experiments/v2.12-implementer-opus-vs-sonnet/decisions/D001-hold-reviewer-on-sonnet.md) | Reviewer/Verifier 도 Opus 로 올려야 하는가 vs Sonnet 고정 | **결정**: Sonnet 고정 — judge consistency 가 implementer 품질 향상 효과를 흐림 |
| [D002 Record used and default](../docs/experiments/v2.12-implementer-opus-vs-sonnet/decisions/D002-record-used-and-default.md) | `state.implementer_model` 필드 모양 — string 만 vs `{used, default}` 객체 | **결정**: `{used, default}` 객체로 contemporaneous default 보존; A/B 분석시 baseline 식별 가능 |

## v2.13 — Natural multi-plan (출하 2026-05-15)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 NL lexicon scope](../docs/experiments/v2.13-natural-multi-plan/decisions/D001-nl-lexicon-scope.md) | 자연어 키워드 lexicon 의 보수성 — open vs closed set | **결정**: closed 4-키 lexicon (opus/sonnet/순차/대화형 + 동의어) + 한국어 particle 분리 알고리즘; 확장은 ADR 필수 |
| [D002 Plan chain schema](../docs/experiments/v2.13-natural-multi-plan/decisions/D002-plan-chain-schema.md) | 멀티 플랜 state shape — top-level 평탄화 vs `plan_chain[]` 배열 | **결정**: `plan_chain[]` 배열 + `active_plan` integer pointer; v2.12 legacy `plan2_state` 는 schema 감지로 호환 |

---

## 가로지르는 결정 (한 실험 아래에 속하지 않음)

### 오케스트레이터-워커 패턴 (vs 단일 세션)

[`../ARCHITECTURE.md`](../ARCHITECTURE.md) §2 + §11 에 문서화. v2.4.0 에서 기원. 선택: Opus 오케스트레이터 + Sonnet 서브에이전트가 계획 실행에 대한 Anthropic 가이드와 일치. 단일 세션 대비 트레이드오프: 더 좋은 병렬성, 서브에이전트당 fresh 컨텍스트, 토큰 비용 증가.

### 실행별 샤딩 학습 로그 (vs 단일 `events.jsonl`)

ADR: v2.8 D001 §Question 1. 기원: v2.8 설계 라운드 3에서 사용자 피드백. 선택: 실행별 디렉터리 레이아웃이 `flock` 없이 동시 쓰기 경합 제거. 빈 실행도 `meta.json` 을 부정 신호로 남김.

### 학습 로그 헬퍼의 단일 작성자 계약

ADR: v2.8 D001 §Q4 (advisor-patch). 기원: 출하 전 advisor 리뷰가 서브에이전트들이 `MAE_LEARNING_RUN_ID` 로 헬퍼 호출하면 Agent 툴 디스패치(env 전파 X)와 `claude -p` 서브프로세스(POSIX env 작동)를 혼동한다는 걸 잡음. 선택: 서브에이전트는 JSON 후보를 쓰고, 오케스트레이터가 유일한 호출자.

### 모든 종료 경로에서 `close-run`

ADR: v2.8 D001 §Q5 (advisor-patch). 기원: 원 설계는 Phase 2 에서만 `close-run` 호출. ESCALATE / 훅 거부 / 하드 크래시는 `meta.outcome=unknown` 을 영구히 남김. 선택: 명시적 close-run — success (Phase 2), blocked (ESCALATE / state-write 실패), aborted (user/hook). 하드 크래시 → `unknown` 은 정직.

### Spec Coverage Walk 의 메타 규칙 적대적 생성

ADR: v2.9 D001 §Q3. 기원: pre-advisor self-check 가 초기 "strict-template enumeration only" 설계로는 픽스처 08의 `30m20m` 케이스 (스펙의 메타 규칙으로만 커버됨)를 노출 못한다는 걸 잡음. 선택: walk가 두 ordered sub-step; sub-step B 가 메타 규칙당 ≥3 적대적 입력 명시적 요구.

### Step 7.5 의 MANDATORY 표현 (v2.8.1)

HISTORY.md v2.8.1 항목에 문서화된 경험적 결정. 기원: F001-smoke.md 의 Smoke B 가 SKILL.md 가 지시했음에도 47개 Bash 호출 중 0개가 헬퍼를 부르지 않았음을 보임. 선택: 더 강한 prose + 가시 마커 + eval 수준 준수 체크. 훅 기반 강제는 v2.10+ 으로 연기 ([`deferred-candidates.md`](./deferred-candidates.md) §Hooks).

---

## 번복 / 대체된 결정들

| 원 결정 | 대체 | 이유 |
|---------|------|------|
| v2.8 Step 7.5 "advisory" 표현 (`2>/dev/null \|\| echo ""`) | v2.8.1 MANDATORY 표현 + 마커 | Smoke B 에서 경험적 준수 회귀 |
| v2.8 D001 초기 "서브에이전트가 env로 헬퍼 호출" | v2.8 D001 §Q4 단일 작성자 계약 | advisor 가 env 전파 모호성 잡음 |
| v2.8 D001 초기 "Phase 2 에서만 close-run" | v2.8 D001 §Q5 모든 종료 경로 close-run | advisor 가 `outcome=unknown` 회귀 잡음 |
| v2.9 D001 초기 "strict-template enumeration only" | v2.9 D001 §Q3 enumeration + 적대적 생성 | pre-advisor self-check 가 `30m20m` 케이스 enumeration 단독으로 노출 안 됨 잡음 |
| v2.7 D008 `quality_plus` 설계 | (출하 안 됨) | F002 ceiling 결과: marginal gain 이 구현 표면 면적 가치 못 미침 |

## ADR 추가 방법

새 ADR은 부모 실험 디렉터리 안에:
```
docs/experiments/v2.X-<name>/decisions/D00N-<short-slug>.md
```

[`_template/decisions/D000-template.md`](../docs/experiments/_template/decisions/D000-template.md) 를 출발점으로 사용. 표준 섹션: Context · Options · Decision · Rationale · Consequences · Links.

그 다음 이 파일의 해당 섹션 (v2.X 표) 에 행을 추가해서 가로지르는 검색으로 찾을 수 있게 함.

실험을 가로지르는 *cross-cutting* 결정 (예: 오케스트레이터-워커 패턴)은 위 "가로지르는 결정" 섹션에 추가, 본체를 담고 있는 ARCHITECTURE.md 섹션 또는 HISTORY.md 항목 포인터와 함께.
