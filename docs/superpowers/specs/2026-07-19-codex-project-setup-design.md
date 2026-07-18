# Archive Codex Project Setup Design

**Date:** 2026-07-19

**Status:** Approved design

**Scope:** Repository-owned guidance, verification routing, safety policy, and
local setup documentation for Codex and adjacent coding agents

## Goal

Make Codex consistently identify the authoritative checkout, select the right
Waygent or executor boundary, edit only the intended surface, run meaningful
verification, and report honest completion evidence without relying on the
user to remember project-specific caveats.

The setup must improve autonomy without granting broader external authority.
Pushes, pull requests, deploys, destructive cleanup, credential changes, and
external connector actions remain governed by the user's request and Codex's
approval boundary.

## Current-State Findings

Archive already has a useful root `AGENTS.md`, project-scoped Codex defaults,
command rules, a plan template, and a review checklist. The missing layer is
consistency and enforcement:

- most active `apps/`, `packages/`, `native/kernel/`, and `skills/` subtrees do
  not have local `AGENTS.md` guidance;
- `.cursor/rules/archive.mdc` and a `.gitignore` comment still point to the
  removed `AgentLens/` layout;
- `code_review.md` names `npm run gen-types`, but the repository has no such
  script;
- verification commands are documented but not selected automatically from
  the changed paths;
- no repository CI or instruction-drift check proves that agent guidance still
  matches tracked paths and executable commands;
- active linked worktrees make the current directory an unsafe proxy for the
  authoritative `main` checkout;
- machine-local Codex health, permissions, MCP credentials, and retained
  sessions are operational concerns but should not be committed as shared
  repository policy.

## Considered Approaches

### A. Documentation-only cleanup

Update the root guidance and stale references, leaving verification and safety
as prose. This is the smallest change, but it does not prevent future drift or
make completion claims reproducible.

### B. Layered repository guardrails (selected)

Keep the root contract concise, add focused subtree guidance, introduce one
path-aware verification entry point, validate the instruction contract in CI,
and test project command rules. This gives Codex fast local routing while
keeping critical claims mechanically checkable.

### C. Archive-specific agent platform/plugin

Package roles, hooks, skills, connectors, and automation as a dedicated Codex
plugin. This would be useful for distribution across many repositories, but it
duplicates Waygent and the existing executor skills for a single-repository
setup. It is intentionally deferred until the same workflow is needed outside
Archive.

## Design Principles

1. **One canonical truth per concern.** `AGENTS.md` owns durable behavior;
   scripts own mechanical checks; operations docs explain why and how.
2. **Closest guidance wins.** Subtree instructions contain only rules that
   differ from or refine the root contract.
3. **Verification is path-aware and evidence-based.** A successful command must
   exercise the changed surface; placeholder commands never count.
4. **Local state is not repository state.** Codex health, authentication, MCP
   secrets, runtime journals, caches, and session retention stay outside Git.
5. **Autonomy does not widen authority.** The agent may inspect and implement
   within the requested scope, but external and destructive actions still need
   explicit authorization.
6. **Historical names stay readable, not routable.** Old AgentLens,
   AgentRunway, CPE, and CME names may remain in history and compatibility
   contracts, but active work follows Waygent and the TypeScript Lens path.

## Guidance Architecture

### Root contract

Refactor the root `AGENTS.md` into a short routing contract containing:

- authoritative product boundaries and forbidden legacy routing;
- a mandatory start preflight: `pwd`, full Git status, current branch/HEAD,
  worktree inventory, and nearest instruction discovery;
- a task classifier for Waygent runtime, Lens, console, native kernel, Codex
  executor, Claude executor, docs-only, and cross-cutting changes;
- the single verification entry point and the definition of done;
- external-authority and destructive-action boundaries;
- links to `PLANS.md`, `code_review.md`, and operations references.

The root file will not duplicate detailed component invariants or long command
matrices.

### Subtree contracts

