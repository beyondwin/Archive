# 사용자 가이드

기본 실행:

```text
/kws-codex-plan-executor plan=plans/example.md
```

기본값은 `mode=interactive`, `subagents=auto`입니다. subagent 사용은 사용자가
delegation/parallel work를 명시하거나 `subagents=on`을 넘긴 경우에만 허용됩니다.
로컬 단일 에이전트로만 실행하려면 `subagents=off`를 넘기세요.

실행 시 코드는 `~/.codex/worktrees/<run_id>`에, 상태와 로그는
`~/.codex/orchestrator/<run_id>`에 생성됩니다.
