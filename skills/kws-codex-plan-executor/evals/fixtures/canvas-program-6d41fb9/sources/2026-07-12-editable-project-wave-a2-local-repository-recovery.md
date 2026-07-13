# Editable Project Wave A2 Local Repository and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist project heads, reversible operations, checkpoints, versions, and resources transactionally; migrate current IndexedDB documents; recover crashes; and enforce one local writer tab.

**Architecture:** A versioned `ProjectRepository` replaces direct document saves while the old adapter remains a temporary facade. The editor emits ordered durable mutations, a commit coordinator serializes them into one IndexedDB transaction per revision, and pure recovery/lease services remain testable without React or a real browser lock manager.

**Tech Stack:** TypeScript 5, IndexedDB/idb 8, Zustand 5, React 19, Vitest 3, fake-indexeddb 6, Playwright 1.50, Web Locks, BroadcastChannel, StorageManager.

## Global Constraints

- Execute after A1 and before existing Wave 2.
- Preserve every legacy `documents` and `assets` record until a validated project migration succeeds.
- A durable mutation updates project head, operation cursor, new operation, and resource references in one transaction.
- Do not debounce operation-journal durability. Snapshot/checkpoint work may be scheduled separately.
- Local status, external-file freshness, and future server status are separate state fields.
- A failed commit keeps the in-memory document, exposes retry/emergency export, and never acknowledges the mutation.
- Retain 200 operations, 20 automatic checkpoints, named versions, and five seven-day discarded branches.
- Only one tab writes a project; readers receive revision notifications and reload immutable snapshots.
- Run `graphify update .` after the wave.

---

### Task 1: Define durable mutation and repository contracts

**Files:**
- Create: `src/persistence/projectRepository.ts`
- Create: `src/persistence/__tests__/projectRepositoryContract.ts`
- Test: `src/persistence/__tests__/projectRepositoryContract.test.ts`

**Interfaces:**
- Consumes: `ProjectEnvelope`, `DesignDocument`, `HistoryEntry`, `DurableProjectMutation`, checkpoint/version types from A1.
- Produces: `LoadedProject`, `ProjectSummary`, `ResourceRecord`, `ProjectRepository`, reusable `runProjectRepositoryContract(factory)`.

- [ ] **Step 1: Write the repository contract RED**

```ts
export async function runProjectRepositoryContract(createRepository: () => Promise<ProjectRepository>) {
  const repository = await createRepository();
  const initial = fixtureProject("project-1", 0);
  await repository.createProject(initial);
  await repository.commitMutation(fixtureMutation(initial, { nextRevision: 1 }));
  const loaded = await repository.loadProject("project-1");

  expect(loaded.snapshot.envelope.revision).toBe(1);
  expect(loaded.history.past).toHaveLength(1);
  expect(loaded.history.resources).toEqual(loaded.snapshot.resources);
  await expect(repository.commitMutation(fixtureMutation(initial, { expectedRevision: 0, nextRevision: 1 })))
    .rejects.toThrow("revision conflict");
}
```

- [ ] **Step 2: Run the repository contract RED**

Run: `npm test -- src/persistence/__tests__/projectRepositoryContract.test.ts`

Expected: FAIL because repository contracts do not exist.

- [ ] **Step 3: Define the exact mutation and repository interfaces**

