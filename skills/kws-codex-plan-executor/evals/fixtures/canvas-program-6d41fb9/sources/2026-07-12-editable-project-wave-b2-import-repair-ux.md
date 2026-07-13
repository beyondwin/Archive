# Editable Project Wave B2 Import, Repair, and File UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the B1 package codec into safe project open/save/export workflows with preflight, lineage conflict handling, exact resource resolution, Repair Center, version recovery, multi-tab transfer, and export blocking.

**Architecture:** UI components consume application services, never ZIP or IndexedDB directly. `ProjectFileService` stages and validates packages, `ResourceResolver` computes non-mutating readiness, and `ProjectImportService` commits only an approved lineage decision. Save state is split into local durability, portable-file freshness, server sync, and edit ownership.

**Tech Stack:** React 19, TypeScript 5, Zustand 5, File System Access API with upload/download fallback, B1 worker codec, IndexedDB ProjectRepository, Vitest, Testing Library, Playwright.

## Global Constraints

- Execute after B1.
- The app library remains the primary working copy; a `.canvasclone` file is a complete portable original at a recorded revision.
- Import never mutates repository state until preflight and user decision succeed.
- The source file and existing project remain unchanged on migration, resource, transaction, or cancellation failure.
- Missing fonts/assets preserve original refs and element geometry; temporary fallbacks do not enter history.
- Normal PNG/PDF, package publication, and official project export are blocked when required resources/capabilities are unresolved; explicit degraded output has a report and distinct filename.
- Save state has four independent axes: local, external file, future server, and edit lease.
- All new dialogs and panels meet the existing focus, keyboard, semantics, live-region, contrast, and reduced-motion requirements.
- Run `graphify update .` after the wave.

---

### Task 1: Abstract browser file capabilities and fallbacks

**Files:**
- Create: `src/editor/project/fileGateway.ts`
- Create: `src/editor/project/browserFileGateway.ts`
- Test: `src/editor/project/__tests__/browserFileGateway.test.ts`

**Interfaces:**
- Consumes: project Blob and approved filename.
- Produces: `ProjectFileGateway`, `FileOpenResult`, `FileSaveResult`, capability detection, native picker and download fallback.

- [ ] **Step 1: Write capability and cancellation RED tests**

```ts
it("uses native save when a writable handle is available", async () => {
  const platform = fakeFilePlatform({ nativePicker: true });
  const result = await createBrowserFileGateway(platform).saveAs(blob(), "design.canvasclone");
  expect(platform.showSaveFilePicker).toHaveBeenCalledWith(expect.objectContaining({ suggestedName: "design.canvasclone" }));
  expect(result).toMatchObject({ mode: "native", revisionWritten: null });
});

it("falls back to a download without treating picker cancel as an error", async () => {
  const platform = fakeFilePlatform({ nativePicker: false });
  expect(await createBrowserFileGateway(platform).saveAs(blob(), "design.canvasclone"))
    .toMatchObject({ mode: "download" });
});
```

- [ ] **Step 2: Run file-gateway RED tests**

Run: `npm test -- src/editor/project/__tests__/browserFileGateway.test.ts`

Expected: FAIL.

- [ ] **Step 3: Define the gateway**

```ts
export type FileCapability = "native-open-save" | "upload-download";
export type OpenedProjectFile = { file: File; handle: FileSystemFileHandle | null; displayName: string };
export type SavedProjectFile = { mode: "native" | "download"; handle: FileSystemFileHandle | null; displayName: string };

export interface ProjectFileGateway {
  capability(): FileCapability;
  open(): Promise<OpenedProjectFile | null>;
  saveAs(blob: Blob, suggestedName: string): Promise<SavedProjectFile | null>;
  saveToHandle(handle: FileSystemFileHandle, blob: Blob): Promise<SavedProjectFile>;
}
```

Native writes use `createWritable()`, `write(blob)`, and `close()`. Treat `AbortError` as user cancellation. The fallback creates a temporary object URL, clicks a download anchor, and always revokes the URL.

