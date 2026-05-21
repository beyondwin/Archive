# Waygent Repository Migration Design

Date: 2026-05-21

## Status

Approved for implementation planning.

## Objective

Rename the repository from Archive to Waygent and converge the tree around the
Waygent platform without losing the execution guarantees currently encoded in
AgentRunway. The migration must make the product structure clear, move
AgentLens into a component boundary, port the remaining AgentRunway runtime
semantics into Waygent packages, and remove `skills/agent-runway` only after
Waygent reaches parity.

## Current State

The repository has two overlapping shapes:

- The legacy active surface: `AgentLens/` and executor skills under `skills/`.
- The new Waygent product surface: `apps/`, `packages/`, `native/`, `tests/`,
  `docs/`, and `skills/waygent/`.

Waygent already has a Bun and TypeScript control plane, a Rust kernel skeleton,
event contracts, a local API, CLI, console prototype, and package tests. The
existing `skills/waygent` skill is intentionally thin: it maps natural language
run, status, explain, resume, and apply requests to stable CLI commands.

`skills/agent-runway` still owns more mature execution semantics: plan parsing,
safe-wave scheduling, worktree lifecycle, provider adapters, review and
verification gates, recovery, merge/apply flow, and AgentLens emission. It must
therefore remain as the reference oracle until those behaviors are represented
in the Waygent runtime.

## Target Repository Shape

After the repository is renamed, the root itself is the Waygent product root:

```text
Waygent/
  apps/
    cli/
    api/
    console/
  packages/
    contracts/
    orchestrator/
    runway-control/
    lens-store/
    lens-projectors/
    provider-adapters/
    policy/
    kernel-client/
    context-packer/
    testkit/
  native/
    kernel/
  components/
    agentlens/
  skills/
    waygent/
    kws-codex-plan-executor/
    kws-claude-multi-agent-executor/
  docs/
    architecture/
    contracts/
    operations/
    migration/
  tests/
  package.json
  bun.lock
  tsconfig.base.json
```

The top-level `apps/`, `packages/`, `native/`, `docs/`, `tests/`, and `skills/`
directories remain top-level because the repository itself is Waygent. Do not
introduce a nested `products/waygent/` directory.

`AgentLens/` moves to `components/agentlens/` because AgentLens is the
observability and evaluation component inside Waygent, not the repository root
product. `apps/lens-web/` becomes `apps/console/` because the user-facing app is
the Waygent console; Lens remains an internal capability.

Generated and local directories such as `node_modules/`, `dist/`, `.agentlens/`,
`.claude/`, `.codex-orchestrator/`, `.orchestrator/`, `.pytest_cache/`, and
`tmp/` are ignore and cleanup concerns, not product structure.

## Runtime Boundary

Waygent absorbs AgentRunway as the `runway` runtime domain. The standalone
`agent-runway` skill disappears only after parity is proven.

| AgentRunway responsibility | Waygent owner |
| --- | --- |
| Plan/spec parsing and task graph | `packages/orchestrator`, `packages/context-packer` |
| Safe-wave scheduling and dependency barriers | `packages/runway-control` |
| Failure barriers and recovery decision packets | `packages/runway-control` |
| Codex, Claude, and fake adapter normalization | `packages/provider-adapters` |
| Worktree creation and diff/apply safety | `native/kernel`, `packages/kernel-client` |
| Event journal and artifact store | `packages/lens-store` |
| Trust projection and evidence scoring | `packages/lens-projectors` |
| User-facing CLI, API, and console | `apps/cli`, `apps/api`, `apps/console` |

The execution flow is:

```text
skills/waygent
  -> apps/cli
  -> packages/orchestrator
  -> packages/runway-control
  -> packages/provider-adapters
  -> native/kernel via packages/kernel-client
  -> packages/lens-store
  -> packages/lens-projectors
  -> apps/api / apps/console
```

Provider adapters and subagents must not write Lens or AgentLens state
directly. The Waygent orchestrator validates typed evidence and writes the
durable event stream.

## Contract Migration

New Waygent runs use the active event families:

- `platform.*`
- `runway.*`
- `kernel.*`
- `lens.*`

Historical AgentRunway events remain readable, but they are not the active
runtime contract for new Waygent executions. `agentrunway.*` is retained only
for read-only compatibility during migration. The old KWS executor namespaces
`kws-cpe.*`, `kws-cme.*`, and `kws.orchestrator.*` remain rejected by the active
contract validator.

