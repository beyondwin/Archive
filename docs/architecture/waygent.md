# Waygent architecture

Bun/TypeScript control plane, Rust kernel, filesystem journals as replayable
evidence. Runtime decisions come from durable state and Lens projections, not
from chat.

```text
apps/cli, apps/api, apps/console
        │
packages/orchestrator  ── schedules, recovers, apply-readiness
packages/provider-adapters  ── fake / Codex / Claude
packages/lens-store + lens-projectors  ── evidence and views
        │
native/kernel  ── process, worktree, seal, policy, apply
```

Default execution is multi-agent. The scheduler still releases work through
safe waves.

## Who owns what

| Piece | Owns |
| --- | --- |
| `waygent` CLI (`apps/cli`) | run, status, inspect, explain, resume, apply |
| Orchestrator | durable runs, task dispatch, completion audit, recovery |
| Provider adapters | worker processes and `runway.worker_result.v1` |
| Lens | store and project evidence |
| Kernel | process, worktree, artifact seal, policy, diff apply |
| API / console | the same projections as CLI inspect/explain |

Providers never write Lens events. Waygent records attempts and accepted
evidence. Active event families are `platform.*`, `runway.*`, `kernel.*`, and
`lens.*`.

`waygent.run_state.v2` is the runtime source of truth. `agentlens.event.v3` is
append-only replay evidence. The schema name is a contract label, not a Python
runtime.

## Pages

- [Runtime](./runtime.md)
- [Lens](./agentlens.md)
- [Decisions](./decisions.md)
