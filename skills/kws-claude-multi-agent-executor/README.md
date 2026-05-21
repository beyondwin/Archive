# kws-claude-multi-agent-executor

구현 계획(plan)과 디자인 스펙(spec)을 입력받아 **자율적으로** 끝까지 실행하는 Claude Code 스킬. Opus **오케스트레이터** 한 명이 새로 생성되는 Sonnet **서브 에이전트**들(Implementer / Reviewer / Verifier / Plan Reviewer / Docs Updater)에게 작업을 분배합니다. 오케스트레이터는 3단계 라이프사이클을 결정론적으로 진행하며, 각 실행은 별도의 git worktree에 격리되고, 모든 태스크는 구조화된 루브릭으로 채점되며, 주요 이벤트는 **AgentLens** (`kws-cme.*` 이벤트 네임스페이스) 에 기록되어 스킬 자체의 개선에 사용됩니다.

**현재 버전**: `2.17.0` (2026-05-19) — 버전 타임라인은 [`HISTORY.md`](./HISTORY.md) 참조.

**최근 변경 (Recent changes)**:
- **v2.17** — AgentLens 컷오버 (Task 11): `append_learning_event.py` + 평행 `~/.claude/learning/...` 쓰기 경로 제거. AgentLens 단독 이벤트 싱크 (`kws-cme.*`). `agentlens_orchestration_run` run-level 필드, `ORCH_RUN_ID` env 전파, Resume Chain handoff에서 `kws-cme.context_health` 스냅샷 emit. dormant `archive_run.sh` + `render_html_report.py` 체인(v2.14 F1/F3) 제거. 패리티는 `scripts/compare_agentlens_events.py --self-test`로 검증.
- **v2.16** — Timing/cost 헬퍼 강화: `timing.started` (태스크 디스패치 전), `state.timestamps.completed_at` (Phase 2 Step 2), `scripts/accumulate_cost.py` (F2 비용 집계가 v2.14에서는 prose-only로 silent skip 됐던 회귀 수정).
- **v2.15** — Context engineering: 티어드 spec injection (`spec_manifest`), per-plan `decisions_register`, 토큰 기반 Resume Chain 트리거.
- **v2.14** — Forensics & cost: archive on close-run, cost ledger, query helpers, run reports (post-v2.17 AgentLens cutover로 archive/HTML 파이프라인은 제거됨).
- **v2.13** — Natural multi-plan: `planN=/specN=` 자동 체인 + NL 키워드 lexicon (opus/순차/대화형 등).
- **v2.12** — Implementer 모델 선택 (`implementer_model=opus|sonnet`); Reviewer/Verifier 는 Sonnet 고정.
- **v2.11** — Method audit gate at Phase 2; ENV_BLOCKER triage categories; local-env preflight; `resource_key` plan annotation; learning-log outcome coherence.

---

## 빠른 시작

스킬은 `~/.claude/skills/kws-claude-multi-agent-executor/` 에 심링크로 설치되어 있습니다. Claude Code에서:

```
/kws-claude-multi-agent-executor plan=<계획문서경로> spec=<스펙문서경로>
```

선택 인자: `risk=<low|mid|high>`, `docs_scope=<file1,file2>`, `plan2=<연결할둘째계획.md>`, `mode=<interactive|headless>`. 전체 호출 계약은 [`SKILL.md`](./SKILL.md) Phase 0 참조.

자세한 사용법·시나리오·트러블슈팅은 [`docs/usage.md`](./docs/usage.md) 부터 읽으세요.

## 문서 지도 — 어디서 무엇을 찾는가

### 개념을 이해하고 싶다

| 질문 | 문서 |
|------|------|
| 이 스킬이 뭐고, 머릿속에 어떻게 그려야 하나 | 이 파일 위쪽 + [`ARCHITECTURE.md`](./ARCHITECTURE.md) §1 |
| 런타임 동작 전반 — 단계·서브에이전트·디스패치·채점 | [`ARCHITECTURE.md`](./ARCHITECTURE.md) §2-§12 |
| 한 번의 실행이 어떻게 진행되는지 시뮬레이션 | [`docs/how-it-works.md`](./docs/how-it-works.md) |
| 용어 사전 (orchestrator / sub-agent / worktree / risk tier 등) | [`docs/glossary.md`](./docs/glossary.md) |
| 2.X와 2.Y의 차이 | [`HISTORY.md`](./HISTORY.md) §1 |
| 어떤 영역이 언제 개선되었나 | [`HISTORY.md`](./HISTORY.md) §2 |
| **왜 이런 설계인가 (입문)** | [`docs/design-decisions.md`](./docs/design-decisions.md) |

