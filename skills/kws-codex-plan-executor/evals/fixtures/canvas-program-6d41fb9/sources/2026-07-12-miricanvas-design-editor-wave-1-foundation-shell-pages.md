# Miricanvas Design Editor Wave 1 Foundation, Shell, and Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish Schema V3 and transient interaction foundations, then replace the current unsupported shell and video-oriented bottom UI with functional size, navigation, and page-management behavior.

**Architecture:** Extend the current document and command model without replacing history, persistence, canvas, or page preview foundations. Keep the editor working after every task; move persisted table selection into the store before removing it from the canonical table schema.

**Tech Stack:** TypeScript, Zustand, React, Konva, Vitest, Testing Library, Playwright.

## Global Constraints

- Preserve legacy page duration and animation data but render no duration, animation, timeline, or playback UI.
- Use one uniform canvas-resize scale and center content; never distort axes independently.
- Keep `StaticPageStage` as the real page-thumbnail renderer.
- Final navigation is Templates, Elements, Text, Photos, Upload, Background, Charts with no disabled filler.
- Every final size or page mutation is one history entry.
- Wave 1 may not add catalog, layer, inspector, or full table features owned by later waves.

---

### Task 1: Introduce additive Schema V3 fields and safe migration

**Files:**
- Modify: `src/domain/document/types.ts`
- Modify: `src/domain/document/factory.ts`
- Modify: `src/domain/document/migrations.ts`
- Modify: `src/domain/document/validation.ts`
- Test: `src/domain/document/__tests__/document.test.ts`

**Interfaces:**
- Produces: `CURRENT_SCHEMA_VERSION = 3`
- Produces: `CanvasPrintMetadata`, `ElementLink`, `TableMerge`
- Produces: `ElementBase.contentLocked`, `ElementBase.link`, `TableElement.merges`
- Preserves temporarily: `TableElement.selectedCellRange` until Task 2

- [ ] **Step 1: Write the V2-to-V3 migration RED**

Add a test that proves new fields are initialized, legacy timing remains readable, and the source is not mutated:

```ts
it("migrates schema v2 into additive schema v3 without losing legacy page timing", () => {
  const source = createBlankDocument();
  source.schemaVersion = 2;
  const page = source.pages[0];
  page.durationMs = 4700;
  page.animation = { kind: "slide" };
  const table = createTableElement({ id: "table-v2" });
  page.elements.push(table);
  const snapshot = structuredClone(source);

  const migrated = migrateDocument(source);

  expect(source).toEqual(snapshot);
  expect(migrated.schemaVersion).toBe(3);
  expect(migrated.canvas.print).toEqual({ presetId: null, widthMm: null, heightMm: null, dpi: 96 });
  expect(migrated.pages[0]).toMatchObject({ durationMs: 4700, animation: { kind: "slide" } });
  expect(migrated.pages[0].elements[0]).toMatchObject({
    contentLocked: false,
    link: null,
    merges: [],
  });
});
```

- [ ] **Step 2: Run the migration RED**

Run: `npm test -- src/domain/document/__tests__/document.test.ts`

Expected: FAIL because schema version 3 and the additive fields do not exist.

- [ ] **Step 3: Add the exact V3 types**

Add these declarations and fields:

```ts
export const CURRENT_SCHEMA_VERSION = 3;

export type CanvasPrintMetadata = {
  presetId: string | null;
  widthMm: number | null;
  heightMm: number | null;
  dpi: number;
};

export type ElementLink = {
  href: string;
};

export type TableMerge = {
  id: string;
  startRow: number;
  startColumn: number;
  rowSpan: number;
  columnSpan: number;
};
```

Extend `CanvasSpec` with `print: CanvasPrintMetadata`, extend `ElementBase` with `contentLocked: boolean` and `link: ElementLink | null`, and extend `TableElement` with `merges: TableMerge[]`. Keep the existing page timing fields as legacy-compatible data.

- [ ] **Step 4: Initialize V3 factories**

Use these exact defaults:

```ts
const base: ElementBase = {
  id,
  type,
  x,
  y,
  width,
  height,
  rotation,
  opacity,
  locked,
  visible,
  zIndex,
  contentLocked: false,
  link: null,
};
```

`createBlankDocument` creates:

```ts
print: { presetId: null, widthMm: null, heightMm: null, dpi: 96 }
```

`createTableElement` creates `merges: []`.

- [ ] **Step 5: Implement `migrateV2ToV3` and validation**

Add the migration:

```ts
const migrateV2ToV3: DocumentMigration = {
  fromVersion: 2,
  toVersion: 3,
  migrate(raw) {
    const document = structuredClone(raw) as DesignDocument;
    return {
      ...document,
      schemaVersion: 3,
      canvas: {
        ...document.canvas,
        print: document.canvas.print ?? { presetId: null, widthMm: null, heightMm: null, dpi: 96 },
      },
      pages: document.pages.map((page) => ({
        ...page,
        elements: page.elements.map((element) => ({
          ...element,
          contentLocked: element.contentLocked ?? false,
          link: element.link ?? null,
          ...(element.type === "table" ? { merges: element.merges ?? [] } : {}),
        })),
      })),
    };
  },
};
```

Register it after `migrateV1ToV2`. Validation requires valid print metadata, booleans, links, and non-overlapping positive table merge rectangles.

- [ ] **Step 6: Run document tests and affected type checks**

Run: `npm test -- src/domain/document/__tests__/document.test.ts src/domain/editor/__tests__/reducer.test.ts`

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/domain/document
git commit -m "feat: introduce editor document schema v3"
```

---

### Task 2: Move table selection out of persisted documents

**Files:**
- Modify: `src/domain/document/types.ts`
- Modify: `src/domain/document/factory.ts`
- Modify: `src/domain/document/migrations.ts`
- Modify: `src/domain/document/validation.ts`
- Modify: `src/domain/editor/commands.ts`
- Modify: `src/domain/editor/reducer.ts`
- Modify: `src/editor/store/editorStore.ts`
- Modify: `src/editor/canvas/CanvasStage.tsx`
- Modify: `src/editor/canvas/renderers/TableElementRenderer.tsx`
- Modify: `src/editor/inspectors/TableInspector.tsx`
- Test: `src/editor/store/__tests__/editorStore.test.ts`
- Test: `src/editor/canvas/__tests__/canvasInteractions.test.tsx`
- Test: `src/domain/document/__tests__/document.test.ts`

**Interfaces:**
- Produces: `TableCellCoordinate`, `TableSelection`
- Produces: `EditorState.tableSelection`, `setTableSelection(selection)`
- Produces: `TableElementRendererInteraction.selection`
- Removes: persisted `TableElement.selectedCellRange` and `table.selection.set` command

- [ ] **Step 1: Write store and serialization RED tests**

```ts
it("keeps table cell selection transient across history and serialization", () => {
  const table = createTableElement({ id: "transient-table" });
  const document = createBlankDocument();
  document.pages[0].elements = [table];
  useEditorStore.getState().loadDocument(document);

  useEditorStore.getState().setTableSelection({
    kind: "range",
    tableId: table.id,
    anchor: { row: 0, column: 0 },
    focus: { row: 1, column: 1 },
  });

  expect(useEditorStore.getState().tableSelection?.kind).toBe("range");
  expect(JSON.stringify(useEditorStore.getState().history.present)).not.toContain("selectedCellRange");
  expect(useEditorStore.getState().history.past).toHaveLength(0);
});
```

- [ ] **Step 2: Run the transient-selection RED**

Run: `npm test -- src/editor/store/__tests__/editorStore.test.ts src/editor/canvas/__tests__/canvasInteractions.test.tsx`

Expected: FAIL because the store has no transient table selection.

- [ ] **Step 3: Define the exact transient selection API**

```ts
export type TableCellCoordinate = { row: number; column: number };

export type TableSelection =
  | { kind: "cell"; tableId: string; anchor: TableCellCoordinate; focus: TableCellCoordinate }
  | { kind: "range"; tableId: string; anchor: TableCellCoordinate; focus: TableCellCoordinate };
```

Add `tableSelection: TableSelection | null` and `setTableSelection(tableSelection: TableSelection | null): void` to `EditorState`. Clear it on page change, document load, selecting a non-table, deleting the table, and undo or redo that invalidates its coordinates.

- [ ] **Step 4: Pass selection into the renderer**

Change the interaction type to:

```ts
export type TableElementRendererInteraction = {
  selection?: TableSelection | null;
  showSelection?: boolean;
  onCellClick?(cellId: string, modifiers: { button: number; shiftKey: boolean }): void;
  onCellDoubleClick?(cellId: string, modifiers: { button: number }): void;
};
```

Compute the overlay from `selection.anchor` and `selection.focus` only when `selection.tableId === element.id`.

- [ ] **Step 5: Remove persisted selection mutation**

Remove `table.selection.set` from `EditorCommand` and reducer branches. `CanvasStage` and `TableInspector` call `setTableSelection`. Remove `selectedCellRange` from `TableElement`, factory output, validation, migration output, and serialization assertions.

- [ ] **Step 6: Run focused and affected tests**

Run: `npm test -- src/domain/document/__tests__/document.test.ts src/domain/editor/__tests__/reducer.test.ts src/editor/store/__tests__/editorStore.test.ts src/editor/canvas/__tests__/canvasInteractions.test.tsx src/editor/panels/__tests__/elementsPanel.test.tsx`

Expected: PASS with selection assertions moved from document state to store state.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/domain src/editor/store src/editor/canvas src/editor/inspectors/TableInspector.tsx
git commit -m "refactor: keep table selection transient"
```

