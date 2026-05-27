# v2.19 — Token Cost Optimization (퀄리티 우선 비용 절감)

**Status**: In progress — analysis phase (2026-05-27 시작)
**Branch**: TBD (제안 단계)
**Production baseline**: v2.18.0 (`SKILL.md` frontmatter)

## Goal

`kws-claude-multi-agent-executor` 의 한 실행당 토큰 비용을 **퀄리티 게이트를 깎지 않는 범위에서** 의미 있게 줄인다. 평가 기준은 두 가지:

1. **비용 지표**: `state.cost_ledger.totals` 의 input / cache_read / cache_write / output 토큰 합계 — 픽스처 셋(`evals/fixtures/`)에서 베이스라인 대비 절감률.
2. **퀄리티 게이트**: `evals/baselines/` 의 `spec_compliance`, `correctness`, `code_quality` 점수가 기존 baseline(v2.8.1) 대비 **드롭하지 않을 것**. 어떤 최적화든 게이트 하락이 관측되면 즉시 롤백.

## Hypothesis

현재 비용 구조의 상당 부분은 **퀄리티에 기여하지 않는 캐시-비친화적 구조**에서 발생한다. 구체적으로:

- `SKILL.md` 가 단일 파일 72k 토큰으로, Phase 전환과 무관하게 오케스트레이터 컨텍스트 prefix를 점유.
- 서브에이전트 시스템 프롬프트가 dispatch 간 비트단위 일치하지 않아 같은 wave 내 fan-out 캐시 hit 손실.
- 서브에이전트가 `state.json` 을 Read tool로 직접 읽어 라운드트립과 컨텍스트 비대를 동시에 발생.

이 셋을 손보면 **퀄리티 게이트를 건드리지 않고 input/cache_read 토큰을 30~60% 절감 가능**할 것으로 기대.

## Status / quick links

- [JOURNAL.md](./JOURNAL.md) — 작업 시계열 로그
- [findings/F001-skill-md-size-analysis.md](./findings/F001-skill-md-size-analysis.md) — SKILL.md 크기/분할 분석
- [findings/F002-cache-mechanics.md](./findings/F002-cache-mechanics.md) — Anthropic prompt cache 동작 팩트체크
- [findings/F003-subagent-cache-fanout.md](./findings/F003-subagent-cache-fanout.md) — 서브에이전트 fan-out 캐시 친화성 분석

## Phase status

| Task | Status | Notes |
|------|--------|-------|
| T0 — 캐시 동작 팩트체크 (대화 기반) | Done | F002 |
| T1 — 현 비용 구조 분석 (SKILL.md / 프롬프트 템플릿 검증) | Done | F001, F003 |
| D001 — SKILL.md 분할 경계 결정 | Draft | `decisions/D001-skill-md-split-boundary.md` |
| D002 — Extended cache (1h) 적용 범위 | Draft | `decisions/D002-extended-cache-applicability.md` — SDK 노출 조사 필요 |
| D003 — 서브에이전트 state.json Read 폐지 | Adopted | `decisions/D003-subagent-state-read.md` — fallback 유지 |
| T2 — 베이스라인 토큰 측정 스크립트 정비 | Done | `scripts/cost_report.py` + `scripts/run_ablation.sh` 작성. 실행은 사용자 (API 비용 발생) |
| T1.2 — 서브에이전트 slice injection PoC | Done | `references/implementer-prompt.md` + `SKILL.md` Phase 1 Step 1 변경. `CONTEXT_SOURCE` 출력 필드 추가 |
| T1.1 — Phase -1 reference 추출 PoC | Done | `references/phases/phase-minus-1-args-and-spawn.md` (411줄) 신설. SKILL.md 2,188→1,859줄 (-15%) |
| T1.1 (cont.) — Phase 0/1/Transition/2 추출 | Pending | 같은 패턴으로 phase 단위 분리 |
| T1.1 (cont.) — Cross-cutting 추출 (state-schema, agentlens, hooks) | Pending | |
| T5 — Orchestrator 1h extended cache 적용성 조사 | Pending | D002 종속 |
| T6 — 측정 / 픽스처 ablation | Pending | 사용자 트리거 필요 |
| T7 — 퀄리티 게이트 회귀 확인 | Pending | T6 완료 후 |

## Decisions index

- D001 — SKILL.md 분할 경계: Phase + Cross-cutting 하이브리드 — [link](./decisions/D001-skill-md-split-boundary.md) (Draft)
- D002 — Extended cache (1h TTL) 적용 범위 — [link](./decisions/D002-extended-cache-applicability.md) (Draft, SDK 노출 조사 필요)
- D003 — 서브에이전트 state.json Read 폐지 + fallback 유지 — [link](./decisions/D003-subagent-state-read.md) (Adopted)

## Findings index

