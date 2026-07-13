# Editable Project Wave C2 Server Contracts and Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove future project sync and template delivery contracts with deterministic fakes, local outbox/conflict behavior, immutable DB/S3/CDN fixtures, signed catalog manifests, lifecycle handling, and final parity-ledger integration.

**Architecture:** No production server is introduced. `RemoteProjectGateway` and `CatalogGateway` are narrow ports with strict DTOs; deterministic in-memory fakes emulate compare-and-swap, idempotency, upload continuation, immutable versions, signatures, offline cache, and unpublication. Static contract fixtures document the later relational/S3 implementation and are validated in CI.

**Tech Stack:** TypeScript 5, IndexedDB ProjectRepository, Web Crypto signature interface, Vitest 3, Testing Library, Playwright 1.50, Node contract scripts.

## Global Constraints

- Execute after C1 and before existing Wave 6.
- Do not add auth SDKs, HTTP clients, database clients, AWS SDKs, S3 calls, CDNs, web sockets, CRDTs, or production endpoints.
- Server DTOs are JSON-compatible, schema-versioned, tenant-aware, and independent of React/Zustand.
- Project push uses `baseRevision`, immutable mutation IDs, and idempotency keys; divergent heads are preserved, never auto-merged.
- Template versions and content-addressed object keys are immutable; publication creates a new version and updates a DB pointer atomically.
- Server template/page-fragment manifests require a trusted signature and exact hashes before cache or application.
- Applied resources are claimed by the project so later unpublication cannot break existing work.
- Telemetry and diagnostics never include document text, thumbnails, resource bytes, filenames, URLs, template metadata, or reversible patch payloads without separate explicit consent.
- C2 adds evidence rows but does not make the final completion claim; existing Wave 6 remains final.
- Run `graphify update .` after the wave.

---

### Task 1: Define remote project sync contracts and deterministic fake

**Files:**
- Create: `src/sync/types.ts`
- Create: `src/sync/RemoteProjectGateway.ts`
- Create: `src/sync/testing/FakeRemoteProjectGateway.ts`
- Test: `src/sync/__tests__/RemoteProjectGateway.test.ts`

**Interfaces:**
- Consumes: project envelope, durable mutations, resource hashes.
- Produces: pull/push/upload DTOs, `RemoteProjectGateway`, deterministic fake.

- [ ] **Step 1: Write compare-and-swap and idempotency RED tests**

```ts
it("accepts one base revision and returns the same receipt for the same idempotency key", async () => {
  const gateway = new FakeRemoteProjectGateway(seedRemoteProject({ revision: 4 }));
  const context = serverContext({ tenantId: "tenant-1", actorId: "user-1" });
  const request = pushRequest({ baseRevision: 4, nextRevision: 5, idempotencyKey: "mutation-5" });
  const first = await gateway.push(context, request);
  const second = await gateway.push(context, request);
  expect(first).toEqual(second);
  expect(await gateway.head(context, "project-1")).toMatchObject({ revision: 5 });
});

it("preserves both heads on a stale base", async () => {
  const gateway = new FakeRemoteProjectGateway(seedRemoteProject({ revision: 5 }));
  expect(await gateway.push(serverContext(), pushRequest({ baseRevision: 4, nextRevision: 5 }))).toMatchObject({
    kind: "conflict",
    remoteRevision: 5,
  });
});
```

- [ ] **Step 2: Run sync contract RED tests**

Run: `npm test -- src/sync/__tests__/RemoteProjectGateway.test.ts`

Expected: FAIL.

- [ ] **Step 3: Define exact DTOs**

