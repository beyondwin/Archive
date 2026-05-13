# 리스크와 한계

이 스킬의 알려진 취약점, 부분 검증, 미해결 이슈를 솔직하게 통합 등록한 리스트. 각 항목은 현재 상태, 구체적 표현, 추적/처리 위치 포인터를 가집니다.

이 파일은 "무엇이 깨질 수 있나?" 에 대한 답입니다 — 비자명한 변경 전에 읽고, 리스크 프로필을 바꾸는 것을 출하할 때 갱신하세요.

---

## 상태 범례

- **★★★ Active risk** — 프로덕션 관련; 사용자에게 지금 깨질 수 있음.
- **★★ Tracked risk** — 알려진, 그러나 제한됨; 구체적 완화책 존재.
- **★ Acknowledged limitation** — 인정된 제약, 활성 문제 아님.
- **CLOSED** — 리스크였음; 특정 변경으로 해소됨.

---

## 스킬 실행 리스크

### ★★ SKILL.md 지시에 대한 오케스트레이터 준수

**표현**: headless `claude -p --dangerously-skip-permissions` 아래에서, 컨텍스트 부담이 높을 때(멀티 태스크 계획, 긴 스펙) 오케스트레이터가 prose-only 지시를 건너뛸 수 있음. v2.8 F001 Smoke B 가 경험적으로 문서화: 지시에도 불구하고 47개 Bash 호출 중 0개가 Step 7.5 init-run 을 실행.

**현재 완화** (v2.8.1):
- Step 7.5 헤딩을 MANDATORY 로 승격.
- `LEARNING_LOG_INIT:` 마커가 출력되고 실행 후 검출됨.
- `evals/run.sh` 가 픽스처별로 `learning_log_adherence: yes|no (markers=N)` 보고.
- 18번째 계약 체크가 SKILL.md 에서 MANDATORY 표현 고정.

**남은 우려**: 모든 완화책이 prose + 관측성. 결의를 가진 건너뛰기는 여전히 가능. 훅 기반 강제(첫 Bash 호출 전 init-run 자동 실행하는 PreToolUse 훅)가 구조적 수정이지만 범위 증가.

**추적**: [`deferred-candidates.md`](./deferred-candidates.md) §Hook-based enforcement.
**참조**: HISTORY.md v2.8.1 항목; `docs/experiments/v2.8-learning-log/findings/F001-smoke.md`.

### ★★ Headless 모델 갭

**표현**: SKILL.md 는 "Orchestrator=Opus, Sub-agents=Sonnet" 을 문서화하지만 6개 `claude -p` 디스패치 사이트 중 어느 것도 `--model` 을 전달하지 않음. 실제 상속되는 모델은 호출 시점 사용자 Claude Code CLI 기본값.

**왜 중요한가**: 사용자가 비용 이유로 기본을 Sonnet 으로 설정했다면, 문서화된 계약에도 불구하고 오케스트레이터가 조용히 Sonnet 위에서 실행. 위험 등급 주도 TDD 엄격도는 영향 없음(프롬프트 수준)이지만, 어려운 태스크에서 추론 깊이가 예상보다 낮을 수 있음.

**완화**: 아직 없음. v2.8 D001 에 out-of-scope 결정으로 문서화. 후보: Resume Chain + 서브에이전트 디스패치 사이트의 각 `claude -p` 호출에 `--model claude-opus-4-7` 명시 전달.

**추적**: [`deferred-candidates.md`](./deferred-candidates.md) §Headless model flag.
**참조**: `docs/experiments/v2.8-learning-log/decisions/D001-initial-design.md` §Out-of-scope.

### ★ 다양한 디스패치 모드에서 `CLAUDE_SESSION_ID` env 전파

**표현**: 학습 로그 헬퍼는 run_id 의 `session_short` 에 `$CLAUDE_SESSION_ID` 사용. 설정 안 되면 `nosession` 으로 fallback. v2.8 F001 Smoke A 는 `session_id="eval"` (nosession 아님) 을 보여서 env 가 가끔 전파되긴 하지만 값 포맷이 다양함을 의미.

**영향**: 현재로선 미관. 최악의 경우: 같은 초에 여러 실행이 시작될 때 run_id 유일성이 덜함(run_id 의 pid 로 완화).

**완화**: 필요 없음; run_id 유일성은 pid 로 보존됨.

**참조**: F001-smoke.md §Residual risks §4.

---

## 측정 / 검증 리스크

### ★★★ 파일럿 강도 증거, 통계적 증명 아님

**표현**: v2.9.0 출하 결정은 픽스처 08 에서 n=4 reps 기반. 이진 결과로, 95% Clopper-Pearson 하한이 ~40% (실제 거부율을 ±60% 보다 더 좁게 못 잡음).

**옹호 가능한 것**: F002 의 25%-catch null 아래 4/4 PASS 는 확률 ~0.4%. "개입이 아무것도 안 한다" 의 강한 거부.

**옹호 불가능한 것**: "Reviewer 가 `30m20m` 을 다시는 놓치지 않는다" 또는 +75pp 효과를 다른 픽스처로 외삽. 파일럿 강도 = "개입이 올바르게 조준됐고 아마 작동; 풀 신뢰는 실사용에서의 장기 관찰 필요".

