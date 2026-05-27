# D001 — SKILL.md 분할 경계: Phase 기준 + Cross-cutting 보조

**Status**: Draft (사용자 검토 대기)
**Date**: 2026-05-27
**Context**: v2.19 T1.1 (SKILL.md 슬림화) 실행 직전 결정

## 결정

SKILL.md를 다음 두 축으로 분할한다:

1. **Phase 축** — `references/phases/phase-<N>-<topic>.md` — 라이프사이클 phase 단위 절차서
2. **Cross-cutting 축** — `references/cross-cutting/<topic>.md` — phase 전반에서 참조되는 공통 도메인

SKILL.md 본문에는 **엔트리포인트 + 분기 규칙 + 안전 게이트** 만 남기고, 상세 절차는 phase reference에 위임한다.

## 고려한 대안

### Option A — Phase 단위 단일 축 분할

```
references/
├── phase-minus-1-args.md
├── phase-0-setup.md
├── phase-1-task-cycle.md
├── phase-2-finalization.md
```

장점: 가장 단순. 오케스트레이터가 phase 진입 시 1개 파일만 Read.
단점: AgentLens emit, state.json 스키마, 멀티플랜 chain 같은 cross-cutting 콘텐츠가 여러 phase 파일에 중복 등장. **단일 소스 원칙 위반 → 유지보수 함정**.

### Option B — 기능 단위 분할 (cross-cutting만)

```
references/
├── state-schema.md
├── agentlens-events.md
├── parallel-subflow.md
├── spec-edit-branch.md
```

장점: 중복 없음.
단점: 한 phase 진행 동안 N개 reference를 Read해야 함 → 라운드트립 증가, 캐시 거동 예측 어려움.

### Option C (채택) — Phase + Cross-cutting 하이브리드

```
references/
├── phases/
│   ├── phase-minus-1-args.md          # NL 파서, Self-Spawn
│   ├── phase-0-setup.md               # worktree, hooks, ambiguity gate, baseline, plan review
│   ├── phase-1-task-cycle.md          # Implementer/Reviewer/Verifier dispatch 순차 (정상 경로)
│   ├── phase-1-parallel-subflow.md    # P2 병렬 sub-worktree (cross-phase 예외 처리)
│   ├── phase-1-spec-edit-branch.md    # P15 spec contradiction (특수 분기)
│   ├── phase-transition.md            # T1~T3 컴팩션, Resume Chain handoff
│   └── phase-2-finalization.md        # 배치 verify, docs, final report
└── cross-cutting/
    ├── state-schema.md                # v2.13 plan_chain 포함 전체 JSON 스키마
    ├── multi-plan-chain.md            # plan_chain 동작, active_plan 해상도
    ├── agentlens-emit-sites.md        # v2.17 cutover 후 4 emit + candidate drain (phase 전반)
    ├── safety-hooks.md                # PreToolUse/PostToolUse/SubagentStop
    └── decisions-register.md          # v2.15 C2 decision consistency 메커니즘
```

원칙:
- 한 phase의 정상 경로는 phases/phase-N.md 한 파일에서 끝낸다.
- 특수 분기(병렬, spec edit)는 같은 phase 그룹의 별도 파일로 분리해 normal-path 가독성 보존.
- cross-cutting 도메인(state schema, agentlens, hooks)은 단일 소스로 cross-cutting/.
- phase reference에서 cross-cutting 콘텐츠를 인용해야 할 때는 1줄 링크만 남기고 본문 중복 금지.

장점: 단일 소스 원칙 + phase별 cache locality 둘 다 충족.
단점: 두 디렉터리 구조로 약간의 인지 부하 — 다만 prefix가 명확(`phases/` vs `cross-cutting/`)해서 혼동 적음.

## SKILL.md 엔트리포인트에 남길 콘텐츠

목표 크기: 8~10k tokens

- `## Path layout` (worktree / orch_dir 정의)
- `## Active-tree resolution` (v2.13 `<active>` 해상도 — 모든 read/write의 관문)
- `## Phase 라이프사이클 요약` (Phase -1 → 0 → 1 → Transition → 2 한 페이지)
- `## Phase 진입 규칙` — "Phase N 시작 시 `references/phases/phase-N.md` 를 Read하라"
- `## Cross-cutting 참조` — "AgentLens emit 시 `cross-cutting/agentlens-emit-sites.md` 참조" 등 분기 규칙
- `## Output 포맷 통일` — 최종 사용자 요약 리포트 형식
- `## 안전 게이트` — halt 조건, ESCALATE 카테고리 enum
- `## 호출 인자 요약` — 인자 종류 한 표 (상세는 phase-minus-1-args.md)

## 마이그레이션 순서 (T1.1 PoC)

1. **Phase -1 추출 먼저** (가장 자기완결적, 의존성 적음) — 파일 1개 추출 후 픽스처 1개 회귀 측정
2. Phase 0 추출 (셋업) — 12 step, 큰 절감 기대
3. Phase 1 정상 경로 추출
4. Phase 1 특수 분기 (parallel, spec-edit) 추출
5. Phase Transition 추출
6. Phase 2 추출
7. Cross-cutting 5개 추출
8. SKILL.md 엔트리포인트 최종 정리

각 단계마다 회귀 픽스처 1~2개 실행 권장 (cost 발생 — 사용자 승인).

## 관련 결정

- D002 — 1h extended cache 적용은 슬림화와 무관하게 가능. 두 변경의 효과는 독립적이므로 병렬 진행 가능.
- D003 — 서브에이전트 state.json Read 폐지 (T1.2)는 SKILL.md Phase 1 dispatch 절차 변경을 동반 → T1.2와 T1.1 phase-1 추출 작업이 같은 영역을 건드림. T1.2 먼저 적용 후 T1.1 phase-1 추출하는 것이 충돌 적음.

## 미해결 / 사용자 확인 필요

- 위 디렉터리 트리(phases/, cross-cutting/) 구조가 OK인지
- references/ 직접 하위에 평탄하게 두는 것을 선호하는지 (기존 `references/implementer-prompt.md` 등이 평탄 구조라 일관성은 평탄이 좋을 수도)
