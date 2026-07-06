# CME v3.0 Deterministic Kernel Design

작성일: 2026-07-06
상태: APPROVED DESIGN SPEC
대상 표면: `skills/kws-claude-multi-agent-executor` (CME) v3.0 대형 리디자인

## Problem

CME v2.25→v2.29의 실제 회귀는 전부 같은 근본 원인을 가진다: **오케스트레이터
LLM이 SKILL.md 프로즈 상태머신을 실행하다가 컨텍스트 부하에서 지시를 조용히
스킵한다.**

실측 근거 (`docs/risks-and-limitations.md`, HISTORY.md v2.25–v2.29,
experiments findings):

- v2.8 F001 Smoke B: 47회 Bash 호출 중 Step 7.5 init-run 실행 0회.
- v2.14→v2.28: cost ledger `dispatches=0` — 프로즈 지시였던 비용 집계가 전
  관측 런에서 스킵. v2.16 helper 강제 후에도 v2.25 agent 디스패치 전환으로
  구조적 공백(auto-waive) 발생.
- v2.16→v2.28: `timing.started` 전부 null인 attached 런 3회 →
  `timing_tracking_absent` blocking FAIL로 승격, `timing_inverted`
  un-waivable FAIL 추가.
- v2.26→v2.27: 훅 미배선 런(레포 자체 settings.json과의 병합 실패),
  스크립트 materialize + finalize 백스톱으로 대응.
- v2.26→v2.28: 전 태스크 COMPLETE인데 미완결(wedge) 상태로 종료한 런 2+1회 →
  Stop 훅 3중 트리거로 대응.

매 버전의 대응이 "프로즈 → 스크립트 강제 + 훅 백스톱"으로 이동해 왔다. v3.0은
이 궤적을 끝까지 밀어붙여 **판정·기록·전이를 전부 스크립트 커널로 이관**하고,
백스톱(사후 감지) 대신 구조적 강제(사전 보장)로 전환한다.

보조 입력 두 갈래가 같은 방향을 가리킨다.

1. **CPE(kws-codex-plan-executor) v2.27**: LLM 주변을 결정론적 스크립트로
   감싼 선행 사례. `parse_plan.py`, task packets(컨텍스트 예산),
   `preflight_dispatch.py`(delegate/local_fallback/block 결정론 판정),
   `reconcile_state.py`/`repair_runs.py`(드리프트), `run_quality`(운영 부채
   등급), 구조화 `completion_audit`, command observations/recovery 분류 —
   대부분 Codex 비의존적이며 이식 가능.
2. **Claude 공식 문서**: `claude -p --output-format json --json-schema`가
   스키마 준수 JSON + usage/cost를 구조적으로 반환. 텍스트 마커
   (`STATUS:`/`SUMMARY:`) 파싱과 SubagentStop 사후 검증을 사전 보장으로
   대체 가능. `--model` 명시로 기존 "headless model gap" 리스크도 해소.

## Goals

우선순위 (사용자 확정):

1. 실행 신뢰성 — 북키핑 손실·미완결 종료 클래스의 구조적 소멸
2. 서브에이전트 품질·통제 — 스키마 출력 계약, write-scope, 시도 계보
3. 운영성·사후 검사 — run_quality, completion_audit, 드리프트 복구
4. 컨텍스트·비용 효율 — task packets, headless usage 기반 원장, 캐시 유지

제약:

- CME는 Claude Code 스킬로 독립 유지 (Waygent 수렴은 이번 범위 밖).
- attached / headless 모드 동등 — 커널이 모드 차이를 흡수.
- **headless `-p` 디스패치를 적극 활용** (사용자 지시): 기본 transport를
  `"p"`로 반전.
- 기존 경로 규약(`~/.claude/worktrees/<RUN_ID>` + `~/.claude/orchestrator/<RUN_ID>`
  형제 구조), 리스크 티어, 리트라이 예산, 품질 임계값(SPEC 0.85 / QUALITY
  0.75, Goodhart 가드)은 유지.
- AGENTS.md 실험 프로토콜 준수: `docs/experiments/v3.0-deterministic-kernel/`
  선개설, 브랜치 기반 구현, findings 근거 후 main 반영.

## §1 아키텍처 — 커널-오케스트레이터 계약

