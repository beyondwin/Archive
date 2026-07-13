# Editable Project Wave A1 Domain and History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project identity, canonical document hashes, reversible patches, and a bounded durable-history domain that every later editor command can use.

**Architecture:** `DesignDocument` remains the render/edit source of truth. `ProjectEnvelope` adds lineage and schema identity, while `HistoryState` switches from repeated full snapshots to reversible RFC 6902 patch entries with canonical SHA-256 guards. Repository I/O is deliberately deferred to A2.

**Tech Stack:** TypeScript 5, Zustand 5, Vitest 3, uuid 11, @noble/hashes 2.2.0, fast-json-patch 3.1.1.

## Global Constraints

- Execute after existing Wave 1 has produced Schema V3 and its migrations.
- Keep the existing synchronous editor command API; persistence remains asynchronous in A2.
- Preserve `history.present`, `history.past.length`, and `history.future.length` consumer behavior while changing entry internals.
- Retain at most 200 ordinary entries and at most five discarded redo branches for seven days.
- Selection, viewport, open panels, crop previews, and uncommitted input drafts never enter durable history.
- One accepted drag, text-edit session, template application, table mutation, or bulk action creates one entry.
- Hashes use canonical JSON and SHA-256; do not use `JSON.stringify` equality as the history contract.
- Run `graphify update .` after the wave.

---

### Task 1: Add dependencies and project identity contracts

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Create: `src/domain/project/types.ts`
- Create: `src/domain/project/resources.ts`
- Create: `src/domain/project/factory.ts`
- Test: `src/domain/project/__tests__/project.test.ts`

**Interfaces:**
- Consumes: `DesignDocument`, `CURRENT_SCHEMA_VERSION`, `uuid.v4()`.
- Produces: `ProjectEnvelope`, `ProjectResourceIndex`, `ProjectSnapshot`, `createProjectEnvelope(document, options?)`, `createProjectSnapshot(document, options?)`, `reconcileProjectResourceIndex(document, current)`, `validateProjectResourceIndex(index, document)`.

- [ ] **Step 1: Install the exact domain dependencies**

Run:

```bash
npm install @noble/hashes@^2.2.0 fast-json-patch@^3.1.1
```

Expected: `package.json` and `package-lock.json` record both runtime dependencies; install exits 0.

- [ ] **Step 2: Write the project identity RED**

```ts
import { createBlankDocument } from "@/domain/document/factory";
import { createProjectSnapshot } from "@/domain/project/factory";

it("creates stable project identity around an unchanged document", () => {
  const document = createBlankDocument();
  const snapshot = createProjectSnapshot(document, {
    projectId: "project-1",
    lineageId: "lineage-1",
    now: "2026-07-12T00:00:00.000Z",
  });

  expect(snapshot.envelope).toMatchObject({
    projectId: "project-1",
    lineageId: "lineage-1",
    revision: 0,
    baseRevision: 0,
    formatVersion: 1,
    documentSchemaVersion: 3,
    historySchemaVersion: 1,
    resourceSchemaVersion: 1,
    kind: "project",
  });
  expect(snapshot.document).toEqual(document);
  expect(snapshot.document).not.toBe(document);
  expect(snapshot.resources.schemaVersion).toBe(1);
});

it("never treats a same-name font as an exact binding", () => {
  const index = reconcileProjectResourceIndex(documentUsingFont("Brand Sans", 400, false), emptyProjectResourceIndex());
  expect(Object.values(index.fonts)[0]).toMatchObject({ state: "unresolved", expectedHash: null });
});

it("keeps two same-name font versions exact at separate usage locators", () => {
  const document = documentWithTwoFontUsages("Brand Sans", 400, false);
  const index = bindFontUsages(document, ["a".repeat(64), "b".repeat(64)]);
  expect(new Set(Object.values(index.fonts).map(({ expectedHash }) => expectedHash))).toHaveLength(2);
  expect(() => validateProjectResourceIndex(index, document)).not.toThrow();
});
```

- [ ] **Step 3: Run the project identity RED**

Run: `npm test -- src/domain/project/__tests__/project.test.ts`

Expected: FAIL because `@/domain/project/factory` does not exist.

- [ ] **Step 4: Add exact project types and factories**

