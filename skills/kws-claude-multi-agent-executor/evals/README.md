# kws-claude-multi-agent-executor — Evaluation Suite (P6)

Regression harness for the orchestrator skill. Anthropic guidance: small fixture sets (5–8) are sufficient to spot meaningful regressions; the cost of running 20+ fixtures dominates the cost of building them.

## Layout

```
evals/
├── fixtures/                    # one YAML per scenario
│   ├── 01-trivial-typo.yaml
│   ├── 02-three-file-refactor.yaml
│   ├── 03-add-new-feature.yaml
│   ├── 04-cross-plan-handoff.yaml
│   ├── 05-ambiguous-spec.yaml
│   ├── 06-flaky-test-recovery.yaml
│   └── 07-low-batch-heavy.yaml
├── judge.md                     # LLM-as-judge prompt template (Sonnet)
├── run.sh                       # run + score harness (bash + jq)
└── baselines/                   # one JSON per version
    ├── v2.4.0.json              # baseline taken before v2.5 changes
    └── ...
```

## Running

```bash
# Full run, all fixtures, write to baselines/v<current>.json
./evals/run.sh

# Single fixture
./evals/run.sh fixtures/01-trivial-typo.yaml

# Compare against an earlier baseline
diff <(jq -S . baselines/v2.4.0.json) <(jq -S . baselines/v2.5.0.json)
```

The harness creates a temp dir per fixture, runs `git init`, applies the fixture's `bootstrap` commands, then invokes the skill via `claude -p` headless. Captures wall-time, token usage (from `stream-json`), task statuses, commit count, test results, then runs `judge.md` against the captured run.

## Fixture format

Each `.yaml` describes:

- `name` — short identifier
- `description` — what behavior the fixture exercises
- `bootstrap` — shell commands run inside the temp git repo before the skill starts
- `plan` — multi-line plan markdown (written to `plan.md`)
- `spec` — multi-line spec markdown (written to `spec.md`)
- `invocation` — args passed to the skill
- `expected` — ground-truth checks the judge uses (commit count, files modified, tests pass, etc.)
- `cost_budget` — token/wall-time ceiling beyond which the run scores 0 on cost-efficiency

## Judge

`judge.md` is a single-call LLM-as-judge prompt. Scores 4 axes 0.0–1.0:

- `correctness` — does the outcome match `expected`?
- `spec_compliance` — did the implementation follow the spec?
- `code_quality` — clarity, conventions, no dead code (judge reads diff)
- `cost_efficiency` — wall-time + tokens vs. `cost_budget`

Mean of axes = fixture score. Per-fixture pass threshold: 0.6.

Regression rule: if any fixture's score drops > 0.1 between versions, flag and block release.

## Caveats

- **Eval cost ~$5–15 per full run** on Sonnet pricing. Don't run on every commit. Run on version bumps and major refactors.
- **Fixtures are not deterministic** — Sonnet sampling introduces variance. The judge is calibrated to be tolerant; small score wobble (±0.05) is noise.
- **Bootstrap repos are throwaway** — fixtures DO NOT depend on real codebases. Each fixture is self-contained.
