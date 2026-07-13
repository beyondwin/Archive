# Editable Project Wave B1 Package Codec and Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a streaming, integrity-checked, migration-aware `.canvasclone` package codec that safely round-trips complete projects, templates, and page fragments without blocking the editor.

**Architecture:** A worker owns ZIP compression/decompression, incremental hashing, and schema migration. The main thread supplies immutable `ProjectBundle` inputs and receives progress or validated staged results. Manifest/integrity validation occurs before repository mutation; content validators fail closed on active or oversized input.

**Tech Stack:** TypeScript 5, Web Workers, fflate 0.8.3, @noble/hashes 2.2.0, DOMPurify 3.4.12, Vitest 3, Playwright 1.50.

## Global Constraints

- Execute after existing Wave 5 and A2 so the final V3 element schema and durable project model are available.
- `.canvasclone` is deterministic ZIP-compatible data; package entries are not trusted merely because ZIP parsing succeeds.
- Keep `document/current.json` independently loadable.
- Project limit: 768 MiB compressed, 2 GiB validated uncompressed, 10,000 entries.
- Template limit: 128 MiB compressed, 512 MiB validated uncompressed, 2,500 entries.
- Shared limits: 200 pages, 20,000 elements, 5,000 resources, 100 megapixels/100 MiB per raster, 32 MiB per font, 64 fonts, 200 ordinary history entries.
- Reject absolute/parent/device paths, duplicate normalized paths, symlinks, recursive archives, undeclared entries, non-finite document numbers, active SVG/HTML/script content, and arbitrary external URLs.
- Do not implement password encryption, executable plugins, production signatures, S3, or network fetches in B1.
- Worker operations expose progress and cancellation and may not mutate the live repository.
- Run `graphify update .` after the wave.

---

### Task 1: Add package dependencies, limits, manifest, and bundle types

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Create: `src/project/package/types.ts`
- Create: `src/project/package/limits.ts`
- Create: `src/project/package/manifest.ts`
- Test: `src/project/package/__tests__/manifest.test.ts`

**Interfaces:**
- Consumes: `ProjectSnapshot`, durable history/checkpoints/versions, resource records.
- Produces: `ProjectBundle`, `PackageManifestV1`, `PackageIntegrityV1`, `PACKAGE_LIMITS`, `validateManifestV1`.

- [ ] **Step 1: Install exact package dependencies**

Run:

```bash
npm install fflate@^0.8.3 dompurify@^3.4.12
```

Expected: install exits 0 and updates lockfile.

- [ ] **Step 2: Write manifest and limit RED tests**

```ts
it("rejects a project manifest over the approved page limit", () => {
  const manifest = validManifest({ kind: "project", counts: { pages: 201, elements: 201, resources: 0, history: 0 } });
  expect(() => validateManifestV1(manifest)).toThrow("pages exceeds 200");
});

it("requires an independently loadable current document", () => {
  const manifest = validManifest({ entries: [] });
  expect(() => validateManifestV1(manifest)).toThrow("document/current.json");
});

it("requires a versioned exact resource index", () => {
  const manifest = validManifest({ entries: [currentDocumentEntry()] });
  expect(() => validateManifestV1(manifest)).toThrow("resources/index.json");
});
```

- [ ] **Step 3: Run manifest RED tests**

Run: `npm test -- src/project/package/__tests__/manifest.test.ts`

Expected: FAIL because package contracts do not exist.

- [ ] **Step 4: Define exact package contracts**

```ts
export const PACKAGE_FORMAT_VERSION = 1;
export const PROJECT_MIME = "application/vnd.canvasclone.project+zip";

export type PackageKind = "project" | "template" | "page-fragment";
export type PackageEntryDescriptor = {
  path: string;
  sha256: string;
  byteSize: number;
  mimeType: string;
  required: boolean;
  role: "document" | "resource-index" | "workspace" | "operation" | "checkpoint" | "version" | "asset" | "font" | "preview" | "license" | "diagnostic";
};

export type PackageManifestV1 = {
  formatVersion: 1;
  minimumReaderVersion: 1;
  kind: PackageKind;
  projectId: string;
  lineageId: string;
  revision: number;
  baseRevision: number;
  documentSchemaVersion: number;
  historySchemaVersion: number;
  resourceSchemaVersion: number;
  requiredCapabilities: string[];
  optionalCapabilities: string[];
  counts: { pages: number; elements: number; resources: number; history: number };
  entries: PackageEntryDescriptor[];
  integrityRoot: string;
  signer: null | { keyId: string; algorithm: "Ed25519" };
  fidelity: {
    state: "complete" | "external-resources-required" | "repair-required";
    issueCount: number;
    issueReportPath: "recovery/resource-issues.json" | null;
  };
};

export type ProjectBundle = {
  manifest: PackageManifestV1;
  entries: Map<string, Uint8Array>;
};
```