### 스킬을 실행·운영하고 싶다

| 작업 | 문서 |
|------|------|
| **호출법·인자·시나리오** | [`docs/usage.md`](./docs/usage.md) |
| 스킬을 계획에 적용 | [`SKILL.md`](./SKILL.md) Phase 0 §Invocation |
| 회귀 eval 스위트 실행 | [`evals/README.md`](./evals/README.md) |
| 학습 로그 읽기·분석 | [`references/learning-log.md`](./references/learning-log.md) |
| 실패한 실행 진단 | [`docs/troubleshooting.md`](./docs/troubleshooting.md) |
| 특정 세션 디버깅 (리플레이) | [`docs/how-it-works.md`](./docs/how-it-works.md) §Replay |

### 동작을 바꾸거나 기여하고 싶다

| 작업 | 문서 |
|------|------|
| AI 기여자가 가장 먼저 읽어야 할 곳 | [`docs/onboarding-for-ai-agents.md`](./docs/onboarding-for-ai-agents.md) |
| 필수 기록 프로토콜 (experiment / history / advisor) | [`AGENTS.md`](./AGENTS.md) |
| 새 실험 시작 (≥50줄 변경, 또는 비자명한 가설) | [`docs/experiments/README.md`](./docs/experiments/README.md) + [`docs/experiments/_template/`](./docs/experiments/_template/) |
| 새 eval 픽스처 추가 | [`evals/README.md`](./evals/README.md) §Fixture format |
| 특정 설계 결정의 배경 | [`docs/decision-log.md`](./docs/decision-log.md) |
| 버전 번프 + 릴리즈 | [`AGENTS.md`](./AGENTS.md) §ARCHITECTURE.md sync + [`HISTORY.md`](./HISTORY.md) §Update protocol |

### 한계와 향후 작업을 알고 싶다

| 질문 | 문서 |
|------|------|
| 무엇이 불안정·취약하거나 부분만 검증되었나 | [`docs/risks-and-limitations.md`](./docs/risks-and-limitations.md) |
| 무엇이 의도적으로 미뤄졌나 | [`docs/deferred-candidates.md`](./docs/deferred-candidates.md) |
| 특정 결정의 대안과 채택 이유 | [`docs/decision-log.md`](./docs/decision-log.md) → 개별 D### 파일 |
| 최근 실험 결과 | [`docs/experiments/`](./docs/experiments/) |

### 나는 다음 세션에서 이 작업을 이어받는 AI 에이전트다

**아래 순서로 읽으세요**:

1. 이 README (현재 위치)
2. [`docs/onboarding-for-ai-agents.md`](./docs/onboarding-for-ai-agents.md) — 운영 규범, 진입점
3. [`AGENTS.md`](./AGENTS.md) — 기록 프로토콜 (**필수**)
4. [`ARCHITECTURE.md`](./ARCHITECTURE.md) §1-§4 — orchestrator-worker 멘탈 모델
5. [`docs/risks-and-limitations.md`](./docs/risks-and-limitations.md) — 알려진 취약점
6. [`HISTORY.md`](./HISTORY.md) §1 가장 최근 2개 항목 — 최근 변경
7. [`docs/decision-log.md`](./docs/decision-log.md) — "왜"에 대한 깊은 인덱스

이후 필요할 때 SKILL.md / learning-log.md / 픽스처 YAML 등을 로드.

## 핵심 불변식 (반드시 외울 것)

이들은 골격을 떠받치는 규칙입니다. 위반하면 한참 뒤에 표면화되는 방식으로 스킬이 깨집니다.

