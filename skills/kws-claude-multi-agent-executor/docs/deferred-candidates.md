# 연기된 후보 — 향후 작업 선반

검토되었고, 의도적으로 연기되었으며, 증거나 범위를 기다리며 선반에 남은 후보 변경들. 각 항목 구성:

- **제안된 변경** (추진했을 때 안착할 것)
- **기원** (아이디어가 어디서 왔나)
- **연기 이유** (현재 범위에 없는 구체적 사유)
- **재방문 기준** (재고려할 구체적 트리거)

이 파일은 "다음으로 그럴듯한 게 뭐냐?" 에 대한 답입니다. 새 실험이나 메이저 버전 번프 계획 시 읽으세요. 항목이 추진되거나 영구 폐기되면 갱신.

---

## omc 영감 후보 (T5 PASS 후 2026-05-14 연기)

이 여섯 항목은 2026-05-13 의 `https://github.com/yeachan-heo/oh-my-claudecode` (omc) — 33K-star Teams-first 멀티 에이전트 오케스트레이션 프로젝트 — 분석에서 나옴. v2.9.0 는 항목 C (Reviewer "What's Missing" walk — 측정된 KCMAE 실패 증거가 있는 유일한 것) 만 출하. 나머지 여섯은 이 선반에 남음.

| 항목 | 설명 | 연기 이유 | 재방문 시점 |
|------|------|-----------|-------------|
| **D — 거버넌스 플래그** | 자율 스킬 호출의 방어적 설정 플래그 (예: 최대 재귀 깊이, 실행당 최대 비용, 스킬 체이닝 허용 목록) | 이를 요구하는 측정된 KCMAE 사고 없음; 방어적 표면; SKILL.md 를 광범위하게 건드림 | "자가 스폰이 폭주" 또는 "비용 폭주" 이벤트가 학습 로그에 표면화; 또는 v2.8.1 런타임 데이터 1-2주 후 |
| **E — Heartbeat freshness** | Monitor 프로세스가 주기적 heartbeat 발산; 오케스트레이터가 heartbeat staleness 로 서브프로세스 hang 검출 | F001/F002 에 측정된 hang 케이스 없음 (`kill -0 $PID` 가 이미 대부분 검출) | `claude -p` 서브프로세스가 실제 실행에서 exit 없이 hang |
| **F — Conflict-mailbox 이벤트 타입** | 크로스 에이전트 머지 충돌용 새 학습 로그 이벤트 타입 (omc 는 병렬 브랜치 자동 머지에 사용) | v2.8 학습 로그가 아직 이벤트 풍부하지 않음; KCMAE 는 in-process Phase 1 (오케스트레이터 수준 병렬 브랜치 없음) | 실제 `parallel_dispatch_failure` 이벤트 표면화 또는 v2.10 이 병렬 브랜치 디스패치 도입 |
| **G — Sentinel READY gate** | 서브에이전트가 다음 스텝 디스패치 차단 해제 전 명시적 "ready" 센티넬 발산 (omc 의 tmux-pane 오케스트레이션 패턴) | KCMAE 의 3초 sleep + kill 체크가 eval 코퍼스에서 실패 안 함; 서브에이전트 디스패치는 in-process, race 없음 | 서브에이전트 디스패치 race / premature progression 관찰됨 |
| **A — Inbox/Outbox 메시징** | 크로스 에이전트 통신용 pane 별 JSONL 메시징 (omc 가 tmux 에서 N 개 CLI 프로세스 실행하기 때문에 사용) | KCMAE 는 in-process Agent 툴 디스패치 + Resume Chain `claude -p` 사용. 현재 ESCALATE 메커니즘이 측정된 어떤 케이스에도 불충분하지 않음 | KCMAE 토폴로지가 멀티 프로세스로 변경 (현재 계획 없음); 또는 크로스 오케스트레이터 메시징 필요 표면화 |
| **B — Auto-merge 오케스트레이터** | 병렬 브랜치용 자동 머지 로직 (omc M1-M6 가 멀티 pane 토폴로지에 사용) | KCMAE 는 in-process 머지; 오케스트레이터 수준 병렬 브랜치 없음. 토폴로지 불일치 | 멀티 오케스트레이터 병렬 작업으로 토폴로지 피벗 (현재 계획 없음) |

**재순위 트리거** (전체 셋): 학습 로그가 실제 실패를 캡처하며 v2.8.1 런타임 사용 1-2주. omc 와의 유추가 아닌 실제 이벤트 스트림 증거에 대해 각 항목 재평가.

**참조**: `docs/experiments/v2.9-reviewer-spec-coverage/decisions/D001-initial-design.md` §Out-of-scope.

---

## Step 7.5 의 훅 기반 강제

