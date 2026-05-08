---
name: kws-new-session-plan-prompt-gpt-5-5
description: Use when a user asks for a copy-paste fresh Codex session prompt, continuation handoff prompt, or prompt-only output based on an implementation plan, optionally with spec, design, or extra docs.
metadata:
  version: "2.2.5"
  updated_at: "2026-05-08"
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

## Required Inputs

- Implementation plan path: required for execution prompts
- Spec or design doc paths: optional but include them when available
- Workspace path: include the absolute repo path when known; ask only when inference could select the wrong repo or worktree

## Generated Prompt Requirements

Unless the user explicitly says otherwise, generated prompts must include:

- Absolute workspace, implementation plan, and known spec/design/extra doc paths.
- The invariant execution blocks already present in `templates/fresh-session-prompt.txt`: repo-local instruction checks, task-by-task execution, per-task execution contracts, subagent implementation plus two-stage `gpt-5.5 high` review, conservative automatic Spark evidence packing, checkbox updates, worktree isolation, unrelated-change handling, session-owned cleanup, structured semantic handoff checkpoints, continuation stop rules, retry budget and raw-output preservation for failures, risk-scaled verification, documentation impact check, and final summary.
- Quality-first routing: default all implementation, review, root-cause, verification interpretation, architecture/state/auth/persistence/shared-module judgment, and completion decisions to `gpt-5.5 high`; other models are allowed only for conservative automatic Spark evidence packing or explicit user exceptions.
- Conservative automatic Spark routing: unless the user forbids Spark/model optimization or requests `gpt-5.5 only`, generated prompts may let `gpt-5.5 high` use `gpt-5.3-codex-spark high` only for read-only evidence packing of commands/files selected by `gpt-5.5 high`.
- No broader Spark/model-usage optimization rules unless the user explicitly requests broader Spark scout routing, model-usage optimization, or a model-specific exception.
- Final verification before completion claims.

## Stop Rules

- Do not invent plan/spec paths or leave placeholder paths in the final prompt.
- Do not leave template tokens such as `{{PLAN_PATH}}` or optional-section markers in the final prompt.
- Do not browse for docs unless the user explicitly asks or a referenced remote document must be fetched.
- If the user forbids Spark/model optimization or requests `gpt-5.5 only`, remove conservative automatic Spark routing and any optional Spark scout bullets.
- Do not include broader Spark/model-usage optimization exceptions unless the user explicitly requested them.
- If repo state, plan path, or required docs are ambiguous enough to change execution scope, ask one short question instead of generating a brittle prompt.

## Success Criteria

The output is ready when:

- the prompt contains an absolute implementation plan path and known workspace path when available;
- all placeholder tokens and unused optional document bullets are removed;
- repo-local instruction checks, task-by-task execution, per-task execution contracts, subagent review flow, conservative automatic Spark evidence packing, structured semantic handoff checkpoints, resource cleanup, continuation stop rules, retry budget, raw-output preservation, risk-scaled verification, and default `gpt-5.5 high` judgment routing are explicit;
- broader Spark scout routing is absent unless explicitly requested, and narrowly scoped when included;
- final documentation impact check is explicit without requiring KWS-only review skills;
- the final answer respects the user's prompt-only preference.

## Output Style

Default to returning a single fenced `text` block that the user can paste into a fresh session.

If the user asks for "prompt only", return only the code block and nothing else.

If the user does not ask for prompt-only output, one short lead-in sentence is acceptable before the code block.

## Template

Use `templates/fresh-session-prompt.txt` as the prompt body and replace every `{{...}}` token with verified content or remove the optional section. Keep the generated output as a single fenced `text` block unless the user asks for surrounding explanation.

Only include document bullets that have real paths. Remove placeholder bullets such as missing design or extra docs.

Keep the conservative automatic Spark routing already present in `templates/fresh-session-prompt.txt` unless the user forbids Spark/model optimization or requests `gpt-5.5 only`; remove it in those cases.

Only include the `{{OPTIONAL_SPARK_SCOUT_BULLETS}}` section when the user explicitly asks for broader Spark scout routing, model-usage optimization beyond conservative evidence packing, or model-specific exceptions. Otherwise remove it completely. For the default Korean prompt, replace it with `templates/spark-scout-bullets.ko.txt` exactly. If the user requested another output language, translate that file without weakening or expanding the constraints.

## Pre-Send Check

Before sending, load and verify against `references/pre-send-checklist.md`.

## Pressure Scenarios

- User gives a plan path and says "prompt only": output only one fenced `text` block.
- User asks "prompt only" but gives no plan path: ask one short question; do not output explanatory prose or a partial prompt.
- User gives a spec path but no plan path: ask for the implementation plan path instead of generating placeholder text.
- User gives plan, spec, and extra docs: include only those real paths and remove every unused template bullet.
- User gives a path that exists but is unreadable: report that specific path as a blocker.
- User gives an existing `codex/...` worktree: include it as the workspace path instead of instructing a second integration worktree unless the plan requires isolation.
- User asks to reduce GPT-5.5 usage with broader Spark scout routing: include `templates/spark-scout-bullets.ko.txt` as an opt-in support path only, keep implementation/review/root-cause/verification interpretation/final judgment on `gpt-5.5 high`, and forbid Spark-driven file edits, formatters, dependency installs, migrations, cleanup commands, service lifecycle commands, staging, commits, merges, pushes, and PR/release decisions.
- User does not mention Spark/model optimization: keep only conservative automatic Spark evidence packing and remove every broader Spark scout bullet.
- User says no Spark, no model optimization, or `gpt-5.5 only`: remove both conservative automatic Spark routing and broader Spark scout bullets.
