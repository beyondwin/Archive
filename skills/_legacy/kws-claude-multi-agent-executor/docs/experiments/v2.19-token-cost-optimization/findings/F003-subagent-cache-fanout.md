# F003 — 서브에이전트 dispatch의 캐시 친화성 진단

**일시**: 2026-05-27
**대상**: `references/implementer-prompt.md` v2.18 (적용 모델), `references/reviewer-prompt.md` v2.18

## 가설

같은 wave 내에서 같은 역할(Implementer)의 서브에이전트를 N개 병렬 spawn할 때, **system prompt + tool 정의가 byte-identical**이면 첫 spawn이 warm시킨 cache entry를 두 번째 spawn부터 cache_read 가격으로 hit할 수 있다.

현 프롬프트 템플릿이 이 조건을 만족하는지 검사한다.

## Implementer prompt 진단

### 시스템 영역으로 분류되는 콘텐츠 (대략)

`references/implementer-prompt.md` 의 ```` 블록 안에서 — Agent 툴 dispatch 시 어디까지 system prompt로 가는지는 Claude Code의 dispatch 로직에 따르지만, 일반적으로 "역할 선언 + Required Skills" 가 안정 prefix.

```
You are an Implementer sub-agent running on {implementer_model}. Implement exactly one task. Do not do anything outside the task's scope.

{decisions_register}
<!-- Substituted at dispatch time by SKILL.md Phase 1 Step 1: renders ... -->

## Required Skills

1. **First action:** invoke `Skill("superpowers:using-superpowers")` ...
2. **If this task involves feature, bugfix, refactor, ...
3. **If you hit any unexpected error, ...
4. **Before reporting `STATUS: DONE`:** ...

{IF this is a re-dispatch after Combined Reviewer FAIL OR Verifier FAIL:}
5. ...

## Task Size (P5 — effort scaling)

Size: `{task_size}`
{effort_guidance}
```

### Cache-깨는 요소 식별

| 변수 / 블록 | 변동성 | 같은 wave 내 byte-identical 보장? |
|---|---|---|
| `{implementer_model}` | run 내 고정 (`sonnet` 또는 `opus`) | ✅ 한 run 내 모든 Implementer dispatch에서 동일 — fan-out 안전 |
| `{decisions_register}` | 태스크가 진행되며 자람 | ❌ task N+1 dispatch 시 task N의 decision이 추가되어 prefix drift |
| Required Skills 본문 | 정적 | ✅ 모든 dispatch에서 byte-identical |
| Conditional block (re-dispatch 5번 항목) | 재시도 여부에 따라 존재/부재 | ⚠️ 같은 task 내 retry 1차 ↔ 2차 사이에는 OK. 다른 task 사이엔 영향 없음 |
| `{task_size}` | 태스크별 다름 | ❌ — 다만 시스템 prompt 영역에 들어가지 않으면 영향 없음 |
| `{effort_guidance}` | task_size 종속 | ❌ — 위와 동일 |

### 핵심 문제: `{decisions_register}` 위치

현재 템플릿에서 `{decisions_register}` 는 첫 줄의 역할 선언 **바로 다음**, Required Skills **앞**에 위치한다. 이 위치가 system prompt 영역에 들어가면 매 dispatch마다 prefix가 자라 — Required Skills 블록 전체와 그 뒤가 cache miss.

이는 v2.15 C2 (Decision consistency rubric) 의 부산물로 Reviewer가 decisions_register를 참조해야 하니 inject되는 것인데, **위치가 prefix를 깨뜨리는 자리**라는 게 문제.

### 권장 변경

```
[SYSTEM PROMPT — byte-identical across all Implementer dispatches in a run]
You are an Implementer sub-agent. Implement exactly one task. Do not do anything outside the task's scope.

## Required Skills
1. First action: invoke Skill("superpowers:using-superpowers") ...
2. If this task involves feature/bugfix/refactor: invoke Skill("superpowers:test-driven-development") ...
3. If you hit unexpected error: invoke Skill("superpowers:systematic-debugging") ...
4. Before reporting STATUS: DONE: invoke Skill("superpowers:verification-before-completion") ...

## Output Format (required — do not deviate)
STATUS: DONE | ESCALATE
SUMMARY: ...
ISSUES: ...
FILES_CHANGED: ...
...
METHOD_AUDIT: ...

[CACHE BREAKPOINT 1 — 여기까지 모든 dispatch에서 동일]

────────────────────────────────────
[USER MESSAGE — 변동, dispatch별로 다름]

## Run config
model: sonnet
task_size: MEDIUM

## Project decisions so far
{decisions_register}

## Re-dispatch context (only if applicable)
{If re-dispatch: "At the start of this re-dispatch: invoke Skill('superpowers:receiving-code-review') ..."}

## Your Task
{task text}

## Spec Requirement
{spec excerpt}

## Files to Touch
{files}

## Context from Previous Tasks (pre-resolved by orchestrator)
deps_for_this_task: [3, 5]
task_3.for_next_tasks: ...
shared_files: ...

## Fix Required (only if re-dispatch)
{issues}
```

