# Memory Second Brain Implementation Plan

### Task 1: Add Memory Seed Command

**Files:**
- Modify: `package.json`
- Create: `scripts/memory/seed.mjs`

Run:

```bash
npm install
npm test -- --runInBand
npm run memory:validate
```

### Task 2: Add Memory Projection

**Files:**
- Modify: `src/memory/projector.ts`
- Modify: `src/memory/projector.test.ts`

Run:

```bash
npm run build
npm run validate
graphify update .
```
