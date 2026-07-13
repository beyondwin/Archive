# Miricanvas Design Editor Wave 4 Inspectors and Crop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execute after the catalog contracts from Wave 3 are stable.

**Goal:** Make element selection open a reliable Miricanvas-style editing surface with common quick actions, complete type-specific controls, numeric parity, nested detail views, and a dedicated non-destructive image crop mode.

**Architecture:** Inspector state is derived from the current selection. Common actions dispatch normalized domain commands; type-specific inspectors own only their presentation and field mapping. Nested inspector views share the Wave 3 route stack. Crop uses transient editor state until confirmation and commits one document command, so cancel never touches history.

**Tech Stack:** React 19, TypeScript, Zustand, react-konva/Konva, Vitest/Testing Library, Playwright.

---

## Wave constraints

- Common controls are opacity, alignment, order, lock, link, style copy/paste, duplicate, and delete where valid.
- Type-specific defaults and numeric ranges must be centralized, clamped, keyboard-accessible, and undoable.
- Every icon-only control has an accessible name and a hover/focus tooltip.
- The inspector may not write document state during render or merely because selection changed.
- Crop preview state is transient; confirm creates exactly one history entry and cancel creates none.
- Similar-content, recommendation, AI, animation, and video controls stay absent.

## Task 1: Build common inspector commands and UI primitives

**Files:**
- Create: `src/domain/editor/elementStyleClipboard.ts`
- Create: `src/domain/editor/__tests__/elementStyleClipboard.test.ts`
- Create: `src/editor/inspectors/InspectorShell.tsx`
- Create: `src/editor/inspectors/InspectorTabs.tsx`
- Create: `src/editor/inspectors/CommonPropertyRow.tsx`
- Create: `src/editor/components/IconButtonWithTooltip.tsx`
- Create: `src/editor/components/__tests__/IconButtonWithTooltip.test.tsx`
- Modify: `src/domain/editor/commands.ts`
- Modify: `src/domain/editor/reducer.ts`
- Modify: `src/domain/editor/__tests__/reducer.test.ts`
- Modify: `src/editor/components/InspectorPanel.tsx`
- Modify: `src/editor/components/SelectionToolbar.tsx`
- Modify: `src/editor/inspectors/NumberField.tsx`

- [ ] **Step 1: Write failing command and accessibility tests**

Cover opacity clamping, page-relative alignment, z-order boundaries, lock/content-lock differences, link validation, compatible style copy/paste, and one-step undo. Assert tooltips appear on hover and keyboard focus while their buttons retain meaningful accessible names.

- [ ] **Step 2: Define normalized common commands**

Add or normalize:

```ts
type CommonElementCommand =
  | { type: 'elements.opacity.set'; ids: string[]; opacity: number }
  | { type: 'elements.align'; ids: string[]; alignment: Alignment; basis: 'page' | 'selection' }
  | { type: 'elements.order.move'; ids: string[]; movement: OrderMovement }
  | { type: 'elements.lock.set'; ids: string[]; locked: boolean }
  | { type: 'elements.contentLock.set'; ids: string[]; locked: boolean }
  | { type: 'elements.link.set'; ids: string[]; href: string | null }
  | { type: 'elements.style.apply'; ids: string[]; style: CompatibleElementStyle };
```

Reject incompatible pasted style fields rather than changing the element type.

- [ ] **Step 3: Implement shared shell and primitives**

The shell owns the selected-type title, quick-action row, tab strip, nested route header, scroll region, and close/back focus behavior. `NumberField` must support click-step, keyboard-step, direct commit, Escape restore, min/max clamp, and locale-safe parsing.

- [ ] **Step 4: Reuse common actions in inspector and floating toolbar**

The floating toolbar shows the compact high-frequency subset; the left inspector shows the full row and nested details. Both call the same commands and reflect lock-disabled behavior.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/domain/editor/__tests__/elementStyleClipboard.test.ts src/domain/editor/__tests__/reducer.test.ts src/editor/components/__tests__/IconButtonWithTooltip.test.tsx`

Expected: PASS with one command path for every shared action.

```bash
git add src/domain/editor src/editor/inspectors src/editor/components/InspectorPanel.tsx src/editor/components/SelectionToolbar.tsx src/editor/components/IconButtonWithTooltip.tsx src/editor/components/__tests__/IconButtonWithTooltip.test.tsx
git commit -m "feat: establish common element inspector actions"
```

## Task 2: Rebuild the text inspector with Style and Font tabs

**Files:**
- Create: `src/editor/inspectors/text/TextStyleTab.tsx`
- Create: `src/editor/inspectors/text/TextFontTab.tsx`
- Create: `src/editor/inspectors/text/TextEffectsSections.tsx`
- Create: `src/editor/inspectors/text/__tests__/TextInspector.test.tsx`
- Modify: `src/editor/inspectors/TextInspector.tsx`
- Modify: `src/editor/canvas/InlineTextEditor.tsx`
- Modify: `src/domain/document/types.ts`
- Modify: `src/domain/document/migrations.ts`
- Modify: `src/domain/document/__tests__/document.test.ts`

- [ ] **Step 1: Write failing default and interaction tests**

Lock the approved defaults and ranges for family, size, weight, italic, underline, strike, horizontal/vertical alignment, line height, letter spacing, list style, text/fill color, highlight, and vertical writing. Cover Style/Font tab switching and Wave 3 font loading.

- [ ] **Step 2: Repair Schema V3 text defaults**

Add only fields that do not already exist. Migration repair must convert invalid numeric values to centralized defaults and keep valid legacy values unchanged. Missing font IDs fall back to the manifest default without deleting the original text.

- [ ] **Step 3: Implement tabs and collapsible detail sections**

Match the approved hierarchy: primary formatting above divider; Outline, Shadow, Curved text, and Vertical writing below. Expanded sections expose numeric/color controls; disabled sections retain their last values but do not affect rendering.

- [ ] **Step 4: Keep inline editing and inspector editing synchronized**

Starting inline edit selects the corresponding text element and opens the text inspector. Inspector changes update the active inline editor without losing caret selection; Escape exits inline edit before clearing element selection.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/inspectors/text/__tests__/TextInspector.test.tsx src/editor/canvas/__tests__/canvasInteractions.test.tsx src/domain/document/__tests__/document.test.ts`