```ts
// src/domain/project/types.ts
import type { DesignDocument } from "@/domain/document/types";
import type { ProjectResourceIndex } from "./resources";

export const CURRENT_PROJECT_FORMAT_VERSION = 1;
export const CURRENT_HISTORY_SCHEMA_VERSION = 1;
export const CURRENT_RESOURCE_SCHEMA_VERSION = 1;

export type ProjectKind = "project" | "template" | "page-fragment";
export type ProjectOrigin =
  | { kind: "blank" }
  | { kind: "imported"; sourceName: string }
  | { kind: "template"; templateId: string; templateVersion: string };

export type ProjectEnvelope = {
  projectId: string;
  lineageId: string;
  revision: number;
  baseRevision: number;
  formatVersion: number;
  documentSchemaVersion: number;
  historySchemaVersion: number;
  resourceSchemaVersion: number;
  kind: ProjectKind;
  requiredCapabilities: string[];
  optionalCapabilities: string[];
  createdAt: string;
  modifiedAt: string;
  exportedAt: string | null;
  origin: ProjectOrigin;
};

export type ProjectSnapshot = {
  envelope: ProjectEnvelope;
  document: DesignDocument;
  resources: ProjectResourceIndex;
};
```

```ts
// src/domain/project/resources.ts
export type ResourceResolutionState = "bound" | "unresolved";

export type AssetResourceBinding = {
  resourceId: string;
  assetId: string;
  expectedHash: string | null;
  mimeType: string | null;
  source: "bundled" | "upload" | "template" | "server" | "legacy";
  state: ResourceResolutionState;
};

export type FontUsage = {
  pageId: string;
  elementId: string;
  cellId: string | null;
  slot: "text" | "table-cell";
  family: string;
  weight: number;
  italic: boolean;
};

export type FontResourceBinding = {
  usageId: string;
  resourceId: string;
  usage: FontUsage;
  expectedHash: string | null;
  postscriptName: string | null;
  embeddingRights: "installable" | "editable" | "preview-print" | "restricted" | "bitmap-only" | "unknown";
  licenseId: string | null;
  state: ResourceResolutionState;
};

export type ProjectResourceIndex = {
  schemaVersion: 1;
  assets: Record<string, AssetResourceBinding>;
  fonts: Record<string, FontResourceBinding>; // keyed by usageId
};
```

`usageId` is canonical from the stable page ID, element ID, optional table-cell ID, and style slot. Family/weight/italic are descriptive style data, not identity. This permits two same-family/same-style font versions with different hashes in different elements without collision. `reconcileProjectResourceIndex` walks page backgrounds, element fills, image/icon refs, text styles, and table-cell styles. It preserves known exact per-usage bindings, adds new unknown usages as explicit `unresolved` bindings with `expectedHash: null`, and never binds bytes by filename/family name alone. Validation requires a 64-hex hash for every `bound` entry, forbids a hash on `unresolved`, permits a shared `resourceId` only when its hashes/license metadata agree, and requires every current document usage locator to have one index entry.

```ts
// src/domain/project/factory.ts
import { v4 as uuid } from "uuid";
import { CURRENT_SCHEMA_VERSION, type DesignDocument } from "@/domain/document/types";
import {
  CURRENT_HISTORY_SCHEMA_VERSION,
  CURRENT_PROJECT_FORMAT_VERSION,
  CURRENT_RESOURCE_SCHEMA_VERSION,
  type ProjectEnvelope,
  type ProjectSnapshot,
} from "./types";
import {
  emptyProjectResourceIndex,
  reconcileProjectResourceIndex,
  type ProjectResourceIndex,
} from "./resources";

export type CreateProjectOptions = Partial<Pick<ProjectEnvelope,
  "projectId" | "lineageId" | "revision" | "baseRevision" | "kind" | "origin"
>> & { now?: string };

export type CreateProjectSnapshotOptions = CreateProjectOptions & { resources?: ProjectResourceIndex };

export function createProjectEnvelope(document: DesignDocument, options: CreateProjectOptions = {}): ProjectEnvelope {
  const now = options.now ?? new Date().toISOString();
  const projectId = options.projectId ?? `project-${uuid()}`;
  return {
    projectId,
    lineageId: options.lineageId ?? projectId,
    revision: options.revision ?? 0,
    baseRevision: options.baseRevision ?? 0,
    formatVersion: CURRENT_PROJECT_FORMAT_VERSION,
    documentSchemaVersion: CURRENT_SCHEMA_VERSION,
    historySchemaVersion: CURRENT_HISTORY_SCHEMA_VERSION,
    resourceSchemaVersion: CURRENT_RESOURCE_SCHEMA_VERSION,
    kind: options.kind ?? "project",
    requiredCapabilities: [],
    optionalCapabilities: [],
    createdAt: now,
    modifiedAt: now,
    exportedAt: null,
    origin: options.origin ?? { kind: "blank" },
  };
}

export function createProjectSnapshot(document: DesignDocument, options: CreateProjectSnapshotOptions = {}): ProjectSnapshot {
  return {
    envelope: createProjectEnvelope(document, options),
    document: structuredClone(document),
    resources: structuredClone(options.resources ?? reconcileProjectResourceIndex(document, emptyProjectResourceIndex())),
  };
}
```