```ts
export type PushProjectRequest = {
  projectId: string;
  lineageId: string;
  tenantId: string;
  baseRevision: number;
  nextRevision: number;
  idempotencyKey: string;
  mutationIds: string[];
  headHash: string;
  fidelity: PackageManifestV1["fidelity"];
  referencedResourceHashes: string[];
  availableUploadHashes: string[];
  unresolvedResourceHashes: string[];
};

export type ServerRequestContext = {
  tenantId: string;
  actorId: string;
};

export type PushProjectResult =
  | { kind: "accepted"; remoteRevision: number; receiptId: string; missingResourceHashes: string[] }
  | { kind: "duplicate"; remoteRevision: number; receiptId: string }
  | { kind: "conflict"; remoteRevision: number; remoteHeadHash: string }
  | { kind: "retryable"; retryAfterMs: number; code: string };

export interface RemoteProjectGateway {
  head(context: ServerRequestContext, projectId: string): Promise<RemoteProjectHead | null>;
  pull(context: ServerRequestContext, projectId: string, revision?: number): Promise<RemoteProjectBundle>;
  push(context: ServerRequestContext, request: PushProjectRequest): Promise<PushProjectResult>;
  beginResourceUpload(context: ServerRequestContext, request: BeginResourceUploadRequest): Promise<ResourceUploadSession>;
  completeResourceUpload(context: ServerRequestContext, request: CompleteResourceUploadRequest): Promise<ResourceUploadResult>;
}
```

`headHash` is A1 `hashProjectContent({ document, resources })`, not a document-only hash, so an exact font/asset binding change participates in compare-and-swap conflicts.

- [ ] **Step 4: Implement deterministic fake behavior**

The fake stores accepted requests by `(tenantId, projectId, idempotencyKey)`, rejects context/payload tenant mismatch before lookup, rejects stale bases, exposes scripted retryable failures, tracks upload sessions and exact checksums, and never silently overwrites a remote head. A repair-required private project revision may sync so edits are backed up; the fake records unresolved hashes, asks for only locally available hashes missing on the server, and upgrades fidelity only when exact bytes are verified. Publication/template conversion remains blocked. Add a cross-tenant test proving identical project IDs/hashes cannot reveal metadata, existence, bytes, or deduplication state.

- [ ] **Step 5: Run sync contract GREEN tests**

Run: `npm test -- src/sync/__tests__/RemoteProjectGateway.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit sync contracts**

```bash
git add src/sync
git commit -m "feat: define project sync contracts"
```

---

### Task 2: Process the local outbox and surface fast-forward/conflict states

**Files:**
- Create: `src/sync/SyncCoordinator.ts`
- Test: `src/sync/__tests__/SyncCoordinator.test.ts`
- Modify: `src/persistence/projectRepository.ts`
- Modify: `src/persistence/indexedDbProjectRepository.ts`
- Modify: `src/editor/store/editorStore.ts`

**Interfaces:**
- Consumes: durable local outbox and `RemoteProjectGateway`.
- Produces: `SyncCoordinator.runOnce`, online/offline/pending/syncing/synced/error/conflict state, conflict copies.

- [ ] **Step 1: Write sync decision RED tests**

```ts
it.each([
  ["remote-only", "fast-forward"],
  ["local-only", "push"],
  ["same-hash", "synced"],
  ["divergent", "conflict"],
])("classifies %s as %s", async (fixture, expected) => {
  expect((await coordinatorFor(fixture).runOnce("project-1")).kind).toBe(expected);
});

it("retains retryable outbox items in order", async () => {
  const coordinator = coordinatorFor("retry-then-accept");
  expect(await coordinator.runOnce("project-1")).toMatchObject({ kind: "retrying" });
  expect((await repository.listOutbox("project-1")).map((item) => item.revision)).toEqual([5, 6]);
});
```

- [ ] **Step 2: Run SyncCoordinator RED tests**

Run: `npm test -- src/sync/__tests__/SyncCoordinator.test.ts`

Expected: FAIL.

- [ ] **Step 3: Extend repository outbox operations**

```ts
interface ProjectRepository {
  enqueueOutbox(item: ProjectOutboxItem): Promise<void>;
  listOutbox(projectId: string): Promise<ProjectOutboxItem[]>;
  acknowledgeOutbox(projectId: string, throughRevision: number, receiptId: string): Promise<void>;
  saveRemoteTracking(projectId: string, tracking: RemoteTracking): Promise<void>;
  createConflictCopy(projectId: string, source: "local" | "remote", head: ProjectSnapshot): Promise<string>;
}
```

Add outbox records only after local commit succeeds. Index by `[projectId, revision]` and retain order.

- [ ] **Step 4: Implement fail-explicit synchronization**

If remote is a direct descendant and local has no pending mutations, pull and fast-forward after checkpoint. If local is direct descendant, push in order. If both changed, stop, preserve heads, and publish conflict state. Upload missing resources before acknowledging the project revision. Retryable failures retain outbox and use fake-provided backoff.

- [ ] **Step 5: Run sync/repository GREEN tests**

Run: `npm test -- src/sync src/persistence/__tests__/indexedDbProjectRepository.test.ts src/editor/store/__tests__/editorStore.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit outbox integration**

