# State, Evidence, And Logging

## Authority

`run_manifest.json` freezes input identity. `events.jsonl` is the authoritative
transition history. `state.json` is a rebuildable projection. Content-addressed
objects under `artifacts/evidence/` carry task, review, verification, usage,
attestation, and repair evidence.

The manifest indexes every immutable task packet and digest. Semantic evidence
records its task/attempt, `packet_sha256`, current `worktree_revision`, and
`worktree_patch_sha256`; attachment alone does not make stale or mismatched
evidence valid.

The kernel is the only durable writer. It locks and fsyncs an event append,
replays the manifest and events, then atomically replaces the projection.
Inspection and recent-run reports are derived and read-only. The same ordered
canonical validator registry powers standalone validation, kernel transitions,
reconciliation, repair planning, inspection, resume, and public success.

## Privacy

Events and evidence use bounded summaries and run-relative references. Do not
persist secrets, raw transcripts, full prompts, absolute home paths, or
unbounded command output. Verify every evidence digest before trusting it.

## Recovery

An interrupted projection write is recoverable by replay. A damaged event
chain, changed manifest/source hash, missing or mismatched model attestation,
or out-of-scope diff is blocking drift. Healthy running state may pass
integrity without passing completion. Repair is dry-run by default, preserves
resolved blockers in history, and cannot erase history or invent success.

## Compatibility

V3 consumers read schema `3`. For an older schema they return
`unsupported_schema` and do not resume, repair, migrate, or rewrite it.
