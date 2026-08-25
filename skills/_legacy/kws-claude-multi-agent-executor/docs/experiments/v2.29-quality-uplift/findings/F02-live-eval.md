# F02 — Live fixture eval (adoption gate)

**Date**: 2026-06-07
**Decision**: PASS — v2.29.0 prose changes confirmed safe in a live run.

The fixture-eval gate recommended in [F01](./F01-close-out.md) (run before relying
on the new orchestrator prose I1/I6/I8/I9/I11 in a live run) was executed:
`./evals/run.sh` over all 8 fixtures, each a real headless
`claude -p /kws-claude-multi-agent-executor` dispatch + judge pass.

## Results — `evals/baselines/v2.29.0.json`

| fixture | mean | passed | exercises |
|---------|------|--------|-----------|
| 01-trivial-typo | 0.96 | ✅ | SMALL bucket |
| 02-three-file-refactor | 0.90 | ✅ | MEDIUM rename |
| 03-add-new-feature | 0.90 | ✅ | HIGH-risk task → I9 forced-verify path |
| 04-cross-plan-handoff | 0.90 | ✅ | plan_chain |
| 05-ambiguous-spec | 1.00 | ✅ | must-refuse halt (contract mismatch) |
| 06-flaky-test-recovery | 0.90 | ✅ | retry / recovery → I1 region |
| 07-low-batch-heavy | 0.90 | ✅ | LOW batch + compaction → I11 |
| 08-subtle-input-validation | 0.94 | ✅ | MID edge-case suite |

**8/8 PASS, mean 0.925.** Deterministic preflight (compare_agentlens
`--self-test`, check_skill_contract, check_doc_freshness) green. The fixtures
that most directly stress the v2.29 prose changes — 03 (HIGH-risk forced
Verifier), 05 (deliberate spec-refuse halt), 06 (retry/recovery), 07 (LOW batch
+ compaction discipline) — all passed.

## Harness fix landed alongside

The baseline first carried a duplicate `01-trivial-typo` entry (9 rows for 8
fixtures). Root cause: `run.sh`'s judge-JSON extractor (`sed -n '/^{/,/^}$/p'`)
prints *every* top-level `{...}` block, so when the judge emitted a draft +
final verdict both were appended. Not a double-run (the run log shows fixture 01
dispatched once). Fix: slurp the extracted blocks and keep only the last object
(`jq -sc 'map(select(type=="object")) | if length>0 then .[-1] else {} end'`).
The committed baseline was re-aggregated to match (`group_by(.fixture) |
map(.[-1])`), giving the canonical 8 rows. Pre-existing harness fragility, not a
v2.29 regression.

## Disposition

The last open item in F01 ("recommend a fixture-eval pass before relying on the
new prose") is now closed: the live gate is green.
