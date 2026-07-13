# Miricanvas Design Editor Wave 3 Catalogs and Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execute only after Waves 1 and 2 pass their focused gates.

**Goal:** Replace synthetic cards and duplicated samples with licensed, searchable, editable catalogs whose thumbnails are rendered from the same source used by the canvas.

**Architecture:** Catalogs are immutable manifests. Factories convert catalog definitions into document elements, and preview components render the definitions or resolved assets without mutating editor state. Local assets carry license/source metadata; user uploads retain IndexedDB blob ownership. A stack-based panel navigator provides Miricanvas-style “More” depth while preserving search, scroll, and selection state.

**Tech Stack:** React 19, TypeScript, Zustand, react-konva/Konva, IndexedDB, Vitest/Testing Library, Playwright.

---

## Wave constraints

- Ship only assets whose license permits redistribution; record author, source URL, license name, and local path.
- Never scrape or copy Miricanvas proprietary templates, photos, icons, or fonts.
- Minimum catalog counts are contractual: 12 editable templates, 40 shapes, 40 lines, 20 icons, 20 photos, 20 fonts, 8 table styles, and 12 text styles.
- Every visible template thumbnail must be generated from the same editable `Page` definition applied to the document.
- Upload thumbnails must resolve the actual stored blob and must survive reload.
- Extend Schema V3 only with backward-compatible optional/defaulted fields; update migration repair and tests whenever a persisted field changes.
- “Similar,” recommendation, and AI entry points remain absent.

## Task 1: Establish catalog and license contracts

**Files:**
- Create: `src/editor/catalog/types.ts`
- Create: `src/editor/catalog/licenses.ts`
- Create: `src/editor/catalog/__tests__/catalogContracts.test.ts`
- Create: `scripts/validate-catalog-assets.mjs`
- Create: `scripts/validate-catalog-assets.test.mjs`
- Modify: `package.json`

- [ ] **Step 1: Write failing catalog-contract tests**

Define the required public contracts in the test before implementation:

```ts
export interface CatalogLicense {
  id: string;
  name: string;
  sourceUrl: string;
  author?: string;
  redistributionAllowed: true;
}

export interface CatalogItemBase {
  id: string;
  label: string;
  keywords: readonly string[];
  sectionId: string;
  licenseId?: string;
  sha256?: string;
}

export interface CatalogSection<T extends CatalogItemBase> {
  id: string;
  title: string;
  items: readonly T[];
}
```

Assert unique IDs, non-empty Korean labels/keywords, known license IDs, reachable local asset paths, matching SHA-256 values for redistributed files, and no remote runtime dependency for bundled assets.

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run: `npm test -- src/editor/catalog/__tests__/catalogContracts.test.ts`

Expected: FAIL because the catalog modules do not exist.

- [ ] **Step 3: Implement contracts and a reusable validator**

Implement `validateCatalogSections()` so every later manifest can reuse the same uniqueness, count, license, path, and SHA-256 checks. Implement the Node validation script to import built manifest data or parse a generated JSON inventory without booting the editor.

- [ ] **Step 4: Add the asset validation script**

Add:

