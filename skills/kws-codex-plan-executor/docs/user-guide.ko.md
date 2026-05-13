# KWS Codex Plan Executor 사용자 가이드

이 문서는 사람이 읽는 상세 설명서다. 에이전트가 매 실행마다 읽어야
하는 지침은 [../SKILL.md](../SKILL.md)와 [../references/](../references/)에
짧게 유지한다.

## 문서 분리 원칙

`kws-codex-plan-executor`는 실행 중 토큰 비용과 판단 오류를 줄여야 하므로
문서를 독자별로 나눈다.

| 독자 | 읽을 파일 | 목적 |
| --- | --- | --- |
| 실행 에이전트 | `SKILL.md` | 언제 사용할지, 어떤 인자를 받는지, 절대 넘지 말아야 할 경계 |
| 실행 에이전트 | `references/*.md` | 모드별 세부 계약, 상태 스키마, headless 실행, prompt export 체크 |
| 사람 사용자 | `docs/user-guide.ko.md` | 사용법, 구성, 설계 이유, 운영 방식 |
| 유지보수자 | `README.md`, `ARCHITECTURE.md`, `docs/*.md` | 변경 범위 판단, 검증, 이력, 위험 관리 |
| 검증 도구 | `scripts/`, `evals/` | 문서 계약을 기계적으로 확인 |

좋은 구조는 `SKILL.md`를 길게 만들지 않는 것이다. `SKILL.md`가 길어지면
에이전트는 매번 많은 문장을 읽고, 정작 중요한 정지 조건이나 검증 조건을
놓칠 가능성이 커진다. 상세한 배경, 예시, 선택 이유는 사람용 문서에 둔다.

## 이 스킬이 하는 일

이 스킬은 이미 작성된 구현 계획을 Codex에서 실행하거나, 같은 입력으로
새 세션용 프롬프트를 만들어 준다.

주요 입력은 다음 세 가지다.

- 구현 계획: `plan=<path>`
- 선택적 제품/설계 문서: `spec=<path>`, `docs=<path1,path2>`
- 실행 방식: `mode=interactive|headless|prompt|handoff`

기본값은 현재 Codex 세션에서 직접 실행하는 `interactive`다. `headless`,
`prompt`, `handoff`는 명시해야 한다.

## 빠른 사용법

현재 세션에서 계획을 실행하려면:

```text
[$kws-codex-plan-executor](/Users/kws/source/private/Archive/skills/kws-codex-plan-executor/SKILL.md) plan=docs/plans/example.md
```

제품 문서와 설계 문서를 함께 제공하려면:

```text
[$kws-codex-plan-executor](/Users/kws/source/private/Archive/skills/kws-codex-plan-executor/SKILL.md) plan=docs/plans/example.md spec=docs/spec.md docs=docs/design.md,docs/api.md
```

새 Codex 세션에 붙여 넣을 프롬프트만 만들려면:

```text
[$kws-codex-plan-executor](/Users/kws/source/private/Archive/skills/kws-codex-plan-executor/SKILL.md) plan=docs/plans/example.md mode=prompt
```

기존 실행을 이어갈 프롬프트를 만들려면:

```text
[$kws-codex-plan-executor](/Users/kws/source/private/Archive/skills/kws-codex-plan-executor/SKILL.md) resume=latest mode=handoff
```

감독 세션에서 별도 `codex exec` 실행을 띄우려면:

```text
[$kws-codex-plan-executor](/Users/kws/source/private/Archive/skills/kws-codex-plan-executor/SKILL.md) plan=docs/plans/example.md mode=headless
```

서브에이전트는 기본으로 꺼져 있다. 병렬 위임이 필요하면 사용자가 명시해야
한다.

```text
subagents=on
```

## 인자 설명