1. **오케스트레이터 1개, worktree 1개, `state.json` 1개.** worktree당 계획 실행은 순차적입니다. 동시 실행은 별도 worktree (공유 상태 없음). [`ARCHITECTURE.md`](./ARCHITECTURE.md) §5-§6 참조.
2. **서브 에이전트는 학습 로그 헬퍼를 절대 직접 호출하지 않습니다.** 후보 JSON을 `<orch_dir>/learning_events/<task_id>-<role>.json` 에 쓰고, 오케스트레이터(단일 작성자)가 `append`를 호출합니다. [`references/learning-log.md`](./references/learning-log.md) 참조.
3. **Step 7.5 `init-run`은 필수입니다** (v2.8.1). 건너뛰면 실행 전체의 관측성이 깨집니다 (meta.json 없음, events.jsonl 없음). `run.jsonl`의 `LEARNING_LOG_INIT:` 마커가 사후 감사 신호입니다.
4. **`close-run`은 모든 종료 경로에서 호출됩니다**: `outcome=success` (Phase 2 정상 종료), `outcome=blocked` (state 쓰기 실패, 에스컬레이션 소진), `outcome=aborted` (사용자/훅 중단). 하드 크래시는 `outcome=unknown` (정직).
5. **위험 등급은 TDD 엄격도를 결정합니다 — 모델 선택이 아닙니다.** 모델 선택은 Orchestrator=Opus / Sub-agents=Sonnet으로 문서화되어 있지만, 아직 `--model` 플래그가 `claude -p` 서브프로세스에 전달되지 않습니다 ([`docs/risks-and-limitations.md`](./docs/risks-and-limitations.md) §Headless model gap).
6. **Reviewer는 채점 전에 `SPEC_COVERAGE_WALK:`를 발산합니다** (v2.9.0). 두 단계: A) 명시된 요구사항 열거, B) 메타 규칙 기반 적대적 생성. [`references/reviewer-prompt.md`](./references/reviewer-prompt.md) 참조.

## 레포 레이아웃

```
skills/kws-claude-multi-agent-executor/
├── README.md                       ← 현재 위치 (한글, 사람용 진입점)
├── SKILL.md                        ← 실행 가능한 스킬 (v2.9.0, 영어, 에이전트 전용)
├── ARCHITECTURE.md                 ← 시스템 설계 (한글, 14개 섹션)
├── AGENTS.md                       ← AI 기여자 운영 프로토콜 (영어, 에이전트 전용)
├── HISTORY.md                      ← 버전 타임라인 + 개선 영역 + 실험 인덱스
├── docs/                           ← 사람용 한글 심화 자료
│   ├── usage.md                    ← 사용법·시나리오·인자 [NEW 한글]
│   ├── design-decisions.md         ← 설계 결정의 배경 [NEW 한글]
│   ├── how-it-works.md             ← 런타임 시뮬레이션 [한글]
│   ├── glossary.md                 ← 용어 사전 [한글]
│   ├── decision-log.md             ← ADR 교차 인덱스 [한글]
│   ├── risks-and-limitations.md    ← 통합 리스크 레지스터 [한글]
│   ├── deferred-candidates.md      ← 향후 작업 선반 [한글]
│   ├── onboarding-for-ai-agents.md ← AI 에이전트가 먼저 읽는 곳 (영어 유지 — 대상이 에이전트)
│   ├── troubleshooting.md          ← 흔한 문제 + 해결 [한글]
│   ├── doc-update-protocol.md      ← 변경 종류별 갱신 체크리스트 [한글]
│   ├── how-to/                     ← 작업 가이드
│   ├── snapshots/                  ← 출시 시점 상태 스냅샷
│   └── experiments/                ← 실험 기록
├── references/                     ← 영어, 에이전트 프롬프트 (절대 한글화 X)
│   ├── implementer-prompt.md       ← 서브에이전트 프롬프트 템플릿
│   ├── reviewer-prompt.md          ← (v2.9.0 Spec Coverage Walk)
│   ├── verifier-prompt.md
│   ├── plan-reviewer-prompt.md
│   ├── docs-updater-prompts.md     ← Phase 2 문서 업데이트 프롬프트
│   ├── escalation-playbook.md      ← ESCALATE 유형 → 이벤트 심각도 매핑
│   ├── learning-log.md             ← 스키마 + 단일 작성자 계약 + 10개 이벤트 타입
│   └── best-of-n-judge-prompt.md   ← 고아 참조 (v2.7 deferred)
├── evals/
│   ├── README.md
│   ├── run.sh                      ← 픽스처별 하네스 (bash + jq)
│   ├── rubric.py                   ← 결정론적 정확성 측정
│   ├── judge.md                    ← LLM-as-judge 프롬프트
│   ├── check_skill_contract.py     ← 18개 결정론적 체크
│   ├── fixtures/                   ← 8개 YAML 픽스처 (01-08)
│   ├── baselines/                  ← 버전별 judge 평균 + 점수
│   └── calibration/                ← judge 캘리브레이션 (v2.7 산출물)
├── scripts/
│   ├── compare_agentlens_events.py  ← (v2.17) 레거시 events.jsonl ↔ AgentLens kws-cme.* 패리티 검증
│   ├── accumulate_cost.py           ← (v2.16) F2 cost-ledger 집계 (flock-guarded R-M-W)
│   ├── build_spec_manifest.py       ← (v2.15 C1) tiered spec injection
│   ├── validate_method_audit.py     ← Phase 2 method audit 게이트
│   ├── query_state.sh / query_run.sh ← (v2.14 F4) jq read-only 조회 헬퍼
│   ├── price_table.py / test_price_table.py
│   └── ...                          ← v2.17 cutover: append_learning_event.py / archive_run.sh / render_html_report.py 제거 — AgentLens 단독 싱크
└── templates/
    └── (현재 비어있음 — 향후 스캐폴드 예약)
```

