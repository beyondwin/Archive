# 품질 개선 플랜 — kws-claude-multi-agent-executor

> 권위 문서는 `SKILL.md` 와 `references/` 다. 이 문서는 **개선 제안(설계 단계)**
> 이며, 채택 시 각 항목이 실제로 옮겨갈 위치를 명시한다. 짝 문서:
> [`품질개선-구현-ko.md`](./품질개선-구현-ko.md) (구체 구현 명세).
>
> 대상 버전 묶음: **v2.29-quality-uplift** (제안 명칭).
> 작성일: 2026-06-07.

---

## 0. 한 줄 요약

오케스트레이터(Opus)가 **자기 컨텍스트를 덜 먹고**, 작업 중 문제를 만나도 **스스로
판단해 다음으로 진행**하며, 실행이 끝난 뒤 **로그만으로 원인 진단·스킬 개선이
가능**하도록 만드는 12개 개선 항목을, 영향×역노력 순으로 3단계(P0/P1/P2)로 묶었다.

이 세 목표는 사용자가 명시한 세 축이다:

- **축 A — 컨텍스트 절감**: 메인 에이전트가 컨텍스트를 덜 먹어 판단 품질이 유지되도록.
- **축 B — 자율 문제판단**: 작업 중 문제 발생 시 효과적으로 판단해 알아서 다음을 진행.
- **축 C — 사후 로그**: 끝난 뒤 로그를 통해 스킬 개선과 문제 파악이 쉽도록.

---

## 1. 분석 방법 (어떻게 도출했나)

세 서브에이전트를 병렬로 돌려 다각도로 깊게 분석했다.

1. **내부 심층 분석** — `SKILL.md`, `references/phases/*`, `references/cross-cutting/*`,
   `scripts/*`(실제 Python/셸 구현), `docs/동작-가이드-ko.md` 를 전수 읽고 세 축에
   대해 file:line 근거로 현재 상태와 잔여 갭을 매핑.
2. **Anthropic 공식 패턴** — 멀티에이전트 리서치 시스템, context engineering,
   context editing/memory tool, Agent SDK, sub-agents, writing-tools-for-agents,
   long-running-agents 하니스 문서를 직접 fetch 해 우리 구조에 매핑.
3. **공개 오케스트레이션 코드 서베이** — LangGraph, OpenHands(condenser), CrewAI,
   AutoGen, OpenAI Agents SDK, Claude Flow, smolagents, SWE-agent, Temporal 의
   컨텍스트 절감·자율복구·관측 패턴을 1차 소스 기준으로 수집.

핵심 출처(검증된 URL):
- https://www.anthropic.com/engineering/multi-agent-research-system
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- https://claude.com/blog/context-management (context editing + memory tool 수치)
- https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- https://docs.claude.com/en/docs/claude-code/sub-agents
- https://docs.langchain.com/oss/python/langgraph/persistence (checkpoint/resume)
- https://docs.openhands.dev/sdk/guides/context-condenser (keep_first 압축)
- https://openai.github.io/openai-agents-python/tracing/ (span 트리)

---

## 2. 현재 상태 진단 (이미 잘 된 것 / 잔여 갭)

설계의 기본기는 이미 탄탄하다. 잘못 손대면 회귀가 나므로, **이미 해결된 것**을 먼저
못 박는다.

### 2.1 이미 잘 되어 있어 그대로 둘 것 (재작업 금지)

- **SKILL.md 슬림화 + phase 지연 로딩** — 각 phase는 진입 시점에만 reference를 읽고
  드롭. 구조적 컨텍스트는 거의 안 들고 있음. (SKILL.md:82-90, 109-131)
- **상태 단일 소스 + flock 헬퍼 번들** — `state_set.py`, `phase_boundary.py`
  (`task-start`/`task-complete`/`phase-emit`), `accumulate_cost.py` 가 "필수 write +
  짝 emit/timestamp"를 묶어 silent skip을 차단. (v2.21 D002)
- **sub-agent 컨텍스트 격리 + "요약만 저장" 가드레일** — 원문 누적 금지, T3 컨텍스트
  드롭. (SKILL.md:216, phase-transition:107)
