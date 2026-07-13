# Miricanvas Design Editor Wave 5 Table Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execute after common inspector commands from Wave 4 pass.

**Goal:** Upgrade tables from a persisted single-range selection into a spreadsheet-like editor with cell/range/row/column/all selection, resizing, insert/delete, merge/unmerge, formatting, keyboard navigation, and clipboard behavior.

**Architecture:** Table content and merge regions remain persisted; selection and edit sessions are transient editor state. Pure table geometry/selection/structure helpers produce deterministic next models, then reducer commands commit one atomic history entry. The renderer maps pointer and keyboard interaction to those helpers, while the inspector derives available actions from selection kind.

**Tech Stack:** React 19, TypeScript, Zustand, react-konva/Konva, Clipboard API with in-memory fallback, Vitest/Testing Library, Playwright.

---

## Wave constraints

- Selection is never persisted and never restored from IndexedDB.
- Table-edit selection kinds are cell/range, row set, column set, and whole table; outer-border selection continues to use the existing element-selection model for geometry transforms.
- Merge uses spreadsheet semantics: the top-left value remains and other selected values are cleared; undo restores all cleared values. Unmerge does not resurrect them.
- Structural edits update merges, dimensions, styles, and transient selection atomically.
- A one-row/one-column table cannot delete its last row or column; unavailable actions are hidden or disabled with an explanation.
- Clipboard prefers `navigator.clipboard`, then falls back to an in-memory clipboard for permission-denied and test environments.
- No formula engine, multi-user collaboration, or XLSX import/export is added in this scope.

## Task 1: Define transient table selection and geometry

**Files:**
- Create: `src/domain/editor/tableSelection.ts`
- Create: `src/domain/editor/__tests__/tableSelection.test.ts`
- Modify: `src/editor/store/editorStore.ts`
- Modify: `src/editor/store/__tests__/editorStore.test.ts`
- Modify: `src/editor/canvas/CanvasStage.tsx`
- Modify: `src/editor/canvas/renderers/TableElementRenderer.tsx`

- [ ] **Step 1: Write failing selection-normalization tests**

Cover forward/reverse drag, shift extension, row/column header selection, additive row/column sets, select-all, bounds clamp after structure changes, page/element change clearing, and selection of a merged region.

- [ ] **Step 2: Define a discriminated transient selection**

Replace Wave 1's temporary `EditorState.tableSelection` with a richer `EditorState.tableEditSession`. This is a store-only migration; update every Wave 1 consumer in this task.

```ts
type TableSelection =
  | { kind: 'cells'; anchor: CellAddress; focus: CellAddress }
  | { kind: 'rows'; rows: number[] }
  | { kind: 'columns'; columns: number[] }
  | { kind: 'all' };

interface TableEditSession {
  elementId: string;
  selection: TableSelection;
  editingCell: CellAddress | null;
}
```

Store this beside other transient editor state. Ensure save snapshots and migration output cannot include it.

- [ ] **Step 3: Implement pure geometry helpers**

Add normalization, selected-cell enumeration, merged-region expansion, hit testing for cell/row header/column header/corner, and selection clamp helpers. Avoid renderer-specific coordinates in the model.

- [ ] **Step 4: Wire pointer selection to the store**

