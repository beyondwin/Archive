# Design: AgentRunway Hybrid Scheduler And Failure Recovery

Date: 2026-05-21
Status: Implemented
Owner: KWS
Related Work:
- `docs/superpowers/specs/2026-05-20-agentrunway-durable-orchestrator-hardening-design.md`
- `docs/superpowers/plans/2026-05-21-agentrunway-durable-orchestrator-hardening.md`

## 1. Summary

AgentRunway should use a checkpoint-streaming hybrid execution model:

```text
dependency checkpoint ready
  + no file/resource conflict
  -> parallel safe wave

shared core file, broad claim, blocked dependency, missing checkpoint,
or repeated failure
  -> serial execution or stop for decision
```

This gives the speed benefits of multi-agent execution without pushing merge,
rebase, and review failures to the end of the run. Worktrees are created only
when a task is truly ready, successful tasks are merged into run-main
immediately, and downstream work is released only by checkpoint evidence.

The failure policy must be part of scheduling, not an after-the-fact status
report. If a task is blocked or its checkpoint is missing, dependent tasks must
not start. If an activity is stale, resume must classify and repair it before
new work is dispatched.

## 2. Evidence From The Hardening Run

The cancelled hardening run exposed three useful facts:

- `task_003` failed review twice with `needs_rebase`.
- `task_004` blocked with `needs_infra_fix`.
- `task_005` still started after those blocked upstream states.

The timings also show why the workflow felt slower than existing KWS skill
runs:

- each task paid implement, review, verification, and merge overhead;
- full-tree review repeated on shared runner changes;
- work touching `runner.py` serialized in practice even when separate
  worktrees existed;
- rebase failures were discovered during review, after worker time had already
  been spent.

The core lesson is that worktree isolation alone is not the speed mechanism.
The speed mechanism is safe concurrency plus fast checkpoint integration.

## 3. Recommended Model

Use `CheckpointStreamingHybridScheduler`.

It has four rules:

1. Create worktrees lazily.
   A task receives a worktree only when all dependency checkpoints exist and
   the scheduler places it in the next safe wave.

2. Parallelize safe independent work.
   Tasks can share a wave only when their file claims and resource keys do not
   conflict, none of them are broad/shared-core tasks, and none depend on a
   blocked or unrepaired task.

3. Merge successful tasks immediately into run-main.
   Passing review and verification creates a `merged:<task_id>` checkpoint.
   Dependent work starts from that checkpoint, not from the original run base.

4. Treat failure as a scheduling barrier.
   A blocked task, missing checkpoint, stale activity, repeated failure class,
   or missing resume handler prevents dependent dispatch until repaired or
   explicitly decided.

## 4. Task Classification

The scheduler should classify each task before dispatch:

| Class | Criteria | Execution |
| --- | --- | --- |
| `independent` | Owned files, no dependency gap, low/medium risk | Parallel safe wave |
| `soft_overlap` | Shared append or docs/tests overlap only | Parallel only if claims are compatible |
| `shared_core` | `runner.py`, scheduler, DB, resume, gate, adapter control flow | Serial |
| `barrier` | Migration, broad claim, high risk, infra fix, plan fix | Serial and checkpoint before release |
| `blocked_dependent` | Depends on blocked/missing-checkpoint task | Do not create worktree |

This classification should be visible in `inspect`, `summarize`, and
`resume --dry-run` so operators know why work is or is not moving.

## 5. Worktree Policy

AgentRunway should not create all worker worktrees at run start.

Worktree lifecycle:

```text
ready by checkpoint projection
  -> create worker worktree from latest run-main checkpoint
  -> run implement/review/verify
  -> merge selected candidate to run-main
  -> create checkpoint
  -> archive or retain worktree according to retention policy
```

Benefits:

- fewer stale bases;
- lower disk/process overhead;
- less manual cleanup after blocked runs;
- downstream workers always start from the newest durable base.

The exception is speculative prefetch. AgentRunway may prepare packet/context
artifacts for likely next tasks, but it should not create a mutable worker
worktree or dispatch an adapter until the task is checkpoint-ready.

## 6. Failure Recovery Policy

Failures should be normalized into a small action table.

