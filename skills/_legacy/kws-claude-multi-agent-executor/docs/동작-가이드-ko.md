# KWS Claude 멀티 에이전트 실행기 — 동작 가이드 (한글)

> 이 문서는 스킬이 실제로 어떻게 돌아가는지를 쉽게 풀어 정리한 한글 가이드입니다.
> 권위 있는 계약(contract)은 항상 `SKILL.md`와 `references/`이며, 이 문서는 이해를
> 돕는 보조 자료입니다. 충돌 시 `SKILL.md`가 우선합니다.

---

## 0. 한 줄 요약

**Opus가 "감독(Orchestrator)"이 되어, 구현 플랜을 받아 신선한 Sonnet 하위
에이전트들에게 작업을 시키고, 검토·검증·문서화까지 사람 개입 없이 끝까지 자동으로
돌리는 시스템.**

핵심 철학: **감독은 코드를 절대 직접 안 짠다.** 감독은 읽고·계획하고·일을
시키고·판단만 한다. 실제 손은 전부 하위 에이전트가 쓴다.

전 영역을 관통하는 설계 원칙 하나: **"글(prose)로만 쓴 규율은 조용히 우회된다."**
그래서 핵심 불변식을 전부 코드/훅/헬퍼로 강제한다.

---

## 1. 역할 분담

```
사용자 ──(plan=..., spec=...)──> Opus 감독
                                   │
        ┌─────────────┬───────────┼────────────┬──────────────┐
        ▼             ▼           ▼            ▼              ▼
   Implementer    Reviewer    Verifier    Plan Reviewer   Docs Updater
   (구현/TDD)     (검토/점수)  (검증/테스트)  (사전 감사)      (문서화)
   Sonnet|Opus    항상 Sonnet  항상 Sonnet   Opus            Sonnet
```

- **Implementer**: 실제 코드 작성. 기본 Sonnet, `opus`로 승격 가능.
- **Reviewer / Verifier**: 판단 일관성을 위해 항상 Sonnet 고정 (모델 안 바꿈).
- **문서(spec/plan) 수정은 감독만** 한다. 하위 에이전트에게 절대 위임 금지.

---

## 2. 저장 위치

모든 상태는 **소스 레포 안이 아니라** `~/.claude/` 아래 두 형제 디렉터리에 저장된다.

| 위치 | 내용 |
|------|------|
| `~/.claude/worktrees/<런ID>/` | 실제 코드 작업용 git worktree (+ `.claude/settings.json` 하나만) |
| `~/.claude/orchestrator/<런ID>/` | 감독의 모든 상태 — `state.json`, 훅, 로그, 결과 |

둘은 같은 `<런ID>`(`플랜이름-YYYYMMDD-HHMMSS`)로 짝지어지며, **중첩이 아니라
형제**다. `state.json`이 **유일한 진실의 원천**이고, 압축(compaction)마다 감독은
컨텍스트에서 원본 작업 내용을 버리고 여기서 다시 읽는다.

> `~/.claude/`는 state.json/하위에이전트에 넘기기 전 반드시 절대경로(`$HOME/...`)로
> 확장해야 한다. 하위 에이전트는 `~`를 못 펼친다.

---

## 3. 실행 단계 (Phase) 개요

```
Phase -1  모드 선택 + 인자 파싱 (+ 옵션 self-spawn)
Phase 0   셋업 (워크트리·훅·baseline·의존성 그래프·리스크 배정)
Phase 1   작업별 사이클 (Implementer→Reviewer→Verifier→Cleanup) 반복
Phase Transition  압축 지점마다 (LOW 일괄검증·문서갱신·컨텍스트 폐기)
Phase 2   마무리 (LOW 최종 스윕·문서·method audit·요약 리포트·run-close)
```

---

## 4. Phase -1: 모드 선택 + 인자 파싱

### 인자 (3-pass 파서)
- **Pass 1** — `key=value` 수집: `plan=`, `spec=`, `implementer_model=`,
  `parallel=`, `risk=`, `budget=`, `context_budget=` 등. 알 수 없는 키는 halt.
- **Pass 2** — 멀티플랜 자동 감지: `plan=`(0), `plan2=`(1), `plan3=`(2)… 번호 갭이나
  `specN=` 짝 누락은 halt.
