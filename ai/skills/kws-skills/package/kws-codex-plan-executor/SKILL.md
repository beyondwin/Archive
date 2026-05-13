---
name: kws-codex-plan-executor
description: Use when executing an implementation plan in Codex from a plan path and optional spec/design docs, or when exporting a fresh-session/handoff prompt from the same plan.
metadata:
  version: "1.2.1"
  updated_at: "2026-05-13"
---

# KWS Codex Plan Executor

## Overview

Execute implementation plans in Codex or export a paste-ready prompt from the
same inputs.

Default behavior is interactive execution in the current Codex session.
Headless execution and prompt export require explicit mode selection.

## Invocation

Supported arguments:

- `plan=<abs-or-repo-relative-path>` required except resume-only flows.
- `spec=<path>` optional.
- `docs=<path1,path2>` optional.
- `workspace=<path>` optional.
- `resume=latest|<state-path>` optional; if multiple candidate states exist,
  stop and ask which state to resume.
- `mode=interactive|headless|prompt|handoff` optional, default `interactive`.
- `subagents=on|off` optional, default `off` unless the user explicitly asked for subagents, delegation, or parallel work.
- `headless_sandbox=workspace-write|read-only` optional, default `workspace-write`;
  `read-only` is for preflight/prompt verification and blocks edit execution.

## Hard Boundary

Do not use `--dangerously-bypass-approvals-and-sandbox` unless the user
explicitly requests it and the target is an isolated throwaway repo or CI
sandbox.

Use `spawn_agent` only when the user explicitly asks for subagents, delegation,
parallel work, or passes `subagents=on`.

## Core Invariants

- No edits before a 5-line `TASK EXECUTION CONTRACT` is stated and recorded:
  `scope`, `files_to_inspect`, `allowed_edits`, `forbidden_edits`, and
  `acceptance_command_or_honest_substitute`.
- Before execution, classify dirty worktree changes as `related` or
  `unrelated`. Continue past unrelated dirty files only when they are outside
  the declared task files; stop before touching related dirty files.
- Execution plans may use `Files`, `Affected files`, `Modified files`,
  `Changed files`, `수정 파일`, `변경 파일`, `대상 파일`, or `파일` headings for
  task file blocks. Execution mode still stops if no file block is present.
- Resume mode uses `.codex-orchestrator/state.json` as source of truth. Do not
  infer between multiple ambiguous states.
- In `interactive` and `headless` execution, record execution-only redacted
  notable-boundary learning events with `scripts/append_learning_event.py` and
  `references/learning-log.md`; `prompt` and `handoff` are not logging modes.

## Workflow

1. Resolve and verify paths. Prefer explicit paths; infer only when one
   workspace and one plan are unambiguous.
2. Select mode. Read `references/mode-contracts.md` if behavior is not obvious.
3. For `prompt` or `handoff`, use `templates/fresh-session-prompt.txt` and
   `references/prompt-export-checklist.md`.
4. For `interactive`, follow `references/execution-cycle.md`.
5. For `headless`, follow `references/headless-runner.md`.
6. Maintain `.codex-orchestrator/state.json` using
   `references/state-schema.md`.
7. For execution modes, record learning events at notable boundaries using
   `references/learning-log.md`.
8. Validate using scripts before claiming completion.

## Stop Rules

- Missing or unreadable plan: ask one short question or report blocker.
- Dirty worktree with related ambiguity: stop and report.
- Ambiguous `resume=latest` with multiple state files: stop and ask.
- Missing `Files:` blocks in execution mode: stop before edits.
- Unclear acceptance criteria on mid/high risk tasks: stop for clarification
  unless the plan gives an honest substitute.
- Verification failure without root cause after 3 same-root retries: stop with
  checkpoint.

## Prompt Export

For prompt/handoff mode:

1. Verify workspace, plan, spec, and docs paths before inserting them.
2. Fill every `{{...}}` token in `templates/fresh-session-prompt.txt` or remove
   the optional section.
3. Keep conservative Spark evidence packing unless the user requests no Spark,
   no model optimization, or `gpt-5.5 only`.
4. Include `templates/spark-scout-bullets.ko.txt` only when the user explicitly
   asks for broader Spark/model scout routing.
5. Run the checklist in `references/prompt-export-checklist.md`.

Return only one fenced `text` block when the user asks for prompt-only output.

## Validation Matrix

| Mode | Required checks before completion |
|------|-----------------------------------|
| `interactive` | `scripts/parse_plan.py`, changed-project tests or honest substitute, `scripts/validate_state.py` |
| `headless` | `scripts/parse_plan.py`, acceptance command or honest substitute, `scripts/validate_state.py`, headless JSONL/final artifact review |
| `prompt` | `evals/check_prompt.py` or the prompt export checklist when no fixture exists |
| `handoff` | `evals/check_prompt.py` or the prompt export checklist, plus source state/path readability |

## Maintenance

Use `references/change-protocol.md` before editing this skill. Update
`HISTORY.md`, `ARCHITECTURE.md`, package metadata, and eval baselines for
behavior changes.

For eval harness runs, the outer harness runs `evals/check_execution.py`.
The target executor must not inspect fixture YAML, baseline files, `.harness`
metadata, or expected values.
