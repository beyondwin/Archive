# Cross-cutting: worktree safety hooks

Canonical reference for the four Claude Code hooks this skill installs into every
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

The helper scripts are copied from templates at Step 2.5:
`references/hooks/scan-debug-artifacts.sh.template` →
`<orch_dir>/hooks/scan-debug-artifacts.sh`,
`references/hooks/check-implementer-output.sh.template` →
`<orch_dir>/hooks/check-implementer-output.sh`, and
`references/hooks/finalization-stop-gate.sh.template` →
`<orch_dir>/hooks/finalization-stop-gate.sh` (v2.26).

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
    }],
    "Stop": [{
      "hooks": [{"type": "command", "command": "<orch_dir>/hooks/finalization-stop-gate.sh <orch_dir>/state.json <skill_dir>/scripts"}]
    }]
  }
}
```

Substitute `<orch_dir>` and `<skill_dir>` with absolute paths before writing. The
`Stop` hook is the only one that takes positional args — it lives outside the
worktree and cannot derive `state.json` / `scripts/` locations on its own.

As of v2.27 this file is **not hand-written** — Phase 0 Step 2.5 runs
`scripts/materialize_worktree_hooks.py`, which deep-merges the four events into any
pre-existing repo settings.json (preserving `permissions`/`$schema`/other hook
events) and self-asserts the Stop gate. `--check` re-runs the assertion without
writing and is reused as the Phase-1 Task-1 preflight. The shape above is exactly
what the script emits, so this remains the single source of truth for the shape.
The sub-worktree byte-identical copy (Parallel Sub-Flow P.1) is unchanged — it
copies the already-materialized file.

Also as of v2.27 (D003), the wired-ness of the result is re-asserted at **finalize
time**: `finalize_run.py` reuses `materialize_worktree_hooks.check_problems` against
`<worktree>/.claude/settings.json` and raises a blocking `hooks_not_wired` FAIL when
the file is present+parseable but missing the four hooks / Stop gate (suppressed by
`hooks_wiring_waived`). It **skips silently** when the worktree key is absent or the
settings file is missing/unparseable, so replays and cleaned worktrees never
false-positive. This is the backstop for a run that skipped Step 2.5 entirely (and
therefore wired no Stop gate at all): the Step 2.5 write and the Phase-1 `--check`
preflight are both prose, so the finalize check — riding the distinct Phase 2 Step 2
`finalize_run.py --fix` site — is the cheapest in-band catch for that bootstrap gap.

## The four hooks

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

### `Stop` — finalization forcing function (v2.26)

`finalization-stop-gate.sh <state.json> <scripts_dir>` fires when the **session**
tries to stop. It resolves the two remaining risks of the Phase-2-only finalization
gates (D001): a run that never enters Phase 2 (the `source-matching` failure) and
attached-mode schema improvisation that Phase 2 Step 1.5 would otherwise never see.

- **Cheap short-circuit.** A single `jq` pass over the active tree. While any task
  is still non-terminal (not COMPLETE/SKIPPED), exit 0 immediately — the
  orchestrator legitimately pauses between turns. Per-turn cost during a run is
  negligible.
- **End-signal gate.** Only once **every** task is terminal AND a real end-signal
  fired (run-level `status: COMPLETE`, or `current_task` cleared with a recorded
  `last_completed_task`, or — v2.28 (D002) — simply **every declared task
  terminal** at Stop time) does it run the full validators. The all-terminal
  trigger is structural: the Stop hook fires only when the session is genuinely
  ending, so an all-terminal run that reaches Stop unfinalized means Phase 2 was
  skipped (a run about to finalize sets `status: COMPLETE`, caught by the first
  condition — no false positive). The `TOTAL > 0` guard preserves the fresh-run
  exemption: a fresh run has no tasks and is allowed to stop.
- **Full gates.** Runs `finalize_run.py --check` and `validate_state_schema.py`. If
  either reports a blocking problem, exit 2 with corrective guidance on stderr so
  Claude Code surfaces it and the orchestrator completes Phase 2 before stopping.
- **Fail-open vs fail-closed.** Missing args/tools/state, or a validator that
  itself exits 2 (broken), → exit 0 (never trap a session on a broken hook). A
  detected inconsistency → exit 2 (block the stop).

Advisory-blocking like the rest of the suite: a determined operator can disable it.
It is enforcement, not a hard lock.

## Relationship to guardrails

These hooks back several SKILL.md guardrails: "PreToolUse hooks in worktree",
"PostToolUse hook is the only debug-artifact gate", "SubagentStop hook validates
Implementer output structure", "Stop hook forces finalization (v2.26)", and
"Sub-worktrees inherit `.claude/settings.json` byte-identical". The guardrails
table is the load-bearing summary; this file is the contract detail.
