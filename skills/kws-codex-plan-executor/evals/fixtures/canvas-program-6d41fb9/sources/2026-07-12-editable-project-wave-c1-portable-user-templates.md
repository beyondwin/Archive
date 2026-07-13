# Editable Project Wave C1 Portable and User Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the 12 distinct editable built-in templates into portable, multi-page, resource-safe sources and let users save clean whole-project, selected-page, and page-fragment templates.

**Architecture:** Existing Wave 3 template documents remain the built-in source catalog. A domain `TemplateSource` normalizes built-in, local-user, cached-server, and page-fragment inputs; `TemplateApplicationService` resolves all resources before one typed command; user-template creation strips history/private state and persists through a dedicated repository.

**Tech Stack:** TypeScript 5, React 19, Zustand 5, ProjectRepository, B1 package profiles, B2 ResourceResolver/File UX, IndexedDB/idb, Vitest, Testing Library, Playwright.

## Global Constraints

- Execute after existing Wave 3 and B2.
- Preserve every template object as editable pages/elements; previews derive from the same source.
- Home/gallery selection creates a new project. In-editor selection offers active-page replace, add page(s), or new project.
- Resolve and validate every required resource before application; failure changes nothing.
- Regenerate page, element, cell, merge, group, and resource-instance IDs without collisions.
- Apply one template or multi-page template as one undoable operation.
- Applied content is independent; origin template ID/version is provenance only and never live-updates existing projects.
- User templates strip history, recovery branches, deleted resources, workspace/session data, local paths, account IDs, and private metadata.
- Advanced placeholders, brand variables, paid asset entitlement, data binding, and public server publication are excluded from C1.
- Run `graphify update .` after the wave.

---

### Task 1: Normalize built-in, user, cached-server, and fragment template sources

**Files:**
- Create: `src/domain/template/types.ts`
- Create: `src/domain/template/normalizeTemplate.ts`
- Test: `src/domain/template/__tests__/normalizeTemplate.test.ts`
- Modify: `src/editor/catalog/templateDocuments.ts`
- Modify: `src/editor/catalog/templateCatalog.ts`

**Interfaces:**
- Consumes: Wave 3 template documents/catalog and project package manifests.
- Produces: `TemplateSource`, `TemplatePageSource`, `normalizeBuiltInTemplate`, `normalizePackagedTemplate`.

- [ ] **Step 1: Write source normalization RED tests**

```ts
it("normalizes every built-in template into distinct editable pages", () => {
  const sources = templateCatalog.map((entry) => normalizeBuiltInTemplate(entry));
  expect(sources).toHaveLength(12);
  expect(new Set(sources.map((source) => source.templateId))).toHaveLength(12);
  expect(sources.every((source) => source.pages.every((page) => page.elements.length > 0))).toBe(true);
});

it("rejects a packaged template with history or workspace state", () => {
  expect(() => normalizePackagedTemplate(packageWithPrivateProjectState())).toThrow("TEMPLATE_PRIVATE_STATE");
});
```

- [ ] **Step 2: Run normalization RED tests**

Run: `npm test -- src/domain/template/__tests__/normalizeTemplate.test.ts`

Expected: FAIL.

- [ ] **Step 3: Define the template source contract**

```ts
export type TemplateOrigin = "built-in" | "local-user" | "cached-server" | "page-fragment";

export type TemplateSource = {
  templateId: string;
  version: string;
  origin: TemplateOrigin;
  title: string;
  description: string;
  categoryIds: string[];
  pages: DesignPage[];
  resourceIndex: ProjectResourceIndex;
  resources: ResourceRecord[];
  previewPageIds: string[];
  provenance: { author: string | null; licenseIds: string[]; sourceUrl: string | null };
};
```

Normalization validates distinct IDs, page bounds, all element families, closed exact-hash resource bindings, no durable history, no workspace state, and supported required capabilities. Family/filename-only font or asset matches remain unresolved and block application until repair.

- [ ] **Step 4: Adapt Wave 3 catalog without duplicating template data**

`templateCatalog` points to `TemplateSource` IDs. `TemplatePreview` continues rendering the exact source page. Remove any remaining preset-to-sample-document remapping.

- [ ] **Step 5: Run template source and preview GREEN tests**