- **Pass 3** — 자연어 키워드 (고정 사전): `opus`/`오푸스`, `sonnet`/`소넷`,
  `순차`/`sequential`/`직렬`, `대화형`/`interactive`. 한국어 조사(`로`, `으로` 등)는
  최장 일치로 제거 후 매칭. **명시적 `key=value`가 항상 이긴다.** 모순은 halt.

파싱 직후 **에코 라인 1줄 필수 출력** — 사용자가 detach 전 오해를 잡을 마지막 기회.

### 모드 결정
1. `mode=interactive` → 레거시 단일 세션 (Phase 0으로)
2. 프롬프트에 `<<HEADLESS_KWS_ORCHESTRATOR>>` → 헤드리스 인스턴스 (Phase 0으로)
3. `detach=true` → **Self-Spawn** (분리된 headless `claude -p` 백그라운드 실행)
4. 그 외 bare 호출 → **attached 인-세션** (v2.22.0 기본, `mode=interactive_attached`)

> **detach + agent 게이트 조정:** detach면 감독 자체가 `claude -p`라 Agent 서브에이전트가
> metered 부모에 청구됨 → `"agent"` 이득 없음. agent 기본값 게이트는 `"api"`로 폴백,
> 명시적 `"agent"`는 경고 후 유지.

---

## 5. Phase 0: 셋업 (핵심만)

- `git status` 깨끗한지 확인 (더러우면 abort)
- **교차 실행 격리** — 같은 소스 레포(`source_repo` 키)를 노리는 다른 헤드리스 런이
  살아있으면 거부. 다른 레포면 동시 실행 허용. 불명확하면 보수적 차단.
- 워크트리 생성 + **안전 훅 4종 설치** (§9)
- 플랜/스펙 읽고 검증 → 애매하면 여기서 질문 (Ambiguity Gate)
- **구조 검증** — `### Task N:`(H3) 또는 `## Task N:`(H2) 헤더 필수, `Files:` 블록 필수,
  레포 밖 경로 halt
- 작업별 **리스크 등급**(LOW/MID/HIGH)과 **크기**(SMALL/MEDIUM/LARGE) 배정
- baseline 테스트 실행, `test_command` 1번만 산출해 캐시
- 의존성 그래프 → **실행 순서(웨이브) + 병렬 그룹** 결정 (`execution_plan`)
- Plan Reviewer 사전 감사 (기계적 루브릭만; 스타일/아키텍처 제안은 무시)
- `state.json` 초기화 + 검증

---

## 6. Phase 1: 작업 하나의 실제 흐름

`task_3` (MID/MEDIUM) 예시:

### 작업 시작 직전
두 가지를 **하나의 원자적 쓰기**로 박는다 (`phase_boundary.py task-start`):
- `current_pre_task_sha = <HEAD SHA>` ← 크래시/검증실패 시 롤백 기준
- `tasks.task_3.timing.started = <지금 UTC>`

> **교훈:** 예전엔 따로 지시 → `timing.started`가 모든 런에서 null이 됐다. 둘을 한
> 헬퍼로 묶어 누락을 원천 차단. **타임스탬프는 손으로 절대 안 쓴다** (run-3에서
> KST를 UTC로 잘못 적어 started가 completed보다 9시간 뒤가 된 적 있음 →
> `timing_inverted`는 면제 불가 FAIL).

### Step 1 — Implementer 디스패치 (신선한 Sonnet)
프롬프트에 채워 넣는 핵심:
- 플랜의 `### Task 3:` 섹션 통째로
- **스펙은 전체가 아니라** `spec_manifest`가 가리키는 섹션만 잘라서 (토큰 절약)
- `context_slice` — 의존 작업의 `for_next_tasks` 요약만 미리 주입 (state.json 전체
  Read 회피)
- `decisions_register` — "이미 내려진 결정, 재결정 금지" 목록

Implementer는 **TDD 강제**: RED→GREEN 증거를 출력에 담아야 한다. → `timing.implementer_done`.

### Step 2 — Combined Reviewer (항상 Sonnet)
감독이 diff를 떠서 인라인 주입. Reviewer가 두 점수 반환 → 티어 계산:

| 티어 | 조건 | 행동 |
|------|------|------|
| PASS | SPEC≥0.85 AND QUALITY≥0.75 | Step 3 |
| WARN | (PASS 아님) AND SPEC≥0.70 AND QUALITY≥0.60 | 경고 기록, **재시도 없이** Step 3 |
| FAIL | 둘 중 하나가 바닥 미만 | `SPEC_FAULT`로 분기 |

FAIL 분기:
- `spec_contradicts`/`unclear` → **스펙 수정 분기** (감독이 직접 수정,
  `spec_clarifications++`, 구현자 재시도 예산 안 깎음)
- `implementer_omitted`/`none` → **표준 재시도** (`review_retries++`, 최대 3).
  직전 이슈와 ISSUE_KEY(file:line:category) 비교해 재발 시 `[RECURRING]` 라벨

→ PASS/WARN이면 `timing.reviewer_done`.

### Step 3 — Verifier (MID/HIGH만)
LOW면 건너뛰고 `low_tasks_pending_verification`에 넣어 나중에 일괄. MID/HIGH면 실행:
Acceptance Criteria 쉘부터 (전부 exit 0). PASS → `timing.verifier_done`. FAIL →
`git reset --hard <pre_sha>` 후 재디스패치 (`verifier_retries++`, 최대 3).

### Step 4 — Agent Cleanup
하나의 원자적 헬퍼(`phase_boundary.py task-complete`)로:
- `tasks.task_3` 결과 객체 기록 (status/scores/method_audit/timing)
- `timing.completed = now` 강제
- `last_completed_task` / `last_completed_at` 갱신
- `kws-cme.task_completed` emit

> compaction point면 Phase Transition으로, 아니면 다음 작업.

### 작업 키 규칙
항상 `task_<N>` (예: `task_3`). 정수(`"3"`)·자유 라벨 금지. 재작업은 `task_7_remediation`.

---

## 7. 병렬 실행 (Parallel Sub-Flow)

같은 웨이브에서 **파일이 겹치지 않는** 작업 2개 이상을 동시 실행. 핵심 보장:
**독립적 실패는 웨이브 전체를 재시작시키지 않는다.**

```
P.0  그룹 시작 SHA 기록 → current_pre_group_sha
P.1  작업마다 서브워크트리 생성 + settings.json byte-identical 복사
      (훅은 워크트리 밖 절대경로 → 경로 재작성 금지)
P.2  ★한 메시지에 N개 Agent 동시 발사★ (worktree=서브워크트리, model 반드시 설정)
P.3  결과 수집 (DONE→commit SHA, ESCALATE→보류; 하나라도 escalate면 머지 안 함)
P.4  ★범위 이탈 검사★ FILES_CHANGED ⊆ 선언 Files:, 그룹 내 중복 파일 없음
      위반 → 그룹 halt, 서브워크트리 제거, 위반 작업만 순차 재배치
P.5  ESCALATE 순차 해결
P.6  ★cherry-pick으로 부모에 병합★ (task-ID 오름차순)
P.7  작업별 Reviewer + Verifier (순차!) — FAIL 시 그 commit만 revert·재배치
P.8  작업별 Cleanup (compaction 경계는 그룹의 마지막 작업)
```

- **Implementer만 병렬, Reviewer/Verifier는 순차** (병합 후 상태 결정론 유지)
- 한 서브워크트리가 죽어도 나머지 병렬 커밋은 살아남음 (실패 격리 = 벽시계 절약)
- `parallel=off`로 전부 순차 강제 가능

---

## 8. Escalation Protocol

서브에이전트는 막히면 **추측 금지 → 반드시 ESCALATE** (type: SPEC_BLOCKER / ENV_BLOCKER / AMBIGUITY).

감독 응답:
1. 두 카운터 동시 증가 (런-레벨 `current_escalation_count`, 작업-레벨
   `tasks.task_N.escalations`). `> 3`이면 **그 작업만** SKIPPED, 런은 계속.
2. `git reset --hard <pre_task_sha>`
3. 타입별: SPEC_BLOCKER→스펙 최소 편집, AMBIGUITY→플랜에 명시적 결정,
   ENV_BLOCKER→Triage Playbook
