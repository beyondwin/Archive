# V3 Decisions

| Decision | Contract |
| --- | --- |
| Product boundary | CPE remains independent from Waygent |
| Core route | Sol/high for coordination, writes, reviews, verification, repair, and completion |
| Scout route | Terra/high only for bounded read-only, non-verdict work |
| Write scheduling | One write-capable task/attempt at a time |
| Durable authority | Immutable manifest, authoritative event chain, immutable evidence, rebuildable projection |
| Spec context | Explicit task section mapping is required when a spec is supplied |
| Compatibility | Older schemas are preserved and reported as `unsupported_schema` |
| Repair | Dry-run first; exact allowlisted action for apply; no fabricated success |
| Release | 3.0.0 remains deterministic-ready and paid-live-pending until a passing live report |
