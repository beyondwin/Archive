# Waygent Documentation System And Graphify Adoption Design

Date: 2026-05-22
Status: Draft for user review

## Goal

Waygent needs a documentation system that explains the project clearly from the
root README, guides operators through real runtime usage, gives future
developers and AI agents stable contracts, and uses Graphify as a supported
repository map for cross-file exploration and documentation audits.

The current repository already contains strong architecture, operations,
contract, AgentLens, and skill documents. The problem is not a lack of content.
The problem is that the entry points and document roles are uneven: root
`README.md` was missing, current product docs and historical migration plans
sit near each other, and older Graphify-free guidance conflicts with the
decision to adopt Graphify as a development aid.

## Audience

The documentation system serves three primary readers:

- external reviewers evaluating Waygent as a portfolio-quality engineering
  project;
- local operators using `waygent run`, `status`, `inspect`, `explain`,
  `resume`, and `apply`;
- future developers and AI agents changing Waygent, AgentLens, runtime
  packages, contracts, or executor skills.

The first page should persuade. The deeper pages should prove.

## Non-Goals

- Do not make Graphify a product runtime dependency.
- Do not treat `graphify-out/` as the canonical source of runtime truth.
- Do not revive old KWS CPE/CME or AgentRunway routing as active architecture.
- Do not delete historical migration or planning documents in this pass.
- Do not rewrite every existing spec or plan. Reframe entry points first, then
  leave deep historical documents as referenced archive material.
- Do not commit runtime state, dependency directories, caches, provider logs, or
  machine-local paths.

## Design Principles

1. Root README is the product front door.
2. `docs/README.md` is the documentation router.
3. Current product docs should be easy to find before migration history.
4. Operations docs should describe what an operator does, not why the system was
   originally designed.
5. Contract docs should stay close to schemas, events, fixtures, and tests.
6. AgentLens should be documented as the observability and evaluation component,
   not as the active Waygent scheduler.
7. Skills should document invocation boundaries and agent behavior contracts.
8. Graphify should improve navigation and audits without replacing owned docs.

## Target Information Architecture

```text
README.md
docs/
  README.md
  getting-started.md
  architecture/
    waygent.md
    runtime.md
    agentlens.md
    decisions.md
  operations/
    waygent.md
    recovery.md
    verification.md
  contracts/
    events.md
    run-state.md
    provider-result.md
  roadmap/
    README.md
    migration-history.md
components/agentlens/docs/
  README.md
  cli.md
  dashboard.md
  security.md
skills/
  README.md
  waygent/
    README.md
  kws-codex-plan-executor/
    README.md
  kws-claude-multi-agent-executor/
    README.md
graphify-out/
  GRAPH_REPORT.md
  graph.json
  graph.html              # optional, only when graph size permits
```

This structure separates front-door explanation, current product docs, component
docs, skill contracts, historical planning, and generated repository maps.

## Document Responsibilities

### Root README

`README.md` introduces Waygent as the active product and explains why it is more
than a thin executor wrapper. It should cover:

- what Waygent is;
- the relationship between Waygent, AgentLens, and KWS executor skills;
- the top-level project map;
- quick local checks;
- common `waygent` commands;
- architecture links;
- Graphify usage as an approved development and documentation-audit tool;
- working rules and links to `AGENTS.md`, `PLANS.md`, and `code_review.md`.

The README should not contain full runtime contracts or long migration history.
It should link to the correct deeper page.

### Docs Router

`docs/README.md` should route readers by intent:

- reviewers: start with root README, architecture overview, and operations
  summary;
- operators: read getting started, operations, recovery, and verification;
- developers: read architecture, contracts, package boundaries, and tests;
- AI agents: read `AGENTS.md`, subtree `AGENTS.md`, `PLANS.md`,
  `code_review.md`, and the target skill docs.

It should make clear which docs describe current Waygent behavior and which are
historical planning records.

### Getting Started

`docs/getting-started.md` should provide a short runnable path:

- install with `bun install`;
- run `bun run check`;
- run `bun run platform:demo`;
- inspect normal `waygent` CLI flows;
- explain live-provider smoke tests as opt-in because they require installed
  and authenticated Codex or Claude CLIs.