- [ ] **Step 4: Run file-gateway GREEN tests**

Run: `npm test -- src/editor/project/__tests__/browserFileGateway.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit file capability abstraction**

```bash
git add src/editor/project/fileGateway.ts src/editor/project/browserFileGateway.ts src/editor/project/__tests__/browserFileGateway.test.ts
git commit -m "feat: add native project file gateway"
```

---

### Task 2: Build export snapshots without changing the live project

**Files:**
- Create: `src/editor/project/ProjectFileService.ts`
- Test: `src/editor/project/__tests__/ProjectFileService.test.ts`
- Modify: `src/project/commit/ProjectCommitCoordinator.ts`
- Modify: `src/persistence/projectRepository.ts`

**Interfaces:**
- Consumes: repository, commit coordinator, B1 bundle builder/worker, file gateway.
- Produces: `exportProject`, `exportOptimizedCopy`, `save`, `saveAs`, external-file revision status.

- [ ] **Step 1: Write flush, immutable revision, and failure RED tests**

```ts
it("flushes revision 42 and records the external file at exactly 42", async () => {
  const service = fixtureProjectFileService({ currentRevision: 42, pending: [42] });
  const result = await service.saveAs();
  expect(service.commitCoordinator.flush).toHaveBeenCalled();
  expect(service.codec.write).toHaveBeenCalledWith(expect.objectContaining({ manifest: expect.objectContaining({ revision: 42 }) }));
  expect(result.externalFile).toMatchObject({ revision: 42, freshness: "current" });
});

it("does not update file freshness when final verification fails", async () => {
  const service = fixtureProjectFileService({ verifyError: "hash mismatch" });
  await expect(service.saveAs()).rejects.toThrow("hash mismatch");
  expect(service.status().externalFile.freshness).toBe("never-exported");
});

it("refuses to overwrite a file changed outside the editor", async () => {
  const service = fixtureProjectFileService({
    rememberedFile: { size: 100, lastModified: 10, sha256: "old-hash" },
    currentFile: { size: 101, lastModified: 11, sha256: "external-hash" },
  });
  await expect(service.save()).rejects.toThrow("EXTERNAL_FILE_CHANGED");
  expect(service.fileGateway.saveToHandle).not.toHaveBeenCalled();
});

it("saves an explicitly marked repairable native project when resources are missing", async () => {
  const service = fixtureProjectFileService({ resourceIssue: missingAsset("expected-hash") });
  const result = await service.saveAs();
  expect(result.manifest.fidelity).toMatchObject({ state: "repair-required", issueCount: 1 });
  expect(result.filename).toMatch(/\.canvasclone$/);
  expect(result.status).toBe("saved-needs-repair");
});
```

- [ ] **Step 2: Run file-service RED tests**

Run: `npm test -- src/editor/project/__tests__/ProjectFileService.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement snapshot/export order**

```ts
await commitCoordinator.flush(projectId);
const loaded = await repository.loadProject(projectId);
const immutable = structuredClone(loaded);
const bundle = optimized ? buildOptimizedCopyBundle(immutable) : buildProjectBundle(immutable);
const blob = await packageClient.write(bundle, { signal, onProgress });
await packageClient.verifyWrittenBlob(blob, bundle.manifest.integrityRoot);
const saved = handle ? await fileGateway.saveToHandle(handle, blob) : await fileGateway.saveAs(blob, filename);
if (saved) publishExternalFileStatus({ freshness: "current", revision: loaded.snapshot.envelope.revision, handle: saved.handle });
```

For a retained native handle, remember the last verified `{ size, lastModified, sha256 }`. Before overwrite, re-read and compare the current file; metadata differences trigger a hash comparison, and a changed hash blocks overwrite with choices to inspect/import the external version, Save As, or explicitly replace after a fresh preflight/checkpoint. Never silently last-writer-win against another app or browser context. If native replacement fails, the previous file remains the platform's responsibility; do not change live project or status. Download fallback never claims a persistent handle or external-change detection.

