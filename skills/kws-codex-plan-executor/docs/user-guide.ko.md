# 사용자 가이드

기본 실행:

```text
/kws-codex-plan-executor plan=plans/example.md
```

기본값은 `mode=interactive`, `subagents=on`입니다. `subagents=on`은
subagent-first 기본 실행이며, task packet과 disjoint write scope가 준비된
write-capable task는 기본적으로 subagent가 구현합니다.
`subagents=auto`는 사용자가 delegation/parallel work를 명시한 경우에만
subagent를 허용하는 보수 모드이고, `subagents=off`는 local-only입니다.
로컬 단일 에이전트로만 실행하려면 `subagents=off`를 넘기세요.
`subagents=on`에서 local fallback이 발생하면 task의 `subagent_strategy`에
구체적인 사유가 기록되어야 합니다.

실행 시 코드는 `~/.codex/worktrees/<run_id>`에, 상태와 로그는
`~/.codex/orchestrator/<run_id>`에 생성됩니다.

주요 inspection 파일:

- `state.json`: 실행의 권위 소스입니다.
- `context.json`: plan/spec/docs와 task packet index의 snapshot입니다.
- `spec_manifest.json`: spec section, mapping signal, fallback policy입니다.
- `task_packets/task_<N>.json`: task body, spec slice, filtered decisions,
  acceptance command, unit manifest, context component budget입니다.
- `trajectory.jsonl`: transcript 없이 보는 compact 실행 흐름입니다.

`blocked`는 recoverable `current_blocker`가 있는 상태이고, `failed`는
`failure_decision` 또는 non-recoverable blocker가 필요한 상태입니다.
`recovery_attempts`는 같은 root signature의 retry/bootstrap 예산을 추적합니다.

로컬 skill 파일을 직접 읽어야 할 때는 현재 세션의 skill registry/root
mapping을 기준으로 경로를 해석합니다. repo가 graphify 지침을 제공하면
`graphify-out/GRAPH_REPORT.md`의 빌드 커밋을 현재 HEAD와 비교하고, 코드
변경 후 `graphify update .` 실행 증거를 completion audit에 남깁니다.
