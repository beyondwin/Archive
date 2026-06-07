# 결정 로그 — ADR 교차 인덱스

이 스킬의 모든 실험에서 만들어진 Architecture/Design Decision Record (ADR) 의 평탄 인덱스. ADR은 부모 실험 디렉터리(`docs/experiments/<version>-<name>/decisions/D###-<slug>.md`) 안에 살고 있는데 *국지적으로 의미가 있기* 때문입니다 — 그렇지만 "채점에 대해 어떤 설계 선택을 했나?" 같은 가로지르는 질문에 답하긴 어렵습니다.

이 파일이 그 가로지르는 뷰입니다. 사용 용도:

- 현재 설계를 설명하는 ADR 찾기 (행마다 링크).
- 어떤 대안이 검토되었는지 보기.
- 어느 실험이 그 결정을 만들었는지 찾기.
- 결정이 재검토 / 번복되었는지 감사.

---

## v2.7 — Quality-mode 실험 (종료; `quality_plus` 는 부정 결과, 루브릭 인프라는 긍정)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Floor level](../docs/experiments/v2.7-quality-mode/decisions/D001-floor-level.md) | 비교용 v2.6.0 베이스라인 floor 설정 위치 | **결정** |
| [D002 Judge model](../docs/experiments/v2.7-quality-mode/decisions/D002-judge-model.md) | LLM-as-judge용 Sonnet vs Opus | **결정**: Opus + rubric.py 하이브리드 |
| [D003 Rubric runner](../docs/experiments/v2.7-quality-mode/decisions/D003-rubric-runner.md) | 결정론적 정확성 측정 인프라 | **결정**: rubric.py |
| [D004 Pilot scope](../docs/experiments/v2.7-quality-mode/decisions/D004-pilot-scope.md) | 파일럿용 rep 수 + 픽스처 수 | **결정**: baseline-variance probe 먼저 |
| [D005 Experimental branch](../docs/experiments/v2.7-quality-mode/decisions/D005-experimental-branch.md) | 실험용 브랜치 전략 | **결정** |
| [D006 Pilot first](../docs/experiments/v2.7-quality-mode/decisions/D006-pilot-first.md) | 풀 실험 빌드 전 파일럿 | **결정**: 파일럿 우선; 1.5일+ 절약 |
| [D007 Fixture realistic spec](../docs/experiments/v2.7-quality-mode/decisions/D007-fixture-realistic-spec.md) | 픽스처 난도 증폭 멈추기 | **결정**: 멈추기, 확증 편향 회피 |
| [D008 quality_plus SKILL changes](../docs/experiments/v2.7-quality-mode/decisions/D008-quality-plus-skill-changes.md) | best-of-3 + judge용 SKILL.md 150줄 변경 | **설계됐지만 출하 안 됨** — F002 ceiling 이 죽임 |

**v2.7 마감**: [F002-close-out.md](../docs/experiments/v2.7-quality-mode/findings/F002-close-out.md) 참조. `quality_plus` 가설에서 부정 결과 (가장 어려운 픽스처에서 marginal gain 0.05, 표면 면적에 비해 가치 없음). 루브릭 인프라는 main으로 출하.

## v2.8 — 학습 로그 (출하, 풀 픽스처 smoke PARTIAL)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Initial design](../docs/experiments/v2.8-learning-log/decisions/D001-initial-design.md) | 실행별 샤드 레이아웃, run_id 포맷, 헬퍼 서브커맨드, 범위 | **결정** + 4개 advisor-patch 수정 (Q4 단일 작성자, Q5 모든 종료 경로 close-run, Q6 Resume Chain 핸드오프, Q7 두 smoke 픽스처) |

**v2.8 마감**: [F001-smoke.md](../docs/experiments/v2.8-learning-log/findings/F001-smoke.md) 참조. Smoke A 클린 PASS; Smoke B 가 멀티 태스크 계획에서 오케스트레이터 준수 갭 폭로. v2.8.1 후속이 갭을 닫음.

## v2.8.1 — Step 7.5 강제 (출하, n=4 검증)

실험 서브디렉터리 없음 — 이건 HISTORY.md 항목과 인라인 근거로 직접 출하된 경험적 수정. 결정 본체는 v2.8.1 HISTORY.md 항목과 `4afca2e` 커밋 메시지에 살아 있음.