역할 역전: 커널(스킬 내 `scripts/kernel/` 단일 CLI `kernel.py`)이 판단하고,
LLM 오케스트레이터는 커널이 지시한 액션의 수행자가 된다.

실행 사이클 (매 스텝 동일):

```
1. LLM:  kernel next --state <orch_dir>/state.json
2. 커널: 다음 액션 JSON 반환
         {action: dispatch, role: implementer, task: task_3,
          prompt_path: ..., schema_path: ..., transport: p|agent, model: ...}
         (또는 run_check / escalate_to_user / compact / finalize / halt)
3. LLM:  액션 수행 — claude -p --json-schema (기본) 또는 Agent 툴,
         결과 JSON을 파일로 저장
4. LLM:  kernel submit --task task_3 --role implementer --result <file>
5. 커널: 스키마 검증 → state.json 원자적 갱신(타이밍·비용·retry 카운터·
         quality_trend·events.jsonl 전부 커널 기록) → 전이 판정
```

구조적 귀결:

- **state.json 단일 작성자는 커널.** LLM은 상태를 직접 쓰지 않는다.
  타이밍 null, 비용 0, quality_trend 미기록이 재발 불가능.
- **attached/headless 동등**: transport 무관 동일 커널 로직. 수행 단계만
  갈라지고 결과 제출·검증 경로는 하나.
- **훅 지위 변화**: Stop 게이트는 `kernel check-stop` 호출로 교체(파이널라이즈
  판정 재사용). SubagentStop 출력 구조 검증은 submit 스키마 검증으로 흡수.
  PreToolUse 위험 명령 차단·PostToolUse 디버그 아티팩트 스캔은 유지.
- **SKILL.md 대폭 축소**: 인자 파싱도 커널 `init`이 수행(결정론 파서 + echo
  line). SKILL.md에는 커널 액션별 수행 방법과 가드레일 요약만 남는다. 8개
  phase reference 파일의 판정 로직은 커널로 이관, 프롬프트 템플릿은
  `references/`에 유지.
- **커널 장애 시 하드 홀트.** 프로즈 대체 진행 금지 — 허용하면 v2.x 문제가
  귀환한다.

## §2 컴포넌트 — 커널 모듈과 디스패치 계층

### 커널 모듈 (`scripts/kernel/`, 순수 Python, 외부 의존 없음)

| 모듈 | 역할 | 출처 |
|------|------|------|
| `init.py` | 3-pass 인자 파서(NL 렉시콘)+echo line, run-id/경로 생성, worktree+훅 materialize, v2.x state 마이그레이션 심 | Phase -1.0 코드화 + `materialize_worktree_hooks.py`, `migrate_legacy_state.py` 흡수 |
| `plan.py` | 플랜 기계 판독: H2/H3 태스크 헤더, Files 블록(한국어 별칭 포함), YAML task 블록, 의존성 그래프 | CPE `parse_plan.py` 포팅 |
| `packets.py` | spec 매니페스트 + task packets: 태스크당 컨텍스트 예산(기본 60KB), 섹션 매핑, fallback 사유+`next_action` 진단 | CPE 이식, 기존 spec_manifest 확장 |
| `gate.py` | 리스크 티어, effort 스케일링, wave 분할, 결정론적 사전 디스패치 판정(delegate/local/block + would-have 어드바이저리), raw/effective blocking 이중 카운트 | 기존 Step 4/6 + CPE `preflight_dispatch.py`, `audit_plan_executability.py` |
| `transitions.py` | 리트라이/WARN/에스컬레이션 예산, spec-edit 분기, verifier reset 규칙, 컴팩션·Resume Chain 트리거 | 현행 가드레일 코드화 |
| `dispatch.py` | 프롬프트 조립(scaffold/payload 캐시 분할 유지) + transport 실행 지시 생성 | 기존 + 신규 |
| `ledger.py` | `-p` JSON usage에서 비용·타이밍 기계 전사, 경계별 예산 평가 | `accumulate_cost.py`, `price_table.py` 흡수 |
| `recovery.py` | 커맨드 관찰 분류(env/flaky/OOM vs 구현 버그) + root-signature 복구 예산 | CPE `classify_recovery.py` 포팅 |
| `drift.py` | 파이널라이즈 전 드리프트 감지+안전 복구, stale run 정리(dry-run 우선) | CPE `reconcile_state.py`/`repair_runs.py` 포팅 |
| `quality.py` | run_quality 운영 부채 등급(제품 정합 ≠ 실행기 효율), 구조화 completion_audit(잔여 리스크 클래스), 최근 런 집계, eval용 정규화 replay | CPE 포팅 + `finalize_run.py`/`validate_state_schema.py` 통합 |
| `events.py` | events.jsonl 단일 작성자 + AgentLens 방출(best-effort 가드 유지, kws-cme.* 네임스페이스 유지) | `phase_boundary.py` 흡수 |