```json
"validate:catalog-assets": "node --test scripts/validate-catalog-assets.test.mjs && node scripts/validate-catalog-assets.mjs"
```

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/catalog/__tests__/catalogContracts.test.ts && npm run validate:catalog-assets`

Expected: PASS with a summary that names every registered catalog and reports zero invalid assets.

```bash
git add package.json scripts/validate-catalog-assets.mjs scripts/validate-catalog-assets.test.mjs src/editor/catalog
git commit -m "feat: establish licensed catalog contracts"
```

## Task 2: Build data-driven shape, line, and icon catalogs

**Files:**
- Create: `src/editor/catalog/vectorDefinitions.ts`
- Create: `src/editor/catalog/__tests__/vectorDefinitions.test.ts`
- Modify: `src/domain/document/types.ts`
- Modify: `src/domain/document/factory.ts`
- Modify: `src/domain/document/migrations.ts`
- Modify: `src/domain/document/__tests__/document.test.ts`
- Modify: `src/editor/panels/elements/ShapeAssets.tsx`
- Modify: `src/editor/panels/elements/LineAssets.tsx`
- Modify: `src/editor/panels/elements/IconAssets.tsx`
- Modify: `src/editor/canvas/renderers/ShapeElementRenderer.tsx`
- Modify: `src/editor/canvas/renderers/LineElementRenderer.tsx`
- Modify: `src/editor/canvas/renderers/IconElementRenderer.tsx`
- Modify: `src/editor/panels/__tests__/elementsPanel.test.tsx`

- [ ] **Step 1: Lock the counts and representative geometry in failing tests**

Require these groups and exact minimums:

```ts
expect(shapeSections.find(byId('basic'))?.items).toHaveLength(20);
expect(shapeSections.find(byId('speech'))?.items).toHaveLength(20);
expect(lineSections.find(byId('basic'))?.items).toHaveLength(20);
expect(lineSections.find(byId('underline-pencil'))?.items).toHaveLength(20);
expect(iconSections.flatMap(section => section.items)).toHaveLength(20);
```

Also assert that a speech bubble has a closed path, a pencil stroke has a non-uniform path, and all view boxes contain their paths.

- [ ] **Step 2: Add stable definition references to the document model**

Add optional `definitionId` to shapes/icons and `definitionId` plus `strokeProfile` to lines. Repair missing or unknown definitions to existing legacy visuals. Keep old documents renderable.

- [ ] **Step 3: Implement manifest-driven factories and renderers**

Use a discriminated definition union:

```ts
type VectorDefinition =
  | { kind: 'shape'; path: string; viewBox: ViewBox; closed: true }
  | { kind: 'line'; points: readonly number[]; viewBox: ViewBox; closed: false }
  | { kind: 'icon'; path: string; viewBox: ViewBox; closed: boolean };
```

Render catalog cards and canvas elements from the same definition. Do not create one React component per asset.

- [ ] **Step 4: Test search and insertion**

Assert Korean/English keyword matching, section “More” navigation, stable insertion IDs, and that inserted geometry matches the selected thumbnail definition.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/catalog/__tests__/vectorDefinitions.test.ts src/editor/panels/__tests__/elementsPanel.test.tsx src/domain/document/__tests__/document.test.ts`

Expected: PASS with 40 shapes, 40 lines, and 20 icons discoverable and insertable.

```bash
git add src/domain/document src/editor/catalog src/editor/panels/elements src/editor/canvas/renderers
git commit -m "feat: add complete vector element catalogs"
```

## Task 3: Add copyright-safe fonts and text/table style catalogs

**Files:**
- Create: `public/assets/fonts/NOTICE.md`
- Create: `src/editor/catalog/fontManifest.ts`
- Create: `src/editor/catalog/textStyleCatalog.ts`
- Create: `src/editor/catalog/tableStyleCatalog.ts`
- Create: `src/editor/catalog/fontLoader.ts`
- Create: `src/editor/catalog/__tests__/fontCatalog.test.ts`
- Create: `src/editor/catalog/__tests__/styleCatalogs.test.ts`
- Modify: `src/editor/panels/TextPanel.tsx`
- Modify: `src/editor/panels/elements/TableAssets.tsx`
- Modify: `src/editor/export/ExportStageProvider.tsx`
- Modify: `src/editor/export/__tests__/ExportStageProvider.test.tsx`

- [ ] **Step 1: Write failing license, count, and load-deduplication tests**

Require 20 fonts with redistribution-safe license metadata, 12 text styles, and 8 table styles. Test that concurrent requests for the same font share one `FontFace.load()` promise and a failure falls back to the declared system stack.

- [ ] **Step 2: Add font files and notices**

Use SIL Open Font License, Apache-2.0, or equivalent redistribution-safe Korean/Latin families. Keep only the weights actually exposed by the editor and document each file in `NOTICE.md`.

- [ ] **Step 3: Implement lazy loading and export readiness**

Expose:

```ts
loadFont(fontId: string): Promise<FontLoadResult>
loadFontsUsedByPage(page: Page): Promise<FontLoadResult[]>
```

The canvas may show a fallback while loading, but export must await all fonts used by the exported page and surface a recoverable warning on fallback.

- [ ] **Step 4: Connect style cards to real element creation**

