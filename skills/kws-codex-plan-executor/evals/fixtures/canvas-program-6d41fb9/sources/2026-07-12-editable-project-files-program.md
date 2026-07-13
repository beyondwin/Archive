# Editable Project Files Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the approved Miricanvas parity expansion with durable project history, portable `.canvasclone` files, resilient resource repair, editable user templates, and server-ready synchronization/catalog contracts.

**Architecture:** Preserve `DesignDocument` and the typed reducer as the editing core. Insert a project envelope, reversible journal, and transactional local repository immediately after Schema V3, then finish the editor feature waves before building the package, repair, template, and server-contract layers. The existing Wave 6 remains the only final evidence gate and runs after the extended suite.

**Tech Stack:** Next.js 16, React 19, TypeScript 5, Zustand 5, Konva 10, IndexedDB/idb 8, Vitest 3, Testing Library, Playwright 1.50, fflate 0.8.3, @noble/hashes 2.2.0, fast-json-patch 3.1.1, DOMPurify 3.4.12.

## Global Constraints

- Native editable format is `.canvasclone`; do not add PPTX or DOCX import/export.
- Preserve every supported page element as structured editable data: text, photo/image, icon/SVG, table, shape, line, chart, background, layer order, groups, and common geometry/state.
- Keep `document/current.json` independently loadable even when history or workspace data is damaged.
- Retain 200 ordinary operations, 20 automatic checkpoints, named versions, and at most five discarded redo branches for seven days.
- Store user assets and legally embeddable fonts by exact SHA-256; never silently persist a fallback font or same-name replacement asset.
- Native project backup remains available as explicitly `external-resources-required` or `repair-required` when exact bytes are unavailable; it preserves editable structure/original hashes but is not labeled portable/full-fidelity. Templates/page fragments must be complete.
- Block ordinary PNG/PDF and server publication while required resources or capabilities are unresolved; degraded output requires an explicit user action and report.
- Package limits: project 768 MiB compressed/2 GiB uncompressed, template 128 MiB compressed/512 MiB uncompressed, 10,000/2,500 entries, 200 pages, 20,000 elements, 5,000 resources, 100 megapixels per raster, 100 MiB encoded raster, 32 MiB per font, and 64 embedded fonts.
- Only one local writer tab may edit a project until a real server collaboration engine exists; other tabs follow live read-only revisions and can request an orderly transfer.
- Phases A-C implement local product behavior and deterministic server fakes only. Production auth/API/DB/S3/CDN is Phase D; real-time collaboration is Phase E and requires separate approval.
- No package may auto-run JavaScript, macros, plugins, HTML, external URLs, data connections, or active media.
- Preserve the existing parity scope and do not weaken the approved catalog, inspector, table, accessibility, export, visual, or evidence requirements.
- Run `graphify update .` after code changes in every new wave.

---

## Authoritative Execution Order

| Stage | Plan | Working deliverable | Depends on |
|---|---|---|---|
| 1 | `2026-07-12-miricanvas-design-editor-wave-1-foundation-shell-pages.md` | Schema V3, transient table selection, shell/page foundations | Approved parity spec |
| 2 | `2026-07-12-editable-project-wave-a1-domain-history.md` | Project envelope, canonical hashes, reversible journal, bounded in-memory history | Stage 1 |
| 3 | `2026-07-12-editable-project-wave-a2-local-repository-recovery.md` | Transactional project repository, migration, durable commits, checkpoints, recovery, multi-tab lease | Stage 2 |
| 4 | `2026-07-12-miricanvas-design-editor-wave-2-layers.md` | Layer panel and layer commands recorded through the durable boundary | Stage 3 |
| 5 | `2026-07-12-miricanvas-design-editor-wave-3-catalogs-assets.md` | Licensed catalogs, distinct editable template sources, real previews and backgrounds | Stage 4 |
| 6 | `2026-07-12-miricanvas-design-editor-wave-4-inspectors-crop.md` | Complete element inspectors and crop commands | Stage 5 |
| 7 | `2026-07-12-miricanvas-design-editor-wave-5-table-editor.md` | Complete table command model, selection, merge, structure, clipboard | Stage 6 |
| 8 | `2026-07-12-editable-project-wave-b1-package-codec-security.md` | Streaming `.canvasclone` codec, integrity, security limits, schema migration corpus | Stage 7 |
| 9 | `2026-07-12-editable-project-wave-b2-import-repair-ux.md` | File/open/save/export flows, preflight, lineage decisions, Resource Repair Center, Export Gate | Stage 8 |
| 10 | `2026-07-12-editable-project-wave-c1-portable-user-templates.md` | Multi-page application, user templates/page fragments, privacy cleanup, resource claims | Stage 9 |
| 11 | `2026-07-12-editable-project-wave-c2-server-contracts-integration.md` | Sync/Catalog contracts and fakes, immutable template storage fixtures, outbox/conflict integration | Stage 10 |
| 12 | `2026-07-12-miricanvas-design-editor-wave-6-integration-evidence.md` | Rebased ledger, all-element round trip, recovery/security/performance/browser evidence, final gate | Stage 11 |