```ts
// src/persistence/projectRepository.ts
import type { AssetBlob, LocalAsset } from "./adapter";
import type { HistoryState } from "@/domain/editor/history";
import type { DurableProjectMutation } from "@/domain/project/mutation";
import type { ProjectSnapshot } from "@/domain/project/types";
import type { ProjectResourceIndex } from "@/domain/project/resources";
import type { ProjectCheckpoint, NamedProjectVersion } from "@/domain/project/checkpoints";

export type ProjectSummary = {
  projectId: string;
  lineageId: string;
  title: string;
  revision: number;
  modifiedAt: string;
  thumbnailHash: string | null;
};

export type ResourceRecord = {
  hash: string;
  mimeType: string;
  byteLength: number;
  createdAt: string;
  blob: AssetBlob;
};

export type LoadedProject = {
  snapshot: ProjectSnapshot;
  history: HistoryState;
  checkpoints: ProjectCheckpoint[];
  namedVersions: NamedProjectVersion[];
};

export type LocalCommitReceipt = { projectId: string; revision: number; committedAt: string };
export type LocalCommitContext = { leaseToken: number | null };

export interface ProjectRepository {
  listProjects(): Promise<ProjectSummary[]>;
  createProject(snapshot: ProjectSnapshot): Promise<void>;
  loadProject(projectId: string): Promise<LoadedProject>;
  commitMutation(mutation: DurableProjectMutation, context?: LocalCommitContext): Promise<LocalCommitReceipt>;
  saveCheckpoint(projectId: string, checkpoint: ProjectCheckpoint): Promise<void>;
  saveNamedVersion(projectId: string, version: NamedProjectVersion): Promise<void>;
  deleteProject(projectId: string): Promise<void>;
  putResource(asset: LocalAsset): Promise<ResourceRecord>;
  getResource(hash: string): Promise<AssetBlob>;
  collectUnreferencedResources(projectId: string): Promise<string[]>;
}
```

- [ ] **Step 4: Add a minimal in-memory contract implementation in the test file**

The in-memory repository must clone inputs, enforce `expectedRevision`, store operations/branches by ID, and rebuild `past`/`future` plus `HistoryState.resources` from the stored head and cursor arrays. Use it only for the shared contract and later coordinator tests.

- [ ] **Step 5: Run the repository contract GREEN**

Run: `npm test -- src/persistence/__tests__/projectRepositoryContract.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit repository contracts**

```bash
git add src/persistence/projectRepository.ts src/persistence/__tests__
git commit -m "feat: define project repository contract"
```

---

### Task 2: Add IndexedDB v2 stores and atomic mutation commits

**Files:**
- Create: `src/persistence/indexedDbProjectRepository.ts`
- Test: `src/persistence/__tests__/indexedDbProjectRepository.test.ts`
- Modify: `src/persistence/indexedDbAdapter.ts`

**Interfaces:**
- Consumes: `ProjectRepository`, `DurableProjectMutation`.
- Produces: `createIndexedDbProjectRepository(dbName?)` and a compatibility `PersistenceAdapter` backed by it after migration.

- [ ] **Step 1: Write atomicity and conflict RED tests**

```ts
it("commits head and operation cursor atomically", async () => {
  const repository = createIndexedDbProjectRepository(uniqueDbName());
  const project = fixtureProject("project-1", 0);
  await repository.createProject(project);
  await repository.commitMutation(fixtureMutation(project, { nextRevision: 1 }));
  const loaded = await repository.loadProject("project-1");
  expect(loaded.snapshot.envelope.revision).toBe(1);
  expect(loaded.history.past.map((entry) => entry.operationId)).toEqual(["operation-1"]);
});

it("leaves the previous head readable when an operation write aborts", async () => {
  const repository = createFailingIndexedDbProjectRepository({ failStore: "operations" });
  await repository.createProject(fixtureProject("project-1", 0));
  await expect(repository.commitMutation(fixtureMutation(undefined, { nextRevision: 1 }))).rejects.toThrow();
  expect((await repository.loadProject("project-1")).snapshot.envelope.revision).toBe(0);
});
```

- [ ] **Step 2: Run IndexedDB v2 RED tests**

Run: `npm test -- src/persistence/__tests__/indexedDbProjectRepository.test.ts`

Expected: FAIL because the repository does not exist.

- [ ] **Step 3: Define v2 stores without deleting legacy stores**

```ts
const DB_VERSION = 2;
const PROJECTS_STORE = "projects";
const OPERATIONS_STORE = "operations";
const CHECKPOINTS_STORE = "checkpoints";
const VERSIONS_STORE = "versions";
const BRANCHES_STORE = "discardedBranches";
const RESOURCES_STORE = "resources";
const STAGING_STORE = "resourceStaging";
const OUTBOX_STORE = "outbox";
const LEASES_STORE = "projectLeases";