Run: `npm test -- src/domain/template/__tests__/normalizeTemplate.test.ts src/editor/components/__tests__/TemplatePreview.test.tsx src/editor/panels/__tests__/primaryPanels.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit template source contracts**

```bash
git add src/domain/template src/editor/catalog src/editor/components/TemplatePreview.tsx src/editor/components/__tests__/TemplatePreview.test.tsx
git commit -m "feat: normalize editable template sources"
```

---

### Task 2: Remap complete multi-page template identity and resource claims

**Files:**
- Create: `src/domain/template/remapTemplate.ts`
- Create: `src/domain/template/resourceClaims.ts`
- Test: `src/domain/template/__tests__/remapTemplate.test.ts`

**Interfaces:**
- Consumes: validated `TemplateSource`, destination `ProjectSnapshot`.
- Produces: `RemappedTemplate`, `remapTemplate(source, destination)`, collision-safe `ResourceClaim[]`.

- [ ] **Step 1: Write exhaustive ID and reference RED tests**

```ts
it("remaps pages, elements, groups, table cells, merges, and resource instances", () => {
  const result = remapTemplate(allElementTemplate(), destinationWithCollisions());
  expect(hasAnyIdCollision(result.pages, destinationWithCollisions().document.pages)).toBe(false);
  expect(validateClosedPageReferences(result.pages, result.resources)).toEqual([]);
  expect(result.idMap.get("template-group-1")).toMatch(/^group-/);
  expect(result.idMap.get("template-cell-1")).toMatch(/^cell-/);
});
```

- [ ] **Step 2: Run remapping RED tests**

Run: `npm test -- src/domain/template/__tests__/remapTemplate.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement two-pass ID allocation and rewrite**

Pass 1 allocates all page, element, group, row, column, cell, merge, and instance IDs. Pass 2 deep-clones and rewrites references. Shared immutable content hashes are not regenerated; project-level resource IDs/claims point to exact hashes.

```ts
export type ResourceClaim = {
  projectId: string;
  resourceId: string;
  contentHash: string;
  source: { kind: "template"; templateId: string; version: string };
};
```

- [ ] **Step 4: Validate remapped output**

Run full document validation after insertion into a cloned destination. Return no partial pages if one reference fails.

- [ ] **Step 5: Run remapping GREEN tests**

Run: `npm test -- src/domain/template/__tests__/remapTemplate.test.ts src/domain/document/__tests__/document.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit identity remapping**

```bash
git add src/domain/template/remapTemplate.ts src/domain/template/resourceClaims.ts src/domain/template/__tests__/remapTemplate.test.ts
git commit -m "feat: remap portable template identity"
```

---

### Task 3: Apply templates atomically in replace, add, and new-project modes

**Files:**
- Create: `src/domain/template/TemplateApplicationService.ts`
- Create: `src/domain/template/applicationTypes.ts`
- Test: `src/domain/template/__tests__/TemplateApplicationService.test.ts`
- Modify: `src/domain/editor/commands.ts`
- Modify: `src/domain/editor/reducer.ts`
- Modify: `src/domain/editor/commandMetadata.ts`
- Modify: `src/domain/editor/resourceEffects.ts`
- Modify: `src/domain/editor/__tests__/resourceEffects.test.ts`
- Modify: `src/editor/store/editorStore.ts`
- Modify: `src/editor/store/__tests__/editorStore.test.ts`

**Interfaces:**
- Consumes: `TemplateSource`, ResourceResolver, remapper, editor/repository.
- Produces: `TemplateApplicationMode`, `preflightTemplate`, `applyTemplate`; typed `template.apply` command.

- [ ] **Step 1: Write atomic mode RED tests**

```ts
it.each(["replace-active-page", "add-pages"] as const)("applies %s as one operation", async (mode) => {
  const before = fixtureProject();
  const service = fixtureApplicationService({ resourceResult: "ready" });
  const result = await service.apply(before, multiPageTemplate(), { mode, activePageId: "page-1" });
  expect(result.history.past).toHaveLength(1);
  expect(undoHistory(result.history).present).toEqual(before.document);
});

it("changes nothing when one required resource cannot resolve", async () => {
  const before = fixtureProject();
  await expect(blockedService().apply(before, template(), { mode: "add-pages" })).rejects.toThrow("TEMPLATE_RESOURCE_BLOCKED");
  expect(before).toEqual(fixtureProject());
});
```

- [ ] **Step 2: Run application RED tests**

Run: `npm test -- src/domain/template/__tests__/TemplateApplicationService.test.ts`

Expected: FAIL.

- [ ] **Step 3: Add the typed command**

```ts
export type TemplateApplyCommand = {
  type: "template.apply";
  mode: "replace-active-page" | "add-pages";
  activePageId: string;
  pages: DesignPage[];
  resourceIndex: ProjectResourceIndex;
  provenance: { templateId: string; version: string };
};
```

Reducer applies all pages to one cloned document and validates once. Replace preserves destination page position while using remapped content. Add inserts after the active page in source order. Extend A1 `resourceEffects` so every remapped page/element/cell locator receives its supplied exact binding. The editor store detects `template.apply`, validates/merges those bindings into `projectResources`, and writes that complete index into the same `DurableProjectMutation` as the page changes. A conflicting resource ID/hash aborts before dispatch. New-project mode creates a new `ProjectSnapshot` through the service rather than the reducer.

- [ ] **Step 4: Resolve all resources before dispatch**

`preflightTemplate` returns size, offline availability, missing resources, licenses, required capabilities, and page count. It validates/stores exact immutable bytes in local CAS before dispatch; those bytes remain unclaimed and garbage-collectable if the user cancels. `applyTemplate` proceeds only with `ready` resolution and commits pages plus exact resource bindings through one durable mutation.

- [ ] **Step 5: Run application/history regressions**

Run: `npm test -- src/domain/template src/domain/editor/__tests__/reducer.test.ts src/domain/editor/__tests__/history.test.ts src/domain/editor/__tests__/resourceEffects.test.ts src/editor/store/__tests__/editorStore.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit atomic template application**