**완화**: F002-T5-n4-results.md §Power note 에 문서화. n 이 ~20 미만일 때마다 향후 출하 결정은 비슷한 power note 기록해야 함.

**참조**: `docs/experiments/v2.9-reviewer-spec-coverage/findings/F002-T5-n4-results.md` §Power note.

### ★★ 단일 픽스처 최적화 리스크

**표현**: v2.9 의 Spec Coverage Walk 는 픽스처 08 에 대해서만 설계됨(코퍼스에서 측정된 실패가 있는 유일한 픽스처). walk 의 적대적 클래스 분류 체계(repeated-segment / ordering-casing / format-excluded) 가 다른 도메인(동시성, 보안, API 설계)에 일반화되는지는 경험적으로 미검증.

**완화**: 현재 범위에 없음. 두 개의 수용 가능한 경로:
1. 다음 정례 베이스라인 캡처 (픽스처 01-07 중 어느 거든) 때 `SPEC_COVERAGE_WALK:` 출력 품질 검사.
2. *새로운* 실패가 프로덕션 사용(학습 로그 통해)에서 표면화되면, walk 가 새 도메인을 다루는지 재평가.

### ★★ 결합 개입 귀인 (v2.9 + v2.8.1 + 스펙 명확화)

**표현**: T5 가 세 변경을 동시에 쌓음: v2.9 프롬프트(Spec Coverage Walk), v2.8.1 강제, 픽스처 08 스펙 명확화. 100% 거부율은 조인트 효과; 개별 기여는 측정 안 됨.

**F002-T5 §Attribution 에서 아는 것**:
- 스펙 명확화 (Phase 2) 가 가장 큰 단일 기여자일 가능성 — "스펙이 반복 단위를 허용한다" 는 옹호 가능한 읽기 제거.
- v2.9 walk 가 rep 간 고려를 결정론적으로 만듦.
- v2.8.1 강제는 관측성 전제조건(학습 로그 없음 = 미래 증거 없음).

**완화**: 문서화됐지만 측정 안 됨. Ablation 실험(스펙만, walk만, 강제만)이 이를 정리할 수 있지만 T5 가 출하 기준을 충족했기에 실행 안 됨. 더 많은 런타임 데이터로 미래 사후 분석이 기여를 분리 가능.

### ★ 짧은 / 테스트측 스펙에서 sub-step B 출력 드리프트

**표현**: T4.5 dry-run 에서 Task 1 Reviewer (구현 아닌 테스트 파일 리뷰) 가 sub-step B 를 *test parametrize 가 다루는 케이스 열거* 로 사용 — *독립적 적대적 케이스 생성* 이 아님. 픽스처 08 에선 문제 안 됨 (test parametrize 가 포괄적); 부분 테스트 스위트에선 문제될 수 있음.

**완화**: 차단 아님; 모니터링 플래그. 미래 픽스처가 sparse test parametrize 를 가지면 sub-step B 가 false-pass 결과 줄 수 있음.

**참조**: F001-T4.5-dry-run.md §Residual risks.

---

## 브랜치 / 레포 위생 리스크

### ★ 장기 공유 브랜치 `codex/executor-learning-log`

**표현**: v2.8, v2.8.1, v2.9 설계 + 출하 커밋이 모두 이 브랜치(사용자의 병렬 Codex executor 작업과 공유) 에 거주. Main 은 아직 이를 받지 못함. v2.9 문서의 v2.8 경로 cross-reference 는 이 브랜치에서만 해결됨.

**완화**: 머지 준비됐을 때, Claude executor 커밋은 경로 격리됨; 사용자의 Codex 커밋은 별도로 안착해야 함. 둘 다 합쳐서 머지하려면 주의 필요.

**권장 순서**:
1. v2.9 + v2.8.1 + v2.8 → main 하나의 머지로 (Claude executor 만).
2. Codex executor 작업 → main 별도 머지.
3. v2.10 (시작 시) 갱신된 main 에서 분기.

### ★ Sub-experiment 작업이 공유 브랜치에서 발생

**표현**: v2.8 + v2.9 가 `codex/executor-learning-log` 공유. 사용자가 같은 브랜치에서 작업하면 향후 실험이 더 공격적으로 충돌 가능.

**권장**: v2.10+ 에서 사용자가 공유 브랜치의 다른 주제로 동시 작업 중이면 main 에서 Claude 전용 피처 브랜치 분기.

---

## Eval 시스템 리스크

### ★★ Eval 비용 집중

**표현**: 픽스처 실행당 = $5-15 + 15-30분 wall. 풀 8-픽스처 스윕 = $40-120 + 2-3시간. 이게 eval 빈도 캡 — "매 커밋마다 실행" 은 불가능.

**완화**: Preflight 체크(33 결정론적) 가 무료로 실행되고 `claude -p` 호출 전에 계약 회귀 잡음. 비싼 eval 은 메이저 버전 출하 시점에만.

