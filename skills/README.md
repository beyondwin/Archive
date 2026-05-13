# skills/

이 디렉터리는 Archive 레포에서 관리되는 **개인용 executor 스킬**의 단일 출처(source of truth)입니다. Claude Code와 Codex 모두 여기로 심볼릭 링크해서 동일한 정의를 공유합니다.

## 포함된 스킬

| 스킬 | 용도 |
|------|------|
| [`kws-claude-multi-agent-executor`](./kws-claude-multi-agent-executor/) | 구현 계획 + 디자인 스펙을 자율 실행. Opus가 오케스트레이션, Sonnet 서브에이전트가 구현/리뷰/검증/문서화. |
| [`kws-codex-plan-executor`](./kws-codex-plan-executor/) | Codex에서 구현 계획을 실행하거나 fresh-session/handoff 프롬프트 내보내기. |

각 스킬 디렉터리의 `SKILL.md` 가 정식 진입점이며, 자세한 사용법은 해당 폴더의 `README.md` / `docs/` / `references/` 를 참고하세요.

## 심볼릭 링크 셋업

두 도구 모두 사용자 홈의 `skills/` 디렉터리를 스캔합니다. 각 executor 폴더를 그 위치로 심링크해 두면 어느 한 쪽에서 수정하더라도 곧바로 양쪽에 반영됩니다.

### Claude Code (`~/.claude/skills/`)

```bash
ln -sfn /Users/kws/source/private/Archive/skills/kws-claude-multi-agent-executor \
        ~/.claude/skills/kws-claude-multi-agent-executor
ln -sfn /Users/kws/source/private/Archive/skills/kws-codex-plan-executor \
        ~/.claude/skills/kws-codex-plan-executor
```

### Codex (`~/.codex/skills/`)

```bash
ln -sfn /Users/kws/source/private/Archive/skills/kws-claude-multi-agent-executor \
        ~/.codex/skills/kws-claude-multi-agent-executor
ln -sfn /Users/kws/source/private/Archive/skills/kws-codex-plan-executor \
        ~/.codex/skills/kws-codex-plan-executor
```

> `ln -sfn` 은 기존 심링크를 안전하게 갱신합니다(`-f` 강제, `-n` 디렉터리 타깃 보호). 실제 디렉터리를 덮어쓰지 않으려면 대상 경로가 심링크인지 먼저 확인하세요.

### 확인

```bash
ls -l ~/.claude/skills/ | grep kws-
ls -l ~/.codex/skills/  | grep kws-
```

두 곳 모두 `→ /Users/kws/source/private/Archive/skills/...` 로 표시되면 정상입니다.

## 수정 워크플로우

1. 이 디렉터리 안에서 직접 편집 (`skills/<skill>/SKILL.md` 등).
2. `git status` 로 Archive 레포에 변경 사항이 잡히는지 확인.
3. Claude/Codex 둘 다 즉시 새 내용을 사용 — 추가 설치 불필요.
4. 의미 있는 런타임 변경이면 각 스킬의 `SKILL.md` 프론트매터 버전,
   `HISTORY.md`, 관련 `docs/` / `references/` 문서를 함께 갱신합니다.
   문서만 정리한 경우에는 버전 bump가 필요하지 않습니다.

## 참고

- 다른 일반 스킬(reflective-writing-coach, archive-docs-organizer 등)은 별도의 `kws-skills` 플러그인에서 관리되며 이 디렉터리에는 포함되지 않습니다.
- executor 스킬을 Archive 레포로 옮긴 배경은 커밋 `d7039d5`, `17ff639`, `da8782c` 참고.
