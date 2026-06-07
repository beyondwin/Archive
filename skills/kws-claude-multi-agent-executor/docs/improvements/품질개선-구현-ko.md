# 품질 개선 구현 명세 — kws-claude-multi-agent-executor

> 짝 문서: [`품질개선-플랜-ko.md`](./품질개선-플랜-ko.md). 항목 번호(I1…I12)는 플랜과
> 일치. 이 문서는 **무엇을 어디에 어떻게** 바꾸는지의 구현 레벨 명세다.
>
> 표기: `<orch_dir>` = `$HOME/.claude/orchestrator/<RUN_ID>/`,
> `<active>` = 단일플랜이면 `state`, 멀티플랜이면 `state.plan_chain[state.active_plan]`.
> 모든 신규 state 필드는 **run-level vs per-plan 분류를 반드시 지킨다**
> (state-schema.md §"Run-level vs per-plan").

---

## 0. 공통 사항

### 0.1 신규/변경 산출물 개요

| 항목 | 신규 파일 | 변경 파일 | state 델타 |
|------|-----------|-----------|------------|
| I1 | — | phase-1-task-cycle.md, SKILL.md(가드레일) | `verification_gaps`/`docs_gaps` 재사용 |
| I2 | `scripts/emit_event.py`(또는 phase_boundary 확장) | phase_boundary.py, SKILL.md:258 영역 | 파일 sink만(스키마 무변) |
| I3 | — | phase_boundary.py(task-complete), phase-1-task-cycle.md | per-plan `tasks.task_N.retry_trace[]` |
| I4 | `scripts/build_final_report.py`, `test_build_final_report.py` | phase-2-finalization.md(Step 2) | 산출물 `run_report.json`(state 무변) |
| I5 | `scripts/build_context_slice.py`, `test_build_context_slice.py` | phase-1-task-cycle.md(Step 1) | 없음 |
| I6 | — | SKILL.md(가드레일), phase-1-task-cycle.md, phase-1-escalation.md | 없음(spec_manifest 재사용) |
| I7 | — | build_final_report.py, finalize_run.py, test_finalize_run.py | `run_report.json.failure_summary` |
| I8 | — | phase-1-escalation.md, phase-transition.md, state_set 경유 | run-level `auto_resolved_count` |
| I9 | — | phase-1-task-cycle.md(Step 2/3) | per-plan `tasks.task_N.forced_verify`(bool) |
| I10 | `scripts/state_resume_digest.py`, 짝 test | phase-0-setup.md(resume), phase-minus-1 | 없음 |
| I11 | — | phase-transition.md(T3) | 없음(규율 명문화) |
| I12 | — | (기록만) docs/experiments/v2.29-quality-uplift/ | 없음 |

### 0.2 스키마/계약 동기화 (모든 신규 필드 공통)

1. `references/cross-cutting/state-schema.md` 의 run-level/per-plan 표와 JSON 샘플에
   필드 추가.
2. `scripts/validate_state_schema.py` 에 타입/기본값 허용 규칙 추가(엄격 거부 아님 —
   기본값 부재 허용, 존재 시 타입 검증).
3. `schema_version`은 **올리지 않는다**(전부 additive, 기본값 부재=하위호환). 마이그레
   이션 셰임 불필요.

---

## I1. retry 소진 → SKIP-and-continue 정렬 [P0, 축 B]

### 의도
review/verifier retry 캡 도달을 "halt, manual intervention"에서 escalation-cap과
동일한 **SKIP + gap 기록 + 다음 task 진행**으로 바꾼다. 캡 자체(3회)는 유지.

### 변경: `references/phases/phase-1-task-cycle.md`
- Step 2(Combined Reviewer) 표준 retry 분기, `review_retries > 3` 처리:
  - 기존: `halt. Manual intervention required.`
  - 신규:
    ```
    review_retries > 3 →
      1. task_N.status = SKIPPED, skip_reason = "review_retries_exhausted"
      2. <active>.verification_gaps.append({task: task_N, kind: "review",
         last_issues: current_previous_issues, attempts: review_retries})
      3. emit kws-cme.blocker {task, reason: "review_retries_exhausted"} (+ events.jsonl tee, I2)
      4. SKIPPED 전파: 이 task에 의존하는 미착수 task는 phase-0-setup:291 전파 규칙 적용
      5. 다음 task로 진행 (run halt 아님)
    ```