```bash
git add src/sync src/persistence src/editor/store/editorStore.ts src/editor/store/__tests__/editorStore.test.ts
git commit -m "feat: coordinate project sync outbox"
```

---

### Task 3: Define signed catalog and immutable template/page-fragment version contracts

**Files:**
- Create: `src/catalog/gateway/types.ts`
- Create: `src/catalog/gateway/CatalogGateway.ts`
- Create: `src/catalog/gateway/manifestSignature.ts`
- Create: `src/catalog/gateway/testing/FakeCatalogGateway.ts`
- Test: `src/catalog/gateway/__tests__/CatalogGateway.test.ts`

**Interfaces:**
- Consumes: catalog metadata, B1 package manifest/integrity, trusted public keys.
- Produces: list/get/download/cache DTOs, signature verifier port, deterministic fake.

- [ ] **Step 1: Write signature, immutability, and offline RED tests**

```ts
it("rejects a changed manifest under the same signed version", async () => {
  const gateway = fakeCatalog({ manifest: signedManifest("template-1", "1") });
  gateway.tamperManifest("template-1", "1");
  await expect(gateway.getVersion(catalogContext(), "template-1", "1")).rejects.toThrow("CATALOG_SIGNATURE_INVALID");
});

it("serves a fully cached immutable version offline", async () => {
  const gateway = fakeCatalog({ online: false, cache: [cachedTemplate("template-1", "1")] });
  expect(await gateway.getVersion(catalogContext(), "template-1", "1")).toMatchObject({ source: "cache", version: "1" });
});
```

- [ ] **Step 2: Run catalog contract RED tests**

Run: `npm test -- src/catalog/gateway/__tests__/CatalogGateway.test.ts`

Expected: FAIL.

- [ ] **Step 3: Define exact catalog contracts**

```ts
export type CatalogItemKind = "template" | "page-fragment";

export type CatalogItemSummary = {
  itemId: string;
  kind: CatalogItemKind;
  currentVersion: string;
  title: string;
  description: string;
  categoryIds: string[];
  visibility: "public" | "private" | "unlisted";
  preview: { url: string; sha256: string; width: number; height: number };
  requiredBytes: number;
};

export type CatalogAccessContext = {
  tenantId: string | null;
  actorId: string | null;
  entitlementIds: string[];
};

export interface CatalogGateway {
  list(context: CatalogAccessContext, query: CatalogQuery): Promise<CatalogPage>;
  getVersion(context: CatalogAccessContext, itemId: string, version: string): Promise<VerifiedCatalogItem>;
  downloadMissing(context: CatalogAccessContext, item: VerifiedCatalogItem, localHashes: Set<string>, signal?: AbortSignal): Promise<DownloadedCatalogResources>;
}
```

`SignatureVerifier.verify` consumes canonical manifest bytes, integrity root, signature bytes, and key ID. C2 tests use deterministic fixture keys; Phase D supplies rotated trusted keys.

- [ ] **Step 4: Implement fake immutable versions and cache**

The fake rejects the same item/version with a different manifest hash or kind, reports download-required while offline and uncached, emits unavailable for unpublished versions not already cached, validates tenant/private visibility and entitlements before revealing metadata or download hashes, and validates each downloaded content hash. It runs the same signature/cache/security contract for templates and page fragments. Cached private versions remain usable only for the local account scope that originally authorized/cache-claimed them.

- [ ] **Step 5: Run catalog GREEN tests**