---

### Task 3: Add uniform document canvas resize commands

**Files:**
- Modify: `src/domain/editor/commands.ts`
- Modify: `src/domain/editor/reducer.ts`
- Modify: `src/domain/editor/geometry.ts`
- Test: `src/domain/editor/__tests__/geometry.test.ts`
- Test: `src/domain/editor/__tests__/reducer.test.ts`

**Interfaces:**
- Produces: `CanvasResizeInput`
- Produces: `resizeDocumentCanvas(document, input): DesignDocument`
- Produces command: `document.canvas.resize`

- [ ] **Step 1: Write geometry RED tests for uniform fit and centering**

```ts
it("uniformly scales and centers all page elements without distortion", () => {
  const document = createBlankDocument();
  document.canvas = { ...document.canvas, width: 1000, height: 1000 };
  document.pages[0].elements = [createShapeElement({ x: 100, y: 200, width: 400, height: 200 })];

  const resized = resizeDocumentCanvas(document, {
    width: 1600,
    height: 900,
    print: { presetId: null, widthMm: null, heightMm: null, dpi: 96 },
  });

  const shape = resized.pages[0].elements[0];
  expect(shape).toMatchObject({ x: 440, y: 180, width: 360, height: 180 });
  expect(shape.width / shape.height).toBe(2);
});
```

The expected scale is `min(1600/1000, 900/1000) = 0.9`; the horizontal content offset is `(1600 - 900) / 2 = 350`.

- [ ] **Step 2: Run the resize RED**

Run: `npm test -- src/domain/editor/__tests__/geometry.test.ts src/domain/editor/__tests__/reducer.test.ts`

Expected: FAIL because `resizeDocumentCanvas` and the command do not exist.

- [ ] **Step 3: Define input and command**

```ts
export type CanvasResizeInput = {
  width: number;
  height: number;
  print: CanvasPrintMetadata;
};
```

Add:

```ts
| { type: "document.canvas.resize"; input: CanvasResizeInput }
```

- [ ] **Step 4: Implement uniform affine resize**

The core calculation is:

```ts
const scale = Math.min(input.width / document.canvas.width, input.height / document.canvas.height);
const offsetX = (input.width - document.canvas.width * scale) / 2;
const offsetY = (input.height - document.canvas.height * scale) / 2;
```

Apply it to element x, y, width, height; line points; table rows and columns; and absolute crop presentation fields that depend on document geometry. Preserve element rotation and image source-space crop rectangles. Replace the canvas size and print metadata in the same returned document.

- [ ] **Step 5: Reject invalid sizes without history**

Tests cover zero, negative, non-finite, fractional pixel output, and an upper bound of 20,000 pixels per axis. Reducer invalid input throws before cloning or stamping.

- [ ] **Step 6: Run focused tests**

Run: `npm test -- src/domain/editor/__tests__/geometry.test.ts src/domain/editor/__tests__/reducer.test.ts src/editor/store/__tests__/editorStore.test.ts`