| 인자 | 필수 여부 | 설명 |
| --- | --- | --- |
| `plan=<path>` | 보통 필수 | 실행할 구현 계획. `resume` 전용 흐름에서는 생략 가능 |
| `spec=<path>` | 선택 | 제품 요구사항, 설계 명세, PRD 같은 핵심 배경 문서 |
| `docs=<path1,path2>` | 선택 | 추가 참고 문서 목록 |
| `workspace=<path>` | 선택 | 원본 작업 디렉터리. 실행 모드는 별도 전용 worktree를 만들거나 상태에 기록된 worktree를 재개 |
| `resume=latest|<state-path>|<run_id>` | 선택 | 기존 실행 상태를 이어받음 |
| `mode=interactive` | 기본 | 현재 Codex 세션에서 실행하되 구현은 전용 `codex/...` worktree에서 수행 |
| `mode=headless` | 명시 필요 | 감독 세션이 전용 `codex/...` worktree에서 `codex exec`를 띄워 실행 |
| `mode=prompt` | 명시 필요 | 실행하지 않고 새 세션용 프롬프트만 출력 |
| `mode=handoff` | 명시 필요 | 기존 상태를 기반으로 이어받기 프롬프트를 출력 |
| `subagents=on|off` | 선택 | 명시하지 않으면 `off` |
| `headless_sandbox=workspace-write|read-only` | 선택 | headless 실행의 샌드박스 수준. 기본은 `workspace-write` |

경로는 절대 경로나 저장소 기준 상대 경로를 사용할 수 있다. 모호한 경로를
추측해서 실행하는 것보다, 실패하더라도 명시적으로 멈추는 쪽을 선택한다.

## 계획 파일 형식

실행 모드는 계획에서 작업별 파일 블록을 요구한다. 파일 블록이 없으면
수정 범위를 안전하게 선언할 수 없으므로 에이전트는 편집 전에 멈춘다.

사용 가능한 파일 블록 제목:

- `Files`
- `Affected files`
- `Modified files`
- `Changed files`
- `수정 파일`
- `변경 파일`
- `대상 파일`
- `파일`

예시:

```markdown
### Task 0: 로그인 오류 메시지 정리

Files:
- Modify: src/auth/login.ts
- Modify: tests/auth/login.test.ts

Acceptance:
- npm test -- tests/auth/login.test.ts
```

계획 안의 코드 블록, HTML 주석, 들여쓰기 코드 영역은 실행 대상으로 보지
않는다. 예시나 주석이 실제 작업으로 잘못 파싱되는 것을 막기 위해서다.

## 실행 흐름

`interactive`와 `headless`는 같은 핵심 순서를 따른다.

1. 입력 경로와 모드를 확인한다.
2. 계획 파일을 파싱한다.
3. git dirty worktree를 확인하고 관련 변경과 무관한 변경을 나눈다.
4. 중복 없는 전용 `codex/...` git worktree를 만든다.
5. `run_id`를 만들고 `.codex-orchestrator/runs/<run_id>/`를 준비한다.
6. 실행 전 `context.json`을 만들어 계획, 명세, 참고 문서의 해시를 기록한다.
7. `context_health`를 갱신해 이어받을 수 있는 상태인지 기록한다.
8. 편집 전에 5줄짜리 `TASK EXECUTION CONTRACT`를 선언하고 상태 파일에 기록한다.
9. 작업을 수행한다.
10. 위험도에 맞는 검증 명령 또는 정직한 대체 검증을 실행한다.
11. 완료 시 `context_health`, `completion_audit`, `lifecycle_outcome=finished`를 기록한다.
12. 상태 파일을 검증하고 최종 결과를 요약한다.

핵심은 "수정하기 전에 범위를 고정하고, 완료라고 말하기 전에 증거를
남기는 것"이다.

## TASK EXECUTION CONTRACT

작업 편집 전에 반드시 다음 다섯 필드를 선언하고 상태에 저장한다.

```text
TASK EXECUTION CONTRACT
scope: ...
files_to_inspect: ...
allowed_edits: ...
forbidden_edits: ...
acceptance_command_or_honest_substitute: ...
```

이 계약은 에이전트가 계획보다 넓은 파일을 건드리거나, 검증 없이 완료를
선언하는 것을 막는 최소 장치다. 또한 세션이 끊기거나 다른 에이전트가
이어받을 때 "무엇을 해도 되고 무엇을 하면 안 되는지"를 복원할 수 있다.

## 상태와 산출물

실행 상태의 기준 파일은 다음이다.

