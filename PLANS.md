# Implementation Plan Template

Use this template for complex, ambiguous, or multi-step implementation work.
Keep plans specific enough that another agent can execute them without guessing.

## Goal

State the concrete outcome and why it matters.

## Context

- Relevant files:
- Relevant docs:
- Prior decisions or constraints:
- Out of scope:

## Task Breakdown

For each task:

```yaml
id: T1
title:
owner_boundary:
files:
  - path:
    mode: read|owned|edit
acceptance:
  - command:
  - expected:
risks:
  - describe the risk or leave this list empty
```

## Execution Order

- Parallel-safe tasks:
- Sequential/shared-core tasks:
- Human approval gates:

## Verification

- Targeted tests:
- Build/lint/type checks:
- Manual or browser checks:
- Honest substitute if a full check is too expensive:

## Review

Use `code_review.md` before reporting completion or creating a PR.