Native project save/export remains available when fonts/assets are unresolved so the user can preserve editable structure, history, original expected hashes, and repair diagnostics. Surface `complete`, `external resources required`, or `saved · repair needed` and never label the latter two portable/full-fidelity. This exception applies only to `.canvasclone`; template/page-fragment packaging and ordinary PNG/PDF/publication retain their blocking policies.

- [ ] **Step 4: Run file-service GREEN tests**

Run: `npm test -- src/editor/project/__tests__/ProjectFileService.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit project file export**

```bash
git add src/editor/project/ProjectFileService.ts src/editor/project/__tests__/ProjectFileService.test.ts src/project/commit src/persistence/projectRepository.ts
git commit -m "feat: export verified editable project files"
```

---

### Task 3: Add import preflight and lineage decisions

**Files:**
- Create: `src/editor/project/importTypes.ts`
- Create: `src/editor/project/ProjectImportService.ts`
- Test: `src/editor/project/__tests__/ProjectImportService.test.ts`
- Modify: `src/persistence/projectRepository.ts`
- Modify: `src/persistence/indexedDbProjectRepository.ts`

**Interfaces:**
- Consumes: opened file, B1 staged package, ProjectRepository.
- Produces: `ProjectPreflight`, `LineageDecision`, `ProjectImportCommit`, `ProjectRepository.commitImport`, `preflight(file)`, `commit(preflight, decision)`.

- [ ] **Step 1: Write the complete lineage RED matrix**

```ts
it.each([
  ["unknown", "new-project"],
  ["same-hash", "duplicate"],
  ["direct-descendant", "update-existing"],
  ["divergent", "decision-required"],
  ["future-required-capability", "read-only"],
])("classifies %s as %s", async (fixture, expected) => {
  expect((await serviceFor(fixture).preflight(file())).lineage.kind).toBe(expected);
});
```

Add tests proving cancel/no decision leaves repository counts unchanged and replace creates a checkpoint before mutation.

- [ ] **Step 2: Run import-service RED tests**

Run: `npm test -- src/editor/project/__tests__/ProjectImportService.test.ts`

Expected: FAIL.

- [ ] **Step 3: Define preflight and decisions**

```ts
export type LineageDecision =
  | { kind: "import-new-copy" }
  | { kind: "update-existing"; projectId: string }
  | { kind: "replace-existing"; projectId: string }
  | { kind: "cancel" };

export type ProjectPreflight = {
  stagedId: string;
  displayName: string;
  kind: PackageKind;
  revision: number;
  counts: PackageManifestV1["counts"];
  migrations: string[];
  resourceIssues: ResourceIssue[];
  capabilityIssues: CapabilityIssue[];
  integrity: "verified" | "unsigned-local";
  lineage: LineageClassification;
};

export type ProjectImportCommit = {
  stagingId: string;
  mode: "create" | "update" | "replace";
  expectedRevision: number | null;
  project: LoadedProject;
  verifiedResourceHashes: string[];
};
```

- [ ] **Step 4: Implement staged atomic commit**

Inspection returns a staging token and immutable validated data. Verified content-addressed bytes may be written before the visible commit because they are immutable and unclaimed; failure leaves them eligible for garbage collection. `commit` rechecks the token, repository revision, every `ProjectResourceIndex` binding, and the existence/hash of all required CAS bytes.

`ProjectRepository.commitImport(input)` then writes the project head, operation cursors/entries, checkpoints, named versions, discarded branches, resource index, and import receipt in one IndexedDB transaction. For update/replace it also stores the pre-import checkpoint and compare-and-swaps `expectedRevision` in that same transaction. No project ID becomes visible before commit. A failed transaction retains redacted diagnostics, marks staging abandoned, and leaves the previous project head unchanged.

- [ ] **Step 5: Run import and repository tests**

Run: `npm test -- src/editor/project/__tests__/ProjectImportService.test.ts src/persistence/__tests__/indexedDbProjectRepository.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit safe import application service**

```bash
git add src/editor/project/importTypes.ts src/editor/project/ProjectImportService.ts src/editor/project/__tests__/ProjectImportService.test.ts src/persistence
git commit -m "feat: preflight editable project imports"
```