```text
.codex-orchestrator/runs/<run_id>/state.json
```

루트의 `.codex-orchestrator/state.json`은 호환성용 최신 상태 복사본 또는
포인터일 뿐이다. 여러 실행이 같은 저장소에서 동시에 존재할 수 있으므로
루트 상태 파일만 진실로 삼지 않는다.

주요 산출물:

| 경로 | 설명 |
| --- | --- |
| `.codex-orchestrator/runs/<run_id>/state.json` | 실행 재개와 완료 판정의 기준 상태 |
| `.codex-orchestrator/runs/<run_id>/context.json` | 계획, 명세, 참고 문서의 경로와 해시 |
| `.codex-orchestrator/runs/<run_id>/headless.jsonl` | headless 실행 로그 |
| `.codex-orchestrator/runs/<run_id>/headless-final.md` | headless 최종 메시지 |
| `~/.codex/learning/kws-codex-plan-executor/` | 사용자 로컬 학습 이벤트 로그 |

`context.json`은 원문 전체를 저장하지 않는다. 어떤 입력을 기준으로 실행이
시작됐는지 확인할 수 있도록 경로와 해시를 기록한다.

## Context Health

`context_health`는 "대화 컨텍스트가 없어도 다음 에이전트가 이어받을 수
있는가"를 상태 파일에 기록하는 작은 품질 체크다. 토큰 잔량을 재는 장치가
아니라, 재개 가능성을 판정하는 장치다.

```json
{
  "context_health": {
    "status": "green",
    "last_checked_at": "2026-05-14T00:00:00Z",
    "context_snapshot_present": true,
    "context_basis_hash_recorded": true,
    "active_task_contract_present": true,
    "next_action": "Run final verification and write completion_audit.",
    "open_questions": [],
    "known_assumptions": [],
    "handoff_ready": true
  }
}
```

상태 의미:

- `green`: 상태 파일과 산출물만 보고 이어받을 수 있음
- `yellow`: 진행은 가능하지만 가정이나 open question이 남아 있음
- `red`: 안전한 진행을 위해 blocker, 사용자 판단, handoff가 필요함

갱신 시점:

- `context.json` 생성 직후
- 각 task나 phase 종료 후
- blocker/error 발생 시
- handoff/resume 전
- final 직전

성공 완료를 선언하려면 `context_health.handoff_ready=true`이고
`context_health.status`가 `red`가 아니어야 한다.

## 모드별 사용 기준

| 모드 | 언제 쓰나 | 저장소 수정 | 학습 로그 |
| --- | --- | --- | --- |
| `interactive` | 일반적인 현재 세션 실행 | 전용 `codex/...` worktree에서 함 | 함 |
| `headless` | 재현 가능한 별도 실행, eval, 장시간 작업 | 전용 `codex/...` worktree에서 보통 함 | 함 |
| `prompt` | 다른 새 세션에 붙여 넣을 실행 프롬프트 생성 | 안 함 | 안 함 |
| `handoff` | 기존 실행을 다른 세션으로 넘김 | 안 함 | 안 함 |

`prompt`와 `handoff`는 직접 실행하지 않지만, 생성된 프롬프트가 나중의
실행에서 같은 상태, 검증, 완료 감사 계약을 지키도록 해야 한다.

## 왜 이런 선택을 했나

### 왜 `SKILL.md`를 짧게 유지하나

스킬 설명은 에이전트가 실제 작업 전에 읽는 실행 지침이다. 여기에 긴 배경
설명과 사례를 넣으면 매번 토큰을 쓰고, 더 중요한 정지 조건과 검증 조건이
묻힌다. 그래서 `SKILL.md`는 트리거, 인자, 하드 경계, 핵심 불변식만 담고,
상세 설명은 `docs/`에 둔다.

### 왜 파일 블록을 강제하나

계획에 파일 블록이 없으면 에이전트가 수정 범위를 추측해야 한다. 추측은
사용자의 기존 변경을 덮거나, 계획 밖 리팩터링을 끌어들일 위험이 있다.
파일 블록은 실행 전 "이번 작업의 표면적"을 고정하는 역할을 한다.

### 왜 dirty worktree를 관련/무관으로 나누나