Text styles must create independently editable text elements. Table styles must create tables whose cell fills, borders, typography, and header configuration match the card preview.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/catalog/__tests__/fontCatalog.test.ts src/editor/catalog/__tests__/styleCatalogs.test.ts src/editor/export/__tests__/ExportStageProvider.test.tsx`

Expected: PASS; no duplicate font loads and exports wait for used fonts.

```bash
git add public/assets/fonts src/editor/catalog src/editor/panels/TextPanel.tsx src/editor/panels/elements/TableAssets.tsx src/editor/export
git commit -m "feat: add licensed fonts and style catalogs"
```

## Task 4: Replace photo and upload placeholders with resolved thumbnails

**Files:**
- Create: `public/assets/photos/NOTICE.md`
- Create: `src/editor/catalog/photoManifest.ts`
- Create: `src/editor/components/ResolvedAssetThumbnail.tsx`
- Create: `src/editor/components/__tests__/ResolvedAssetThumbnail.test.tsx`
- Modify: `src/editor/panels/PhotosPanel.tsx`
- Modify: `src/editor/panels/UploadPanel.tsx`
- Modify: `src/editor/panels/__tests__/primaryPanels.test.tsx`
- Modify: `src/editor/hooks/useResolvedAsset.ts`
- Modify: `src/editor/hooks/__tests__/useResolvedAsset.test.tsx`

- [ ] **Step 1: Write failing actual-thumbnail tests**

Assert 20 bundled photos with license data, real intrinsic aspect ratios, lazy image loading, and blob URL cleanup. For uploads, mock IndexedDB resolution and assert the card displays the stored image rather than a generic placeholder.

- [ ] **Step 2: Add the licensed photo inventory**

Store optimized local renditions and optional small preview renditions. Record original source and license in the manifest and `NOTICE.md`; do not hotlink third-party CDNs.

- [ ] **Step 3: Implement a shared resolved thumbnail**

The component accepts either a bundled URL or document asset ID, shows a skeleton/error state without layout shift, preserves aspect ratio, and revokes only blob URLs it owns.

- [ ] **Step 4: Connect insertion and persistence**

Photo insertion creates an image element referencing its bundled catalog source. Upload insertion references the persisted asset record and must render after save/reload. Do not duplicate binary data in the document JSON.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/components/__tests__/ResolvedAssetThumbnail.test.tsx src/editor/panels/__tests__/primaryPanels.test.tsx src/editor/hooks/__tests__/useResolvedAsset.test.tsx src/persistence/__tests__/indexedDbAdapter.test.ts`

Expected: PASS with real bundled and uploaded image previews.

```bash
git add public/assets/photos src/editor/catalog/photoManifest.ts src/editor/components/ResolvedAssetThumbnail.tsx src/editor/components/__tests__/ResolvedAssetThumbnail.test.tsx src/editor/panels/PhotosPanel.tsx src/editor/panels/UploadPanel.tsx src/editor/panels/__tests__/primaryPanels.test.tsx src/editor/hooks
git commit -m "feat: render real photo and upload thumbnails"
```

## Task 5: Ship 12 editable templates with source-derived previews

**Files:**
- Create: `src/editor/catalog/templateDocuments.ts`
- Create: `src/editor/catalog/templateCatalog.ts`
- Create: `src/editor/components/TemplatePreview.tsx`
- Create: `src/editor/components/__tests__/TemplatePreview.test.tsx`
- Modify: `src/editor/panels/TemplatesPanel.tsx`
- Modify: `src/editor/panels/__tests__/primaryPanels.test.tsx`
- Modify: `src/editor/canvas/StaticPageStage.tsx`
- Modify: `src/editor/store/editorStore.ts`
- Modify: `src/editor/store/__tests__/editorStore.test.ts`

- [ ] **Step 1: Write failing editability and preview-source tests**

For every template, assert a unique page structure, editable element IDs/types, valid asset/font references, bounds inside the page, and a preview built from that exact page object. Require at least 12 valid templates across multiple categories.

- [ ] **Step 2: Define templates as normalized page documents**

Each template owns a stable source page, not a flattened screenshot. Use licensed catalog photos/vectors/fonts only. Preview through a non-interactive `StaticPageStage` with an `IntersectionObserver` guard.

- [ ] **Step 3: Implement atomic template application**

Add a single undoable store command that deep-clones the source page, remaps page/element/group/asset references without collisions, preserves the destination page ID when replacing it, and rolls back completely on validation failure.

- [ ] **Step 4: Implement Miricanvas-like discovery**

