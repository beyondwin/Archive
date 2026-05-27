# F001 — SKILL.md 크기 분포 및 슬림화 기회

**일시**: 2026-05-27
**대상**: `skills/kws-claude-multi-agent-executor/SKILL.md` v2.18.0

## 측정값

```
$ wc -l SKILL.md
2188 lines

$ wc -c SKILL.md
175097 bytes

추정 토큰: ~72,000 (175KB / 2.4 bytes/token)
```

비교 — 같은 디렉터리의 다른 문서:

| 파일 | 라인 | 바이트 |
|---|---|---|
| `SKILL.md` | 2,188 | 175,097 |
| `ARCHITECTURE.md` | 410 | (작음) |
| `AGENTS.md` | 178 | (작음) |
| `references/learning-log.md` | 481 | 20,558 |
| `references/reviewer-prompt.md` | 224 | 14,164 |
| `references/implementer-prompt.md` | 195 | 11,619 |
| `references/plan-reviewer-prompt.md` | 178 | 7,549 |
| `references/escalation-playbook.md` | 114 | 7,030 |
| `references/verifier-prompt.md` | 125 | 5,670 |
| `references/docs-updater-prompts.md` | 138 | 4,986 |
| `references/best-of-n-judge-prompt.md` | 101 | 3,280 |
| `references/common-mistakes.md` | 17 | 1,339 |

**SKILL.md 단독으로 references/ 전체 합의 약 2.5배.**

## 컨텐츠 분포 (Phase 단위 헤딩 기준 추정)

`SKILL.md` 의 주요 섹션과 추정 토큰 비중 (육안 + 라인 수 기반):

| 섹션 | 추정 비중 | 한 사이클당 능동 참조? |
|---|---|---|
| Path layout / Active-tree resolution | ~3% | 항상 |
| Phase -1 (Mode selection + NL 파서 + Self-Spawn) | ~12% | 시작 시 1회만 |
| Phase 0 (셋업: 12 step) | ~25% | 시작 시 1회만 |
| Phase 1 (태스크 사이클) | ~30% | 매 태스크 |
| Phase Transition (T1~T3) | ~5% | 컴팩션 시점만 |
| Phase 2 (마무리) | ~8% | 종료 시 1회만 |
| Multi-plan chain (v2.13 plan_chain 스키마) | ~8% | multi 일 때만 |
| AgentLens emit (v2.17 cutover) | ~5% | 모든 emit site |
| state.json 전체 스키마 + 기타 | ~4% | 참조 시점만 |

**Phase 1 한 태스크 사이클을 도는 동안 실제 의사결정에 능동 참조되는 영역은 ~30–35%** 추정. 나머지 ~65–70%는 컨텍스트에 상주만 함.

## 슬림화 시나리오 비용 모델

가정:
- Opus orchestrator
- 한 run 평균 200~500 턴 (50태스크 plan, MID/HIGH 비율 50%)
- Anthropic 가격 (2026 기준 추정):
  - Opus input: $15 / MT
  - Opus cache_read: $1.50 / MT (input의 1/10)
  - Opus cache_write: $18.75 / MT (input의 1.25배)

### 현 구조 (단일 72k SKILL.md)

세션 첫 턴: 72k × $15/MT = **$1.08 cache_write** (1회)
이후 캐시 hit 가정 (5분 안 새 턴 발생): 72k × $1.50/MT = **$0.108 / 턴**

300턴 가정 시:
- Write 1회 (또는 5분 만료 시 재write — 평균 5회 가정): 5 × $1.08 = $5.40 amortized
- Read 295회: 295 × $0.108 = $31.86
- **SKILL.md 소계: ~$37 / run**

(주: 실제 Claude Code/Agent SDK가 어떤 cache_control을 자동 박는지에 따라 달라짐. 위는 단순 시나리오.)

### 슬림화 후 (10k 엔트리포인트 + Phase별 reference 온디맨드)

- 엔트리포인트 10k: 300턴 × $0.015 = $4.50
- Phase reference 평균 동시 점유 ~8k (Phase 진입 시 Read, 종료 시 노화):
  300턴 × $0.012 = $3.60
- **SKILL.md 소계: ~$8 / run**

**예상 절감: ~$29 / run (~78%)** — 다만 위는 상한 추정. 실측은 T2에서.

## 슬림화 분할 경계 (잠정)

### Phase 기준 분리

```
references/phases/
├── phase-minus-1-args.md          (~7k tokens)
├── phase-0-setup.md               (~15k)
├── phase-1-task-cycle.md          (~18k)
├── phase-1-parallel-subflow.md    (~5k)
├── phase-1-spec-edit-branch.md    (~3k)
├── phase-transition.md            (~3k)
└── phase-2-finalization.md        (~5k)
```

### Cross-cutting reference

```
references/cross-cutting/
├── state-schema.md                (~5k)  — v2.13 plan_chain 포함
├── multi-plan-chain.md            (~4k)
├── agentlens-emit-sites.md        (~3k)  — Phase 전반에서 참조
└── safety-hooks.md                (~2k)
```

### SKILL.md 엔트리포인트 (~8–10k tokens)

다음만 유지:

- Path layout (변하지 않음, 모든 단계서 참조)
- Phase 라이프사이클 한 페이지 요약
- "Phase N 시작 시 references/phases/phase-N.md를 Read" 지시
- Output 포맷 통일 규칙
- 안전 게이트 (어떤 경우 ESCALATE / halt)
- state.json `active_plan` 결정 로직 (모든 read/write가 거쳐가는 관문)

## 리스크 / 주의

1. **Phase 경계가 흐릿한 절차**: AgentLens emit은 Phase 0/1/Transition/Phase 2 전반에서 발생. cross-cutting reference로 빼되 SKILL.md 엔트리에서 "어느 phase reference도 AgentLens emit 시 cross-cutting/agentlens-emit-sites.md를 참조" 명시.
2. **중복 위험**: Phase reference 간 내용 중복 시 단일 소스 원칙 깨짐. 모든 cross-cutting을 cross-cutting/ 로 강제.
3. **Read 오버헤드**: Phase 전환 시 Read tool 호출 1회 추가. 그러나 reference 1개 = 5~18k tokens 한 번만 cache_write 하면 phase 동안 계속 cache_read 가격으로 활용 가능 → 순 절감 압도적.
4. **버전 관리**: SKILL.md frontmatter `metadata.version` 외에 reference 파일들의 버전을 어떻게 추적할지 — `ARCHITECTURE.md` 와 동일하게 git으로 충분할 듯.

## 다음 액션

- T3 PoC 시작 전 D001 결정: 위 분할 경계가 맞는지, 다른 축(기능 단위 등)이 더 나은지 비교 검토.
- 분할 후 `evals/run.sh` 픽스처 1개로 token 측정 → README §6.2 ablation 표에 기입.