| 변경 | 이유 |
|------|------|
| Step 7.5 헤딩을 MANDATORY 로 승격 | Smoke B에서 advisory 표현이 선택사항으로 읽혔음 |
| `LEARNING_LOG_INIT:` 마커를 양쪽 경로에서 발산 | 사후 준수 감사 신호 |
| 헬퍼 호출에서 `2>/dev/null` 제거 | 스크립트 깨졌을 때 헬퍼 stderr 노출 |
| `evals/run.sh` 가 픽스처별로 마커 grep | 준수가 측정 가능한 속성이 됨 |
| `check_skill_contract.py` 의 18번째 계약 체크 | MANDATORY 표현을 자리에 고정 |

## v2.9 — Reviewer Spec Coverage Walk (출하 2026-05-14)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Initial design](../docs/experiments/v2.9-reviewer-spec-coverage/decisions/D001-initial-design.md) | single-pass walk vs 멀티 관점 디스패치; omc 7-아이템 shortlist 에서 증거 선택; **§Q3 critical post-advisor-pre-check patch** — 메타 규칙용 적대적 생성 추가 | **결정** |

**v2.9 findings**:
- [F001-T4.5-dry-run.md](../docs/experiments/v2.9-reviewer-spec-coverage/findings/F001-T4.5-dry-run.md) — 1-rep 파일럿; walk 메커니즘 PASSED, 실패 모드 이동 (silent miss → spec 모호성 노출)
- [F002-T5-n4-results.md](../docs/experiments/v2.9-reviewer-spec-coverage/findings/F002-T5-n4-results.md) — v2.8.1 + 명확화된 스펙 + v2.9 프롬프트 아래 n=4 reps; 네 개 통과 기준 모두 만족; SHIP

## v2.12 — Implementer 모델 선택 (출하 2026-05-15)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Hold Reviewer on Sonnet](../docs/experiments/v2.12-implementer-opus-vs-sonnet/decisions/D001-hold-reviewer-on-sonnet.md) | Reviewer/Verifier 도 Opus 로 올려야 하는가 vs Sonnet 고정 | **결정**: Sonnet 고정 — judge consistency 가 implementer 품질 향상 효과를 흐림 |
| [D002 Record used and default](../docs/experiments/v2.12-implementer-opus-vs-sonnet/decisions/D002-record-used-and-default.md) | `state.implementer_model` 필드 모양 — string 만 vs `{used, default}` 객체 | **결정**: `{used, default}` 객체로 contemporaneous default 보존; A/B 분석시 baseline 식별 가능 |

## v2.13 — Natural multi-plan (출하 2026-05-15)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 NL lexicon scope](../docs/experiments/v2.13-natural-multi-plan/decisions/D001-nl-lexicon-scope.md) | 자연어 키워드 lexicon 의 보수성 — open vs closed set | **결정**: closed 4-키 lexicon (opus/sonnet/순차/대화형 + 동의어) + 한국어 particle 분리 알고리즘; 확장은 ADR 필수 |
| [D002 Plan chain schema](../docs/experiments/v2.13-natural-multi-plan/decisions/D002-plan-chain-schema.md) | 멀티 플랜 state shape — top-level 평탄화 vs `plan_chain[]` 배열 | **결정**: `plan_chain[]` 배열 + `active_plan` integer pointer; v2.12 legacy `plan2_state` 는 schema 감지로 호환 |

---

## v2.19 — 토큰/비용 최적화 (진행 중)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 SKILL.md split boundary](../docs/experiments/v2.19-token-cost-optimization/decisions/D001-skill-md-split-boundary.md) | SKILL.md 분할 경계 — Phase 축 + cross-cutting 축 | **결정(초안)**: Option C 하이브리드 (phases/ + cross-cutting/); v2.21 D005 가 확정 |
| [D002 Extended cache applicability](../docs/experiments/v2.19-token-cost-optimization/decisions/D002-extended-cache-applicability.md) | 확장 캐시 적용 범위 | 분석 |
| [D003 Subagent state read](../docs/experiments/v2.19-token-cost-optimization/decisions/D003-subagent-state-read.md) | 서브에이전트 상태 읽기 (pre-resolved slice vs state.json fallback) | 분석/결정 |

