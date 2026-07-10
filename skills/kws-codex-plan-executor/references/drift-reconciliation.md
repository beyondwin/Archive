# Drift, Reconciliation, And Repair

Reconciliation checks, in order: manifest and source hashes, event sequence and
hash chain, fresh projection, stored projection, git identity and diff, task
file claims, evidence digests, attempt terminal state and route attestation,
then verification/completion links.

Results are `clean`, `repairable`, or `blocking_drift`. Check and repair-plan
modes are read-only. Apply requires an exact run ID, an allowlisted action, and
explicit `--apply`.

Safe actions rebuild a projection from valid history, regenerate derived
reports, mark a provably stale attempt interrupted with a compensating event,
or reconnect an already present hash-valid evidence object. Repair cannot edit
product files, change source hashes, invent attestation or success, rewrite a
damaged event chain, or mutate an unsupported schema.
