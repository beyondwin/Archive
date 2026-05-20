Source-of-truth: the design document wins when this reference and code disagree.

# Runtime Adapters

Adapters expose AdapterCapabilities, including runtime, reattach support,
streaming support, and `network_egress` allowlists.

Adapters implement process lifecycle: prepare, start, poll, collect, cancel, and
reattach. Codex uses `codex exec` and is treated as non-reattachable. Claude uses
headless `claude -p` and may reattach when WorkerHandle session metadata is
available. Both write stdout/stderr logs and return runner-validated
`worker_result.json` artifacts.

The production supervisor owns state transitions and treats adapter output as
untrusted until schema validation, method audit, and diff-scope checks pass.