### 디스패치 계층 — headless-first

- 기본 transport `"p"`: 모든 역할이
  `claude -p --output-format json --json-schema references/schemas/<role>.json --model <명시>`
  로 실행. 결과 파일은 `<orch_dir>/results/`, 커널이 스키마 검증 후 수리.
- Implementer도 headless 통일: `-p` detached 병렬 실행으로 Parallel Sub-Flow가
  "N개 detached 프로세스 + 커널 폴링"으로 단순화. 파일 disjoint 검증은
  커널 submit 시 수행 (현행 P.4 규칙 유지).
- `dispatch_config` 역할 게이트 유지, 기본값만 `agent`→`p` 반전. 구독 풀
  Agent 툴은 명시적 opt-in. Agent 게이트 사용 시에만 cost waive 필드군 잔존.
- 역할 스키마 5종 (`references/schemas/{implementer,reviewer,verifier,plan_reviewer,docs}.json`)
  이 `STATUS:`/`SUMMARY:` 텍스트 마커를 전면 대체. ESCALATE도 스키마 내
  구조화 필드.
- 모델 라우팅: orchestrator=Opus, 전 서브에이전트 기본 Sonnet 유지, `--model`
  항상 명시 (headless model gap 해소). Haiku 하향은 출하 후 별도 A/B 실험
  (deferred-candidates J의 조건 준수).
- 서브에이전트 TDD 계약 유지: implementer 프롬프트의
  `superpowers:test-driven-development` 부트스트랩과 RED/GREEN 증거 보고는
  스키마 필드(`method_audit`)로 구조화.

## §3 데이터 플로우와 상태 스키마

### 디렉터리 레이아웃 (경로 규약 현행 유지)

```
<orch_dir>/
├── state.json            # v3 스키마, 커널 단일 작성자, flock+원자적 R-M-W
├── events.jsonl          # 커널 tee (AgentLens 도달성과 무관하게 항상 기록)
├── packets/task_N.json   # task packets (+ 사람용 .md 뷰는 파생물)
├── prompts/<role>_<task>.md
├── results/<role>_<task>_<attempt>.json   # -p 구조화 출력 원본 (usage 포함)
├── hooks/                # 현행 유지
└── DECISIONS.md          # decisions_register 마크다운 프로젝션
```

### state.json v3

- `schema_version: 3` 명시. `plan_chain`/`<active>` 해석 규칙 유지하되 해석
  코드는 커널 안에만 존재 — SKILL.md의 `<active>` 치환 프로즈 전체 삭제.
- 태스크 레코드 신규 필드: `attempts[]`(시도 계보, 거부 시도는
  `superseded_by`로 보존), `dispatch_decision`(gate 판정+사유),
  `command_observations[]`, `recovery_attempts[]`.
- 런 레벨 신규: `run_quality`(readiness / dispatch_consistency /
  context_quality / verification_quality + open_followups + grade),
  `completion_audit`(체크리스트·검증 증거·잔여 리스크 클래스), `drift`
  (감지·복구 이력).
- 비용·타이밍은 결과 파일 usage에서 커널이 기계 전사.

### 플로우

`init`(파싱·마이그레이션·worktree·훅) → `plan.py`+`packets.py`(기계 판독·패킷)
→ 준비성 감사(차단 이슈 raw/effective 이중 카운트, operator 리뷰 기록) →
사이클 `next→dispatch→submit` → 경계마다 컴팩션·예산 평가 → `drift.py` 통과
후 `quality.py`가 completion_audit·run_quality 작성 → run-close.

### 마이그레이션

`init.py`가 v2.x state.json 감지 시 v3 단방향 변환. 변환 불가 필드는
`legacy` 서브트리에 보존 — 데이터 파기 없음.