---

### Task 4: Resolve fonts and assets without mutating canonical refs

**Files:**
- Create: `src/editor/resources/types.ts`
- Create: `src/editor/resources/ResourceResolver.ts`
- Create: `src/editor/resources/fontFallback.ts`
- Create: `src/editor/resources/exportReadiness.ts`
- Test: `src/editor/resources/__tests__/ResourceResolver.test.ts`

**Interfaces:**
- Consumes: `ProjectResourceIndex`, package bytes, local CAS, trusted catalog fake, user reconnect callback.
- Produces: `ResolvedResource`, `ResourceIssue`, `resolveProjectResources`, `assessExportReadiness`.

- [ ] **Step 1: Write exact resolution-order and non-mutation RED tests**

```ts
it("resolves package, local CAS, trusted server, then user reconnect", async () => {
  const resolver = fixtureResolver({ package: miss(), cas: miss(), catalog: hit("exact-hash") });
  expect(await resolver.resolve(ref("exact-hash"))).toMatchObject({ source: "trusted-catalog", hash: "exact-hash" });
  expect(resolver.calls).toEqual(["package", "cas", "catalog"]);
});

it("temporarily substitutes a font without changing canonical text style", async () => {
  const project = projectWithMissingFont("brand-font");
  const before = structuredClone(project.snapshot.document);
  const result = await resolver.resolveProject(project);
  expect(result.issues[0]).toMatchObject({ kind: "missing-font", temporaryFallbackId: "noto-sans-kr" });
  expect(project.snapshot.document).toEqual(before);
});
```

- [ ] **Step 2: Run resource-resolver RED tests**

Run: `npm test -- src/editor/resources/__tests__/ResourceResolver.test.ts`

Expected: FAIL.

- [ ] **Step 3: Define issue/result contracts**

```ts
export type ResourceIssue = {
  issueId: string;
  kind: "missing-font" | "missing-glyph" | "missing-asset" | "hash-mismatch" | "decode-failed" | "untrusted-external";
  severity: "warning" | "blocking";
  resourceId: string;
  expectedHash: string | null;
  affected: Array<{ pageId: string; elementId: string | null }>;
  temporaryFallbackId?: string;
};

export type ExportReadiness =
  | { kind: "ready" }
  | { kind: "blocked"; issues: ResourceIssue[] }
  | { kind: "degraded-allowed"; issues: ResourceIssue[]; report: DegradedOutputReport };
```

- [ ] **Step 4: Implement exact lookup and placeholders**

Package and CAS matches require exact hash and validated bytes. Trusted catalog results require allowlisted gateway, immutable ID/version, and exact hash. Arbitrary URLs remain issues. Missing images return diagnostic renderer data that preserves geometry/crop/effects; missing fonts return temporary writing-system fallback and layout-overflow diagnostics while retaining the original `usageId`, resource ID, expected hash, target locator, and style values in `ProjectResourceIndex`.

- [ ] **Step 5: Run resolver GREEN tests**

