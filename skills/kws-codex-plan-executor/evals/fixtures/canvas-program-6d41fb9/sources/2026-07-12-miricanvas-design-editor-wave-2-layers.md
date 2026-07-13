# Miricanvas Design Editor Wave 2 Layers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a page-scoped right layer panel synchronized with the canvas and supporting rename, reorder, lock, visibility, grouping, duplication, and deletion.

**Architecture:** Derive rows from the active page and existing z-order. Persist names and ordering through typed commands, keep panel and drag state transient, and reuse existing selection and element commands.

**Tech Stack:** TypeScript, Zustand, React, HTML drag and drop, Testing Library, Playwright.

## Global Constraints

- Frontmost element is the first row.
- Layers never replace the left inspector.
- Layers dock above 1600px and overlay at or below 1600px.
- Locked elements remain selectable for inspection and unlocking.
- Reorder and rename each create one history entry and have keyboard equivalents.

---

### Task 1: Add layer selectors and commands

**Files:**
- Create: `src/editor/layers/layerModel.ts`
- Create: `src/editor/layers/__tests__/layerModel.test.ts`
- Modify: `src/domain/editor/commands.ts`
- Modify: `src/domain/editor/reducer.ts`
- Test: `src/domain/editor/__tests__/reducer.test.ts`

**Interfaces:**
- Produces: `LayerRowModel`
- Produces: `getLayerRows(document, pageId): LayerRowModel[]`
- Produces commands: `element.rename`, `layer.reorder`

- [ ] **Step 1: Write selector and reorder RED tests**

```ts
it("returns front-to-back rows with fallback names", () => {
  const document = createBlankDocument();
  document.pages[0].elements = [
    createShapeElement({ id: "back", zIndex: 0 }),
    createTextElement({ id: "front", content: "레이어 제목", zIndex: 4 }),
  ];
  expect(getLayerRows(document, document.pages[0].id)).toEqual([
    expect.objectContaining({ elementId: "front", name: "레이어 제목" }),
    expect.objectContaining({ elementId: "back", name: "도형" }),
  ]);
});
```

- [ ] **Step 2: Run RED**

Run: `npm test -- src/editor/layers/__tests__/layerModel.test.ts src/domain/editor/__tests__/reducer.test.ts`

Expected: FAIL because the model and commands do not exist.

- [ ] **Step 3: Define the exact model**

```ts
export type LayerRowModel = {
  elementId: string;
  name: string;
  type: DesignElement["type"];
  zIndex: number;
  locked: boolean;
  visible: boolean;
  groupId: string | null;
  preview: { kind: "image"; assetId: string } | { kind: "text"; text: string } | { kind: "type"; color?: string };
};
```

Explicit `element.name` wins. Text uses 30 trimmed characters, image uses the asset name, and other rows use Korean type labels.

- [ ] **Step 4: Add command signatures and reducer behavior**

```ts
| { type: "element.rename"; elementId: string; name: string }
| { type: "layer.reorder"; pageId: string; elementId: string; targetIndex: number }
```

Rename removes empty names. Reorder converts the front-to-back target into the page's back-to-front element list and normalizes integer z-index values once.

- [ ] **Step 5: Run focused tests and commit**

Run: `npm test -- src/editor/layers/__tests__/layerModel.test.ts src/domain/editor/__tests__/reducer.test.ts src/editor/store/__tests__/editorStore.test.ts`

Expected: PASS including invalid-page and same-position no-ops.

Commit: `git add src/editor/layers src/domain/editor && git commit -m "feat: add layer model and commands"`

---

### Task 2: Add transient panel state

**Files:**
- Modify: `src/editor/store/editorStore.ts`
- Modify: `src/editor/store/__tests__/editorStore.test.ts`
- Modify: `src/editor/pages/DesignBottomControls.tsx`
- Test: `src/editor/pages/__tests__/DesignBottomControls.test.tsx`

**Interfaces:**
- Produces: `layerPanelOpen`, `setLayerPanelOpen(open)`, `toggleLayerPanel()`
- Produces: `layerDrag: { elementId: string; targetIndex: number } | null`

- [ ] **Step 1: Write transient-state RED**

```ts
it("keeps layers open while page changes clear incompatible selection", () => {
  useEditorStore.getState().setLayerPanelOpen(true);
  useEditorStore.getState().setActivePage("page-2");
  expect(useEditorStore.getState()).toMatchObject({ layerPanelOpen: true, selectedElementIds: [], tableSelection: null });
});
```

- [ ] **Step 2: Run RED**

Run: `npm test -- src/editor/store/__tests__/editorStore.test.ts`

Expected: FAIL because layer state does not exist.

- [ ] **Step 3: Implement state and trigger**