```ts
export const PACKAGE_LIMITS = {
  project: { compressedBytes: 768 * 1024 ** 2, uncompressedBytes: 2 * 1024 ** 3, entries: 10_000 },
  template: { compressedBytes: 128 * 1024 ** 2, uncompressedBytes: 512 * 1024 ** 2, entries: 2_500 },
  pageFragment: { compressedBytes: 128 * 1024 ** 2, uncompressedBytes: 512 * 1024 ** 2, entries: 2_500 },
  pages: 200,
  elements: 20_000,
  resources: 5_000,
  history: 200,
  rasterEncodedBytes: 100 * 1024 ** 2,
  rasterPixels: 100_000_000,
  fontBytes: 32 * 1024 ** 2,
  fonts: 64,
} as const;
```

- [ ] **Step 5: Implement structural validation and run GREEN**

Validate exact keys, integer/range constraints, unique entry paths/hashes, one required `document/current.json`, one required `resources/index.json`, history count, and profile-specific limits. `manifest.json` describes the other entries and may not list/hash itself. `complete` requires a validated entry for every exact binding; `external-resources-required` is project-only and permits intentionally non-embeddable licensed font bytes to be absent; `repair-required` is project-only and requires a redacted issue report. Templates/page fragments must be `complete`. The current document may still open in repair mode if the resource index fails after archive integrity staging, but a package cannot claim full fidelity without it. Reject unknown required manifest fields rather than coercing them.

Run: `npm test -- src/project/package/__tests__/manifest.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit package contracts**

```bash
git add package.json package-lock.json src/project/package
git commit -m "feat: define canvasclone package contracts"
```

---

### Task 2: Normalize entry paths and build integrity roots

**Files:**
- Create: `src/project/package/entryPath.ts`
- Create: `src/project/package/integrity.ts`
- Test: `src/project/package/__tests__/integrity.test.ts`

**Interfaces:**
- Consumes: package entry byte streams.
- Produces: `normalizeEntryPath`, `IncrementalEntryHasher`, `createIntegrityMap`, `createIntegrityRoot`, `verifyEntry`.

- [ ] **Step 1: Write traversal, duplicate, and hash RED tests**

```ts
it.each(["/absolute", "../escape", "a/../../escape", "C:\\device", "a\\b", "a\0b"])(
  "rejects unsafe entry path %s",
  (path) => expect(() => normalizeEntryPath(path)).toThrow(),
);

it("hashes streamed chunks identically to one buffer", () => {
  const hasher = new IncrementalEntryHasher();
  hasher.update(new TextEncoder().encode("ab"));
  hasher.update(new TextEncoder().encode("c"));
  expect(hasher.digestHex()).toBe(sha256Hex("abc"));
});
```

- [ ] **Step 2: Run integrity RED tests**

Run: `npm test -- src/project/package/__tests__/integrity.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement strict path normalization**

```ts
export function normalizeEntryPath(input: string): string {
  if (!input || input.includes("\0") || input.includes("\\") || input.startsWith("/") || /^[A-Za-z]:/.test(input)) {
    throw new Error(`Unsafe package entry path: ${input}`);
  }
  const parts = input.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`Unsafe package entry path: ${input}`);
  }
  return parts.join("/").normalize("NFC");
}
```

- [ ] **Step 4: Implement incremental hashes and canonical integrity root**

Use `sha256.create()` from `@noble/hashes/sha2.js`. Sort normalized paths, then hash canonical descriptors `{path, sha256, byteSize, mimeType, required, role}`. `manifest.json` does not hash itself; the manifest stores the resulting root. A server signature covers canonical manifest bytes with the signature value omitted plus the integrity root. Local unsigned packages still verify every entry hash and the root.

- [ ] **Step 5: Run integrity GREEN tests**