- **이미 닫힌 회귀들 — 절대 되돌리지 말 것**:
  - `timing_inverted` 무면제 blocking FAIL (v2.28 D003)
  - 비용 원장 미집계 → all-agent 경로는 `cost_tracking_waived`로 정직하게 면제
    (v2.28 D001) — agent 경로 빈 원장을 "고치려" 하지 말 것
  - Phase 2 스킵/attached 스키마 즉흥 → Stop 훅 강제 (v2.26 + v2.28 D002)
  - repo 자체 settings.json 병합 손실 → `materialize_worktree_hooks.py` deep-merge
    + finalize 백스톱 (v2.27 D001/D003)
  - `quality_trend` 이중 write/희소 → 단일 writer + `quality_trend_sparse` WARN
  - 비정규 task 키 / 삽입순서 버그 → `last_completed_task` 권위 + WARN
  - detach + agent 게이트 과금 → Phase -1 reconcile (v2.25 D002)

### 2.2 잔여 갭 (이번 개선의 표적)

| 축 | 잔여 갭 | 근거 |
|----|---------|------|
| A | 스펙 편집 후 **전체 스펙 재독** | SKILL.md:215, phase-1-task-cycle:242 |
| A | `{context_slice}` 도출 ~40줄을 **매 task in-context 실행** | phase-1-task-cycle:89-132 |
| A | Final Summary **수작업 다수 필드 취합**(최대 컨텍스트 버스트) | phase-2-finalization:244-322 |
| A | resume 시 **state.json 전체 로드** | phase-0-setup:27 |
| B | review/verifier **retry 소진 시 halt**(escalation-cap은 SKIP인데 비대칭) | phase-1-task-cycle:251,300 vs phase-1-escalation:41-49 |
| B | `auto_resolved` 재해석 **무제한** | phase-1-escalation:78-89 |
| B | WARN tier + HIGH risk 인데 **추가 검증 없음** | phase-1-task-cycle:201,211 |
| C | **머신리더블 run report 부재**(마크다운 prose만) | phase-2-finalization:244 |
| C | **per-task 결정 트레이스("왜 retry") 부재** — `current_previous_issues` 덮어씀 | phase-1-task-cycle:249 |
| C | AgentLens 부재 시(=all-agent 기본 경로) **로컬 이벤트 타임라인 0건** | SKILL.md:258 |
| C | run-level **failure taxonomy 롤업 부재** | finalize_run.py:186 |

---

## 3. 설계 원칙 (재설계의 앵커)

공식·공개 소스에서 수렴한, 우리가 따를 원칙:

1. **오케스트레이터 컨텍스트는 희소 자원** — "가장 작은 고신호 토큰 집합"을 유지.
   (Anthropic context-engineering)
2. **sub-agent는 장황한 작업을 오케스트레이터 창 밖으로 빼는 장치** — 항상 압축된
   구조화 결과만 돌려받는다(~1–2K 토큰 요약 권장). (Anthropic multi-agent; sub-agents)
3. **plan/state/decisions는 외부 메모리(state.json + git)** — resume 시 히스토리가
   아니라 파일에서 재구성. (Anthropic; LangGraph thread resume; SWE-agent ACI)
4. **just-in-time 검색** — 경로/ID/슬라이스 범위만 들고 필요할 때 로드.
5. **실패 시 알리고 적응 + 경계 있는 재시도 + git 체크포인트; 재시작이 아니라 재개.**
   (Anthropic; LangGraph RetryPolicy; Temporal)
6. **중간 단계가 아니라 검증된 end-state로 루프를 구동, 한 번에 한 작업 단위.**
   (Anthropic long-running harness)
7. **모든 결정의 구조화 트레이스가 개선의 토대** — fixture eval + (선택) LLM-judge와
   결합. (Anthropic; OpenAI Agents SDK span 트리; smolagents replay)
8. **경직된 규칙이 아니라 휴리스틱 + 명시적 가드레일/예산으로 폭주 방지.**

### 3.1 우리 맥락에서의 중요한 제약 (반드시 준수)

