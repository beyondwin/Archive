# Miricanvas Design Editor Wave 6 Integration and Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execute only after stages 1-11 in `2026-07-12-editable-project-files-program.md` and their focused gates pass.

**Goal:** Integrate the design-only editor and editable-project program, prove persistence/package/resource/template/sync/export/interaction behavior across the approved scope, replace obsolete evidence, enforce quality budgets, and finish with one clean-worktree full E2E run.

**Architecture:** The parity matrix is the traceability source from design requirement to automated or manual evidence. Focused unit/integration tests remain the primary regression layer; Playwright covers cross-boundary user workflows. Visual snapshots cover a finite state inventory at approved viewports. Final scripts orchestrate each expensive suite once and archive machine-readable evidence.

**Tech Stack:** Next.js 16, TypeScript 5, Vitest 3, Playwright 1.50, Node validation scripts, Graphify.

---

## Global Constraints

- No new feature scope unless an integration failure proves a missing approved requirement.
- Re-record snapshots only after reviewing the rendered change; never bulk-accept unexplained diffs.
- Run the complete E2E suite once in the final clean-worktree gate.
- A focused workflow may run three times only after a genuine flake is reproduced, root-caused, repaired, and documented.
- Do not report completion with skipped/expected failures, stale evidence, uncommitted source changes, or an out-of-date Graphify graph.
- Preserve legacy duration/animation data but prove no design-editor UI exposes playback, duration, or animation.
- Include `.canvasclone` all-element round trips, 200-operation reopen history, recovery, font/asset repair, user templates, local writer transfer, and deterministic server-fake scenarios in final traceability.
- Production backend deployment and real-time multi-user collaboration remain later Phase D/E work and cannot be implied by passing fake contracts.

## Task 1: Rebase the parity matrix on the approved design-only scope

**Files:**
- Modify: `scripts/parity-matrix.mjs`
- Modify: `scripts/parity-matrix.test.mjs`
- Modify: `scripts/miricanvas-reference-lock.json`
- Modify: `scripts/check-parity-matrix.mjs`
- Create: `docs/qa/design-editor-parity-matrix.md`

**Interfaces:**
- Consumes: approved parity spec, editable-project design, A1-C2 focused evidence, implementation owner paths.
- Produces: validated machine-readable matrix, human-readable matrix, scoped reference lock.

- [ ] **Step 1: Write failing scope and evidence-contract tests**

Require matrix rows for navigation, size chooser, pages, layers, template/photo/upload previews, catalog counts, nested panels, every inspector family, crop, backgrounds, table selection/structure/merge/clipboard, local persistence, `.canvasclone` import/export, history reopen, recovery, missing resources, user templates, local writer transfer, fake sync/catalog contracts, PNG/PDF export gates, keyboard, accessibility, responsive layout, and performance. Reject rows for AI, recommendation/similar content, video, playback, duration, animation UI, PPTX/DOCX, production server claims, or real-time collaboration.

- [ ] **Step 2: Define evidence types and ownership**

Each row must include requirement ID, user-visible behavior, implementation owner path, automated evidence path, optional manual screenshot state, supported viewport, and status. Ban generic evidence references such as a whole test directory.

- [ ] **Step 3: Rebase the reference lock**

Record only the approved screenshot/reference observations and the date inspected. Separate “visual reference” from “asset source” so the lock cannot be misread as permission to copy Miricanvas assets.

- [ ] **Step 4: Generate the human-readable matrix**

Have `check-parity-matrix.mjs` validate the machine-readable matrix and emit/update `docs/qa/design-editor-parity-matrix.md` with grouped coverage and explicit manual-only rows.

- [ ] **Step 5: Verify and commit**

Run: `node --test scripts/parity-matrix.test.mjs && node scripts/check-parity-matrix.mjs`

Expected: PASS with zero missing owner/evidence paths and zero excluded-scope rows.

```bash
git add scripts/parity-matrix.mjs scripts/parity-matrix.test.mjs scripts/miricanvas-reference-lock.json scripts/check-parity-matrix.mjs docs/qa/design-editor-parity-matrix.md
git commit -m "test: rebase design editor parity matrix"
```

