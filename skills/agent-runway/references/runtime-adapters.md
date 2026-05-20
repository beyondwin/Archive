Source-of-truth: the design document wins when this reference and code disagree.

# Runtime Adapters

Adapters expose AdapterCapabilities, including runtime, reattach support,
streaming support, and `network_egress` allowlists.

Adapters implement process lifecycle: prepare, start, poll, collect, cancel, and
reattach. Codex uses `codex exec` and is treated as non-reattachable. Claude uses
headless `claude -p` and may reattach when WorkerHandle session metadata is
available. Both write stdout/stderr logs and return runner-validated
`worker_result.json` artifacts.

Codex workers are launched with an explicit `workspace-write` sandbox and the
runner artifact directory is passed as an additional writable directory. Claude
workers are launched with `acceptEdits`, the runner artifact directory as an
additional directory, and a bounded tool allowlist for git, basic file creation,
Python/pytest, and edit tools. The process supervisor pins the worker worktree
with `cwd=` and detaches worker stdin so headless CLIs cannot accidentally read
or block on the parent process input stream.

The production supervisor owns state transitions and treats adapter output as
untrusted until schema validation, method audit, and diff-scope checks pass.