- **팬아웃 확대 금지.** Anthropic은 코딩 작업이 리서치보다 병렬화 가능 작업이 적고
  LLM 에이전트의 실시간 위임/조정이 아직 약하다고 명시한다. 사용자도
  터미널-1개당-역할-1개 수동 디스패치를 선호([[feedback_agent_invocation_style]]).
  → **본 플랜은 병렬성을 늘리지 않는다.** 순차 단일-작업-단위 위임을 강화한다.
- **AGENTS.md/CLAUDE.md 준수.** sub-agent가 Lens 이벤트를 직접 쓰지 않는다(Waygent가
  emission 소유). 본 플랜의 로컬 `events.jsonl` 은 **오케스트레이터 단일 writer**
  로컬 로그이며 Lens 채널이 아니다 — 제약과 충돌하지 않는다.
- **컨텍스트 비용 vs 품질.** 멀티에이전트는 chat 대비 ~15× 토큰을 쓴다. 추가 에이전트
  /패스는 "고가치일 때만" 추가한다(축 B의 추가 검증은 조건부로 게이팅).

---

## 4. 개선 항목 카탈로그 (12개)

각 항목: **문제 → 제안 → 축 → 영향/노력 → 근거**. 구체 구현은 짝 문서 참조.

### P0 — 빠른 승리 (저노력·고효과)

**I1. retry 소진 → SKIP-and-continue 정렬 [축 B]**
- 문제: escalation-cap 소진은 v2.25부터 SKIP+continue인데, review/verifier retry
  소진은 여전히 "halt, manual intervention". Phase 1 내 마지막 하드 스톱이자 비대칭.
- 제안: retry 소진 시 task를 SKIPPED로 마킹 + `verification_gaps`/`docs_gaps`에 사유
  기록 후 다음 task로 진행(이미 D003 갭마커 기계가 있음). 의존 서브트리는 기존 SKIP
  전파 규칙을 따른다.
- 영향: 高 / 노력: 低. 근거: phase-1-task-cycle:251,300; phase-1-escalation:41-49.

**I2. 로컬 `events.jsonl` tee [축 C]**
- 문제: all-agent attached(=기본) 경로에서 AgentLens CLI가 없으면 모든 emit이
  `2>/dev/null` no-op → 타임라인 0건. 나쁜 run을 사후 재구성할 수 없음.
- 제안: 모든 boundary emit을 AgentLens 도달성과 무관하게 `<orch_dir>/events.jsonl`
  에 append(오케스트레이터 단일 writer). 값싸고 로컬이며 replay 가능. (v2.17에서
  제거된 건 "병렬 sink"였고, 여기선 "fallback tee"라 충돌 아님.)
- 영향: 高 / 노력: 低. 근거: SKILL.md:258; agentlens-emit-sites.

**I3. per-task `retry_trace[]` (append-only) [축 C]**
- 문제: retry 횟수만 남고 "왜 각 retry가 났는지"(ISSUE_KEY, RECURRING 여부,
  SPEC_FAULT 클래스, tier)는 `current_previous_issues` 덮어쓰기로 소실. 디버깅
  최고 신호가 사라짐.
- 제안: `<active>.tasks.task_N.retry_trace[]` 에 `{attempt, fault, recurring_keys,
  tier, ts}` 추가(append-only).
- 영향: 高 / 노력: 低-中. 근거: phase-1-task-cycle:249.

### P1 — 코어 (중노력·고효과)

**I4. `build_final_report.py` → 마크다운 + `run_report.json` [축 A+C]**
- 문제: 최대 end-run 컨텍스트 버스트가 수작업 취합(phase-2-finalization:244-322);
  결과는 prose뿐이라 머신리더블 로그 없음. `aggregate_runs.py`가 소비할 입력이 없음.
- 제안: state.json에서 리포트 마크다운과 `run_report.json`(tasks/tiers/retries/gaps/
  timing/cost/auto_resolved/quality delta)을 함께 생성하는 헬퍼. 오케스트레이터는
  헬퍼 출력만 읽음(컨텍스트 절감) + aggregate 파이프라인 직결(관측).
