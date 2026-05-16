# Unit Context Manifest

The unit context manifest is a compact per-task contract. It records the task
type, required skills, context size, allowed tool class, and write policy before
execution begins.

Example:

```json
{
  "unit_manifest": {
    "unit_type": "execute-task",
    "context_mode": "focused",
    "required_skills": ["using-superpowers", "test-driven-development"],
    "tool_policy": "implementation",
    "allowed_write_globs": ["scripts/*.py", "evals/*.py", "references/*.md"],
    "forbidden_write_globs": [".git/**", "graphify-out/**"],
    "artifact_policy": "inline-summary",
    "max_context_chars": 60000
  }
}
```

## Enums

`unit_type`:

- `research`
- `plan`
- `execute-task`
- `reactive-execute`
- `validate`
- `complete`
- `docs`
- `review`
- `handoff`

`context_mode`:

- `minimal`
- `focused`
- `expanded`
- `full`

`tool_policy`:

- `read-only`
- `planning`
- `implementation`
- `docs`
- `verification`

`artifact_policy`:

- `inline`
- `inline-summary`
- `excerpt`
- `on-demand`

## Policy Meaning

| Policy | Reads | Writes | Commands |
| --- | --- | --- | --- |
| `read-only` | allowed | none | non-mutating inspection commands |
| `planning` | allowed | plan/docs only | inspection and validation commands |
| `implementation` | allowed | declared task files only | implementation and verification commands |
| `docs` | allowed | docs/reference globs only | docs validation commands |
| `verification` | allowed | run artifacts only | tests, builds, linters, validators |

Codex skills cannot intercept every low-level file write through a custom hook.
The manifest is enforced by contract, state validation, and post-diff checks
rather than a true runtime write gate.

## Write Scope

`allowed_write_globs` is the narrowest write scope that can complete the unit.
It should agree with the task contract's `allowed_edits`. For implementation
tasks, an empty `allowed_write_globs` value is invalid.

`forbidden_write_globs` always wins over allowed globs. Use it for generated
navigation layers, `.git/**`, run-external state, and other files that must not
be touched by the unit.

Use `scripts/check_run_diffs.py` after implementation and before task
completion to compare the git diff against both the task contract and
`unit_manifest`. The checker treats `contract.allowed_edits` and
`unit_manifest.allowed_write_globs` as allowed patterns, and
`contract.forbidden_edits` plus `unit_manifest.forbidden_write_globs` as
forbidden patterns. Forbidden patterns win.