## v2.21 — 슬리밍 + 강제 (진행 중)

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 state_set helper](../docs/experiments/v2.21-slimming-and-enforcement/decisions/D001-state-set-helper.md) | active-tree 쓰기 단일 헬퍼 — inline jq vs `state_set.py` | **결정**: 단일 `state_set.py` (dotpath + flock R-M-W + readback); active-tree 해석 내장 |
| [D002 Phase-boundary helper](../docs/experiments/v2.21-slimming-and-enforcement/decisions/D002-phase-boundary-helper.md) | 위상 경계 강제 — hook vs 헬퍼 스크립트 | **결정**: `phase_boundary.py` (task-start/task-complete/phase-emit); 비용 누적은 dispatch 경계로 분리 (accumulate_cost.py 유지) |
| [D003 Headless default vs cache](../docs/experiments/v2.21-slimming-and-enforcement/decisions/D003-headless-default-vs-cache.md) | headless 기본값 vs 캐시 온기 | **결정**: headless 기본값 유지(자율성), 캐시 분석 정정·문서화; auto-fan-out 미추가; `mode=interactive` 권장 (사용자) |
| [D004 Legacy plan2_state retirement](../docs/experiments/v2.21-slimming-and-enforcement/decisions/D004-legacy-plan2state-retirement.md) | v2.12 `plan2_state` 이중 경로 은퇴 | **결정**: resume 마이그레이션 shim (`migrate_legacy_state.py`) → `plan_chain[]` 변환 후 legacy 분기 제거 |
| [D005 Split boundary](../docs/experiments/v2.21-slimming-and-enforcement/decisions/D005-split-boundary.md) | SKILL.md 분할 경계 확정 (v2.19 D001 재확인) | **결정**: v2.19 하이브리드 레이아웃 채택 + 헬퍼 와이어링·post-D004 multi-plan·health probe 델타 |

## v2.22 — Dispatch optimization (출하 2026-05-31)

API-direct 디스패치 + 프롬프트 캐싱, T1/T2 병합, Haiku Plan Reviewer, attached-by-default.
D001–D005 + D007 은 ADR 본체가 있음; D006 은 pending (open question, 본체 없음 — 이 인덱스만).

| ADR | 주제 | Phase | 결과 |
|-----|------|-------|------|
| [D001 Haiku Plan Reviewer](../docs/experiments/v2.22-dispatch-optimization/decisions/D001-haiku-plan-reviewer.md) | Plan Reviewer 를 Haiku 4.5 로 이전 | A1 | **shipped** |
| [D002 Transition merge](../docs/experiments/v2.22-dispatch-optimization/decisions/D002-transition-merge.md) | Transition T1 + T2 를 단일 디스패치로 병합 | A2 | **shipped** |
| [D003 dispatch_via_api](../docs/experiments/v2.22-dispatch-optimization/decisions/D003-dispatch-via-api.md) | 모든 API-direct 롤의 단일 헬퍼 `dispatch_via_api.py` | B1 | **shipped** |
| [D004 Scaffold byte-stability](../docs/experiments/v2.22-dispatch-optimization/decisions/D004-scaffold-byte-stability.md) | scaffold/payload 분할을 Phase 0 Step 6.7 에서 byte-stability lint | B3 | **shipped** |
| [D005 No -p fallback](../docs/experiments/v2.22-dispatch-optimization/decisions/D005-no-p-fallback.md) | API 오류는 `-p` 로 폴백 금지 (forbidden mixed-path retry) | B6 | **shipped** |
| D006 Cache TTL ephemeral | v2.22 동안 캐시 TTL 은 ephemeral 유지 (open Q2) | — | **pending** |
| [D007 Self-Spawn attached](../docs/experiments/v2.22-dispatch-optimization/decisions/D007-self-spawn-attached.md) | Self-Spawn 기본값을 attached 로 전환 + deprecation warning | C2 | **shipped** |

**v2.22 메모**: D004 의 lint 위치는 as-shipped Task 5 deviation 에 따라 Phase 0 **Step 6.7** (Step 7.5 는 이미 v2.17 boundary-emit 이 차지). D006 은 cache-hit-ratio 데이터를 기다리는 open question 으로 ADR 본체 없이 이 인덱스에만 기록됨.

## v2.23 — Implementer adversarial self-check (종료 — SKIP, 2026-06-02)

측정 결과 부정 (baseline defect 가 현재 Sonnet 에서 더 이상 재현 안 됨). v2.9 Reviewer Spec Coverage Walk 의 Implementer-side 거울.

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Metric is prevention](../docs/experiments/v2.23-implementer-adversarial-selfcheck/decisions/D001-metric-is-prevention.md) | 측정 대상은 first-pass + retries 의 예방이지 최종 품질이 아님 | **결정** |
| [D002 Isolated Implementer measurement](../docs/experiments/v2.23-implementer-adversarial-selfcheck/decisions/D002-isolated-implementer-measurement.md) | Implementer 를 풀 오케스트레이터 실행이 아닌 격리 상태로 측정 | **결정** |