- [ ] **Step 5: Run the project identity GREEN**

Run: `npm test -- src/domain/project/__tests__/project.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit the identity contracts**

```bash
git add package.json package-lock.json src/domain/project
git commit -m "feat: add editable project identity contracts"
```

---

### Task 2: Add canonical JSON and SHA-256 document hashes

**Files:**
- Create: `src/domain/project/canonicalJson.ts`
- Create: `src/domain/project/hash.ts`
- Create: `src/domain/project/__fixtures__/canonical-json-vectors.json`
- Test: `src/domain/project/__tests__/hash.test.ts`

**Interfaces:**
- Consumes: JSON-compatible project/domain values.
- Produces: RFC 8785-compatible `canonicalStringify(value): string`, `sha256Hex(bytes|string): string`, `hashDocument(document): string`, `hashProjectContent({ document, resources }): string`, cross-runtime golden vectors.

- [ ] **Step 1: Write deterministic hash tests**

```ts
import { canonicalStringify } from "@/domain/project/canonicalJson";
import { sha256Hex } from "@/domain/project/hash";

it("canonicalizes object keys", () => {
  expect(canonicalStringify({ z: 1, a: { d: 2, c: 3 } }))
    .toBe('{"a":{"c":3,"d":2},"z":1}');
});

it("produces the known SHA-256 digest", () => {
  expect(sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});

it("matches canonical Unicode and number golden vectors", () => {
  for (const vector of canonicalJsonVectors) {
    expect(canonicalStringify(vector.input)).toBe(vector.canonical);
    expect(sha256Hex(vector.canonical)).toBe(vector.sha256);
  }
});

it.each([{ value: undefined }, { value: "\ud800" }])("rejects values outside interoperable JSON", (value) => {
  expect(() => canonicalStringify(value)).toThrow("canonical JSON");
});
```

- [ ] **Step 2: Run the deterministic hash RED**

Run: `npm test -- src/domain/project/__tests__/hash.test.ts`

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement canonical JSON and hashing**

```ts
// src/domain/project/canonicalJson.ts
function canonicalize(value: unknown): unknown {
  if (value === undefined) throw new Error("canonical JSON rejects undefined");
  if (Array.isArray(value)) return value.map((item) => canonicalize(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value as Record<string, unknown>)
      .sort()
      .map((key) => [key, canonicalize((value as Record<string, unknown>)[key])]));
  }
  if (typeof value === "number" && !Number.isFinite(value)) {
    throw new Error("Canonical JSON rejects non-finite numbers");
  }
  return value;
}

export function canonicalStringify(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}
```

Complete the implementation with RFC 8785 JSON Canonicalization Scheme rules: UTF-16 code-unit property ordering, ECMAScript JSON number serialization including `-0`, minimal required string escaping, and rejection of non-finite numbers, `undefined`, functions/symbols/bigints, cycles, and unpaired Unicode surrogates. Do not normalize string content. Golden vectors include nested key order, astral characters, control escapes, `-0`, integer boundaries, and exponent forms; C2 reuses the same file for server contract hashes.

```ts
// src/domain/project/hash.ts
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import type { DesignDocument } from "@/domain/document/types";
import type { ProjectResourceIndex } from "./resources";
import { canonicalStringify } from "./canonicalJson";

const encoder = new TextEncoder();

export function sha256Hex(value: string | Uint8Array): string {
  return bytesToHex(sha256(typeof value === "string" ? encoder.encode(value) : value));
}

export function hashDocument(document: DesignDocument): string {
  return sha256Hex(canonicalStringify(document));
}

export function hashProjectContent(content: { document: DesignDocument; resources: ProjectResourceIndex }): string {
  return sha256Hex(canonicalStringify(content));
}
```

- [ ] **Step 4: Run the deterministic hash GREEN**

Run: `npm test -- src/domain/project/__tests__/hash.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit canonical hashing**

```bash
git add src/domain/project/canonicalJson.ts src/domain/project/hash.ts src/domain/project/__fixtures__/canonical-json-vectors.json src/domain/project/__tests__/hash.test.ts
git commit -m "feat: add canonical project hashes"
```

---

### Task 3: Add reversible editable-project content patches

**Files:**
- Create: `src/domain/project/patch.ts`
- Test: `src/domain/project/__tests__/patch.test.ts`

