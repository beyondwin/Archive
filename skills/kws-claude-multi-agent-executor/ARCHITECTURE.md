# Architecture — kws-claude-multi-agent-executor

이 스킬이 위에서 아래로 어떻게 동작하는지. 런타임 명령어는 `SKILL.md`, 버전 이력은 `HISTORY.md`, 실험 기록은 `docs/experiments/` 참조.

**이 파일을 갱신할 때**: [§13 갱신 프로토콜](#13-갱신-프로토콜) 참조.

---

## 1. 스킬이 하는 일

계획 문서 + 스펙 문서를 입력받아 계획의 모든 태스크를 처음부터 끝까지 **자율적으로** 실행합니다. 태스크 사이에 사용자 승인을 받지 않습니다. 스킬이 전체 딜리버리 사이클을 주도합니다: 코드 작성, 코드 리뷰, 테스트 검증, 문서 갱신, 반복.

입력:
- `plan=<경로>` — `### Task N:` 섹션들을 가진 markdown 계획. 각 섹션은 `**Files:**` 를 선언하고, 선택적으로 `## Acceptance Criteria` 를 포함.
- `spec=<경로>` — 구현이 따라야 할 디자인 스펙.
- 선택: `risk=low|mid|high` (태스크별 위험 등급 일괄 오버라이드), `docs_scope=...`.

출력: 격리된 worktree 위에 만들어진 일련의 커밋과 최종 요약 리포트. 실행 동안 메인 브랜치는 절대 변경되지 않습니다.

## 2. 오케스트레이터-워커 패턴

Anthropic이 정형화한 멀티 에이전트 토폴로지. Opus 오케스트레이터 한 명이 새로 생성되는 Sonnet 서브 에이전트 여러 명을 지휘합니다.

```
                Opus 오케스트레이터 (단일 세션)
                      │
   ┌─────┬────────────┼─────────────┬──────────────┐
   │     │            │             │              │
 Plan   Implementer  Combined    Verifier       Docs Updater
 Reviewer (Sonnet,   Reviewer    (Sonnet,        (Sonnet,
 (Sonnet, fresh)     (Sonnet,    headless)       headless)
 preflight)          fresh)
                      │
                state.json (외부 메모리)
                git worktree (격리된 작업 공간)
```

**왜 오케스트레이터-워커이고 다른 토폴로지가 아닌가**:
- 단일 세션 오케스트레이터가 50+ 태스크 계획을 컨텍스트를 다 쓰지 않고 실행할 수 있는 이유는 서브 에이전트가 *요약*만 돌려주기 때문입니다. 오케스트레이터는 원본 작업물을 자기 버퍼에 누적하지 않습니다.
- 새로 생성된 서브 에이전트는 사전 정보가 없어서 → 드리프트가 적고 태스크별 결정론이 강합니다.
- 잘못 행동하는 서브 에이전트(에스컬레이션, 형식 깨진 출력)는 오케스트레이터 경계에서 포착되어 이후 태스크를 오염시키지 않습니다.

**오케스트레이터가 절대 하지 않는 일**: 코드를 직접 작성하지 않습니다. 읽고, 결정하고, 디스패치하고, 결과를 파싱하고, 상태를 갱신합니다. 패턴은 "기여자가 아닌 매니저"입니다.

## 3. 라이프사이클: 3단계

### Phase 0 — 셋업 (1회)

1. 호출 인자 파싱 (`plan=`, `spec=`, `risk=`, `docs_scope=`, 실험적 `mode=`).
2. 트리가 깨끗한지 확인 (`git status` 비어있음); 아니면 중단.
3. 작업 격리용 **worktree**를 `<repo>/../worktrees/<branch>` 에 생성. 이후 모든 작업은 여기서 이뤄지고 `main`은 그대로.
4. **안전 훅**을 `<worktree>/.claude/settings.json` 에 설치:
   - `PreToolUse` — `rm -rf`, `git push`, 스키마 드롭 차단
   - `PostToolUse` — Edit/Write 시 디버그 아티팩트(`console.log`, `TODO`, `FIXME`, `debugger`) 스캔
   - `SubagentStop` — Implementer 출력 구조 sanity 체크
5. 계획 + 스펙 읽기. **모호성 게이트** 실행: 누락된 Files 블록, 레포 밖 경로, 모순 검출. 발견 시 사용자 확인 대기.
6. 태스크별 **위험 등급** 할당 (LOW/MID/HIGH) — §7 참조.
7. **베이스라인 테스트 상태** 스냅샷 (현재 테스트 스위트의 pass/fail 카운트) — 나중 회귀 비교용.
8. **컴팩션 포인트** 계산 — 이 인덱스 이후로는 이전 원본 컨텍스트를 오케스트레이터 메모리에서 드롭해도 되는 태스크 경계.
9. **웨이브 구조** 계산 (P2) — 의존성 기준으로 태스크 그룹핑. 한 웨이브 안에서 파일 집합이 겹치지 않는 태스크들은 병렬 sub-worktree에서 실행 가능.
10. 태스크별 **노력 버킷** 계산 (P5) — 파일 수, LOC 추정, 선언 수, 위험을 종합해 SMALL/MEDIUM/LARGE.
11. **Plan Reviewer 사전 검토** 실행 (P3) — headless Sonnet 서브에이전트가 계획을 기계적으로 감사 (누락된 AC 블록, 계약 불일치, 의존성 비일관성).
12. 모든 계산된 메타데이터로 `state.json` 초기화.

### Phase 1 — 태스크 사이클 (반복)

`state.execution_plan`의 각 태스크에 대해:

```
Step 1: Implementer 디스패치 (Sonnet, fresh)
   │  프롬프트: 스펙 발췌, 파일, 위험, effort_guidance,
   │           previous_issues (재시도일 때)
   ↓ STATUS: DONE | ESCALATE
   
Step 2: Combined Reviewer 디스패치 (Sonnet, fresh)
   │  입력: 스펙, diff, previous_issues
   │  출력: SPEC_SCORE, QUALITY_SCORE (0.0-1.0), SPEC_FAULT
   ↓ tier:
   │  PASS  (spec≥0.85 AND quality≥0.75) → Step 3
   │  WARN  (≥0.70 AND ≥0.60)            → Step 3 + 경고 기록
   │  FAIL                                → 분기:
   │     spec_contradicts → spec edit branch (P15)
   │     unclear          → 명확화 (스펙 텍스트 변경 없음)
   │     implementer_omitted/none → 표준 재시도 (최대 3)
   ↓
Step 3: Verifier (MID/HIGH만 — LOW는 컴팩션 포인트에서 배치)
   │  headless `claude -p` → JSON 결과 파일
   │  전체 테스트 스위트 실행, 베이스라인과 비교
   ↓ 결과:
   │  PASS                → Step 4
   │  FAIL (테스트 깨짐)  → 재시도 (최대 3)
   │  ENV_BLOCKER         → 사용자에게 ESCALATE
   ↓
Step 4: Agent Cleanup
   │  디버그 아티팩트 스캔 (이제 P1 훅으로 강제됨)
   │  보호 파일 체크 (.git, .orchestrator 등 편집 금지)
   │  커밋 검증
   ↓
   다음 태스크로 진행. state.json 갱신.
```

**병렬 서브 플로우 (P2)**: 한 웨이브 내 같은 병렬 그룹에 여러 태스크가 있으면, 각각 자기 sub-worktree (`<worktree>/.parallel/task_N`) 에서 실행. 모두 DONE 후: 우승 커밋들을 메인 worktree로 cherry-pick. 머지된 상태에서 Reviewer + Verifier를 순차 실행.

**LOW 태스크 배칭**: LOW 태스크는 태스크별 Verifier를 건너뜁니다. `state.low_tasks_pending_verification` 에 누적됩니다. 각 컴팩션 포인트와 Phase 2 진입 시점에 배치 Verifier가 누적된 LOW 태스크를 한꺼번에 검증. 배치 FAIL이면 어느 태스크가 범인인지 이진 탐색, 리셋, 재시도.

### Phase 2 — 마무리 (마지막에 1회)

1. **배치 Verifier 스윕** — 남은 LOW 태스크 검증.
2. **최종 Docs Updater** — headless Sonnet, 모든 태스크의 통합된 `FILES_CHANGED`를 받아 README, CHANGELOG, 관련 문서 갱신.
3. **최종 요약 리포트** — markdown 요약을 사용자에게 전달: 완료/스킵된 태스크, WARN 목록, quality_trend 차트, 총 wall time, 총 토큰, 적용된 스펙 편집.

## 4. 서브 에이전트 역할 카탈로그

| 역할 | 모델 | 디스패치 방식 | 시점 | 출력 포맷 |
|------|------|---------------|------|-----------|
| Plan Reviewer | Sonnet | headless | Phase 0 Step 0.6, 1회 | JSON: `{status, issues[]}` |
| Implementer | Sonnet | `Agent` 툴 (fresh) | Phase 1 Step 1, 태스크당 | Text: `STATUS:`, `COMMIT:`, `FILES_CHANGED:`, `FILES_TEST_CHANGED:` |
| Combined Reviewer | Sonnet | `Agent` 툴 (fresh) | Phase 1 Step 2, 태스크당 | Text: `SPEC_SCORE:`, `QUALITY_SCORE:`, `SPEC_FAULT:`, `ISSUES:` |
| Verifier | Sonnet | headless `claude -p` | Phase 1 Step 3 (MID/HIGH) + Phase 2 배치 (LOW) | JSON: 테스트 결과, 회귀 목록, 환경 상태 |
| Phase Docs Updater | Sonnet | headless `claude -p` | 컴팩션 포인트 | Markdown 요약 + 커밋 |
| Final Docs Updater | Sonnet | headless `claude -p` | Phase 2 Step 1 | Markdown 요약 + 커밋 |

**`Agent` 툴 vs headless `claude -p`**:
- `Agent`는 결과를 오케스트레이터 컨텍스트로 반환 — 오케스트레이터가 구조화된 답을 직접 읽어야 하는 짧은 인터랙티브 태스크에 적합.
- `claude -p`는 결과를 JSON 파일로 작성 — 결과가 크고(테스트 출력, 문서 본문) 오케스트레이터가 평가(verdict)만 필요할 때 적합. 컨텍스트 비대화 회피.

## 5. 상태 관리 (외부 메모리)

`<worktree>/.orchestrator/state.json` 은 **유일한 진실의 출처**입니다. 모든 오케스트레이터 결정: state.json 읽기 → 계산 → 변경 → 쓰기.

주요 필드 (전체 스키마는 `SKILL.md` Phase 0 Step 6):

```json
{
  "schema_version": "2",
  "branch": "...",
  "worktree": "...",
  "mode": "interactive_session | headless_pending | headless_running | ...",
  "active_plan": "plan1 | plan2",
  "tasks": {
    "0": {
      "status": "PENDING | IN_PROGRESS | COMPLETE | SKIPPED",
      "risk": "low | mid | high",
      "files": ["..."],
      "files_test": ["..."],
      "review_retries": 0,
      "verifier_retries": 0,
      "escalation_count": 0,
      "spec_score": 0.90,
      "quality_score": 0.85,
      "review_tier": "PASS",
      "commit": "abc1234",
      "spec_clarifications": 0
    }
  },
  "baseline": {"passing": 12, "failing": 0},
  "execution_plan": [
    {"wave": 0, "parallel_groups": [[1, 3], [2]]},
    ...
  ],
  "compaction_points": [4, 8, 12],
  "quality_trend": [0.9, 0.85, 0.95, ...],   // 롤링 최근 10개
  "low_tasks_pending_verification": [...],
  "task_summaries": {
    "task_N": {"summary": "...", "warnings": [...]}
  },
  "task_complexity": {"0": "SMALL", "1": "LARGE", ...},
  "spec_edits": [{"task", "spec_line", "reason", "commit", "ts", "fault"}],
  "plan_review_warnings": [],
  "implementer_model": {"used": "sonnet | opus", "default": "sonnet"},
  "plan_chain": [/* v2.13 — present only when multi-plan; see below */]
}
```

**v2.12 추가 — `implementer_model`**: Implementer 서브에이전트의 모델을 선택. `used` 는 이번 실행에서 dispatch에 쓴 모델, `default` 는 스킬이 인자 없을 때 쓰는 contemporaneous 기본값 (현재 항상 `"sonnet"`). 인자는 인터랙티브 부모(Phase -1 step b 또는 mode=interactive 의 Phase 0 Step 7)에서만 파싱되며 — 헤들리스 자식 `claude -p` 는 원래 인자에 접근하지 못하므로 state.json 에서 읽어 보존합니다. Reviewer / Verifier 는 영향 없음 (judge 일정성 — `docs/experiments/v2.12-implementer-opus-vs-sonnet/decisions/D001-...` 참조).

**v2.13 추가 — `plan_chain[]` + NL 인자**: `plan=, plan2=, plan3=, ..., planN=` 와 각각의 `specN=` 쌍을 받으면 자동으로 시퀀셜 체이닝됩니다. 단일 plan 호출은 v2.12 스키마 그대로 (state.tasks 등 top-level). N≥2 일 때만 `plan_chain[]` 배열이 state.json 에 박힘 — 각 entry 가 `{index, plan_path, spec_path, status, baseline, tasks, task_summaries, quality_trend, risk_levels, task_complexity, compaction_points, execution_plan, global_constraints, low_tasks_pending_verification, last_compaction_after_task, last_completed_task, last_completed_at, plan_review}`. `active_plan` 은 단일 plan 에서 `"plan1"` 문자열, multi 에서 정수 인덱스. Phase 2 Step -1 Cross-Plan Trigger 가 i → i+1 swap 을 일반화 처리. NL 키워드 lexicon (opus, 오푸스, sonnet, 소넷, 순차, sequential, interactive, 대화형) 은 explicit `key=value` 안 줬을 때만 채움. 충돌 시 halt — 자세히는 `docs/experiments/v2.13-natural-multi-plan/decisions/`.

**재개(Resumption)**: 모든 상태가 JSON에 있으므로, 새 오케스트레이터 세션은 state.json만 읽어서 기록된 태스크/스텝에서 이어 실행할 수 있습니다. 이것이 `mode: headless_pending` 의 동작 원리입니다 — 스폰하는 세션이 최소 상태를 쓰고, 스폰된 세션이 채워 넣습니다.

## 6. 격리 메커니즘

| 경계 | 메커니즘 |
|------|----------|
| 메인 브랜치 ↔ 스킬 실행 | `git worktree` at `<repo>/../worktrees/<branch>` — 별도 워킹 트리, 작업 파일 교차 오염 없음 |
| 한 웨이브 내 병렬 태스크 | sub-worktree at `<worktree>/.parallel/task_N/` — 각 태스크가 자기 체크아웃 |
| 오케스트레이터 ↔ 서브에이전트 컨텍스트 | fresh 서브에이전트 디스패치 — Sonnet은 오케스트레이터 사전 정보 없이 시작, 프롬프트가 필요한 것만 전달 |
| 서브에이전트 ↔ 파괴적 연산 | `.claude/settings.json` 훅이 `PreToolUse` 정규식으로 `rm -rf`, `git push`, 스키마 드롭 차단 |
| 서브에이전트 출력 유효성 | `SubagentStop` 훅이 구조 검사: `STATUS:` 존재, DONE이면 `COMMIT:` 존재, `FILES_CHANGED:` 존재. 형식 깨짐 → 오케스트레이터가 거부로 인식하고 재디스패치 |
| 디버그 아티팩트가 커밋으로 새는 것 | `PostToolUse` 훅이 Edit/Write 시 diff 라인에서 `console.log`/`TODO`/`FIXME`/`debugger` 스캔 |

## 7. 위험 등급

오케스트레이터가 Phase 0 Step 4에서 할당. Verifier 디스패치 타이밍, 노력 버킷 적격성, (제안된 quality_plus에서는) 모델 선택을 제어.

| 등급 | 기준 | Verifier | 노력 버킷 적격성 |
|------|------|----------|-------------------|
| LOW  | 1 파일, 격리된 모듈, API 변경 없음 | 컴팩션 포인트에서 배치 | SMALL 가능 (≤8 툴 콜) |
| MID  | 2+ 모듈, 공유 상태, 설정 변경 | 태스크별 | MEDIUM 기본 (10–25 툴 콜) |
| HIGH | DB/스키마/API 표면, breaking change, 명시적 마킹 | 태스크별 | LARGE 강제 (25–60 툴 콜) |

**LOW→MID 자동 승격 규칙**: 한 LOW 태스크가 같은 계획 안의 이전 LOW 태스크가 이미 건드린 파일을 건드리면, 후행 태스크를 MID로 승격. 배치 Verifier가 겹치는 변경을 누적해 어느 태스크가 무엇을 깨뜨렸는지 숨기는 것을 방지.

## 8. 품질 채점 (P4)

이진 PASS/FAIL을 대체. Combined Reviewer가 `SPEC_SCORE`와 `QUALITY_SCORE`를 출력 — 둘 다 0.0–1.0, 소수점 1자리로 양자화.

**등급 매핑**:
- `PASS`: `SPEC_SCORE >= 0.85` AND `QUALITY_SCORE >= 0.75`
- `WARN`: (PASS 아님) AND `SPEC_SCORE >= 0.70` AND `QUALITY_SCORE >= 0.60`
- `FAIL`: 그 외

**WARN 등급이 존재하는 이유는 경계선이지만 출하 가능한 작업에 재시도를 낭비하지 않기 위해서입니다**. WARN 태스크는 진행하고 (Verifier는 그래도 실행), QUALITY_ISSUES 는 `state.task_summaries.task_N.warnings[]` 에 기록되고 최종 요약 리포트에서 노출됩니다.

**품질 추세 추적**: 롤링 10개 태스크 버퍼, `state.quality_trend` 에 저장. 마지막 5개의 평균이 버퍼 안의 처음 5개 평균보다 > 0.10 떨어지면, 다음 컴팩션 포인트에서 사용자에게 경고 — 품질이 떨어지고 있다는 신호.

## 9. 스펙 편집 분기 (P15)

`SPEC_FAULT: spec_contradicts` 또는 `unclear` 인 Reviewer FAIL은 **Implementer 문제가 아니라 스펙 문제**로 분류됩니다. 표준 재시도는 진척 없이 `review_retries` 예산만 태웁니다 — 스펙 자체가 깨졌기 때문에.

스펙 편집 분기는 대신:
1. `task.spec_clarifications` 증가 (`review_retries` 와 별도 카운터). 태스크당 최대 3.
2. 오케스트레이터가 영향받은 스펙 섹션을 다시 읽고 **최소한의 편집**.
3. 편집을 `state.spec_edits[]` 에 추가: `{task, spec_line, reason, commit, ts, fault}`.
4. 편집된 스펙 섹션과 겹치는 후행 태스크 식별. 그들의 다음 Implementer 프롬프트에 `## [SPEC UPDATED]` 섹션 주입.
5. 스펙 편집 커밋: `chore(<plan>): clarify spec line N for task M`.
6. pre-task SHA로 리셋. 깨끗한 상태에서 Implementer 재디스패치.

## 10. Eval 하네스

`evals/` 는 `SKILL.md` 와 독립적입니다 — 스킬을 외부에서 테스트합니다.

```
evals/
├── fixtures/           # 시나리오당 YAML 1개 (plan + spec + bootstrap +
│   │                   #   expected outcome + rubric)
│   ├── 01-trivial-typo.yaml
│   ├── 02-three-file-refactor.yaml
│   ├── ...
│   └── 08-subtle-input-validation.yaml
├── rubric.py           # 결정론적 픽스처별 루브릭 러너
├── judge.md            # LLM judge 프롬프트 템플릿 (4축 채점)
├── run.sh              # 하네스: 레포 부트스트랩, 스킬 호출, state/log/diff/test/rubric 캡처,
│                       #   judge 프롬프트 빌드, baseline JSON 작성
├── baselines/          # 버전별 채점 결과
│   └── v2.6.0.json
└── calibration/        # judge 캘리브레이션 프레임워크 (v2.7 추가)
    ├── good_impl.py    # 레퍼런스 구현
    ├── broken_impl.py
    ├── run.py          # judge × N reps 호출, Δ≥0.2 검증
    └── README.md
```

**두 측정 계층**:
1. **프로그래매틱 루브릭** (`rubric.py`) — 픽스처에 `expected.rubric` 이 있으면 각 체크를 shell-execute, pass/fail 카운트. 결정론적. `correctness` 와 `spec_compliance` 축에 사용.
2. **LLM judge** (`judge.md` → Sonnet/Opus) — `code_quality` 와 `cost_efficiency` 채점 (주관적). 입력으로 rubric_results 를 받아 정확성을 다시 추정하지 않음.

**왜 둘 다인가**: v2.7 실험에서 LLM judge 단독은 rep별 분산이 크고(주관적 축에서 ±0.16) 부분 점수가 후해서 델타를 누른다는 것이 밝혀짐. 결정론적 측정과 주관적 측정을 분리하면 기계적 축에서 노이즈가 사라집니다.

## 11. 핵심 설계 결정 (왜 이 패턴인가)

| 결정 | 왜 이것이고 대안이 아닌가 |
|------|---------------------------|
| 오케스트레이터-워커 (스웜/퀸이 아니라) | 스웜은 복잡한 창발적 조정 필요. 오케스트레이터-워커는 잘 이해되고 디버깅 가능하고 재개 가능 |
| Opus 오케스트레이터 + Sonnet 워커 (전 Opus나 전 Sonnet이 아니라) | 오케스트레이션은 Opus 수준 판단 필요 (언제 에스컬레이트할지, FAIL에 어떻게 대응할지). 구현은 Sonnet 가능 — 캘리브레이션으로 측정됨 |
| 외부 메모리 (state.json) | 재개, 디버깅성, 오케스트레이터 컨텍스트 증가 캡. SQLite는 이 필드 셋에 과공학 |
| 짧은 인터랙티브 서브에이전트는 `Agent` 툴, 큰 출력은 headless `claude -p` | 큰 테스트 로그 / 문서 텍스트로 오케스트레이터 컨텍스트가 비대해지는 것 회피 |
| Worktree 격리 (브랜치만이 아니라) | 사용자 메인 체크아웃을 방해하지 않고 worktree 안에서 테스트 가능. 훅이 worktree 범위로 한정 (사용자 전역 아님) |
| 위험 등급을 폭발 반경으로 (품질 잣대가 아님) | TDD 항상, Reviewer 항상 — 품질 잣대는 균일. 위험은 검증 타이밍/노력을 결정, "얼마나 좋아야 하는가" 가 아님 |
| WARN 등급 (PASS/FAIL만이 아니라) | WARN 없으면 모든 경계선 결과가 재시도를 태움. WARN 있으면 경계선 작업이 플래그 달고 출하, 재시도 예산은 진짜 깨진 것에만 |
| 서브에이전트는 요약을 반환, 원본 작업이 아님 | 오케스트레이터가 50+ 태스크로 확장 가능 — 태스크당 컨텍스트가 유계이기 때문 |
| 결정론적 루브릭 러너 (v2.7) | LLM judge 단독은 가까운 케이스에서 Δ < 0.2 변별력. rubric.py 가 기계적 축에서 그 노이즈 제거 |
| Pilot-first 실험 (v2.7) | 셀당 n=1 풀 실험은 현실적 효과 크기를 못 잡음. 한 픽스처에 n=3 파일럿이 천장/분산 문제를 싸게 노출 |

## 12. 실패 모드 & 에스컬레이션

| 실패 | 검출 | 대응 |
|------|------|------|
| Implementer 가 ESCALATE | 서브에이전트 답에서 `STATUS: ESCALATE` | 에스컬레이션 프로토콜 — 카테고리화 (SPEC_BLOCKER, ENV_BLOCKER, AMBIGUITY, TASK_BLOCKER), `escalation_count` 증가 (태스크당 캡 3), 프로토콜에 따라 응답 |
| Combined Reviewer FAIL — Implementer 책임 | `SPEC_FAULT: implementer_omitted` | 표준 재시도. `review_retries` 증가 (캡 3). `## Fix Required\n{issues}` 와 함께 재디스패치 |
| Combined Reviewer FAIL — 스펙 책임 | `SPEC_FAULT: spec_contradicts` 또는 `unclear` | 스펙 편집 분기 (§9). `review_retries` 에 카운트 안 됨 |
| Verifier FAIL — 테스트 깨짐 | Verifier JSON이 회귀 보고 | `## Fix Required\n{failed tests}` 와 함께 Implementer 재디스패치. `verifier_retries` 증가 (캡 3) |
| Verifier ENV_BLOCKER | Verifier JSON이 환경 불안정 보고 | ESCALATE — 사용자가 환경 고쳐야 함 (DB 다운, 포트 충돌 등) |
| 커밋에 디버그 아티팩트 | `PostToolUse` 훅 발동 | 훅이 exit 2 반환. Implementer가 거부 보고 받고 자동 재시도 |
| 형식 깨진 서브에이전트 출력 | `SubagentStop` 훅이 필드 누락 검출 | 훅이 exit 2 반환. 오케스트레이터가 Reviewer FAIL로 처리, 재디스패치 |
| 서브에이전트가 보호 파일 편집 | Agent Cleanup grep | 태스크 리셋, 프롬프트에 명시적 금지 추가하고 재디스패치 |
| state.json 손상 | Phase 0 재개 읽기 | "state file corrupted, manual inspection recommended" 와 함께 중단 |
| 시작 시 worktree dirty | Phase 0 클린 체크 | 중단 — "git status not empty, resolve before invoking" |

---

## 14. 학습/이벤트 로그 계약 (v2.8 → v2.17 AgentLens 컷오버)

스킬은 구조화·민감정보 제거된 이벤트를 **AgentLens** (`kws-cme.*` 네임스페이스) 로 발산해서 스킬 자체가 여러 실행에 걸쳐 개선될 수 있도록 합니다. 이것은 **관측성 계층**입니다 — 스킬의 정확성은 여기에 의존하지 않으며, 모든 emit은 `2>/dev/null || true` 로 감싸져 있고 `ORCH_RUN_ID` 가 비어있으면 silent no-op 입니다.

> **v2.17 cutover (2026-05-19, Task 11)**: `scripts/append_learning_event.py` 와 평행 `~/.claude/learning/kws-claude-multi-agent-executor/runs/<YYYY-MM-DD>/<run_id>/{meta.json,events.jsonl}` 쓰기 경로는 제거되었습니다. AgentLens 가 단독 이벤트 싱크입니다. 과거 (cutover 이전) run의 디스크 아카이브는 그대로 남아있지만 신규 쓰기는 없습니다.

### 저장소 레이아웃

이벤트는 AgentLens 의 run-scoped 스토어에 거주:

```
agentlens_orchestration_run = <id>         # state.json top-level (string|null)
├── run metadata  (agent=kws-cme-orchestrator, workspace, meta=plan/spec/...)
└── events        (type 별 kws-cme.<event_type>; payload + timestamp)
```

`ORCH_RUN_ID` 는 Phase -1 step b 에서 `agentlens run-open` 으로 한 번 열리고, Resume Chain handoff에는 `AGENTLENS_PARENT_RUN_ID` env로 child에 전파됩니다 (child는 새 run을 열지 않음).

### 단일 작성자 계약 (cutover 후 그대로 유지)

**오케스트레이터만 AgentLens emit을 합니다.** 서브에이전트(Agent 툴 / `claude -p`)들은 여전히 `<worktree>/.orchestrator/learning_events/<task_id>-<role>.json` 에 이벤트 후보 JSON 을 준비하고, 오케스트레이터의 Phase 1 Step 3.5 candidate-drain 루프가 각 사이클 스텝 후 디렉터리를 스캔해서 `agentlens event append --type kws-cme.<event_type> --payload-json @<candidate>` 로 publish합니다. 후보 JSON → `.appended` 로 rename. 이 indirection 은 환경변수 전파 퍼즐을 피하기 위해 v2.8 부터 유지된 패턴 — 컷오버는 발산 사이트만 바꿨습니다.

### 오케스트레이터 직접 emit 사이트 (4개)

| Phase | Step | 이벤트 |
|---|---|---|
| 0 | Step 7.5 | `kws-cme.phase_0_started` |
| 1 | Step 2.6 | `kws-cme.task_completed` |
| Transition | T3 | `kws-cme.compaction` + `kws-cme.context_health` (Resume Chain handoff시) |
| 2 | Step 2 | `kws-cme.phase_2_complete` → `agentlens run-close --outcome success` |

Hard-halt 분기(에스컬레이션 소진, 예산 pause, T3 state-write 실패): `kws-cme.blocker` emit + `agentlens run-close --outcome aborted|blocked`.

### 10개 이벤트 타입 (네임스페이스: `kws-cme.<event_type>`)

- `blocker` (orchestrator) — Phase 0를 막는 plan/spec/baseline 누락, dirty worktree
- `error` (orchestrator) — 스킬 절차 실패 (state 손상, worktree 생성 실패)
- `verification_failure` (verifier) — MID/HIGH 태스크별 또는 LOW 배치에서 Verifier FAIL
- `reviewer_warn_or_fail` (reviewer) — Combined Reviewer WARN/FAIL 등급
- `escalation` (any sub-agent) — 서브에이전트 ESCALATE (심각도는 `references/escalation-playbook.md` 참조)
- `recurring_issue` (orchestrator) — 재시도 후 같은 `ISSUE_KEY` 재출현
- `user_correction` (orchestrator) — 실행 중 사용자가 범위/파일/가정 수정
- `parallel_dispatch_failure` (orchestrator) — P2 웨이브 디스패치 실패 / 머지 충돌
- `successful_workaround` (implementer 또는 orchestrator) — 재사용 가능한 복구 통찰
- `completion_learning` (orchestrator) — 종료 시 실행자 개선 관찰

### 살균 가드

후보 JSON 은 발산 전 다음을 거부/마스킹: 비밀(Authorization: Bearer / api_key / sk-...), 전체 트랜스크립트, 절대 홈 경로, 과도한 발췌 (> 400자). `--repo-root` 하위 경로는 상대화. 서브에이전트 트랜스크립트는 AgentLens run-scope 안의 child run id 로 참조, 복제하지 않음.

### 실패 격리

SKILL.md 의 모든 AgentLens 호출은 `[ -n "${ORCH_RUN_ID:-}" ]` 가드 + `2>/dev/null || true` 접미사로 감싸져 있습니다. AgentLens CLI 누락, registry 오류, 스키마 거부 — 이 중 어느 것도 계획 실행을 막지 않습니다. `ORCH_RUN_ID` 가 비어있으면 Phase 1 Step 3.5 의 candidate-drain 루프는 후보 파일을 `.appended` 로 옮기되 publish는 silently 건너뜁니다 (재시도 없음).

### `state.json` 과의 관계

`state.json` 은 실행당 재개 진실의 출처 (worktree에 거주). AgentLens 이벤트 스트림은 실행 교차 제도적 메모리. 둘은 독립적입니다: 오케스트레이터는 AgentLens가 없어도 끝까지 실행할 수 있고(CLI 누락 / run-open 실패), AgentLens 는 `state.json` 이 삭제된 실행의 이벤트도 기록할 수 있습니다. `state.agentlens_orchestration_run` 필드(run-level, top-level)가 두 계층의 유일한 연결점입니다.

### 패리티 검증

cutover-이전 run의 디스크 아카이브(`~/.claude/learning/.../events.jsonl`)와 AgentLens 스트림을 비교하려면 `scripts/compare_agentlens_events.py` 사용. `--self-test` 모드는 legacy `event_type` → `kws-cme.<event_type>` rename 계약을 합성 케이스로 검증하고, `evals/run.sh` 의 deterministic preflight 로 실행됩니다.

전체 스키마와 코드 예시는 `references/learning-log.md` 참조 (cutover-이전 헬퍼 호출 예시는 *historical diagnostic procedures* 로 보존되어 있습니다).

## Method Audit (v2.11)

MAE requires sub-agents to invoke `superpowers:test-driven-development`, `superpowers:verification-before-completion`, and code-review-pass disciplines, but prior to v2.11 it did not verify the disciplines were actually applied. v2.11 adds:

- Structured output blocks (`METHOD_AUDIT:`, `REVIEW_FINDINGS:`, Verifier `commands_run`) emitted by sub-agents.
- Orchestrator populator at Phase 1 Step 4 — parses and writes `state.tasks.<id>.method_audit`.
- SubagentStop hook (`references/hooks/check-implementer-output.sh.template`) — runtime gate on Implementer output shape.
- Validator script (`scripts/validate_method_audit.py`) — semantic gate at Phase 2 Step 1.5 before close-run.

Required-methods derivation: executable task → TDD + verification + code-review-pass; docs-only task (`files_test == []` or all `.md` files) → verification only. TDD waiver reasons are restricted to `docs-only-task`, `config-only-task`, `generated-only-task`.

Fabricated evidence is grounds for re-dispatch and a `method_audit_violation` learning-log event (severity=high).

## Local-Env Preflight (v2.11)

Phase 0 Step 4.7 runs between risk assignment and baseline test. Two detection rules:

1. **Unfilled local-config counterpart** — for every `*.example` / `*.template` / `*.dist` in the worktree, the suffix-stripped counterpart is checked for existence + gitignored status.
2. **Stale dependencies** — manifest/lockfile/install-marker mtime triple per language ecosystem.

Both are detection-only. Warnings are written to `state.preflight_warnings`. The orchestrator does not auto-copy gitignored files (potential secret / machine-specific path leakage).

ENV_BLOCKER triage cross-references preflight warnings before running generic dependency install.

## Resource-Key Serialization (v2.11)

A task may declare `**Resource Key:** <slug>` in its plan body. Phase 0 Step 6 partition algorithm builds the resource-key map per wave and splits any same-key collisions into singleton groups. The wave's file-disjointness invariant is preserved; only serialization widens.

`state.execution_plan` group entries record `serialization_reason: "resource_key=<key>"` when applied.

Plan Reviewer (Phase 0 Step 6.5) emits WARN issues for same-wave collisions so the plan author sees the reduced parallelism. WARN, not BLOCKER — runtime correctness is automatic.

## 13. 갱신 프로토콜

다음 중 하나를 변경하면 **이 파일을 갱신하세요**:

| 이 문서의 주제 | 갱신 트리거 |
|----------------|-------------|
| 서브에이전트 카탈로그 (§4) | 새 역할 추가, 역할 제거, 모델 매핑 변경 |
| state.json 스키마 (§5) | 새 필드, 필드 의미 변경 |
| 격리 메커니즘 (§6) | 새 훅, 새 worktree 패턴, 새 안전 경계 |
| 위험 등급 (§7) | 기준 변경, 승격 규칙 변경, 모드 기반 오버라이드 추가 |
| 품질 채점 (§8) | 임계값 변경, 등급 변경, 추세 규칙 변경 |
| Eval 하네스 (§10) | 새 픽스처 타입, 새 측정 계층, 새 캘리브레이션 도구 |
| 실패 모드 (§12) | 새 ESCALATE 카테고리, 새 재시도 규칙 |
| 학습 로그 (§14) | 새 이벤트 타입, 새 헬퍼 서브커맨드, 스키마 변경, 새 살균 규칙, 후보 파일 경로 변경 |

**갱신하지 말 것**:
- 새 픽스처 추가 (`evals/` 의 일)
- 기존 동작 버그 수정 (커밋 메시지의 일)
- SKILL.md 의 문장만 다듬는 변경 (SKILL.md 의 일)

**버전 번프 시** (SKILL.md frontmatter `metadata.version`): 그 버전에서 변경된 ARCHITECTURE.md 섹션을 참조하는 행을 `HISTORY.md` §1 에 추가. 내용을 복제하지 말고 — 커밋과 실험 기록으로 링크.

**새 실험 시**: 실험이 동작 변경을 머지하면, 실험을 main에 머지하는 같은 커밋에서 해당 ARCHITECTURE.md 섹션을 갱신. 실험의 자체 `docs/experiments/<name>/` 디렉터리는 상세 기록으로 유지; ARCHITECTURE.md 는 종합된 현재 상태 뷰로 유지.