**제안된 변경**: 오케스트레이터의 첫 비자명 Bash 호출 전에 `init-run` 을 자동 실행하는 PreToolUse 훅. v2.8.1 의 prose + 마커 메커니즘을 구조적 강제로 대체.

**기원**: v2.8 F001 Smoke B 준수 갭 + risks-and-limitations "Adherence marker is spoofable".

**연기 이유**:
- 스코핑 이슈: SessionStart 훅은 비-오케스트레이터 실행을 포함한 모든 `claude -p` 에 발화.
- PreToolUse 훅은 너무 늦게 (오케스트레이터가 이미 시작된 후) 그리고 잘못된 컨텍스트에서 발화.
- 이 훅들은 `.claude/hooks/` 설정에 살고 스킬 내부 아님 — 추가하면 스킬과 환경 경계 흐려짐.

**재방문 시점**:
- v2.8.1 의 마커 기반 검출이 프로덕션 런타임에서 실제 준수 회귀를 놓침.
- 훅 프레임워크가 스킬 스코프 이벤트 타입(예: "스킬 X, Y, Z 에 대해서만 발화") 획득.

---

## Headless 모델 플래그

**제안된 변경**: SKILL.md 의 6개 `claude -p` 디스패치 사이트 전부에서 `--model claude-opus-4-7` (오케스트레이터) 와 `--model claude-sonnet-4-6` (서브에이전트) 명시 전달.

**기원**: v2.8 설계 감사가 문서화된 모델 할당이 런타임 동작과 일치 안 한다는 걸 발견 (모델이 CLI 기본값에서 상속됨).

**연기 이유**:
- 동작 변경, 관측성 변경 아님. v2.8 (관측성 추가) 와 묶으면 스코프 혼동.
- 별도 v2.8.x 미니 PR 이 올바른 모양 — 단일 목적, 낮은 위험.

**재방문 시점**: 사용자가 예상 못한 추론 깊이나 비용을 보고하는 다음 시점 (가능한 지표: 오케스트레이터가 Sonnet 으로 실행됐지만 사용자가 Opus 기대).

**참조**: `docs/experiments/v2.8-learning-log/decisions/D001-initial-design.md` §Out-of-scope.

---

## Verifier acceptance-criteria coverage walk

**제안된 변경**: v2.9 Spec Coverage Walk 패턴을 Verifier 로 확장 — 검증 전에 스펙 acceptance criteria + 적대적 기준 위반 입력 열거하는 `CRITERIA_COVERAGE_WALK:` 블록 발산.

**기원**: v2.9 D001 §Open question Q3.

**연기 이유**:
- Verifier 실패율이 이 입도로 측정 안 됨 (Verifier 용 F002 등가 증거 없음).
- v2.9 의 파일럿 강도 증거가 픽스처 특이적; walk 패턴을 자신의 데이터에 검증 전에 다른 역할로 일반화하면 과-튜닝 리스크 복합화.

**재방문 시점**: 측정된 Verifier 실패 (학습 로그의 `verification_failure` 이벤트) 가 프롬프트가 놓친 케이스 표면화.

---

## `check_skill_contract.py` 의 walk 패턴 검증자

**제안된 변경**: Reviewer 프롬프트의 walk 템플릿이 엄격한 행 포맷 `"<frag>" :: <file>:<line> | NOT FOUND | PARTIAL` 을 명시한다는 계약 체크 추가. 현재 v2.9.0 체크는 섹션 제목 존재만 검증.

**기원**: v2.9 D001 §Open question Q2.

**연기 이유**:
- 한계 이익에 비해 eval 표면 추가 — walk 는 구조 계약이 아니라 프롬프트 수준 discipline.
- walk 템플릿 진화에 따라 반복 필요; 계약 체크가 정당한 프롬프트 개선의 제약 요인이 될 리스크.

**재방문 시점**: walk 템플릿이 추가 반복 없이 2+ 마이너 버전 걸쳐 안정화.

---

## 픽스처 스펙 감사 (01-07)

**제안된 변경**: 스펙 vs 루브릭 모호성에 대해 픽스처 01-07 수동 감사 (v2.9 Phase 2 가 픽스처 08 에서 고친 것과 같은 종류).

**기원**: risks-and-limitations §Spec ambiguity vs rubric strictness.

**연기 이유**:
- 현재 어떤 작업도 차단 안 함.
- 이미 안정된 픽스처에서 false-positive 플래그 생성 가능.

**재방문 시점**: 픽스처 01-07 의 어떤 재실행이 혼란스러운 "rubric FAIL but Reviewer PASS" (또는 반대) 생성 — v2.9 T4.5 발견의 역.

---

## 학습 로그용 집계자 / 리포팅 CLI