**Interfaces:**
- Consumes: two validated `{ document: DesignDocument; resources: ProjectResourceIndex }` values.
- Produces: `ProjectContentState`, `ReversibleProjectPatch`, `createReversiblePatch(before, after)`, `applyForward(content, patch)`, `applyInverse(content, patch)`.

- [ ] **Step 1: Write reversible-patch RED tests**

```ts
import { createBlankDocument, createPage } from "@/domain/document/factory";
import { applyForward, applyInverse, createReversiblePatch } from "@/domain/project/patch";

it("round-trips an array mutation with guarded hashes", () => {
  const before = createBlankDocument();
  const after = structuredClone(before);
  after.pages.push(createPage({ id: "page-2" }));
  const beforeContent = projectContent(before);
  const afterContent = projectContent(after);
  const patch = createReversiblePatch(beforeContent, afterContent);

  expect(applyForward(beforeContent, patch)).toEqual(afterContent);
  expect(applyInverse(afterContent, patch)).toEqual(beforeContent);
  expect(() => applyForward(afterContent, patch)).toThrow("base hash");
});

it("round-trips an exact font binding change with the document style", () => {
  const before = projectContent(documentUsingFont("Brand A"), resourceIndexFor("Brand A", "hash-a"));
  const after = projectContent(documentUsingFont("Brand B"), resourceIndexFor("Brand B", "hash-b"));
  const patch = createReversiblePatch(before, after);
  expect(applyInverse(applyForward(before, patch), patch)).toEqual(before);
});
```

- [ ] **Step 2: Run the reversible-patch RED**

Run: `npm test -- src/domain/project/__tests__/patch.test.ts`

Expected: FAIL because `patch.ts` does not exist.

- [ ] **Step 3: Implement guarded forward and inverse patches**

```ts
import { applyPatch, compare, type Operation } from "fast-json-patch";
import type { DesignDocument } from "@/domain/document/types";
import { assertDesignDocument } from "@/domain/document/validation";
import type { ProjectResourceIndex } from "./resources";
import { validateProjectResourceIndex } from "./resources";
import { hashProjectContent } from "./hash";

export type ProjectContentState = { document: DesignDocument; resources: ProjectResourceIndex };

export type ReversibleProjectPatch = {
  baseHash: string;
  resultHash: string;
  forward: Operation[];
  inverse: Operation[];
};

export function createReversiblePatch(before: ProjectContentState, after: ProjectContentState): ReversibleProjectPatch {
  assertDesignDocument(before.document);
  validateProjectResourceIndex(before.resources, before.document);
  assertDesignDocument(after.document);
  validateProjectResourceIndex(after.resources, after.document);
  return {
    baseHash: hashProjectContent(before),
    resultHash: hashProjectContent(after),
    forward: compare(structuredClone(before), structuredClone(after), true),
    inverse: compare(structuredClone(after), structuredClone(before), true),
  };
}

function applyGuarded(content: ProjectContentState, operations: Operation[], expected: string, result: string): ProjectContentState {
  if (hashProjectContent(content) !== expected) throw new Error("Project content base hash does not match patch");
  const next = applyPatch(structuredClone(content), operations, true, false).newDocument as ProjectContentState;
  assertDesignDocument(next.document);
  validateProjectResourceIndex(next.resources, next.document);
  if (hashProjectContent(next) !== result) throw new Error("Project content result hash does not match patch");
  return next;
}

export const applyForward = (content: ProjectContentState, patch: ReversibleProjectPatch) =>
  applyGuarded(content, patch.forward, patch.baseHash, patch.resultHash);

export const applyInverse = (content: ProjectContentState, patch: ReversibleProjectPatch) =>
  applyGuarded(content, patch.inverse, patch.resultHash, patch.baseHash);
```

- [ ] **Step 4: Run patch and document regressions**

Run: `npm test -- src/domain/project/__tests__/patch.test.ts src/domain/document/__tests__/document.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit reversible patches**

```bash
git add src/domain/project/patch.ts src/domain/project/__tests__/patch.test.ts
git commit -m "feat: add reversible project content patches"
```

---

### Task 4: Replace snapshot history with bounded durable entries

**Files:**
- Modify: `src/domain/editor/history.ts`
- Modify: `src/domain/editor/__tests__/reducer.test.ts`
- Create: `src/domain/editor/__tests__/history.test.ts`

**Interfaces:**
- Consumes: `ReversibleProjectPatch` and the `HistoryCommitMetadata` contract defined in this task; Task 5 maps editor commands into that metadata.
- Produces: `HistoryEntry`, `HistoryState`, `createHistoryState`, `commitHistory`, `undoHistory`, `redoHistory`, `discardFutureAsRecovery`.

- [ ] **Step 1: Write retention, reopen, and redo RED tests**

```ts
import { createBlankDocument } from "@/domain/document/factory";
import { commitHistory, createHistoryState, redoHistory, undoHistory } from "@/domain/editor/history";