type StoredProjectHead = {
  projectId: string;
  envelope: ProjectEnvelope;
  document: DesignDocument;
  resources: ProjectResourceIndex;
  pastOperationIds: string[];
  futureOperationIds: string[];
  discardedBranchIds: string[];
  migrationSourceDocumentId?: string;
};
```

Create compound-key stores for operations/checkpoints/versions/discarded branches using `[projectId, id]`, and indexes by `projectId`. `projectLeases` is keyed by `projectId` and stores `{ projectId, ownerId, fencingToken, heartbeatAt, expiresAt }`. Keep legacy `documents` and `assets` stores untouched.

- [ ] **Step 4: Implement one-transaction compare-and-swap**

```ts
const tx = database.transaction([PROJECTS_STORE, OPERATIONS_STORE, BRANCHES_STORE, LEASES_STORE], "readwrite");
const head = await tx.objectStore(PROJECTS_STORE).get(mutation.projectId);
if (!head || head.envelope.revision !== mutation.expectedRevision) {
  tx.abort();
  throw new Error(`Project revision conflict: expected ${mutation.expectedRevision}`);
}
const activeLease = await tx.objectStore(LEASES_STORE).get(mutation.projectId);
if (activeLease && context?.leaseToken !== activeLease.fencingToken) {
  tx.abort();
  throw new Error("Project lease fence rejected");
}
if (mutation.appendedEntry) {
  await tx.objectStore(OPERATIONS_STORE).put({ projectId: mutation.projectId, ...mutation.appendedEntry });
}
for (const branch of mutation.discardedBranches) {
  await tx.objectStore(BRANCHES_STORE).put({ projectId: mutation.projectId, ...branch });
}
await tx.objectStore(PROJECTS_STORE).put({
  projectId: mutation.projectId,
  envelope: structuredClone(mutation.envelope),
  document: structuredClone(mutation.document),
  resources: structuredClone(mutation.resources),
  pastOperationIds: [...mutation.pastOperationIds],
  futureOperationIds: [...mutation.futureOperationIds],
  discardedBranchIds: mutation.discardedBranches.map(({ branchId }) => branchId),
});
await tx.done;
```

- [ ] **Step 5: Run the shared repository contract against IndexedDB**

Run: `npm test -- src/persistence/__tests__/projectRepositoryContract.test.ts src/persistence/__tests__/indexedDbProjectRepository.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit IndexedDB v2**

```bash
git add src/persistence/indexedDbProjectRepository.ts src/persistence/indexedDbAdapter.ts src/persistence/__tests__
git commit -m "feat: persist project revisions atomically"
```

---

### Task 3: Migrate legacy documents and asset IDs without data loss

**Files:**
- Create: `src/persistence/projectMigration.ts`
- Test: `src/persistence/__tests__/projectMigration.test.ts`
- Modify: `src/persistence/indexedDbProjectRepository.ts`

**Interfaces:**
- Consumes: legacy `StoredDocument`, legacy `StoredAsset`, current document migration.
- Produces: `migrateLegacyProject(documentId, repositoryDb)`, `LegacyMigrationReport`.

- [ ] **Step 1: Write non-destructive migration RED tests**

```ts
it("migrates one legacy document once and retains legacy source records", async () => {
  const dbName = await seedLegacyDatabase({ document: legacyV2Document(), assets: [legacyUpload()] });
  const repository = createIndexedDbProjectRepository(dbName);
  const first = await repository.loadProject("legacy-document-1");
  const second = await repository.loadProject("legacy-document-1");

  expect(first.snapshot.envelope).toMatchObject({ projectId: "legacy-document-1", lineageId: "legacy-document-1" });
  expect(second.snapshot.envelope.projectId).toBe(first.snapshot.envelope.projectId);
  expect(await readLegacyDocument(dbName, "legacy-document-1")).toBeDefined();
  expect(first.snapshot.document.assets[0].id).toBe("asset-upload-1");
  expect(first.snapshot.resources.assets["asset-upload-1"].expectedHash).toMatch(/^[a-f0-9]{64}$/);
  expect(Object.values(first.snapshot.resources.fonts).every((font) => font.state === "unresolved")).toBe(true);
});
```