Match the approved search field, category selector, recent/popular/category rows, “More” depth, hover actions, and loading states. Search label and keywords; preserve the query when returning from a nested list.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/components/__tests__/TemplatePreview.test.tsx src/editor/panels/__tests__/primaryPanels.test.tsx src/editor/store/__tests__/editorStore.test.ts`

Expected: PASS; all 12 cards are distinct and applying a template is one undo step.

```bash
git add src/editor/catalog/templateDocuments.ts src/editor/catalog/templateCatalog.ts src/editor/components/TemplatePreview.tsx src/editor/components/__tests__/TemplatePreview.test.tsx src/editor/panels/TemplatesPanel.tsx src/editor/panels/__tests__/primaryPanels.test.tsx src/editor/canvas/StaticPageStage.tsx src/editor/store
git commit -m "feat: add editable template catalog and previews"
```

## Task 6: Add stack-based panel depth and finish backgrounds

**Files:**
- Create: `src/editor/panels/panelNavigation.ts`
- Create: `src/editor/panels/ContextPanelShell.tsx`
- Create: `src/editor/panels/__tests__/panelNavigation.test.tsx`
- Modify: `src/editor/components/AssetPanel.tsx`
- Modify: `src/editor/panels/TemplatesPanel.tsx`
- Modify: `src/editor/panels/ElementsPanel.tsx`
- Modify: `src/editor/panels/TextPanel.tsx`
- Modify: `src/editor/panels/PhotosPanel.tsx`
- Modify: `src/editor/panels/UploadPanel.tsx`
- Modify: `src/editor/panels/BackgroundPanel.tsx`
- Modify: `src/editor/components/__tests__/editorShell.test.tsx`

- [ ] **Step 1: Write failing navigation-state tests**

Test root → section → item-list transitions, back/close behavior, keyboard focus restoration, per-depth scroll restoration, and query preservation. Closing the panel returns focus to its navigation button.

- [ ] **Step 2: Implement an explicit stack**

Use serializable view descriptors rather than nested component-local booleans:

```ts
type PanelRoute =
  | { kind: 'root'; menu: LeftMenu }
  | { kind: 'section'; menu: LeftMenu; sectionId: string; title: string }
  | { kind: 'search'; menu: LeftMenu; query: string };
```

Keep transient scroll/focus metadata outside the persisted document.

- [ ] **Step 3: Adopt the shell across every catalog panel**

All “More” links enter a full-width nested list with back and close buttons matching the approved screenshot hierarchy. Search results use the same card renderer and never open a second modal.

- [ ] **Step 4: Extend the Wave 1 background panel**

Keep solid color and clear behavior, then add gradient presets and licensed photo/upload backgrounds. Applying a background is undoable, targets only the active page, resolves assets after reload, and does not create an invisible image element.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/panels/__tests__/panelNavigation.test.tsx src/editor/panels/__tests__/primaryPanels.test.tsx src/editor/components/__tests__/editorShell.test.tsx`

Expected: PASS for all menu roots, nested lists, and background types.

```bash
git add src/editor/panels src/editor/components/AssetPanel.tsx src/editor/components/__tests__/editorShell.test.tsx
git commit -m "feat: add nested catalog navigation and backgrounds"
```

## Task 7: Verify catalog workflows without the complete E2E suite

**Files:**
- Create: `tests/e2e/catalogs.spec.ts`
- Modify: `tests/e2e/helpers/editor.ts`

- [ ] **Step 1: Add stable workflow helpers**

Add helpers based on roles and explicit test IDs for panel roots, section navigation, asset cards, upload completion, and template application. Avoid positional selectors.

- [ ] **Step 2: Cover the critical catalog workflows**

Test one representative from every catalog, a real upload thumbnail after reload, template preview/application/undo, search and “More” state restoration, and background persistence.

- [ ] **Step 3: Run the focused Wave 3 gate once**

Run: `npx playwright test tests/e2e/catalogs.spec.ts --project=usable-1440`

Expected: PASS once. Repeat only an individual failing workflow after diagnosing an actual flake.

- [ ] **Step 4: Run static gates and commit**

Run: `npm run lint && npm test && npm run build && npm run validate:catalog-assets`

Expected: all PASS.

```bash
git add tests/e2e/catalogs.spec.ts tests/e2e/helpers/editor.ts
git commit -m "test: cover catalog and asset workflows"
```