4. Step 1로 복귀, 전 단계 재실행 (Review/Verify 건너뛰지 않음)

### 자율 해결 (v2.25)
런타임 `AMBIGUITY`/`SPEC_BLOCKER`은 SKIP·보고 대신 **자율 해결**: 가장 방어 가능한
해석 채택 → `spec_edits`에 `auto_resolved:true` 기록 → `## [AUTO-INTERPRETATION]`
노트로 재배치 → Final Report에 노출. **사용자에게 묻지 않는다.**

### 하드 halt는 오직
- **데이터 무결성 실패**: state.json 쓰기 실패, `git reset` 실패, 워크트리 없음
- **Phase 0 구조/설정 오류**: 레포 밖 경로, `Files:` 없음, task 헤더 없음

나머지는 전부 self-heal 후 진행.

---

## 9. 안전 훅 4종

**경로 불변식:** `<worktree>/.claude/settings.json`이 워크트리 안에 쓰는 유일한 파일.
훅 command는 워크트리 밖 `<orch_dir>/hooks/` 절대경로 참조 → teardown에도 생존,
`git status` 깨끗, 서브워크트리 byte-identical 복사로 충분(경로 재작성=버그).

| 훅 | 역할 |
|----|------|
| `PreToolUse`(Bash) | `rm -rf /`, 보호 브랜치 force-push, `DROP TABLE/DATABASE/SCHEMA` 차단 (exit 1). `git reset --hard`는 허용 — 복구에 필요 |
| `PostToolUse`(Edit\|Write) | `console.log/debugger/TODO/FIXME` 감지 시 exit 2 → 서브에이전트 재시도. **유일한** 디버그 게이트 (수동 grep 금지) |
| `SubagentStop` | Implementer 출력 필수 필드(STATUS/SUMMARY/FILES_CHANGED 등) 누락 시 exit 2 → 자동 재시도 |
| `Stop`(v2.26) | 세션 종료 시 모든 작업 terminal + 종료 신호면 `finalize_run --check`+`validate_state_schema` 실행, 미완료/비정규면 exit 2로 차단. fail-open(깨진 훅), fail-closed(불일치) |

4개 모두 advisory-blocking (강제이지 하드 락은 아님). settings.json은 손으로 안 쓰고
`materialize_worktree_hooks.py`가 deep-merge로 생성.

---

## 10. Phase Transition (압축 지점)

### T1.2 — Combined Transition Dispatch
옛 T1(LOW 일괄검증) + T2(문서갱신)를 **한 서브에이전트가 두 도구 호출**로 병합
(~50% 벽시계 절약). 결과 `{verify, docs}`.
- `verify` PASS → `low_tasks_pending_verification` 비움, docs 커밋 확정
- `verify` FAIL → `transition_blocked=true`, docs 커밋 보류, 실패 테스트→LOW 작업 매핑
  후 리셋·재구현·재배치 (애매하면 배치 전체 리셋, MID 취급)
- `docs` ESCALATE → `phase_docs_skipped` 기록, Phase 2가 복구

### T3 — State Anchor + Context Drop
1. 앵커 플러시 (`last_compaction_after_task`, `low_tasks_pending_verification=[]`).
   비-제로 종료 = 하드 halt
1.1 `kws-cme.compaction` emit
1.5 `decisions_register` → `DECISIONS.md` 투영 (원자적 write-then-mv)
2. **★이전 작업 컨텍스트 능동 폐기★** — raw 출력 보관 금지, 필요시 state.json 재읽기
3. `context_health` 수동 스냅샷 (관측 전용, 흐름 변경 금지 — Goodhart 가드)
3.5 `chain_trigger_eval` emit + Resume Chain 트리거 판정
4. 예산 평가: cost ≥ cap이면 warn(계속) 또는 pause(run-close blocked + HALTED 종료)

T3 state 쓰기 실패 → run-close(blocked) 후 즉시 하드 halt.

---

## 11. 디스패치 전송 방식 (dispatch_config)

각 역할 게이트는 `"p"`(headless claude -p) / `"api"`(스크립트) / `"agent"`(인-세션
Agent 도구) 중 하나. **v2.25부터 `"agent"`가 기본** (구독 풀 청구, metered 아님).