Run: `npm test -- src/catalog/gateway/__tests__/CatalogGateway.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit catalog contracts**

```bash
git add src/catalog/gateway
git commit -m "feat: define signed editable catalog contracts"
```

---

### Task 4: Codify relational metadata and S3/CDN object layout as fixtures

**Files:**
- Create: `src/server-contracts/templateStorage.ts`
- Create: `src/server-contracts/projectStorage.ts`
- Create: `src/server-contracts/fixtures/template-version-v1.json`
- Create: `src/server-contracts/fixtures/project-revision-v1.json`
- Create: `scripts/validate-project-contracts.mjs`
- Create: `scripts/validate-project-contracts.test.mjs`
- Modify: `package.json`

**Interfaces:**
- Consumes: approved DB/S3 design, C2 DTOs, and A1 RFC 8785 canonical JSON golden vectors.
- Produces: typed object-key builders, fixture validators, `test:project-contracts` script.

- [ ] **Step 1: Write object-key and fixture RED tests**

```js
test("published keys are immutable version keys", () => {
  assert.equal(templateManifestKey("tv_01"), "published/template-versions/tv_01/manifest.json");
  assert.equal(contentAddressedAssetKey("abcdef"), "cas/assets/sha256/ab/abcdef");
  assert.equal(projectBundleKey("tenant_01", "project_01", "pr_0007"), "tenants/tenant_01/projects/project_01/revisions/pr_0007/bundle.canvasclone");
});

test("rejects a mutable current template key", () => {
  assert.throws(() => validateTemplateStorageFixture({ objectKey: "templates/current/manifest.json" }), /immutable version/);
});

test("rejects a project object key outside its tenant scope", () => {
  assert.throws(() => validateProjectStorageFixture({ tenantId: "tenant_01", objectKey: projectBundleKey("tenant_02", "project_01", "pr_0007") }), /tenant scope/);
});
```

- [ ] **Step 2: Run contract-script RED tests**

Run: `node --test scripts/validate-project-contracts.test.mjs`

Expected: FAIL, including any server-contract hash implementation that disagrees with the shared RFC 8785 golden vectors.

- [ ] **Step 3: Define storage contracts**

Catalog metadata records: item ID, kind (`template` or `page-fragment`), tenant/owner, status, visibility, current version ID. Version records: immutable version ID/number, item kind, manifest hash, schema versions, S3 prefix, signer key ID, published time. Resource joins: version ID, content hash, role, required, license ID, bytes.

Project metadata records: project ID, tenant/owner, lineage ID, current revision ID/number, soft-delete state, created/updated time. Project-revision records: immutable revision ID/number, base revision, head hash, manifest hash, descriptor/current-document keys, optional materialized bundle key, schema versions, creator/idempotency key, byte counts, created time. Project-resource joins record revision ID, content hash, role, required, and license/provenance. The relational `current revision` pointer is the only mutable head; S3 revision objects and global CAS objects are immutable.

Object keys:

```ts
export const templateVersionPrefix = (versionId: string) => `published/template-versions/${safeId(versionId)}`;
export const templateManifestKey = (versionId: string) => `${templateVersionPrefix(versionId)}/manifest.json`;
export const templateDocumentKey = (versionId: string) => `${templateVersionPrefix(versionId)}/document.json`;
export const templateBundleKey = (versionId: string) => `${templateVersionPrefix(versionId)}/bundle.canvasclone`;
export const pageFragmentVersionPrefix = (versionId: string) => `published/page-fragment-versions/${safeId(versionId)}`;
export const pageFragmentBundleKey = (versionId: string) => `${pageFragmentVersionPrefix(versionId)}/bundle.canvasclone`;
export const contentAddressedAssetKey = (hash: string) => `cas/assets/sha256/${hash.slice(0, 2)}/${hash}`;
export const contentAddressedFontKey = (hash: string) => `cas/fonts/sha256/${hash.slice(0, 2)}/${hash}`;
export const projectRevisionPrefix = (tenantId: string, projectId: string, revisionId: string) =>
  `tenants/${safeId(tenantId)}/projects/${safeId(projectId)}/revisions/${safeId(revisionId)}`;
export const projectManifestKey = (tenantId: string, projectId: string, revisionId: string) =>
  `${projectRevisionPrefix(tenantId, projectId, revisionId)}/manifest.json`;