- 영향: 高 / 노력: 中. 근거: phase-2-finalization:244; aggregate_runs.py 존재.

**I5. `build_context_slice.py` 헬퍼 [축 A]**
- 문제: `{context_slice}` 도출 ~40줄을 매 task 모델이 in-context로 실행
  (task_summaries/shared_files/global_constraints 취합).
- 제안: `build_spec_manifest.py` 패턴을 그대로 따라, 준비된 슬라이스를 반환하는 헬퍼.
  오케스트레이터는 도출 로직을 안 들고 결과만 주입.
- 영향: 中 / 노력: 低-中. 근거: phase-1-task-cycle:89-132.

**I6. 스펙 편집 후 변경 섹션만 재독 [축 A]**
- 문제: 편집 후 "전체 스펙 재독" 강제 — 모순 많은 플랜에서 전체 스펙 반복 로드.
- 제안: `spec_manifest.sections[sid]` 범위만 재독. 가드레일 "re-read after update"는
  "변경된 섹션 재독"으로 정밀화(무결성은 유지하되 전체 로드 제거).
- 영향: 高 / 노력: 中. 근거: SKILL.md:215; phase-1-task-cycle:242; build_spec_manifest.py 존재.

**I7. `failure_summary` 롤업 + finalize 체크 [축 C]**
- 문제: 실패 신호(verifier category, blocker 사유, gaps, auto_resolved)가 이벤트·배열
  에 흩어져 있고 run 단위 분류 롤업이 없음.
- 제안: `finalize_run.py`(또는 리포트 빌더)가 클래스별 `failure_summary` 블록을 생성해
  `run_report.json`에 포함.
- 영향: 中 / 노력: 低. 근거: finalize_run.py:186; verifier category enum 존재.

### P2 — 하드닝 / 전략

**I8. run-level `auto_resolved` 임계 → 압축 시점 표면화 [축 B]**
- 문제: D003 자율 재해석이 run당 무제한. 매우 모호한 스펙이 다수 silent 재해석을
  낳고 Final Report에서만 드러남.
- 제안: run-level 카운트가 N 초과 시 다음 compaction에서 신호로 표면화(여전히 halt
  아님 — 관측 신호). 근거: phase-1-escalation:78-89.

**I9. WARN+HIGH+저점수 → 1회 추가 Verifier [축 B]**
- 문제: HIGH는 항상 검증하지만, implementer가 추측해 WARN tier로 통과한 HIGH-risk
  파일에 추가 정밀검증 없음.
- 제안: 경계 있는 정책 — `tier==WARN AND risk==high AND quality_score<0.70 → 추가
  Verifier 1회`(기존 retry 캡 안에서). 고가치일 때만 패스를 추가(원칙 3.1 준수).
- 영향: 中 / 노력: 低-中. 근거: phase-1-task-cycle:201,211.

**I10. `state_resume_digest.py` (선택적 resume 로드) [축 A]**
- 문제: resume 시 state.json 전체 로드(긴 체인에서 큼).
- 제안: 라이브 카운터 + `<active>` 포인터만 반환하는 다이제스트. 후속 세션은 다이제스트
  + plan만으로 부팅(Anthropic/LangGraph 원칙). 근거: phase-0-setup:27.

**I11. 압축 압축규율 명시화: keep_first 고정 + 직전 task tool-result 드롭 [축 A]**
- 문제: 현재 T3 컨텍스트 드롭은 "요약만 저장"에 의존. OpenHands keep_first 패턴처럼
  "plan + state 다이제스트"를 명시적으로 고정하고, 직전 task의 tool-result 블록을
  명시적으로 드롭하면 더 안전하고 일관됨.
- 제안: phase-transition T3에 keep_first(plan/state digest) 고정 + 직전 task
  tool-result 드롭을 명문화. (Anthropic context editing의 in-session 등가물.)
- 영향: 中 / 노력: 中. 근거: phase-transition; Anthropic context-management.

**I12. (전략) Agent SDK 포팅 시 네이티브 context-editing + memory tool 채택 [축 A, 선택]**
- 배경: Claude Code 세션은 API beta 헤더(`context-management-2025-06-27`)를 직접
  못 켠다 → context-editing/memory-tool은 **현 실행 형태에선 직접 적용 불가**.