Run: `npm test -- src/editor/resources/__tests__/ResourceResolver.test.ts src/editor/hooks/__tests__/useResolvedAsset.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit resource resolution**

```bash
git add src/editor/resources src/editor/hooks
git commit -m "feat: resolve project resources safely"
```

---

### Task 5: Add project file menu, independent status axes, and preflight dialog

**Files:**
- Create: `src/editor/project/ProjectFileMenu.tsx`
- Create: `src/editor/project/ProjectStatus.tsx`
- Create: `src/editor/project/ImportPreflightDialog.tsx`
- Test: `src/editor/project/__tests__/ProjectFileMenu.test.tsx`
- Test: `src/editor/project/__tests__/ImportPreflightDialog.test.tsx`
- Modify: `src/editor/components/TopBar.tsx`
- Modify: `src/editor/components/EditorShell.tsx`
- Modify: `app/globals.css`

**Interfaces:**
- Consumes: file/import services and local/storage/file/server/lease statuses.
- Produces: accessible file actions, five independent status axes, preflight decisions.

- [ ] **Step 1: Write accessible status and preflight RED tests**

```tsx
render(<ProjectStatus local="saved" storage="best-effort" external={{ freshness: "stale", revision: 38 }} server={{ kind: "pending", count: 3 }} lease="writer" />);
expect(screen.getByText("로컬 저장됨")).toBeVisible();
expect(screen.getByText("브라우저가 저장 공간을 회수할 수 있음 · 원본 파일 백업 권장")).toBeVisible();
expect(screen.getByText("원본 파일 revision 38 · 다시 저장 필요")).toBeVisible();
expect(screen.getByText("서버 동기화 대기 · 변경 3개")).toBeVisible();
expect(screen.getByText("현재 탭이 편집 중")).toBeVisible();
```

Preflight tests cover counts, migrations, issues, duplicate, descendant, divergent choices, cancel, progress, focus trap, and focus return.

- [ ] **Step 2: Run component RED tests**

Run: `npm test -- src/editor/project/__tests__/ProjectFileMenu.test.tsx src/editor/project/__tests__/ImportPreflightDialog.test.tsx`

Expected: FAIL.

- [ ] **Step 3: Implement file menu and status components**

Actions: new project, open project, Save, Save As, export full project, export optimized editable copy, version history, and document/resource status. C1 adds Save as My Template when functional; B2 does not render a placeholder/disabled action. Do not overload the existing DownloadPanel with editable-project actions.

- [ ] **Step 4: Implement preflight dialog states**

Use semantic dialog, headings, list issue summaries by resource/page, show lineage choice buttons only when valid, announce progress and failure once, expose cancel at all non-commit stages, and disable commit while resources/required capabilities block it.

- [ ] **Step 5: Run component and shell regressions**

Run: `npm test -- src/editor/project src/editor/components/__tests__/editorShell.test.tsx src/editor/components/__tests__/documentLoadSave.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit project file UI**

```bash
git add src/editor/project src/editor/components/TopBar.tsx src/editor/components/EditorShell.tsx app/globals.css
git commit -m "feat: add editable project file workflows"
```

---

### Task 6: Build Resource Repair Center and permanent replacement commands

**Files:**
- Create: `src/editor/resources/ResourceRepairCenter.tsx`
- Create: `src/editor/resources/ResourceIssueRow.tsx`
- Create: `src/domain/editor/resourceCommands.ts`
- Modify: `src/domain/editor/commands.ts`
- Modify: `src/domain/editor/reducer.ts`
- Modify: `src/domain/editor/resourceEffects.ts`
- Modify: `src/domain/editor/__tests__/resourceEffects.test.ts`
- Modify: `src/editor/store/editorStore.ts`
- Modify: `src/editor/store/__tests__/editorStore.test.ts`
- Test: `src/editor/resources/__tests__/ResourceRepairCenter.test.tsx`
- Test: `src/domain/editor/__tests__/resourceCommands.test.ts`

**Interfaces:**
- Consumes: `ResourceIssue[]`, reconnect/retry service, typed resource replacement command.
- Produces: exact retry, reconnect, temporary display choice, permanent element/page/project replacement, removal, diagnostics.

- [ ] **Step 1: Write command scope and no-silent-save RED tests**

```ts
it.each(["element", "page", "project"] as const)("replaces a font at %s scope as one undoable command", (scope) => {
  const command = createFontReplacementCommand(document, {
    fromResourceId: "font-missing-brand",
    toBinding: exactFontBinding("noto-sans-kr", "sha256-noto"),
    scope,
    pageId: "page-1",
    elementId: "text-1",
  });
  const history = commitHistory(createHistoryState(document), applyCommand(document, command), describeCommand(command));
  expect(history.past).toHaveLength(1);
  expect(undoHistory(history).present).toEqual(document);
});
```

- [ ] **Step 2: Run repair RED tests**

Run: `npm test -- src/editor/resources/__tests__/ResourceRepairCenter.test.tsx src/domain/editor/__tests__/resourceCommands.test.ts`

