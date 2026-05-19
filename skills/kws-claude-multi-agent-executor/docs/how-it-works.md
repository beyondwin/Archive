# 동작 방식 — 한 번의 실행 시뮬레이션

한 번의 계획 실행이 처음부터 끝까지 어떻게 흘러가는지 서술형으로 풀어 씁니다. 정형 계약은 [`../SKILL.md`](../SKILL.md), 시스템 설계는 [`../ARCHITECTURE.md`](../ARCHITECTURE.md) 참조. 이 문서는 *벌어지는 순서* 에 집중해서 읽는 사람이 머릿속에 그림을 그릴 수 있도록 합니다.

## 등장 인물

1. **사용자 (당신)** — 계획 경로와 스펙 경로로 스킬을 호출.
2. **Claude Code (Opus 오케스트레이터)** — SKILL.md를 로드하고 3단계 라이프사이클을 진행.
3. **서브에이전트 (Sonnet)** — 오케스트레이터가 태스크별로 디스패치.
4. **git worktree** — 모든 계획 작업이 사는 격리된 레포 상태.
5. **학습 로그** — 사용자 로컬 JSONL, 모든 실행에서 주목할 만한 경계를 기록.

## 한 번의 실행, 단계별로

### Phase 0 — 셋업 (실행당 1회)

사용자가 호출:
```
/kws-claude-multi-agent-executor plan=docs/plans/2026-05-12-foo.md spec=docs/specs/2026-05-12-foo-design.md
```

오케스트레이터가 하는 일:

1. **호출 인자를 읽고** 계획 + 스펙 파일을 파싱. 태스크 목록, 위험 등급, 의존성, plan2 체이닝, docs scope 검출.
2. **git worktree 생성** — `<repo>/../worktrees/plan-<timestamp>/` 하위 (또는 모드에 따라 `<repo>/.claude/worktrees/...`).
3. **`state.json` 작성** — `<orch_dir>/state.json` 에 초기 태스크 상태(`pending`), 위험 등급, plan/spec 경로, 실행 식별자.
4. **Step 7.5 — 필수 AgentLens 경계 이벤트** (v2.17 cutover; v2.8.1+ 의 init-run 대체). `agentlens event append --type kws-cme.phase_0_started` 발송. `ORCH_RUN_ID` 는 Phase -1 step b 에서 `agentlens run-open` 으로 이미 열림. AgentLens CLI 누락 시 silent no-op. 레거시 `append_learning_event.py` 헬퍼는 Task 11 에서 제거됨 — AgentLens 가 단독 이벤트 싱크. 과거 실행의 패리티 검증은 `scripts/compare_agentlens_events.py` 사용.
5. **선택적 Plan Reviewer 디스패치** — 계획이 `mid` 또는 `high` 위험일 때. 서브에이전트가 Implementer 작업 시작 전에 계획 자체에 대한 PASS/WARN/FAIL 발산. 구조적 계획 결함을 일찍 잡음.

Phase 0 이후 실행은 "live": worktree 존재, 상태 커밋됨, 학습 로그 실행 디렉터리 존재(`outcome=unknown`).

### Phase 1 — 태스크 사이클 (각 태스크마다 반복)

계획의 각 태스크에 대해:

1. **위험 등급 디스패치**. 계획 또는 호출 오버라이드에서 위험 읽음. `low` → 느슨한 TDD, 재시도 1회. `mid` → TDD 필수, 재시도 2회. `high` → 엄격한 TDD, 재시도 3회 + 일관된 SPEC_FAULT 시 스펙 편집 분기.
2. **Implementer 디스패치 (Agent 툴)**. `implementer-prompt.md` 템플릿 전송:
   - 정확한 스펙 발췌
   - 정확한 계획 태스크 블록
   - 관련 컨텍스트 (읽어야 할 기존 파일, 컨벤션)
   - task_complexity (SMALL/MEDIUM/LARGE)에서 파생된 `effort_guidance` 문자열
   Implementer는 코드 작성, 테스트 실행, FILES_CHANGED + 커밋 메시지 발산. 막히면 ESCALATE 마커.
