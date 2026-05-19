# 사용법 — kws-claude-multi-agent-executor

이 문서는 **사람이 이 스킬을 어떻게 호출하고 운영하는지** 다룹니다. 내부 동작은 [`../ARCHITECTURE.md`](../ARCHITECTURE.md), 자세한 설계 배경은 [`./design-decisions.md`](./design-decisions.md), 실패 진단은 [`./troubleshooting.md`](./troubleshooting.md) 를 참조하세요.

---

## 1. 스킬을 호출하기 전에 준비할 것

이 스킬은 **이미 작성된 계획과 스펙**을 받아 실행합니다. 직접 계획을 만들어내진 않습니다 — 그건 사용자(또는 다른 brainstorming/planning 스킬)의 일입니다.

### 1.1. 계획 문서 (plan.md)

다음을 포함하는 markdown 파일:

```markdown
# 제목

## Phase 1: ...

### Task 0: 로깅 모듈 추가

**Files:**
- src/util/logger.ts
- src/util/logger.test.ts

**구현 노트:**
- console.log 호출을 logger.info 로 교체
- ...

## Acceptance Criteria
```bash
npm test -- src/util/logger.test.ts
```

### Task 1: ...
```

**필수 조건**:
- 각 태스크는 `### Task N: 제목` 헤더로 시작 (N은 0부터 순차 또는 의미 있는 ID)
- 각 태스크는 `**Files:**` 블록을 포함 (없으면 모호성 게이트에서 사용자에게 묻습니다)
- `Files:` 의 모든 경로는 레포 루트 내부 (`../other-repo` 같은 외부 경로는 즉시 중단)
- 선택: `## Acceptance Criteria` 코드 블록 — Verifier가 일차 PASS 조건으로 실행

**권장**:
- MID/HIGH 위험 태스크에는 Acceptance Criteria 필수 (Plan Reviewer가 BLOCKER로 잡습니다)
- 외부 자원(DB 포트, 파일 락)을 공유하는 태스크는 `serial: true` 주석으로 표시 — 병렬 그룹에서 제외됨
- 명시적 단계 경계(`## Phase 1`, `## Phase 2`)는 자동으로 컴팩션 포인트가 됨

### 1.2. 스펙 문서 (spec.md)

구현이 따라야 할 디자인 문서. 함수/타입/API 이름·시그니처·계약을 명확히. 모호하면 Reviewer 가 `SPEC_FAULT: unclear` 로 FAIL 시키고, 오케스트레이터가 스펙을 직접 편집해서 명확화합니다 (§Phase 1 Step 2 분기).

### 1.3. 환경 점검

호출 전:

- `git status` 가 깨끗할 것 (지저분하면 Phase 0에서 즉시 중단)
- 테스트 명령이 결정론적으로 실행될 것 (`Makefile`, `package.json`, `pyproject.toml`, `Cargo.toml` 중 하나에서 자동 추출)
- 베이스라인 테스트가 통과할 것 — 실패 0개가 이상적이지만, **0이 아니어도 됩니다**. 베이스라인 실패 N개는 그대로 받아들이고, Verifier 는 "그 N개를 늘리지 않으면 PASS" 규칙으로 동작합니다.

---

## 2. 호출

### 2.1. 기본 호출

```
/kws-claude-multi-agent-executor plan=docs/plans/2026-05-14-feature.md spec=docs/specs/2026-05-14-feature.md
```

### 2.2. 인자 전체 목록

| 인자 | 값 | 기본값 | 설명 |
|------|----|------|------|
| `plan=` | 경로 | (필수) | 계획 markdown |
| `spec=` | 경로 | (필수) | 스펙 markdown |
| `risk=` | `low\|mid\|high` | 자동 추론 | 모든 태스크의 위험 등급 일괄 오버라이드. **HIGH 위험으로 보이는 태스크는 silent 다운그레이드 되지 않고 경고 로그됨** |
| `docs_scope=` | `file1,file2` | `README.md,CHANGELOG.md,docs/*runbook*,docs/*operator*` | Phase 2 Docs Updater 가 갱신할 파일 집합 |
| `plan2=` | 경로 | 없음 | Plan 1 완료 후 자동으로 이어 실행할 두 번째 계획. 베이스라인은 Plan 1 결과 위에서 재측정 |
| `mode=` | `interactive\|headless` | `headless` (자동 자가 스폰) | `interactive` 면 Phase -1 자가 스폰 건너뜀, 현재 세션에서 직접 실행 |
| `parallel=` | `off` | `on` | `off` 면 모든 병렬 그룹을 싱글톤으로 — sub-worktree 생성 제약 환경(shallow clone, 낮은 디스크)에서 사용 |
| `preflight=` | `off` | `on` | Phase 0 Step 6.5 Plan Reviewer 사전 검토 건너뜀. 이미 검증된 계획의 회귀 실행용 |