- [ ] **Step 2: Run migration RED tests**

Run: `npm test -- src/persistence/__tests__/projectMigration.test.ts`

Expected: FAIL because lazy migration does not exist.

- [ ] **Step 3: Implement validated lazy migration**

Migration steps:

```ts
const migratedDocument = migrateDocument(legacyDocument);
assertDesignDocument(migratedDocument);
const snapshot = createProjectSnapshot(migratedDocument, {
  projectId: migratedDocument.documentId,
  lineageId: migratedDocument.documentId,
  origin: { kind: "imported", sourceName: "legacy-indexeddb" },
});
await repository.createProject(snapshot);
```

Hash uploaded/bundled asset bytes into the new resource store, keep each original document `asset.id`, and bind that ID to the exact content hash in `ProjectResourceIndex`. Create explicit unresolved font bindings for legacy family/weight/italic usages because a family name is insufficient to identify bytes; never guess from an installed same-name font. Set `migrationSourceDocumentId` so a repeated load is idempotent. Never delete legacy stores in this wave.

- [ ] **Step 4: Run migration and existing persistence regressions**

Run: `npm test -- src/persistence/__tests__/projectMigration.test.ts src/persistence/__tests__/indexedDbAdapter.test.ts src/domain/document/__tests__/document.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit lazy migration**

```bash
git add src/persistence/projectMigration.ts src/persistence/indexedDbProjectRepository.ts src/persistence/__tests__/projectMigration.test.ts
git commit -m "feat: migrate local designs into projects"
```

---

### Task 4: Serialize editor mutations through a durable commit coordinator

**Files:**
- Create: `src/project/commit/ProjectCommitCoordinator.ts`
- Create: `src/project/commit/useProjectCommitCoordinator.ts`
- Create: `src/project/commit/storageDurability.ts`
- Test: `src/project/commit/__tests__/ProjectCommitCoordinator.test.ts`
- Test: `src/project/commit/__tests__/storageDurability.test.ts`
- Modify: `src/editor/store/editorStore.ts`
- Modify: `src/editor/hooks/useAutosave.ts`
- Modify: `src/editor/hooks/useSaveCoordinator.ts`

**Interfaces:**
- Consumes: `EditorState.durabilityQueue: DurableProjectMutation[]` and `acknowledgeDurabilityMutation(mutationId)` from A1, `ProjectRepository.commitMutation`.
- Produces: ordered `ProjectCommitCoordinator`, local durability status, retry, flush, emergency-export readiness, and a lease-token provider hook used by Task 7.

- [ ] **Step 1: Write ordering, failure, and retry RED tests**

```ts
it("never commits revision 2 before revision 1", async () => {
  const repository = deferredRepository();
  const coordinator = createProjectCommitCoordinator(repository);
  const first = coordinator.enqueue(mutation(0, 1));
  const second = coordinator.enqueue(mutation(1, 2));
  expect(repository.calls).toEqual([1]);
  repository.resolve(1);
  await first;
  expect(repository.calls).toEqual([1, 2]);
  repository.resolve(2);
  await second;
});

it("keeps a failed mutation queued for explicit retry", async () => {
  const coordinator = createProjectCommitCoordinator(failingRepository());
  await expect(coordinator.enqueue(mutation(0, 1))).rejects.toThrow("quota");
  expect(coordinator.snapshot()).toMatchObject({ status: "error", failedRevision: 1 });
});

it("reports best-effort storage honestly when persistence is denied", async () => {
  const result = await assessStorageDurability(fakeStorageManager({ persisted: false, persistResult: false }));
  expect(result).toMatchObject({ durability: "best-effort", evictionRisk: true });
});