Expected: FAIL.

- [ ] **Step 3: Implement typed permanent commands**

Add `resource.font.replace`, `resource.asset.replace`, and `resource.remove` command families. The command payload contains the validated exact-hash target binding and explicit scope. For font replacement, the reducer changes only matching family/weight/italic style usages in scope; for assets it rewrites only matching asset IDs while preserving element geometry/crop/effects. Extend A1 `resourceEffects` to update each affected usage locator/binding, and let the editor store persist that index in the same durable mutation. Temporary fallbacks remain outside commands/history.

- [ ] **Step 4: Implement Repair Center**

Group by issue, list affected pages/elements, support problem-only canvas filtering, exact retry, reconnect picker, replacement preview, scope confirmation, and diagnostic export. A wrong-hash resource stays quarantined and can never be selected as a replacement without being imported as a new validated resource.

- [ ] **Step 5: Run repair and history regressions**

Run: `npm test -- src/editor/resources src/domain/editor/__tests__/resourceCommands.test.ts src/domain/editor/__tests__/resourceEffects.test.ts src/domain/editor/__tests__/history.test.ts src/editor/store/__tests__/editorStore.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit Repair Center**

```bash
git add src/editor/resources src/domain/editor src/editor/store/editorStore.ts src/editor/store/__tests__/editorStore.test.ts
git commit -m "feat: repair missing project resources"
```

---

### Task 7: Add version, recovery, conflict, and edit-transfer UX

**Files:**
- Create: `src/editor/project/VersionHistoryPanel.tsx`
- Create: `src/editor/project/RecoveryDialog.tsx`
- Create: `src/editor/project/ConflictDialog.tsx`
- Create: `src/editor/project/EditLeaseBanner.tsx`
- Test: `src/editor/project/__tests__/VersionHistoryPanel.test.tsx`
- Test: `src/editor/project/__tests__/EditLeaseBanner.test.tsx`
- Modify: `src/editor/components/EditorShell.tsx`

**Interfaces:**
- Consumes: repository versions/checkpoints/recovery, A2 lease coordinator, conflict classification.
- Produces: preview, name, duplicate, restore-as-new-head, recovery-copy acceptance, keep-local/remote/both, live reader/transfer/copy.

- [ ] **Step 1: Write restore and transfer RED tests**

```tsx
await user.click(screen.getByRole("button", { name: "이 버전 복원" }));
expect(repository.saveCheckpoint).toHaveBeenCalledWith("project-1", expect.objectContaining({ reason: "before-restore" }));
expect(repository.restoreVersion).toHaveBeenCalledWith("project-1", "version-4");

