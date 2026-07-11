# V3 Decisions

| Decision | Contract |
| --- | --- |
| Product boundary | CPE remains independent from Waygent |
| Core route | Sol/high for coordination, writes, reviews, verification, repair, and completion |
| Scout route | Terra/high only for bounded read-only, non-verdict work |
| Write scheduling | One write-capable task/attempt at a time |
| Durable authority | Immutable manifest, authoritative event chain, immutable evidence, rebuildable projection |
| Runtime ownership | PlanCompiler, PacketStore, AttemptController, RunKernel, CanonicalValidator, RecoveryEngine, and PublicCLI have non-overlapping boundaries |
| Spec context | Explicit task section mapping is required when a spec is supplied |
| Packet context | Every worker role consumes the manifest-indexed packet and verifies `packet_sha256` |
| Git evidence | Only implementation and repair write; the measured delta advances revision and invalidates older semantic success |
| Validation | One ordered registry exposes integrity and completion profiles to all consumers |
| Scheduler | Acceptance, task review, verification, repository checks, and final review repeat after a repair revision |
| Compatibility | Older schemas are preserved and reported as `unsupported_schema` |
| Repair | Dry-run first; exact allowlisted action, evidence, and expected projection delta for apply; `applied=false` is a valid no-op |
| Public result | One `PublicResult`; exit 0 only after canonical completion, blocked is 1, failed is 2 |
| Harness | Maintained inventory drives the public CLI; expectations come from an isolated oracle |
| Release | 3.0.1 is deterministic-ready and paid-live-pending after audited cost-free closure; paid evidence remains separate and release_ready stays false |