export const projectCurrentDocumentKey = (tenantId: string, projectId: string, revisionId: string) =>
  `${projectRevisionPrefix(tenantId, projectId, revisionId)}/document/current.json`;
export const projectOperationBatchKey = (tenantId: string, projectId: string, revisionId: string) =>
  `${projectRevisionPrefix(tenantId, projectId, revisionId)}/history/operations.ndjson`;
export const projectBundleKey = (tenantId: string, projectId: string, revisionId: string) =>
  `${projectRevisionPrefix(tenantId, projectId, revisionId)}/bundle.canvasclone`;
```

Template and page-fragment versions always materialize a complete immutable `bundle.canvasclone`. Frequent project autosave revisions store the small manifest/current document/operation batch and reference global CAS; they do not rebuild a resource-duplicating ZIP on every edit. Materialize the complete project bundle only for explicit download/export, named version, periodic server checkpoint, or retention compaction, record its hash/key on that immutable revision, and allow regeneration from immutable revision objects plus CAS.

The contract fixture requires private S3 origin access, short-lived actor/tenant/object-scoped upload/download grants, declared SHA-256 checksums, content length/type bounds, quarantine keys before verification, server-side hash revalidation, immutable cache keys/ETags, and CDN delivery only for published template previews/bundles. Project objects and private templates never use public object URLs. Global CAS deduplication is an internal storage optimization: authorization comes from tenant-owned resource joins, APIs never reveal cross-tenant hash existence, and licensed resources may opt out of cross-tenant physical deduplication. S3 bucket versioning/lifecycle is defense-in-depth, not the application revision model.

- [ ] **Step 4: Validate publication sequence in fixtures**

Template/page-fragment fixture states: draft DB row, quarantine upload ID, missing-hash upload requests, verified resources, generated preview/bundle/signature, atomic publish pointer. Failure at each state leaves the prior public version active.

Project fixture states: compare-and-swap reservation, missing-hash upload grants, quarantined uploads, checksum/security verification, immutable small revision objects, relational joins, and atomic current-revision pointer update. A separate idempotent materialization state produces/verifies a complete bundle only when required. Failure leaves the prior head active and retry with the same idempotency key returns the same reservation/receipt.

Retention fixtures keep current head, named versions, server checkpoints, the supported 200-operation window, active conflict copies, and legal/restore holds. Older compacted revisions become garbage-collection candidates only after a restore grace period. Quarantine/staging objects have short TTLs; CAS bytes delete only after every project/template/version/license join is absent and a second delayed reachability scan agrees. Soft deletion and template unpublication remove discovery/access pointers first, never bytes still claimed by an applied project.

- [ ] **Step 5: Run contract GREEN tests**

Run:

```bash
node --test scripts/validate-project-contracts.test.mjs
npm run test:project-contracts
```

Expected: PASS.

- [ ] **Step 6: Commit server storage fixtures**

```bash
git add src/server-contracts scripts/validate-project-contracts.mjs scripts/validate-project-contracts.test.mjs package.json
git commit -m "test: codify project server storage contracts"
```

---

### Task 5: Download, verify, cache, and apply catalog editable sources atomically

**Files:**
- Create: `src/catalog/gateway/CatalogEditableSourceService.ts`
- Test: `src/catalog/gateway/__tests__/CatalogEditableSourceService.test.ts`
- Modify: `src/domain/template/TemplateApplicationService.ts`
- Modify: `src/persistence/templateRepository.ts`
- Modify: `src/editor/templates/UserTemplatesView.tsx`

**Interfaces:**
- Consumes: `CatalogGateway`, local CAS/template repository, TemplateApplicationService.
- Produces: catalog card download states, verified local cache, atomic template/page-fragment apply.

- [ ] **Step 1: Write missing-hash and unpublication RED tests**

```ts
it("downloads only missing hashes before one atomic apply", async () => {
  const service = fixtureCatalogEditableSourceService({ kind: "template", localHashes: ["hash-a"], requiredHashes: ["hash-a", "hash-b"] });
  await service.apply("template-1", "1", destination(), { mode: "add-pages" });
  expect(gateway.downloadMissing).toHaveBeenCalledWith(expect.anything(), expect.anything(), new Set(["hash-a"]), expect.anything());
  expect(templateApplication.apply).toHaveBeenCalledWith(
    expect.anything(),
    expect.objectContaining({ resourceIndex: expectResourceHashes(["hash-a", "hash-b"]) }),
    expect.anything(),
  );
});

