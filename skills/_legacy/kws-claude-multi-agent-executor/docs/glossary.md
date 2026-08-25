# 용어 사전

이 스킬 전반(프롬프트, eval, 실험 기록)에서 사용되는 용어. 이 코드베이스가 처음이라면 이 파일을 먼저 훑어보세요.

## 역할과 프로세스

- **Orchestrator (오케스트레이터)** — `SKILL.md` 를 실행하는 Claude Code 세션. 기본으로 Opus 위에서 실행. worktree, `state.json`, 학습 로그 실행, 모든 서브에이전트 디스패치를 소유. 계획 실행당 정확히 하나의 오케스트레이터.
- **Sub-agent (서브에이전트)** — 오케스트레이터가 `Agent` 툴(세션 내) 또는 `claude -p` 서브프로세스(Resume Chain)로 디스패치하는 fresh Claude Code 인스턴스. 역할: Implementer, Reviewer, Verifier, Plan Reviewer, Docs Updater. 기본으로 Sonnet; 현재 `--model` 플래그가 전달되지 않음 ([`risks-and-limitations.md`](./risks-and-limitations.md) §Headless model gap 참조).
- **Combined Reviewer** — 한 번의 패스로 스펙 준수 리뷰(Part 1)와 코드 품질 리뷰(Part 2)를 모두 수행하는 단일 Reviewer 서브에이전트. 이전의 2-서브에이전트 설계를 대체.
- **Verifier** — Implementer 의 테스트와 독립적으로 스펙의 acceptance criteria 를 구현 산출물에 대해 재실행하는 서브에이전트.

## 실행 구조

- **Plan (계획)** — 태스크 번호 섹션을 가진 markdown 파일; 실행의 입력. 각 태스크는 파일, acceptance criteria, 선택적 위험 오버라이드를 가짐.
- **Task cycle (태스크 사이클)** — Phase 1 의 태스크당 루프: Implementer → Reviewer (재시도 루프) → Verifier → commit → state 갱신. 한 태스크 = 한 사이클.
- **Phase 0** — 셋업. worktree 생성, 계획/스펙 읽기, state.json init, 학습 로그 init-run, 선택적 plan review. 실행당 1회.
- **Phase 1** — 태스크 사이클 (계획의 각 태스크마다 반복).
- **Phase 2** — 마무리. 문서 갱신, 최종 커밋, 학습 로그 close-run. 실행당 1회, 성공 경로에서.
- **Phase Transition T3** — Phase 1 (마지막 태스크 완료)과 Phase 2 (마무리) 사이의 경계. 여기서 state 쓰기 실패가 `outcome=blocked` 종료 경로 중 하나.

## 상태와 격리

- **Worktree** — `<repo>/../worktrees/plan-<timestamp>/` (또는 모드에 따라 `<repo>/.claude/worktrees/...`) 하위의 git worktree. 오케스트레이터가 실행당 하나 생성; 모든 태스크 커밋이 여기 안착, 부모 체크아웃에서 계획 실행을 격리.
- **`state.json`** — 오케스트레이터의 외부 메모리, `<orch_dir>/state.json` 에 있음. 태스크 상태, 점수, 사이클 카운트, 에스컬레이션 히스토리 기록. 오케스트레이터가 모든 스텝 시작에서 이걸 읽어 컨텍스트 컴팩션에서 복구.
- **Resume Chain** — `compaction_points >= 2 AND complete >= 8` 일 때, 오케스트레이터가 `claude -p` 를 띄워 새 세션에서 실행을 계속. `MAE_LEARNING_RUN_ID` 를 env 로 전달해 학습 로그 실행이 이어짐.
- **Compaction point (컴팩션 포인트)** — Claude Code 대화 자동 컴팩션 이벤트. state.json 에 추적되어 Resume Chain 을 적절한 임계에서 트리거.

## 위험과 채점

- **Risk tier (위험 등급)** — `low | mid | high`, 계획(또는 호출 오버라이드)에서 태스크별로 파생. TDD 엄격도, 재시도 예산, 검증 깊이를 결정 — **모델 선택은 아님**.
- **TDD strictness (TDD 엄격도)** — `mid`/`high` 태스크는 Implementer 가 실패하는 테스트를 먼저 쓰고 그 다음 통과시키도록 구현 필수. `low` 는 TDD 권장이지만 강제 아님.
- **P4 Generator-Verifier scoring** — Reviewer 가 SPEC_SCORE 와 QUALITY_SCORE 발산 (0.0-1.0, 0.1 양자화). 임계값: SPEC PASS iff ≥0.85; QUALITY PASS iff ≥0.75. eval 스위트에 대해 보정됨.
- **SPEC_FAULT** — 스펙이 실패한 *이유* 에 대한 Reviewer 의 진단: `spec_contradicts`, `unclear`, `implementer_omitted`, `none`. 에스컬레이션 라우팅 결정.
- **SPEC_COVERAGE_WALK** (v2.9.0+) — Reviewer 의 결정론적 열거 패스: sub-step A (명시된 항목), sub-step B (메타 규칙에서 적대적 생성). 스펙 항목당 1행 + 메타 규칙당 ≥3 적대적 행 발산. [`../references/reviewer-prompt.md`](../references/reviewer-prompt.md) 참조.