### 2.3. 실행 모드 두 가지

**Headless 자가 스폰** (기본):
- 호출 즉시 Phase -1 자가 분기 발동: 현재 세션에서 worktree만 만들고, 별도 백그라운드 `claude -p` 프로세스를 띄운 뒤 종료
- 사용자는 즉시 채팅으로 돌아옴. 진행 상황은 Monitor 알림으로 들어옴 (태스크 전환마다 한 줄)
- 장점: 사용자가 다른 작업 가능, 컨텍스트 소비 X
- 단점: 디버깅이 약간 더 번거로움 (백그라운드 jsonl 파일을 tail 해야 함)

**Interactive** (`mode=interactive`):
- Phase -1 건너뜀, 같은 세션에서 모든 단계 실행
- 장점: 디버깅 직관적, 즉각 피드백
- 단점: 사용자 세션의 컨텍스트를 소비 — 10+ 태스크 계획은 컨텍스트 압박

**추천**: 5개 이하 태스크 계획이거나 디버깅 중일 때는 `interactive`. 그 외는 기본(headless).

---

## 3. 실행 중 무엇을 보게 되는가

### 3.1. Headless 모드 (기본)

호출 직후 받게 되는 출력:

```
Orchestrator running headless.
Worktree: /Users/.../worktrees/feature-20260514-143022
PID: 84291

Monitor live (stream-json events):
  tail -f .../headless.jsonl | jq -c 'select(.type=="text" or .type=="tool_use")'

Status snapshot:
  jq '{current_task, mode, completed: ...}' .../state.json

Completion check:
  test -f .../HEADLESS_DONE.txt && cat .../HEADLESS_DONE.txt
```

이후 Monitor 가 태스크 전환마다 한 줄씩 알려줍니다:

```
[14:32:17] [plan1] task_0 COMPLETE risk=low review_retries=0 | totals: 1C 0S
[14:34:42] [plan1] task_1 COMPLETE risk=mid review_retries=1 | totals: 2C 0S
[14:39:11] [plan1] task_2 SKIPPED risk=high review_retries=0 | totals: 2C 1S
...
[14:55:03] DONE: 8 tasks completed, 1 skipped, branch feature-20260514-143022
```

체인 핸드오프(긴 계획에서 헤드리스 프로세스가 컨텍스트 한계에 가까워질 때 새 프로세스로 자동 이양)도 한 줄 표시됩니다 — `CHAIN_HANDOFF: PID 84291 → 84520`.

### 3.2. Interactive 모드

오케스트레이터가 단계별로 무엇을 하는지 출력하면서 같은 세션에서 진행. 사용자는 도중에 명령을 보낼 수 있지만, 일반적으로 그냥 끝까지 두는 게 안전 (개입하면 state.json 불변식을 깰 수 있음).

### 3.3. 진행 상황 직접 확인하는 명령어

```bash
# 현재 상태 스냅샷
jq '{
  current_task,
  mode,
  active_plan,
  last_completed_task,
  completed: ([.tasks[] | select(.status=="COMPLETE")] | length),
  skipped:   ([.tasks[] | select(.status=="SKIPPED")]  | length)
}' <orch_dir>/state.json

# 마지막 5개 태스크의 점수
jq '.tasks | to_entries[-5:] | map({key, status: .value.status, spec: .value.spec_score, quality: .value.quality_score, tier: .value.review_tier})' <orch_dir>/state.json

# 라이브 이벤트 스트림 (headless)
tail -f <orch_dir>/headless.jsonl | jq -c 'select(.type=="text")'

# 완료 여부
test -f <orch_dir>/HEADLESS_DONE.txt && cat <orch_dir>/HEADLESS_DONE.txt
test -f <orch_dir>/HEADLESS_HALTED.txt && cat <orch_dir>/HEADLESS_HALTED.txt  # 실패 시
```