실제 저장소는 항상 깨끗하지 않을 수 있다. 무관한 사용자 변경 때문에 모든
작업을 멈추면 비효율적이다. 반대로 관련 파일에 이미 변경이 있는데 계속
수정하면 사용자 작업을 덮을 수 있다. 그래서 선언된 작업 파일 기준으로
관련 변경은 멈추고, 무관한 변경은 보존한 채 진행한다.

### 왜 전용 worktree를 강제하나

`interactive`는 현재 Codex 세션에서 진행된다는 뜻이지, 현재 checkout을
직접 수정해도 된다는 뜻이 아니다. 실행 모드는 편집이나
`TASK EXECUTION CONTRACT` 전에 중복 없는 전용 `codex/...` git worktree를
만들어야 한다. `main`이나 호출 세션의 원래 checkout에서 구현하면 사용자
작업, 다른 실행, protected branch를 섞을 위험이 커진다.

worktree 이름은 `git worktree list --porcelain`과 로컬 브랜치를 확인해서
충돌을 피한다. 같은 branch name이 이미 있으면 `run_id`나 고유 suffix를
붙이고, 최종 branch/worktree를 상태 파일에 기록한다. 재개 흐름만 예외로,
명시된 상태 파일에 기록된 worktree가 실제로 존재하고 같은 브랜치를 가리킬
때만 그 worktree를 다시 쓴다.

### 왜 실행마다 `run_id`를 만들나

하나의 저장소에서 여러 실행이 생길 수 있다. 단일 상태 파일만 쓰면 어떤
실행을 이어받아야 하는지 모호해진다. `run_id`별 디렉터리는 상태, 로그,
컨텍스트를 실행 단위로 분리해 재개와 감사가 가능하게 한다.

### 왜 `context.json`이 필요한가

에이전트는 대화 맥락을 잃거나 다른 세션으로 넘어갈 수 있다. `context.json`
은 실행 시작 시점의 계획, 명세, 참고 문서 경로와 해시를 기록해 "무엇을
근거로 실행했는지"를 복원하게 한다.

### 왜 `context_health`가 필요한가

`context.json`은 입력 근거를 보존하지만, 현재 실행 상태가 실제로
이어받기 좋은지는 말해 주지 않는다. 예를 들어 다음 액션이 불분명하거나,
열린 질문이 있거나, 현재 task contract가 아직 기록되지 않았을 수 있다.

`context_health`는 그런 상태를 `green`, `yellow`, `red`로 압축해 남긴다.
컨텍스트 압박이나 세션 재개 상황에서 다음 에이전트가 바로 판단할 수 있고,
완료 직전에도 "정말 이어받을 수 있는 상태인가"를 검증할 수 있다.

### 왜 `completion_audit`가 필요한가

테스트가 통과해도 프롬프트의 모든 요구사항이 충족됐다는 뜻은 아니다.
`completion_audit`는 요구사항과 변경 산출물, 검증 증거를 연결한다. 완료
판정이 채팅 메시지에만 남지 않고 상태 파일에 저장되므로 후속 에이전트가
검토할 수 있다.

### 왜 학습 로그를 저장소 밖에 두나

학습 이벤트는 프로젝트 산출물이 아니라 실행기를 개선하기 위한 사용자 로컬
기록이다. 저장소 안에 남기면 프로젝트 이력에 섞이고, 민감한 과정 정보가
커밋될 위험이 있다. 그래서 `~/.codex/learning/kws-codex-plan-executor/`
아래에 두고, helper가 축약과 redaction을 강제한다.

### 왜 서브에이전트를 기본으로 쓰지 않나

서브에이전트는 독립적인 작업을 병렬화할 때 유용하지만, 파일 충돌과 상태
조율 비용이 생긴다. 이 스킬은 기본적으로 단일 Codex 세션에서 명확한
소유권으로 실행한다. 사용자가 병렬 작업을 원하거나 `subagents=on`을
명시할 때만 사용한다.

### 왜 headless 프롬프트가 스킬을 다시 부트스트랩하나