it("keeps an already applied project valid after template unpublication", async () => {
  const project = await applyThenUnpublish();
  expect(allResourcesResolve(await projectRepository.loadProject(project.projectId))).toBe(true);
});
```

- [ ] **Step 2: Run catalog service RED tests**

Run: `npm test -- src/catalog/gateway/__tests__/CatalogEditableSourceService.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement download and cache sequence**

List/preview may load independently. Application fetches the signed template or page-fragment manifest, checks local hashes, downloads missing bytes with progress/cancel, validates each hash/security result, stores immutable cached version/CAS bytes, normalizes through C1 `TemplateSource`, and then invokes one template/page-fragment command carrying the verified resource index. The editor commits bindings and pages in one durable mutation. Any failure before final commit leaves project unchanged; unclaimed immutable bytes remain garbage-collectable.

- [ ] **Step 4: Implement unpublication and offline states**

Uncached unpublished version is unavailable. Fully cached immutable version stays usable offline. Existing projects use their own exact resource index/CAS bytes and do not consult the catalog item on reopen.

- [ ] **Step 5: Run catalog/template GREEN tests**

Run: `npm test -- src/catalog/gateway src/domain/template src/persistence/__tests__/indexedDbTemplateRepository.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit catalog integration**

```bash
git add src/catalog/gateway src/domain/template/TemplateApplicationService.ts src/persistence/templateRepository.ts src/editor/templates/UserTemplatesView.tsx
git commit -m "feat: integrate verified server editable catalog"
```

---

### Task 6: Redact diagnostics and define stable project error families

**Files:**
- Create: `src/project/diagnostics/errorCodes.ts`
- Create: `src/project/diagnostics/createDiagnosticReport.ts`
- Test: `src/project/diagnostics/__tests__/createDiagnosticReport.test.ts`
- Modify: `src/editor/project/RecoveryDialog.tsx`
- Modify: `src/editor/resources/ResourceRepairCenter.tsx`

**Interfaces:**
- Consumes: package/migration/history/resource/repository/quota/lease/sync/catalog/export failures.
- Produces: stable user-safe codes and redacted diagnostic JSON.

- [ ] **Step 1: Write redaction RED tests**

```ts
it("never includes document content, filenames, URLs, bytes, or patches", () => {
  const report = JSON.stringify(createDiagnosticReport(privateFailureFixture()));
  for (const secret of ["private text", "hero.jpg", "https://private.example", "base64bytes", "replace /pages/0"]) {
    expect(report).not.toContain(secret);
  }
  expect(JSON.parse(report)).toMatchObject({ errorCode: "RESOURCE_HASH_MISMATCH", schemaVersions: expect.any(Object) });
});
```

- [ ] **Step 2: Run diagnostic RED tests**

Run: `npm test -- src/project/diagnostics/__tests__/createDiagnosticReport.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement stable error families**

Families: `PACKAGE_*`, `MIGRATION_*`, `HISTORY_*`, `RESOURCE_*`, `REPOSITORY_*`, `QUOTA_*`, `LEASE_*`, `SYNC_*`, `CATALOG_*`, `EXPORT_*`. Report schema includes versions, aggregate counts, byte ranges, redacted IDs, resource types/hashes, operation-family names, phase, and code only.

- [ ] **Step 4: Expose diagnostics from recovery and repair UI**

Default export contains no content. A future content-bearing support package remains absent; do not add a hidden option.

- [ ] **Step 5: Run diagnostic/component GREEN tests**

Run: `npm test -- src/project/diagnostics src/editor/project/__tests__ src/editor/resources/__tests__`

Expected: PASS.

- [ ] **Step 6: Commit redacted diagnostics**

