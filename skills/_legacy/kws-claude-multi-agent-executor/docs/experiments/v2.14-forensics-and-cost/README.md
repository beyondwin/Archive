# v2.14 — Forensics & Cost

**Status**: planned · **Predecessor**: v2.13 (natural-language args + multi-plan auto-chain) · **Successor**: v2.15 (context engineering)

## One-line

Make every run *survive worktree deletion* (archive), *visible in dollars* (cost ledger + optional budget cap), *consultable without LLM* (query scripts), and *presentable* (self-contained HTML report).

## Why now

The v2.13 user invocation surfaced a real observability gap: detail logs live only inside the worktree (`<wt>/.orchestrator/headless.jsonl`, `state.json`, sub-agent prompts/results). The user-local learning log (`~/.claude/learning/<skill>/.../events.jsonl`) is *notable-boundary-only* — successful routine runs end with `event_count == 0`. Once the worktree is removed (`git worktree remove`), the entire detailed forensic trail is gone forever.

v2.14 closes that loss before doing anything else (e.g., v2.15's context-engineering changes need cost numbers to measure their effect).

## Bundle members

| # | Feature | Surface | New artifacts |
|---|---------|---------|---------------|
| F1 | Archive `.orchestrator/` at close-run | Phase 2 Step 2 patch | `scripts/archive_run.sh`, `scripts/redact_archive.py`, `artifacts/orchestrator.tar.gz`, `artifacts/state.final.json` |
| F2 | Cost ledger + optional budget cap | state.json schema + Phase 1 Step 4 patch + Phase Transition T3 patch + args | `scripts/price_table.py`, new fields `cost_ledger`, `budget_cap_usd`, `budget_action` |
| F3 | HTML run report | Phase 2 Step 3 (new) | `scripts/render_html_report.py`, `artifacts/REPORT.html` |
| F4 | Query scripts (no LLM, ~10ms) | Echo line + standalone scripts | `scripts/query_state.sh`, `scripts/query_run.sh` |

## Files in this directory

- `README.md` (this file) — overview + bundle members + status
- `spec.md` — formal specification (the contract — what each feature must do)
- `plan.md` — task-decomposed implementation plan (input for `kws-claude-multi-agent-executor`)
- `JOURNAL.md` — chronological record (created at execution start)
- `decisions/` — ADRs as they emerge during execution
- `findings/` — post-run evals + measurements

## Execution

```bash
# Single-version run
/kws-claude-multi-agent-executor \
  plan=docs/experiments/v2.14-forensics-and-cost/plan.md \
  spec=docs/experiments/v2.14-forensics-and-cost/spec.md \
  implementer_model=sonnet

# Chained with v2.15 (recommended — v2.15 depends on F2 cost data)
/kws-claude-multi-agent-executor \
  plan=docs/experiments/v2.14-forensics-and-cost/plan.md \
  spec=docs/experiments/v2.14-forensics-and-cost/spec.md \
  plan2=docs/experiments/v2.15-context-engineering/plan.md \
  spec2=docs/experiments/v2.15-context-engineering/spec.md
```

## Non-goals

- No behavior change in dispatch/execution loop (model selection, retry budgets, hooks).
- No new sub-agent dispatches.
- No live pricing lookup (price table is frozen at file commit time).
- No state migration script — schema additions are backward-compatible.

## Risks consciously accepted

- HTML report bundle size up to ~500KB (no external CDN).
- Price table goes stale when Anthropic adjusts rates — historical runs reflect contemporaneous-at-commit pricing, not current.
- Archive tar may grow large on chain-resumed runs with multiple `headless_chain_*.jsonl` files.