Do not run the old numeric waves as an uninterrupted 1→6 sequence. Stages 2 and 3 must be complete before new persistent commands are added in stages 4-7. The existing Wave 6 is final only when every stage above has passed focused tests and review.

## Spec Coverage Map

| Design sections | Owning stage |
|---|---|
| 6-9 architecture, identity, all-element coverage | A1 |
| 12-14 history, durability, crash recovery, multi-tab | A1-A2 |
| 10-11 package format and profiles | B1 |
| 15-16 font and asset policy | B1-B2 |
| 19 import/export/conflicts, 20 UX, 21 errors | B2 |
| 17 editable/user templates | Existing Wave 3, then C1 |
| 18 future server storage and lifecycle | C2 contracts; Phase D implementation later |
| 22 security, 23 performance | B1-B2, enforced in final Wave 6 |
| 24 verification, 26 ledger, 27 completion | C2 and final Wave 6 |

## File Ownership Map

### A1 owns

- `src/domain/project/**`
- `src/domain/editor/history.ts` and its focused tests
- Project-aware command commit metadata in `src/editor/store/editorStore.ts`
- Dependency additions for canonical hashing and reversible JSON patches

### A2 owns

- `src/persistence/projectRepository.ts`
- `src/persistence/indexedDbProjectRepository.ts`
- `src/persistence/projectMigration.ts`
- `src/project/commit/**`, `src/project/recovery/**`, `src/project/lease/**`
- Local durability integration in save/load hooks and top-level editor composition

### B1 owns

- `src/project/package/**`
- `src/project/security/**`
- `src/project/workers/**`
- `src/project/__fixtures__/**`
- Package/security/performance dependencies and focused tests

### B2 owns

- `src/editor/project/**`
- `src/editor/resources/**`
- Project file menu, preflight, version, conflict, and Repair Center components
- `.canvasclone` E2E helpers and focused browser specs
- PNG/PDF Export Gate integration

### C1 owns

- `src/domain/template/**`
- `src/editor/templates/**`
- User-template and page-fragment repositories/components
- Template sanitization, ID remapping, resource claims, and package profiles

### C2 owns

- `src/sync/**`
- `src/catalog/gateway/**`
- `src/server-contracts/**`
- `scripts/validate-project-contracts.mjs` and fixtures
- New parity ledger rows and final-gate inputs for editable project files

Existing waves retain ownership of their declared element, catalog, inspector, canvas, table, export renderer, and evidence files. A new wave may change an existing owner only through an interface explicitly named in that wave's plan.

## Dependency and Migration Rules

1. Add `@noble/hashes@^2.2.0` and `fast-json-patch@^3.1.1` in A1.
2. Add `fflate@^0.8.3` and `dompurify@^3.4.12` in B1.
3. Do not add a general event-sourcing, CRDT, collaboration, backend SDK, S3 SDK, or database client dependency in A-C.
4. IndexedDB schema upgrades preserve all current `documents` and `assets` entries until each document has a validated project migration.
5. The old `PersistenceAdapter` remains as a temporary compatibility facade until A2 migrates all editor consumers; remove it only after focused load/save tests prove parity.
6. Package schemas, document schemas, history schemas, and resource schemas version independently.

## Execution Rules

1. Use an isolated worktree at implementation time.
2. Begin each task with the exact focused RED in its wave plan.
3. Observe the expected failure before implementation.
4. Keep each task independently reviewable and commit it after focused and affected regression tests pass.
5. Never accept a silent recovery, substitution, partial template application, or last-writer overwrite as a shortcut.
6. Every task that adds a resource-bearing or ID-generating command must extend A1 `resourceEffects` mapping tests in the same commit.
7. Do not run the complete parity E2E suite in intermediate tasks; run the focused specs named by the plan.
8. Run `git diff --check` and inspect the task diff before each commit.
9. Run `graphify update .` at the end of each new wave.
10. Stage 12 alone runs the complete final validation and makes any product-completion claim.

## Final Handoff Contract

The program is complete only when Stage 12 proves:

- A clean `.canvasclone` round trip containing every supported element family.
- Cross-reopen 200-operation undo/redo and checkpoint/version recovery.
- Missing-font, missing-asset, wrong-hash, and degraded-output behavior.
- User-template and multi-page template behavior with privacy cleanup.
- Multi-tab edit transfer and crash recovery.
- Fake server fast-forward, conflict, retry, immutable catalog version, unpublication, and offline cache behavior.
- Package security fuzz and historical migration corpus.
- Reference S and stress L performance budgets.
- Chromium, Firefox, and Playwright WebKit capability fallbacks; a real macOS Safari smoke is required before a Safari-specific support claim.
- Existing design-editor parity, PNG/PDF, accessibility, visual, build, and clean-worktree gates.