```bash
git add src/project/diagnostics src/editor/project/RecoveryDialog.tsx src/editor/resources/ResourceRepairCenter.tsx
git commit -m "feat: add redacted project diagnostics"
```

---

### Task 7: Add project requirement families to the parity ledger and final gate

**Files:**
- Modify: `scripts/parity-matrix.mjs`
- Modify: `scripts/parity-matrix.test.mjs`
- Modify: `scripts/final-parity-gate.mjs`
- Modify: `scripts/final-parity-gate.test.mjs`
- Modify: `scripts/miricanvas-reference-lock.json`
- Modify: `docs/qa/design-editor-parity-matrix.md`

**Interfaces:**
- Consumes: focused A1-C2 test/evidence files.
- Produces: `DE-PROJECT`, `DE-HISTORY`, `DE-RECOVERY`, `DE-RESOURCE`, `DE-TEMPLATE-PORTABLE`, `DE-SERVER-CONTRACT`, `DE-MULTITAB`, `DE-PACKAGE-SECURITY`, `DE-PACKAGE-PERF` rows.

- [ ] **Step 1: Write ledger/final-gate RED tests**

Require every new family, owning spec section, focused unit/component/E2E evidence, browser coverage, and current source fingerprint. Final gate fails when any row is open, package fixtures are stale, project contract tests fail, or required browser/performance evidence is missing.

- [ ] **Step 2: Run contract RED tests**

Run: `npm run test:parity-contract && npm run test:parity-final-contract`

Expected: FAIL because new project rows are absent.

- [ ] **Step 3: Add rows and evidence routing**

Do not mark a row passed from control presence. Each row names exact unit/component/E2E/security/performance artifacts. Existing `DE-PERSIST`, `DE-TEMPLATE`, and `DE-EXPORT` rows link to stronger project requirements.

- [ ] **Step 4: Run parity contract GREEN tests**

Run: `npm run test:parity-contract && npm run test:parity-final-contract && npm run parity:progress`

Expected: contract tests PASS; progress reports implementation evidence state honestly and does not claim final completion.

- [ ] **Step 5: Commit ledger integration**

```bash
git add scripts docs/qa/design-editor-parity-matrix.md
git commit -m "test: track editable project quality evidence"
```

---

### Task 8: Prove fake sync/catalog contracts and hand off to final Wave 6

**Files:**
- Create: `tests/e2e/project-server-contracts.spec.ts`
- Modify: `tests/e2e/helpers/editor.ts`
- Modify: `package.json`

**Interfaces:**
- Consumes: complete C2 fake server integration.
- Produces: `test:e2e:project-server-contracts` and focused handoff evidence for Wave 6.

- [ ] **Step 1: Add fake sync workflows**

Cover local-only push, remote-only fast-forward, same-hash no-op, duplicate idempotency key, retryable 5xx, interrupted resource upload, stale base conflict, keep local/remote/both, and outbox persistence across reload.

- [ ] **Step 2: Add fake catalog workflows**

Cover signed manifest, tampered signature, missing hash download, progress/cancel, fully cached offline apply, uncached offline state, immutable version update, unpublication after apply, and broken version hidden without partial application.

- [ ] **Step 3: Run the C2 focused gate**

Run:

```bash
npm run lint
npm run test:project-contracts
npm test -- src/sync src/catalog/gateway src/server-contracts src/project/diagnostics
npx playwright test tests/e2e/project-server-contracts.spec.ts --project=parity-1920 --workers=1
npm run test:parity-contract
npm run test:parity-final-contract
git diff --check
npm run graphify:update
```

Expected: all commands PASS; parity progress remains non-final until existing Wave 6 executes.

- [ ] **Step 4: Commit C2 evidence**

```bash
git add src tests/e2e/project-server-contracts.spec.ts scripts docs/qa package.json package-lock.json
git commit -m "test: prove project server integration contracts"
```

- [ ] **Step 5: Hand off to existing Wave 6**

Confirm Stages 1-11 have no failing focused tests or unresolved review findings, then execute `docs/superpowers/plans/2026-07-12-miricanvas-design-editor-wave-6-integration-evidence.md` as Stage 12. Do not claim product completion from C2 alone.