## Task 2: Prove migration, project packages, recovery, resources, and export together

**Files:**
- Modify: `src/editor/components/__tests__/documentLoadSave.test.tsx`
- Modify: `src/editor/hooks/__tests__/useDocumentLoader.test.tsx`
- Modify: `src/editor/hooks/__tests__/useSaveCoordinator.test.tsx`
- Modify: `src/persistence/__tests__/indexedDbAdapter.test.ts`
- Modify: `src/editor/export/__tests__/exportService.test.tsx`
- Modify: `src/editor/export/__tests__/ExportStageProvider.test.tsx`
- Modify: `tests/e2e/persistence-export.spec.ts`
- Create: `src/test/fixtures/schemaV2Document.ts`
- Modify: `src/project/package/__tests__/roundTrip.test.ts`
- Modify: `src/project/security/__tests__/maliciousPackages.test.ts`
- Modify: `tests/e2e/project-file-roundtrip.spec.ts`
- Modify: `tests/e2e/project-repair.spec.ts`
- Modify: `tests/e2e/project-local-recovery.spec.ts`
- Modify: `tests/e2e/editable-templates.spec.ts`
- Modify: `tests/e2e/project-server-contracts.spec.ts`

**Interfaces:**
- Consumes: completed document migration, ProjectRepository, package/security codec, resource resolver, templates, sync/catalog fakes, PNG/PDF exporters.
- Produces: all-element lifecycle, recovery, repair, and output-gate integration evidence.

- [ ] **Step 1: Add a realistic V2 migration fixture**

Include multiple pages, groups, every legacy element type, a table with legacy persisted selection, image crop/effects, uploaded assets, duration/animation values, and intentionally omitted V3 fields. The fixture must be stable and human-readable.

- [ ] **Step 2: Test V2 → V3 → project save → reopen invariants**

Assert legacy timing data remains, table selection disappears, new defaults repair correctly, asset IDs remain resolvable, page/layer order remains stable, saving again is idempotent, and the reopened project retains its latest 200 ordinary operations plus checkpoint/named-version cursors.

- [ ] **Step 3: Reprove the complete native package boundary**

Round-trip every supported element family, exact user assets, legally embeddable fonts, 200 operations, automatic checkpoints, named versions, and template/profile metadata. Re-run zip-slip, duplicate-path, traversal, entry-count, compressed/uncompressed size, image-bomb, SVG sanitization, wrong-hash, cancellation, and unsupported-capability cases. Assert `document/current.json` opens independently when optional history/workspace data is corrupt.

- [ ] **Step 4: Test real export inputs and gates**

Export pages containing licensed fonts, bundled photos, uploaded photos, crop, image effects, vectors, chart, merged table, and page background. Await fonts/assets and fail with a clear recoverable error if resolution cannot complete. Ordinary PNG/PDF/publication stays blocked for required missing/wrong-hash resources; explicit degraded export writes a distinct filename and machine-readable report without mutating the project.

- [ ] **Step 5: Cover cross-session lifecycle and recovery**

Create/edit/save/reload and compare meaningful document state plus rendered markers. Simulate interrupted commit, quota failure, missing font/image, wrong hash, emergency export, checkpoint restore, named version, abandoned staging cleanup, local writer transfer, user-template application, and fake server conflict/retry. Confirm transient crop/table/layer UI state is not restored and no fallback is silently persisted.

- [ ] **Step 6: Run the focused proof and commit**

Run: `npm test -- src/editor/components/__tests__/documentLoadSave.test.tsx src/editor/hooks src/persistence src/editor/export src/project src/domain/template src/sync src/catalog/gateway`

Run: `npx playwright test tests/e2e/persistence-export.spec.ts tests/e2e/project-file-roundtrip.spec.ts tests/e2e/project-repair.spec.ts tests/e2e/project-local-recovery.spec.ts tests/e2e/editable-templates.spec.ts tests/e2e/project-server-contracts.spec.ts --project=usable-1440`

Expected: both PASS once.

