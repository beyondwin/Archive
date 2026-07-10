# State, Evidence, And Logging

## Authority

`run_manifest.json` freezes input identity. `events.jsonl` is the authoritative
transition history. `state.json` is a rebuildable projection. Content-addressed
objects under `artifacts/evidence/` carry task, review, verification, usage,
attestation, and repair evidence.

The kernel is the only durable writer. It locks and fsyncs an event append,
replays the manifest and events, then atomically replaces the projection.
Inspection and recent-run reports are derived and read-only.

## Privacy

Events and evidence use bounded summaries and run-relative references. Do not
persist secrets, raw transcripts, full prompts, absolute home paths, or
unbounded command output. Verify every evidence digest before trusting it.

## Recovery

An interrupted projection write is recoverable by replay. A damaged event chain,
changed manifest/source hash, missing or mismatched model attestation, or
out-of-scope diff is blocking drift. Repair is dry-run by default and cannot
erase history or invent success.

## Compatibility

V3 consumers read schema `3`. For an older schema they return
`unsupported_schema` and do not resume, repair, migrate, or rewrite it.
