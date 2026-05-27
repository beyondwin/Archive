# JOURNAL — v2.19 Token Cost Optimization

## 2026-05-27

### 14:00 — 분석 세션 시작

사용자가 멀티에이전트 워크플로의 캐시 거동에 대한 직관(터미널이 캐시 친화적, `-p`는 드리프트, 서브에이전트는 cold start)을 공유. 팩트체크 결과 **관측은 정확하나 메커니즘 설명은 일부 부정확** — 정정 내용을 [findings/F002-cache-mechanics.md](./findings/F002-cache-mechanics.md) 에 정리.

핵심 정정:
- "터미널이 TTL을 더 살린다" → 터미널이 TTL을 늘리는 게 아니라, **인터랙티브 사용 패턴이 prefix를 안정시키고 5분 안에 다음 턴이 발생** 하기 때문.
- "캐시는 세션과 무관, prefix 토큰만 따짐" → 정확.
- "서브에이전트는 메인 캐시 무관, cold start" → 정확. 보강: 같은 wave 내 fan-out은 시스템 프롬프트가 byte-identical이면 2nd spawn부터 hit 가능.

### 14:45 — 캐시 친화적 에이전트 설계 가이드 도출

대화 흐름에서 "Frozen Core + Hot Tail" 패턴, 시스템 프롬프트에 절대 넣지 말 것 목록, 멀티에이전트 prompt 합성 시 캐시 함정 등을 정리. 이 일반 가이드는 추후 별도 문서화 검토.

### 15:30 — `kws-claude-multi-agent-executor` 본격 진단

`SKILL.md` (2,188줄 / 175KB / ~72k tokens), `references/implementer-prompt.md` (195줄), `references/reviewer-prompt.md` (224줄), `ARCHITECTURE.md` (410줄) 정독.

발견된 핫스팟 3개:
1. SKILL.md 자체가 매 턴 prefix 점유. Phase 별 분리 가능 — [F001](./findings/F001-skill-md-size-analysis.md).
2. 서브에이전트 dispatch 시 system prompt 변수가 cache key를 깨뜨림 — [F003](./findings/F003-subagent-cache-fanout.md).
3. 서브에이전트가 state.json을 직접 Read하는 패턴 (`implementer-prompt.md` L52~57) — 토큰 + 라운드트립 이중 비용.

추가로 Tier 2/3에 들어갈 후보들 (1h extended cache, 디프 사이즈 캡, candidate drain 묶음) 도출.

### 16:30 — 제안 정리 및 사용자 승인

비용/퀄리티 트레이드오프 우선순위 표를 사용자에게 제시. 사용자 승인 받음 — 다음 단계는:

1. T2 — 베이스라인 측정 인프라 (변화 측정 없이 진행 불가)
2. T1.2 — slice injection PoC (변경 작고 안전)
3. T1.1 — SKILL.md 슬림화 PoC

이 README + findings 문서로 분석 단계 종료. 구현은 별도 작업 세션 / PR로 진행.

### 다음 action item

- [ ] T2 베이스라인 측정 — `evals/run.sh` 픽스처 4–5개 실행, `cost_ledger.totals` 표 생성
- [ ] D003 결정 — 서브에이전트 state.json Read를 폐지할지 fallback으로 남길지
- [ ] D002 결정 — extended cache 적용 시 SDK 노출 여부 사전 조사
- [ ] T3 SKILL.md 슬림화 경계 (D001) — Phase 기준 vs cross-cutting (AgentLens emit 등)

---

## 2026-05-27 (오후 — 사용자 승인 후 PoC 실행)

### 17:00 — D001~D003 초안 작성

3개 ADR 모두 `decisions/` 하위에 작성:

- D001 — Phase 축 + Cross-cutting 축 하이브리드. 두 디렉터리(`references/phases/`, `references/cross-cutting/`) 로 단일 소스 원칙 + cache locality 둘 다 충족.
- D002 — 1h extended cache 잠정 적용 결정. SDK가 호출자에게 `cache_control.ttl` 노출 여부 사전 조사 필요. 노출 안 되면 SDK 이슈 제기 권장.
- D003 — 서브에이전트의 `state.json` 직접 Read 폐지 + fallback 절차 유지 (서브에이전트가 fallback 타면 `CONTEXT_SOURCE: fallback-read` 출력 → 오케스트레이터가 카운트 + AgentLens 이벤트 emit).

### 17:30 — T2 베이스라인 측정 인프라

`scripts/cost_report.py` + `scripts/run_ablation.sh` 작성. cost_report는 `state.cost_ledger`를 읽어 markdown 표로 출력 (single + compare 모드 둘 다). 실행 결과 검증 — synthetic state로 smoke test 통과.

`run_ablation.sh` 는 baseline/experiment/compare/single 4개 모드. 실제 `evals/run.sh` 호출은 API 토큰 비용 발생하므로 스크립트 안에서 stub 처리 — 사용자가 명시적으로 활성화해야 실행.

### 17:45 — T1.2 PoC 적용

`references/implementer-prompt.md` 변경:
- L51~67의 "## Context from Previous Tasks" 블록을 `{context_slice}` placeholder + 사용 안내로 교체
- Output Format에 `CONTEXT_SOURCE: pre-resolved | fallback-read` 라인 추가

`SKILL.md` Phase 1 Step 1 변경:
- placeholder 리스트에 `{context_slice}` 추가 + 치환 규칙 명시 (Python-like pseudocode로 task_summaries + shared_files 슬라이스 계산)
- `CONTEXT_SOURCE` 파싱 + `kws-cme.orchestrator_bug` 이벤트 emit 규칙

Reviewer는 state.json을 직접 읽지 않으므로 변경 불필요. SubagentStop hook (`check-implementer-output.sh.template`) 검증 — `CONTEXT_SOURCE` 추가 필드는 hook의 missing 검사 로직에 영향 없음 (purely additive). T1.2 안전 통과.

### 18:00 — T1.1 PoC (Phase -1 추출)

`references/phases/phase-minus-1-args-and-spawn.md` 신설 (411줄 / 27KB). SKILL.md L77-470의 Phase -1 본문을 그대로 옮김 + 도입 헤더 추가.

SKILL.md의 Phase -1 섹션은 ~25줄 stub으로 교체. stub 핵심: "**Required action at the start of every invocation**: before doing anything else, Read `references/phases/phase-minus-1-args-and-spawn.md`."

**측정**:
- SKILL.md: 2,188줄 / 175,097 bytes → 1,859줄 / 153,020 bytes (-15% / -22KB)
- 추출된 reference: 411줄 / 27,165 bytes (Phase -1 진입 시 1회만 Read)
- 다음 추출 후보: Phase 0 (~630줄), Phase 1 (~530줄), Phase Transition, Phase 2, cross-cutting (state-schema, agentlens-emit-sites 등)

### 종료 — 후속 액션

이번 세션에서 멈춘 지점:
1. **Phase 0/1/Transition/2 추출** — T1.1 PoC 패턴이 검증됐으니 같은 방식으로 진행 가능. 다만 phase 간 cross-reference가 더 복잡하므로 신중히.
2. **베이스라인 + ablation 실측** — `scripts/run_ablation.sh` 활성화 + 사용자가 API 비용 부담 후 실행. 픽스처는 `evals/fixtures/01-trivial-typo.yaml`, `03-three-file-refactor.yaml`, `07-subtle-input-validation.yaml` 등 선택.
3. **D002 후속** — Claude Code / Agent SDK가 `cache_control.ttl` 노출하는지 조사. 노출되면 1h cache 적용, 아니면 이슈 제기.
4. **HISTORY.md / ARCHITECTURE.md 업데이트** — v2.19 머지 시점에 진행 (이번 세션은 experiment branch 단계로 보존).

이번 세션의 변경은 main 브랜치 working tree에 남아있음 — 사용자가 실험 branch로 분기하거나 commit 결정.
