# Context Intelligence

The v3 task packet is the worker context boundary. It selects exact task body,
file claims, acceptance commands, explicit spec sections, dependency outputs,
decisions, and immutable evidence refs. Missing or conflicting required mapping
blocks preflight.

At task boundaries, retain concise decisions, changed files, verification
results, and evidence digests. Discard raw transient output after the necessary
evidence is stored. Critical facts from a scout are reopened by Sol before a
write or verdict.

Context summaries are evidence inputs, not durable state authority. The event
stream records when the runtime accepts a context update.

The subscription live-matrix Sol v3 treatment applies the same boundary to its
small fixture repositories. The runner supplies a bounded UTF-8 snapshot of
tracked seed files plus the output of the fixture-owned baseline command. It
never includes untracked files, Git internals, or the hidden oracle tree. A
read-only worker can therefore return its structured finding without discovery
tool calls; a write worker edits from the supplied snapshot and runs the
acceptance command once. The exact rendered packet remains bound by the slot's
prompt digest in immutable evidence.