### 실패 사다리 (자율 — 사용자에게 안 물음)
```
1. 결과 없음/스키마 실패 → 같은 ROLE 1회 재시도
2. 여전히 실패 → ★agent → api 자동 폴백 (1회)★ + kws-cme.dispatch_fallback
3. api도 실패 →
   • Plan Reviewer(자문) → 경고 후 진행
   • Verifier/Docs(필수) → verification_gaps/docs_gaps 기록 + blocker emit + 진행
     → Final Report에 전용 행. 절대 침묵·halt·질문 안 함
```

> **agent 비용 관측 불가:** Agent 도구는 `usage`를 안 준다 → attached+all-agent 런은
> `cost_tracking_waived=true`. 이러면 `budget_cap_usd` 강제와 토큰 기반 Resume Chain
> 트리거도 꺼진다. 예산 강제가 필요하면 게이트를 `"api"`/`"p"`로.

---

## 12. method_audit (방법론 증거 검증)

각 작업이 **실제로 방법론을 적용했는지 증거로** 검증한다 ("주장"은 불인정).

- **채움 시점**: Phase 1 Step 4. Implementer `METHOD_AUDIT:`, Reviewer
  `REVIEW_FINDINGS:`, Verifier `commands_run` 파싱
- **required**: docs-only(`files_test==[]` 또는 모든 `.md`)면
  `[verification-before-completion]`만, 실행 코드면
  `[test-driven-development, verification-before-completion, code-review-pass]` 셋 다
- **검증**(`validate_method_audit.py`): `missing = required − applied − waived`.
  하나라도 비지 않으면 exit 1. **증거 참조(RED/GREEN/commands_run/findings_count)가
  있어야 applied 인정**
- **멀티플랜**: `--active-plan auto`면 체인의 모든 플랜 순회 (top-level만 보면 plan 1~N 누락)
- **TDD 면제**: `reason=docs-only-task|config-only-task|generated-only-task`만 허용
- **강제 위치**: Phase 2 Step 1.5. FAIL이면 `run-close` 전 하드 중단

---

## 13. state.json 구조 (Run-level vs Per-plan)

이 구분을 틀리면 멀티플랜 체인이 조용히 깨진다.

```
state.json
├── [RUN-LEVEL] 최상위 — 런 전체 공유, 체인 전환·Resume에도 보존
│   mode, active_plan, branch, worktree, orchestrator_dir, source_repo,
│   implementer_model, test_command, cost_ledger, budget_*, cost_tracking_waived,
│   dispatch_config, context_budget, timestamps, plan_chain
│
└── [PER-PLAN] <active> 아래 — 플랜마다 따로
    tasks, task_summaries, quality_trend, baseline, execution_plan,
    risk_levels, task_complexity, decisions_register, spec_manifest,
    low_tasks_pending_verification, verification_gaps, docs_gaps
```

**`<active>` 해석:**
- `plan_chain` 있으면 → `state.plan_chain[state.active_plan]` (active_plan = **정수**)
- 없으면 (단일플랜) → `state` 최상위 (active_plan = **문자열** `"plan1"`)

per-plan 필드를 멀티플랜에서 최상위에 하드코딩하면 → plan 0은 최상위, plan 1은
`plan_chain[1]`에 써져 두 트리가 갈라진다. 모든 접근은 반드시 `<active>` 경유.

**검증 3종 (Phase 2 close 전 필수):**
- `validate_state_schema.py` — 정규 형태 (비정규 키는 WARN)
- `finalize_run.py --fix` — completed_at 박힘? PENDING_BATCH 없음? cost/timing 누락은
  blocking FAIL? hooks wired?
- `validate_method_audit.py` — §12
- 하나라도 위반 시 `agentlens run-close --outcome success` 전 하드 중단

---

## 14. 멀티 플랜 체인 (`plan2=`, `plan3=`)

여러 플랜을 **순차 자동 연결**. `plan=`(0), `plan2=`(1)…