it("blocks a large staging write before quota exhaustion", async () => {
  const result = await preflightStorage(fakeStorageManager({ quota: 1_000, usage: 900 }), { requiredBytes: 200 });
  expect(result.kind).toBe("insufficient");
});
```

- [ ] **Step 2: Run coordinator RED tests**

Run: `npm test -- src/project/commit/__tests__/ProjectCommitCoordinator.test.ts`

Expected: FAIL because the coordinator does not exist.

- [ ] **Step 3: Implement serialized commits**

Use one FIFO queue per project. Acknowledge `mutationId` in the store only after `commitMutation` succeeds. Publish local states `unsaved | saving | saved | error`. `flush()` waits for the current project queue. `retry()` reuses the same mutation and idempotent local key. Accept `getLeaseToken(projectId): number | null`; Task 7 connects the lease coordinator, while tests before Task 7 return `null`.

`storageDurability.ts` wraps `navigator.storage.persisted()`, user-gesture-triggered `persist()`, and `estimate()`. Expose `persistent | best-effort | unavailable` separately from save status. Persistence denial never claims data is safe; it surfaces portable-backup guidance. Before package/template/resource staging, require estimated free space ≥ incoming bytes + 10% + 64 MiB headroom. `QuotaExceededError` keeps the in-memory head and failed mutation queue, runs only unreachable staging cleanup, then offers retry and emergency `.canvasclone` export from the immutable in-memory snapshot.

```ts
while (queue.length > 0 && !stopped) {
  const mutation = queue[0];
  publish({ status: "saving", revision: mutation.envelope.revision });
  try {
    await repository.commitMutation(mutation, { leaseToken: getLeaseToken(mutation.projectId) });
    queue.shift();
    acknowledge(mutation.mutationId);
    publish({ status: queue.length ? "saving" : "saved", revision: mutation.envelope.revision });
  } catch (error) {
    publish({ status: "error", revision: mutation.envelope.revision, error });
    break;
  }
}
```

- [ ] **Step 4: Replace debounced document autosave with mutation durability**

`useAutosave` no longer waits 800 ms to protect a document change. It feeds the store's durable-mutation queue into the coordinator. Keep `useSaveCoordinator` as a compatibility facade exposing `saveNow`, `retryLatest`, and `flushCurrent` until B2 replaces the top-bar API.

- [ ] **Step 5: Run coordinator and save regressions**

Run: `npm test -- src/project/commit src/editor/hooks/__tests__/useSaveCoordinator.test.tsx src/editor/components/__tests__/documentLoadSave.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit durable coordination**

```bash
git add src/project/commit src/editor/store/editorStore.ts src/editor/hooks
git commit -m "feat: commit editor revisions durably"
```

---

### Task 5: Persist checkpoints, versions, compaction, and resource collection

**Files:**
- Create: `src/project/checkpoint/CheckpointCoordinator.ts`
- Create: `src/project/checkpoint/resourceReachability.ts`
- Test: `src/project/checkpoint/__tests__/CheckpointCoordinator.test.ts`
- Modify: `src/persistence/indexedDbProjectRepository.ts`

**Interfaces:**
- Consumes: A1 checkpoint policy, `ProjectRepository`.
- Produces: `CheckpointCoordinator.observe(commit)`, named-version persistence, reachability-based garbage collection.

- [ ] **Step 1: Write trigger and reachability RED tests**

Cover 20 operations, five active minutes, all named boundaries, 20 automatic retention, named-version immunity, five seven-day discarded branches, and resources referenced only by retained history.

```ts
expect(reachableResourceHashes({ current, operations, checkpoints, namedVersions, discardedBranches }))
  .toEqual(new Set(["hash-current", "hash-history", "hash-version"]));
```

- [ ] **Step 2: Run checkpoint coordinator RED tests**