| Failure | Automatic action | Stop condition |
| --- | --- | --- |
| `needs_rebase` | Redispatch once from latest checkpoint | Same class repeats |
| `needs_implementer_retry` | Retry implementer within budget | Budget exhausted |
| `needs_plan_fix` | Stop and create decision packet | Always human |
| `needs_infra_fix` | Stop and create decision packet | Always human |
| `missing_checkpoint` | Verify/reconstruct from completed merge output | No valid merge output |
| `missing_resume_handler` | Block action and report unsupported boundary | Always human or implementation |
| `stale_activity` | Mark stale, inspect process, then resume from last completed boundary | Activity has live process |
| `merge_conflict` | Stop at merge boundary with candidate/checkpoint context | Always human unless explicit strategy exists |
| `adapter_crash` | Retry only if idempotency key has no completed output | Repeated crash |
| `artifact_missing` | Block and request artifact repair | Missing required evidence |

No automatic recovery may dispatch dependent tasks until the projection has no
blocked upstream dependency and no checkpoint repair task.

## 7. State Machine Guardrails

The runtime loop should follow one invariant:

```text
dispatchable_tasks = projection.safe_wave
```

The projection must exclude any task when:

- any dependency lacks a `merged:<dependency_id>` checkpoint;
- any dependency is `blocked` or `failed`;
- a dependency has a completed merge activity but no checkpoint;
- the run has a human decision packet for an upstream node;
- an activity is `started` past timeout and not classified;
- the required resume action lacks an implemented handler.

Final run status should also come from projection:

- `finished`: all tasks have merge checkpoints and no repair tasks remain;
- `blocked`: any human decision, stale unrepaired activity, missing handler,
  blocked task, or unreachable pending task exists;
- `running`: at least one live activity or dispatchable safe wave exists;
- `cancelled`: operator cancellation only.

This prevents task status alone from making the run look healthier than its
checkpoint graph.

## 8. Gate Policy For Speed

Gate depth should vary by task class.

| Task class | Review | Verification |
| --- | --- | --- |
| `independent` | Diff review | Task acceptance commands |
| `soft_overlap` | Diff review plus claim check | Focused tests |
| `shared_core` | Full-tree review | Focused tests plus e2e |
| `barrier` | Full-tree review | Full relevant suite |

Repeated full-tree review on every small task is too expensive. Full-tree
review should be reserved for shared control flow, broad claims, or previous
failure evidence.

## 9. Observability And Operator Output

`inspect`, `summarize`, and `resume --dry-run` should show:

- current checkpoint id and commit;
- completed checkpoint tasks;
- blocked upstream tasks;
- safe wave with classification reasons;
- tasks withheld from worktree creation and why;
- stale activities with age;
- next automatic action;
- required human decision packet;
- retry budget consumed by failure class.

This makes "why is it slow?" and "why did it stop?" answerable without reading
SQLite by hand.

## 10. Best Practical Strategy

The best near-term strategy is not a full rewrite. It is a two-layer change:

1. Make the projection authoritative.
   Every command and runtime dispatch decision reads the same durable
   projection. No dependent task can start unless it appears in `safe_wave`.

2. Add failure barriers before adding more concurrency.
   Fix stale activity handling, repeated failure budgets, missing handler
   blocking, and checkpoint repair first. Then increase parallel safe-wave
   width for independent tasks.

This preserves AgentRunway's safety model while recovering much of the speed
of earlier KWS skill workflows.

## 11. Acceptance Criteria

- A blocked upstream task prevents downstream worktree creation and dispatch.
- A task marked `merged` without checkpoint produces a repair action, not
  dependency release.
- A repeated `needs_rebase` stops with a decision packet instead of looping.
- `missing_resume_handler` is visible and blocks writes.
- Independent non-overlapping tasks share a safe wave.
- Shared-core tasks execute serially even if their dependencies are ready.
- `inspect`, `summarize`, and `resume --dry-run` report the same safe wave,
  blocked node, next action, and human decision.
- Full evals pass after implementation.

## 12. Implementation Note

Implemented through the hybrid scheduler failure recovery plan. The durable
projection is the authoritative dispatch source, task classification drives
parallel versus serial execution, resume failures block durably, and
inspect/summarize expose the same scheduler diagnostics used by runtime
dispatch.