3. **Combined Reviewer 디스패치**. `reviewer-prompt.md` 전송 — 같은 스펙 발췌 + Implementer 커밋의 diff. Reviewer는:
   - `Skill("superpowers:requesting-code-review")` 호출해서 체크리스트 grounding (v2.8+)
   - **`SPEC_COVERAGE_WALK:`** 블록 발산 (v2.9.0+) — sub-step A 명시된 항목 열거, sub-step B 메타 규칙에서 적대적 생성
   - SPEC_SCORE + QUALITY_SCORE 채점 (P4, 0.0-1.0, 0.1 양자화)
   - SPEC_FAULT 진단 (`spec_contradicts | unclear | implementer_omitted | none`)
   - file:line + ISSUE_KEY 와 함께 SPEC_ISSUES, QUALITY_ISSUES 나열
4. **재시도 루프**. SPEC_STATUS=FAIL 또는 QUALITY_STATUS=FAIL 이면 오케스트레이터가 Reviewer의 `previous_issues` 와 함께 새 Implementer 디스패치. 재시도 예산은 위험 등급별. 소진 시 → ESCALATE.
5. **Step 3.5 — 학습 이벤트 후보 스캔** (v2.8+, v2.17 cutover). 오케스트레이터가 `<orch_dir>/learning_events/` 를 스캔, 서브에이전트가 남긴 JSON 후보 발견 (Reviewer는 WARN/FAIL 시, Verifier는 verification_failure 시, Implementer는 escalation/workaround 시 작성). 각 후보에 대해 `agentlens event append --run $ORCH_RUN_ID --type kws-cme.<event_type>` 발송 후 후보 파일을 `.appended` 로 이름 변경 (재발송 방지). 이벤트 조회: `agentlens events --type 'kws-cme.*'`.
6. **Verifier 디스패치** (Reviewer PASS 후, 커밋 전). `verifier-prompt.md` 전송 — 스펙의 acceptance criteria. Verifier는:
   - `Skill("superpowers:verification-before-completion")` 호출해서 체크리스트 (v2.8+)
   - acceptance criteria 독립적으로 재실행
   - 구체적 증거와 함께 PASS/FAIL 발산
7. **성공 시 커밋**. 오케스트레이터가 태스크 변경을 worktree 브랜치에 서술적 메시지와 함께 커밋, `state.json` 갱신.

사이클이 각 태스크마다 반복됩니다. 복구 불가 ESCALATE 발생 시 → 오케스트레이터가 `close-run --outcome blocked` 호출하고 중단.

### Phase 2 — 마무리 (마지막에 1회, 성공 경로)

1. **Docs Updater 디스패치**. 서브에이전트가 최종 diff를 읽고 `docs_scope` (보통 README / CHANGELOG / ADR 류) 갱신. 파일별 변경 셋 발산.
2. **문서 갱신을 worktree 브랜치에 최종 커밋**.
3. **Step 2 — `close-run --outcome success`**. `meta.json` 에 `ended_at`, `outcome=success`, `event_count=<N>` 갱신.
4. **사용자에게 보고**: 브랜치 이름, 커밋 목록, 테스트 결과, 점수 요약, 학습 이벤트 요약(있으면), 머지 여부 안내.

### 종료 경로 요약

| 종료 경로 | `meta.outcome` | 조건 |
|-----------|----------------|------|
| Phase 2 정상 도달 | `success` | 모든 태스크 완료 + 문서 갱신 |
| 실행 중단 ESCALATE | `blocked` | 스킵 불가 태스크에서 재시도 소진 |
| Transition T3 상태 쓰기 실패 | `blocked` | Phase 1과 Phase 2 사이에 디스크 풀 / 권한 거부 |
| 사용자 중단 / 훅 거부 | `aborted` | `claude -p` 훅이 실행 중 툴 콜 차단 |
| 하드 크래시 / 미처리 예외 | `unknown` | close-run 전에 오케스트레이터 프로세스 사망 |