- Step 3(Verifier) `verifier_retries > 3` 도 동일 패턴(`kind: "verify"`,
  `skip_reason = "verifier_retries_exhausted"`). **단, reset 규율 유지**:
  SKIP 직전에도 마지막 `git reset --hard <pre_task_sha>` 를 수행해 워킹트리를
  pre-task 상태로 되돌린 뒤 SKIPPED 마킹(부분 변경 잔존 금지).

### 변경: `SKILL.md` 가드레일 표
- "Max 3 review retries per task" / "Max 3 verifier retries per task" 행의
  "halts that task" 문구를 "→ SKIP + records verification_gaps + continues
  (v2.29 I1; run does not halt)" 로 갱신.

### 근거/주의
- 이미 D003 갭마커 기계(`verification_gaps`/`docs_gaps`)와 escalation-cap SKIP
  전파가 존재 → 신규 기계 없이 정렬만. (phase-1-escalation:41-49)
- halt 경계는 유지: data-integrity + Phase-0 malformed-input 만 run halt.

### 수용 기준
- retry 3회 초과 task가 run을 멈추지 않고 SKIPPED로 기록되며 후속 task가 진행됨.
- `verification_gaps`에 해당 항목이 남고 Final Report/`run_report.json`에 렌더됨.
- SKIP 직전 reset로 워킹트리 clean.

---

## I2. 로컬 `events.jsonl` tee [P0, 축 C]

### 의도
AgentLens 도달성과 무관하게 모든 boundary emit을 `<orch_dir>/events.jsonl` 에
append. **오케스트레이터 단일 writer**(AGENTS.md 준수 — sub-agent는 직접 안 씀).

### 구현 선택지 (권장: phase_boundary 확장)
`phase_boundary.py` 의 `phase-emit`/`task-start`/`task-complete` 가 이미 emit을
생성하므로, 동일 지점에서 로컬 파일에도 tee 하는 것이 최소 변경.

- 새 내부 함수 `_tee_event(orch_dir, event: dict)`:
  ```python
  def _tee_event(orch_dir, event):
      path = os.path.join(orch_dir, "events.jsonl")
      line = json.dumps({**event, "ts": _now_iso()}, ensure_ascii=False)
      with open(path, "a", encoding="utf-8") as f:   # append, flock 불필요(단일 writer)
          f.write(line + "\n")
  ```
- 모든 emit 경로(AgentLens 성공/실패/CLI 부재 무관)에서 `_tee_event` 호출.
  AgentLens CLI 호출은 기존대로 best-effort(`2>/dev/null`), tee는 **항상** 수행.
- 이벤트 스키마(최소): `{type, task, phase, plan_index, payload, ts}`.
  `type`은 기존 `kws-cme.*` 와 1:1.

### 대안
독립 `scripts/emit_event.py <orch_dir> <type> --json '<payload>'` 를 만들고
phase_boundary가 호출. 셸/jq 경로(Monitor 등)에서도 재사용 가능. 단 호출지점 분산.
→ **phase_boundary 확장 권장**(emit 단일화).

### 변경: `SKILL.md:258` 인근 + agentlens-emit-sites.md
- "AgentLens emit은 best-effort; 추가로 `<orch_dir>/events.jsonl` 에 항상 tee된다
  (오케스트레이터 단일 writer, replay 용)" 명문화.
- v2.17에서 제거된 병렬 sink와의 차이(= fallback tee, 단일 writer) 한 줄 주석.

### 수용 기준
- AgentLens CLI 미설치 환경에서도 run 종료 후 `events.jsonl` 에 phase_0_started …
  phase_2_complete 타임라인이 순서대로 남음.
- sub-agent는 이 파일에 직접 쓰지 않음(쓰기 호출지점이 phase_boundary뿐).

---

## I3. per-task `retry_trace[]` [P0, 축 C]

### 의도
"왜 각 retry가 났는지"를 append-only로 보존(덮어쓰기 금지).