Single click selects a cell; drag selects a range; row/column/corner headers create their corresponding kinds; Shift extends where meaningful. Clicking the outer border exits cell editing and selects the table as an ordinary transformable element; clicking elsewhere exits the table edit session before selecting another element.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/domain/editor/__tests__/tableSelection.test.ts src/editor/store/__tests__/editorStore.test.ts src/editor/canvas/__tests__/canvasInteractions.test.tsx`

Expected: PASS and serialized documents contain no table selection.

```bash
git add src/domain/editor/tableSelection.ts src/domain/editor/__tests__/tableSelection.test.ts src/editor/store src/editor/canvas/CanvasStage.tsx src/editor/canvas/renderers/TableElementRenderer.tsx
git commit -m "feat: add spreadsheet table selection model"
```

## Task 2: Add merge regions with loss-explicit semantics

**Files:**
- Create: `src/domain/editor/tableMerge.ts`
- Create: `src/domain/editor/__tests__/tableMerge.test.ts`
- Modify: `src/domain/document/types.ts`
- Modify: `src/domain/document/migrations.ts`
- Modify: `src/domain/document/validation.ts`
- Modify: `src/domain/document/__tests__/document.test.ts`
- Modify: `src/domain/editor/commands.ts`
- Modify: `src/domain/editor/reducer.ts`
- Modify: `src/domain/editor/__tests__/reducer.test.ts`
- Modify: `src/editor/canvas/renderers/TableElementRenderer.tsx`

- [ ] **Step 1: Write failing merge/unmerge tests**

Cover valid rectangles, one-cell no-op, partial overlap rejection, already-merged selection, top-left value preservation, other values cleared, style resolution, undo restoring exact content/styles/merges, redo clearing again, and unmerge retaining only the top-left value.

- [ ] **Step 2: Persist normalized merge regions**

```ts
interface TableMerge {
  id: string;
  startRow: number;
  startColumn: number;
  rowSpan: number;
  columnSpan: number;
}
```

Migration repair drops out-of-bounds/overlapping invalid regions and reports a recoverable validation issue. Legacy tables default to no merges.

- [ ] **Step 3: Implement atomic merge commands**

Add the canonical `table.merge` and `table.unmerge` commands. The reducer owns all content/style clearing so the history snapshot can restore it exactly; the UI must not issue multiple cell-update commands.

- [ ] **Step 4: Render merged cells once**

Only the merge origin renders content and border geometry. Covered cells do not receive hit targets; hit testing maps them back to the origin/region. Selection outlines encompass the full merged rectangle.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/domain/editor/__tests__/tableMerge.test.ts src/domain/editor/__tests__/reducer.test.ts src/domain/document/__tests__/document.test.ts src/editor/canvas/__tests__/canvasInteractions.test.tsx`

Expected: PASS with exact undo restoration after destructive merge.

```bash
git add src/domain/document src/domain/editor src/editor/canvas/renderers/TableElementRenderer.tsx
git commit -m "feat: add atomic table merge operations"
```

## Task 3: Implement structural row and column commands

**Files:**
- Create: `src/domain/editor/tableStructure.ts`
- Create: `src/domain/editor/__tests__/tableStructure.test.ts`
- Modify: `src/domain/editor/commands.ts`
- Modify: `src/domain/editor/reducer.ts`
- Modify: `src/domain/editor/__tests__/reducer.test.ts`
- Modify: `src/editor/store/editorStore.ts`

- [ ] **Step 1: Write failing structure-transform tests**

Cover insert above/below/left/right, duplicate and delete selected row/column sets, multi-row/multi-column operations, last-row/column guard, merge shifting/expansion/removal, style cloning, dimensions, selection clamp, and exact undo/redo.

- [ ] **Step 2: Implement pure table transforms**

Expose operations that receive a table plus normalized indices and return a complete next table or a typed rejection. Do not mutate arrays in place. Define inserted row height/column width from the nearest neighbor and inserted cell style from the nearest compatible cell.

- [ ] **Step 3: Add one-command reducer entry points**

```ts
type TableStructureCommand =
  | { type: 'table.rows.insert'; tableId: string; index: number; count: number }
  | { type: 'table.rows.duplicate'; tableId: string; indices: number[] }
  | { type: 'table.rows.delete'; tableId: string; indices: number[] }
  | { type: 'table.columns.insert'; tableId: string; index: number; count: number }
  | { type: 'table.columns.duplicate'; tableId: string; indices: number[] }
  | { type: 'table.columns.delete'; tableId: string; indices: number[] };
```

Normalize/sort/deduplicate indices at the command boundary.

- [ ] **Step 4: Reconcile transient selection after success**

