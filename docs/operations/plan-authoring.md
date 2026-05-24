# Waygent Plan Authoring

Operational conventions for authoring executable `waygent-task` plans. These
rules are captured from real plan failures hit during SP-1 (design-contract)
delivery and are enforced (or surfaced) by the runtime; following them avoids
predictable predispatch / diff_scope / verification blockers.

See [waygent.md](./waygent.md) for runtime behavior and
[verification.md](./verification.md) for project-wide check gates.

## Task Block Shape

Every implementation task must live inside a fenced `yaml waygent-task` block
with at least `id`, `title`, `dependencies`, `file_claims`, `risk`, and
`verify`. Plan preflight rejects missing fields, escaping file claims, and
unresolved dependencies before any provider dispatch.

```yaml waygent-task
id: task_3
title: Add deterministic parser cache
dependencies: [task_2]
file_claims:
  - path: packages/design-contract/src/parse/cache.ts
    mode: owned
  - path: packages/design-contract/tests/cache.test.ts
    mode: owned
risk: low
verify:
  - bun run typecheck
  - bun test packages/design-contract/tests/cache.test.ts
```

`mode: edit` is accepted as a compatibility alias for `owned`. Use `owned`
when the worker creates or overwrites the file, `shared_append` when multiple
tasks append into the same file (e.g., `packages/.../src/index.ts`
re-exports), and `read_only` when the worker needs to read a file outside its
write scope.

## Verification Commands

Verification runs inside the task worktree after the worker reports a result.
The worktree is checkpointed by diffing against the source, so any file the
verify step mutates without a claim trips `diff_scope_failed:
changed_file_missing_provider_claim`.

### Verify Must Not Mutate Tracked Files

Never invoke commands that rewrite tracked files (lockfiles, generated
artifacts, formatted output) inside `verify`. Concretely:

- Do **not** run `bun install`, `npm install`, `pnpm install`, or any command
  that writes `bun.lock` / `package-lock.json` / `pnpm-lock.yaml`. Source
  dependency installation is the operator's job before the run, not the
  worker's job inside verify.
- Do **not** run `cargo build` that updates `Cargo.lock` in the verify step
  unless the file is claimed by the same task.
- Do **not** run formatters (`bun run format`, `prettier --write`, `cargo
  fmt`) inside verify. Use `--check` variants instead.
- Code generators (`bun run generate`, codegen scripts) must be in
  implementation, not verification.

If the run genuinely needs a regenerated lockfile, add the lockfile to the
task's `file_claims` with `mode: owned` *and* run the generating command
inside the implementation, not the verify step.

### Superpowers Plan Normalization

When a Superpowers-style implementation plan includes task headings, file
claims, and safe verification commands, Waygent normalizes it into executable
`yaml waygent-task` blocks during intake. Commands that install dependencies,
format files, generate code, update Graphify output, or mutate git state are
preserved as implementation instructions and removed from `verify`.

Waygent asks for a decision only when the command is destructive, escapes the
workspace, writes unclaimed files, or leaves a source-changing task without a
usable verification command.

### Verify Must Exercise Strict TypeScript

`bun test` transpiles TypeScript permissively — strict-mode diagnostics
(`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, unused locals) do
not fail a `bun test` run. For any task that writes TypeScript, include
`bun run typecheck` (the workspace-wide `tsc -b apps/* packages/*`) before
running the test command, or your code can ship type errors while still
reporting `verified`.

```yaml
verify:
  - bun run typecheck
  - bun test packages/<pkg>/tests
```

The typecheck gate is cheap (~3 s incremental) and is the only place where
strict diagnostics actually block a run.

## TypeScript Code Conventions

These match the repo tsconfig and apply to plan snippets the worker will
implement verbatim:

- **No `.ts` extensions on relative imports.** The repo tsconfig forbids
  them; `import x from "./foo.ts"` will fail typecheck. Write
  `import x from "./foo"` even if the plan author copied the extension from
  an editor autocomplete.
- **No unused parameters.** Strict mode catches unused destructured args.
  Prefix intentional unused params with `_` (e.g., `_provider`) or omit
  them.
- **No silent `unknown` indexing.** `noUncheckedIndexedAccess` is on, so
  `arr[0]` is `T | undefined`. Use `arr[0]!` only when invariants hold and
  the alternative would be runtime checks the code does not actually do.

## File Claim Patterns

- Re-export barrels (`packages/<pkg>/src/index.ts`) that grow across multiple
  tasks should use `mode: shared_append`. Mode `owned` would conflict the
  moment a second task touches the same barrel.
- Test files belong to the task that writes them. Claim the test file with
  `mode: owned` even when the implementation file is in a different task —
  the worker that writes the test owns the file.
- Do not claim `bun.lock`, `package.json`, `tsconfig.json`, or generated
  files unless the task's deliverable is a dependency or configuration
  change. The runtime treats unclaimed mutations to these as diff_scope
  failures and will not silently waive them.

## Dependency Patterns

`dependencies` must be a list of task ids that already exist earlier in the
plan. Plan preflight resolves these before run state is created — a typo
fails the plan instead of trapping the worker at scheduling time.

Sequential dependencies (`task_3 depends on task_2`) are the safe default
when one task's output is another task's input. Reserve fan-out dependencies
(many tasks depending on a shared prerequisite) for genuinely parallel work;
they only help when the safe-wave scheduler can actually run them
concurrently.

## Quick Authoring Checklist

Before submitting a plan to `waygent run`:

- [ ] Every implementation task lives in a fenced `yaml waygent-task` block.
- [ ] `dependencies` lists are sequential where work is sequential.
- [ ] `file_claims` cover every file the worker will write, including tests
      and any barrel re-export it appends.
- [ ] Every path named by a `verify` command is covered by some task's
      `file_claims`; native `waygent-task` plans fail preflight before
      dispatch when verification names an unclaimed file.
- [ ] `verify` does not invoke `bun install`, formatters in write mode, or
      code generators.
- [ ] `verify` includes `bun run typecheck` for any task writing
      TypeScript.
- [ ] Plan snippets do not use `.ts` import extensions.
- [ ] `risk` reflects worst-case blast radius — destructive verify or write
      paths must declare `high`.
