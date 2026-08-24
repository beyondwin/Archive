# Image Quality Rubric

## Status Semantics

Use exactly four evidence statuses:

- `verified`: directly observed in the current run.
- `partially_verified`: a stated subset was observed and the missing portion is named.
- `not_measured`: no current evidence was collected.
- `blocked`: a required check could not run and its blocker is named.

## Visual Criteria

Open each deliverable candidate and check content completeness;
composition/crop; style, palette, material, and light; stated invariants; exact
visible copy or marks; and visible artifacts. Visual review remains required
even when file facts are available.

## Mechanical Criteria

For a project-bound final file, record detected format, dimensions, alpha when
exposed, byte size, SHA-256, and destination/path readiness with the local
inspector. These facts describe the file; they do not judge aesthetics, rights,
or the result of an edit.

## Critical Versus Advisory

Critical failures include a missing subject, failed edit invariant, incorrect
exact copy, unsafe crop, unverifiable path or dimensions for project handoff,
unauthorized overwrite, and an unknown material rights or privacy boundary.
An aesthetic preference is advisory unless the request makes it
acceptance-critical.

## Exact Copy And Invariants

Treat literal text, protected marks, identity, preserved background, crop-safe
area, and required layout as explicit checks. If an exact requirement cannot be
directly inspected or constructed deterministically, hold the handoff instead
of inferring success.

## Targeted Iteration

Name one failed critical or acceptance condition, apply one justified correction,
then reopen the candidate and repeat the relevant invariant checks. Stop when
the acceptance conditions are satisfied or a material condition remains blocked.

## Final Handoff

Report the path or preview, final prompt, operation or route, and all critical
statuses. Include whether integration changed consuming code or metadata. No
automatic score can replace opening the candidate.
