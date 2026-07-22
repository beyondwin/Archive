# KWS Claude Plan Executor (CLPE)

Version 1.0.0. A thin (~550-line) launcher for approved Superpowers
implementation plans on the `claude` CLI. Ownership boundary (same as CPE): CLPE maintains
one execution environment and verifies submitted facts; the child session's
Superpowers owns plan interpretation, implementation, tests, reviews,
subagents, and commits.

Design spec:
`docs/superpowers/specs/2026-07-22-claude-plan-executor-thin-rewrite-design.md`.
Predecessor (fat v3 orchestrator): `skills/kws-claude-multi-agent-executor/`
(archival to `archive/` pending — see SKILL.md).

## Requirements

- Python 3 standard library, Git, `claude` on PATH
- a clean Git workspace and absolute readable UTF-8 spec/plan paths

## Usage

```bash
python3 scripts/clpe.py run --spec /abs/spec.md --plan /abs/plan.md \
  --workspace /abs/repository
python3 scripts/clpe.py resume --run-id RUN_ID
python3 scripts/clpe.py inspect --run-id RUN_ID
```

`--spec` is repeatable. Exit codes: 0 completed / 1 failed / 2 blocked / 3
resumable. Run state: `~/.claude/clpe/<run-id>/` (`CLPE_HOME` overrides the
prefix); worktree: `~/.claude/worktrees/<run-id>/`, branch `clpe/<run-id>`.

See SKILL.md for the launch contract, fail-closed completion gates, failure
classification, and resume semantics.

## Tracked inventory

```text
AGENTS.md
README.md
SKILL.md
evals/check_cli.py
evals/check_gates.py
evals/check_units.py
evals/fake_claude.py
evals/run.sh
scripts/clpe.py
templates/plan-result.schema.json
```

## Verify

```bash
./evals/run.sh
python3 -m py_compile scripts/clpe.py evals/*.py
bash -n evals/run.sh
```