Run: `npm test -- src/project/package/__tests__/integrity.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit integrity primitives**

```bash
git add src/project/package/entryPath.ts src/project/package/integrity.ts src/project/package/__tests__/integrity.test.ts
git commit -m "feat: verify package entry integrity"
```

---

### Task 3: Add cancellable streaming ZIP worker protocol

**Files:**
- Create: `src/project/workers/packageWorkerProtocol.ts`
- Create: `src/project/workers/package.worker.ts`
- Create: `src/project/package/PackageWorkerClient.ts`
- Test: `src/project/package/__tests__/PackageWorkerClient.test.ts`

**Interfaces:**
- Consumes: async entry chunks and package Blob chunks.
- Produces: `PackageWorkerClient.write(request)`, `inspect(blob, policy)`, progress events, `AbortSignal` cancellation.

- [ ] **Step 1: Write worker protocol RED tests**

```ts
it("reports monotonic progress and cancels without a final blob", async () => {
  const worker = fakePackageWorker();
  const client = new PackageWorkerClient(worker);
  const abort = new AbortController();
  const progress: number[] = [];
  const pending = client.write(fixtureWriteRequest(), { signal: abort.signal, onProgress: (event) => progress.push(event.completedBytes) });
  abort.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  expect(progress).toEqual([...progress].sort((a, b) => a - b));
});

it("writes byte-identical archives for the same immutable bundle", async () => {
  const first = await client.write(deterministicBundle());
  const second = await client.write(deterministicBundle());
  expect(await sha256Blob(first)).toBe(await sha256Blob(second));
});
```

- [ ] **Step 2: Run worker protocol RED tests**

Run: `npm test -- src/project/package/__tests__/PackageWorkerClient.test.ts`

Expected: FAIL.

- [ ] **Step 3: Define the discriminated worker messages**

```ts
export type PackageWorkerRequest =
  | { id: string; type: "write.start"; manifest: PackageManifestV1; entries: PackageEntryDescriptor[] }
  | { id: string; type: "write.entry.start"; path: string }
  | { id: string; type: "write.entry.chunk"; path: string; sequence: number; bytes: ArrayBuffer }
  | { id: string; type: "write.entry.end"; path: string }
  | { id: string; type: "write.finalize" }
  | { id: string; type: "inspect"; blob: Blob; limits: PackageLimitPolicy }
  | { id: string; type: "cancel" };

export type PackageWorkerResponse =
  | { id: string; type: "progress"; phase: "hash" | "compress" | "inspect" | "inflate" | "validate"; completedBytes: number; totalBytes: number }
  | { id: string; type: "written.chunk"; sequence: number; bytes: ArrayBuffer }
  | { id: string; type: "written"; byteLength: number }
  | { id: string; type: "inspected"; staged: StagedPackage }
  | { id: string; type: "error"; code: string; message: string };
```

- [ ] **Step 4: Implement fflate streaming in the worker**

`PackageWorkerClient.write` accepts each entry as `AsyncIterable<Uint8Array>` and sends one transferable chunk at a time with sequence/backpressure acknowledgement; it never constructs an array containing all source bytes. For writes, use `Zip` and `ZipPassThrough`/`ZipDeflate`; forward produced chunks immediately through transferable `ArrayBuffer`s and let the client append them to a Blob builder without concatenating one giant buffer. For inspection, feed Blob slices into `Unzip`, enforce entry count and cumulative output before retaining an entry, and reject undeclared or duplicate normalized paths. Register only the required inflate decoder.

Sort normalized entry paths, use a fixed ZIP timestamp/permissions/platform marker, omit nondeterministic extra fields, and fix compression method/level by MIME class. Manifest timestamps come from the immutable project revision, never packaging wall-clock time. Two writes of the same bundle must be byte-identical.

The worker must check its request cancellation set between input chunks and before every postMessage.

- [ ] **Step 5: Run worker tests and a 50 MiB smoke fixture**

Run: `npm test -- src/project/package/__tests__/PackageWorkerClient.test.ts`

Expected: PASS; the smoke fixture reports progress before completion and cancellation releases pending state.

- [ ] **Step 6: Commit worker codec foundation**

```bash
git add src/project/workers src/project/package/PackageWorkerClient.ts src/project/package/__tests__/PackageWorkerClient.test.ts
git commit -m "feat: stream canvasclone packages in a worker"
```

---

### Task 4: Validate archive budgets and structured JSON before domain parsing

**Files:**
- Create: `src/project/security/archiveBudget.ts`
- Create: `src/project/security/jsonBudget.ts`
- Test: `src/project/security/__tests__/archiveBudget.test.ts`
- Test: `src/project/security/__tests__/jsonBudget.test.ts`

**Interfaces:**
- Consumes: ZIP metadata/output counters and UTF-8 JSON bytes.
- Produces: `ArchiveBudget`, `consumeEntry`, `parseBudgetedJson`.

- [ ] **Step 1: Write size/depth/string RED tests**

```ts
expect(() => consumeEntry(projectBudget(), { compressed: 1, uncompressed: 2 * 1024 ** 3 + 1 })).toThrow("uncompressed");
expect(() => parseBudgetedJson(new TextEncoder().encode('{"a":{"b":{"c":1}}}'), { maxDepth: 2 })).toThrow("depth");
expect(() => parseBudgetedJson(new TextEncoder().encode(JSON.stringify({ a: "x".repeat(10) })), { maxStringLength: 9 })).toThrow("string");
```

- [ ] **Step 2: Run budget RED tests**

Run: `npm test -- src/project/security/__tests__/archiveBudget.test.ts src/project/security/__tests__/jsonBudget.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement checked counters and iterative JSON walk**