Add focused guidance at these boundaries:

- `apps/AGENTS.md`: CLI/API/console ownership, public surface compatibility,
  and UI/build expectations;
- `packages/AGENTS.md`: package dependency direction, event/state contracts,
  TypeScript checks, and cross-package verification escalation;
- `native/kernel/AGENTS.md`: Rust-only safety boundary, process supervision,
  platform support, formatting, and workspace tests;
- `skills/AGENTS.md`: skill source-of-truth rules, required `SKILL.md` reading,
  docs/eval synchronization, and separation from Waygent product runtime;
- `skills/kws-codex-plan-executor/AGENTS.md`: strict-thin sequential executor
  invariants, Python standard-library boundary, eval gate, and plan/runtime
  separation.

The existing Claude executor `AGENTS.md` remains authoritative in its subtree
and will be checked for consistency rather than flattened into the root file.

### Cross-agent mirrors

`CLAUDE.md`, `GEMINI.md`, `.cursor/rules/archive.mdc`, and
`.github/copilot-instructions.md` remain lightweight adapters that point to the
canonical `AGENTS.md`. They may contain tool-specific reminders, but may not
restate project topology in a way that can drift independently.

## Verification Architecture

Add one repository entry point, exposed as `bun run agent:verify`, that accepts
either the current worktree diff or an explicit base/head range. It will:

1. collect changed tracked and untracked paths without modifying the worktree;
2. classify them into docs, apps, packages, native kernel, Waygent skill,
   Codex executor, and Claude executor scopes;
3. run the smallest meaningful deterministic checks for each scope;
4. escalate to broader checks for cross-boundary changes;
5. always run instruction-contract validation and `git diff --check`;
6. print a stable summary of selected scopes, commands, exits, and skipped
   opt-in checks.

The selection policy will be data-driven in a tracked manifest so reviewers
can see which paths map to which commands. It must not install dependencies,
rewrite generated files, start live providers, or mutate runtime state.

Initial verification mapping:

| Changed surface | Required checks |
| --- | --- |
| Docs and agent guidance only | instruction contract, Markdown links for touched files, `git diff --check` |
| `apps/console/` | focused tests and console build |
| Other `apps/` or TypeScript `packages/` | targeted tests when available, `bun run typecheck`, then `bun run check` for shared-runtime changes |
| Waygent runtime across two or more packages or `bun.lock` | offline closure gate from `docs/operations/verification.md` |
| `native/kernel/` | Rust format check and `cargo test --workspace` |
| `skills/waygent/` | its skill contract eval plus relevant Waygent checks |
| Codex executor | `skills/kws-codex-plan-executor/evals/run.sh` |
| Claude executor | `skills/kws-claude-multi-agent-executor/evals/run.sh` |

Live-provider tests remain explicit opt-in checks and must be reported as not
run rather than silently substituted.

## Instruction-Contract Validation

Add a deterministic validator that fails when:

- a path presented as active does not exist;
- an active surface lacks an expected nearest `AGENTS.md`;
- guidance references a removed active path such as `AgentLens/` outside an
  explicitly historical context;
- a required package script or verification executable is missing;
- cross-agent mirror files contradict the Waygent/Lens routing contract;
- local runtime, secret, cache, or transcript paths become tracked;
- the verification manifest contains overlapping or unreachable scope rules.

The validator will check structure, not prose style. Historical migration and
design documents are excluded from active-path assertions.

## Safety And Codex Configuration

Keep `.codex/config.toml` limited to safe, shareable project defaults. Do not
commit provider credentials, account-specific MCP configuration, notification
commands, or machine-specific paths.

Expand `.codex/rules/archive.rules` with precise, tested decisions for:

- force pushes and destructive branch deletion;
- recursive deletion of runtime/state/worktree directories;
- destructive worktree removal;
- history rewrites and broad clean operations.

Each rule must have positive and negative `codex execpolicy check` fixtures so
ordinary read-only Git and targeted file operations remain frictionless.