**제안된 변경**: `~/.claude/learning/kws-claude-multi-agent-executor/runs/**/events.jsonl` 을 읽고 요약 발산하는 작은 CLI (상위 이벤트 타입, 반복 실패 시그니처, 시계열).

**기원**: v2.8 D001 §Out-of-scope.

**연기 이유**: 실제 이벤트 코퍼스가 먼저 필요. v2.8 런타임 데이터가 현재 sparse (그리고 v2.8.0 의 준수 갭이 더 sparse 하게 만듦).

**재방문 시점**: 준수 수정이 자리잡은 채로 1-2주 정례 사용 후 v2.8.1 사후.

---

## 컨텍스트 헬스 관측성 (v2.10 후보)

**제안된 변경**: 새 학습 로그 이벤트 타입 `context_health` 또는 기존 `completion_learning` 확장. 실행당 1회 (Phase 2 종료 시) 발산. 측정 지표 후보:
- `max_orchestrator_tokens` — 세션 jsonl 의 누적 토큰 카운트
- `compaction_events_observed` — `state.compaction_points` 실제 도달 횟수
- `resume_chain_handoffs` — state.json `chain_resume` 히스토리에서 카운트
- `subagent_dispatch_count` / `avg_subagent_tokens_in_out` — 서브에이전트 입출력 토큰 평균
- `state_json_writes` / `read_after_compaction` — 외부 메모리가 복구 보조 역할 실제로 하는지
- 드리프트 신호: `recurring_issue` 카운트, 반복 SPEC_FAULT, 같은 file:line 의 ISSUE_KEY 재출현

**기원**: 사용자 제안 2026-05-14 — "로그 기록할때 컨텍스트가 잘관리되고있는지도 파악". 스킬 전체 아키텍처(오케스트레이터-워커, 컴팩션 포인트, fresh 서브에이전트, state.json) 가 컨텍스트 위생을 위해 설계됐는데 정작 작동 여부를 측정 안 하고 있다는 관찰.

**연기 이유**:
- 측정 정의에 가설 있음 — "어떤 지표가 실제로 드리프트 예측할까?" 가 비자명. 추측으로 지표 선택하면 메트릭이 *수단* 이 되어 동작 왜곡 (Goodhart's law).
- 실험 스캐폴드로 다뤄야 함 (≥50줄 변경: SKILL.md 5곳 + 헬퍼 + eval). 현재 코퍼스 부족.
- v2.8.1 자체가 아직 1-2주 실사용 데이터 부족 — 이 데이터로 가설을 키울 수 있어야 함.

**재방문 시점**:
- v2.8.1 가 자리 잡고 1-2주 정례 사용 후, 학습 로그가 ≥10 실제 실행 캡처.
- 또는 `recurring_issue` / SPEC_FAULT 반복 패턴이 컨텍스트 압박 추정을 정당화하는 사고 표면화.
- 또는 omc 비교 후보 D(거버넌스 플래그) / E(heartbeat) 재방문 시 — 이 항목이 그들의 트리거 기준 데이터 공급.

**시작 시 주의**: 메트릭은 진단용 — threshold 기반 자동 분기(예: "토큰 X 초과면 자동 컴팩션") 도입 금지. 그러면 측정이 동작 왜곡.

---

## 학습 로그 → 실험 스캐폴드 자동 트리거

**제안된 변경**: 학습 로그에서 반복 패턴 감시하고 표면화된 이슈에 대해 실험 스캐폴드 자동 생성하는 메타 스킬 (D001 템플릿 + README + 계획 stub).

**기원**: v2.8 D001 §Out-of-scope.

**연기 이유**: 위 집계자를 전제조건으로 요구, 그건 코퍼스 요구, 그건 1-2주 프로덕션의 v2.8.1 요구. 전제조건 두 계층.

**재방문 시점**: 집계자 출하 후 사용자가 이미 자동 스캐폴드 됐으면 했던 수동 케이스 식별.

---

## 후보 추가 방법

지금 *하지 않기* 로 결정했지만 옵션을 열어두고 싶을 때:

1. 위에 섹션 추가: 제안된 변경, 기원 (커밋 / 토론 / 실험), 연기 이유, 재방문 기준.
2. 재방문 기준을 *구체적* 으로 — "1-2주 후", "N 이벤트 표면화 시", "X 보고 시" — "미래에" 아님.
3. 이전 결정을 대체하면 [`decision-log.md`](./decision-log.md) §Overturned 표에 추가.
4. 기준 충족 (작업 수행) 또는 기준 무관해짐 (won't-do 노트와 함께 종결) 시 항목 갱신 또는 제거.

목표: 좋은 아이디어를 절대 잃지 않기, 오래된 아이디어가 숨은 backlog 부담이 되지 않기.