- 제안: 만약 executor를 Agent SDK 앱으로 포팅한다면, 100-turn eval에서 토큰 84%
  절감이 보고된 context-editing과 file-based memory tool을 채택. **지금은 의사결정
  기록만**; 근시일 작업은 I11(인세션 등가물)으로 대체.

---

## 5. 우선순위 로드맵

```
P0 (1차, 독립·저위험):   I1  I2  I3
P1 (2차, 관측·절감 코어): I4  I5  I6  I7      (I4는 I7·aggregate 직결)
P2 (3차, 하드닝/전략):    I8  I9  I10 I11 (I12는 기록만)
```

의존성:
- I4(run_report.json) ⟶ I7(failure_summary는 같은 빌더가 생성) ⟶ aggregate_runs.py 소비
- I2(events.jsonl) + I3(retry_trace) ⟶ I4 리포트의 트레이스 섹션 입력
- I5/I6는 독립. I11은 I4와 무관하나 같은 "압축 규율" 테마.

권장: **P0를 한 묶음(v2.29.0)** 으로 먼저 — 저위험·즉효·관측 토대. 이후 P1을
v2.29.1, P2를 v2.29.2로.

---

## 6. 검증 전략

- **회귀 eval**: 각 묶음 채택 전 `evals/run.sh` + `scripts/fixtures`/driving-run
  fixtures로 재생. Anthropic의 "lead 프롬프트 작은 변경이 sub-agent 거동을 예측불가하게
  바꾼다" 경고에 따라 **오케스트레이터 프롬프트 변경은 fixture eval 통과 후 채택.**
- **계약 체크**: 신규 state 필드는 `validate_state_schema.py`에 추가, finalize 신규
  FAIL/WARN은 `test_finalize_run.py`에 케이스 추가.
- **표준 체크**(루트 CLAUDE.md): 관련 변경에 한해
  `cd skills/kws-claude-multi-agent-executor && ./evals/run.sh`, 신규/변경 스크립트는
  짝 `test_*.py`.
- **실험 기록**: 스킬 컨벤션상 비자명 변경은 `docs/experiments/v2.29-quality-uplift/`
  에 실험 레코드 작성(가설/변경/fixture 결과/의사결정).

---

## 7. 안티패턴 / 주의 (공개 사례에서 학습)

- **과압축으로 핵심 state 소실** — plan과 state 다이제스트는 절대 요약 대상에서 제외
  (OpenHands keep_first). I11은 이 원칙을 명문화한다.
- **무제한 retry** — 모든 재시도 경로에 캡 유지(I1은 캡 도달을 halt가 아닌
  SKIP+gap으로 바꾸되 캡 자체는 유지).
- **멀티에이전트 비용 폭주** — 역할당 1 sub-agent 유지, 팬아웃 금지(3.1).
- **체크포인트 ≠ 내구 실행** — 다음 디스패치 *이전*에 state flush(이미 헬퍼가 보장).
- **대화 히스토리로 state 추론** — 진실원은 state.json. resume 다이제스트(I10)도
  파일에서 재구성.
- **가드레일 커버리지 갭** — sub-agent **출력**을 명시 검증(이미 SubagentStop 훅 +
  Verifier; I9는 고위험 경계 보강).

---

## 8. 기대 효과 요약

| 축 | 핵심 변화 | 기대 효과 |
|----|-----------|-----------|
| A | I4/I5/I6/I10/I11 | end-run·per-task in-context 도출 제거, 전체 스펙 반복 로드 제거, resume 경량화 → 메인 에이전트 토큰 절감·판단 품질 유지 |
| B | I1/I8/I9 | Phase 1 마지막 하드 스톱 제거(자율 진행), 무제한 재해석 가시화, 고위험 경계 추가 검증 → "알아서 다음 진행" 강화 |
| C | I2/I3/I4/I7 | 모든 run에 replay 가능한 타임라인 + 머신리더블 리포트 + 결정 트레이스 + 실패 분류 → 사후 진단·스킬 개선 용이 |