---

## 4. 완료 후 무엇을 받게 되는가

### 4.1. 최종 요약 리포트

Phase 2 Step 2 가 markdown 표를 출력 (interactive 모드는 채팅에, headless 모드는 `HEADLESS_DONE.txt` 와 `summary.md` 에):

```markdown
## Execution Summary

**Plan:** docs/plans/...
**Spec:** docs/specs/...
**Branch:** feature-20260514-143022
**Worktree:** /Users/.../worktrees/feature-20260514-143022
...

### Tasks
| Task | Status | Risk | Size | Spec | Quality | Tier | Escalations | ... |
|------|--------|------|------|------|---------|------|-------------|-----|
| Task 0 | COMPLETE | low | SMALL | 0.95 | 0.90 | PASS | 0 | ... |
| Task 1 | COMPLETE | mid | MEDIUM | 0.80 | 0.70 | WARN | 0 | ... |
| Task 2 | SKIPPED | high | LARGE | — | — | — | 3 | escalation cap |
...

### WARN-tier tasks (P4)
- task_1 — spec=0.80, quality=0.70 — warnings: error handling 누락, 변수명 모호

### Quality trend
- 처음 5 평균: 0.88
- 마지막 5 평균: 0.82
- Delta: -0.06
- 상태: stable

### Cleanup Status
- Worktree: **active** — `feature-20260514-143022` at `<path>`. 머지 또는 삭제는 사용자 결정.
- 디버그 아티팩트: 없음
```

### 4.2. 산출물의 위치

- **코드 변경**: `<worktree_path>/` (별도 git worktree). 메인 체크아웃에는 영향 없음.
- **커밋**: 브랜치 `<plan-slug>-<timestamp>` 위에. `feat:` (구현)와 `chore:` (오케스트레이터 상태)가 번갈아.
- **state.json**: `<orch_dir>/state.json` — 사후 디버깅·재개의 진실의 출처.
- **이벤트 스트림 (v2.17 cutover)**: AgentLens 의 `kws-cme.*` 이벤트 타입. 조회: `agentlens events --run <ORCH_RUN_ID> --type 'kws-cme.*'`. 크로스-실행 제도적 메모리는 AgentLens 가 보존. `state.json.agentlens_orchestration_run` 에 run id 가 기록됨.
- **레거시 학습 로그 (읽기 전용, 역사적)**: `~/.claude/learning/kws-claude-multi-agent-executor/runs/<YYYY-MM-DD>/<run_id>/` — v2.17 cutover (Task 11) 이전 실행만 존재. 신규 실행은 작성하지 않음. 레거시 ↔ AgentLens 패리티 검증: `python3 scripts/compare_agentlens_events.py <legacy events.jsonl> <agentlens run dir>`.
- **서브에이전트 결과**: `<orch_dir>/{verifier,docs}_results/` — 헤드리스 JSON 결과 파일들.

### 4.3. 머지하기

스킬은 **worktree를 자동 삭제하지도, 메인에 머지하지도 않습니다**. 사용자가 결정:

```bash
# 검토
cd <worktree_path>
git log --oneline main..HEAD
git diff main..HEAD

# 메인으로 머지 (예: fast-forward)
cd <repo_root>
git merge --ff-only <branch_name>

# 또는 squash로
git merge --squash <branch_name> && git commit

# worktree 정리 (선택)
git worktree remove <worktree_path>
git branch -d <branch_name>  # 머지 후
```

---

## 5. 시나리오별 사용 패턴

### 5.1. 작고 명확한 계획 (5개 이하 태스크)

```
/kws-claude-multi-agent-executor plan=... spec=... mode=interactive
```

- `interactive` 로 직접 봅니다 — headless 오버헤드(자가 스폰, 모니터 셋업)가 작업 시간을 추월할 수 있음.
- 모든 태스크가 LOW면 Verifier 가 마지막에 한 번만 배치로 돈다 — 빠름.

### 5.2. 중간 크기 계획 (10–25 태스크)

```
/kws-claude-multi-agent-executor plan=... spec=...
```

- 기본 (headless 자가 스폰). 사용자는 다른 작업하면서 Monitor 알림으로 진행 확인.
- Phase 0 가 자동으로 컴팩션 포인트를 계산해서 중간중간 컨텍스트를 정리.

### 5.3. 큰 계획 (25+ 태스크) 또는 두 단계 마이그레이션

