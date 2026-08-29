# Plan authoring

Executable `waygent-task` plans. Runtime preflight rejects missing fields,
escaping claims, and bad dependencies before any provider runs.

See [operations](./waygent.md) and [verification](./verification.md).

## Task block

Every implementation task needs a fenced `yaml waygent-task` block with `id`,
`title`, `dependencies`, `file_claims`, `risk`, and `verify`.

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

- `owned` — create or overwrite
- `shared_append` — several tasks append (barrels like `src/index.ts`)
- `read_only` — read outside write scope
- `edit` — alias for `owned`

Use `verify_fail` only when the task's deliverable is an intentional RED
contract. Those commands must fail with a normal assertion, not a missing
binary or timeout.

```yaml waygent-task
id: task_1_lock_contract
title: Lock RED contract
dependencies: []
file_claims:
  - path: tests/contract.test.ts
    mode: owned
risk: medium
verify_fail:
  - bun test tests/contract.test.ts
```

## Verify must not rewrite tracked files

Verify runs in the task worktree. Unclaimed writes trip
`diff_scope_failed: changed_file_missing_provider_claim`.

Do not put these in `verify`:

- `bun install` / `npm install` / `pnpm install` (lockfile writes)
- `cargo build` that updates `Cargo.lock` unless that file is claimed
- formatters in write mode — use `--check`
- codegen — that belongs in implementation

If the run truly needs a new lockfile, claim it `owned` and generate it during
implementation.

Generated outputs (fixtures, snapshots, exporters) must be claimed:

```yaml
verify:
  - pnpm --dir front zod:export-fixtures
file_claims:
  - path: front/scripts/export-zod-fixtures.ts
    mode: owned
  - path: front/tests/unit/__fixtures__/zod-schemas/*.json
    mode: owned
```

Waygent may warn before dispatch. It will not widen claims for you.

## Superpowers plans

If a Superpowers-style plan has headings, file claims, and safe verify
commands, intake normalizes them into `yaml waygent-task` blocks. Install /
format / generate / git-mutation commands stay as implementation notes and
leave `verify`.

`Run:` plus `Expected: FAIL` becomes `verify_fail`. Mixed RED/GREEN tasks keep
the passing commands as verify.

Waygent asks for a decision only when the command is destructive, escapes the
workspace, writes unclaimed files, or leaves source-changing work with no
usable verify command.

## TypeScript

`bun test` does not fail on strict `tsc` diagnostics. Any task that writes
TypeScript should include `bun run typecheck`.

In plan snippets:

- no `.ts` suffix on relative imports
- unused params prefixed with `_`
- `arr[0]` is `T | undefined` (`noUncheckedIndexedAccess`)

## Claims and dependencies

- Growing re-export barrels: `shared_append`
- Test files belong to the task that writes them
- Do not claim `bun.lock`, `package.json`, or `tsconfig.json` unless that is
  the deliverable
- `dependencies` must name earlier task ids. Typos fail at preflight.

Sequential deps are the default. Fan-out only when the scheduler can actually
run the work in parallel.

## Checklist

- [ ] Every implementation task is a `yaml waygent-task` block
- [ ] Sequential work uses sequential dependencies
- [ ] Claims cover writes, tests, and any barrel append
- [ ] Paths named by `verify` are claimed
- [ ] `verify` has no install, write-formatter, or codegen
- [ ] TypeScript tasks include `bun run typecheck`
- [ ] No `.ts` import extensions in snippets
- [ ] `risk` matches blast radius