## v2.25 — Subscription-pool agent dispatch (출하 2026-06-04)

`"agent"` 디스패치 transport 추가 → 7개 역할 게이트가 metered `claude -p`/API 대신 구독 풀(Agent 툴)로 in-session 디스패치를 기본값으로 사용. Plan Reviewer 기본 모델 Opus 전환 + D003 자율 실패 래더/gap 리포팅 + D002 detach 정합.

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Agent gate + subscription default](../docs/experiments/v2.25-subscription-agent-dispatch/decisions/D001-agent-gate-subscription-default.md) | `"agent"` 게이트 값 + 7개 역할 게이트 구독-기본값 | **shipped** |
| [D002 Detach conflict handling](../docs/experiments/v2.25-subscription-agent-dispatch/decisions/D002-detach-conflict-handling.md) | detach 와 agent-gate 의 상호작용 정합 규칙 | **shipped** |
| [D003 Autonomous error handling](../docs/experiments/v2.25-subscription-agent-dispatch/decisions/D003-autonomous-error-handling.md) | 자율 오류 처리 + 에스컬레이션 자율 + 정지 경계 | **shipped** |

---

## v2.26 — Finalization + schema enforcement (출하 2026-06-04)

`interactive_attached` run 2건이 Phase 2 finalization 을 건너뛰어 state.json 이 비정합/비정규(null `completed_at`, `PENDING_BATCH` 잔존, dispatches 0, 빈 `tasks{}`+`execution_order`)로 남은 회귀. 두 standalone validator(`validate_state_schema.py`, `finalize_run.py`)를 Phase 2 게이트로 와이어링 + Stop-hook 강제 함수로 "Phase 2 미진입" 잔여 리스크 해소.

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Stop-hook forcing function](../docs/experiments/v2.26-finalization-enforcement/decisions/D001-stop-hook-forcing-function.md) | 거절됐던 Stop-hook 재도입 — 모든 태스크 terminal 시에만 validator 실행하는 저비용 short-circuit 으로 skipped-Phase-2 + 스키마 즉흥성 동시 해소 | **shipped** |

---

## v2.27 — Attached-mode enforcement gaps (출하 2026-06-06)

`interactive_attached` run 2건이 v2.26 게이트가 못 막은 두 갭 노출: (1) Phase 0 Step 2.5 가 settings.json 을 merge 없이 손으로 써서, 레포가 자체 settings.json 을 가진 ReadMates run 은 훅 4개(Stop 게이트 포함) 전부 미와이어; (2) `dispatches==0` + 모든 태스크 `timing.started` null 이 WARN 이라 drift run 이 조용히 green 으로 finalize. 결정론적 머지 스크립트 + drift severity 격상으로 해소. 잔여 부트스트랩 갭(Step 2.5 자체를 건너뛰면 Stop 게이트가 안 깔림)은 finalize-time hooks-wired 백스톱(D003)으로 축소.

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Script-materialized settings](../docs/experiments/v2.27-attached-mode-enforcement/decisions/D001-script-materialized-settings.md) | 손으로 쓰던 settings.json 을 `materialize_worktree_hooks.py` 로 — deep-merge(레포 키 보존) + Stop-gate self-assert + `--check` preflight | **shipped** |
| [D002 Blocking drift severity](../docs/experiments/v2.27-attached-mode-enforcement/decisions/D002-blocking-drift-severity.md) | cost/timing drift 를 WARN→blocking FAIL 로 격상, `cost_tracking_waived`/`timing_tracking_waived` 탈출구; Stop 게이트가 drift 차단 | **shipped** |
| [D003 Finalize hooks-wired backstop](../docs/experiments/v2.27-attached-mode-enforcement/decisions/D003-finalize-hooks-wired-backstop.md) | Step 2.5+preflight 둘 다 건너뛴 run 을 위해 `finalize_run.py` 가 워크트리 settings.json 의 4개 훅 와이어링 검사 — 미와이어 시 `hooks_not_wired` FAIL(`hooks_wiring_waived` 면제), 검사 불가 시 skip(replay false-positive 방지) | **shipped** |

---

## v2.28 — Instrumentation integrity (출하 2026-06-07)