it("retains only 200 reversible operations and preserves redo", () => {
  let history = createHistoryState(createBlankDocument(), { sessionId: "session-1" });
  for (let index = 1; index <= 205; index += 1) {
    const next = structuredClone(history.present);
    next.title = `title-${index}`;
    history = commitHistory(history, next, { label: "문서 이름 변경", commandType: "document.rename" });
  }
  expect(history.past).toHaveLength(200);
  const undone = undoHistory(history);
  expect(undone.present.title).toBe("title-204");
  expect(redoHistory(undone).present.title).toBe("title-205");
});

it("captures a discarded redo path before a divergent command", () => {
  const undone = undoHistory(historyWithThreeTitles());
  const next = structuredClone(undone.present);
  next.title = "divergent";
  const committed = commitHistory(undone, next, {
    label: "문서 이름 변경",
    commandType: "document.rename",
    now: "2026-07-12T00:00:00.000Z",
  });
  expect(committed.future).toEqual([]);
  expect(committed.discardedBranches.at(-1)?.entries).toEqual(undone.future);
});
```

- [ ] **Step 2: Run the durable-history RED**

Run: `npm test -- src/domain/editor/__tests__/history.test.ts src/domain/editor/__tests__/reducer.test.ts`

Expected: FAIL because current history stores documents and accepts no metadata.

- [ ] **Step 3: Implement bounded reversible history**

```ts
import { v4 as uuid } from "uuid";
import type { DesignDocument } from "@/domain/document/types";
import { applyForward, applyInverse, createReversiblePatch, type ReversibleProjectPatch } from "@/domain/project/patch";
import { emptyProjectResourceIndex, reconcileProjectResourceIndex, type ProjectResourceIndex } from "@/domain/project/resources";

export const MAX_HISTORY_ENTRIES = 200;
export const MAX_DISCARDED_BRANCHES = 5;
export const DISCARDED_BRANCH_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export type HistoryEntry = {
  operationId: string;
  sessionId: string;
  createdAt: string;
  label: string;
  commandType: string;
  touchedIds: string[];
  patch: ReversibleProjectPatch;
};

export type HistoryState = {
  sessionId: string;
  past: HistoryEntry[];
  present: DesignDocument;
  resources: ProjectResourceIndex;
  future: HistoryEntry[];
  discardedBranches: DiscardedHistoryBranch[];
};

export type DiscardedHistoryBranch = {
  branchId: string;
  createdAt: string;
  expiresAt: string;
  baseDocument: DesignDocument;
  baseResources: ProjectResourceIndex;
  entries: HistoryEntry[];
};

export type HistoryCommitMetadata = {
  label: string;
  commandType: string;
  touchedIds?: string[];
  now?: string;
};

export function createHistoryState(
  document: DesignDocument,
  options: { sessionId?: string; resources?: ProjectResourceIndex } = {},
): HistoryState {
  const resources = options.resources ?? reconcileProjectResourceIndex(document, emptyProjectResourceIndex());
  return { sessionId: options.sessionId ?? `session-${uuid()}`, past: [], present: document, resources, future: [], discardedBranches: [] };
}

export function discardFutureAsRecovery(state: HistoryState, now: string): HistoryState {
  if (state.future.length === 0) return state;
  const createdAtMs = new Date(now).getTime();
  const branch: DiscardedHistoryBranch = {
    branchId: `branch-${uuid()}`,
    createdAt: now,
    expiresAt: new Date(createdAtMs + DISCARDED_BRANCH_TTL_MS).toISOString(),
    baseDocument: structuredClone(state.present),
    baseResources: structuredClone(state.resources),
    entries: structuredClone(state.future),
  };
  return {
    ...state,
    future: [],
    discardedBranches: [...state.discardedBranches, branch].slice(-MAX_DISCARDED_BRANCHES),
  };
}