### state 델타 (per-plan)
`<active>.tasks.task_N.retry_trace`: 기본 `[]`, 원소:
```json
{"attempt": 2, "kind": "review", "fault": "spec_unclear",
 "recurring_keys": ["src/a.ts:42:logic"], "tier": "WARN", "ts": "..."}
```
- `kind ∈ {review, verify}`; `fault`는 SPEC_FAULT 클래스 또는 verifier category;
  `recurring_keys`는 RECURRING 판정의 ISSUE_KEY 배열.

### 변경: `scripts/phase_boundary.py`
- `task-complete` 및 retry 기록 경로에서 `current_previous_issues` 를 덮어쓰기
  *전에* 해당 attempt를 `retry_trace`에 append. 단일 writer 보장(헬퍼 내부).
- 기존 `current_previous_issues`(다음 retry 입력용 휘발 버퍼)는 그대로 유지 —
  `retry_trace`는 누적 감사 로그로 별도.

### 변경: `references/phases/phase-1-task-cycle.md`
- Step 2/3 retry 분기에 "각 retry attempt는 `phase_boundary` 경유로 `retry_trace`에
  append된다(오케스트레이터 in-context 누적 금지)" 명시.

### 수용 기준
- 3회 retry한 task의 `retry_trace.length == 3`, 각 원소에 fault/tier 존재.
- I4 리포트가 task별 retry 사유를 렌더.

---

## I4. `build_final_report.py` → 마크다운 + `run_report.json` [P1, 축 A+C]

### 의도
최대 end-run 컨텍스트 버스트(수작업 취합)를 헬퍼로 이전 + 머신리더블 리포트 산출.

### 신규: `scripts/build_final_report.py`
```
usage: build_final_report.py <state.json> [--out-md <path>] [--out-json <path>]
                             [--orch-dir <dir>]
exit: 0 정상 / 2 state 파싱 불가
```
- 입력: state.json(+ 선택 `events.jsonl`, `verifier_results/`, `docs_results/`).
- 멀티플랜이면 `plan_chain[*]` 전체 순회(`query_state.sh` 의 `$ACTIVE` 디스패치 규칙
  동일 적용).
- 출력 1 — 마크다운: `phase-2-finalization.md` 의 `## Execution Summary` 템플릿을
  **그대로** 생성(현 prose와 1:1; 회귀 방지 위해 레이아웃 보존).
- 출력 2 — `<orch_dir>/run_report.json`:
  ```json
  {
    "run_id": "...", "schema": "run_report/1",
    "mode": "...", "plans": [{"index":0,"plan_path":"...","status":"COMPLETE"}],
    "tasks": [{"id":"task_0","plan_index":0,"status":"COMPLETE","risk":"MID",
               "tier":"PASS","spec_score":0.91,"quality_score":0.82,
               "review_retries":1,"verifier_retries":0,
               "retry_trace":[...],"timing":{...},"skip_reason":null}],
    "quality": {"trend":[...],"delta":0.04,"warn_count":2},
    "gaps": {"verification_gaps":[...],"docs_gaps":[...]},
    "autonomy": {"auto_resolved_count":3,"escalations_total":1},
    "cost": {"waived":true,"reason":"agent-dispatch-no-usage","totals":{...}},
    "failure_summary": { /* I7가 채움 */ },
    "generated_at": "..."
  }
  ```

### 변경: `references/phases/phase-2-finalization.md` Step 2
- "오케스트레이터가 필드를 수작업 취합" → "`build_final_report.py` 를 실행하고
  생성된 마크다운을 그대로 출력, `run_report.json` 을 `<orch_dir>`에 둔다." 로 교체.
- 오케스트레이터는 헬퍼 stdout(마크다운)만 컨텍스트에 들임(state 대량 재독 제거).

### 신규 테스트 `scripts/test_build_final_report.py`
- 단일/멀티플랜 fixture에서 마크다운 레이아웃이 기존 템플릿과 일치(스냅샷),
  `run_report.json` 스키마 키 존재, gaps/retry_trace 반영.

### 연계
- `aggregate_runs.py` 가 `run_report.json` 을 직접 소비하도록 입력 경로 추가
  (별도 PR 가능, 본 항목은 산출까지).

### 수용 기준
- 동일 state에서 헬퍼 마크다운 == 기존 수작업 리포트(스냅샷 동등).
- `run_report.json` 이 생성되고 `validate` 가능(키 누락 없음).

---

## I5. `build_context_slice.py` 헬퍼 [P1, 축 A]