Use safe-integer addition for compressed, uncompressed, entry, page, element, resource, history, and font counts. Parse JSON only after UTF-8 byte and string limits pass; then walk iteratively to enforce depth, collection length, key count, finite numbers, and allowed scalar types.

- [ ] **Step 4: Run budget GREEN tests**

Run: `npm test -- src/project/security/__tests__/archiveBudget.test.ts src/project/security/__tests__/jsonBudget.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit package budgets**

```bash
git add src/project/security/archiveBudget.ts src/project/security/jsonBudget.ts src/project/security/__tests__
git commit -m "feat: enforce package resource budgets"
```

---

### Task 5: Validate raster, SVG, and font resources

**Files:**
- Create: `src/project/security/resourceSignature.ts`
- Create: `src/project/security/rasterValidator.ts`
- Create: `src/project/security/svgSanitizer.ts`
- Create: `src/project/security/fontValidator.ts`
- Test: `src/project/security/__tests__/resources.test.ts`

**Interfaces:**
- Consumes: resource descriptor and bytes.
- Produces: `validateRaster`, `sanitizeSvg`, `validateFont`, typed `ResourceSecurityResult`.

- [ ] **Step 1: Write active-content and malformed-resource RED tests**

```ts
it.each([
  '<svg onload="alert(1)"></svg>',
  '<svg><script>alert(1)</script></svg>',
  '<svg><foreignObject><div>html</div></foreignObject></svg>',
  '<svg><image href="https://tracker.example/pixel"/></svg>',
])("rejects active SVG", (svg) => expect(() => sanitizeSvg(svg)).toThrow("SVG_ACTIVE_CONTENT"));

it("rejects raster dimensions above 100 megapixels", () => {
  expect(() => validateRaster(fakePngHeader(20_000, 20_000), "image/png")).toThrow("RASTER_PIXEL_LIMIT");
});

it("rejects an sfnt font whose table extends past the file", () => {
  expect(() => validateFont(invalidSfntTableBounds())).toThrow("FONT_TABLE_BOUNDS");
});

it.each([
  ["restricted", false],
  ["preview-print", false],
  ["editable", true],
  ["installable", true],
])("applies %s embedding rights to editable packages", (rights, embeddable) => {
  expect(validateFont(fontWithEmbeddingRights(rights)).editablePackageEmbeddingAllowed).toBe(embeddable);
});
```

- [ ] **Step 2: Run resource security RED tests**

Run: `npm test -- src/project/security/__tests__/resources.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement signature and structural validators**

Allow PNG, JPEG, WebP, sanitized SVG, OTF, TTF, and WOFF2 only. Verify declared MIME against magic bytes. Reuse the existing robust PNG validation where possible instead of duplicating it from export code. Parse raster dimensions without fully decoding.

For fonts, enforce byte limit, accepted sfnt/WOFF2 signature, table count, unique tags, checked offsets/lengths, and embedding-permission metadata. Parse OpenType `OS/2.fsType`: zero/installable and editable embedding may enter a native editable package; restricted, preview-and-print, and bitmap-only rights may not. Honor `no subsetting` by embedding the full validated file or omitting it. Missing/invalid rights metadata defaults to non-embeddable. Store a license/provenance record with the exact font hash and decision; a filename, family name, user upload, or same-name installed font never grants embedding rights. Record that Phase D must run server-side font sanitization before catalog publication.

When bytes cannot legally be embedded, keep the canonical font reference and hash requirements but omit the bytes, mark the resource `licensed-external`, and require exact local/server resolution on reopen. Do not convert preview-and-print rights into editable rights; a publication-only output path may use those rights only under a separately tested policy.

- [ ] **Step 4: Sanitize SVG with a strict allowlist**