The new projection artifact should be owned by Lens, not by the execution
domain. Use `lens.runway_projection.v1` for the new Waygent projection. Existing
`agentlens.agentrunway_projection.v1` and `agentrunway_projection.json`
fixtures may remain as legacy read fixtures until the compatibility layer is
explicitly retired.

## Implementation Phases

### Phase 0: Preparation

Commit pending ignore-policy changes separately from structural changes. Do not
mix `.gitignore` edits with directory moves. Do not delete generated or local
runtime directories without explicit approval.

Verification:

```bash
git diff --check
git status --short --branch --untracked-files=all
```

### Phase 1: Structure Migration

Move `AgentLens/` to `components/agentlens/` and `apps/lens-web/` to
`apps/console/`. Update package scripts, imports, tests, documentation, and
agent instructions. This phase must not change runtime behavior.

Verification:

```bash
bun run check
bun run --cwd apps/console build
cd components/agentlens && python -m pytest -q
git diff --check
```

### Phase 2: Waygent Runtime Parity

Port the execution behavior currently represented by AgentRunway into Waygent
packages and the Rust kernel boundary. Cover plan parsing, task graph creation,
safe-wave scheduling, worktree lifecycle, provider result normalization,
verification gates, recovery decision packets, and apply safety.

Verification:

```bash
bun test ./packages/runway-control/tests ./packages/orchestrator/tests ./packages/provider-adapters/tests ./tests/integration
cd native/kernel && cargo fmt --all -- --check
cd native/kernel && cargo clippy --workspace --all-targets -- -D warnings
cd native/kernel && cargo test --workspace
```

### Phase 3: Contract Migration

Make `platform.*`, `runway.*`, `kernel.*`, and `lens.*` the active contract
surface. Move `agentrunway.*` test coverage into legacy read-compatibility
fixtures. Add new Waygent projection coverage for `lens.runway_projection.v1`.

Verification:

```bash
bun test ./packages/contracts/tests ./packages/lens-store/tests ./packages/lens-projectors/tests
cd components/agentlens && python -m pytest -q
```

### Phase 4: AgentRunway Removal

Remove `skills/agent-runway` only after Waygent can replace the core
`run/status/explain/resume/apply` scenarios and deterministic eval meaning.
Update `AGENTS.md`, `CLAUDE.md`, `skills/README.md`, and verification commands
to route execution through Waygent.

Verification:

```bash
rg "skills/agent-runway|agentrunway.py"
bun run check
cd native/kernel && cargo test --workspace
cd components/agentlens && python -m pytest -q
git diff --check
```

The `rg` command may return historical migration notes or legacy compatibility
fixtures, but it must not return active routing or runtime instructions.

### Phase 5: Final Cleanup

Review ignored generated directories and local runtime state. Remove local
generated files only with explicit approval. Keep cleanup commits separate from
runtime or structure commits.

## Non-Goals

- Do not introduce `products/waygent/`.
- Do not revive the old KWS CPE/CME split as an active runtime direction.
- Do not delete `skills/agent-runway` before Waygent parity is proven.
- Do not make provider adapters or subagents write Lens state directly.
- Do not combine local generated-file cleanup with product refactors.

## Risks And Controls

| Risk | Control |
| --- | --- |
| Large path move hides behavior regressions | Keep Phase 1 behavior-neutral and run both Bun and AgentLens tests. |
| Waygent removes mature AgentRunway guarantees too early | Use AgentRunway eval meaning as the parity oracle until Phase 4. |
| Event migration breaks old recorded runs | Preserve `agentrunway.*` read compatibility during migration. |
| Root cleanup deletes local state unexpectedly | Require explicit approval before deleting generated or runtime directories. |
| Commit scope becomes hard to review | Separate ignore policy, structure, runtime, contract, removal, and cleanup commits. |

## Acceptance Criteria

The migration is complete when:

- The repository is coherent as a Waygent root.
- AgentLens lives under `components/agentlens/`.
- The console lives under `apps/console/`.
- New runs use the Waygent event families.
- Waygent covers the core AgentRunway execution scenarios.
- `skills/agent-runway` has been removed from active routing.
- Remaining AgentRunway references are historical notes or legacy
  compatibility fixtures only.
- The full verification set passes for Bun, Rust, and AgentLens surfaces.
