# How CPE v3 Works

CPE resolves a plan, optional spec/docs, workspace, and execution mode. It
preflights task scope and acceptance criteria, creates an isolated worktree,
freezes an immutable manifest, then records all durable transitions in
`events.jsonl`.

Each task receives only its packet: dependencies, allowed files, explicit spec
sections, acceptance commands, and evidence requirements. Write tasks execute
sequentially. Core attempts use Sol/high. A bounded read-only scout may use
Terra/high, but cannot edit or issue a verdict.

The transition kernel appends events and projects `state.json`. Models never
edit durable executor artifacts. Completion replays the run and checks event
integrity, evidence digests, git scope, task and final reviews, verification,
model attestation, blockers, and repository-specific gates.

Prompt and handoff export stop after rendering one launcher bundle and create
no run artifacts. Resume, validation, reconciliation, repair, and inspection
accept v3 runs only. An older schema is preserved and reported as
`unsupported_schema`.