구조:
```
plan_chain[0] = {status:"running", ...채워짐}
plan_chain[1] = {status:"queued", blocked_until:"plan_chain[0].all_tasks_complete_or_skipped"}
```
Phase 0은 활성 항목만 채우고, 큐 항목은 차례가 와야 채워진다.

**Cross-Plan Trigger (Phase 2 Step -1):** plan i 완료 시 →
1. LOW 일괄검증 PASS + 모든 작업 COMPLETE/SKIPPED 확인
2. `active_plan = i+1` 스왑, `mode = "plan_chain_running"`
3. 런-레벨 임시 카운터 리셋
4. plan i+1에 대해 Phase 0 일부(Step 3,3.5,4,6) 재실행 → `plan_chain[i+1]`에 기록
5. **baseline 새로 측정** (plan i 변경이 이제 HEAD; 절대 재사용 금지)

런-레벨 인자(`implementer_model`, `parallel`, `risk`, `cost_ledger`)는 모든 플랜에
전파되며 스왑 때 리셋되지 않는다. 플랜별 다른 모델은 의도적 미지원.

---

## 15. Resume Chain (세션 이어가기)

한 헤드리스 프로세스 컨텍스트가 차기 전 **새 프로세스로 바통 터치**. (멀티플랜과
다름 — 이건 *컨텍스트 한계* 대응, 멀티플랜은 *여러 플랜 연결*.)

**트리거 (가산적, Phase Transition T3 판정):**
1. **토큰 임계치(주력)**: `session_input_tokens(=input − cached_read) ≥
   threshold_tokens(기본 102000)`. `budget_action=off`면 비활성
2. **레거시 바닥(폴백)**: compaction ≥ 2 AND COMPLETE 작업 ≥ 8 (항상 평가)

> all-agent 기본 런은 토큰 usage가 없어(`cost_tracking_waived`) 토큰 트리거 사실상
> 꺼짐 → 레거시 바닥만.

**절차:**
1. UUID 생성 → `chain_resume.session_id`
2. state 플러시 (`mode=headless_chained`). 쓰기 검증 실패 = 하드 halt. 런-레벨 비용
   필드는 그대로 자식이 읽음
3. 자식 spawn + **PID 파일 원자적 스왑**(write-then-rename) → Monitor가
   `CHAIN_HANDOFF`로 인식
4. **부모는 close-run 없이 종료** (런은 자식 안에서 생존)
5. 자식은 새 AgentLens 런 안 열고 `AGENTLENS_PARENT_RUN_ID`를 `ORCH_RUN_ID`로
   재수출해 같은 런에 계속 발행, `context_health` 스냅샷으로 경계 표시

> 폴백이다. 정상은 헤드리스 하나가 10~25개 작업 플랜을 자기 예산 안에서 완료.

---

## 16. 전 영역을 관통하는 설계 철학

| 원칙 | 구현 |
|------|------|
| prose 규율은 우회된다 | 핵심 불변식을 코드/훅/헬퍼로 강제 |
| 누락은 묶어서 막는다 | 타임스탬프·결과·이벤트를 단일 헬퍼 호출로 번들 |
| 단일 작성자 | `quality_trend`, `timing.*`는 정해진 헬퍼만 기록 |
| 주장이 아니라 증거 | method_audit은 evidence 참조가 있어야 applied |
| 관측은 흐름을 안 바꾼다 | `context_health` 등은 Goodhart 가드 (control flow 금지) |
| 추측이 위험한 곳만 멈춘다 | 런타임 모호성은 자율 해결, 데이터 무결성·구조 오류만 하드 halt |
| 조용한 성공 금지 | cost/timing/hooks 누락은 finalize에서 blocking FAIL, Stop 훅이 미완료 종료 차단 |

각 가드레일은 실제 런(run-1/2/3)에서 관찰된 회귀를 근거로 박혀 있다.

---

## 17. 더 읽을거리

- `SKILL.md` — 권위 있는 계약 (Guardrails 표가 load-bearing 요약)
- `references/phases/` — 각 Phase의 상세 절차
- `references/cross-cutting/` — state 스키마, 멀티플랜, agent-dispatch, 안전훅,
  decisions-register, agentlens emit-site
- `ARCHITECTURE.md`, `HISTORY.md`, `docs/how-it-works.md` (영문)