Use DOMPurify with SVG profile, then separately reject `script`, `foreignObject`, `style`, event attributes, CSS `url()`, `href`/`xlink:href` outside internal fragment references, and animation elements. Reparse sanitized output and fail if any rejected construct remains; do not silently drop an element and claim full fidelity.

- [ ] **Step 5: Run resource security GREEN tests**

Run: `npm test -- src/project/security/__tests__/resources.test.ts src/editor/export/__tests__/exportService.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit resource validators**

```bash
git add src/project/security src/editor/export
git commit -m "feat: validate package fonts and assets"
```

---

### Task 6: Build project, template, page-fragment, and optimized-copy profiles

**Files:**
- Create: `src/project/package/resourceClosure.ts`
- Create: `src/project/package/buildBundle.ts`
- Create: `src/project/package/profiles.ts`
- Test: `src/project/package/__tests__/profiles.test.ts`

**Interfaces:**
- Consumes: `LoadedProject`, resources, selected page IDs.
- Produces: `buildProjectBundle`, `buildTemplateBundle`, `buildPageFragmentBundle`, `buildOptimizedCopyBundle`.

- [ ] **Step 1: Write profile privacy and closure RED tests**

```ts
it("keeps history resources in a project but strips them from a template", () => {
  const loaded = projectWithCurrentAndDeletedHistoryAssets();
  expect(resourceHashes(buildProjectBundle(loaded))).toContain("history-only-hash");
  const template = buildTemplateBundle(loaded, { pageIds: ["page-1"] });
  expect(resourceHashes(template)).not.toContain("history-only-hash");
  expect(template.manifest.counts.history).toBe(0);
});

it("rejects a page fragment with an external group reference", () => {
  expect(() => buildPageFragmentBundle(projectWithCrossPageGroup(), { pageIds: ["page-1"] })).toThrow("FRAGMENT_OPEN_REFERENCE");
});
```

- [ ] **Step 2: Run profile RED tests**

Run: `npm test -- src/project/package/__tests__/profiles.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement closed reference traversal**

Traverse page backgrounds, every element family, table fills, icon/image refs, fonts, current history patches, checkpoints, named versions, and retained discarded branches. Return structural open references, reachable exact bindings, intentionally external licensed fonts, and missing/corrupt bytes separately. Structural open references always fail. Project profile preserves exact missing bindings and emits a redacted repair report instead of losing the editable snapshot; template/page-fragment profiles fail on any non-complete resource closure.

Write the stable package layout:

```text
manifest.json
document/current.json
resources/index.json
history/operations/<operationId>.json
history/checkpoints/<checkpointId>.json
history/versions/<versionId>.json
history/branches/<branchId>.json
resources/assets/sha256/<first2>/<hash>
resources/fonts/sha256/<first2>/<hash>
licenses/<licenseId>.json
previews/page-<pageId>.webp
recovery/resource-issues.json
workspace/local.json
```

Only project profile may contain `history/**`, optional `recovery/resource-issues.json`, and optional `workspace/local.json`; workspace is never required to open/edit. Template/page-fragment profiles omit those trees. Entry filenames use validated IDs or hashes only, never user filenames.

- [ ] **Step 4: Implement profile-specific cleanup**

- Project: current, 200 history, 20 automatic checkpoints, named versions, retained branches, all available closure bytes, exact unresolved bindings plus redacted repair report, optional workspace.
- Template: selected clean source, closure, license/provenance, preview; no history/workspace/private metadata.
- Page fragment: selected pages, regenerated fragment identity, closed refs only.
- Optimized copy: editable current document and closure; no ordinary history, recovery, deleted resources, or private workspace.

- [ ] **Step 5: Run profile GREEN tests**

Run: `npm test -- src/project/package/__tests__/profiles.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit package profiles**

```bash
git add src/project/package/resourceClosure.ts src/project/package/buildBundle.ts src/project/package/profiles.ts src/project/package/__tests__/profiles.test.ts
git commit -m "feat: build portable project package profiles"
```

---

### Task 7: Add package migrations and immutable golden fixtures

**Files:**
- Create: `src/project/package/migrations.ts`
- Create: `src/project/__fixtures__/manifest-v1.json`
- Create: `src/project/__fixtures__/project-v1.canvasclone`
- Create: `scripts/generate-project-package-fixtures.mjs`
- Test: `src/project/package/__tests__/migrations.test.ts`
- Modify: `package.json`

**Interfaces:**
- Consumes: raw manifest/current/history/resource bytes.
- Produces: `migratePackageToCurrent(staged)`, deterministic fixture generator, `project:fixtures` script.

- [ ] **Step 1: Write future/old version RED tests**

```ts
it("migrates a v1 golden package without mutating its bytes", async () => {
  const source = await fixtureBytes("project-v1.canvasclone");
  const before = sha256Hex(source);
  const current = await migratePackageToCurrent(await inspect(source));
  expect(current.manifest.formatVersion).toBe(PACKAGE_FORMAT_VERSION);
  expect(sha256Hex(source)).toBe(before);
});

