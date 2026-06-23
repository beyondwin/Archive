# Waygent Codex Best Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Codex `--profile max-quality` select the strongest Waygent runtime loop without requiring operators to remember low-level flags.

**Architecture:** Keep Waygent runtime authority in `packages/orchestrator` and expose the behavior through CLI profile resolution. The CLI maps provider-aware profile presets and run-harness defaults into existing `runWaygent` options; the scheduler, verifier, checkpoint, and apply gates remain unchanged.

**Tech Stack:** Bun, TypeScript, `bun:test`, Waygent CLI, existing Waygent run state and provider profile contracts.

## Global Constraints

- Waygent must not call `skills/kws-codex-plan-executor`.
- New Waygent runs use `platform.*`, `runway.*`, `kernel.*`, and `lens.*` event families.
- Do not recreate `components/agentlens`.
- Preserve source-checkout and worker-worktree isolation.
- External research clones stay outside this repository and are not committed.
- Verification uses focused CLI tests first, then repo-level gates.

---

### Task 1: Add Provider-Aware Codex Profile Tests

**Files:**

- Modify: `apps/cli/tests/profilePreset.test.ts`

**Interfaces:**

- Consumes: `resolveCliProfile(parseCli(...))`
- Produces: assertions for `resolveCliRunDefaults(parsed, profile)`

- [x] **Step 1: Write failing profile tests**

Add tests asserting that `--provider codex --profile max-quality` resolves to
`gpt-5.5` with `xhigh` main reasoning and `high` role reasoning.

- [x] **Step 2: Run RED**

Run:

```bash
bun test apps/cli/tests/profilePreset.test.ts
```

Expected before implementation: fails because `resolveCliRunDefaults` is not
exported and Codex `max-quality` still uses Claude-shaped model names.

- [x] **Step 3: Implement provider-aware preset resolution**

Modify `apps/cli/src/index.ts` so Claude keeps the existing
`opus`/`sonnet` presets while Codex receives `gpt-5.5`/`gpt-5` presets.

- [x] **Step 4: Add run-harness default resolver**

Add `resolveCliRunDefaults(parsed, profile)` with Codex max-quality defaults:

```ts
{
  plan_preflight: "full",
  spec_slice: "manifest",
  hook_config: "builtin",
  require_method_evidence: true
}
```

- [x] **Step 5: Run GREEN**

Run:

```bash
bun test apps/cli/tests/profilePreset.test.ts
```

Expected after implementation: all profile tests pass.

### Task 2: Wire Defaults Into `waygent run`

**Files:**

- Modify: `apps/cli/src/index.ts`

**Interfaces:**

- Consumes: `RunWaygentOptions`
- Produces: `runCli(["run", ...])` options with profile-specific defaults

- [x] **Step 1: Apply defaults when constructing run options**

Spread `resolveCliRunDefaults(parsed, profile)` into the `run`/`demo` options
object before task-specific fields are added.

- [x] **Step 2: Preserve explicit overrides**

Keep explicit `--plan-preflight`, `--spec-slice`, and `--hook-config` higher
priority than the profile defaults.

- [x] **Step 3: Keep `run-chain` model-only**

Do not change run-chain semantics in this slice. It can use provider-aware
model routing, but chain-wide harness defaulting needs a separate design if
operators need it.

### Task 3: Document The Codex Best Loop

**Files:**

- Create: `docs/superpowers/specs/2026-06-23-waygent-codex-best-loop-design.md`
- Create: `docs/superpowers/plans/2026-06-23-waygent-codex-best-loop.md`
- Create: `docs/operations/codex-best-loop.md`
- Modify: `docs/README.md`
- Modify: `docs/operations/waygent.md`
- Modify: `skills/waygent/SKILL.md`
- Modify: `skills/waygent/README.md`

**Interfaces:**

- Consumes: external clone/test evidence from `/tmp/waygent-codex-loop-research`
- Produces: operator-facing command and architecture rationale

- [x] **Step 1: Record research evidence**

List external repositories, commit ids, local commands, and pass/fail status.

- [x] **Step 2: Write operator guidance**

Make the recommended command explicit:

```bash
bun run waygent -- run --plan <plan.md> --spec <design.md> --profile max-quality
```

- [x] **Step 3: Update Waygent skill guidance**

Map “최고 품질” and Codex implementation requests to `--profile max-quality`
instead of hand-managed worker orchestration.

### Task 4: Verify And Close

**Files:**

- Read: changed files from Tasks 1-3

**Interfaces:**

- Consumes: focused tests, repo check, Graphify freshness
- Produces: final verification evidence

- [x] **Step 1: Run focused CLI profile tests**

```bash
bun test apps/cli/tests/profilePreset.test.ts apps/cli/tests/cli.test.ts
```

Result: `38 pass`, `0 fail`.

- [x] **Step 2: Run relevant Waygent gates**

```bash
bun run check
bun run waygent:scenarios
```

Result: `bun run check` reported `816 pass`, `10 skip`, `0 fail`;
`bun run waygent:scenarios` reported `15 pass`, `0 fail`.

- [x] **Step 3: Refresh Graphify**

```bash
graphify update .
```

Result: rebuilt `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json`
from the current code graph.

- [x] **Step 4: Check patch hygiene**

```bash
git diff --check
git status --short --branch --untracked-files=all
```

Result: `git diff --check` passed. Final status showed intentional source/doc
changes plus tracked Graphify updates, and one unrelated untracked file:
`docs/2026-06-23-sidabari4loop-analysis.md`.