Expected: PASS and one undo restores the exact pre-resize document.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/domain/editor src/editor/store/__tests__/editorStore.test.ts
git commit -m "feat: resize design canvas uniformly"
```

---

### Task 4: Replace unsupported navigation and add the size chooser

**Files:**
- Create: `src/editor/components/size/SizeChooser.tsx`
- Create: `src/editor/components/size/printPresets.ts`
- Create: `src/editor/components/size/__tests__/SizeChooser.test.tsx`
- Create: `src/editor/panels/BackgroundPanel.tsx`
- Create: `src/editor/panels/__tests__/backgroundPanel.test.tsx`
- Modify: `src/editor/components/TopBar.tsx`
- Modify: `src/editor/components/LeftNavigation.tsx`
- Modify: `src/editor/store/editorStore.ts`
- Modify: `src/editor/components/AssetPanel.tsx`
- Modify: `src/editor/components/__tests__/editorShell.test.tsx`
- Modify: `app/globals.css`

**Interfaces:**
- Produces: `PRINT_PRESET_GROUPS`
- Produces: `SizeChooser({ open, onClose })`
- Extends: `LeftMenu` with `background`

- [ ] **Step 1: Write navigation and size chooser RED tests**

```tsx
it("renders only the seven functional design-editor navigation items", () => {
  render(<LeftNavigation />);
  expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(expect.arrayContaining([
    "템플릿", "요소", "텍스트", "사진", "업로드", "배경", "차트",
  ]));
  expect(screen.queryByText("프로젝트")).not.toBeInTheDocument();
  expect(screen.queryByText("AI 도구")).not.toBeInTheDocument();
  expect(screen.queryByText("동영상")).not.toBeInTheDocument();
});

it("applies a print preset through one resize command", async () => {
  render(<SizeChooser open onClose={() => undefined} />);
  await userEvent.click(screen.getByRole("button", { name: "A4 210 × 297mm" }));
  await userEvent.click(screen.getByRole("button", { name: "적용" }));
  expect(useEditorStore.getState().history.present.canvas.print).toMatchObject({ presetId: "a4", widthMm: 210, heightMm: 297 });
  expect(useEditorStore.getState().history.past).toHaveLength(1);
});

it("makes the background navigation functional in the same wave", async () => {
  render(<EditorShell adapter={adapter} />);
  await userEvent.click(screen.getByRole("button", { name: "배경" }));
  await userEvent.click(screen.getByRole("button", { name: "검정 배경" }));
  const state = useEditorStore.getState();
  const activePage = state.history.present.pages.find((page) => page.id === state.activePageId);
  expect(activePage?.background).toMatchObject({ kind: "solid", color: "#000000" });
  expect(useEditorStore.getState().history.past).toHaveLength(1);
});
```

- [ ] **Step 2: Run component RED tests**

Run: `npm test -- src/editor/components/size/__tests__/SizeChooser.test.tsx src/editor/components/__tests__/editorShell.test.tsx`

Expected: FAIL because the component and final navigation do not exist.

- [ ] **Step 3: Add print preset data**

`PRINT_PRESET_GROUPS` contains A0-A6, B0-B6, and named poster, flyer, card, sticker, and banner groups. Each item has `{ id, label, widthMm, heightMm, dpi }`. Convert millimeters to pixels with `Math.round(mm / 25.4 * dpi)` and retain that DPI in print metadata.

- [ ] **Step 4: Implement the dialog contract**

`SizeChooser` renders Search, Direct Input, Print Sizes, orientation swap, unit selection, and Apply. Direct input validates local drafts before dispatching:

```ts
dispatch({
  type: "document.canvas.resize",
  input: { width, height, print },
});
```

No All, Web, or Video tabs are rendered. Escape closes without dispatch.

- [ ] **Step 5: Make the top dimension label interactive**

Replace the dimension `<span>` with a button using `aria-expanded`, `aria-controls`, and focus restoration. The current canvas label remains exact `WIDTH×HEIGHT px`.

- [ ] **Step 6: Replace navigation data**

Use exactly:

```ts
const items: NavigationItem[] = [
  { id: "templates", label: "템플릿", icon: LayoutTemplate },
  { id: "elements", label: "요소", icon: Shapes },
  { id: "text", label: "텍스트", icon: Type },
  { id: "photos", label: "사진", icon: Image },
  { id: "upload", label: "업로드", icon: CloudUpload },
  { id: "background", label: "배경", icon: PaintBucket },
  { id: "charts", label: "차트", icon: ChartPie },
];
```

- [ ] **Step 7: Add a minimum functional background panel**

Provide a real Wave 1 slice: `BackgroundPanel` renders a small solid-color preset grid, a custom color input, and Clear. Each action updates only the active page through one existing page-background command and one undo step. Wave 3 extends this same panel with gradients, licensed photos, and uploads; it does not replace the contract.

- [ ] **Step 8: Run focused tests and 1440 containment assertions**

Run: `npm test -- src/editor/components/size/__tests__/SizeChooser.test.tsx src/editor/panels/__tests__/backgroundPanel.test.tsx src/editor/components/__tests__/editorShell.test.tsx`

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```bash
git add src/editor/components src/editor/store/editorStore.ts app/globals.css
git commit -m "feat: add design size and final navigation"
```

---

### Task 5: Split and simplify the design-only page strip

**Files:**
- Create: `src/editor/pages/PageCard.tsx`
- Create: `src/editor/pages/PageActionsMenu.tsx`
- Create: `src/editor/pages/PageStrip.tsx`
- Create: `src/editor/pages/DesignBottomControls.tsx`
- Modify: `src/editor/components/EditorShell.tsx`
- Delete: `src/editor/components/PageStrip.tsx`
- Modify: `src/editor/components/__tests__/pageStrip.test.tsx`
- Modify: `tests/e2e/editor.spec.ts`
- Modify: `app/globals.css`

**Interfaces:**
- Produces: `PageStrip({ adapter })`
- Produces: `PageActionsMenu({ pageId, anchor, onClose })`
- Produces: `DesignBottomControls()`
- Preserves: `StaticPageStage` thumbnail renderer

- [ ] **Step 1: Rewrite page-strip tests as design-only RED**

The test must assert:

```tsx
expect(screen.queryByRole("button", { name: "재생 시작" })).not.toBeInTheDocument();
expect(screen.queryByLabelText("페이지 시간")).not.toBeInTheDocument();
expect(screen.queryByLabelText("페이지 애니메이션")).not.toBeInTheDocument();
expect(screen.getByRole("button", { name: "페이지 1 더보기" })).toBeVisible();
expect(screen.getByRole("button", { name: "페이지 추가" })).toBeVisible();
expect(screen.getByText("디자인 에디터")).toBeVisible();
expect(screen.getByRole("button", { name: "레이어" })).toBeVisible();
```

Keep existing add, duplicate, delete, reorder, sole-page guard, focus-return, and real-preview assertions.

- [ ] **Step 2: Run the page RED**

Run: `npm test -- src/editor/components/__tests__/pageStrip.test.tsx`

Expected: FAIL because playback and timing UI still render and the split modules do not exist.

- [ ] **Step 3: Extract `PageCard` without changing behavior**

Move the existing `StaticPageStage`, number, selection button, draggable page container, and hover More button into `PageCard`. Keep the existing page IDs and adapter inputs; remove the duration badge from the thumbnail.

- [ ] **Step 4: Extract and reduce `PageActionsMenu`**

Render only Rename, Add, Duplicate, and Delete. Keep keyboard shortcuts Shift+Enter, Ctrl/Cmd+D, and Delete. Do not render the disabled Page Split row. Delete is disabled when page count is one.

- [ ] **Step 5: Implement `DesignBottomControls`**

Render the label and existing canvas controls plus a layer trigger interface reserved for Wave 2:

```tsx
<div className="design-bottom-controls" data-testid="bottom-controls">
  <span>디자인 에디터</span>
  <CanvasControls />
  <button type="button" aria-label="레이어" onClick={toggleLayerPanel}><Layers3 /></button>
  <button type="button" aria-label="사용법"><CircleHelp /></button>
