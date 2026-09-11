# Waygent architecture

TypeScript apps and packages plus a Rust kernel. Saved files on disk are the
records you can replay. Runtime choices come from the saved run file and Lens
views, not from chat.

```text
apps/cli, apps/api, apps/console
        │
packages/orchestrator  ── schedules, recovers, ready-to-apply
packages/provider-adapters  ── fake / Codex / Claude
packages/lens-store + lens-projectors  ── records and views
        │
native/kernel  ── process, isolated git copy, lock, policy, apply
```

Default runs use several agents. The scheduler still starts work in safe
task groups.

## Who owns what

| Piece | Owns |
| --- | --- |
| `waygent` CLI (`apps/cli`) | run, status, inspect, explain, resume, apply |
| Scheduler | saved runs, task start, final check, recovery |
| Provider adapters | worker processes and `runway.worker_result.v1` |
| Lens | store records and build views |
| Kernel | process, isolated git copy, lock saved files, policy, apply |
| API / console | the same views as CLI inspect/explain |

Providers never write Lens events. Waygent records attempts and accepted
results. Active event families are `platform.*`, `runway.*`, `kernel.*`, and
`lens.*`.

`waygent.run_state.v2` is the saved run file. `agentlens.event.v3` is the
append-only event log. The schema name is a label, not a Python runtime.

## Pages

- [Runtime](./runtime.md)
- [Lens](./lens.md)
- [Decisions](./decisions.md)