```bash
git add src/test/fixtures/schemaV2Document.ts src/editor/components/__tests__/documentLoadSave.test.tsx src/editor/hooks src/persistence src/editor/export src/project/package/__tests__/roundTrip.test.ts src/project/security/__tests__/maliciousPackages.test.ts tests/e2e/persistence-export.spec.ts tests/e2e/project-file-roundtrip.spec.ts tests/e2e/project-repair.spec.ts tests/e2e/project-local-recovery.spec.ts tests/e2e/editable-templates.spec.ts tests/e2e/project-server-contracts.spec.ts
git commit -m "test: prove editable project lifecycle integrity"
```

## Task 3: Rebuild the visual-state inventory and responsive evidence

**Files:**
- Modify: `tests/e2e/visual-parity.spec.ts`
- Modify: `playwright.config.ts`
- Modify: `tests/e2e/helpers/editor.ts`
- Modify: `tests/e2e/visual-parity.spec.ts-snapshots/*`
- Create: `tests/e2e/project-browser-capabilities.spec.ts`
- Create: `docs/qa/design-editor-visual-states.md`

**Interfaces:**
- Consumes: completed editor UI, approved viewports, browser capability adapters.
- Produces: reviewed visual inventory and Chromium/Firefox/WebKit fallback evidence.

- [ ] **Step 1: Define a finite state inventory before screenshots**

Include: blank selection, template root/nested list, Elements sections, text Style/Font, image Properties/Effects/Crop, shape, line, icon, chart, table cell/range/row/column/all menus, page hover/More, layers docked, layers overlay, size chooser direct input/print, upload thumbnail, background, and sole-page delete guard.

- [ ] **Step 2: Assign viewports deliberately**

Keep 1920-wide parity and 1440 usable layouts; add one <=1600 viewport assertion for the overlay layer panel only if not already represented. Stabilize fonts/assets with explicit readiness markers rather than timeouts.

- [ ] **Step 3: Capture and review snapshots state by state**

Run each changed state by title while developing. Inspect every diff for layout, clipping, hover/focus, tooltip, and readable text. Update the snapshot only when it matches the approved design contract and record the reason in `design-editor-visual-states.md`.

- [ ] **Step 4: Verify keyboard and responsive layout in the same state inventory**

At each modal/popover/panel boundary, test focus entry, Escape/back, focus return, and no horizontal viewport overflow. Confirm the layer overlay does not cover the active selection without an available close action.

- [ ] **Step 5: Add narrow browser-capability projects**

Add Chromium, Firefox, and Playwright WebKit projects that run only `project-browser-capabilities.spec.ts`. Prove native picker availability detection, upload/download fallback, Web Locks fallback, BroadcastChannel fallback, persistent-storage denial, worker cancellation, import/save/reopen, and keyboard repair flow. Treat WebKit as an engine approximation; record a manual macOS Safari smoke result before making a Safari-specific support claim.

```ts
{
  name: "capability-chromium",
  testMatch: /project-browser-capabilities\.spec\.ts/,
  use: { ...devices["Desktop Chrome"] },
},
{
  name: "capability-firefox",
  testMatch: /project-browser-capabilities\.spec\.ts/,
  use: { ...devices["Desktop Firefox"] },
},
{
  name: "capability-webkit",
  testMatch: /project-browser-capabilities\.spec\.ts/,
  use: { ...devices["Desktop Safari"] },
},
```

Exclude the capability spec from the two layout projects so the final single Playwright invocation does not duplicate it.

```ts
// Add to parity-1920 and usable-1440.
testIgnore: /project-browser-capabilities\.spec\.ts/,
```

- [ ] **Step 6: Run the visual and capability specs once after review and commit**

Run: `npx playwright test tests/e2e/visual-parity.spec.ts --project=parity-1920 --project=usable-1440`

Run: `npx playwright test tests/e2e/project-browser-capabilities.spec.ts --project=capability-chromium --project=capability-firefox --project=capability-webkit`

Expected: both commands PASS once with zero unreviewed snapshot changes and all three automated browser engines represented.

```bash
git add tests/e2e/visual-parity.spec.ts tests/e2e/visual-parity.spec.ts-snapshots tests/e2e/project-browser-capabilities.spec.ts playwright.config.ts tests/e2e/helpers/editor.ts docs/qa/design-editor-visual-states.md
git commit -m "test: refresh design editor visual evidence"
```