Expected: PASS for mouse, keyboard, and direct numeric editing.

```bash
git add src/editor/inspectors/TextInspector.tsx src/editor/inspectors/text src/editor/canvas/InlineTextEditor.tsx src/domain/document
git commit -m "feat: rebuild the text property inspector"
```

## Task 3: Complete image properties and effect subviews

**Files:**
- Create: `src/editor/inspectors/image/ImageAdjustments.tsx`
- Create: `src/editor/inspectors/image/ImageFilters.tsx`
- Create: `src/editor/inspectors/image/ImageEffects.tsx`
- Create: `src/editor/inspectors/image/__tests__/ImageInspector.test.tsx`
- Modify: `src/editor/inspectors/ImageInspector.tsx`
- Modify: `src/editor/canvas/renderers/ImageElementRenderer.tsx`
- Modify: `src/domain/document/types.ts`
- Modify: `src/domain/document/migrations.ts`
- Modify: `src/domain/document/__tests__/document.test.ts`

- [ ] **Step 1: Write failing image-property tests**

Cover opacity, alignment, order, flip X/Y, filter preset, brightness, contrast, saturation, temperature, blur, shadow, border, corner radius, gradient mask, reset, and Crop entry. Assert all defaults produce the same appearance as an unedited legacy image.

- [ ] **Step 2: Extend Schema V3 with explicit image effects**

Use a structured optional value instead of unrelated booleans:

```ts
interface ImageAdjustments {
  brightness: number;
  contrast: number;
  saturation: number;
  temperature: number;
  blur: number;
}

interface GradientMask {
  enabled: boolean;
  direction: 'top' | 'right' | 'bottom' | 'left';
  start: number;
  end: number;
}
```

Repair ranges during load and serialize them during save/export.

- [ ] **Step 3: Implement quick actions and nested effect views**

The root shows the approved quick row plus Properties/Effects tabs. Filters, adjustments, gradient mask, border, shadow, and rounded corners use nested views or collapsible sections. Do not include “Similar image.”

- [ ] **Step 4: Render effects consistently on editor and export stages**

Share effect helpers so `CanvasStage`, `StaticPageStage`, and `ExportStageProvider` cannot diverge. Cache only immutable filter configuration, not rendered thumbnails.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/inspectors/image/__tests__/ImageInspector.test.tsx src/editor/canvas/__tests__/staticPageStage.test.tsx src/editor/export/__tests__/ExportStageProvider.test.tsx src/domain/document/__tests__/document.test.ts`

Expected: PASS with identical editor/static/export effect configuration.

```bash
git add src/editor/inspectors/ImageInspector.tsx src/editor/inspectors/image src/editor/canvas/renderers/ImageElementRenderer.tsx src/domain/document src/editor/export
git commit -m "feat: complete image property controls"
```

## Task 4: Implement dedicated non-destructive crop mode

**Files:**
- Create: `src/editor/canvas/crop/cropGeometry.ts`
- Create: `src/editor/canvas/crop/__tests__/cropGeometry.test.ts`
- Create: `src/editor/canvas/crop/ImageCropOverlay.tsx`
- Create: `src/editor/canvas/crop/__tests__/ImageCropOverlay.test.tsx`
- Modify: `src/editor/store/editorStore.ts`
- Modify: `src/editor/store/__tests__/editorStore.test.ts`
- Modify: `src/editor/canvas/CanvasStage.tsx`
- Modify: `src/editor/canvas/KeyboardShortcuts.tsx`
- Modify: `src/editor/components/SelectionToolbar.tsx`
- Modify: `src/editor/inspectors/ImageInspector.tsx`

- [ ] **Step 1: Write failing crop geometry and history tests**

Test pan/scale clamping for landscape, portrait, and rotated images; minimum visible coverage; handle movement under zoom; confirm/undo/redo; and cancel. Assert `history.past` is unchanged throughout preview and increases by one only on confirm.

- [ ] **Step 2: Add transient crop state**

Define:

```ts
interface CropSession {
  elementId: string;
  initial: ImageCrop;
  draft: ImageCrop;
}
```

Store it outside the persisted document. Opening crop on a locked image is rejected. Changing selection, page, or document prompts the same safe cancel path and cannot apply a stale session to another element.

- [ ] **Step 3: Implement the crop overlay**

Dim outside the frame, show image bounds and crop handles, support pointer drag, wheel/trackpad zoom, keyboard nudging, and the approved floating Cancel/Confirm controls. Keep the canvas transform stable while cropping.

- [ ] **Step 4: Wire confirm, cancel, and shortcuts**

Enter or the check button confirms; Escape or X cancels. Confirm dispatches one `image.crop.set` command containing the final normalized crop. Undo returns exactly to the initial crop.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/canvas/crop src/editor/store/__tests__/editorStore.test.ts src/editor/canvas/__tests__/canvasInteractions.test.tsx`

