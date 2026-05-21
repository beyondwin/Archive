# Waygent Documentation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reviewer-friendly and operator-usable Waygent documentation system from the root README down through architecture, operations, contracts, AgentLens, skills, and Graphify repo-map outputs.

**Architecture:** Root `README.md` becomes the product front door, `docs/README.md` becomes the reader router, focused docs own current architecture/operations/contracts, and historical migration plans move behind a roadmap index. Graphify is enabled as a development and documentation-audit layer while canonical runtime truth remains in code, tests, contracts, and owned docs.

**Tech Stack:** Markdown documentation, Bun workspace commands, Graphify 0.8.x, `git diff --check`, existing Waygent docs under `docs/`, AgentLens docs under `components/agentlens/docs/`, and skill docs under `skills/`.

---

## Source Design

Spec: `docs/superpowers/specs/2026-05-22-waygent-documentation-system-design.md`

Repository instructions: `AGENTS.md`

Current useful commands:

```bash
bun install
bun run check
bun run platform:demo
graphify update .
graphify query "how does Waygent decide apply readiness?" --graph graphify-out/graph.json
git diff --check
```

## Scope Check

This is one documentation system, not seven independent docs projects. The
tasks are sequential because the root README and docs router decide how later
architecture, operations, contract, roadmap, component, and skill docs are
linked.

No runtime behavior changes are included. If implementation reveals stale
commands or broken code paths, stop and report the blocker instead of editing
runtime code inside this docs plan.

The current worktree may already contain uncommitted Phase 1 material from the
design session: `README.md`, `.graphifyignore`, `.gitignore`, `AGENTS.md`, and
`graphify-out/`. Treat those files as in-scope work to inspect and refine, not
as unrelated changes to discard.

## File Structure

### Front Door And Graphify Enablement

- `README.md`: create or refine the product front door for reviewers,
  operators, developers, and AI agents.
- `AGENTS.md`: update repository instructions so Graphify is approved as a repo
  map and documentation-audit tool.
- `.graphifyignore`: keep runtime state, dependency directories, build outputs,
  caches, and Graphify's own outputs out of extraction.
- `.gitignore`: allow stable Graphify outputs while ignoring cache and
  machine-local metadata.
- `graphify-out/GRAPH_REPORT.md`: generated navigation and audit report.
- `graphify-out/graph.json`: generated queryable graph.

### Docs Router And Getting Started

- `docs/README.md`: reader-specific navigation for reviewers, operators,
  developers, and AI agents.
- `docs/getting-started.md`: local setup, default checks, basic Waygent CLI
  flows, Graphify refresh, and opt-in live provider checks.

### Current Product Architecture

- `docs/architecture/waygent.md`: short overview and links to focused
  architecture pages.
- `docs/architecture/runtime.md`: current Bun control plane, Rust kernel,
  scheduler, provider adapter, verification, recovery, and apply-readiness
  architecture.
- `docs/architecture/agentlens.md`: AgentLens role as observability and
  evaluation component.
- `docs/architecture/decisions.md`: durable current decisions, including
  active event families, no legacy KWS namespaces, Graphify as development aid,
  and live-provider checks as opt-in.

### Operations And Contracts

- `docs/operations/waygent.md`: keep as the main operations overview and link
  to focused pages.
- `docs/operations/recovery.md`: failure classes and recovery choices.
- `docs/operations/verification.md`: local and live verification gates.
- `docs/contracts/events.md`: keep active event-family contract and link to new
  contract docs.
- `docs/contracts/run-state.md`: `waygent.run_state.v2`, task state, safe
  waves, checkpoints, completion audit, reconciliation, recovery, and apply
  readiness.
- `docs/contracts/provider-result.md`: normalized provider result contract for
  fake, Codex, and Claude adapters.

### Roadmap, AgentLens, And Skills

- `docs/roadmap/README.md`: current roadmap and reader-safe index.
- `docs/roadmap/migration-history.md`: index existing `docs/migration/*.md`
  files as historical planning records.
- `components/agentlens/docs/README.md`: AgentLens component entry point.
- `skills/README.md`: clarify Waygent skill versus KWS executor skills.
- `skills/waygent/README.md`: clarify thin skill boundary and Graphify
  relationship.