export function commitHistory(
  state: HistoryState,
  next: DesignDocument,
  metadata: HistoryCommitMetadata,
  nextResources?: ProjectResourceIndex,
): HistoryState {
  const resolvedNextResources = nextResources ?? reconcileProjectResourceIndex(next, state.resources);
  const patch = createReversiblePatch(
    { document: state.present, resources: state.resources },
    { document: next, resources: resolvedNextResources },
  );
  if (patch.forward.length === 0) return state;
  const prepared = state.future.length > 0
    ? discardFutureAsRecovery(state, metadata.now ?? new Date().toISOString())
    : state;
  const entry: HistoryEntry = {
    operationId: `operation-${uuid()}`,
    sessionId: state.sessionId,
    createdAt: metadata.now ?? new Date().toISOString(),
    label: metadata.label,
    commandType: metadata.commandType,
    touchedIds: metadata.touchedIds ?? [],
    patch,
  };
  return { ...prepared, past: [...prepared.past, entry].slice(-MAX_HISTORY_ENTRIES), present: next, resources: resolvedNextResources, future: [] };
}

export function undoHistory(state: HistoryState): HistoryState {
  const entry = state.past.at(-1);
  if (!entry) return state;
  const previous = applyInverse({ document: state.present, resources: state.resources }, entry.patch);
  return { ...state, past: state.past.slice(0, -1), present: previous.document, resources: previous.resources, future: [entry, ...state.future] };
}

export function redoHistory(state: HistoryState): HistoryState {
  const entry = state.future[0];
  if (!entry) return state;
  const next = applyForward({ document: state.present, resources: state.resources }, entry.patch);
  return { ...state, past: [...state.past, entry], present: next.document, resources: next.resources, future: state.future.slice(1) };
}
```

- [ ] **Step 4: Update existing reducer history assertions**

Replace direct `history.past[n].pages` assertions with document results obtained through `undoHistory` and `redoHistory`. Do not expose patch internals to reducer tests.

- [ ] **Step 5: Run history regressions**

Run: `npm test -- src/domain/editor/__tests__/history.test.ts src/domain/editor/__tests__/reducer.test.ts`

Expected: PASS with 200-entry retention and exact undo/redo.

- [ ] **Step 6: Commit bounded history**

```bash
git add src/domain/editor/history.ts src/domain/editor/__tests__/history.test.ts src/domain/editor/__tests__/reducer.test.ts
git commit -m "feat: make editor history durable and bounded"
```

---

### Task 5: Add command metadata and project-aware editor state

**Files:**
- Create: `src/domain/editor/commandMetadata.ts`
- Create: `src/domain/editor/resourceEffects.ts`
- Test: `src/domain/editor/__tests__/resourceEffects.test.ts`
- Create: `src/domain/project/mutation.ts`
- Modify: `src/editor/store/editorStore.ts`
- Modify: `src/editor/store/__tests__/editorStore.test.ts`

**Interfaces:**
- Consumes: every `EditorCommand`, `ProjectSnapshot`, durable `HistoryState`.
- Produces: `describeCommand(command)`, `applyCommandResourceEffects(command, before, after, currentIndex)`, `DurableProjectMutation`, `EditorState.project`, `EditorState.durabilityQueue`, `acknowledgeDurabilityMutation(mutationId)`, `loadProject(snapshot, history?)`; retains `loadDocument` compatibility until A2.

- [ ] **Step 1: Write command metadata and revision RED tests**

```ts
it("increments project and document revisions for every persistent command", () => {
  const before = useEditorStore.getState();
  before.dispatch({ type: "document.rename", title: "새 제목" });
  const after = useEditorStore.getState();
  expect(after.documentRevision).toBe(before.documentRevision + 1);
  expect(after.project.revision).toBe(before.project.revision + 1);
  expect(after.history.past.at(-1)).toMatchObject({ commandType: "document.rename", label: "문서 이름 변경" });
  expect(after.durabilityQueue.at(-1)).toMatchObject({
    projectId: before.project.projectId,
    expectedRevision: before.project.revision,
    envelope: { revision: before.project.revision + 1 },
    reason: "command",
  });
});

it("queues undo and redo as new durable revisions without duplicating operations", () => {
  const store = resetStoreWithOneCommittedCommand();
  store.undo();
  expect(useEditorStore.getState().durabilityQueue.at(-1)).toMatchObject({ reason: "undo", appendedEntry: null });
  store.redo();
  expect(useEditorStore.getState().durabilityQueue.at(-1)).toMatchObject({ reason: "redo", appendedEntry: null });
  expect(useEditorStore.getState().project.revision).toBe(3);
});
```

- [ ] **Step 2: Run the editor-store RED**

Run: `npm test -- src/editor/store/__tests__/editorStore.test.ts`

Expected: FAIL because `project` and command metadata do not exist.

- [ ] **Step 3: Add deterministic metadata**

```ts
// src/domain/editor/commandMetadata.ts
import type { EditorCommand } from "./commands";
import type { HistoryCommitMetadata } from "./history";