The store maps selection through the applied structure transform. On rejected commands, both document and selection remain unchanged and the UI receives a recoverable reason.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/domain/editor/__tests__/tableStructure.test.ts src/domain/editor/__tests__/reducer.test.ts src/editor/store/__tests__/editorStore.test.ts`

Expected: PASS for single and multi-index operations.

```bash
git add src/domain/editor/tableStructure.ts src/domain/editor/__tests__/tableStructure.test.ts src/domain/editor/commands.ts src/domain/editor/reducer.ts src/domain/editor/__tests__/reducer.test.ts src/editor/store
git commit -m "feat: add atomic table structure editing"
```

## Task 4: Add row/column resizing and even distribution

**Files:**
- Create: `src/domain/editor/tableDimensions.ts`
- Create: `src/domain/editor/__tests__/tableDimensions.test.ts`
- Modify: `src/domain/editor/commands.ts`
- Modify: `src/domain/editor/reducer.ts`
- Modify: `src/editor/canvas/renderers/TableElementRenderer.tsx`
- Modify: `src/editor/canvas/__tests__/canvasInteractions.test.tsx`

- [ ] **Step 1: Write failing dimension tests**

Cover pointer delta under canvas zoom, minimum dimensions, multi-row/column selection, total table bounds, distribute selected/all rows/columns, cancel, confirm, and undo as one step.

- [ ] **Step 2: Add pure dimension calculations**

Keep persisted arrays `rowHeights` and `columnWidths` normalized to row/column count. Distribution preserves the selected aggregate size and divides it evenly within numeric tolerance.

- [ ] **Step 3: Implement transient drag preview**

Pointer movement previews dimensions without adding history entries. Pointer up commits one `table.dimensions.set` command; Escape or pointer cancel restores initial dimensions with zero history.

- [ ] **Step 4: Add visible resize affordances**

Show row and column boundaries only while the table is selected/edited. Give handles enlarged hit targets, resize cursors, keyboard alternatives in the inspector, and tooltips.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/domain/editor/__tests__/tableDimensions.test.ts src/editor/canvas/__tests__/canvasInteractions.test.tsx src/domain/editor/__tests__/reducer.test.ts`

Expected: PASS with exactly one history entry per confirmed resize.

```bash
git add src/domain/editor/tableDimensions.ts src/domain/editor/__tests__/tableDimensions.test.ts src/domain/editor/commands.ts src/domain/editor/reducer.ts src/editor/canvas/renderers/TableElementRenderer.tsx src/editor/canvas/__tests__/canvasInteractions.test.tsx
git commit -m "feat: add table dimension editing"
```

## Task 5: Build selection-aware table inspector and context menus

**Files:**
- Create: `src/editor/inspectors/table/TableSelectionToolbar.tsx`
- Create: `src/editor/inspectors/table/TableContextMenu.tsx`
- Create: `src/editor/inspectors/table/TableCellProperties.tsx`
- Create: `src/editor/inspectors/table/__tests__/TableInspector.test.tsx`
- Modify: `src/editor/inspectors/TableInspector.tsx`
- Modify: `src/editor/components/SelectionToolbar.tsx`
- Modify: `src/editor/components/IconButtonWithTooltip.tsx`

- [ ] **Step 1: Write failing availability-matrix tests**

Create a table-driven test for table-element geometry, whole table, single cell, cell range, rows, and columns. Assert exactly which actions appear: copy/paste/delete, merge/unmerge, add/duplicate/delete rows/columns, distribute, size, fill, border, typography, alignment, whole-table style, and common element geometry controls.

- [ ] **Step 2: Implement a selection capability selector**

Compute capabilities from table structure plus transient selection in one pure selector. The inspector, floating toolbar, and context menu consume this selector so their enabled states cannot diverge.

- [ ] **Step 3: Match context-sensitive menus**

The canvas ellipsis/right-click menu uses the approved grouping and keyboard labels. For example, a selected column offers merge when rectangular and valid, delete selected columns, add columns, add rows, and row/column distribution where applicable. Sole-dimension delete is absent or disabled.

- [ ] **Step 4: Implement selection-aware property application**