Repository hooks are optional enforcement, not the first line of design. A
hook will be added only where an execpolicy rule or normal test cannot express
the invariant, and it must fail with a clear recovery message. No hook may
send data, modify credentials, or write outside ignored local state.

## CI And Drift Control

Add a GitHub Actions workflow with two layers:

- **agent contract:** fast instruction validation, execpolicy fixtures,
  touched-document link checks, and patch hygiene;
- **change verification:** invoke the same path-aware verification entry point
  used locally, with dependency caches but without live providers.

Local and CI commands must be identical. CI is evidence that the repository
contract is executable, not a separate source of verification truth.

## Local Operator Setup

Add `docs/operations/codex-local-setup.md` for non-committable operator tasks:

- trust the repository before expecting project `.codex` layers to load;
- run `codex doctor --summary` and distinguish repository failures from global
  configuration warnings;
- keep sandbox/approval choices in the user's configuration unless the team
  explicitly standardizes them;
- configure only required MCP servers and environment variables;
- periodically review retained sessions and stale worktrees without deleting
  active evidence automatically;
- restart Codex or open a new task after instruction/configuration changes.

This document may recommend actions but must not encode personal credentials,
absolute home-directory paths, or automatic destructive cleanup.

## Agent Workflows

Routine work follows this flow:

1. Load the root and nearest subtree guidance.
2. Reconcile the current checkout with the worktree inventory and identify the
   authoritative branch/HEAD for the requested task.
3. Classify the task and read only the routed architecture, operations, skill,
   or plan documents.
4. Preserve dirty state and implement within the user's authority.
5. Run `bun run agent:verify` and any explicitly required opt-in evidence.
6. Review against `code_review.md`.
7. Report changed files, exact commands/results, skipped evidence, residual
   risks, and local-versus-remote state.

Complex approved Superpowers plan execution still routes through the relevant
executor contract. A normal Codex task must not emulate Waygent orchestration
or mutate its durable run state manually.

## Error Handling

- Missing tools or dependencies produce an environment blocker with the exact
  failed probe; the verifier does not install or weaken checks automatically.
- A dirty or non-authoritative worktree stops destructive or finalization
  actions but does not block read-only diagnosis.
- Unknown changed paths select a conservative full offline gate and emit a
  manifest-gap warning.
- Flaky or live-provider checks are reported separately from deterministic
  gates.
- Instruction drift fails before implementation completion can be claimed.
- CI and local disagreements include tool versions and selected scopes in the
  result so the mismatch is diagnosable.

## Acceptance Criteria

The implementation is complete when:

- all active code families have accurate nearest guidance;
- stale active-layout references are removed from current instruction files;
- one documented command selects and runs meaningful verification from a diff;
- instruction drift and execpolicy behavior have automated tests;
- CI runs the same repository-owned checks as local Codex;
- docs-only, console-only, package-crossing, Rust-only, and each executor change
  fixture select the expected gates;
- a clean checkout passes the agent contract and default offline verification;
- local-only warnings are documented without being embedded into shared config;
- no runtime state, credentials, transcripts, generated output, or unrelated
  worktree changes are committed.

## Out Of Scope

- installing external connectors or plugins;
- changing Waygent product behavior or event contracts;
- changing either executor's scheduling or quality policy;
- deleting existing worktrees, runtime evidence, or Codex sessions;
- standardizing user-global model, sandbox, approval, or authentication policy;
- rewriting historical design and migration documents solely to remove legacy
  terminology.

## Rollout Order

1. Correct canonical guidance and stale mirrors.
2. Add subtree contracts.
3. Add and test instruction-contract validation.
4. Add the verification manifest and path-aware entry point.
5. Expand and test execpolicy rules.
6. Add CI using the established local commands.
7. Add local operator documentation and run the full acceptance matrix.

This order keeps every enforcement layer based on an already-correct written
contract and makes regressions attributable to one layer at a time.