- F001 — SKILL.md 크기 분포와 슬림화 기회 — [link](./findings/F001-skill-md-size-analysis.md)
- F002 — Anthropic prompt cache 동작 메커니즘 (팩트체크 결과) — [link](./findings/F002-cache-mechanics.md)
- F003 — 서브에이전트 dispatch의 캐시 친화성 진단 — [link](./findings/F003-subagent-cache-fanout.md)

---

## 1. 배경 — 캐시 동작 모델 (요약)

Anthropic prompt cache의 서버측 키는 다음 셋으로 결정된다:

```
(API key, model, prefix 토큰 시퀀스 + cache_control breakpoint 위치)
```

**중요한 사실**:

- `session_id` 는 서버측 캐시 키에 포함되지 않는다. Claude Code 클라이언트가 디스크에 대화 히스토리를 이어붙이기 위한 로컬 식별자일 뿐.
- 캐시 hit은 prefix 토큰이 **비트단위로 동일** 해야 발생. 한 토큰만 달라도 그 지점부터 뒷쪽 전부 miss.
- 기본 TTL 5분. 마지막 hit으로부터 5분 이내에 같은 prefix가 재요청되면 hit.
- Extended TTL 1시간 옵션 존재 — write 비용 2배, 그 외 read 가격은 동일.
- Cache_control breakpoint는 호출당 최대 4개 배치 가능.

**상호작용 결과**:

- 인터랙티브 터미널 세션은 **prefix가 append-only로만 자라고** 턴 간격이 보통 5분 안에 들어오므로 캐시 hit ratio가 높다.
- `claude -p` 헤들리스는 (a) SessionStart 훅이 동적 컨텍스트(시간 스탬프, git status)를 prefix 앞부분에 주입하여 prefix가 드리프트, (b) 호출 간격이 5분을 자주 초과하므로 hit ratio가 낮다.
- 서브에이전트(Task 툴 spawn)는 **완전히 새로운 대화** 다 — 자체 system prompt, 자체 tool set, 빈 message history로 시작. 메인 에이전트의 warm cache가 전이되지 않는다. 같은 역할의 서브에이전트를 5분 안에 여러 번 spawn하면, **시스템 프롬프트가 byte-identical인 한** 두 번째 spawn부터 cache hit이 가능하다.

자세한 검증 및 잘못된 통설(예: "터미널이 TTL을 더 살린다") 정정은 [F002](./findings/F002-cache-mechanics.md) 참조.

---

## 2. 현 구조의 비용 핫스팟

### 2.1 SKILL.md (단일 최대 비용원)

- 현재 크기: **2,188줄 / 175KB / ~72k tokens**
- Phase 0 셋업, Phase -1 NL 인자 파서, 멀티플랜 chain 스키마, AgentLens 이벤트 emit 사이트, 안전 훅 정의 등이 한 파일에 박혀있음.
- 오케스트레이터 세션 동안 매 턴 prefix 일부로 로드됨. 캐시 hit해도 cache_read 가격(write의 1/10)은 발생.
- 한 태스크 사이클(Phase 1) 실제로 능동 참조되는 영역은 ~10–15k 토큰. 나머지 ~55k는 점유만 함.

영향 추정:

| 시나리오 | 세션당 SKILL.md 비용 (대략) |
|---|---|
| 50턴 / cache hit ratio 80% / Opus | input(20%) $0.22 + cache_read(80%) $0.86 = **~$1.08** |
| 50턴 / cache hit ratio 20% (드리프트 잦은 경우) | input(80%) $0.86 + cache_read(20%) $0.22 + cache_write ≈ **~$1.50+** |

50태스크 plan + 멀티 phase 합쳐 한 run 평균 200~500 턴을 가정하면 SKILL.md만으로 **$4–10/run** 수준. 상세는 [F001](./findings/F001-skill-md-size-analysis.md).

### 2.2 서브에이전트 dispatch의 cold start

- 한 태스크 사이클당 Implementer + Combined Reviewer 최소 2회 cold start. MID/HIGH는 Verifier 1회 추가.
- 각 cold start는 system prompt + tool defs + Required Skills 블록을 **풀가격 input**으로 지불.
- 같은 wave 내 병렬 Implementer N개를 spawn해도 시스템 프롬프트에 `{implementer_model}` 등 변수가 박혀있어 prefix가 비트단위로 같지 않을 수 있음 → 두 번째부터의 cache hit 기회 손실.

상세 진단은 [F003](./findings/F003-subagent-cache-fanout.md).

### 2.3 서브에이전트의 `state.json` Read

`references/implementer-prompt.md` L52~57:

> Read `{orch_dir}/state.json`. Resolve which task tree applies to you using this rule (v2.13):
> - `state.plan_chain` exists (multi-plan) → active tree is `state.plan_chain[state.active_plan]`...