```
/kws-claude-multi-agent-executor plan=phase1.md spec=spec.md plan2=phase2.md
```

- `plan2=` 로 두 계획을 체이닝. Plan 1 완료 + LOW 배치 sweep 통과 후 자동으로 Plan 2 시작.
- Plan 2 는 Plan 1 의 결과를 베이스라인으로 재측정. 같은 worktree, 같은 학습 로그 실행 ID.
- 단일 헤드리스 서브프로세스가 컨텍스트 한계에 닿으면 **Resume Chain** 이 발동해서 새 프로세스로 자동 이양 (`CHAIN_HANDOFF` 알림).

### 5.4. 디버깅·반복

```
/kws-claude-multi-agent-executor plan=... spec=... mode=interactive parallel=off preflight=off
```

- `parallel=off` 로 sub-worktree 변수 제거.
- `preflight=off` 로 이미 검증된 계획의 Plan Reviewer 건너뜀.
- `interactive` 로 모든 단계 직접 관찰.

### 5.5. 의도적인 빠른 회귀 검증 (eval)

`evals/run.sh <fixture>` 를 사용 — 이건 사용자 호출이 아니라 픽스처 기반 하네스. 자세히는 [`../evals/README.md`](../evals/README.md).

---

## 6. 자주 일으키는 실수

| 실수 | 결과 | 해결 |
|------|------|------|
| `git status` 더러운 채로 호출 | Phase 0 Step 1에서 즉시 중단 | 커밋하거나 stash |
| 계획에 `Files:` 블록 없는 태스크 | Phase 0 Step 3.5 모호성 게이트가 사용자에게 질문 | 미리 모든 태스크에 Files 블록 추가 |
| 계획이 `../other-repo/` 같은 외부 경로 참조 | Phase 0 Step 3.5에서 즉시 중단 | 레포 내 경로로 수정 (또는 그 작업을 다른 스킬로 분리) |
| MID/HIGH 태스크에 Acceptance Criteria 없음 | Plan Reviewer 가 BLOCKER로 잡고 사용자에게 질문 | `## Acceptance Criteria` 코드 블록 추가 — 일차 PASS 조건 |
| 같은 파일을 여러 LOW 태스크에서 만짐 | LOW→MID 자동 승격, 배치 Verifier 안 됨 | 의도된 동작이지만, 의도적으로 LOW를 유지하려면 파일 분리 |
| 외부 자원(같은 DB 포트) 공유하는 병렬 태스크 | 스킬이 자동 감지 못함, 런타임 충돌 | 계획에서 한쪽에 `serial: true` 주석 |
| 헤드리스 모드에서 진행 안 보임 | Monitor 알림 수신을 기다리거나 직접 `tail -f` | 위 §3.3 명령어들 |
| 도중에 worktree를 직접 만져서 state.json 깨짐 | 다음 단계가 "state file corrupted" 로 중단 | 실행 중에는 worktree 만지지 말 것. 만져야 하면 일단 중단하고 끝나길 기다리세요 |

---

## 7. 재개 (Resume)

`<orch_dir>/state.json` 이 존재하면 스킬을 다시 호출했을 때 **자동으로 재개**합니다.

조건:
- `schema_version: "2"` 인 유효한 JSON
- `state.branch` 와 `state.worktree` 가 현재와 일치

재개 동작:
- Phase 0 Step 1–7 (셋업)을 건너뜀 — 이미 끝났음.
- 기록된 `current_task` / `current_step_within_task` 에서 Phase 1 시작.
- 같은 학습 로그 실행 ID 에 이어 작성 (헤드리스 환경변수 전파 시).

손상된 state.json (빈 파일, 깨진 JSON):
- 자동 덮어쓰기 안 함. 사용자에게 수동 검사 요청 후 중단.

---

## 8. 더 자세히

- 내부 단계 흐름: [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §3, §4
- 실행 시뮬레이션: [`./how-it-works.md`](./how-it-works.md)
- 실패한 실행 진단: [`./troubleshooting.md`](./troubleshooting.md)
- 왜 이런 인자/모드/플래그인가: [`./design-decisions.md`](./design-decisions.md)
- 알려진 한계: [`./risks-and-limitations.md`](./risks-and-limitations.md)
- 학습 로그 분석: [`../references/learning-log.md`](../references/learning-log.md)
