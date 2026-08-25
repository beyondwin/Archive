# 설계 결정 — kws-claude-multi-agent-executor

이 스킬이 **왜 이렇게 만들어졌나**. 무엇을 검토했고, 무엇을 선택했고, 무엇을 의도적으로 버렸나. 결정의 깊은 인덱스는 [`./decision-log.md`](./decision-log.md), 현재 상태는 [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

이 문서는 **새로 이 스킬을 이해하려는 사람**(혹은 6개월 뒤의 나 자신)을 위한 입문서입니다. 결정마다 "왜 이걸 골랐고, 무엇이 대안이었고, 그 대안의 단점이 무엇이었는지" 를 같이 적습니다.

---

## 1. 큰 그림 — 왜 이런 스킬이 필요했나

### 문제

긴 구현 계획을 사람이 직접 실행하면 다음이 반복됩니다:

1. 한 태스크 구현
2. 리뷰 받기
3. 피드백 반영
4. 테스트
5. 다음 태스크로 — 이때 이전 컨텍스트가 머릿속에 남아 다음 결정에 편향
6. 10개쯤 가면 사용자가 지치거나 처음 의도를 놓치기 시작

LLM에게 그냥 "이 계획 다 실행해줘" 하면:

- 컨텍스트 윈도우 한계 (50개 태스크 = 한 세션 못 버팀)
- 한 태스크의 실수가 다음 태스크 컨텍스트로 누적
- 리뷰가 자체 출력에 대한 자기-편향
- 검증을 건너뛰고 "다 됐어요" 라고 하는 경향

### 채택한 해법

**오케스트레이터-워커 패턴**: 한 명의 Opus 오케스트레이터가 책 한 권을 들고 있고, 매 태스크마다 페이지를 찢어서 깨끗한 Sonnet 워커에게 건네줍니다. 워커는 그 페이지만 보고 작업한 뒤 결과만 돌려줍니다. 오케스트레이터는 결과를 받아 정리하고 다음 워커를 부릅니다.

이 분리가 위 5가지 문제를 한 번에 풉니다:
- **컨텍스트 한계**: 오케스트레이터는 요약만 누적 (태스크당 ~200 토큰). 50+ 태스크 가능.
- **누적 오염**: 워커는 매번 새로 — 사전 정보 0.
- **자기-편향**: Implementer와 Reviewer가 다른 세션 → 진짜 두 번째 의견.
- **검증 누락**: Verifier 가 독립 헤드리스 서브프로세스로 실제 테스트를 실행. LLM이 "통과했다고 했다" 가 아니라 실제 exit code 확인.
- **드리프트**: 매 단계 결정이 state.json에 기록됨. 재개 가능, 감사 가능, 디버그 가능.

### 대안과 그 단점

| 대안 | 단점 |
|------|------|
| 단일 에이전트 루프 | 위에 적은 5개 문제 그대로 |
| Swarm (창발적 조정, 다수 동등 에이전트) | 디버깅 불가, 결정론 없음, 재개 불가, 토큰 비용 폭발 |
| 인간이 매번 승인 | 자율 실행이라는 목표 자체 부정. 10개 태스크 = 사용자 10번 깨움 |
| 전부 Opus | 비용. Sonnet으로 충분히 잘 되는 일에 Opus는 낭비 (캘리브레이션으로 측정됨) |
| 전부 Sonnet | 오케스트레이션 판단(언제 escalate, FAIL에 어떻게 대응)에서 약함 (이건 측정 안 했지만 직관적으로 명확) |

---

## 2. 핵심 구조 결정

### 2.1. 왜 git worktree인가 (브랜치만 아니라)

대안: 그냥 새 브랜치 만들고 메인 체크아웃에서 작업.

문제:
- 사용자가 작업 중인 파일을 덮어씀
- 테스트가 사용자의 unsaved 변경을 봄
- 훅(`.claude/settings.json`)이 사용자 전역에 영향
- 동시 실행 불가 (브랜치는 하나의 작업 트리만 가짐)

**worktree 선택**: 각 실행이 `<repo>/../worktrees/<branch>` 라는 별도 디렉터리에 자기 체크아웃을 가짐. 사용자 메인 작업과 완전 분리. 훅은 worktree 한정. 동시 실행 가능 (각각 다른 worktree).

비용: 디스크 (대부분 lightweight checkout으로 작음).

### 2.2. 왜 state.json (외부 메모리)인가

대안: 오케스트레이터의 컨텍스트(채팅 히스토리)에 모든 결정 보관.

문제:
- 컨텍스트가 태스크마다 비대해짐 — 50개 태스크면 컨텍스트 한계 초과
- 세션이 죽으면 모든 상태 손실 (재개 불가)
- 디버깅 시 무엇이 어떻게 결정됐는지 grep 안 됨

**state.json 선택**: JSON 한 파일에 모든 상태. 매 결정 후 쓰고, 다음 결정 전에 다시 읽음. 사후 분석은 `jq` 한 줄.

대안 2: SQLite. **거부**. 필드 셋(태스크 ~20개, 메타 ~10개)이 너무 작아서 관계형 DB가 과공학. JSON에 쓸 수 있는 걸 SQLite 스키마로 만들면 마이그레이션 비용만 더해짐.

비용: 동시 작성자 0명 보장 필요 — "오케스트레이터만 쓴다" 라는 단일 작성자 규약. 위반하면 race condition (실제로 v2.7 초기에 서브에이전트가 직접 쓰려다 깨졌음).

### 2.3. 왜 fresh 서브에이전트인가 (대화 컨텍스트 공유 X)

대안: 서브에이전트들이 한 채팅 세션을 공유하며 서로 결과를 봄.

문제:
- 한 태스크의 실수가 다음 태스크에 누적
- Implementer가 자기 자신을 Review할 위험 (지속 세션이면 같은 모델 인스턴스)
- 컨텍스트 윈도우 압박

**fresh 선택**: 매 디스패치마다 새 Sonnet 세션. 프롬프트가 자체 완결적. 워커는 자기 일만 보고 결과만 반환.

비용: 매번 프롬프트 다시 빌드 — 약간의 토큰 중복. 하지만 (a) Opus 오케스트레이터가 작은 컨텍스트 유지로 보상, (b) prompt caching 으로 부분 완화.

### 2.4. 왜 Agent 툴 + headless `claude -p` 혼합인가

| 사용처 | 디스패치 | 이유 |
|--------|----------|------|
| Implementer | Agent 툴 (fresh) | 결과(STATUS, COMMIT, FILES_CHANGED 등)를 오케스트레이터가 직접 읽고 파싱 |
| Combined Reviewer | Agent 툴 (fresh) | 점수와 ISSUES 를 즉시 분기에 사용 |
| Verifier | headless `claude -p` | 출력이 큼 (테스트 로그 수천 줄). 오케스트레이터는 JSON 한 파일의 verdict 만 읽으면 됨 |
| Plan Reviewer | headless `claude -p` | 일회성, 결과는 JSON 한 파일 |
| Docs Updater | headless `claude -p` | 출력이 큼 (markdown 수십 줄), JSON에 요약 |

**원칙**: 오케스트레이터가 즉시 구조화된 답을 받아야 분기할 수 있으면 Agent. 결과가 크고 verdict만 필요하면 headless.

### 2.5. 왜 위험 등급 (LOW/MID/HIGH) 인가

대안: 모든 태스크를 똑같이 검증.

문제: 한 줄 typo 수정도 풀 테스트 스위트를 돌리면 시간 낭비. 단순한 변경에 큰 검증을 강제하면 사람이 스킬을 안 쓰게 됨.

**위험 등급 선택**: 폭발 반경 기준. LOW(한 모듈, 격리)는 배치 검증, MID/HIGH는 즉시 검증.

**핵심 명확화 (실수하기 쉬운 곳)**: 위험은 **검증 타이밍/노력**을 결정합니다. **품질 기준을 결정하지 않습니다**. TDD와 Reviewer는 모든 등급에서 동일하게 적용. "LOW니까 대충 해도 됨" 이 아님 — "LOW니까 한 번에 묶어서 검증하자" 임.

대안 (거부): LOW = 리뷰 생략. 거부 이유 — 리뷰는 정확성 잣대가 아니라 코드 품질 잣대고, 코드 품질은 모든 변경에서 일정해야 함.

### 2.6. 왜 WARN 등급 (PASS/FAIL 만 아니라)

이건 v2.5에서 추가된 거고, 측정 가능한 효과가 있었습니다.

문제 (v2.5 이전): 점수가 0.84/0.85 같이 경계선이면 FAIL → 재시도. 재시도하면 비슷한 점수 또 나옴 → 또 FAIL. 3번 후 halt. 사용자가 보면 "이 정도면 됐는데 왜 halt했나?" 함.

**WARN 도입**: PASS(0.85/0.75)와 FAIL 사이에 WARN(0.70/0.60). WARN은 진행하되 `task_summaries[].warnings` 에 기록.

**효과**:
- 경계선 작업이 재시도 예산을 안 태움 → 진짜 깨진 작업에 예산 보존
- 사용자가 최종 리포트에서 WARN 목록을 보고 한꺼번에 검토 가능
- 3개 연속 WARN 이면 컴팩션 포인트에서 사용자에게 신호 (silent regression 방지)

대안: PASS/FAIL 만 유지하고 임계값을 낮춤. 거부 — 임계값을 낮추면 진짜 나쁜 코드도 PASS가 됨. WARN 은 "괜찮긴 한데 이 부분 봐줘" 라는 별도 신호로서의 가치가 있음.

### 2.7. 왜 SPEC_FAULT 분기 (P15)

문제 (이전 버전): Reviewer 가 FAIL 했을 때, Implementer 잘못인지 Spec 잘못인지 모름. 일단 Implementer 재시도 → 같은 문제 또 발견 → 재시도 → halt.

**SPEC_FAULT 도입**:
- `implementer_omitted` — 스펙은 명확, Implementer가 빠뜨림. 표준 재시도.
- `spec_contradicts` — 스펙 자체가 모순. **스펙을 편집**해서 해결.
- `unclear` — 스펙이 모호. 편집(또는 명확화 노트) 후 재시도.

**효과**: 스펙 잘못으로 인한 FAIL이 Implementer 재시도 예산을 안 태움. 별도 카운터(`spec_clarifications`, 캡 3) 사용.

**중요 제약**: 스펙 편집은 **오케스트레이터만** 합니다. 서브에이전트에게 위임하지 않음. 이유 — 스펙은 모든 후속 태스크의 입력이므로, 단일 작성자가 최소 편집을 가하는 게 가장 안전.

### 2.8. 왜 헤드리스 자가 스폰 (Phase -1)

대안: 항상 같은 세션에서 실행.

문제:
- 50+ 태스크 계획은 사용자 세션의 컨텍스트를 다 먹음
- 사용자가 다른 작업 할 수 없음 — 스킬이 끝날 때까지 기다림
- 컨텍스트 압박이 오케스트레이터 판단을 흐릴 가능성

**자가 스폰 도입** (v2.8): 호출 즉시 백그라운드 `claude -p` 프로세스를 spawn하고 부모 세션은 종료. 진행은 Monitor 도구로 알림.

**Phase -1 의 미묘한 점**:
- Phase 0 Step 1, 2, 2.5 (clean check, worktree 생성, 훅 설치) 는 **부모 세션에서** 실행. 빠르고(~2분), 헤드리스 시작 전에 무결성 확인 필요.
- 헤드리스가 시작 후 Phase 0 나머지(분석, 베이스라인, 의존성 그래프, state 채우기)를 진행.

**`<<HEADLESS_KWS_ORCHESTRATOR>>` 센티넬**: 헤드리스 인스턴스를 식별. 이게 프롬프트에 있으면 Phase -1 건너뜀. 부모 세션과 헤드리스 세션이 같은 `SKILL.md` 를 읽지만 다른 분기를 탐.

**비용**: 디버깅이 약간 더 번거로움 (jsonl 파일 tail 필요). 그래서 `mode=interactive` 오버라이드 보존.

### 2.9. 왜 Resume Chain

50+ 태스크 큰 계획은 단일 헤드리스 서브프로세스 한 번의 컨텍스트로 안 끝남.

**Resume Chain**: 헤드리스가 컴팩션 포인트 ≥ 2 AND 완료 태스크 ≥ 8 을 만나면, 새 `claude -p` 자식을 spawn하고 자기는 종료. `state.json` 으로 인계.

**왜 이 두 임계값**: 둘 다 state.json에서 검사 가능 (결정론적). "토큰 카운트가 X 이상이면" 같은 휴리스틱은 introspect 불가능해서 거부.

**Monitor 핸드오프 처리**: PID 파일이 atomic 하게 교체됨. Monitor 가 다음 polling에 새 PID 발견 → `CHAIN_HANDOFF` 알림. `PROCESS_DIED` 와 구분.

### 2.10. 왜 P2 병렬 실행 (sub-worktree)

대안: 항상 순차.

문제: 같은 웨이브(deps 동일한 태스크 집합) 안에서 파일이 겹치지 않는 태스크들은 순차 실행할 필요가 없음 — wall time 낭비.

**P2 도입** (v2.6): Phase 0 가 웨이브를 계산하고, 웨이브 안에서 파일 겹침 없는 태스크를 같은 병렬 그룹으로 묶음. 각 태스크가 자기 sub-worktree에서 Implementer 실행 → 모두 DONE 후 cherry-pick → Reviewer/Verifier 는 순차.

**왜 Implementer만 병렬, Reviewer/Verifier 는 순차**:
- Implementer 단계는 독립적 (다른 파일 만지니까)
- Reviewer 는 메인 worktree 의 최종 diff를 봐야 하고, 다른 태스크의 변경이 그 diff에 같이 있어야 함 → 순차
- Verifier 는 전체 테스트 스위트 돌림 → 순차

**실패 격리**: 한 sub-worktree가 ESCALATE 해도 다른 병렬 태스크는 영향 없음. 충돌(out-of-scope edit, 같은 파일 중복)이 감지되면 그 그룹만 롤백, 메인 worktree로 순차 재디스패치.

**`parallel=off` 탈출구**: shallow clone, 낮은 디스크, fsmonitor race 같은 환경에서 sub-worktree 생성이 불안정하면 끄고 모든 그룹을 싱글톤으로.

---

## 3. 채점 / 측정 결정

### 3.1. 왜 0.0–1.0 점수 (binary 아니라)

PASS/FAIL은 정보를 1비트로 압축. 0.0–1.0(1자리)는 11 단계.

**효과**:
- 등급(PASS/WARN/FAIL) 임계값을 점수에서 파생 가능 → 분기 명료
- 추세 추적 가능 (`quality_trend` 롤링 10개) → 천천히 나빠지는 걸 감지
- 캘리브레이션 가능 — Reviewer가 0.90 줬을 때 정말 0.90 짜리인지 측정

**임계값은 사용자 설정 X**: PASS 0.85/0.75, WARN 0.70/0.60. 이유 — `evals/calibration/` 에서 정의된 P6 eval 스위트로 보정한 값. 사용자가 바꾸면 캘리브레이션 깨짐.

### 3.2. 왜 rubric.py (결정론적) + LLM judge 둘 다

이건 v2.7 실험에서 측정으로 결정된 거.

문제: LLM judge 단독은 rep별 분산이 ±0.16 (주관적 축). 작은 개선(예상 효과 +0.1)을 detect 못함.

**해법**:
- 기계적 축 (correctness, spec_compliance) → `rubric.py` 셸 체크. 결정론적, 분산 0.
- 주관적 축 (code_quality, cost_efficiency) → LLM judge. rubric_results 를 입력으로 받아서 정확성을 중복 추정하지 않음.

**결과**: 변별력이 ±0.05 로 좁아짐. 작은 개선이 검출 가능해짐.

### 3.3. 왜 Spec Coverage Walk (v2.9)

문제: Reviewer 가 "스펙에 적힌 거 다 했나?" 를 채점하는데, 실제로 스펙의 모든 항목을 nichtt 모두 확인하지 않는 경우가 있음 (LLM의 자연스러운 누락).

**Spec Coverage Walk 도입**: Reviewer 프롬프트가 점수 매기기 **전에** 두 sub-step 강제:
- A) 스펙에 명시된 요구사항을 unique bullet 으로 열거
- B) 메타 규칙(에러 처리, 입력 검증, 동시성, etc.)에서 적대적 생성