v2.27 이후 실행된 `interactive_attached` run 3건이 boundary-only 처방이 안 먹힘을 증명 — 셋 다 cost ledger 가 비어 있음. run3(`session-package`)은 blocking FAIL 에 걸렸지만 waive 안 하고 그냥 wedge(`status:null`, `current_task=16`), `timing.started` 가 `completed` 보다 9시간 늦음(KST 리터럴+가짜 `Z`). run2(`readmates-resilience`)/run1(`target-type`)은 `cost_tracking_waived=true` 를 반사적으로 켜고 진행, run1 은 `"1".."6"`+`"riskclose"` 키 + `quality_trend:[]`, 셋 다 `agentlens_orchestration_run:null`. 근본 원인: 기록돼야 할 값이 attached 오케스트레이터가 손으로 수행하는 prose 로 존재 → 컨텍스트 압박 시 스킵/즉흥. v2.27 은 finalize 경계에서만 잡았고, v2.28 은 기록 사이트에서 잡으며(가능한 경우) 구조적으로 기록 불가능한 한 곳(agent 경로 cost)은 시스템이 정직하게 만든다.

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Cost auto-waive on the agent path](../docs/experiments/v2.28-instrumentation-integrity/decisions/D001-cost-auto-waive-on-agent-path.md) | Agent-tool 디스패치는 `usage` 미반환 → 모든 gate `"agent"` + attached 면 Phase 0 Step 7 이 `cost_tracking_waived`/`cost_tracking_waive_reason="agent-dispatch-no-usage"` 자동 설정(mandate→honest auto-waive); "subscription dispatches still report usage" 허위 prose 제거; 두 필드 run-level 보존 | **shipped** |
| [D002 Stop-gate all-terminal trigger](../docs/experiments/v2.28-instrumentation-integrity/decisions/D002-finalize-trigger-all-terminal.md) | v2.26 Stop 게이트의 "done" 판정이 Phase-2-set 신호(`status==COMPLETE`/`current_task==null`)에만 의존 → Phase 2 미실행이 실패 모드. `elif [ "${TOTAL:-0}" -gt 0 ]` DONE=1 분기 추가 — 선언된 모든 태스크 terminal 이면 finalize 강제 | **shipped** |
| [D003 Timing sanity + coverage + task-key checks](../docs/experiments/v2.28-instrumentation-integrity/decisions/D003-timing-sanity-coverage-keys.md) | `finalize_run.py` 가 `_parse_iso` 로 timing 파싱 후 `completed < started` 시 **면제 불가** blocking `timing_inverted` FAIL; `quality_trend_sparse`/`agentlens_run_absent` WARN; `quality_trend` 는 `phase_boundary.py` task-complete 단일 작성자; `validate_state_schema.py` 가 `TASK_KEY_RE` 로 `task_key_noncanonical` WARN | **shipped** |

---

## v2.29 — Quality uplift (출하 2026-06-07)

I1–I12 12개 품질 개선 (축 A 컨텍스트 절감 / B 자율 문제판단 / C 사후 로그). 전부 additive, `schema_version` 불변. 한글 설계/구현 문서(`docs/improvements/품질개선-{플랜,구현}-ko.md`)에서 도출. 단일 세션 실행(플랜의 공유 파일 경합 + "병렬성 미증가" §3.1 → 멀티에이전트 부적합).

| ADR | 주제 | 결과 |
|-----|------|------|
| [D001 Agent SDK context-editing deferred](../docs/experiments/v2.29-quality-uplift/decisions/D001-agent-sdk-context-editing-deferred.md) | I12 — 네이티브 context-editing/memory tool 은 API beta 헤더(`context-management-2025-06-27`)가 Claude Code/`claude -p` 실행 형태에서 비활성 → 미적용, 기록만; 근시일 효과는 I11(인세션 등가)로. Agent SDK 포팅 시 재검토 | **decided (record-only)** |

---

## 가로지르는 결정 (한 실험 아래에 속하지 않음)

### 오케스트레이터-워커 패턴 (vs 단일 세션)

[`../ARCHITECTURE.md`](../ARCHITECTURE.md) §2 + §11 에 문서화. v2.4.0 에서 기원. 선택: Opus 오케스트레이터 + Sonnet 서브에이전트가 계획 실행에 대한 Anthropic 가이드와 일치. 단일 세션 대비 트레이드오프: 더 좋은 병렬성, 서브에이전트당 fresh 컨텍스트, 토큰 비용 증가.