## §4 에러 처리와 안전 게이트

- **에스컬레이션**: 결과 스키마의 `escalate` 오브젝트(type:
  AMBIGUITY/SPEC_BLOCKER/ENV_BLOCKER, 근거, 질문) → 커널이 예산(태스크당
  3회) 차감 후 `escalate_to_user` 액션 반환. 문서 수정은 오케스트레이터
  전담 유지, 수정 후 커널이 매니페스트 재빌드·변경 섹션만 재읽기 지시
  (v2.29 I6 유지).
- **환경 실패 vs 구현 버그 분리**: Verifier FAIL 시 `recovery.py`가 커맨드
  증거 선분류 — env/flaky/timeout 판정이면 리트라이 예산 소모 없이
  bootstrap/재시도 1회, 동일 root-signature 반복 시 차단. 구현 버그일 때만
  `git reset --hard <pre_task_sha>` + 재디스패치.
- **리트라이/스킵 정책 현행 유지**: 리뷰 3회·검증 3회 초과 → SKIP +
  `verification_gaps` 기록 후 계속 (v2.29 I1). 판정·기록은 커널.
- **하드 홀트**: 커널 자체 오류, state 쓰기 실패, 동일 디스패치 스키마 검증
  3연속 실패, 예산 초과(`budget_action=pause`). 홀트 시 events.jsonl blocker
  기록 + run-close(blocked)까지 커널 수행 — wedge 방치 불가능.
- **훅 단순화**: Stop 게이트 = `kernel check-stop`. PreToolUse/PostToolUse
  현행 유지. 훅 materialize는 `init` 내장이라 스킵 불가.
- **폴라이트-스톱 금지 불변식 유지**: `next`가
  finalize/escalate_to_user/halt를 반환하기 전까지 같은 턴에서 사이클 계속.

## §5 테스트·평가와 이행 계획

- **커널 단위 테스트** (`tests/kernel/`): 순수 Python이라 per-commit 무료.
  전이 규칙, 패킷 예산, 게이트 판정, 마이그레이션 픽스처 커버. 판정 로직이
  LLM 밖으로 나오면서 기존 "풀 eval $40–120" 빈도 제약을 구조적으로 우회.
- **replay eval**: `quality.py` 정규화 출력(CPE `normalize_cpe_run.py` 포팅)
  을 eval 증거 표준으로. 금지 패턴(절대 홈 경로, 시크릿) 스캔 포함.
- **기존 eval 스위트 재베이스라인**: SPEC 0.85 / QUALITY 0.75 임계값 유지
  (Goodhart 가드), 하네스가 커널 사이클을 구동하도록 어댑터 수정.
- **실험 프로토콜**: `docs/experiments/v3.0-deterministic-kernel/` 선개설
  (README/JOURNAL/ADR). ARCHITECTURE.md·HISTORY.md·스냅샷 동커밋 갱신.
  브랜치 구현, findings 근거 후 main 반영.
- **내부 구현 순서** (단일 v3.0 출하): ① 커널 스캐폴드+스키마 계약+headless
  디스패치 → ② CPE 포팅 모듈(packets/gate/recovery/drift/quality) →
  ③ SKILL.md 축소·phase reference 정리 → ④ 재베이스라인.
  Haiku A/B는 출하 후 별도 실험.

## Out of Scope

- Waygent 수렴/통합 (별도 방향, AGENTS.md 참조).
- Agent Teams 등 실험 플래그 기능에 대한 코어 의존.
- 품질 임계값 변경·사용자 설정화 (기각된 유보 후보 K 유지).
- Haiku 역할 하향의 기본값 채택 (측정 후 별도 결정).
- CPE 자체 변경 (CPE는 이번 리디자인의 참조 원천일 뿐).

## Success Criteria

1. 커널 단위 테스트 전체 green + 기존 eval 재베이스라인 통과.
2. 실 플랜 2회 이상(attached·headless 각 1회)에서: 타이밍·비용 필드 완전
   기록(waive 없음), wedge 없는 종료, run_quality·completion_audit 생성.
3. SKILL.md 본문에서 상태 전이·북키핑 프로즈 지시 제거 확인 (커널 액션 수행
   가이드만 잔존).
4. `STATUS:` 텍스트 마커 파싱 코드 0건 — 전 역할 스키마 검증 경로.
