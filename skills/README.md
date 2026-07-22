# skills/

이 디렉터리는 Archive 레포에서 관리되는 **개인용 executor 스킬**의 단일 출처(source of truth)입니다. Claude Code와 Codex 모두 여기로 심볼릭 링크해서 동일한 정의를 공유합니다.

## 포함된 스킬

| 스킬 | 용도 |
|------|------|
| [`kws-claude-plan-executor`](./kws-claude-plan-executor/) | 승인된 Superpowers 구현 계획을 헤드리스 자식 Claude 세션(`claude -p`)으로 자율 실행하는 얇은 런처. fail-closed 완료 검증 + 세션 위임 재개. v3 오케스트레이터를 대체할 예정이며, 현재 `kws-claude-multi-agent-executor`는 그대로 유지(아카이브는 후속 작업). |
| [`kws-claude-multi-agent-executor`](./kws-claude-multi-agent-executor/) | (v3, 대체 예정) 구현 계획 + 디자인 스펙을 자율 실행. Opus가 오케스트레이션, Sonnet 서브에이전트가 구현/리뷰/검증/문서화. `kws-claude-plan-executor`로 대체 중; agent 검증 툴링 마이그레이션 후 아카이브 예정. |
| [`kws-codex-plan-executor`](./kws-codex-plan-executor/) | 2.1 strict-thin 계약: 승인된 Superpowers 구현 계획을 한 worktree에서 고정 순서로 실행·재개하는 소형 Codex 실행기. |
| [`waygent`](./waygent/) | 활성 제품 런타임 스킬. 자연어 실행, 상태, 이벤트, 검사, 설명, 재개, 적용 요청을 Waygent CLI로 변환합니다. KWS executor 스킬은 별도 비제품 executor 계약으로 유지됩니다. |

각 스킬 디렉터리의 `SKILL.md`가 정식 진입점입니다. 자세한 사용법은 먼저
실제로 존재하는 `README.md`를 확인하고, 해당 스킬이 제공하는 추가 파일을
따르세요.

## Waygent Boundary

Waygent 요청은 `skills/waygent/`에서 CLI로 라우팅하고, 런타임 상태와
스케줄링은 Waygent가 소유합니다. `kws-*` 스킬은 로컬 executor 계약이며
Waygent 제품 런타임 의존성이 아닙니다.

## Codex Executor Subtree Contract

`skills/kws-codex-plan-executor/`는 승인된 Superpowers 스펙과 구현 계획을
입력 스냅샷으로 고정하고, 계획 순서를 유지한 채 하나의 격리 worktree를
재사용하며, 첫 미완료 계획에서 재개하는 strict-thin 순차 실행기입니다.
Superpowers가 구현, 리뷰, 수정, 검증, 커밋과 품질 정책을 소유합니다.
CPE는 Waygent 제품 런타임이 아니며 task mapping, 별도 오케스트레이션,
품질 판단을 추가하지 않습니다.

이 하위 트리를 변경하기 전에는
[`AGENTS.md`](./kws-codex-plan-executor/AGENTS.md),
[`SKILL.md`](./kws-codex-plan-executor/SKILL.md),
[`README.md`](./kws-codex-plan-executor/README.md)를 읽고 최종적으로 해당
디렉터리의 `./evals/run.sh`를 실행합니다.

## 심볼릭 링크 셋업

두 도구 모두 사용자 홈의 `skills/` 디렉터리를 스캔합니다. 아래 예제에서
`ARCHIVE_REPO`를 현재 Archive checkout의 루트로 설정한 뒤 각 폴더를 그
위치로 심링크하면 어느 한 쪽에서 수정하더라도 곧바로 양쪽에 반영됩니다.

### Claude Code (`~/.claude/skills/`)

```bash
ln -sfn "$ARCHIVE_REPO/skills/kws-claude-plan-executor" \
        ~/.claude/skills/kws-claude-plan-executor
ln -sfn "$ARCHIVE_REPO/skills/kws-claude-multi-agent-executor" \
        ~/.claude/skills/kws-claude-multi-agent-executor
ln -sfn "$ARCHIVE_REPO/skills/kws-codex-plan-executor" \
        ~/.claude/skills/kws-codex-plan-executor
ln -sfn "$ARCHIVE_REPO/skills/waygent" \
        ~/.claude/skills/waygent
```

### Codex (`~/.codex/skills/`)

```bash
ln -sfn "$ARCHIVE_REPO/skills/kws-claude-plan-executor" \
        ~/.codex/skills/kws-claude-plan-executor
ln -sfn "$ARCHIVE_REPO/skills/kws-claude-multi-agent-executor" \
        ~/.codex/skills/kws-claude-multi-agent-executor
ln -sfn "$ARCHIVE_REPO/skills/kws-codex-plan-executor" \
        ~/.codex/skills/kws-codex-plan-executor
ln -sfn "$ARCHIVE_REPO/skills/waygent" \
        ~/.codex/skills/waygent
```

> `ln -sfn` 은 기존 심링크를 안전하게 갱신합니다(`-f` 강제, `-n` 디렉터리 타깃 보호). 실제 디렉터리를 덮어쓰지 않으려면 대상 경로가 심링크인지 먼저 확인하세요.

### 확인

```bash
ls -l ~/.claude/skills/ | grep -E 'kws-|waygent'
ls -l ~/.codex/skills/  | grep -E 'kws-|waygent'
```

두 곳 모두 `ARCHIVE_REPO` 아래의 `skills/...` 경로를 가리키면 정상입니다.

## 수정 워크플로우

1. 이 디렉터리 안에서 직접 편집 (`skills/<skill>/SKILL.md` 등).
2. `git status` 로 Archive 레포에 변경 사항이 잡히는지 확인.
3. Claude/Codex 둘 다 즉시 새 내용을 사용 — 추가 설치 불필요.
4. 의미 있는 런타임 변경이면 각 스킬의 `SKILL.md` 프론트매터 버전과
   실제로 존재하는 README, 계약 테스트, 관련 문서를 함께 갱신합니다.
   문서만 정리한 경우에는 버전 bump가 필요하지 않습니다.

## 참고

- 다른 일반 스킬(reflective-writing-coach, archive-docs-organizer 등)은 별도의 `kws-skills` 플러그인에서 관리되며 이 디렉터리에는 포함되지 않습니다.
- executor 스킬을 Archive 레포로 옮긴 배경은 커밋 `d7039d5`, `17ff639`, `da8782c` 참고.
