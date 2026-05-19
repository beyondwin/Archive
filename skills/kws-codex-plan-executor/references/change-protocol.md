# Change Protocol

Before editing this skill:

1. Update or add deterministic eval coverage for the behavior change.
2. Update `SKILL.md`, prompt templates, references, and docs together.
3. Run the deterministic eval suite.
4. Run `python3 -m py_compile scripts/*.py evals/*.py`.
5. Run `bash -n evals/run.sh`.

When changing runtime layout, check for stale references with:

```bash
rg 'orchestrator|worktrees|subagents' SKILL.md references templates evals docs
```
