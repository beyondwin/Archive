# Headless Runner

Headless mode uses the same v3 manifest, task packet, kernel, evidence,
reconciliation, and completion gates as interactive mode. Each core process is
launched with explicit Sol/high arguments and a structured output schema. A
read-only scout may be launched with Terra/high only when its request and
sandbox prohibit writes and verdicts.

The worker records bounded diagnostics, usage, latency, output digest, and
launcher attestation. It does not persist raw model transcripts. Missing output,
invalid schema, timeout, nonzero exit, or attestation mismatch becomes attempt
evidence and cannot be treated as completion.

Headless execution always targets the isolated execution worktree. Model
configuration files in the operator home or target repository are never
rewritten.
