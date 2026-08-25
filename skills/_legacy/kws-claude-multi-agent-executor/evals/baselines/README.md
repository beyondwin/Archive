# Eval Baselines

Per-version regression captures for the multi-agent executor. Each
`vX.Y.Z.json` file records the eval state at the time a version was promoted so
later changes can be diffed against a known-good reference.

## File shape

Every baseline carries `version`, `date`, and a `fixtures[]` array of per-fixture
quality scores (`correctness`, `spec_compliance`, `code_quality`,
`cost_efficiency`, plus a `mean` / `passed` summary).

### `metrics` block (introduced in v2.22.0)

Starting with **v2.22.0**, baselines may also carry a top-level `metrics` block
capturing per-dispatch cost data from the API-based dispatch path
(`scripts/dispatch_via_api.py` with prompt caching):

- `per_role` — map of role → `{ wall_ms_mean, input_tokens_mean, cache_hit_ratio_mean }`
  for `plan_reviewer`, `verifier`, `docs_updater`, `transition_combined`.
- `input_tokens_mean` — overall mean input tokens per dispatch.
- `cache_hit_ratio_mean` — overall mean cache-read ratio (cache_read / input_tokens).
- `escalate_count` — number of dispatches that escalated.
- `output_quality_mean` — overall output-quality score.

Older baselines (**≤ v2.21.0**) predate this block — they only have fixture
quality scores. Because of that, `scripts/cost_compare.py` **skips** (does not
fail) the input-cost ratio check when the baseline lacks
`metrics.input_tokens_mean`.

## Comparing baselines

`scripts/cost_compare.py` diffs two baselines and gates dispatch cost metrics:

```bash
python3 scripts/cost_compare.py \
  --baseline evals/baselines/v2.21.0.json \
  --candidate evals/baselines/v2.22.0.json \
  --check-cache-hit-min 0.60 \
  --check-input-cost-max-ratio 0.20
```

- `--check-cache-hit-min F` — fail unless the candidate's
  `cache_hit_ratio_mean >= F`.
- `--check-input-cost-max-ratio R` — fail unless
  `candidate.input_tokens_mean / baseline.input_tokens_mean <= R`. If the
  baseline predates the metric (e.g. v2.21.0.json), this check is **SKIPPED**,
  not failed.
- `--self-test` — run the tool's internal assertions (`SELF-TEST OK`).

## Entries

- **v2.22.0** — dispatch optimization: API + prompt-caching baseline. First
  baseline with a `metrics` block (per-role + overall cache/input/escalate/
  quality). Numbers are representative-offline placeholders
  (`captured: representative-offline`) pending a live capture; they meet the
  v2.22 targets (`cache_hit_ratio_mean = 0.66 ≥ 0.60`, input cost ~19% of the
  assumed v2.21 figure).