await user.click(screen.getByRole("button", { name: "이 탭으로 편집권 가져오기" }));
expect(commitCoordinator.flush).toHaveBeenCalled();
expect(lease.requestTransfer).toHaveBeenCalled();
```

- [ ] **Step 2: Run version/lease RED tests**

Run: `npm test -- src/editor/project/__tests__/VersionHistoryPanel.test.tsx src/editor/project/__tests__/EditLeaseBanner.test.tsx`

Expected: FAIL.

- [ ] **Step 3: Implement version and recovery flows**

Version preview is read-only and never swaps the live store until confirmed. Restore first checkpoints current head and creates a new revision. Recovery always creates a new project ID in the same lineage. Named-version deletion shows referenced-resource size and cannot delete current head.

- [ ] **Step 4: Implement live-reader and conflict flows**

Readers reload repository snapshots on revision notifications. Buttons: move to writer tab, orderly transfer, edit a new copy. Conflict dialog never offers automatic merge; it exposes keep local as copy, keep remote with local recovery copy, or keep both.

- [ ] **Step 5: Run component regressions**

Run: `npm test -- src/editor/project src/project/lease src/project/recovery`

Expected: PASS.

- [ ] **Step 6: Commit recovery UI**

```bash
git add src/editor/project src/editor/components/EditorShell.tsx
git commit -m "feat: add project version and recovery UX"
```

---

### Task 8: Gate PNG/PDF and explicit degraded outputs

**Files:**
- Create: `src/editor/export/ExportGate.ts`
- Modify: `src/editor/components/DownloadPanel.tsx`
- Modify: `src/editor/export/exportService.ts`
- Modify: `src/editor/export/__tests__/exportService.test.tsx`
- Modify: `src/editor/components/__tests__/downloadPanel.test.tsx`

**Interfaces:**
- Consumes: `ExportReadiness`, PNG/PDF export options.
- Produces: blocked normal export and explicit `exportDegradedCopy` with report/filename.

- [ ] **Step 1: Write output-gate RED tests**

```ts
it("blocks ordinary PDF when a required font is unresolved", async () => {
  render(<DownloadPanel readiness={{ kind: "blocked", issues: [missingFontIssue()] }} />);
  await user.click(screen.getByRole("button", { name: "PDF" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("폰트 1개를 해결해야 합니다");
  expect(exportPdf).not.toHaveBeenCalled();
});

it("allows an explicit degraded copy with a report", async () => {
  await exportDegradedCopy(options(), [missingFontIssue()]);
  expect(download).toHaveBeenCalledWith(expect.objectContaining({ filename: expect.stringContaining("-degraded") }));
  expect(downloadReport).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run export-gate RED tests**

Run: `npm test -- src/editor/export/__tests__/exportService.test.tsx src/editor/components/__tests__/downloadPanel.test.tsx`

Expected: FAIL.

- [ ] **Step 3: Implement explicit gating**

Normal export calls `assertExportReady` before any render. Degraded export requires a separate confirmation listing issues, uses temporary render fallbacks without changing document, adds `-degraded` to filename, and downloads a JSON report with issue types and affected page/element IDs but no document text or resource bytes.

- [ ] **Step 4: Run export regressions**

Run: `npm test -- src/editor/export src/editor/components/__tests__/downloadPanel.test.tsx`

Expected: PASS including existing PNG/PDF size and page-order tests.

- [ ] **Step 5: Commit Export Gate**

```bash
git add src/editor/export src/editor/components/DownloadPanel.tsx src/editor/components/__tests__/downloadPanel.test.tsx
git commit -m "feat: gate exports on project fidelity"
```

---

### Task 9: Prove file round trip, repair, lineage, recovery, and accessibility

**Files:**
- Create: `tests/e2e/project-file-roundtrip.spec.ts`
- Create: `tests/e2e/project-repair.spec.ts`
- Modify: `tests/e2e/helpers/editor.ts`
- Modify: `package.json`

**Interfaces:**
- Consumes: complete B2 product flow.
- Produces: focused E2E scripts and accepted browser evidence.

- [ ] **Step 1: Add complete editable round-trip scenario**

Export the reference S project, clear the repository, import the file, verify all pages/elements/resources, perform undo/redo, edit every representative element, save again, and compare structure and expected rendered pixels.

- [ ] **Step 2: Add repair and conflict scenarios**

Cover missing embeddable font, prohibited font, missing glyph, missing image, same-name wrong hash, decode failure, unavailable trusted catalog, duplicate lineage, direct descendant, divergent copy, future required capability, recovery copy, one writer/one live reader, and orderly transfer.

- [ ] **Step 3: Add accessibility assertions**

Keyboard-only open/save/preflight/repair/version/transfer flows; focus trap/return; visible focus; semantic dialog/list/progress; live-region messages; severity not color-only; cancel available during worker work.

- [ ] **Step 4: Run the B2 focused gate**

Run:

```bash
npm run lint
npm test -- src/editor/project src/editor/resources src/editor/export src/project src/persistence
npx playwright test tests/e2e/project-file-roundtrip.spec.ts tests/e2e/project-repair.spec.ts --project=parity-1920 --workers=1
git diff --check
npm run graphify:update
```

Expected: all commands PASS with zero console or unhandled errors.

- [ ] **Step 5: Commit B2 evidence**

```bash
git add src tests/e2e package.json package-lock.json
git commit -m "test: prove editable project file recovery flows"
```