`codex exec`로 시작한 headless 프로세스는 부모 세션의 스킬 로드 상태를
그대로 이어받는다고 가정할 수 없다. 그래서 구현 작업 프롬프트는 필요한
스킬, 특히 `using-superpowers`와 `test-driven-development`를 명시적으로
부트스트랩해야 한다. 다만 TDD는 headless 전용 규칙이 아니다. interactive와
headless 실행 모두 feature/bugfix/refactor/behavior change 구현 전
`test-driven-development`를 적용하고 RED/GREEN 증거를 남겨야 한다.

### 왜 prompt export가 runtime 계약을 따라야 하나

`mode=prompt`는 실행하지 않는다. 하지만 그 출력물이 다음 세션의 실행
지침이 된다. prompt export가 상태 기록, 검증, 완료 감사 계약을 빠뜨리면
나중의 실행이 조용히 약해진다. 그래서 runtime과 prompt template을 함께
검증한다.

## 유지보수 방법

변경 전에 항상 다음을 먼저 읽는다.

1. [../SKILL.md](../SKILL.md)
2. [../references/change-protocol.md](../references/change-protocol.md)
3. [doc-update-protocol.md](doc-update-protocol.md)

변경 분류:

| 변경 종류 | 같이 확인할 것 |
| --- | --- |
| 실행 동작 변경 | `SKILL.md`, `references/`, `ARCHITECTURE.md`, `HISTORY.md`, eval |
| prompt/handoff 변경 | template, prompt checklist, prompt eval |
| 상태 스키마 변경 | `references/state-schema.md`, `scripts/validate_state.py`, state eval |
| parser 변경 | parser script, parser fixtures, parser eval |
| 문서만 변경 | README/docs, link check, quick validation, 보통 버전 bump 없음 |

문서만 바뀐 경우에도 `docs/verification-log.md`에 어떤 검증을 했고 어떤
무거운 검증을 생략했는지 짧게 남긴다.

## 자주 막히는 상황

| 상황 | 원인 | 대응 |
| --- | --- | --- |
| 계획을 실행하지 않고 멈춤 | 파일 블록이 없음 | 작업마다 `Files` 또는 `수정 파일` 블록 추가 |
| `resume=latest`가 멈춤 | active run이 여러 개임 | 명시적인 `run_id` 또는 state path 제공 |
| dirty worktree 때문에 멈춤 | 작업 대상 파일에 기존 변경이 있음 | 사용자 변경을 먼저 정리하거나 실행 범위를 바꿈 |
| headless가 편집하지 않음 | `headless_sandbox=read-only` | preflight 용도가 아니라면 `workspace-write` 사용 |
| 완료라고 말하지 않음 | 검증 실패 또는 completion audit 부족 | 실패 원인을 해결하거나 정직한 대체 검증 기록 |
| prompt-only 요청인데 설명이 같이 나옴 | 출력 계약 위반 | `mode=prompt`에서 prompt-only를 명시하고 체크리스트 실행 |

## 좋은 계획 작성 습관

- 작업을 작게 나눈다.
- 각 작업에 명확한 파일 블록을 둔다.
- acceptance command를 가능하면 구체적으로 적는다.
- 위험한 작업에는 엣지 케이스와 실패 조건을 적는다.
- plan/spec/docs 경로를 명시한다.
- 병렬 작업이 필요할 때만 `subagents=on`을 쓴다.

## 피해야 할 사용법

- 파일 블록 없이 "알아서 수정"이라고 지시하기.
- dirty worktree의 관련 변경을 무시하고 계속 진행시키기.
- `--dangerously-bypass-approvals-and-sandbox`를 일반 저장소에서 쓰기.
- `prompt` 모드 출력에 runtime 계약을 빼기.
- `completion_audit` 없이 테스트 통과만으로 완료 선언하기.
- `context_health`가 `red`인데 성공 완료로 보고하기.
- 사람용 설명을 계속 `SKILL.md`에 추가하기.

## 한 줄 요약

사람에게는 충분한 배경과 이유를 `docs/`에 제공하고, 에이전트에게는
`SKILL.md`와 `references/`로 짧고 강한 실행 계약만 제공한다. 이 분리가
이 스킬의 핵심 운영 방식이다.
