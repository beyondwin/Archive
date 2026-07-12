---
name: kws-codex-plan-executor
description: Use when executing an implementation plan in Codex from a plan path and optional spec or design documents, resuming or inspecting a v3 run, or exporting a prompt or handoff launcher.
metadata:
  version: "3.1.0"
  updated_at: "2026-07-12"
  release_status: "deterministic-ready; paid-live-verified"
---

# KWS Codex Plan Executor

CPE v3 is an independent, event-sourced Codex plan executor. Its audited
deterministic integrity closure and reviewed subscription live-migration matrix
are complete, so the published tuple is
`deterministic-ready; paid-live-verified`.

The checked-in subscription live-matrix runner is a guarded release-evidence
tool, not an execution route for normal CPE plans. It dry-runs, starts, and
resumes the exact 32-slot matrix with ChatGPT subscription authentication,
isolated fixture worktrees, an immutable ledger, and fail-closed aggregation.
The complete reviewed report has `release_gate.passed=true`; the privacy audit
also passed, so version 3.1.0 publishes `release_ready=true`. Direct USD cost
remains unobservable at the account-side subscription boundary.

## Public Commands

```bash
python3 scripts/cpe.py run --plan PLAN [--spec SPEC] --workspace REPO --mode interactive
python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py export --plan PLAN --workspace REPO --mode prompt
python3 scripts/cpe.py export --plan PLAN --workspace REPO --mode handoff

python3 scripts/validate_state.py RUN_DIR
python3 scripts/reconcile_state.py --run-dir RUN_DIR --check
python3 scripts/repair_runs.py --run-dir RUN_DIR --dry-run
python3 scripts/repair_runs.py --run-dir RUN_DIR --action ACTION \
  --details '{...}' --expected-projection-delta '{...}' --apply
python3 scripts/inspect_runs.py --codex-home ~/.codex --all-plans
python3 scripts/analyze_recent_runs.py --codex-home ~/.codex --recent 20

python3 evals/live_model_runner.py dry-run \
  --billing-mode chatgpt_subscription --output /tmp/cpe-live-plan.json
python3 evals/live_model_runner.py attest-predecessor \
  --predecessor-root /absolute/failed-evidence-root \
  --evidence-root /absolute/corrected-evidence-root
```

`run` and `resume` are execution surfaces. `export` in `prompt` or `handoff`
mode is export-only and creates no worktree or run artifacts. Validation,
reconciliation, repair, inspect, and recent-run inspection consume v3 run
artifacts. A v2 schema is reported as `unsupported_schema` and never rewritten.
`evals/live_model_runner.py` is separate from those public plan-execution
surfaces and requires explicit subscription-usage confirmation before any
credentialed call.

The v4-only `attest-predecessor` maintenance command is cost-free. It validates
one terminal failed predecessor root in place, then stores only a
domain-separated digest attestation in a fresh corrected root. It never copies
the predecessor manifest, slot evidence, output, session, authentication, or
oracle-bearing path bytes.

The unpublished v4 quality path is risk-first. Its immutable manifest names
`sol_v4_candidate` plus `security/migration block` as the only qualified
sentinel, independent of slot order. Every credentialed slot launches only
from a content-addressed `LaunchEnvelopeV4` containing the exact prompt and
output-schema bytes. Hidden oracle material stays in a separate runner-owned
`OracleBindingV4`; any envelope, route, source, fixture, schema, or oracle
binding drift blocks before a provider invocation. A sentinel semantic/oracle
failure terminally protects all remaining credentialed slots. For the block-ID
sentinel, semantic pass requires `review_accurate=true`; top-level blocked alone
is insufficient. One compiler-derived 17-entry sanitized envelope map binds the
slot ledger, aggregate, and release validator without exposing oracle material.

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

The immediately preceding published release was version 3.0.1 with
`deterministic-ready; paid-live-pending`; it remains historical compatibility
context only.

The older initial candidate metadata is retained solely for compatibility with
maintained contract scanners and historical readers. It never describes the
current release, current readiness, or an active routing decision. That literal
was `version: "3.0.0"`.
