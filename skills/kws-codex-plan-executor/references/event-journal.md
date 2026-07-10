# Event Journal

`events.jsonl` is the authoritative CPE v3 transition history. The runtime
appends one canonical JSON event while holding an exclusive file lock, flushes
and fsyncs it, then rebuilds and atomically replaces `state.json`.

Validation rejects sequence gaps, duplicate event IDs, predecessor mismatch,
hash mismatch, invalid transitions, and a stored projection that differs from
replay. Evidence is referenced by digest rather than embedded as raw prompt,
transcript, secret, or unbounded command output.

Repair never edits or truncates the journal. A safe state change is represented
by a compensating event; rebuilding the projection does not require a new event.