이렇게 하면:
- 시스템 prompt = Required Skills + Output Format (둘 다 모든 dispatch에 정적) → 한 wave 내 fan-out에서 두 번째부터 cache_read 가격
- 모든 변동 요소는 user message 측으로 이동
- `model: sonnet` 처럼 변수도 user message 첫 줄로 빼면 시스템 prompt가 모델 종속성에서도 자유로워짐

## Reviewer prompt 진단

`references/reviewer-prompt.md` 도 유사한 패턴.

### 시스템 영역 안정성

| 요소 | 변동성 | 비고 |
|---|---|---|
| 역할 선언 / Required Skills | 정적 | ✅ |
| Review Checklist (인라인) | 정적 | ✅ — v2.9 SPEC_COVERAGE_WALK 본문 포함 |
| Scoring 앵커 (SPEC_SCORE / QUALITY_SCORE) | 정적 | ✅ |
| Output Format | 정적 | ✅ |

### Cache-깨는 요소

| 요소 | 위치 | 문제 |
|---|---|---|
| `{exact spec requirement text}` | 시스템 prompt 상단(현재) | 태스크마다 다름 → fan-out 깨짐 |
| `{git diff inline}` | 시스템 prompt 중단(현재) | 태스크마다 완전히 다름 → 결정적으로 prefix 깨뜨림 |
| `{previous_issues}` | conditional | 재시도 시에만 존재 |
| `{decisions_register}` | "## Project Decisions Register" 섹션 | 태스크 진행에 따라 자람 |

Reviewer는 본질적으로 매 dispatch에 diff와 spec 발췌가 들어가야 하므로 — **시스템 prompt를 Required Skills + Output Format 까지로 좁히고**, spec / diff / previous_issues / decisions_register 는 전부 user message로.

이렇게 정리하면:

- 시스템 prompt 안정 영역: ~8–10k tokens (Required Skills + Review Checklist 인라인 + Scoring + Output Format)
- User message 변동 영역: 매번 다름 (spec + diff + register)
- 두 번째 Reviewer spawn부터 시스템 prompt ~8k tokens 가 cache_read 가격 (Sonnet 기준 $0.024 → input 풀가격 $0.024 vs $0.0024). 50태스크 plan이면 ~$1.1 → ~$0.11 절감 추정.

## Verifier prompt

`references/verifier-prompt.md` 는 headless `claude -p` 호출이므로 다른 cache 거동. headless의 SessionStart 훅 영향(F002 §사용자 가설 (-p drift))을 받음. v2.19에서는 우선순위 낮음.

## 같은 wave 내 fan-out 시점

`SKILL.md` Phase 1의 P2 (병렬 sub-flow) 가 한 wave 안에서 file-disjoint 태스크들을 동시 spawn하는 패턴. 이 spawn 들이 같은 wall-clock 윈도우(예: 30초 안)에 dispatch되면 첫 spawn이 cache_write, 나머지는 cache_read.

만약 dispatch 사이에 오케스트레이터가 다른 작업(Verifier 대기, state.json 갱신, AgentLens emit 등)으로 지연이 생기면 5분 초과 가능 → 1h extended cache 적용 시 안전.

## 측정 계획

T6 ablation 시점에 다음 비교:

```
시나리오                                   | Implementer dispatch 평균 input tokens
v2.18 (현 템플릿)                          | ?
+ {decisions_register} 를 user message로  | ? (절감)
+ system prompt 모든 변수 제거             | ? (추가 절감)
+ 1h extended cache (Tier 2.1)             | ? (긴 wave에서 추가 절감)
```

같은 픽스처(예: `evals/fixtures/03-three-file-refactor.yaml` — 병렬 fan-out 트리거되는 케이스)로 측정.

## 다음 액션

- T1.2 PoC에 본 권장사항 반영: implementer/reviewer prompt 재구조화 + system/user 영역 명시
- 측정에서 `decisions_register` inject 위치 변경의 단독 효과 확인
- Verifier 캐시 거동은 별도 finding으로 분리 (v2.20 후속)
