---
name: kws-spec-implementation-docs
description: Use when creating or revising repository-grounded spec documents, implementation documents, design specs, detailed implementation references, or approval-ready planning docs.
---

# KWS Spec Implementation Docs

## Overview

Create two approval-ready artifacts from real repository context: a spec
document that defines the desired product/engineering outcome, and an
implementation document that turns the spec into traceable, verifiable work.

This skill is for document production only. Do not implement code, stage files,
commit, or merge unless the user separately requests execution.

## Workflow

1. Read repo instructions first: `AGENTS.md`, subtree `AGENTS.md`, and any
   named source docs or plans.
2. Inspect current state: run `git status --short --branch --untracked-files=all`,
   search existing docs with `rg`, and read the relevant code paths before
   drafting.
3. Preserve approval boundaries. If the user is choosing a direction, present a
   small option set first. After `승인` or equivalent, write the spec and
   implementation document without reopening the decision.
4. Write the spec document before the implementation document. The spec owns
   goals, non-goals, requirements, UX/API behavior, architecture, data, risks,
   open questions, and acceptance criteria.
5. Write the implementation document from the approved spec. It owns files,
   task order, dependency boundaries, verification commands, rollback, and
   done-when evidence.
6. Keep both docs grounded in existing repo names, paths, commands, and tests.
   Mark unknowns as open questions instead of inventing facts.
7. Run `scripts/check_doc_quality.py` on the finished docs and fix failures
   before reporting completion.

## Required Output

Produce or update both artifacts unless the user explicitly asks for only one:

- `spec document`: default to `docs/superpowers/specs/<date>-<slug>-design.md`
  when the repo has that directory; otherwise follow the repo's existing doc
  pattern.
- `implementation document`: default to
  `docs/superpowers/plans/<date>-<slug>.md` for execution plans, or
  `docs/implementation/<slug>.md` for detailed implementation references when
  that pattern already exists.

Each document must include a `Traceability Matrix` and `Verification Plan`.
Use `references/doc-quality-contract.md` for the full section contract.

## Quality Gates

Before final response:

```bash
python3 <skill-dir>/scripts/check_doc_quality.py --spec <spec.md> --implementation <implementation.md> --repo-root <repo>
git diff --check
```

For docs-only work, manually inspect touched links and paths. If the repository
mentions Graphify, run `graphify update .` after meaningful documentation
structure changes and report whether tracked or ignored outputs changed.

## Common Failures

- Treating the implementation document as a vague checklist. Fix by mapping
  each requirement to concrete files, tasks, and verification.
- Writing a polished spec without checking the repo. Fix by reading code,
  existing docs, and available commands before drafting.
- Hiding uncertainty. Fix by adding explicit `Open Questions`, `Risks`, or an
  honest verification substitute.
- Continuing into code changes after docs are approved. Stop at the handoff
  boundary until the user asks for implementation.