### 실행별 샤딩 학습 로그 (vs 단일 `events.jsonl`)

ADR: v2.8 D001 §Question 1. 기원: v2.8 설계 라운드 3에서 사용자 피드백. 선택: 실행별 디렉터리 레이아웃이 `flock` 없이 동시 쓰기 경합 제거. 빈 실행도 `meta.json` 을 부정 신호로 남김.

### 학습 로그 헬퍼의 단일 작성자 계약

ADR: v2.8 D001 §Q4 (advisor-patch). 기원: 출하 전 advisor 리뷰가 서브에이전트들이 `MAE_LEARNING_RUN_ID` 로 헬퍼 호출하면 Agent 툴 디스패치(env 전파 X)와 `claude -p` 서브프로세스(POSIX env 작동)를 혼동한다는 걸 잡음. 선택: 서브에이전트는 JSON 후보를 쓰고, 오케스트레이터가 유일한 호출자.

### 모든 종료 경로에서 `close-run`

ADR: v2.8 D001 §Q5 (advisor-patch). 기원: 원 설계는 Phase 2 에서만 `close-run` 호출. ESCALATE / 훅 거부 / 하드 크래시는 `meta.outcome=unknown` 을 영구히 남김. 선택: 명시적 close-run — success (Phase 2), blocked (ESCALATE / state-write 실패), aborted (user/hook). 하드 크래시 → `unknown` 은 정직.

### Spec Coverage Walk 의 메타 규칙 적대적 생성

ADR: v2.9 D001 §Q3. 기원: pre-advisor self-check 가 초기 "strict-template enumeration only" 설계로는 픽스처 08의 `30m20m` 케이스 (스펙의 메타 규칙으로만 커버됨)를 노출 못한다는 걸 잡음. 선택: walk가 두 ordered sub-step; sub-step B 가 메타 규칙당 ≥3 적대적 입력 명시적 요구.

### Step 7.5 의 MANDATORY 표현 (v2.8.1)

HISTORY.md v2.8.1 항목에 문서화된 경험적 결정. 기원: F001-smoke.md 의 Smoke B 가 SKILL.md 가 지시했음에도 47개 Bash 호출 중 0개가 헬퍼를 부르지 않았음을 보임. 선택: 더 강한 prose + 가시 마커 + eval 수준 준수 체크. 훅 기반 강제는 v2.10+ 으로 연기 ([`deferred-candidates.md`](./deferred-candidates.md) §Hooks).

---

## 번복 / 대체된 결정들

| 원 결정 | 대체 | 이유 |
|---------|------|------|
| v2.8 Step 7.5 "advisory" 표현 (`2>/dev/null \|\| echo ""`) | v2.8.1 MANDATORY 표현 + 마커 | Smoke B 에서 경험적 준수 회귀 |
| v2.8 D001 초기 "서브에이전트가 env로 헬퍼 호출" | v2.8 D001 §Q4 단일 작성자 계약 | advisor 가 env 전파 모호성 잡음 |
| v2.8 D001 초기 "Phase 2 에서만 close-run" | v2.8 D001 §Q5 모든 종료 경로 close-run | advisor 가 `outcome=unknown` 회귀 잡음 |
| v2.9 D001 초기 "strict-template enumeration only" | v2.9 D001 §Q3 enumeration + 적대적 생성 | pre-advisor self-check 가 `30m20m` 케이스 enumeration 단독으로 노출 안 됨 잡음 |
| v2.7 D008 `quality_plus` 설계 | (출하 안 됨) | F002 ceiling 결과: marginal gain 이 구현 표면 면적 가치 못 미침 |

## ADR 추가 방법

새 ADR은 부모 실험 디렉터리 안에:
```
docs/experiments/v2.X-<name>/decisions/D00N-<short-slug>.md
```

[`_template/decisions/D000-template.md`](../docs/experiments/_template/decisions/D000-template.md) 를 출발점으로 사용. 표준 섹션: Context · Options · Decision · Rationale · Consequences · Links.

그 다음 이 파일의 해당 섹션 (v2.X 표) 에 행을 추가해서 가로지르는 검색으로 찾을 수 있게 함.

실험을 가로지르는 *cross-cutting* 결정 (예: 오케스트레이터-워커 패턴)은 위 "가로지르는 결정" 섹션에 추가, 본체를 담고 있는 ARCHITECTURE.md 섹션 또는 HISTORY.md 항목 포인터와 함께.
