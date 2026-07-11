---
name: kws-codex-plan-executor
description: Use when executing an implementation plan in Codex from a plan path and optional spec or design documents, resuming or inspecting a v3 run, or exporting a prompt or handoff launcher.
metadata:
  version: "3.0.0"
  updated_at: "2026-07-10"
  release_status: "integrity-closure-pending; paid-live-pending"
---

# KWS Codex Plan Executor

CPE v3 is an independent, event-sourced Codex plan executor. Its integrity
closure is still pending, and the paid live migration matrix has not run, so
release closeout remains `integrity-closure-pending; paid-live-pending`.

## Public Commands

```bash
python3 scripts/cpe.py run --plan PLAN [--spec SPEC] --workspace REPO --mode interactive
python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py export --plan PLAN --workspace REPO --mode prompt
python3 scripts/cpe.py export --plan PLAN --workspace REPO --mode handoff

python3 scripts/validate_state.py RUN_DIR
python3 scripts/reconcile_state.py --run-dir RUN_DIR --check
python3 scripts/repair_runs.py --run-dir RUN_DIR
python3 scripts/repair_runs.py --run-dir RUN_DIR --action ACTION \
  --details '{...}' --expected-projection-delta '{...}' --apply
python3 scripts/inspect_runs.py --codex-home ~/.codex --all-plans
python3 scripts/analyze_recent_runs.py --codex-home ~/.codex --recent 20
```

`run` and `resume` are execution surfaces. `export` in `prompt` or `handoff`
mode is export-only and creates no worktree or run artifacts. Validation,
reconciliation, repair, inspect, and recent-run inspection consume v3 run
artifacts. A v2 schema is reported as `unsupported_schema` and never rewritten.

## Fixed Routing

- Core coordination, implementation, review, verification, repair, and
  completion use `gpt-5.6-sol` with reasoning `high`.
- Only bounded read-only scouts may use `gpt-5.6-terra` with reasoning `high`.
- Model, reasoning, profile, alias, and fallback overrides are unsupported.
- Launcher arguments enforce the route; prompts do not select models.
- Missing or conflicting attestation blocks completion.

## Run Contract

Execution uses an isolated git worktree at
`~/.codex/worktrees/<run_id>` and durable artifacts at
`~/.codex/orchestrator/<run_id>`:

```text
run_manifest.json  immutable plan, spec, graph, model, and pricing hashes
events.jsonl       authoritative hash-chained transition history
state.json         rebuildable projection of manifest plus events
artifacts/         immutable task packets, evidence, prompts, and reports
```

Each executable task declares dependencies, file claims, acceptance commands,
and evidence requirements. When a spec is supplied, every task needs explicit `spec_refs`;
a missing or conflicting mapping blocks before edits. Every
`scout`, `implementation`, `task_review`, `verification`, `repair`, and
`final_review` request consumes the manifest-indexed task packet and verifies
its `packet_sha256`. Write-capable tasks execute sequentially. Independent
read-only scouts may run concurrently. Models never edit the manifest, events,
evidence index, or state projection.

Implementation starts only in the isolated worktree after the
`using-superpowers` and `test-driven-development` gates; the source checkout
and `main` branch are never used as the edit target.

Implementation and repair are the only product-writing roles. Their measured
Git delta records `worktree_revision` and `worktree_patch_sha256`; every later
`acceptance`, `task_review`, `verification`, `repository_check`, and
`final_review` record is valid only at that revision. A later write invalidates
the earlier suffix and schedules it again.

Completion first passes canonical integrity validation, then canonical
completion validation. It requires a valid manifest and event chain, snapshot
replay parity, all task and whole-diff reviews, in-scope git evidence,
acceptance evidence, fixed-route attestations, resolved blockers, and
repository-specific checks. The resulting projection records a structured
`completion_audit`; missing or stale completion evidence is a blocker.

## References

- [Architecture](ARCHITECTURE.md)
- [State and event contract](references/state-schema.md)
- [Execution cycle](references/execution-cycle.md)
- [Modes](references/mode-contracts.md)
- [Reconciliation and repair](references/drift-reconciliation.md)
- [Eval and release status](docs/evals-and-verification.md)

## Maintenance

Before changing this skill, follow [change-protocol.md](references/change-protocol.md),
[doc-update-protocol.md](docs/doc-update-protocol.md), and
[release-process.md](docs/release-process.md).