이 walk 의 출력이 채점 컨텍스트에 들어가므로, "확인했다고 주장하는 항목" 과 "실제로 확인된 항목" 이 같아짐.

**측정 결과**: 미세 누락 검출률 개선 (T5 n=4 PASS, `docs/snapshots/v2.9.0.md` 참조).

---

## 4. 안전·격리 결정

### 4.1. 왜 settings.json 훅 (코드 검사 아니라)

대안: 오케스트레이터가 매 단계 후 grep으로 디버그 아티팩트(`console.log` 등) 검사.

문제 (v2.4): 오케스트레이터의 prose discipline 으로 grep을 돌리도록 명령했지만, 컨텍스트 압박이나 드리프트로 silently 건너뛰는 일이 발생. 디버그 아티팩트가 커밋으로 빠져나감.

**훅 도입** (v2.5, P1): `PostToolUse(Edit|Write)` 훅이 runtime-enforced. 헬퍼 스크립트 `scan-debug-artifacts.sh` 가 exit 2 반환하면 Implementer가 자동 재시도.

**원칙**: discipline 은 runtime 에 위임. prose 에 두면 silent bypass 가능. v2.5 변경 후 오케스트레이터의 manual grep 은 제거 — 중복이고 silent bypass risk 의 근원이었음.

