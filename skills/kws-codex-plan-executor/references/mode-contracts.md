# Mode Contracts

## interactive

Create or resume a dedicated execution worktree at
`~/.codex/worktrees/<plan-slug>-<YYYYMMDD-HHMMSS>`. Keep all executor state in
`~/.codex/orchestrator/<run_id>/state.json`. `subagents=on` is the default and
uses task-packet-scoped subagents first for eligible write-capable tasks.
`subagents=auto` is conservative and remains local unless the user explicitly
requests delegation/parallel agent work. `subagents=off` is always local-only.

When current Superpowers skills are installed, interactive implementation first
runs `scripts/audit_superpowers_compatibility.py`. If it recommends
`thin_stateful_bridge`, use the Superpowers-native implementation loop for the
approved plan and keep CPE as the state, worktree, task-packet, validation, and
audit bridge. If the audit fails, keep the existing CPE execution cycle or stop
when the requested route depends on missing Superpowers contracts.

## headless

Use the same worktree and orchestrator layout as interactive mode. A headless
target must bootstrap required skills in its prompt, must not launch another
nested `codex exec`, and must write the structured headless result described by
`templates/headless-output-schema.json`.

Headless remains CPE-owned because it must produce CPE state, context snapshots,
and structured result artifacts from a fresh process.

When `CODEX_EVAL_HOME` is present, the current `codex exec --cd` repository is
the isolated execution workspace. Do not run `git worktree add` or write git
refs in that eval runtime; record the logical worktree path in state and write
orchestrator artifacts under `$CODEX_EVAL_HOME/.codex/orchestrator/<run_id>`.

## prompt

Export a fresh-session prompt only. Do not create worktrees, state, context
snapshots, hooks, logs, or task artifacts.

Prompt mode remains CPE-owned and does not run the Superpowers compatibility
audit unless a caller explicitly asks for route diagnostics.

## handoff

Export a continuation prompt only. The prompt must include `HANDOFF CHECKPOINT`
and enough state path information for a future session to resume from
`~/.codex/orchestrator/<run_id>/state.json`.

Handoff mode remains CPE-owned because it is an export and recovery artifact,
not an implementation loop.

## resume

`resume=latest` scans `~/.codex/orchestrator/*/state.json`. If more than one
active candidate exists, stop and ask which run to resume.

Resume remains CPE-owned because state discovery and ambiguity handling depend
on CPE orchestrator artifacts.