```bash
git add src/domain/template src/domain/editor src/editor/store/editorStore.ts src/editor/store/__tests__/editorStore.test.ts
git commit -m "feat: apply editable templates atomically"
```

---

### Task 4: Sanitize projects and selected pages into user templates/fragments

**Files:**
- Create: `src/domain/template/createUserTemplate.ts`
- Create: `src/domain/template/templatePrivacy.ts`
- Test: `src/domain/template/__tests__/createUserTemplate.test.ts`

**Interfaces:**
- Consumes: `LoadedProject`, page IDs, metadata, B1 profile builders.
- Produces: clean `TemplateSource`, template bundle, page-fragment bundle, `TemplatePrivacyReport`.

- [ ] **Step 1: Write privacy RED tests**

```ts
it("removes history, deleted resources, session state, paths, and account IDs", () => {
  const result = createUserTemplate(projectWithPrivateState(), {
    pageIds: ["page-1"],
    metadata: { title: "내 템플릿", description: "설명", categoryIds: ["poster"] },
  });
  expect(result.privacy.removed).toEqual(expect.arrayContaining(["history", "recovery", "workspace", "local-path", "account-id", "unreachable-resource"]));
  expect(result.bundle.manifest.counts.history).toBe(0);
});

it("blocks a font or asset whose license forbids template redistribution", () => {
  expect(() => createUserTemplate(projectWithForbiddenLicense(), options())).toThrow("TEMPLATE_LICENSE_BLOCKED");
});
```

- [ ] **Step 2: Run user-template RED tests**

Run: `npm test -- src/domain/template/__tests__/createUserTemplate.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement privacy scrub and license closure**

Keep only selected page content, exact required resources, intended author/title/description/category/visibility metadata, license/provenance, and source-derived previews. Remove document title if not selected for publication, private notes, external file handle metadata, sync/outbox state, recovery diagnostics, and telemetry identifiers.

- [ ] **Step 4: Build both template and page-fragment profiles**

Use B1 profile builders. Page fragment must have no open cross-page group/resource reference. Template package uses `kind: template`; page fragment uses `kind: page-fragment`.

- [ ] **Step 5: Run privacy/profile GREEN tests**

Run: `npm test -- src/domain/template/__tests__/createUserTemplate.test.ts src/project/package/__tests__/profiles.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit user-template creation**

```bash
git add src/domain/template src/project/package
git commit -m "feat: create privacy-safe user templates"
```

---

### Task 5: Persist local user templates in a dedicated repository

**Files:**
- Create: `src/persistence/templateRepository.ts`
- Create: `src/persistence/indexedDbTemplateRepository.ts`
- Test: `src/persistence/__tests__/indexedDbTemplateRepository.test.ts`
- Modify: `src/persistence/indexedDbProjectRepository.ts`

**Interfaces:**
- Consumes: clean `TemplateSource` and package Blob/resource hashes.
- Produces: `TemplateRepository`, local IndexedDB v3 template/version indexes, list/get/save/delete.

- [ ] **Step 1: Write repository RED tests**

```ts
it("stores immutable local template versions and reuses content hashes", async () => {
  await repository.saveTemplate(templateVersion("template-1", "1", [resource("hash-a")]));
  await repository.saveTemplate(templateVersion("template-1", "2", [resource("hash-a")]));
  expect(await repository.listVersions("template-1")).toHaveLength(2);
  expect(await countResourceBytes("hash-a")).toBe(1);
});
```

- [ ] **Step 2: Run template repository RED tests**

Run: `npm test -- src/persistence/__tests__/indexedDbTemplateRepository.test.ts`

Expected: FAIL.

- [ ] **Step 3: Define repository and v3 stores**

```ts
export interface TemplateRepository {
  listTemplates(): Promise<TemplateSummary[]>;
  getTemplate(templateId: string, version?: string): Promise<TemplateSource>;
  saveTemplate(source: TemplateSource, bundle: Blob): Promise<void>;
  listVersions(templateId: string): Promise<TemplateVersionSummary[]>;
  deleteTemplate(templateId: string): Promise<void>;
}
```