Initialize `layerPanelOpen: false`. The trigger uses `aria-expanded` and `aria-controls="layer-panel"`. Panel state is absent from history and persistence.

- [ ] **Step 4: Run tests and commit**

Run: `npm test -- src/editor/store/__tests__/editorStore.test.ts src/editor/pages/__tests__/DesignBottomControls.test.tsx`

Expected: PASS.

Commit: `git add src/editor/store src/editor/pages && git commit -m "feat: add layer panel state"`

---

### Task 3: Build panel, rows, previews, and actions

**Files:**
- Create: `src/editor/layers/LayerPanel.tsx`
- Create: `src/editor/layers/LayerRow.tsx`
- Create: `src/editor/layers/LayerPreview.tsx`
- Create: `src/editor/layers/__tests__/LayerPanel.test.tsx`
- Modify: `src/editor/components/EditorShell.tsx`
- Modify: `app/globals.css`

**Interfaces:**
- Produces: `LayerPanel()` with `id="layer-panel"`
- Consumes: `getLayerRows`, layer commands, and existing selection commands

- [ ] **Step 1: Write synchronized-panel RED**

```tsx
it("selects, renames, and locks a layer", async () => {
  render(<LayerPanel />);
  const row = screen.getByRole("option", { name: "레이어 제목 텍스트" });
  await userEvent.click(row);
  expect(useEditorStore.getState().selectedElementIds).toEqual(["title"]);
  const name = within(row).getByRole("textbox", { name: "레이어 이름" });
  await userEvent.clear(name);
  await userEvent.type(name, "새 제목{Enter}");
  expect(activeElement("title").name).toBe("새 제목");
  await userEvent.click(within(row).getByRole("button", { name: "잠금" }));
  expect(activeElement("title").locked).toBe(true);
});
```

- [ ] **Step 2: Run RED**

Run: `npm test -- src/editor/layers/__tests__/LayerPanel.test.tsx`

Expected: FAIL because layer UI does not exist.

- [ ] **Step 3: Implement previews and row semantics**

Images resolve a small real thumbnail. Text shows T plus a snippet. Other types use an icon and optional swatch. Rows are ARIA options in a multiselect listbox. Rename commits on Enter or blur and cancels on Escape.

- [ ] **Step 4: Implement actions and reorder**

Hover and focus reveal lock and visibility. Footer actions reuse duplicate, group, ungroup, lock, visibility, and delete. Pointer drag uses `application/x-canvas-layer-id`; Alt+ArrowUp and Alt+ArrowDown dispatch the same reorder command and announce position.

- [ ] **Step 5: Compose without replacing the inspector**

Render `<LayerPanel />` after the canvas when open. Do not change `hasSelection` or `InspectorPanel` routing.

- [ ] **Step 6: Run tests and commit**

Run: `npm test -- src/editor/layers src/editor/components/__tests__/editorShell.test.tsx`

Expected: PASS.

Commit: `git add src/editor/layers src/editor/components/EditorShell.tsx app/globals.css && git commit -m "feat: add page scoped layer panel"`

---

### Task 4: Prove responsive browser workflows

**Files:**
- Modify: `tests/e2e/editor.spec.ts`
- Modify: `tests/e2e/canvas.spec.ts`
- Modify: `tests/e2e/helpers/editor.ts`
- Modify: `app/globals.css`

**Interfaces:**
- Produces: `openLayers(page): Promise<Locator>`

- [ ] **Step 1: Add browser RED**

Open layers, select text, assert the text inspector, rename, reorder, lock, prove canvas transform is blocked, switch page, and assert the row set changes without closing layers.

- [ ] **Step 2: Add responsive CSS**

```css
@media (min-width: 1601px) {
  .editor-shell:has(.layer-panel) { grid-template-columns: 72px 360px minmax(0, 1fr) 360px; }
}
@media (max-width: 1600px) {
  .layer-panel { position: fixed; top: 64px; right: 0; bottom: 0; width: 360px; z-index: 30; }
}
```

- [ ] **Step 3: Run focused E2E**

Run: `npx playwright test tests/e2e/editor.spec.ts tests/e2e/canvas.spec.ts --project=usable-1440 --grep "layer"`

Expected: PASS in both projects with zero application console errors.

- [ ] **Step 4: Run regressions and commit**

Run: `npm run lint && npm test -- src/editor/layers src/editor/store src/editor/components && graphify update . && git diff --check`

Expected: all commands exit 0.

Commit: `git add tests/e2e src/editor app/globals.css && git commit -m "test: prove layer panel workflows"`

---

## Wave 2 Exit Gate

Verify page-specific rows, selection synchronization, rename, reorder, lock, visibility, group, duplicate, delete, page switching, focus restoration, responsive overlay, and zero console errors before Wave 3.