const labels: Partial<Record<EditorCommand["type"], string>> = {
  "document.rename": "문서 이름 변경",
  "page.add": "페이지 추가",
  "page.delete": "페이지 삭제",
  "page.duplicate": "페이지 복제",
  "page.template.apply": "템플릿 적용",
  "element.add": "요소 추가",
  "element.delete": "요소 삭제",
  "element.duplicate": "요소 복제",
};

export function describeCommand(command: EditorCommand): HistoryCommitMetadata {
  return { label: labels[command.type] ?? command.type, commandType: command.type };
}
```

- [ ] **Step 4: Define the mutation passed to the A2 durability boundary**

```ts
// src/domain/project/mutation.ts
import type { DesignDocument } from "@/domain/document/types";
import type { DiscardedHistoryBranch, HistoryEntry } from "@/domain/editor/history";
import type { ProjectResourceIndex } from "./resources";
import type { ProjectEnvelope } from "./types";

export type DurableMutationReason = "command" | "undo" | "redo" | "restore" | "replace";

export type DurableProjectMutation = {
  mutationId: string;
  reason: DurableMutationReason;
  projectId: string;
  expectedRevision: number;
  envelope: ProjectEnvelope;
  document: DesignDocument;
  resources: ProjectResourceIndex;
  pastOperationIds: string[];
  futureOperationIds: string[];
  appendedEntry: HistoryEntry | null;
  discardedBranches: DiscardedHistoryBranch[];
};
```

The mutation is a domain value only; A1 does not perform repository I/O. `dispatch`, `undo`, and `redo` each append exactly one immutable mutation after a real document change. Undo/redo set `appendedEntry: null` and persist the resulting cursor arrays. `restore` and `replace` are reserved for A2/B2 boundary operations.

Add exhaustive resource-effect tests before store integration. `element.duplicate`, `page.duplicate`, table row/column copy/add, and template/page insertion must map each newly generated page/element/cell locator to the corresponding source binding and preserve its exact resource ID/hash. A font-style or asset change without validated binding metadata becomes explicit unresolved state; it may not inherit a same-name binding. Delete keeps bindings reachable from retained history until compaction. `applyCommandResourceEffects` must throw on ambiguous source/destination mapping instead of guessing.

Every later wave that adds a resource-bearing or ID-generating persistent command must add its case and focused test to `resourceEffects.ts` in the same task.

- [ ] **Step 5: Integrate project revision, metadata, and the ordered durability queue**

In `editorStore.ts`, initialize `project` with `createProjectEnvelope(initialDocument)`. For non-selection commands:

```ts
const nextResources = applyCommandResourceEffects(command, state.history.present, nextDocument, state.projectResources);
const nextHistory = commitHistory(state.history, nextDocument, describeCommand(command), nextResources);
if (nextHistory === state.history) return;
const nextProject = {
  ...state.project,
  revision: state.project.revision + 1,
  modifiedAt: new Date().toISOString(),
};
const mutation: DurableProjectMutation = {
  mutationId: `mutation-${uuid()}`,
  reason: "command",
  projectId: state.project.projectId,
  expectedRevision: state.project.revision,
  envelope: nextProject,
  document: structuredClone(nextHistory.present),
  resources: structuredClone(nextHistory.resources),
  pastOperationIds: nextHistory.past.map(({ operationId }) => operationId),
  futureOperationIds: nextHistory.future.map(({ operationId }) => operationId),
  appendedEntry: nextHistory.past.at(-1) ?? null,
  discardedBranches: structuredClone(nextHistory.discardedBranches),
};
set({
  project: nextProject,
  history: nextHistory,
  projectResources: nextHistory.resources,
  durabilityQueue: [...state.durabilityQueue, mutation],
  documentRevision: state.documentRevision + 1,
  // preserve the existing active-page, selection, edit-mode and save-status fields
});
```

Add `projectResources: ProjectResourceIndex` to editor state. Add `loadProject(snapshot, history = createHistoryState(snapshot.document, { resources: snapshot.resources }))` and implement `loadDocument(document)` as a compatibility wrapper around `createProjectSnapshot(document)`. Both load/reconcile the resource index and clear `durabilityQueue`. Undo/redo assign both `history.present` and `history.resources` before queuing their durable revision. Add `acknowledgeDurabilityMutation(mutationId)` that removes only the matching committed head item and throws on out-of-order acknowledgement; A2 owns async retry/status behavior.

- [ ] **Step 6: Run editor-store and component regressions**

Run: `npm test -- src/domain/editor/__tests__/resourceEffects.test.ts src/editor/store/__tests__/editorStore.test.ts src/editor/components/__tests__/documentLoadSave.test.tsx src/editor/components/__tests__/editorShell.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit project-aware editor state**

