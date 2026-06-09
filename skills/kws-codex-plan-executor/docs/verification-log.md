# Verification Log

## 2026-05-19

Scope:

- v2.19 path split: code worktrees under `~/.codex/worktrees/<run_id>`.
- Orchestrator state and runtime artifacts under `~/.codex/orchestrator/<run_id>`.
- v2.20.0 subagent default is `on`; spawning remains task-packet-scoped,
  `subagents=auto` is conservative explicit-request mode, and `subagents=off`
  is local-only.
- v2.21.0 tightens that default to subagent-first execution for eligible
  write-capable tasks and validates task-level `subagent_strategy` records for
  delegated and local-fallback outcomes.
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

## 2026-05-31

Scope:

- Prompt cache boundary audit and optional provider cache observations.
- Graphify freshness audit evidence.
- Deterministic subagent pre-dispatch decisions.
- Contract, state schema, and docs updates for the execution-hardening gates.

Commands:

```bash
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_state_schema.py
python3 evals/check_state_reconciliation.py
python3 evals/check_context_snapshot.py
python3 evals/check_headless_result.py
python3 evals/check_spec_manifest.py
python3 evals/check_task_packet.py
python3 evals/check_local_env_preflight.py
python3 evals/check_invocation_args.py
python3 evals/check_inspect_runs.py
python3 evals/check_decisions_register.py
python3 evals/check_prompt_cache_audit.py
python3 evals/check_cache_observations.py
python3 evals/check_graphify_freshness.py
python3 evals/check_preflight_dispatch.py
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
bash evals/run.sh
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root /Users/kws/.codex/worktrees/2026-05-31-cpe-execution-hardening-20260531-202212 --update-ran --output /tmp/cpe-graphify-audit-final.json
```

Result:

- Deterministic evals: pass.
- Full fixture harness: pass.
- Python compile and shell syntax: pass.
- Graphify update: pass; `graphify-out/GRAPH_REPORT.md` and `graph.json`
  refreshed with `Built from commit: b094e729`.
- Graphify freshness audit: pass with `fresh=true` and no errors.

## 2026-06-10

Scope:

- v2.22.0 operational run quality: explicit delegation intent, deterministic
  delegation policy fallback, local bootstrap suggestions, optional v2.22 state
  validation, recent run-quality inspection, and static fixture state emission.

Commands:

```bash
bash evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/inspect_runs.py --codex-home ~/.codex --all-plans --recent 10 --validate-state --quality-report
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root /Users/kws/.codex/worktrees/v2-22-operational-run-quality-20260610-001259 --update-ran --output /Users/kws/.codex/orchestrator/v2-22-operational-run-quality-20260610-001259/graphify_audit_final.json
git diff --check
```

Result:

- Full deterministic fixture harness: pass; `evals/baselines/v2.22.0.json`
  written with all fixtures passed.
- Python compile and shell syntax: pass.
- Recent run-quality smoke: pass; `summary.total=10`, `finished=9`,
  `non_terminal=1`.
- Graphify update: pass; `graphify-out/GRAPH_REPORT.md` and `graph.json`
  refreshed with `Built from commit: 52645b58`.
- Graphify freshness audit: pass with `fresh=true` and no errors.
- Diff whitespace check: pass.

Follow-up residual risk closure:

- `scripts/check_graphify_freshness.py` now treats a post-update commit that
  changes only tracked `graphify-out/` outputs as source-fresh.
- It also treats a successful `graphify update .` with no output changes as
  fresh when `--update-ran` evidence is supplied.
- This closes the tracked-output loop where committing `GRAPH_REPORT.md` and
  `graph.json` advanced HEAD and made the report appear stale again even
  though no indexed source file changed.