## Execution Order

Sequential tasks:

1. Task 1 finalizes the root front door and Graphify enablement.
2. Task 2 creates the docs router and getting-started guide.
3. Task 3 splits current architecture docs.
4. Task 4 splits operations and contract docs.
5. Task 5 reframes migration history behind roadmap docs.
6. Task 6 aligns AgentLens and skill docs with the product boundary.
7. Task 7 refreshes Graphify and performs the final documentation audit.

Parallel-safe tasks:

- None in the default plan. The link graph and naming decisions are shared
  across all docs, so sequential edits reduce drift.

Human approval gates:

- Stop after Task 2 if the root README and docs router do not match the desired
  portfolio tone.
- Stop before deleting or moving any historical migration document. This plan
  indexes historical files; it does not delete them.

---

### Task 1: Finalize Root README And Graphify Enablement

**Files:**
- Create or modify: `README.md`
- Modify: `AGENTS.md`
- Create: `.graphifyignore`
- Modify: `.gitignore`
- Generate: `graphify-out/GRAPH_REPORT.md`
- Generate: `graphify-out/graph.json`

- [ ] **Step 1: Inspect current front-door and Graphify changes**

Run:

```bash
git status --short --untracked-files=all
git diff -- README.md AGENTS.md .gitignore .graphifyignore
```

Expected: current worktree may already contain `README.md`, `.graphifyignore`,
Graphify updates in `AGENTS.md`, `.gitignore`, and generated
`graphify-out/GRAPH_REPORT.md` plus `graphify-out/graph.json`. Preserve these
changes and refine them instead of replacing them blindly.

- [ ] **Step 2: Ensure root README has the required sections**

Edit `README.md` so it has these headings in this order:

```markdown
# Waygent

## Project Map

## Quick Start

## Architecture

## Graphify Repository Map

## Working Rules
```

Ensure the opening paragraphs say:

```markdown
Waygent is a local agent runtime for running, inspecting, recovering, and
applying multi-agent implementation work. It owns scheduling, worktrees,
provider adapters, verification, recovery, apply readiness, and AgentLens event
emission.

AgentLens is the observability and evaluation component. KWS executor skills
remain in this repository as local executor contracts, but they are not the
Waygent product runtime.
```

- [ ] **Step 3: Add README command blocks**

Ensure `README.md` contains this default local check block:

```bash
bun install
bun run check
bun run platform:demo
```

Ensure it contains this Waygent command block:

```bash
waygent run --latest
waygent status --last
waygent inspect --run <run_id> --json
waygent explain --last
waygent resume --last
waygent apply --run <run_id>
```

Ensure live provider checks are documented as opt-in:

```bash
WAYGENT_LIVE_PROVIDER=codex bun run waygent:live-smoke
WAYGENT_LIVE_PROVIDER=claude bun run waygent:live-smoke
```

- [ ] **Step 4: Add Graphify README policy**

Ensure `README.md` states:

```markdown
[Graphify](https://github.com/safishamsi/graphify) is an approved development
and documentation-audit tool for this repository.
```

Ensure it includes:

```bash
graphify update .
graphify query "how does Waygent decide apply readiness?"
graphify path "ProviderResult" "AgentLens"
graphify explain "safe wave"
```

Ensure it says Graphify is not a product runtime dependency and does not replace
canonical contracts under `docs/`, `packages/`, `native/`, and
`components/agentlens/`.

- [ ] **Step 5: Update repository instructions for Graphify**

In `AGENTS.md`, keep this Graphify instruction near the project-shape section:

```markdown
Graphify is approved as a repository map and documentation-audit tool. Use
`graphify-out/` when it exists, and refresh it with `graphify update .` after
meaningful code or documentation structure changes. Treat Graphify output as
navigation and audit evidence, not as the product runtime source of truth.
Canonical contracts remain in code, tests, `docs/`, `components/agentlens/`,
and `skills/`.
```

Remove any current-facing sentence that says `graphify-out/` should not be
assumed as part of the active checkout. Historical specs may still mention
Graphify-free designs when clearly historical.

- [ ] **Step 6: Add Graphify extraction ignores**

Create `.graphifyignore` with these categories:

```gitignore
# Runtime and local machine state
.git/
.agentlens/
.claude/
.codex/
.codex-orchestrator/
.orchestrator/
.superpowers/
.waygent/
.parallel/
.cursor/
.local/

# Dependency and build output
node_modules/
apps/*/node_modules/
packages/*/node_modules/
components/agentlens/.venv/
components/agentlens/.pytest_cache/
components/agentlens/.agentlens/
components/agentlens/src/*.egg-info/
native/kernel/target/
target/
dist/
build/
coverage/
htmlcov/
.cache/
tmp/
temp/

# Generated graph output should not feed back into extraction.
graphify-out/
docs/wiki/
docs/_graph/

# Local artifacts
.DS_Store
*.log
*.json.partial
```

- [ ] **Step 7: Update `.gitignore` for Graphify outputs**

In `.gitignore`, the generated navigation/search section should ignore local
Graphify metadata while allowing stable outputs:

```gitignore
# Generated navigation/search layers
graphify-out/manifest.json
graphify-out/cost.json
graphify-out/cache/
graphify-out/.graphify_root
graphify-out/.graphify_labels.json
docs/wiki/*
!docs/wiki/README.md
docs/_graph/*
!docs/_graph/README.md
```

- [ ] **Step 8: Generate and verify Graphify outputs**

Run:

```bash
graphify update .
graphify query "how does Waygent decide apply readiness?" --graph graphify-out/graph.json
```

Expected: `graphify update .` exits 0 and writes `graphify-out/graph.json` and
`graphify-out/GRAPH_REPORT.md`. If `graph.html` is skipped because the graph has
more than 5,000 nodes, leave that as accepted behavior.

- [ ] **Step 9: Validate and commit front-door changes**

Run:

```bash
git diff --check -- README.md AGENTS.md .graphifyignore .gitignore graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git add README.md AGENTS.md .graphifyignore .gitignore graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "docs: add Waygent README and Graphify map"
```

Expected: diff check exits 0 and the commit includes only front-door,
repository-instruction, ignore-policy, and Graphify output files.

---

### Task 2: Add Documentation Router And Getting Started Guide

**Files:**
- Create: `docs/README.md`
- Create: `docs/getting-started.md`
- Modify: `README.md`

- [ ] **Step 1: Create `docs/README.md`**

Create `docs/README.md` with these sections:

```markdown
# Waygent Documentation

## Start Here

## Reader Paths

## Current Product Docs

## Component Docs

## Skill Docs

## Historical Planning

## Graphify Map
```

Under `Reader Paths`, include:

```markdown
- Reviewers: read the root `README.md`, then `architecture/waygent.md`, then
  `operations/waygent.md`.
- Operators: read `getting-started.md`, `operations/waygent.md`,
  `operations/recovery.md`, and `operations/verification.md`.
- Developers: read `architecture/waygent.md`, `contracts/events.md`,
  `contracts/run-state.md`, and `contracts/provider-result.md`.
- AI agents: read `../AGENTS.md`, the nearest subtree `AGENTS.md`,
  `../PLANS.md`, `../code_review.md`, and the target skill README.
```

- [ ] **Step 2: Create `docs/getting-started.md`**

Create `docs/getting-started.md` with these sections:

```markdown
# Getting Started With Waygent

## Prerequisites

## Install

## Default Local Verification

## Demo Run

## Basic CLI Flow

## Graphify Refresh

## Live Provider Checks

## Stop Rules
```

Include these exact default commands:

```bash
bun install
bun run check
bun run platform:demo
```

Include this basic CLI flow:

```bash
waygent run --latest
waygent status --last
waygent inspect --run <run_id> --json
waygent explain --last
```

State that `waygent apply --run <run_id>` requires a clean source checkout and
ready apply projection.

- [ ] **Step 3: Link the router from root README**

In `README.md`, add this link under the Architecture or Working Rules section:

```markdown
- Documentation index: [docs/README.md](docs/README.md)
- Getting started: [docs/getting-started.md](docs/getting-started.md)
```

- [ ] **Step 4: Validate links and commit**

Run:

```bash
test -f docs/README.md
test -f docs/getting-started.md
test -f docs/architecture/waygent.md
test -f docs/operations/waygent.md
test -f docs/contracts/events.md
git diff --check -- README.md docs/README.md docs/getting-started.md
git add README.md docs/README.md docs/getting-started.md
git commit -m "docs: add Waygent documentation index"
```

Expected: all commands exit 0.

---

### Task 3: Split Current Architecture Docs

**Files:**
- Modify: `docs/architecture/waygent.md`
- Create: `docs/architecture/runtime.md`
- Create: `docs/architecture/agentlens.md`
- Create: `docs/architecture/decisions.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Slim `docs/architecture/waygent.md` into an overview**

Keep `# Waygent Architecture` as the title. Ensure the first paragraph says:

```markdown
Waygent is the user-facing agent platform. The control plane is Bun and
TypeScript; the execution kernel is Rust; AgentLens stores replayable events,
artifacts, and trust projections; API and console surfaces expose that evidence
to operators.
```

Keep current links to shipped detailed designs, but add a `Current Architecture
Pages` section with:

```markdown
- [Runtime](./runtime.md)
- [AgentLens](./agentlens.md)
- [Decisions](./decisions.md)
```

- [ ] **Step 2: Create `docs/architecture/runtime.md`**

Create `docs/architecture/runtime.md` with these sections:

```markdown
# Waygent Runtime Architecture

## Runtime Boundary

## Control Plane

## Execution Kernel

## Scheduling And Safe Waves

## Provider Adapters

## Verification And Recovery

## Apply Readiness

## Default Gates
```

Include the active event families:

```markdown
Active event families are `platform.*`, `runway.*`, `kernel.*`, and `lens.*`.
```

Include the default gates:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
```

- [ ] **Step 3: Create `docs/architecture/agentlens.md`**

Create `docs/architecture/agentlens.md` with these sections:

```markdown
# AgentLens Architecture

## Role In Waygent

## Durable Artifacts

## Projections

## Evaluation And Trust

## Boundaries
```

Include this boundary statement:

```markdown
AgentLens observes and evaluates Waygent evidence. Waygent owns active
scheduling, provider execution, verification, recovery, and apply readiness.
```

- [ ] **Step 4: Create `docs/architecture/decisions.md`**

Create `docs/architecture/decisions.md` with a table containing these rows:

```markdown
| Decision | Current Position |
| --- | --- |
| Product brand | Waygent is the user-facing platform and orchestrator. |
| Observability | AgentLens is the observability and evaluation component. |
| Event families | Active events use `platform.*`, `runway.*`, `kernel.*`, and `lens.*`. |
| Legacy namespaces | New Waygent runs must not emit `agentrunway.*`, `kws-cpe.*`, or `kws-cme.*`. |
| Graphify | Graphify is an approved development and documentation-audit tool, not a runtime dependency. |
| Live providers | Codex and Claude live smoke checks are opt-in. |
```

- [ ] **Step 5: Link architecture pages from docs router**

In `docs/README.md`, under current product docs, include:

```markdown
- [Architecture overview](architecture/waygent.md)
- [Runtime architecture](architecture/runtime.md)
- [AgentLens architecture](architecture/agentlens.md)
- [Architecture decisions](architecture/decisions.md)
```

- [ ] **Step 6: Validate and commit architecture docs**

Run:

```bash
test -f docs/architecture/runtime.md
test -f docs/architecture/agentlens.md
test -f docs/architecture/decisions.md
git diff --check -- docs/README.md docs/architecture/waygent.md docs/architecture/runtime.md docs/architecture/agentlens.md docs/architecture/decisions.md
git add docs/README.md docs/architecture/waygent.md docs/architecture/runtime.md docs/architecture/agentlens.md docs/architecture/decisions.md
git commit -m "docs: split Waygent architecture guide"
```

Expected: all commands exit 0.

---

### Task 4: Split Operations And Contracts

**Files:**
- Modify: `docs/operations/waygent.md`
- Create: `docs/operations/recovery.md`
- Create: `docs/operations/verification.md`
- Modify: `docs/contracts/events.md`
- Create: `docs/contracts/run-state.md`
- Create: `docs/contracts/provider-result.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Update operations overview links**

At the top of `docs/operations/waygent.md`, add:

```markdown
Related operations docs:

- [Recovery](./recovery.md)
- [Verification](./verification.md)
```

Keep existing operational trust-loop, run preflight, apply readiness,
safe-wave, execution-intelligence, and stop-rule content.

- [ ] **Step 2: Create `docs/operations/recovery.md`**

Create `docs/operations/recovery.md` with these sections:

```markdown
# Waygent Recovery

## First Step

## Failure Classes

## Recovery Actions

## Stop Conditions
```

Include this failure mapping:

```markdown
| Failure | Operator action |
| --- | --- |
| `dirty_source_checkout` | Clean or commit the source checkout before resume or apply. |
| `dependency_missing` | Repair the verification environment and rerun verification. |
| `environment_blocker` | Inspect setup evidence before retrying. |
| `verification_failed` | Fix the task worktree or route to human decision. |
| `artifact_missing` | Inspect checkpoint artifacts before regeneration. |
| `state_drift` | Reconcile drift before apply. |
| duplicate run id | Choose a new run id or resume the existing run. |
```

- [ ] **Step 3: Create `docs/operations/verification.md`**

Create `docs/operations/verification.md` with these sections:

```markdown
# Waygent Verification

## Default Offline Gate

## Console Gate

## Native Kernel Gate

## AgentLens Gate

## Live Provider Gate

## Docs-Only Gate
```

Include:

```bash
bun run check
bun run platform:demo
bun run waygent:scenarios
bun run --cwd apps/console build
cd native/kernel && cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace
cd components/agentlens && .venv/bin/python -m pytest -q
git diff --check
```

State that live provider gates require `WAYGENT_LIVE_PROVIDER=codex` or
`WAYGENT_LIVE_PROVIDER=claude`.

- [ ] **Step 4: Update event contract links**

In `docs/contracts/events.md`, add:

```markdown
Related contracts:

- [Run state](./run-state.md)
- [Provider result](./provider-result.md)
```

Keep the statement that legacy KWS executor namespaces are rejected by the
contract validator.

- [ ] **Step 5: Create `docs/contracts/run-state.md`**

Create `docs/contracts/run-state.md` with these sections:

```markdown
# Waygent Run State Contract

## Source Of Truth

## Task State

## Safe Waves

## Checkpoints

## Completion Audit

## Reconciliation

## Apply Readiness

## Related Tests
```

Include:

```markdown
`waygent.run_state.v2` is the authoritative runtime state for task status,
provider attempts, verification evidence, review records, recovery decisions,
drift, completion audit, and apply readiness.
```

Reference `tests/fixtures/contracts/valid-run-state-v2.json` as the fixture to
inspect.

- [ ] **Step 6: Create `docs/contracts/provider-result.md`**

Create `docs/contracts/provider-result.md` with these sections:

```markdown
# Waygent Provider Result Contract

## Providers

## Normalized Result

## Evidence

## Stderr And Logs

## Related Tests
```

Include:

```markdown
Fake, Codex, and Claude providers normalize worker output into
`runway.worker_result.v1`. Providers do not write AgentLens events directly.
Waygent records provider attempts and converts accepted worker output into
runtime-owned evidence.
```

- [ ] **Step 7: Link operations and contracts from docs router**

In `docs/README.md`, add:

```markdown
- [Operations](operations/waygent.md)
- [Recovery](operations/recovery.md)
- [Verification](operations/verification.md)
- [Event contract](contracts/events.md)
- [Run-state contract](contracts/run-state.md)
- [Provider-result contract](contracts/provider-result.md)
```

- [ ] **Step 8: Validate and commit operations and contracts**

Run:

```bash
test -f docs/operations/recovery.md
test -f docs/operations/verification.md
test -f docs/contracts/run-state.md
test -f docs/contracts/provider-result.md
git diff --check -- docs/README.md docs/operations/waygent.md docs/operations/recovery.md docs/operations/verification.md docs/contracts/events.md docs/contracts/run-state.md docs/contracts/provider-result.md
git add docs/README.md docs/operations/waygent.md docs/operations/recovery.md docs/operations/verification.md docs/contracts/events.md docs/contracts/run-state.md docs/contracts/provider-result.md
git commit -m "docs: split Waygent operations and contracts"
```