매 dispatch마다:
1. Read tool 호출 (라운드트립 latency).
2. state.json 전체가 컨텍스트 진입 — multi-plan run에서는 수 KB.
3. 서브에이전트가 active tree 판별 로직을 재실행 (오케스트레이터가 이미 결정한 정보).

오케스트레이터 시점에서 active 슬라이스를 user message에 inject하면 위 세 비용 모두 제거 가능.

### 2.4 Reviewer 디프 인젝션

`references/reviewer-prompt.md` 는 diff를 user message에 통째로 inject. LARGE 태스크에서 1000줄+ diff면 5k+ 토큰. SPEC_COVERAGE_WALK가 디프 정확성에 의존하므로 절감 여지 작지만, 임계값(예: 500줄) 초과 시 헤더+hunk만 inject하고 reviewer가 필요 시 Read하도록 전환 가능.

---

## 3. 제안 — 우선순위별 최적화

### Tier 1 (높은 절감, 무손실)

#### T1.1 SKILL.md 슬림화 (최우선)

**현재**: 단일 파일 72k 토큰.

**제안 구조**:

```
SKILL.md (~8–10k tokens, 엔트리포인트)
├── Path layout
├── Phase 라이프사이클 요약 (한 줄짜리)
├── Output 포맷 + 안전 가드
├── state.json 핵심 필드만 (전체 스키마 X)
└── "Phase N 진입 시 references/phase-N.md 를 Read하라" 지시

references/phases/
├── phase-minus-1-args.md      ← NL 파서, 멀티플랜 자동 감지
├── phase-0-setup.md           ← worktree, hooks, ambiguity gate, baseline, plan review
├── phase-1-task-cycle.md      ← Implementer/Reviewer/Verifier dispatch 절차
├── phase-1-parallel-subflow.md ← P2 병렬 sub-worktree
├── phase-1-spec-edit-branch.md ← P15 spec contradiction 처리
├── phase-2-finalization.md    ← 배치 verify, docs, 최종 리포트
├── state-schema.md            ← state.json 전체 스키마 (v2.13 plan_chain 포함)
├── multi-plan-chain.md        ← plan_chain handoff, Resume Chain
└── agentlens-emit-sites.md    ← v2.17 cutover 후 4개 emit + candidate drain
```

오케스트레이터는 Phase 전환 시점에 해당 reference를 Read tool로 로드. 한 phase 동안 그 reference는 컨텍스트 안에서 캐시 친화적으로 유지되고, 다음 phase 진입 시 자연 노화됨.

**리스크**:
- Phase 경계가 모호한 일부 절차(예: candidate drain은 Phase 0/1/2 전반에 걸쳐 발생) → `references/agentlens-emit-sites.md` 처럼 cross-cutting reference 별도 유지.
- 절차 일관성 — 분할 시 같은 정보가 두 파일에 중복되면 안 됨. 단일 소스 원칙 엄격 적용.

**예상 절감**: 세션당 input/cache 토큰 **40–60%**.

#### T1.2 서브에이전트 user-msg slice injection

`implementer-prompt.md` / `reviewer-prompt.md` 에서 "Read state.json" 지시를 제거하고, 오케스트레이터가 dispatch 시점에 필요한 슬라이스를 user message에 직접 inject.

**변경 전**:
```
## Context from Previous Tasks
Read `{orch_dir}/state.json`. Resolve which task tree applies...
```

**변경 후 (오케스트레이터가 inject)**:
```
## Context from Previous Tasks (pre-resolved)
deps_for_this_task: [3, 5]
task_3.for_next_tasks: |
  <요약 텍스트>
task_5.for_next_tasks: |
  <요약 텍스트>
shared_files:
  src/foo.py: [task_3, task_5]
```

**리스크**:
- 오케스트레이터의 inject 로직 버그 시 서브에이전트가 컨텍스트 없이 동작 → state.json fallback Read 옵션을 명시적으로 남길지 결정 필요(D003).

**예상 절감**: 태스크당 Read 라운드트립 1회 + state.json 토큰. 50태스크 plan 기준 ~50k 토큰 + latency.

### Tier 2 (중간 절감, 인프라 의존)

#### T2.1 Orchestrator 1h Extended Cache

오케스트레이터 세션이 30분 이상 지속되는 경우가 일반적이므로, 시스템 프롬프트 + 툴 정의 + 슬림화된 SKILL.md prefix에 1시간 TTL 적용. 손익분기: ~6분.

**선행 조사 필요**: Claude Code / Agent SDK 가 호출자에게 `cache_control.ttl` 설정을 노출하는지 확인. 노출 안 되면 SDK 이슈 제기 대상.

#### T2.2 서브에이전트 system prompt 정규화