it("preserves but does not edit an unknown required capability", async () => {
  const result = await migratePackageToCurrent(stagedPackage({ requiredCapabilities: ["future.unknown"] }));
  expect(result.mode).toBe("read-only");
});
```

- [ ] **Step 2: Run migration RED tests**

Run: `npm test -- src/project/package/__tests__/migrations.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement sequential registries**

Define separate package, document, history, and resource migration registries. Every migration clones input, validates output, records from/to versions, and cannot overwrite source bytes. Unknown optional capabilities stay in the manifest with their entries; unknown required capabilities return read-only mode only when a valid preview exists.

- [ ] **Step 4: Generate and verify deterministic golden fixtures**

Run:

```bash
npm run project:fixtures
cp src/project/__fixtures__/project-v1.canvasclone /tmp/project-v1.canvasclone
npm run project:fixtures
cmp /tmp/project-v1.canvasclone src/project/__fixtures__/project-v1.canvasclone
git diff --exit-code -- src/project/__fixtures__
```

Expected: `cmp` exits 0 and the second generation changes no tracked bytes. On the first execution, stage the newly created fixtures before using `git diff --exit-code` as the repeatability check.

- [ ] **Step 5: Commit migrations and fixtures**

```bash
git add src/project/package/migrations.ts src/project/package/__tests__/migrations.test.ts src/project/__fixtures__ scripts/generate-project-package-fixtures.mjs package.json
git commit -m "test: add canvasclone migration corpus"
```

---

### Task 8: Prove all-element round trip, security corpus, cancellation, and budgets

**Files:**
- Create: `src/project/package/__tests__/roundTrip.test.ts`
- Create: `src/project/security/__tests__/maliciousPackages.test.ts`
- Create: `src/project/__fixtures__/referenceProjectS.ts`
- Create: `src/project/__fixtures__/stressProjectL.ts`
- Create: `tests/e2e/project-package-worker.spec.ts`
- Modify: `package.json`

**Interfaces:**
- Consumes: complete B1 codec and existing final element schema.
- Produces: `test:project-package`, `test:e2e:project-package`, reference S and stress L measurements.

- [ ] **Step 1: Add the all-element round-trip test**

Build a project containing text, uploaded photo, catalog image, icon/SVG, table with merge, shape, line, chart, page background, crop/effects, groups, links, 200 history entries, checkpoints, named version, and exact resources.

```ts
const bytes = await writePackage(buildProjectBundle(referenceProjectS()));
const opened = await inspectAndDecode(bytes);
expect(opened.project.document).toEqual(referenceProjectS().snapshot.document);
expect(opened.project.history.past).toHaveLength(200);
expect(opened.verifiedResourceHashes).toEqual(referenceProjectS().resourceHashes);
```

- [ ] **Step 2: Add malicious package cases**

Cover traversal, duplicate normalized paths, undeclared entries, invalid UTF-8, compression expansion, excessive entries, JSON depth/strings, wrong hash/signature metadata, recursive archive, malformed raster/font, active SVG, external URLs, and future required capabilities.

- [ ] **Step 3: Add browser worker responsiveness and cancellation**

In Playwright, start the stress fixture package operation, assert progress appears within 200 ms, cancel it, assert no project mutation, and record main-thread long tasks. Then run a smaller complete package and assert no codec-caused long task exceeds 50 ms.

- [ ] **Step 4: Run the B1 focused gate**

Run:

```bash
npm run lint
npm test -- src/project/package src/project/security src/domain/project
npx playwright test tests/e2e/project-package-worker.spec.ts --project=parity-1920 --workers=1
git diff --check
npm run graphify:update
```

Expected: all commands PASS; security tests report zero accepted malicious fixtures.

- [ ] **Step 5: Commit B1 evidence**

```bash
git add src/project tests/e2e/project-package-worker.spec.ts package.json package-lock.json scripts
git commit -m "test: prove secure canvasclone package round trips"
```