**언어 정책**:
- `SKILL.md`, `AGENTS.md`, `references/*` — 영어 유지 (LLM이 직접 읽는 프롬프트, 한글화 시 토큰 30~50% 증가 + 영어 학습 패턴 약화)
- 그 외 사람이 읽는 문서 — 한국어

자세한 분리 원칙은 [`docs/design-decisions.md`](./docs/design-decisions.md) §문서 언어 정책 참조.

## Archive 레포 내 교차 컨텍스트

이 스킬은 Archive의 `skills/` 트리에 독립 디렉터리로 존재합니다. 디렉터리 밖의 관련 산출물:

- **현재 source of truth**: 이 디렉터리의 `SKILL.md`, `AGENTS.md`,
  `ARCHITECTURE.md`, `HISTORY.md`, `docs/`, `references/`, `evals/`
- **역사적 디자인/구현 계획**: 과거 `docs/superpowers/...` 경로에 있던
  문서는 git history나 실험 기록에서만 참조될 수 있습니다. 현재 체크아웃에
  해당 경로가 실제로 존재하는지 확인하기 전에는 live source로 취급하지
  마세요.
- **자매 스킬** (Codex executor 병렬 설계): `skills/kws-codex-plan-executor/`
- **Archive 스킬 인덱스**: `skills/README.md`

## 문서 신선도 유지

변경이 머지될 때 문서가 같이 갱신되지 않으면 드리프트가 발생합니다. 이를 방지하기 위해:

- **문서 갱신 프로토콜** ([`docs/doc-update-protocol.md`](./docs/doc-update-protocol.md)) — 변경 종류별 (스킬 동작 / 새 이벤트 / 새 픽스처 / 위험 등) "어떤 문서를 어떻게 건드릴지" 체크리스트.
- **신선도 eval** (`evals/check_doc_freshness.py`) — 가장 회귀되기 쉬운 드리프트를 결정론적으로 검사: SKILL.md/README 버전 일치, 문서 트리의 내부 markdown 링크 깨짐, 오래된 TODO/FIXME 마커. 다른 두 계약 eval과 같은 사전 점검 단계에서 실행.
- **스냅샷** ([`docs/snapshots/`](./docs/snapshots/)) — 메이저 버전마다 전체 상태 캡처. 현재: `v2.9.0.md`. 마이너 버전 번프마다 추가.

신선도 eval은 **기본적으로 비차단**입니다 (드리프트를 보고하지만 하네스를 실패시키진 않음). 경고를 자꾸 무시하게 되면 차단으로 승격하세요.
