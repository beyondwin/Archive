# Waygent Codex Superpowers Production Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved personal-local, Codex-only Waygent production harness in independently shippable phases while keeping Superpowers methods, deterministic evidence, and user-only merge as hard contracts.

**Architecture:** This is the program-level execution map. Five executable phase plans land in order: trust foundation, Superpowers contract, Codex worker plane, Console/improvement loop, and production validation. Each phase must produce a reviewed feature-branch checkpoint and pass its exit gate before the next phase starts.

**Tech Stack:** Bun, TypeScript, `bun:test`, Codex App Server JSON-RPC, Git worktrees, JSON/JSONL Lens storage, React/Vite Console, Rust native kernel, Superpowers skills.

**Spec:** `docs/superpowers/specs/2026-07-10-waygent-codex-superpowers-production-harness-design.md`

## Global Constraints

- Product scope is single-user, local-first, and Codex-only.
- Waygent must not call CPE or CME and must not recreate legacy Python AgentLens.
- Active events remain `agentlens.event.v3` records using only `platform.*`, `runway.*`, `kernel.*`, and `lens.*` namespaces.
- Superpowers skills are exact hash-pinned inputs; similar prompt prose is not evidence.
- Terra high is allowed only for mechanical read-only extraction.
- Sol high handles semantic exploration, task slicing, all ordinary writes, docs, config, and small changes.
- Sol xhigh handles shared API/state/concurrency/security/migration, repeated repair, independent review, and completion audit.
- Sol max is a one-attempt hard-blocker escalation after xhigh produced new evidence; `ultra` is forbidden.
- No worker may recursively delegate; Waygent owns fan-out.
- No runtime, CLI, API, or Console path may push a remote branch or merge a protected branch.
- User performs the final merge.
- P0 integrity must pass before P1; P1 method/manifest contracts before P2; P2 worker plane before P3; P3 projections before P4 acceptance.

---

## Phase Plans

| Order | Plan | Produces | Exit gate |
| --- | --- | --- | --- |
| P0 | `2026-07-10-waygent-codex-superpowers-p0-trust-foundation.md` | immutable IDs/artifacts, provider fail-fast, sealed journal, circuit breaker, security baseline | `P0_ACCEPTED` |
| P1 | `2026-07-10-waygent-codex-superpowers-p1-method-contract.md` | Skill Registry, full RunManifest, bounded packets, artifact-backed Superpowers evidence, real review | `P1_ACCEPTED` |
| P2 | `2026-07-10-waygent-codex-superpowers-p2-worker-plane.md` | App Server adapter, exact model router, role sandboxes, safe waves, feature-branch integrator | `P2_ACCEPTED` |
| P3 | `2026-07-10-waygent-codex-superpowers-p3-console-improvement.md` | persistent SSE, secure command API, operator projections, Console, Improvement Lab | `P3_ACCEPTED` |
| P4 | `2026-07-10-waygent-codex-superpowers-p4-production-validation.md` | replay/fault/model/live/dogfood evidence and production acceptance report | `PRODUCTION_READY` |

This umbrella file is not a substitute for the phase plans. Workers execute the
phase file named in the current task and must not preload later plans.

## Program Phase Gates (Reference Only)

This section is a non-executable index. It contains no task checklist and no
commit instruction. Waygent executes and checkpoints only the authoritative
phase plan named in the table above.

| Phase | Entry gate | Exit evidence |
| --- | --- | --- |
| P0 | current runtime and historical read compatibility | provider startup fail-closed, immutable identity/artifacts, sealed replay equality, private storage, native parity, `P0_ACCEPTED` |
| P1 | `P0_ACCEPTED` | immutable skill/manifest/packet contracts, artifact-backed method evidence, real independent review, `P1_ACCEPTED` |
| P2 | `P1_ACCEPTED` | pinned App Server protocol, approved model routes, fresh role roots, safe waves, local feature-branch integration, `P2_ACCEPTED` |
| P3 | `P2_ACCEPTED` | shared CLI/API/Console projections, cursor SSE, authenticated idempotent run controls, redacted improvement candidates, `P3_ACCEPTED` |
| P4 | `P3_ACCEPTED` | replay/fault/model/method evidence, 20/20 startup canaries, ten completed real-plan dogfoods, independently reviewed content-addressed verdict, `PRODUCTION_READY` |

Any failed exit gate blocks the next phase. A technical block remains visible
in the report but cannot satisfy the P4 requirement that all ten selected plans
complete dogfood execution.

## Execution Order

- Parallel-safe inside phases: only tasks explicitly marked by the phase plan.
- Sequential/shared-core: P0 → P1 → P2 → P3 → P4.
- Human approval gate: final protected-branch merge only.
- Technical blocks fail closed and produce evidence; they do not ask the user to choose routine implementation details.

## Spec Coverage Matrix

| Approved design requirement | Implemented by |
| --- | --- |
| personal-local, Codex-only, autonomous until user merge | umbrella constraints; P2 Tasks 6-7; P3 Tasks 3-5; P4 Task 7 |
| immutable RunManifest and explicit spec/task/skill policy | P0 Task 6; P1 Tasks 1-3 |
| thin Lead and bounded context | P1 Task 4; P2 Task 4 |
| exact Superpowers skill injection and public method evidence | P1 Tasks 2, 5, 6; P2 Task 2 |
| App Server primary and exec fallback | P2 Tasks 1, 2, 7 |
| approved Terra/Sol reasoning policy | P2 Task 3; P4 Task 4 |
| role worktrees, safe waves and serial integration | P2 Tasks 4-6 |
| sealed additive `agentlens.event.v3` journal and replay migration | P0 Tasks 1, 5, 6, 8 |
| failure observation, fingerprint and circuit breaker | P0 Tasks 2, 4; P4 Tasks 2-3 |
| persistent secure API/SSE and Console evidence views | P3 Tasks 1-5, 7 |
| failure clustering and guarded improvement loop | P3 Task 6; P4 Task 5 |
| local privacy, redaction and retention | P0 Task 7; P3 Tasks 3, 7; P4 Task 1 |
| historical replay, model eval, live canary and ten-plan dogfood | P4 Tasks 1, 4, 6, 7 |

## Program Verification

- Targeted tests: defined in each phase plan.
- Full TypeScript gate: `bun run check`.
- Scenario gate: `bun run waygent:scenarios`.
- Console gate: `cd apps/console && bun test src && bun run build`.
- Native gate: `cd native/kernel && cargo test --workspace`.
- Skill gate: `skills/waygent/evals/run.sh`.
- Graph audit: `git diff --check` after structural changes.
- Patch hygiene: `git diff --check` and clean intentional status.

## Review

Use `code_review.md` at every phase checkpoint. Findings are fixed within that
phase before its exit marker is accepted. No phase may defer a correctness,
security, state-integrity, or evidence gap to a later UI/reporting phase.