### 의도
매 task in-context로 도출하던 `{context_slice}` 를 헬퍼로 이전.

### 신규: `scripts/build_context_slice.py`
```
usage: build_context_slice.py <state.json> --task <task_id> [--plan-index N]
stdout: 준비된 context_slice 텍스트(sub-agent 프롬프트에 그대로 삽입)
```
- 도출 내용(현 phase-1-task-cycle:89-132 로직 1:1 이식):
  - 의존 task들의 `task_summaries` 발췌
  - `global_constraints.shared_files` 중 본 task 관련 항목
  - 해당 task의 risk/complexity, RECURRING 컨텍스트
- `build_spec_manifest.py` 와 동일한 호출 관례/에러 모델 따름.

### 변경: `references/phases/phase-1-task-cycle.md` Step 1
- "오케스트레이터가 슬라이스를 도출" → "`build_context_slice.py --task task_N` 출력을
  Implementer 프롬프트 `{context_slice}` 자리에 삽입" 으로 교체. 도출 의사코드 블록은
  헬퍼 docstring으로 이동(문서 본문에서 제거 → 컨텍스트 절감).

### 신규 테스트
- 의존성 있는 task에서 선행 task_summaries가 포함되는지, shared_files 필터가 맞는지.

### 수용 기준
- 헬퍼 출력이 기존 in-prose 도출과 의미적으로 동등(같은 의존/제약 포함).
- phase-1-task-cycle.md 라인 수 감소(도출 블록 제거 확인).

---

## I6. 스펙 편집 후 변경 섹션만 재독 [P1, 축 A]

### 의도
편집 후 전체 스펙 재독 → `spec_manifest` 의 변경 섹션 범위만 재독.

### 변경: `SKILL.md` 가드레일
- "Re-read docs after every update" 행:
  "→ 변경된 spec_manifest 섹션 범위만 재독(전체 재독 아님). plan 무결성에 영향 주는
  편집은 인접 섹션 포함." 로 정밀화.

### 변경: `references/phases/phase-1-task-cycle.md`(spec-edit 브랜치, ~242) + `phase-1-escalation.md`(~104)
- "re-read the full spec" → "re-read `spec_manifest.sections[<edited_sids>]` 범위
  (+ 의존 섹션). 편집이 manifest 구조 자체를 바꾼 경우에 한해 `build_spec_manifest.py`
  재실행 후 변경분만 재독." 로 교체.
- 안전장치: 편집이 섹션 경계/번호를 바꾸면 manifest를 재생성(부분 재독의 전제가
  깨지지 않도록). 이때만 전체 manifest 재계산(스펙 본문 전체를 컨텍스트에 들이지는
  않음 — manifest는 슬라이스 인덱스).

### 수용 기준
- 한 섹션만 편집한 시나리오에서 오케스트레이터가 전체 스펙이 아닌 해당 섹션만 재독.
- manifest 구조 변경 편집에서는 재생성 경로가 동작.

---

## I7. `failure_summary` 롤업 [P1, 축 C]

### 의도
실패 신호를 클래스별로 롤업해 `run_report.json` 에 단일 블록으로.

### 산출 스키마 (`run_report.json.failure_summary`)
```json
{
  "by_class": {
    "review_retries_exhausted": 1,
    "verifier_retries_exhausted": 0,
    "spec_unclear": 2,
    "env_blocker": 0,
    "verification_gap": 1,
    "docs_gap": 0
  },
  "auto_resolved": 3,
  "escalations": [{"task":"task_4","type":"AMBIGUITY","resolved":"auto"}],
  "skipped_tasks": [{"task":"task_7","reason":"review_retries_exhausted"}]
}
```
입력 소스: `verification_gaps`/`docs_gaps`, verifier category, escalation 기록,
`auto_resolved_count`(I8), `retry_trace`(I3) 의 fault 집계.

### 구현
- `build_final_report.py` 가 롤업 계산해 `run_report.json` 에 포함.
- `finalize_run.py` 는 **읽기 전용 검증만**: `failure_summary` 가 state의 gaps와
  불일치하면 WARN(`failure_summary_mismatch`). (FAIL 아님 — 리포트 보조 신호.)