### 4.2. 왜 PreToolUse 차단 패턴

훅이 차단하는 것:
- `rm -rf /` 또는 `rm -rf ~` 같은 루트 파괴
- `git push --force` to main/master/trunk
- `DROP TABLE/DATABASE/SCHEMA`

**의도적으로 차단하지 않는 것**:
- `git reset --hard` — 오케스트레이터가 verifier-fail 복구에 사용. 차단하면 정상 흐름 깨짐.
- `git commit --amend` — Implementer가 가끔 사용. 위험하지만 가시화 가능.

**원칙**: 복구 불가능한 파괴만 차단. 위험하지만 복구 가능한 것은 가시화.

### 4.3. 왜 SubagentStop 훅 (출력 구조 검증)

문제: Implementer 가 `STATUS:`, `COMMIT:`, `FILES_CHANGED:`, `FILES_TEST_CHANGED:` 같은 필드를 누락한 채 끝낼 수 있음. 오케스트레이터가 파싱 실패하면 그냥 "이상한 답" 으로 처리하고 실수.

**훅 도입** (v2.7): `check-implementer-output.sh` 가 필드 존재 검증. 누락 → exit 2 → Implementer 자동 재시도.

**오케스트레이터 책임 감소**: prose 로 "Implementer 출력에 X 필드 확인하라" 라고 적을 필요 없음 — 훅이 강제.

