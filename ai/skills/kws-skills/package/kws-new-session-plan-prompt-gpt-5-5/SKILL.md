---
name: kws-new-session-plan-prompt-gpt-5-5
description: Use when a user asks for a copy-paste fresh Codex session prompt, continuation handoff prompt, or prompt-only output based on an implementation plan, optionally with spec, design, or extra docs.
metadata:
  version: "2.2.1"
  updated_at: "2026-05-06"
---

# KWS New Session Plan Prompt

## Overview

Generate a paste-ready prompt that lets a fresh Codex session continue from known implementation documents without re-discovering scope, routing, verification, or handoff rules.

This skill produces the prompt only. Do not start implementation, edit the plan, or create a new plan unless the user separately asks for that work.

## Workflow

1. **Collect real paths.** Use explicit user paths first. Infer paths only from current local context when the target is unambiguous.
2. **Stop on missing plan.** If an implementation plan path is missing and cannot be inferred safely, ask one short question for the plan path.
3. **Verify local paths.** For local filesystem paths, confirm that required paths exist and are readable before placing them in the prompt.
4. **Fill only known documents.** Include spec, design, or extra docs only when the path is real. Remove optional placeholder bullets.
5. **Preserve output intent and language.** If the user asks for "prompt only", return only one fenced `text` block. Use the user's requested language when specified; otherwise preserve the template language.
6. **Validate before sending.** Load `references/pre-send-checklist.md` and check every generated prompt against it.

## Required Inputs

- Implementation plan path: required for execution prompts
- Spec or design doc paths: optional but include them when available
- Workspace path: include the absolute repo path when known

## Generated Prompt Requirements

Unless the user explicitly says otherwise, generated prompts must include:

- Absolute workspace, implementation plan, and known spec/design/extra doc paths.
- Repo-local instruction checks before edits.
- Task-by-task execution from Task 0 or Task 1 through the end, continuing in the current session by default.
- Checkbox plan updates when applicable.
- Subagent-driven execution with a fresh subagent per task and task closure only after implementation, two-stage review, fixes/re-review, verification, and agent cleanup.
- Quality-first routing defaults to `gpt-5.5 high` only for all work; other models require explicit user exception.
- When the user explicitly requests Spark or model-usage optimization, allow `gpt-5.3-codex-spark` scout mode only for read-only exploration, read-only inspection commands, non-mutating verification commands selected by `gpt-5.5 high` plus raw output collection, file/resource inventory, and `HANDOFF CHECKPOINT` drafts.
- Spark scout mode uses reasoning effort `high`.
- Spark scout mode must not decide implementation direction, root cause, review conclusions, verification interpretation, completion status, staging, commits, merges, pushes, PR creation, PR merge, release/version/changelog decisions, or other repository state mutations. It must not run file edits, formatters, dependency installs, migrations, cleanup commands, service lifecycle commands, or git state mutations.
- Spark output is only an input to `gpt-5.5 high`; before implementation or final judgment, `gpt-5.5 high` must directly verify the key files and conclusions.
- Do not create Spark scouts for small tasks, obvious single-file edits, or fixes whose root cause is already confirmed.
- One isolated `codex/...` integration worktree when possible, preserving unrelated changes in the original workspace.
- Session-owned resource tracking and cleanup by owner/command/PID/session id/port; broad `killall`/`pkill` cleanup is forbidden.
- Semantic handoff boundaries: leave short delta-focused `HANDOFF CHECKPOINT`s at Task/Phase boundaries so system compaction can be recovered from; `CONTINUATION PROMPT` is an exception only for user-blocking ambiguity, unresolved root-cause/verification failure, inability to reconstruct the next high-risk task safely, or clear context pressure.
- Verification ladder: context boundaries do not imply full-suite verification. Use the smallest honest check for phase work, broader checks at task completion or for high-risk/cross-area changes, and final verification at the end.
- Final documentation update: after implementation and feature verification, use `$kws-doc-prompt-review` to review and update relevant repository docs, README, AGENTS.md, prompt/operator docs, and agent-facing instructions before the final completion summary. If the relevant artifact is a Codex `SKILL.md` or skill bundle, use `$kws-skill-prompt-review` instead.
- Final verification before completion claims, then a short final summary of work, commands, models, worktree/branch, cleanup status, and risks.

## Stop Rules

