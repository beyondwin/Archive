---
name: kws-new-session-plan-prompt-gpt-5-5
description: Use when a user asks for a copy-paste fresh Codex session prompt, continuation handoff prompt, or prompt-only output based on an implementation plan, optionally with spec, design, or extra docs.
metadata:
  version: "2.3.0"
  updated_at: "2026-05-13"
---

# KWS New Session Plan Prompt

## Overview

Generate a paste-ready prompt that lets a fresh Codex session continue from known implementation documents without re-discovering scope, routing, verification, or handoff rules.

This skill produces the prompt only. Do not start implementation, edit the plan, or create a new plan unless the user separately asks for that work.

## Workflow

1. **Collect real paths.** Use explicit user paths first. Infer paths only from current local context when the target is unambiguous.
2. **Stop on missing plan.** If an implementation plan path is missing and cannot be inferred safely, ask one short question for the plan path.
3. **Resolve workspace conservatively.** Use an explicit workspace first. Otherwise infer only from the plan path's git root or the current repo when there is one clear candidate; ask if multiple roots could change scope.
4. **Verify local paths.** For local filesystem paths, confirm that required paths exist and are readable before placing them in the prompt.
5. **Fill only known documents.** Include spec, design, or extra docs only when the path is real. Remove optional placeholder bullets.
6. **Preserve output intent and language.** If the user asks for "prompt only", return only one fenced `text` block. Use the user's requested language when specified; otherwise preserve the template language.
7. **Validate before sending.** Load `references/pre-send-checklist.md` and check every generated prompt against it.

## Inputs

- Implementation plan path: required for execution prompts
- Spec or design doc paths: optional but include them when available
- Workspace path: include the absolute repo path when known; ask only when inference could select the wrong repo or worktree

## Required Invariants

Unless the user explicitly says otherwise, generated prompts must include:

- Verified absolute workspace, implementation plan, and known spec/design/extra doc paths; no placeholder paths, unused optional bullets, or template tokens.
- The invariant execution blocks in `templates/fresh-session-prompt.txt`: repo-local instruction checks, Task 0/1 start handling, task-by-task execution, per-task execution contracts, lightweight session ledger, task risk ledger, subagent implementation plus two-stage `gpt-5.5 high` review, recurring issue detection, worktree isolation, unrelated-change handling, session-owned cleanup, structured checkpoints, continuation stop rules, retry budget, raw-output preservation, ENV_BLOCKER triage, risk-scaled verification, documentation impact check, and final summary.
- Quality-first routing: all implementation, review, root-cause, verification interpretation, architecture/state/auth/persistence/shared-module judgment, and completion decisions stay on `gpt-5.5 high`.
- Conservative automatic Spark evidence packing is included unless the user forbids Spark/model optimization or requests `gpt-5.5 only`; broader Spark scout routing is included only for an explicit broader Spark/model-routing request.
- Source-of-truth plan progress updates are explicit: if generated prompts tell agents to update checkboxes or status in original plan docs, they must also tell agents to inspect whether those docs are tracked, untracked, dirty, and intended for commit.
- Prompt-only and requested-language behavior is preserved, and final verification before completion claims is explicit.

## Stop Rules

- If an implementation plan path is missing and cannot be inferred safely, ask one short question; do not generate a partial prompt.
- If repo state, workspace, plan path, or required docs are ambiguous enough to change execution scope, ask one short question.
- If a local path exists but is unreadable, report that path as a blocker.
- If the user forbids Spark/model optimization or requests `gpt-5.5 only`, remove conservative automatic Spark routing and any optional Spark scout bullets.
- Do not include broader Spark/model-usage optimization exceptions unless the user explicitly requested them.
- Do not include low-risk main-agent implementation shortcuts unless the user explicitly asks for lean/cost-optimized execution. Default prompts preserve fresh implementation subagents and two-stage review.
- Do not browse for docs unless the user explicitly asks or a referenced remote document must be fetched.

## Output Style

Default to returning a single fenced `text` block that the user can paste into a fresh session.

If the user asks for "prompt only", return only the code block and nothing else.

If the user does not ask for prompt-only output, one short lead-in sentence is acceptable before the code block.

## Template Rules

Use `templates/fresh-session-prompt.txt` as the prompt body and replace every `{{...}}` token with verified content or remove the optional section. Keep the generated output as a single fenced `text` block unless the user asks for surrounding explanation.

Only include document bullets that have real paths. Remove placeholder bullets such as missing design or extra docs.

Keep the conservative automatic Spark routing already present in `templates/fresh-session-prompt.txt` unless the user forbids Spark/model optimization or requests `gpt-5.5 only`; remove it in those cases.

Only include the `{{OPTIONAL_SPARK_SCOUT_BULLETS}}` section when the user explicitly asks for broader Spark scout routing, model-usage optimization beyond conservative evidence packing, or model-specific exceptions. Otherwise remove it completely. For the default Korean prompt, replace it with `templates/spark-scout-bullets.ko.txt` exactly. If the user requested another output language, translate that file without weakening or expanding the constraints.

## Pre-Send Check

Before sending, load and verify against `references/pre-send-checklist.md`.

## Skill Maintenance

When editing this skill itself, use `references/change-protocol.md`. Keep runtime behavior in `SKILL.md` and `templates/`, long rationale in `references/`, regression scenarios in `evals/`, and non-trivial experiment records in `docs/experiments/`.

On behavior changes, update `HISTORY.md` and package metadata (`manifest.json`, package `README.md`, and `CHANGELOG.md`) in the same change. Update `ARCHITECTURE.md` when the generation flow, routing contract, validation gates, or maintenance/eval structure changes.

## Pressure Scenarios

- Plan path + "prompt only": output only one fenced `text` block; no plan path: ask one short question.
- Spec/design path but no plan path: ask for the implementation plan path instead of generating placeholders.
- Multiple docs: include only readable real paths; unreadable paths are blockers.
- Existing `codex/...` worktree: include it as workspace instead of instructing a second integration worktree unless the plan requires isolation.
- Spark routing: default to conservative evidence packing only; broader Spark requires explicit request; no-Spark or `gpt-5.5 only` removes every Spark route.
- Continuation prompt: preserve any existing `.codex-orchestrator/session.json` path and instruct the fresh session to read it before resuming task execution.
- Source-of-truth plan outside an integration worktree: include explicit git-status handling for the original plan document and do not let agents stage or commit unrelated plan/doc changes by inference.
- Lean/cost-optimized execution request: allow low-risk single-file hygiene tasks to skip implementation subagents only when the user explicitly requests that mode; keep fresh `gpt-5.5 high` reviews and honest verification.