---

## 5. 문서 언어 정책

### 결정

- **에이전트가 직접 읽는 프롬프트** (`SKILL.md`, `AGENTS.md`, `references/*.md`): **영어**, 한글화 금지
- **사람이 읽는 문서** (`README.md`, `ARCHITECTURE.md`, `docs/*.md`, 단 `onboarding-for-ai-agents.md` 제외): **한국어**, 자세히
- **하이브리드** (`HISTORY.md`, `DESIGN-v2.5.md`, snapshots): 영어 원본 + 한글 TL;DR 헤더

### 왜

**에이전트 프롬프트를 한글로 안 쓰는 이유**:
1. **토큰 비용**: 한글이 영어보다 토큰당 정보 밀도가 낮음. SKILL.md(현재 80KB) 같은 큰 프롬프트는 매 호출마다 한국어 버전이 30~50% 더 비쌈.
2. **학습 패턴**: LLM은 영어로 된 명령형 지시(`MUST`, `SHALL`, `NEVER`) 패턴에 가장 강하게 학습됨. 한국어 명령("절대 ~하지 말 것")은 같은 의미지만 약한 신호.
3. **레퍼런스 정렬**: Anthropic의 가이드, 캐시 문서, Sub-agent 패턴 자료가 모두 영어. 영어로 통일하면 cross-reference 가능.

