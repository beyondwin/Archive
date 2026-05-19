# Verification Log

## 2026-05-19

Scope:

- v2.19 path split: code worktrees under `~/.codex/worktrees/<run_id>`.
- Orchestrator state and runtime artifacts under `~/.codex/orchestrator/<run_id>`.
- v2.20.0 subagent default is `on`; spawning remains task-packet-scoped,
  `subagents=auto` is conservative explicit-request mode, and `subagents=off`
  is local-only.
- Retired local replay and learning helper surface removed from active docs,
  scripts, and eval expectations.
- AgentLens outcome mapping, redacted payload refs, non-mutating reconcile
  checks, and eval harness failure propagation were tightened.

Commands:

```bash
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 evals/check_state_reconciliation.py
python3 evals/check_eval_harness.py
python3 evals/check_run_diffs.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
```

Dynamic harness note: `evals/run.sh` copies the skill into the fixture repository
before invoking `codex exec` so fixture agents cannot mutate the source package.

Result:

- Legacy token scan: pass.
- Deterministic evals: pass.
- Python compile, shell syntax, skill quick validation, and diff whitespace
  checks: pass.
- Dynamic prompt/handoff smoke:
  `CODEX_EVAL_TIMEOUT_SECONDS=240 bash evals/run.sh evals/fixtures/01-prompt-only.yaml evals/fixtures/03-continuation.yaml`
  passed both fixtures.