Expected: PASS, including zero-history cancel.

```bash
git add src/editor/canvas/crop src/editor/store src/editor/canvas/CanvasStage.tsx src/editor/canvas/KeyboardShortcuts.tsx src/editor/components/SelectionToolbar.tsx src/editor/inspectors/ImageInspector.tsx
git commit -m "feat: add non-destructive image crop mode"
```

## Task 5: Complete shape, line, icon, and chart inspectors

**Files:**
- Create: `src/editor/inspectors/vector/VectorFillSection.tsx`
- Create: `src/editor/inspectors/vector/VectorStrokeSection.tsx`
- Create: `src/editor/inspectors/vector/__tests__/VectorInspectors.test.tsx`
- Create: `src/editor/inspectors/chart/__tests__/ChartInspector.test.tsx`
- Modify: `src/editor/inspectors/ShapeInspector.tsx`
- Modify: `src/editor/inspectors/LineInspector.tsx`
- Modify: `src/editor/inspectors/IconInspector.tsx`
- Modify: `src/editor/inspectors/ChartInspector.tsx`
- Modify: `src/editor/canvas/renderers/ShapeElementRenderer.tsx`
- Modify: `src/editor/canvas/renderers/LineElementRenderer.tsx`
- Modify: `src/editor/canvas/renderers/IconElementRenderer.tsx`
- Modify: `src/editor/canvas/renderers/ChartElementRenderer.tsx`

- [ ] **Step 1: Write failing type-specific control tests**

Require shape fill/stroke/corners, line color/width/dash/start/end caps, icon color/multi-color behavior, and chart data/type/legend/axes/colors. Confirm irrelevant controls never render for the selected type.

- [ ] **Step 2: Implement shared vector sections without flattening differences**

Reuse color and stroke primitives, but keep shape, line, and icon entry components separate so each can enforce valid fields. A multi-color icon exposes only supported paint slots.

- [ ] **Step 3: Complete chart editing**

Validate chart data as a rectangular numeric dataset with labels. Invalid cell input remains editable but does not commit until valid; changing chart type preserves compatible data and one undo reverses the type change.

- [ ] **Step 4: Match quick toolbar and More behavior**

Provide duplicate, delete, lock, and More for every supported type. The More button opens the correct nested inspector section and returns focus to the triggering button on back.

- [ ] **Step 5: Verify and commit**

Run: `npm test -- src/editor/inspectors/vector/__tests__/VectorInspectors.test.tsx src/editor/inspectors/chart/__tests__/ChartInspector.test.tsx src/editor/canvas/__tests__/canvasInteractions.test.tsx`

Expected: PASS with no cross-type field leakage.

```bash
git add src/editor/inspectors src/editor/canvas/renderers
git commit -m "feat: complete vector and chart inspectors"
```

## Task 6: Verify inspector and crop workflows

**Files:**
- Create: `tests/e2e/inspectors-crop.spec.ts`
- Modify: `tests/e2e/helpers/editor.ts`

- [ ] **Step 1: Add focused selection and property helpers**

Use stable element IDs/test IDs and role-based controls. Include helpers to commit number fields, open nested routes, assert history, and enter/exit crop.

- [ ] **Step 2: Cover one full workflow per element family**

Test text Style/Font, image quick properties/effects/crop cancel/crop confirm, shape, line, icon, and chart. Include lock-disabled controls and undo/redo for each command family.

- [ ] **Step 3: Run the focused Wave 4 gate once**

Run: `npx playwright test tests/e2e/inspectors-crop.spec.ts --project=usable-1440`

Expected: PASS once. If a workflow flakes, isolate and repair its cause before any repeat.

- [ ] **Step 4: Run static gates and commit**

Run: `npm run lint && npm test && npm run build`

Expected: all PASS.

```bash
git add tests/e2e/inspectors-crop.spec.ts tests/e2e/helpers/editor.ts
git commit -m "test: cover inspectors and crop workflows"
```