**사람 문서를 한국어로 쓰는 이유**:
1. **속도**: 사용자가 빠르게 이해해야 디버깅·확장이 가능. 영어 80KB 읽는 것보다 한국어가 빠름 (사용자가 한국어 사용자이므로).
2. **뉘앙스**: 설계 결정의 "왜" 와 트레이드오프는 모국어로 더 잘 전달됨.

**파일명은 영어**: `사용법.md` 가 아니라 `usage.md`. 이유 — git/URL/grep/search 가 영어 ASCII가 편함. 내용만 한글.

---

## 6. 의도적으로 거부된 것들

| 거부한 것 | 거부 이유 |
|-----------|-----------|
| 사용자가 임계값(PASS/WARN) 튜닝 | 캘리브레이션 깨짐. 임계값은 P6 eval 으로 측정된 값. |
| Reviewer 가 직접 Implementer 코드를 fix | 검증/수정 분리 원칙. Reviewer 가 고치면 자기 출력을 자기가 다시 평가하게 됨. |
| 서브에이전트가 학습 로그 직접 작성 | 단일 작성자 계약. 환경변수 전파, 경쟁 조건, 살균 일관성 모두 깨짐. |
| 토큰 카운트 기반 Resume Chain | introspect 불가능. 결정론적 두 임계값(compaction_points ≥ 2 AND completed ≥ 8) 으로 대체. |
| 자동 worktree 삭제 | 사용자가 머지 전에 검토해야 함. 자동 삭제는 작업 손실 위험. |
| SQLite로 state 저장 | 필드 셋이 작아서 과공학. JSON으로 충분. |
| 모든 위험 등급 자동 추론 | 사용자 오버라이드(`risk=`) 보존. 단, HIGH로 보이는 태스크의 silent downgrade 는 경고 로깅. |
| Phase Docs Updater 가 실패하면 halt | docs는 best-effort. Phase 2 Final Docs Updater 가 복구. |

---

## 7. 더 깊은 결정 인덱스

이 문서는 입문서입니다. 개별 결정의 완전한 ADR(대안 5개, 측정 데이터, 채택 후 회고 등)은 [`./decision-log.md`](./decision-log.md) 와 거기서 가리키는 D### 파일들을 보세요.

실험으로 결정된 항목(P3 Plan Reviewer, P4 quality scoring 등)의 원본 데이터는 [`./experiments/`](./experiments/) 디렉터리.

거부됐지만 다시 검토할 수 있는 후보는 [`./deferred-candidates.md`](./deferred-candidates.md).