This keeps the README concise while giving operators enough detail to try the
project locally.

### Architecture

`docs/architecture/waygent.md` remains the overview. It should be shorter and
point to focused pages:

- `runtime.md`: Bun control plane, Rust kernel, provider adapters, worktrees,
  safe-wave scheduling, verification, recovery, and apply readiness;
- `agentlens.md`: AgentLens event storage, projections, evaluation, and console
  role;
- `decisions.md`: durable decisions such as active event families, no legacy
  KWS namespaces, Graphify as a development aid, and live-provider checks as
  opt-in.

Historical architecture docs can stay where they are, but current overview pages
should not read like a migration chronology.

### Operations

`docs/operations/waygent.md` remains the main operator page. It should link to:

- `recovery.md`: failure classes, dirty checkout, drift, missing artifacts,
  provider failures, verification failure, duplicate run ids, and human
  decision points;
- `verification.md`: default local gates, AgentLens tests, console build,
  native kernel checks, fake-provider scenarios, and opt-in live-provider smoke
  tests.

The operations section should answer "what should I do next" during a real run.

### Contracts

`docs/contracts/events.md` remains the event-family contract. Add:

- `run-state.md`: `waygent.run_state.v2`, task status, safe waves,
  checkpoint refs, completion audit, reconciliation, recovery, and apply
  readiness;
- `provider-result.md`: normalized `runway.worker_result.v1` shape across fake,
  Codex, and Claude adapters, including provider attempts and stderr evidence.

Contract docs should cross-reference fixtures and tests where possible.

### Roadmap And Migration History

`docs/migration/` should not be the primary reader path. Keep existing migration
plans as historical planning records and add a current-facing index under
`docs/roadmap/`.

The roadmap section should explain:

- what has shipped;
- what is current design-only work;
- what remains future work;
- which migration documents are historical context rather than active runtime
  instructions.

### AgentLens Docs

`components/agentlens/docs/README.md` should clarify AgentLens' role inside the
Waygent platform:

- filesystem JSON artifacts and event replay;
- projections, trust, and evaluation;
- CLI and dashboard surfaces;
- security and local-state boundaries.

It should avoid framing AgentLens as the active scheduler or owner of apply
readiness. Waygent owns active runtime decisions.

### Skill Docs

`skills/README.md` and `skills/waygent/README.md` should keep the active product
boundary explicit:

- `waygent` is the active product skill that maps natural language to CLI
  commands;
- KWS executor skills are load-bearing local executor contracts but are outside
  the Waygent product runtime;
- when Waygent execution is requested, the runtime owns scheduling, worktrees,
  providers, verification, AgentLens emission, resume, and apply.

KWS executor docs can retain Graphify freshness rules when repository
instructions mention Graphify.

## Graphify Adoption

Graphify is approved as a repository map and documentation-audit tool.

### Intended Uses

Use Graphify for:

- exploring cross-file relationships before architecture or documentation
  changes;
- checking whether Waygent, AgentLens, skills, contracts, and package docs are
  still aligned;
- finding stale AgentRunway, KWS CPE/CME, or Graphify-free language in current
  docs;
- producing `GRAPH_REPORT.md` as a navigation and audit artifact;
- querying how runtime concepts connect across docs, fixtures, and packages.

Useful commands:

```bash
graphify update .
graphify query "how does Waygent decide apply readiness?"
graphify path "ProviderResult" "AgentLens"
graphify explain "safe wave"
```

### Output Policy

Commit stable navigation outputs when useful:

- `graphify-out/GRAPH_REPORT.md`;
- `graphify-out/graph.json`;
- `graphify-out/graph.html` when Graphify can generate it for the current graph
  size.

Ignore local or machine-specific outputs:

- `graphify-out/manifest.json`;
- `graphify-out/cost.json`;
- `graphify-out/cache/`;
- `graphify-out/.graphify_root`;
- `graphify-out/.graphify_labels.json`.