```bash
git add src/domain/editor/commandMetadata.ts src/domain/editor/resourceEffects.ts src/domain/editor/__tests__/resourceEffects.test.ts src/domain/project/mutation.ts src/domain/project/resources.ts src/editor/store/editorStore.ts src/editor/store/__tests__/editorStore.test.ts
git commit -m "feat: record project command metadata"
```

---

### Task 6: Add checkpoint, named-version, and discarded-branch rules

**Files:**
- Create: `src/domain/project/checkpoints.ts`
- Create: `src/domain/project/compaction.ts`
- Test: `src/domain/project/__tests__/checkpoints.test.ts`

**Interfaces:**
- Consumes: `ProjectEnvelope`, `DesignDocument`, `HistoryState`.
- Produces: `ProjectCheckpoint`, `NamedProjectVersion`, `shouldCheckpoint`, `compactCheckpoints`, `compactHistory`, `captureDiscardedBranch`.

- [ ] **Step 1: Write exact policy RED tests**

```ts
it("checkpoints after 20 operations and keeps 20 automatic checkpoints", () => {
  expect(shouldCheckpoint({ operationsSinceCheckpoint: 20, activeMs: 1_000, boundary: null })).toBe(true);
  const compacted = compactCheckpoints(Array.from({ length: 25 }, (_, i) => checkpoint(`cp-${i}`)));
  expect(compacted).toHaveLength(20);
  expect(compacted[0].checkpointId).toBe("cp-5");
});

it("keeps at most five discarded redo branches for seven days", () => {
  const retained = compactDiscardedBranches(branches(8), "2026-07-12T00:00:00.000Z");
  expect(retained).toHaveLength(5);
  expect(retained.every((branch) => branch.expiresAt <= "2026-07-19T00:00:00.000Z")).toBe(true);
});
```

- [ ] **Step 2: Run checkpoint RED tests**

Run: `npm test -- src/domain/project/__tests__/checkpoints.test.ts`

Expected: FAIL because checkpoint policy modules do not exist.

- [ ] **Step 3: Implement pure checkpoint and compaction policy**

Define:

```ts
import type { ProjectSnapshot } from "./types";
import {
  DISCARDED_BRANCH_TTL_MS,
  MAX_DISCARDED_BRANCHES,
  type DiscardedHistoryBranch,
} from "@/domain/editor/history";

export const MAX_AUTOMATIC_CHECKPOINTS = 20;
export const CHECKPOINT_OPERATION_INTERVAL = 20;
export const CHECKPOINT_ACTIVE_MS = 5 * 60 * 1000;
export type CheckpointBoundary = "import" | "template" | "restore" | "replace" | "switch" | "compact";

export type ProjectCheckpoint = {
  checkpointId: string;
  projectId: string;
  revision: number;
  createdAt: string;
  reason: "automatic" | CheckpointBoundary;
  snapshot: ProjectSnapshot;
  pastOperationIds: string[];
  futureOperationIds: string[];
};

export type NamedProjectVersion = {
  versionId: string;
  projectId: string;
  revision: number;
  name: string;
  createdAt: string;
  snapshot: ProjectSnapshot;
  pastOperationIds: string[];
  futureOperationIds: string[];
};

export function shouldCheckpoint(input: { operationsSinceCheckpoint: number; activeMs: number; boundary: CheckpointBoundary | null }) {
  return input.boundary !== null
    || input.operationsSinceCheckpoint >= CHECKPOINT_OPERATION_INTERVAL
    || input.activeMs >= CHECKPOINT_ACTIVE_MS;
}
```

Store complete validated snapshots in checkpoints; ordinary history remains patch-based. Named versions are not passed to automatic compaction.

- [ ] **Step 4: Run checkpoint and history tests**

Run: `npm test -- src/domain/project/__tests__/checkpoints.test.ts src/domain/editor/__tests__/history.test.ts`

Expected: PASS.

- [ ] **Step 5: Run the A1 focused gate**

Run:

```bash
npm run lint
npm test -- src/domain/project src/domain/editor src/editor/store
git diff --check
npm run graphify:update
```

Expected: lint and focused tests PASS; Graphify update exits 0.

- [ ] **Step 6: Commit checkpoint policy**

```bash
git add src/domain/project src/domain/editor src/editor/store package.json package-lock.json
git commit -m "feat: complete durable project history domain"
```