Cell fill/border/text/alignment changes apply to enumerated selected cells in one command. Whole-table settings update table-level style where possible; explicit cell overrides remain explicit and undoable.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/inspectors/table/__tests__/TableInspector.test.tsx src/domain/editor/__tests__/reducer.test.ts`

Expected: PASS for the entire selection/action matrix.

```bash
git add src/editor/inspectors/TableInspector.tsx src/editor/inspectors/table src/editor/components/SelectionToolbar.tsx src/editor/components/IconButtonWithTooltip.tsx
git commit -m "feat: add selection-aware table controls"
```

## Task 6: Add spreadsheet keyboard navigation and clipboard

**Files:**
- Create: `src/domain/editor/tableClipboard.ts`
- Create: `src/domain/editor/__tests__/tableClipboard.test.ts`
- Create: `src/editor/canvas/TableKeyboardController.tsx`
- Create: `src/editor/canvas/__tests__/TableKeyboardController.test.tsx`
- Modify: `src/editor/canvas/KeyboardShortcuts.tsx`
- Modify: `src/editor/canvas/CanvasStage.tsx`
- Modify: `src/editor/store/editorStore.ts`

- [ ] **Step 1: Write failing navigation and clipboard tests**

Cover Arrow, Shift+Arrow, Tab/Shift+Tab, Enter, Home/End where supported, Escape, Delete/Backspace, Cmd/Ctrl+A, Cmd/Ctrl+C, Cmd/Ctrl+V, TSV parsing, internal structured copy/paste, rectangular paste, single-value fill, size mismatch rejection, merged-cell restrictions, permission denial, browser event fallback, and in-memory fallback.

- [ ] **Step 2: Implement table-focused shortcut routing**

When a table edit session is active, table navigation consumes its shortcuts before global element shortcuts. Text input/composition inside a cell must not trigger canvas deletion or page shortcuts.

- [ ] **Step 3: Implement clipboard serialization and parsing**

Serialize selected cells as TSV with rows separated by newlines and create a versioned internal payload containing supported cell styles and merge-safe geometry. Parse CRLF/LF, preserve empty cells, reject ragged data with a user-readable error, and never evaluate formulas or HTML. Internal editor paste may restore supported styles only when destination geometry is valid; external exchange remains TSV values.

- [ ] **Step 4: Implement permission-safe clipboard access**

Attempt `navigator.clipboard.writeText/readText`; also support browser `copy`/`paste` events for the internal MIME payload. On unavailable or denied access, use the session-local structured fallback. Surface a non-blocking status message indicating which path was used.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/domain/editor/__tests__/tableClipboard.test.ts src/editor/canvas/__tests__/TableKeyboardController.test.tsx src/editor/store/__tests__/editorStore.test.ts`

Expected: PASS in both Clipboard API and fallback modes.

```bash
git add src/domain/editor/tableClipboard.ts src/domain/editor/__tests__/tableClipboard.test.ts src/editor/canvas/TableKeyboardController.tsx src/editor/canvas/__tests__/TableKeyboardController.test.tsx src/editor/canvas/KeyboardShortcuts.tsx src/editor/canvas/CanvasStage.tsx src/editor/store/editorStore.ts
git commit -m "feat: add table keyboard and clipboard editing"
```

## Task 7: Verify spreadsheet-style table workflows

**Files:**
- Create: `tests/e2e/table-editor.spec.ts`
- Modify: `tests/e2e/helpers/editor.ts`

- [ ] **Step 1: Cover every selection granularity**

Test table-element geometry, single cell, rectangular range, complete row, complete column, and whole-table selection. Assert the inspector/context-menu action matrix and keyboard focus after menu close.

- [ ] **Step 2: Cover destructive and structural workflows**

Test merge → undo → redo → unmerge, multi-row insert/delete, multi-column insert/delete, last-row/column guard, resize cancel/confirm, distribute, formatting, TSV copy/paste, and reload persistence of content/merges without selection.

- [ ] **Step 3: Run the focused Wave 5 gate once**

Run: `npx playwright test tests/e2e/table-editor.spec.ts --project=usable-1440`

Expected: PASS once. A failure must be reduced to the responsible workflow before rerun.

- [ ] **Step 4: Run static gates and commit**

Run: `npm run lint && npm test && npm run build`

Expected: all PASS.

```bash
git add tests/e2e/table-editor.spec.ts tests/e2e/helpers/editor.ts
git commit -m "test: cover spreadsheet table workflows"
```