## Task 4: Enforce accessibility and measured performance budgets

**Files:**
- Create: `tests/e2e/accessibility-performance.spec.ts`
- Create: `src/editor/performance/editorMetrics.ts`
- Create: `src/editor/performance/__tests__/editorMetrics.test.ts`
- Modify: `src/editor/components/__tests__/accessibilityContrast.test.ts`
- Modify: `vite.config.ts`
- Modify: `scripts/check-parity-matrix.mjs`
- Create: `docs/qa/design-editor-performance-budget.md`

**Interfaces:**
- Consumes: editor action instrumentation, reference S/stress L fixtures, accessibility contracts.
- Produces: enforced accessibility assertions, reproducible performance evidence, build budgets.

- [ ] **Step 1: Write budget tests before optimizing**

Define and document budgets for initial JS chunks, largest editor chunk, catalog panel interaction readiness, page switch, layer reorder, template application, and a 100-element canvas drag. Re-run B1 reference S (5 pages, 500 elements, 50 MiB resources, four fonts, 200 history entries) with first-page readiness ≤1.5 s, journal commit p95 ≤100 ms, and cached-template apply ≤500 ms. Re-run stress L (100 pages, 10,000 elements, 500 MiB resources, 20 fonts, 200 history entries) with lazy page/resource loading, progress visible ≤200 ms, and no codec-caused main-thread task >50 ms. Record hardware, browser, build mode, cold/warm cache, repetitions, p50/p95, and tolerances.

- [ ] **Step 2: Add lightweight measurement marks**

Instrument named editor actions with `performance.mark/measure` behind a test/development-safe helper. Avoid production console noise and do not collect user content.

- [ ] **Step 3: Audit accessibility across dynamic controls**

Test accessible names, tooltip parity, tab order, focus traps/return, selected/expanded states, disabled reasons, contrast, keyboard alternatives for drag/resize, and reduced-motion behavior. Treat serious automated violations as failures.

- [ ] **Step 4: Optimize only measured failures**