- Do not invent plan/spec paths or leave placeholder paths in the final prompt.
- Do not leave template tokens such as `{{PLAN_PATH}}` or optional-section markers in the final prompt.
- Do not browse for docs unless the user explicitly asks or a referenced remote document must be fetched.
- Do not include Spark/model-usage optimization exceptions unless the user explicitly requested them.
- If repo state, plan path, or required docs are ambiguous enough to change execution scope, ask one short question instead of generating a brittle prompt.

## Success Criteria

The output is ready when:

- the prompt contains an absolute implementation plan path and known workspace path when available;
- all placeholder tokens and unused optional document bullets are removed;
- repo-local instruction checks, task-by-task execution, subagent review flow, semantic handoff checkpoints, resource cleanup, continuation stop rules, risk-scaled verification, and default `gpt-5.5 high` routing are explicit;
- Spark scout routing is absent unless explicitly requested, and narrowly scoped when included;
- final project documentation review/update with `$kws-doc-prompt-review`, or `$kws-skill-prompt-review` for skill artifacts, is explicit;
- the final answer respects the user's prompt-only preference.

## Output Style

Default to returning a single fenced `text` block that the user can paste into a fresh session.

If the user asks for "prompt only", return only the code block and nothing else.

If the user does not ask for prompt-only output, one short lead-in sentence is acceptable before the code block.

## Template

Use `templates/fresh-session-prompt.txt` as the prompt body and replace every `{{...}}` token with verified content or remove the optional section. Keep the generated output as a single fenced `text` block unless the user asks for surrounding explanation.

Only include document bullets that have real paths. Remove placeholder bullets such as missing design or extra docs.

Only include the `{{OPTIONAL_SPARK_SCOUT_BULLETS}}` section when the user explicitly asks for Spark, model-usage optimization, or model-specific exceptions. Otherwise remove it completely. When included, write it in the generated prompt language and preserve these constraints: `gpt-5.3-codex-spark high` scout mode, read-only/support-only, no judgment, no repository state mutation, and `gpt-5.5 high` must verify key files and conclusions.

For the default Korean prompt, replace `{{OPTIONAL_SPARK_SCOUT_BULLETS}}` with exactly this body. If the user requested another output language, translate this body without weakening or expanding the constraints:

```text
- 사용자가 명시적으로 Spark/model-usage optimization을 요청한 경우에만 `gpt-5.3-codex-spark` + reasoning effort `high` scout mode를 사용할 수 있다.
- Spark scout mode는 read-only 탐색, read-only inspection 명령, `gpt-5.5 high`가 선택한 non-mutating verification 명령의 실행 및 raw output 수집, 파일/리소스 인벤토리, `HANDOFF CHECKPOINT` 초안에만 허용된다.
- Spark scout mode는 구현 방향, root-cause, 리뷰 결론, 검증 해석, 완료 판단을 내리지 않는다. 파일 편집, formatter 실행, dependency install, migration, cleanup command, service lifecycle command, staging/commit/merge/push/PR 생성/PR merge/release/version/changelog 결정 등 repository state mutation을 수행하지 않는다.
- Spark 출력은 `gpt-5.5 high`의 판단 입력일 뿐이다. 구현 또는 최종 판단 전에 `gpt-5.5 high`가 핵심 파일과 결론을 직접 확인한다.
- 작은 Task, 명확한 단일 파일 수정, 이미 root cause가 확정된 수정에는 Spark scout를 만들지 않는다.
```

## Pre-Send Check

Before sending, load and verify against `references/pre-send-checklist.md`.

## Pressure Scenarios

- User gives a plan path and says "prompt only": output only one fenced `text` block.
- User asks "prompt only" but gives no plan path: ask one short question; do not output explanatory prose or a partial prompt.
- User gives a spec path but no plan path: ask for the implementation plan path instead of generating placeholder text.
- User gives plan, spec, and extra docs: include only those real paths and remove every unused template bullet.
- User gives a path that exists but is unreadable: report that specific path as a blocker.
- User gives an existing `codex/...` worktree: include it as the workspace path instead of instructing a second integration worktree unless the plan requires isolation.
- User asks to reduce GPT-5.5 usage with Spark: include the exact Spark scout replacement body as an opt-in support path only, keep implementation/review/root-cause/verification interpretation/final judgment on `gpt-5.5 high`, and forbid Spark-driven file edits, formatters, dependency installs, migrations, cleanup commands, service lifecycle commands, staging, commits, merges, pushes, and PR/release decisions.
- User does not mention Spark/model optimization: remove every Spark scout bullet from the generated prompt.
