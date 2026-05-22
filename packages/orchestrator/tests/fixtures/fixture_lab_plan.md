# Fixture Lab Demo Plan

## Task 1: Refine local helpers in orchestrator

**Files:**

- Modify: `packages/orchestrator/src/foo.ts`
- Modify: `packages/orchestrator/tests/foo.test.ts`

- [ ] **Step 1: Add unit test**
- [ ] **Step 2: Implement helper**

Run:

```bash
bun test packages/orchestrator/tests/foo.test.ts
```

## Task 2: Wire CLI surface to orchestrator helper

**Files:**

- Modify: `apps/cli/src/index.ts`
- Modify: `apps/cli/tests/cli.test.ts`
- Modify: `packages/orchestrator/src/foo.ts`

- [ ] **Step 1: Expose the helper through CLI**

Run:

```bash
bun test apps/cli/tests/cli.test.ts
```

## Task 3: Update README and ship printf verify

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Update README**

Run:

```bash
printf done
```