### 변경: `scripts/test_finalize_run.py`
- gaps 있는 fixture에서 `failure_summary.by_class` 합이 gaps 수와 일치하는 케이스.

### 수용 기준
- gaps/escalation/skip이 있는 run에서 `failure_summary` 가 정확히 집계됨.

---

## I8. run-level `auto_resolved` 임계 표면화 [P2, 축 B]

### state 델타 (run-level)
`state.auto_resolved_count`: int, 기본 0. (run-level — 체인/Resume 보존,
state-schema.md run-level 표에 추가.)

### 변경: `references/phases/phase-1-escalation.md`
- D003 자율 재해석이 발생할 때마다 `state_set.py` 경유로 `auto_resolved_count += 1`
  + `retry_trace`/이벤트에 사유 기록.

### 변경: `references/phases/phase-transition.md`(T3)
- compaction 시점에 `auto_resolved_count > THRESHOLD`(기본 5, run 규모 비례 권장)면
  **신호로 표면화**: context_health 스냅샷 옆에 "high auto-resolution" 경고 라인 +
  이벤트 emit. **halt 아님** — 관측 신호(원칙 3.1: 자율 유지).

### 수용 기준
- 다수 재해석 run에서 카운트가 누적되고 임계 초과 시 compaction 로그/이벤트에 경고가
  남되 run은 계속 진행.

---

## I9. WARN+HIGH+저점수 → 1회 추가 Verifier [P2, 축 B]

### state 델타 (per-plan)
`<active>.tasks.task_N.forced_verify`: bool, 기본 false(중복 강제 방지 가드).

### 변경: `references/phases/phase-1-task-cycle.md`
- Step 2(Combined Reviewer) 후 정책:
  ```
  if tier == WARN and risk == HIGH and quality_score < 0.70 and not forced_verify:
      forced_verify = true
      → Step 3(Verifier) 1회 강제 실행 (기존 verifier_retries 캡 안에서 카운트)
  ```
- 이미 MID/HIGH는 Verifier를 거치므로, 이 정책은 주로 "HIGH인데 WARN으로 통과하려는"
  경계 케이스를 잡는다. 추가 패스는 **조건 충족 시 1회만**(비용 가드, 원칙 3.1).

### 수용 기준
- WARN+HIGH+score<0.70 task가 추가 Verifier 1회를 받고, 통과 시 PASS로 승급/실패 시
  기존 retry/SKIP 경로로.
- 조건 미충족 task는 추가 패스 없음(비용 불변).

---

## I10. `state_resume_digest.py` [P2, 축 A]

### 신규: `scripts/state_resume_digest.py`
```
usage: state_resume_digest.py <state.json>
stdout: 라이브 카운터 + 포인터만 (전체 state 아님)
```
출력 예:
```json
{"mode":"...","active_plan":0,"current_task":7,"current_step_within_task":1,
 "last_completed_task":"task_6","tasks_total":12,"tasks_done":6,"tasks_skipped":1,
 "pending_verification":["task_3"],"worktree":"...","orchestrator_dir":"...",
 "test_command":"...","gaps":{"verification":1,"docs":0}}
```

### 변경: `references/phases/phase-0-setup.md`(resume 프로토콜) + `phase-minus-1-args-and-spawn.md`(Resume Chain)
- "전체 state.json 로드(Step, ~27)" → "`state_resume_digest.py` 로 다이제스트만 로드,
  세부는 필요 시 `<active>` 경로로 just-in-time 재독." 으로 교체.
- 단일 소스 원칙 유지: 다이제스트는 **편의 읽기**이며 권위는 여전히 state.json
  (쓰기는 항상 헬퍼 경유).

### 수용 기준
- 긴 체인 run resume에서 오케스트레이터가 전체 state가 아닌 다이제스트로 부팅,
  이어지는 task 진행에 문제 없음.

---

## I11. 압축 규율 명문화 (keep_first 고정 + 직전 task tool-result 드롭) [P2, 축 A]

### 변경: `references/phases/phase-transition.md` T3
- "State Anchor + Context Drop" 절에 명시 규칙 추가:
  1. **keep_first 고정**: plan(또는 plan 다이제스트)과 `state_resume_digest` 출력은
     압축 대상에서 제외(절대 요약/드롭 금지) — OpenHands keep_first 등가.
  2. **직전 task tool-result 드롭**: 직전 task의 sub-agent 원문/파일 읽기/Verifier
     출력 블록은 명시적으로 컨텍스트에서 제거(요약은 state에 이미 존재).
  3. 압축 후에는 state.json/다이제스트가 진실원(SKILL.md:"State file is authoritative"
     와 일치).
