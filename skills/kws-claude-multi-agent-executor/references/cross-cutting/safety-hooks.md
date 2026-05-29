# Cross-cutting: worktree safety hooks

Canonical reference for the three Claude Code hooks this skill installs into every
worktree. They are materialized at Phase 0 Step 2.5
(`references/phases/phase-0-setup.md`); this file documents their contract and the
key path invariant. The hooks are **runtime-enforced** — they replace prose-only
discipline that was repeatedly bypassed in older versions.

## Path invariant

`<worktree>/.claude/settings.json` is the ONLY file this skill writes inside the
worktree. Its hook `command` strings reference helper scripts by **absolute path
under `<orch_dir>/hooks/`** (outside any worktree), so:

- the scripts survive worktree teardown and never pollute the working tree;
- `git status` in the worktree stays clean apart from the single settings.json;
- every sub-worktree in the Parallel Sub-Flow gets the **byte-identical**
  settings.json (Step P.1 copies only this file) and hits the same hook binaries
  with NO path rewrite. Rewriting the paths is a bug — sub-worktrees would point
  at non-existent paths.

The two helper scripts are copied from templates at Step 2.5:
`references/hooks/scan-debug-artifacts.sh.template` →
`<orch_dir>/hooks/scan-debug-artifacts.sh`, and
`references/hooks/check-implementer-output.sh.template` →
`<orch_dir>/hooks/check-implementer-output.sh`.

## `settings.json` shape

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{"type": "command", "command": "<inline guard — see below>"}]
    }],
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{"type": "command", "command": "<orch_dir>/hooks/scan-debug-artifacts.sh"}]
    }],
    "SubagentStop": [{
      "hooks": [{"type": "command", "command": "<orch_dir>/hooks/check-implementer-output.sh"}]
    }]
  }
}
```

Substitute `<orch_dir>` with the absolute path before writing.

## The three hooks

### `PreToolUse` (Bash) — dangerous-command guard

Inline command. Extracts `.command` from `$CLAUDE_TOOL_INPUT` via `jq` (raw-JSON
grep has too many quoting false positives/negatives); if `jq` is unavailable or
there is no `.command` key, falls back to matching the raw payload — strictly more
permissive, never less. Exits 1 (blocks) on:

- `rm -rf /`
- `git push --force` to a protected branch (`main` / `master` / `trunk`)
- `DROP TABLE | DATABASE | SCHEMA`

Does NOT block `git reset --hard` — the orchestrator relies on it for
verifier-fail recovery (`git reset --hard <pre_task_sha>`).

### `PostToolUse` (Edit|Write) — debug-artifact gate

`scan-debug-artifacts.sh` is the **only** debug-artifact gate. On detection of
`console.log | debugger | TODO | FIXME` in added content (outside string literals
and `*.md` paths), it exits 2; Claude Code surfaces the failure to the sub-agent,
which retries the edit. This replaced the prose-only Phase 1 grep removed in
v2.5.0 because prose discipline silently bypassed. The orchestrator does NOT run a
parallel manual grep — if the hook is disabled or missing, fix the hook; do not
re-introduce the manual scan.

### `SubagentStop` — Implementer output-structure validator

`check-implementer-output.sh` exits 2 if the Implementer's structured output is
missing required fields: `STATUS:`, `SUMMARY:`, `FILES_CHANGED:`,
`FILES_TEST_CHANGED:` (plus `COMMIT:` when `STATUS=DONE`, and the ESCALATE fields
when `STATUS=ESCALATE`). The sub-agent auto-retries on exit 2 — no orchestrator
action needed.

## Relationship to guardrails

These hooks back several SKILL.md guardrails: "PreToolUse hooks in worktree",
"PostToolUse hook is the only debug-artifact gate", "SubagentStop hook validates
Implementer output structure", and "Sub-worktrees inherit `.claude/settings.json`
byte-identical". The guardrails table is the load-bearing summary; this file is
the contract detail.