## 동시성

여러 계획 실행이 병렬로 가능:
- 다른 레포: 자명하게 OK. 격리된 worktree + 격리된 AgentLens run.
- 같은 레포, 다른 계획: 각자 자기 worktree (`plan-<timestamp>`) + 자기 `ORCH_RUN_ID` (AgentLens run id). 공유 상태 없음.
- Resume Chain 상속 (v2.17 cutover): 체이닝된 `claude -p` 서브프로세스는 `env AGENTLENS_PARENT_RUN_ID=$ORCH_RUN_ID nohup claude -p ...` 로 부모의 AgentLens run id 상속. 체이닝된 자식은 새 run 을 열지 않고 동일 run 에 이벤트를 계속 발행. (레거시 `MAE_LEARNING_RUN_ID` / `append-session-id` 흐름은 Task 11 에서 제거됨.)

## 리플레이 — 과거 실행 디버깅

각 세션은 `~/.claude/projects/<encoded-cwd>/<full-uuid>.jsonl` 에 트랜스크립트 작성. 실행 디버깅 방법 (v2.17+):

1. AgentLens run id 확인: `<orch_dir>/state.json` 의 `agentlens_orchestration_run` 필드 (또는 `agentlens runs --agent kws-cme-orchestrator` 목록).
2. 이벤트 스트림 조회: `agentlens events --run <run_id> --type 'kws-cme.*'` — 페이즈 경계, 태스크 완료, 블로커, verification_failure, reviewer_warn_or_fail, context_health 등 전 이벤트 시계열.
3. `<orch_dir>/state.json` 열어서 기록된 태스크 상태 확인.
4. 트랜스크립트 정밀 조사가 필요하면 `~/.claude/projects/<encoded>/<session_id>.jsonl` 열기 (세션 ID 는 AgentLens run meta 또는 `<orch_dir>/headless_chain_*.jsonl` 에서 추출).

레거시(`~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/`) — v2.17 cutover 이전 실행만 존재. 읽기 전용 사료(historical). 신규 실행은 더 이상 작성하지 않음. 레거시 ↔ AgentLens 패리티 점검은 `scripts/compare_agentlens_events.py <legacy_events.jsonl> <agentlens_run_dir>`.

Eval 하네스의 `run.jsonl` 은 별도 트랜스크립트 산출물 — `<tmpdir>/.harness/run.jsonl`. Reviewer 출력 파싱(Agent 툴 결과), 툴 호출 카운트에 유용. (v2.17 cutover 이전: `LEARNING_LOG_INIT:` grep 으로 Step 7.5 준수 측정. cutover 이후에는 AgentLens 의 `kws-cme.phase_0_started` 이벤트 존재 여부로 측정.)

## 왜 이 설계인가 — 빠른 근거 포인터

이 선택들에는 역사가 있습니다. 각각의 "왜" 는:

- 3단계 라이프사이클 (vs 연속 루프): [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §11
- Combined Reviewer (vs spec + quality 분리 리뷰어): [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4 + v2.6 history
- 실행별 샤딩 학습 로그 (vs 단일 events.jsonl): `experiments/v2.8-learning-log/decisions/D001-initial-design.md` §Q1 (역사적; v2.17 cutover 로 AgentLens 단독 싱크로 전환)
- 헬퍼 단일 작성자 계약: 같은 D001 §Q4 (advisor patch) — v2.17 에서는 오케스트레이터가 AgentLens 발송도 단독 수행 (서브에이전트는 후보 JSON 만 작성)
- 적대적 생성 포함된 Spec Coverage Walk: `experiments/v2.9-reviewer-spec-coverage/decisions/D001-initial-design.md` §Q3
- Step 7.5 MANDATORY 표현: HISTORY.md v2.8.1 항목 + F001-smoke.md PARTIAL 감사

전체 인덱스는 [`decision-log.md`](./decision-log.md).