Expected: all commands exit 0.

---

### Task 5: Reframe Roadmap And Migration History

**Files:**
- Create: `docs/roadmap/README.md`
- Create: `docs/roadmap/migration-history.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Create roadmap index**

Create `docs/roadmap/README.md` with these sections:

```markdown
# Waygent Roadmap

## Current Product Baseline

## Shipped Work

## Design-Only Work

## Future Work

## Historical Migration Records
```

Under `Current Product Baseline`, state that Waygent is the active product
runtime and AgentLens is the observability and evaluation component.

- [ ] **Step 2: Create migration-history index**

Create `docs/roadmap/migration-history.md` with links to every current
`docs/migration/*.md` file. Use this exact structure:

```markdown
# Waygent Migration History

These documents are historical planning and migration records. They are useful
for understanding how the repository arrived at the current Waygent shape, but
they are not the primary operator or implementation entry point.

## Records
```

Then list each file from:

```bash
find docs/migration -maxdepth 1 -type f -name '*.md' | sort
```

Use relative links such as:

```markdown
- [Waygent repository migration design](../migration/2026-05-21-waygent-repository-migration-design.md)
```

- [ ] **Step 3: Link roadmap from docs router**

In `docs/README.md`, add:

```markdown
- [Roadmap](roadmap/README.md)
- [Migration history](roadmap/migration-history.md)
```

State that migration documents are not the first reader path for current
runtime behavior.

- [ ] **Step 4: Validate and commit roadmap docs**

Run:

```bash
test -f docs/roadmap/README.md
test -f docs/roadmap/migration-history.md
git diff --check -- docs/README.md docs/roadmap/README.md docs/roadmap/migration-history.md
git add docs/README.md docs/roadmap/README.md docs/roadmap/migration-history.md
git commit -m "docs: index Waygent roadmap and migration history"
```

Expected: all commands exit 0.

---

### Task 6: Align AgentLens And Skill Docs

**Files:**
- Create or modify: `components/agentlens/docs/README.md`
- Modify: `skills/README.md`
- Modify: `skills/waygent/README.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Add AgentLens component README**

Create or update `components/agentlens/docs/README.md` with these sections:

```markdown
# AgentLens Documentation

## Role In Waygent

## Durable State

## CLI And Dashboard

## Security

## Related Waygent Docs
```

Include:

```markdown
AgentLens records, queries, evaluates, and visualizes agent-run evidence.
Waygent owns active scheduling, provider execution, verification, recovery, and
apply readiness.
```

Link:

```markdown
- [CLI](./cli.md)
- [Dashboard](./dashboard.md)
- [Security](./security.md)
- [Waygent architecture](../../../docs/architecture/waygent.md)
- [AgentLens architecture](../../../docs/architecture/agentlens.md)
```

- [ ] **Step 2: Clarify `skills/README.md` product boundary**

In `skills/README.md`, keep the existing skill table and ensure the `waygent`
row says:

```markdown
| [`waygent`](./waygent/) | 활성 제품 런타임 스킬. 자연어 실행, 상태, 이벤트, 검사, 설명, 재개, 적용 요청을 Waygent CLI로 변환합니다. KWS executor 스킬은 별도 비제품 executor 계약으로 유지됩니다. |
```

Add a short section:

```markdown
## Waygent Boundary

Waygent 요청은 `skills/waygent/`에서 CLI로 라우팅하고, 런타임 상태와
스케줄링은 Waygent가 소유합니다. `kws-*` 스킬은 로컬 executor 계약이며
Waygent 제품 런타임 의존성이 아닙니다.
```

- [ ] **Step 3: Clarify `skills/waygent/README.md` Graphify relationship**

In `skills/waygent/README.md`, add:

```markdown
## Repository Map

When `graphify-out/` exists, use it as navigation and audit evidence for
cross-file questions. Refresh it with `graphify update .` after meaningful code
or documentation structure changes. Graphify output is not Waygent runtime
state and does not replace `waygent.run_state.v2`, AgentLens events, or
contract tests.
```

- [ ] **Step 4: Link component and skill docs from docs router**

In `docs/README.md`, add:

```markdown
- [AgentLens docs](../components/agentlens/docs/README.md)
- [Skills overview](../skills/README.md)
- [Waygent skill](../skills/waygent/README.md)
```

- [ ] **Step 5: Validate and commit component and skill docs**

Run:

```bash
test -f components/agentlens/docs/README.md
git diff --check -- docs/README.md components/agentlens/docs/README.md skills/README.md skills/waygent/README.md
git add docs/README.md components/agentlens/docs/README.md skills/README.md skills/waygent/README.md
git commit -m "docs: align AgentLens and Waygent skill docs"
```

Expected: all commands exit 0.

---

### Task 7: Refresh Graphify And Audit Documentation System

**Files:**
- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`
- Read: `README.md`
- Read: `docs/README.md`
- Read: `AGENTS.md`
- Read: `docs/architecture/waygent.md`
- Read: `docs/operations/waygent.md`
- Read: `docs/contracts/events.md`

- [ ] **Step 1: Refresh Graphify after all docs changes**

Run:

```bash
graphify update .
```

Expected: exits 0 and updates `graphify-out/GRAPH_REPORT.md` and
`graphify-out/graph.json`. If `graph.html` is skipped because the graph is too
large, accept that result.

- [ ] **Step 2: Run architecture query smoke checks**

Run:

```bash
graphify query "how does Waygent decide apply readiness?" --graph graphify-out/graph.json
graphify query "what is the relationship between Waygent and AgentLens?" --graph graphify-out/graph.json
graphify query "where are Graphify outputs documented?" --graph graphify-out/graph.json
```

Expected: each command exits 0 and returns nodes from current docs or fixtures.

- [ ] **Step 3: Run stale-language checks**

Run:

```bash
rg -n "active routing|product runtime|Graphify-free|graphify-out" README.md AGENTS.md docs components/agentlens/docs skills/README.md skills/waygent/README.md
rg -n "kws-cpe|kws-cme|agentrunway\\." README.md docs/README.md docs/architecture docs/operations docs/contracts components/agentlens/docs/README.md skills/README.md skills/waygent/README.md
```

Expected: any hits in current-facing docs describe legacy namespaces as
historical or rejected. `Graphify-free` should appear only in historical specs
or migration records, not in current README, docs router, active architecture,
operations, contracts, AgentLens README, or Waygent skill README.

- [ ] **Step 4: Run docs-only checks**

Run:

```bash
git diff --check
test -f README.md
test -f docs/README.md
test -f docs/getting-started.md
test -f docs/architecture/runtime.md
test -f docs/architecture/agentlens.md
test -f docs/architecture/decisions.md
test -f docs/operations/recovery.md
test -f docs/operations/verification.md
test -f docs/contracts/run-state.md
test -f docs/contracts/provider-result.md
test -f docs/roadmap/README.md
test -f docs/roadmap/migration-history.md
test -f components/agentlens/docs/README.md
test -f graphify-out/GRAPH_REPORT.md
test -f graphify-out/graph.json
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit final Graphify refresh**

Run:

```bash
git add graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "docs: refresh Graphify map"
```

Expected: commit succeeds if Graphify outputs changed. If Graphify outputs did
not change after Task 1, skip the commit and record that no final Graphify
refresh commit was necessary.

- [ ] **Step 6: Final status check**

Run:

```bash
git status --short --branch --untracked-files=all
```

Expected: no unintended docs, runtime state, `.DS_Store`, dependency, cache, or
build-output files remain staged or untracked. Existing unrelated user changes
may remain, but do not stage them.

## Final Verification Checklist

Run before reporting completion:

```bash
git diff --check
graphify update .
graphify query "how does Waygent decide apply readiness?" --graph graphify-out/graph.json
git status --short --branch --untracked-files=all
```

Manual checks:

- Root README explains Waygent without requiring historical migration docs.
- `docs/README.md` has reader-specific routes.
- Current architecture, operations, and contract docs have focused
  responsibilities.
- AgentLens is described as observability and evaluation, not active scheduling.
- Waygent skill docs route execution through the CLI/runtime.
- Graphify is approved in current docs and repository instructions.
- `graphify-out/.graphify_root`, `.graphify_labels.json`, cache, manifest, and
  cost files are not staged.
- `.DS_Store` is not staged.
