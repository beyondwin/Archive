# Document Quality Contract

Use this contract when writing or checking spec and implementation documents.

## Spec Document

Required sections:

- `Overview`: concise problem and proposed outcome.
- `Goals`: concrete outcomes the work must achieve.
- `Non-goals`: boundaries that prevent scope creep.
- `Requirements`: stable IDs, requirement text, and acceptance criteria.
- `User Experience`: user-visible behavior, workflow, API, or CLI behavior.
- `Architecture`: affected components and data/control flow.
- `Data`: persisted data, migrations, generated artifacts, or explicit none.
- `Traceability Matrix`: maps each requirement to implementation and verification.
- `Verification Plan`: commands and manual smoke checks.
- `Risks`: failure modes, safety concerns, and mitigations.
- `Open Questions`: unresolved decisions or `None`.

## Implementation Document

Required sections:

- `Overview`: how implementation satisfies the spec.
- `Files`: expected files or directories to inspect/edit.
- `Implementation Plan`: ordered tasks with files and acceptance.
- `Traceability Matrix`: maps spec requirements to tasks and verification.
- `Verification Plan`: exact commands plus browser/manual smoke when relevant.
- `Rollback Plan`: how to undo or disable the change.
- `Risks`: residual implementation risks.
- `Done When`: observable completion criteria.

## Quality Rules

- Use repo-real paths, commands, components, and constraints.
- Do not leave TODO/TBD placeholders.
- Do not invent benchmark numbers, APIs, files, or tests.
- Include at least one command-form verification item.
- Include manual smoke/browser checks for user-facing UI, CLI, or route changes.
- Keep risk and open-question sections explicit even when the answer is `None`.