`implementer-prompt.md` 의 시스템 부분에서 변수(`{implementer_model}`, `{decisions_register}` 등) 를 user message로 이동. 시스템 프롬프트가 모든 dispatch에 byte-identical하면 같은 wave 내 fan-out 캐시 hit 가능.

상세 분석: [F003](./findings/F003-subagent-cache-fanout.md).

### Tier 3 (제한적 절감, 신중 적용)

#### T3.1 Reviewer 디프 인젝션 사이즈 캡

- 임계값 (잠정): 500줄 초과 시 헤더+hunk 메타데이터만 inject.
- 절감 추정: LARGE 태스크에서 디프당 2–5k 토큰.
- 리스크: SPEC_COVERAGE_WALK 정확도 하락 → MID/LOW에는 적용 안 함, LARGE에만.

#### T3.2 Candidate drain emit 묶음 처리

Phase 1 Step 3.5 의 candidate drain은 현재 매 사이클 스텝 후 디렉터리 스캔. 빈 디렉터리 스캔도 토큰 비용 발생. 컴팩션 포인트나 명시적 boundary로 묶을 수 있음. 단 AgentLens 가시성 지연 트레이드오프 있음.

---

## 4. 절대 건드리지 않을 것 (퀄리티 게이트)

다음은 비용이 들더라도 유지:

| 항목 | 유지 이유 |
|---|---|
| SPEC_COVERAGE_WALK (v2.9, reviewer) | parse_duration 류 fixture에서 75% miss rate 잡는 메커니즘 — F002 of v2.9 |
| METHOD_AUDIT lines (v2.11) | TDD/verification 디시플린 위조 차단 |
| 3회 재시도 캡 | 무한 burn 방지 |
| MID/HIGH per-task Verifier | 회귀 검출 최후 방어선 |
| Safety hooks (Pre/PostToolUse, SubagentStop) | 토큰 비용 무관, 안전 핵심 |
| Opus 오케스트레이터 | 사용자 모델 선호도 (memory: feedback_model_preferences) |
| Combined Reviewer 통합 (분할 X) | 분할 시 cold start 2배 = 비용 오히려 증가 |
| LOW 태스크의 Reviewer 유지 | LOW도 spec drift 발생 가능 — Reviewer 스킵은 위험 |

## 5. 검토 보류 (퀄리티 영향 큰 불확실 항목)

- LOW 태스크 Reviewer 스킵 — drift 회귀 분석 선행 필요
- Sonnet 4.6 orchestrator 실험 — 사용자 선호 충돌
- Docs Updater 컴팩션 빈도 — 메인 컨텍스트 슬롭 리스크 있음

---

## 6. 측정 계획

### 6.1 베이스라인 캡처 (T2)

1. `evals/run.sh` 를 픽스처 4–5개에 대해 현재 v2.18 그대로 실행.
2. 각 run의 `state.cost_ledger.totals` 를 `scripts/accumulate_cost.py` 로 집계.
3. 역할별 (orchestrator / implementer / reviewer / verifier / docs) 토큰 breakdown 표 작성.
4. 같은 픽스처의 `evals/baselines/v2.20.0-pre-opt.json` 으로 spec/correctness 점수 캡처.

### 6.2 변경별 ablation

각 Tier 1 / Tier 2 변경을 개별 브랜치로 적용 후 같은 픽스처 재실행. 변경 전후 비교 표:

```
픽스처 / 변경       | input | cache_read | cache_write | output | spec_score | correctness
v2.18 (baseline)   | ...
+ T1.1 (slim SKILL)| ...
+ T1.2 (slice inj) | ...
+ T2.1 (1h cache)  | ...
```

### 6.3 게이트

- spec_compliance 점수가 baseline 대비 -0.05 이상 하락 → 해당 변경 롤백
- correctness 점수가 baseline 대비 -1 케이스 이상 회귀 → 롤백
- code_quality 는 -0.10 까지 허용 (주관적 축)

## 7. 다음 단계

1. 이 README + findings 문서 리뷰 (사용자 승인 완료, 2026-05-27)
2. T2 (베이스라인 측정) 먼저 — 변화 측정 인프라 없이 진행하면 ROI 평가 불가
3. T1.2 (slice injection) PoC — 변경 작고 안전, 측정 검증용으로 적합
4. T1.1 (SKILL.md 슬림화) PoC — 가장 큰 절감 기대, 가장 큰 구조 변경

---

## 출처 / 검증 컨텍스트

- 캐시 메커니즘 분석은 사용자와의 2026-05-27 대화에서 진행됨 (F002 참조). 결론은 1차 자료(Anthropic API 문서 + 관측된 동작)와 일치.
- 비용 추정치는 v2.18 SKILL.md byte 수 + Anthropic 공식 가격표 기준. 실측은 T2 베이스라인에서 확정.
- 이 문서 자체는 코드 변경이 아니라 **분석 + 제안**. 실제 변경은 T3 이후 별도 PR.
