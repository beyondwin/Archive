# How CPE v3 Works

CPE resolves a plan, optional spec/docs, workspace, and execution mode. It
reads source bytes into an internal input snapshot, preflights task scope and
acceptance criteria, creates an isolated worktree, freezes an immutable
manifest, then records all durable transitions in `events.jsonl`.

Each task receives only its manifest-indexed, digest-verified packet:
dependencies, allowed files, explicit spec sections, acceptance commands, and
evidence requirements. Scout, implementation, task review, verification,
repair, and final review all consume that packet. Write tasks execute
sequentially, and only implementation and repair can write. Core attempts use
Sol/high. A bounded read-only scout may use Terra/high, but cannot edit or issue
a verdict.

The transition kernel appends events and projects `state.json`. Models never
edit durable executor artifacts. Every measured write advances a worktree
revision and invalidates old acceptance or verdict evidence. The scheduler
runs acceptance, task review, verification, the repository command bundle, and
final review in order, repairing and repeating the suffix when required.
Completion replays the run and uses the canonical integrity and completion
profiles to check evidence digests, git scope, verdicts, model attestation,
blockers, and repository-specific gates.

Prompt and handoff export stop after rendering one launcher bundle and create
no run artifacts. Resume, validation, reconciliation, repair, and inspection
accept v3 runs only. An older schema is preserved and reported as
`unsupported_schema`.

The public CLI emits one `PublicResult` JSON object with `success=0`,
`blocked=1`, or `failed=2`. The maintained eval inventory exercises this public
CLI in temporary repositories and checks it against an isolated oracle rather
than duplicating production logic in a fixture runner.