## 학습 로그

- **Run (실행)** — 한 번의 계획 실행 = 학습 로그 실행 하나. `run_id = <UTC-compact-timestamp>-<session_short>-<pid>` 로 식별, 예: `20260513T143321Z-188042f4-48211`.
- **Run dir (실행 디렉터리)** — `~/.claude/learning/kws-claude-multi-agent-executor/runs/<date>/<run_id>/`, `meta.json` (항상) + `events.jsonl` (≥1 이벤트 시) 포함.
- **`meta.json`** — 실행 요약: outcome (`success | blocked | aborted | unknown`), event_count, session_ids[], started_at, ended_at, plan_path, spec_path, worktree_path (상대화됨).
- **Event (이벤트)** — JSONL 한 줄. 10개 이벤트 타입: `blocker`, `error`, `verification_failure`, `reviewer_warn_or_fail`, `escalation`, `recurring_issue`, `user_correction`, `parallel_dispatch_failure`, `successful_workaround`, `completion_learning`. [`../references/learning-log.md`](../references/learning-log.md) 참조.
- **Candidate file (후보 파일)** — 서브에이전트가 `<orch_dir>/learning_events/<task_id>-<role>.json` 에 작성한 JSON. 오케스트레이터가 이 디렉터리를 스캔하고 `append` 호출. 단일 작성자 계약.
- **Adherence marker (준수 마커)** — Step 7.5 가 run.jsonl 에 출력하는 `LEARNING_LOG_INIT: RUN_ID=<id>` (또는 `SKIPPED`). eval 하네스가 이 마커를 grep 해서 v2.8.1 의 필수 init-run 준수 검출.

## Eval 시스템

- **Fixture (픽스처)** — `evals/fixtures/` 하위의 YAML 파일. 자체 완결 plan + spec + bootstrap + acceptance criteria + 선택적 rubric 기술.
- **Rubric (루브릭)** — 결정론적 정확성 체크 (구현을 운동시키는 bash 한 줄들). 정확성에 대한 권위; LLM judge 는 주관적 축(품질, 비용 효율) 담당.
- **Judge** — LLM-as-judge (`evals/judge.md` 템플릿). 네 개 축 채점: correctness, spec_compliance, code_quality, cost_efficiency. 네 축의 평균이 헤드라인 숫자.
- **Baseline** — `evals/baselines/v<version>.json`, 그 버전의 픽스처별 캡처된 judge 출력. 회귀 검출용 버전 간 비교.
- **Calibration (캘리브레이션)** — `evals/calibration/`, judge 가 변별 가능한지 검증하는 controlled test (good_impl.py vs broken_impl.py 를 judge 에 대해 실행) — v2.7 산출물; judge 정확도 드리프트 시 재방문.

## 기타 용어

- **Superpowers** — `superpowers:*` 스킬 패밀리. 서브에이전트가 이걸 호출 (예: Reviewer 의 `Skill("superpowers:requesting-code-review")`) 해서 체크리스트 기반 리뷰. v2.8 에서 추가.
- **Headless mode** — `claude -p --dangerously-skip-permissions`. `evals/run.sh` 와 Resume Chain 이 사용. 인터랙티브 프롬프트 없음; 툴 자동 승인. 이 모드의 주된 취약점은 스킬 지시 준수 ([`risks-and-limitations.md`](./risks-and-limitations.md) §Adherence).
- **`MAE_LEARNING_RUN_ID`** — 서브프로세스와 Resume Chain 경계 너머로 현재 학습 로그 run_id 를 운반하는 env 변수. Step 7.5 가 설정; 모든 헬퍼 호출이 읽음.
- **Escalation (에스컬레이션)** — Implementer-Reviewer 재시도 루프가 `mid`/`high` 태스크에서 예산을 소진하면 오케스트레이터가 ESCALATE 기록(state.json + 학습 로그) 발산하고 중단(`outcome=blocked`) 또는 문서화된 타협으로 진행.
- **ESCALATE-type** — `spec_blocked | implementation_blocked | test_blocked`. 각각이 [`../references/escalation-playbook.md`](../references/escalation-playbook.md) 에서 이벤트 심각도로 매핑.