The first local run in this checkout generated `graph.json` and
`GRAPH_REPORT.md`, but skipped `graph.html` because the graph had more than
5,000 nodes. That is acceptable. Use `GRAPH_REPORT.md`, `graph.json`, and
`graphify query` for large graphs.

### Extraction Scope

Add `.graphifyignore` so generated maps do not ingest runtime state, local agent
state, dependencies, virtualenvs, build outputs, caches, or Graphify's own
output.

Required ignore categories:

- `.agentlens/`, `.claude/`, `.codex/`, `.codex-orchestrator/`,
  `.orchestrator/`, `.superpowers/`, `.waygent/`;
- `node_modules/`;
- `components/agentlens/.venv/`;
- `native/kernel/target/`;
- `dist/`, `build/`, coverage, cache, and temp directories;
- `graphify-out/`, `docs/wiki/`, and `docs/_graph/`.

### Agent Instructions

`AGENTS.md` should no longer say or imply that `graphify-out/` is unavailable
or discouraged. It should instead say:

- Graphify is approved for repo maps and documentation audits;
- use `graphify-out/` when it exists;
- refresh it with `graphify update .` after meaningful code or documentation
  structure changes;
- treat Graphify output as navigation and audit evidence, not runtime truth.

This keeps Graphify compatible with existing KWS Codex executor guidance that
checks `GRAPH_REPORT.md` freshness when repository instructions mention
Graphify.

## Rollout Plan

### Phase 1: Front Door And Graphify Enablement

- Create root `README.md`.
- Add Graphify usage to the README.
- Update `AGENTS.md` to approve Graphify as a development aid.
- Add `.graphifyignore`.
- Adjust `.gitignore` so stable Graphify outputs can be tracked while local
  cache and machine-path metadata remain ignored.
- Run `graphify update .`.
- Verify `GRAPH_REPORT.md` and `graph.json` are produced.

### Phase 2: Documentation Router

- Add `docs/README.md`.
- Add `docs/getting-started.md`.
- Link current docs from README and docs router.
- Make reader paths explicit for reviewers, operators, developers, and AI
  agents.

### Phase 3: Current Product Docs

- Slim `docs/architecture/waygent.md` into an overview.
- Add focused architecture pages for runtime, AgentLens, and decisions.
- Split operations recovery and verification details into focused pages.
- Add run-state and provider-result contract docs.

### Phase 4: Historical Context Reframing

- Add `docs/roadmap/README.md` and `docs/roadmap/migration-history.md`.
- Keep existing `docs/migration/*.md` files but route them through the roadmap
  index.
- Mark current, shipped, design-only, and historical material clearly.

### Phase 5: Component And Skill Alignment

- Add or update `components/agentlens/docs/README.md`.
- Review `skills/README.md` and `skills/waygent/README.md` for product-boundary
  clarity.
- Leave KWS executor skill internals untouched unless contract drift is found.

## Verification

Docs-only verification:

```bash
git diff --check
graphify update .
graphify query "how does Waygent decide apply readiness?" --graph graphify-out/graph.json
```

Manual review:

- root README links point to existing docs, or to new docs added in the same
  implementation phase;
- `AGENTS.md` no longer discourages Graphify;
- `.gitignore` does not allow local Graphify cache or machine paths;
- `.graphifyignore` prevents runtime state and dependencies from entering the
  graph;
- `GRAPH_REPORT.md` built commit matches the current `git rev-parse --short
  HEAD` at the time it was generated, or the staleness is understood after new
  uncommitted edits.

For future behavior changes that accompany docs updates, run the smallest
runtime gate that proves the changed code path.

## Acceptance Criteria

- A first-time reader can understand Waygent from root `README.md` without
  opening historical migration docs.
- `docs/README.md` gives clear reader-specific navigation.
- Operations, architecture, contracts, AgentLens, and skill docs have distinct
  responsibilities.
- Current Waygent docs do not present legacy KWS CPE/CME or AgentRunway names as
  active routing.
- Graphify is documented and enabled as a supported development aid.
- Stable Graphify outputs can be generated and tracked.
- Machine-local Graphify metadata and caches remain ignored.
- The documentation system remains compatible with KWS executor Graphify
  freshness checks.