</div>
```

Wave 1 adds `layerPanelOpen` and `toggleLayerPanel` store fields; Wave 2 provides the panel.

- [ ] **Step 6: Remove playback state and timing controls**

Delete `PlaybackSession`, timers, elapsed-state calculations, `PageSettings`, and related CSS. Keep legacy duration and animation values untouched in the document.

- [ ] **Step 7: Run focused component and browser tests**

Run: `npm test -- src/editor/components/__tests__/pageStrip.test.tsx src/editor/components/__tests__/editorShell.test.tsx src/editor/canvas/__tests__/staticPageStage.test.tsx`

Run: `npx playwright test tests/e2e/editor.spec.ts --project=parity-1920`

Expected: PASS; no playback, duration, animation, or disabled split UI exists.

- [ ] **Step 8: Commit Task 5 and update Graphify**

```bash
graphify update .
git add src/editor/pages src/editor/components/EditorShell.tsx src/editor/components/__tests__/pageStrip.test.tsx tests/e2e/editor.spec.ts app/globals.css
git rm src/editor/components/PageStrip.tsx
git commit -m "feat: simplify design page controls"
```

---

## Wave 1 Exit Gate

Run:

```bash
npm run lint
npm test -- src/domain/document src/domain/editor src/editor/store src/editor/components src/editor/canvas
npm run build
git diff --check
```

Expected: all commands exit 0. Manually verify the size chooser, final navigation, real page thumbnails, page More menu, and design-only bottom controls at 1920x960 and 1440x900 before starting Wave 2.