Run: `npm test -- src/project/checkpoint/__tests__/CheckpointCoordinator.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement checkpoint scheduling and compaction**

Checkpoint work runs after the head mutation is durable. It creates a complete validated snapshot, stores it, then trims eligible operations/checkpoints in a second transaction. If compaction fails, keep the durable head and retry later; never roll it back.

- [ ] **Step 4: Implement resource reachability before deletion**

Only delete a content hash absent from current document, 200 retained operations, 20 automatic checkpoints, all named versions, retained discarded branches, staging claims, and future outbox records.

- [ ] **Step 5: Run checkpoint/repository tests**

Run: `npm test -- src/project/checkpoint src/persistence/__tests__/indexedDbProjectRepository.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit checkpoint persistence**

```bash
git add src/project/checkpoint src/persistence/indexedDbProjectRepository.ts
git commit -m "feat: persist project checkpoints and versions"
```

---

### Task 6: Recover valid state from damaged heads and journal tails

**Files:**
- Create: `src/project/recovery/recoverProject.ts`
- Create: `src/project/recovery/types.ts`
- Test: `src/project/recovery/__tests__/recoverProject.test.ts`
- Modify: `src/persistence/indexedDbProjectRepository.ts`

**Interfaces:**
- Consumes: stored head, checkpoints, ordered operations, document validation and hashes.
- Produces: `RecoveryResult = clean | recovered-copy | degraded-history | unrecoverable`.

- [ ] **Step 1: Write the recovery matrix RED**

Test clean head, truncated final operation, wrong base hash, invalid current with valid checkpoint, and no valid canonical state.

```ts
expect(recoverProject(corruptTailFixture())).toMatchObject({
  kind: "degraded-history",
  lastValidOperationId: "operation-19",
  quarantinedOperationIds: ["operation-20"],
});
```

- [ ] **Step 2: Run recovery RED tests**

Run: `npm test -- src/project/recovery/__tests__/recoverProject.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement fail-closed recovery**

Never mutate stored records in `recoverProject`. Return a candidate snapshot and diagnostics. Persist a candidate only through `repository.createProject()` with a new project ID and the same lineage after explicit user acceptance in B2.

- [ ] **Step 4: Run recovery and hash regressions**

Run: `npm test -- src/project/recovery src/domain/project/__tests__/hash.test.ts src/domain/project/__tests__/patch.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit recovery services**

```bash
git add src/project/recovery src/persistence/indexedDbProjectRepository.ts
git commit -m "feat: recover damaged local projects safely"
```

---

### Task 7: Enforce one writer tab and live read-only followers

**Files:**
- Create: `src/project/lease/EditLeaseCoordinator.ts`
- Create: `src/project/lease/browserLeasePlatform.ts`
- Test: `src/project/lease/__tests__/EditLeaseCoordinator.test.ts`
- Modify: `src/editor/store/editorStore.ts`

**Interfaces:**
- Consumes: project ID, `navigator.locks`, BroadcastChannel-compatible platform.
- Produces: `EditLeaseState`, `acquire`, `requestTransfer`, `release`, monotonic fencing tokens, revision notifications, and heartbeat fallback.

- [ ] **Step 1: Write lease RED tests with fake platform**

```ts
it("grants one writer and makes the second context a live reader", async () => {
  const platform = fakeLeasePlatform();
  const first = createEditLeaseCoordinator(platform, "project-1", "tab-1");
  const second = createEditLeaseCoordinator(platform, "project-1", "tab-2");
  expect(await first.acquire()).toMatchObject({ mode: "writer" });
  expect(await second.acquire()).toMatchObject({ mode: "reader", writerTabId: "tab-1" });
});

it("flushes before orderly transfer", async () => {
  const events: string[] = [];
  const result = await reader.requestTransfer({ flushWriter: async () => { events.push("flush"); return true; } });
  expect(events).toEqual(["flush"]);
  expect(result.mode).toBe("writer");
});

it("rejects a stale writer after lease takeover", async () => {
  const stale = await first.acquire();
  platform.advancePastExpiry();
  const current = await second.acquire();
  expect(current.fencingToken).toBeGreaterThan(stale.fencingToken);
  await expect(repository.commitMutation(mutation(1, 2), { leaseToken: stale.fencingToken }))
    .rejects.toThrow("lease fence");
});
```