**권장**: 베이스라인 캡처를 의도된 이벤트로 다루기, CI 스텝 아님. 해당 실험 findings 에 실행 문서화.

### ★ 단일 rep 베이스라인 덮어쓰기

**표현**: `evals/baselines/v<X>.json` 이 가장 최근 `bash evals/run.sh` 호출로 덮어써짐. 체인 안의 n=4 reps 는 마지막만 영구 베이스라인으로 남김.

**완화**: `~/.claude/learning/...` 의 rep 별 run 디렉터리가 전체 체인 보유. Cross-rep 데이터는 `baselines/` 가 아니라 실험의 `findings/F00N-*.md` 파일에 거주.

**권장**: 베이스라인은 버전 스냅샷, rep 집계가 아님. 현 상태 수용 가능.

### ★ 픽스처의 스펙 모호성 vs 루브릭 엄격성

**표현**: v2.9 T4.5 가 픽스처 08 의 스펙 발췌가 `30m20m` 에 대해 모호함을 발견 (루브릭은 ValueError 요구; 스펙은 반복 단위 명시적 금지 안 함). Phase 2 에서 스펙 명확화로 해소.

**미해결 질문**: 다른 픽스처(01-07) 가 비슷한 스펙 vs 루브릭 불일치에 대해 감사되지 않음. 마주치면 혼란스러운 T5 스타일 결과의 가능한 원천.

**완화**: 픽스처 01-07 수동 감사가 후보 작업. [`deferred-candidates.md`](./deferred-candidates.md) §Fixture spec audit 에 추적.

---

## 관측성 리스크

### ★★ 준수 마커는 위조 가능

**표현**: `LEARNING_LOG_INIT:` 마커가 run.jsonl 의 정규식으로 검출. 결의를 가진 건너뛰기는 실제로 `init-run` 호출 없이 그 문자열을 *출력* 할 수 있음.

**현재 완화**: 파일시스템 상태 교차 확인 — `~/.claude/learning/...` 에 실제로 새 run 디렉터리가 생성됐나? T5 감사에서 이미 수행 (4/4 reps 에 새 run 디렉터리).

**경화 후보**: 훅 기반 강제 (PreToolUse). deferred-candidates 에 추적.

### ★ `MAE_LEARNING_RUN_ID` env 가 전파 안 되면 Resume Chain 에서 학습 로그 발화 안 함

**표현**: Resume Chain 의 `nohup claude -p ...` 가 체인된 오케스트레이터가 같은 실행에 계속 쓰도록 `env MAE_LEARNING_RUN_ID="$..." nohup ...` 로 시작되어야 함.

**현재 완화**: SKILL.md Phase 0 Resume Chain step 4 가 이를 명시적으로 문서화. F001 Smoke A 에서 shell 수준 테스트 (실제 Resume Chain 아님 — smoke 가 컴팩션 트리거 안 함).

**참조**: F001-smoke.md §Residual risks §2.

---

## 종결 / 해소 (참조용 보존)

### CLOSED — 멀티 태스크 계획에서 init-run silent 실패 (였던 ★★★)

**상태**: v2.8 F001 Smoke B 가 47개 Bash 호출 중 0개가 Step 7.5 실행했음을 보임.
**해소**: v2.8.1 강제 (MANDATORY 표현 + 마커 + eval 체크).
**검증**: T5 n=4 reps, 4 모두 ≥7 마커 발산 + 새 run 디렉터리 생성.

### CLOSED — `30m20m` Reviewer silent miss (였던 ★★★)

**상태**: v2.7 F002 가 ~75% Reviewer miss rate 측정. T4.5 단일 rep 이 walk 가 케이스 노출했지만 Reviewer 가 스펙이 허용한다고 추론.
**해소**: v2.9.0 walk + Phase 2 스펙 명확화.
**검증**: T5 n=4 reps, 100% 거부율 (8/8 Reviewer 호출이 `30m20m` 명시적 처리).

### CLOSED — 서브에이전트 env 전파 모호성 (였던 ★★)

**상태**: 원 v2.8 설계는 모든 서브에이전트가 상속된 `MAE_LEARNING_RUN_ID` 로 헬퍼 호출 가능하다고 가정. Advisor 가 Agent 툴 디스패치는 env 전파 보장 안 한다고 잡음.
**해소**: v2.8 D001 §Q4 단일 작성자 계약 — 서브에이전트는 후보 JSON 파일 작성; 오케스트레이터가 유일한 호출자.

---

## 이 파일을 갱신하는 법

리스크 프로필에 영향을 주는 변경을 출하할 때:

1. 리스크를 **종결** 하면 → "Closed / resolved" 로 이동, `verified by` 링크와 함께.
2. 리스크를 **도입** 하면 → 상태 ★~★★★, 표현, 완화, 추적 포인터와 함께 새 항목 추가.
3. 기존 리스크를 **완화** 하지만 완전 종결 안 하면 → 완화 섹션 갱신 + 적절하게 ★★★ → ★★ 또는 ★★ → ★ 다운그레이드.

이 파일의 정확성은 유지 없이 부패. 포기보다 stale 한 진실 선호.