Add `templates` and `templateVersions` stores without deleting v1/v2 stores. Reuse the project content-addressed resource store. Local template versions are immutable; a save with the same ID/version but different manifest hash fails.

- [ ] **Step 4: Run repository GREEN tests**

Run: `npm test -- src/persistence/__tests__/indexedDbTemplateRepository.test.ts src/persistence/__tests__/indexedDbProjectRepository.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit local template persistence**

```bash
git add src/persistence/templateRepository.ts src/persistence/indexedDbTemplateRepository.ts src/persistence/indexedDbProjectRepository.ts src/persistence/__tests__
git commit -m "feat: persist local editable templates"
```

---

### Task 6: Add application choices and Save as My Template UX

**Files:**
- Create: `src/editor/templates/TemplateApplyDialog.tsx`
- Create: `src/editor/templates/SaveUserTemplateDialog.tsx`
- Create: `src/editor/templates/UserTemplatesView.tsx`
- Test: `src/editor/templates/__tests__/TemplateApplyDialog.test.tsx`
- Test: `src/editor/templates/__tests__/SaveUserTemplateDialog.test.tsx`
- Modify: `src/editor/panels/TemplatesPanel.tsx`
- Modify: `src/editor/project/ProjectFileMenu.tsx`
- Modify: `app/globals.css`

**Interfaces:**
- Consumes: application service, local template repository, template creation service.
- Produces: new project/replace/add choices, multi-page summary, local user-template save/list/delete.

- [ ] **Step 1: Write UI RED tests**

```tsx
render(<TemplateApplyDialog template={multiPageTemplate()} context="editor" />);
expect(screen.getByRole("button", { name: "현재 페이지 교체" })).toBeEnabled();
expect(screen.getByRole("button", { name: "새 페이지 3개로 추가" })).toBeEnabled();
expect(screen.getByRole("button", { name: "새 디자인 만들기" })).toBeEnabled();
```

Save dialog tests cover whole document/selected pages, title/description/category, actual source preview, privacy report, blocked license, progress/cancel, and focus return.

- [ ] **Step 2: Run template UI RED tests**

Run: `npm test -- src/editor/templates`

Expected: FAIL.

- [ ] **Step 3: Implement application and download state UI**

Template cards show source, immutable version, page count, required download size, cached/offline state, and blocking resource/license messages. Application confirms one mode; do not use `window.confirm`.

- [ ] **Step 4: Implement user-template UX**

Enable the B2 file-menu action. Present the privacy removal inventory before save. Render user-template cards from the same source preview renderer and permit delete only after confirmation; deleting a template never deletes resources still referenced by projects or other versions.

- [ ] **Step 5: Run template component regressions**

Run: `npm test -- src/editor/templates src/editor/panels/__tests__/primaryPanels.test.tsx src/editor/components/__tests__/TemplatePreview.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit template UX**

```bash
git add src/editor/templates src/editor/panels/TemplatesPanel.tsx src/editor/project/ProjectFileMenu.tsx app/globals.css
git commit -m "feat: add portable user template workflows"
```

---

### Task 7: Prove built-in, user, page-fragment, multi-page, offline, and privacy flows

**Files:**
- Create: `tests/e2e/editable-templates.spec.ts`
- Modify: `tests/e2e/helpers/editor.ts`
- Modify: `package.json`

**Interfaces:**
- Consumes: complete C1 template system.
- Produces: `test:e2e:editable-templates` and focused evidence.

- [ ] **Step 1: Add representative template family workflows**

For every shipped template family, prove preview/source fingerprint, new-project creation, active-page replacement, multi-page addition, every representative element remains selectable/editable, one-step undo, save/reopen, package export/import, and no ID collision.

- [ ] **Step 2: Add user-template and fragment workflows**

Save whole project and selected pages; inspect privacy report; reopen from local template repository; export/import template package; apply fragment; prove removed history/private metadata and exact required resources only.

- [ ] **Step 3: Add offline and lifecycle workflows**

Fully cached template applies offline. Uncached template shows download-required. Deleting a local template does not break an existing project. A blocked-license resource prevents user-template save without changing source.

- [ ] **Step 4: Run the C1 focused gate**

Run:

```bash
npm run lint
npm test -- src/domain/template src/editor/templates src/persistence src/project/package
npx playwright test tests/e2e/editable-templates.spec.ts --project=parity-1920 --workers=1
git diff --check
npm run graphify:update
```

Expected: all commands PASS with zero console/unhandled errors.

- [ ] **Step 5: Commit C1 evidence**

```bash
git add src tests/e2e/editable-templates.spec.ts package.json package-lock.json
git commit -m "test: prove portable editable template workflows"
```