- [ ] **Step 2: Run lease RED tests**

Run: `npm test -- src/project/lease/__tests__/EditLeaseCoordinator.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement platform and fallback**

Use `navigator.locks.request("canvas-project:<projectId>", { mode: "exclusive", ifAvailable: true })` when available and hold the callback open until explicit release. In every environment, acquire/renew the `projectLeases` row through one IndexedDB read-write transaction and increment its monotonic fencing token on takeover. Every repository commit checks the active token in the same transaction as the head write, so a suspended or stale tab cannot resume writing after transfer. A 10-second expiry permits takeover only after a fresh transactional read; heartbeat every 3 seconds while visible and on visibility/page lifecycle changes.

Broadcast only project ID, revision, writer tab ID, fencing token, transfer request/ack, and timestamps; readers reload the repository snapshot instead of accepting document bytes from messages. Prefer `BroadcastChannel`; when unavailable, emit the same small notification through a `localStorage` key and the cross-tab `storage` event. Notifications are hints, never authority—the IndexedDB lease and revision checks decide ownership.

- [ ] **Step 4: Add editor lease state without final UX**

Add `editLease: "writer" | "reader" | "transfer-pending" | "recovering"` and `leaseFencingToken: number | null` to the store. Connect the token provider from Task 4. Reject persistent dispatches in reader mode with a typed `READ_ONLY_PROJECT` error; allow selection and viewport operations. Transfer succeeds only after writer flush, lease release, reader transactional takeover, and repository revision reload; otherwise both tabs stay in their prior safe modes.

- [ ] **Step 5: Run lease and editor tests**

Run: `npm test -- src/project/lease src/editor/store/__tests__/editorStore.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit lease foundation**

```bash
git add src/project/lease src/editor/store/editorStore.ts src/editor/store/__tests__/editorStore.test.ts
git commit -m "feat: coordinate project editing across tabs"
```

---

### Task 8: Prove local reopen, 200-operation history, crash recovery, and tab transfer

**Files:**
- Modify: `tests/e2e/persistence-export.spec.ts`
- Create: `tests/e2e/project-local-recovery.spec.ts`
- Modify: `tests/e2e/helpers/editor.ts`
- Modify: `package.json`

**Interfaces:**
- Consumes: complete A2 local project stack.
- Produces: focused Playwright evidence and a `test:e2e:project-local` script.

- [ ] **Step 1: Add focused E2E scenarios**

```ts
test("reopens with 200 undoable operations", async ({ page }) => {
  await openEditor(page);
  await seedProjectWithHistory(page, { operations: 205 });
  await page.reload();
  await expect(page.getByLabel("실행 취소")).toBeEnabled();
  await undoTimes(page, 200);
  await expect(page.getByLabel("실행 취소")).toBeDisabled();
});
```

Add browser contexts for one writer/one reader, orderly transfer, stale writer close, and repository reload after a deliberately truncated final operation fixture.

- [ ] **Step 2: Run focused E2E RED/GREEN while implementing helpers**

Run: `npx playwright test tests/e2e/project-local-recovery.spec.ts --project=parity-1920 --workers=1`

Expected final result: PASS with no console or unhandled errors.

- [ ] **Step 3: Run the A2 focused gate**

Run:

```bash
npm run lint
npm test -- src/domain/project src/domain/editor src/persistence src/project src/editor/store src/editor/hooks
npx playwright test tests/e2e/project-local-recovery.spec.ts --project=parity-1920 --workers=1
git diff --check
npm run graphify:update
```

Expected: all commands PASS.

- [ ] **Step 4: Commit A2 evidence**

```bash
git add src tests/e2e package.json package-lock.json
git commit -m "test: prove durable local project recovery"
```
