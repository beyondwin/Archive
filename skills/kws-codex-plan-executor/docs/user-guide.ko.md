# 사용자 가이드

기본 실행:

```text
/kws-codex-plan-executor plan=plans/example.md
```

기본값은 `mode=interactive`, `subagents=on`입니다. 기본 실행은 task packet과
disjoint write scope가 준비된 경우 subagent 사용을 허용합니다.
`subagents=auto`는 사용자가 delegation/parallel work를 명시한 경우에만
subagent를 허용하는 보수 모드이고, `subagents=off`는 local-only입니다.
로컬 단일 에이전트로만 실행하려면 `subagents=off`를 넘기세요.

실행 시 코드는 `~/.codex/worktrees/<run_id>`에, 상태와 로그는
`~/.codex/orchestrator/<run_id>`에 생성됩니다.

로컬 skill 파일을 직접 읽어야 할 때는 현재 세션의 skill registry/root
mapping을 기준으로 경로를 해석합니다. repo가 graphify 지침을 제공하면
`graphify-out/GRAPH_REPORT.md`의 빌드 커밋을 현재 HEAD와 비교하고, 코드
변경 후 `graphify update .` 실행 증거를 completion audit에 남깁니다.