First prefer code splitting for heavy catalogs, lazy preview mounting, memoized immutable selectors, and Konva redraw containment. Do not add thumbnail/cache systems unless profiling identifies them as the bottleneck. Add a regression assertion for every accepted optimization.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/performance src/editor/components/__tests__/accessibilityContrast.test.ts`

Run: `npx playwright test tests/e2e/accessibility-performance.spec.ts tests/e2e/project-package-worker.spec.ts --project=usable-1440`

Run: `npm run build`

Expected: PASS once and every documented budget is within tolerance.

```bash
git add tests/e2e/accessibility-performance.spec.ts src/editor/performance src/editor/components/__tests__/accessibilityContrast.test.ts vite.config.ts scripts/check-parity-matrix.mjs docs/qa/design-editor-performance-budget.md
git commit -m "test: enforce editor accessibility and performance budgets"
```

## Task 5: Simplify final validation to one expensive E2E pass

**Files:**
- Modify: `package.json`
- Modify: `scripts/final-parity-gate.mjs`
- Modify: `scripts/final-parity-gate.test.mjs`
- Modify: `scripts/compare-parity-evidence.mjs`
- Modify: `scripts/compare-parity-evidence.test.mjs`
- Create: `scripts/focused-flake-proof.mjs`
- Create: `scripts/focused-flake-proof.test.mjs`

**Interfaces:**
- Consumes: all static validators, focused/full Playwright scripts, evidence manifests.
- Produces: `validate:static`, `validate:e2e`, `validate:final`, and focused-only flake proofing.

- [ ] **Step 1: Write failing orchestration tests**

Assert the final gate invokes lint, unit tests, build, catalog asset validation, editable-project contract validation, parity matrix validation, fixture freshness, visual evidence comparison, and exactly one complete Playwright invocation. Reject configurations that call the full suite through nested scripts or preserve the old three-run artifact convention.

- [ ] **Step 2: Make evidence comparison run-count agnostic**

Compare required projects/states/results, not `run-1/run-2/run-3` filenames. Preserve useful timestamps, commit SHA, environment, and failure attachments.

- [ ] **Step 3: Add a narrow flake-proof utility**

Require an explicit spec path or exact test title plus a root-cause note. The utility may repeat only that focused workflow three times; reject directories, wildcard-all, and an empty selector.

- [ ] **Step 4: Define scripts with no duplicated expensive work**

Recommended shape:

```json
"validate:static": "npm run lint && npm test && npm run build && npm run validate:catalog-assets && npm run test:parity-contract && npm run test:parity-final-contract && node scripts/check-parity-matrix.mjs",
"validate:e2e": "playwright test",
"validate:final": "npm run validate:static && npm run validate:e2e && node scripts/final-parity-gate.mjs"
```

`final-parity-gate.mjs` validates evidence produced by the preceding commands; it must not launch Playwright again.

- [ ] **Step 5: Verify orchestration and commit**

Run: `node --test scripts/final-parity-gate.test.mjs scripts/compare-parity-evidence.test.mjs scripts/focused-flake-proof.test.mjs`

Expected: PASS and the spy reports one full E2E invocation.

```bash
git add package.json scripts/final-parity-gate.mjs scripts/final-parity-gate.test.mjs scripts/compare-parity-evidence.mjs scripts/compare-parity-evidence.test.mjs scripts/focused-flake-proof.mjs scripts/focused-flake-proof.test.mjs
git commit -m "chore: make final parity validation efficient"
```

## Task 6: Run the single final gate and close traceability

**Files:**
- Modify only if evidence proves a defect: implementation/test files owned by Waves 1-5
- Modify: `docs/qa/design-editor-parity-matrix.md`
- Modify: `docs/qa/design-editor-visual-states.md`
- Modify: `docs/qa/design-editor-performance-budget.md`
- Refresh (gitignored evidence): `graphify-out/*`

**Interfaces:**
- Consumes: complete stages 1-11, Task 1-5 validators, reviewed manual states.
- Produces: final evidence closure, limitations/support boundary, completion handoff.

- [ ] **Step 1: Confirm a clean source baseline**

Run: `git status --short && git diff --check`

Expected: only intentional evidence/doc changes are present; no unexplained source modifications or whitespace errors.

- [ ] **Step 2: Run the complete final gate exactly once**

Run: `npm run validate:final`

Expected: lint, unit/integration tests, build, asset/license validation, editable-project contract/fixture validation, matrix validation, and the complete Playwright suite all PASS; the complete E2E suite appears once in the command trace.

If it fails, fix the root cause and run the smallest responsible test first. Re-run `validate:final` only when the fix can affect another boundary or when a successful final artifact is required; do not manufacture three green runs.

- [ ] **Step 3: Perform the final manual blind-spot audit**

Check the approved screenshots and reference observations against the running editor: hover-only actions, focus return, sole-page deletion, overlay/docked layers, nested panel return state, real thumbnails, crop confirm/cancel, locked elements, table selection kinds, and absence of excluded features. Also inspect missing-font glyph warnings, prohibited-embedding behavior, same-name/wrong-hash assets, degraded-export filename/report, corrupt optional history with valid current document, quota/emergency export, writer transfer, user-template privacy cleanup, unpublishing after download, offline cache, and conflict-copy labels. Record manual-only evidence and remaining limitations honestly; include a real macOS Safari smoke result if Safari support is claimed.

- [ ] **Step 4: Refresh Graphify after all code changes**

Run: `graphify update .`

Expected: PASS and the local, gitignored `graphify-out/` reflects the final implementation graph.

- [ ] **Step 5: Recheck clean state and commit closure evidence**

Run: `git diff --check && git status --short`

Expected: only reviewed tracked evidence changes remain; refreshed `graphify-out/` is intentionally absent from Git status because the repository ignores it.

```bash
git add docs/qa
git commit -m "docs: close design editor parity evidence"
```

- [ ] **Step 6: Report evidence, not a blanket clone claim**

The final handoff must list the commands and results, implemented scope, excluded scope, local-only versus fake-server boundaries, automated browser engines, manual-only checks, known limitations, and the final commit range. Describe the result as approved design-editor and editable-project parity for the documented scope, not an unrestricted clone of Miricanvas or a production collaboration/backend claim.