- 이는 Anthropic context-editing의 **인세션 등가물**이다(API beta 헤더를 못 켜는
  현 실행 형태의 대체).

### 수용 기준
- 압축 직후에도 plan/state 다이제스트가 컨텍스트에 남고, 직전 task 원문은 사라짐.
- 회귀: 압축 후 다음 task 디스패치가 state만으로 정상 구성.

---

## I12. (전략, 기록만) Agent SDK 네이티브 context-editing + memory tool [P2, 선택]

- **결정**: 현 Claude Code 세션 실행 형태에서는 API beta 헤더
  (`context-management-2025-06-27`)를 직접 켤 수 없어 **미적용**. 근시일 효과는
  I11(인세션 등가)로 확보.
- **트리거 조건**: executor를 Claude Agent SDK 앱으로 포팅하기로 결정할 경우.
- **그때 채택**: context-editing(stale tool-result 자동 클리어; 100-turn eval 토큰
  84% 절감 보고)과 file-based memory tool(create/read/update/delete). state.json은
  자연스럽게 memory tool의 외부 메모리로 매핑.
- 본 문서/실험 레코드에 의사결정으로만 보존.

---

## 4. 롤아웃 순서 & 버전

```
v2.29.0 (P0): I1, I2, I3
v2.29.1 (P1): I4, I5, I6, I7   (I4→I7→aggregate 직결)
v2.29.2 (P2): I8, I9, I10, I11 (I12 기록)
```

각 묶음 채택 절차:
1. 신규 스크립트 + 짝 `test_*.py` 작성, `references/`·`SKILL.md` 편집.
2. `cd skills/kws-claude-multi-agent-executor && ./evals/run.sh` + 관련
   `python -m pytest scripts/test_*.py` 통과.
3. 신규 state 필드는 `validate_state_schema.py` + `state-schema.md` 동기화.
4. `docs/experiments/v2.29-quality-uplift/` 에 실험 레코드(가설/변경/fixture 결과).
5. `docs/CHANGELOG.md` 갱신.

---

## 5. 리스크 & 완화

| 리스크 | 완화 |
|--------|------|
| I1 SKIP 전파가 의존 트리를 과도 SKIP | escalation-cap과 동일 전파 규칙 재사용(신규 거동 없음) + SKIP 전 reset로 트리 clean |
| I4 헬퍼 마크다운이 기존 리포트와 미세 차이 | 스냅샷 테스트로 1:1 고정, 차이 발생 시 fixture 기준 정렬 |
| I6 부분 재독이 manifest 구조 변경 편집을 놓침 | "구조 변경 시 manifest 재생성" 안전장치 |
| I2 events.jsonl 파일 비대 | append-only + 라인 단위 JSON, run 종료 후 `<orch_dir>` 내 보존(워크트리 오염 없음) |
| 신규 필드가 구버전 state 읽기 깨뜨림 | 전부 additive·기본값 부재 허용, schema_version 불변 |
| 오케스트레이터 프롬프트 변경의 emergent 거동 | fixture eval 통과를 채택 게이트로(Anthropic 경고 반영) |

---

## 6. 수용 체크리스트 (묶음별 DoD)

- **v2.29.0**: AgentLens 없는 환경에서 `events.jsonl` 타임라인 생성 / retry 3회 초과
  task가 run을 멈추지 않고 SKIPPED+gap / `retry_trace`에 attempt별 fault 기록.
- **v2.29.1**: `build_final_report.py` 마크다운이 기존과 스냅샷 동등 + `run_report.json`
  생성 / `build_context_slice.py` 출력이 in-prose 도출과 동등 / 부분 스펙 재독 동작 /
  `failure_summary` 집계 정확.
- **v2.29.2**: `auto_resolved_count` 누적·임계 표면화(halt 없음) / WARN+HIGH+저점수
  추가 Verifier 1회 / resume 다이제스트 부팅 / 압축 후 plan·state 잔존·직전 원문 제거.
