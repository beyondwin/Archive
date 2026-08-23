# Korean Writing Editor Live Evaluation

## Purpose And Evidence Boundary

This optional operator procedure compares the installed Korean Writing Editor
against its tracked source using only synthetic cases in `live_cases.json`.
It is not a product-quality score and does not replace the offline contract.
The approved baseline is 119 producer calls plus 3 independent review calls:
122 calls at most.

Only an operator with explicit authorization may start a paid baseline. An
`--execute` run may be billable. Do not treat a dry run, preflight, or fixture
pass as evidence that a provider was invoked or that model quality was proven.
The 122-call baseline and 38-call remediation reserve define one approved
evaluation cycle boundary. The runner cannot prevent an operator from starting
multiple separately authorized cycles; do not represent those cycles as one
approved 160-call result.

## Safety And Privacy

Use synthetic prompts only. Do not place private manuscripts, credentials, or
full provider transcripts in `live_cases.json`, receipts intended for review,
or reports. Evidence stays in the ignored exact root
`.superpowers/kws-korean-writing-editor/live`; the evaluator rejects another
evidence root.

Reports use hashes and minimal redacted excerpts for review. Keep raw response
files inside the ignored run directory, and do not copy them into an issue,
commit, or dated operations report.

## Offline Validation

Run the deterministic evaluator before requesting or using live authorization:

```bash
python3 skills/kws-korean-writing-editor/evals/run.py --scope full
```

Its 30 fixtures prove only the offline oracle contract. They make no live
invocation or model-quality claim.

## Dry Run

This command is provider-free: it only prints the approved call plan and
budget.

```bash
python3 skills/kws-korean-writing-editor/evals/live_matrix.py --dry-run
```

Expected baseline accounting is 119 producer calls, 3 reviewer calls, and 122
baseline calls. The dry-run payload also reports 38 remediation calls and the
global ceiling shown as `approved_total_ceiling` is 160.

## Baseline Preflight

Before execution, ensure the source and installed skill manifests are equal,
the checkout is clean, and the chosen lowercase hyphenated run ID has not been
used. Preflight writes the immutable run identity to the ignored evidence root
and performs no provider inference.

```bash
RUN_ID="2026-08-23-korean-editor-baseline"
python3 skills/kws-korean-writing-editor/evals/live_matrix.py \
  --preflight --scope baseline --run-id "$RUN_ID" --jobs 3 --max-calls 122 \
  --evidence-root .superpowers/kws-korean-writing-editor/live \
  --report docs/operations/2026-08-23-kws-korean-writing-editor-cross-model-evaluation.md
```

`--jobs` accepts 1 through 4; the approved example uses 3. The report path
must be the dated filename under `docs/operations` shown above.

The `2026-08-23` run ID and report filename are the approved artifact date,
intentionally retained across the wall-date rollover. Do not replace them with
the wall-clock date when following this approved plan.

## Paid Baseline

After explicit authorization, execute the same preflighted identity. This is
the operation that may be billable.

```bash
RUN_ID="2026-08-23-korean-editor-baseline"
python3 skills/kws-korean-writing-editor/evals/live_matrix.py \
  --execute --scope baseline --run-id "$RUN_ID" --jobs 3 --max-calls 122 \
  --evidence-root .superpowers/kws-korean-writing-editor/live \
  --report docs/operations/2026-08-23-kws-korean-writing-editor-cross-model-evaluation.md
```

Do not raise the baseline above 122. The 38-call reserve is for separately
authorized remediation, and the baseline plus remediation total must never
exceed the 160-call ceiling.

## Resume

Use `--resume` only with `--execute` after an interrupted run, with the same
run ID and scope. Resume validates the complete run identity: runner version,
repository HEAD, source and installed skill hashes, `live_cases.json` hash,
producer identities, requested-model identities, and scope. Any mismatch needs
a new run ID.

When the matching preflight exists but the report target is absent and no
report-state exists, resume may dispatch and make the first publication with
exclusive creation at completion. A report target without state, state without
its exact report, an unsafe target or symlink, identity or hash drift, or any
extra checkout dirt fails before dispatch. Exact matching report and state use
the atomic update path.

```bash
RUN_ID="2026-08-23-korean-editor-baseline"
python3 skills/kws-korean-writing-editor/evals/live_matrix.py \
  --execute --resume --scope baseline --run-id "$RUN_ID" --jobs 3 --max-calls 122 \
  --evidence-root .superpowers/kws-korean-writing-editor/live \
  --report docs/operations/2026-08-23-kws-korean-writing-editor-cross-model-evaluation.md
```

Completed `verified`, `partially_verified`, `failed`, and `not_measured`
receipts are retained; a `blocked` call can be attempted again within the
approved budget.

## Review Packet

The baseline reserves 3 reviewer calls after the 119 producer calls. Review
packets contain bounded synthetic candidates and record review findings, not a
full transcript. The dated operations report records hashes, minimal excerpts,
receipt status, verification facts, and local-versus-remote facts. Inspect the
packet and report as evidence, not as an automatic release decision.

## Status Meanings

The dated report uses five executed-evidence labels:

- `verified`: the returned body met the deterministic case checks.
- `partially_verified`: body checks passed but the case cannot observe skill activation.
- `blocked`: dispatch or response processing could not produce usable evidence.
- `failed`: a returned body violated one or more case checks.
- `not_measured`: no usable body was measured for the planned evidence item.

Status is never averaged into a quality score. Failure takes precedence when a
producer and control band are summarized.

## Remediation Budget

Baseline authorization is 122 calls maximum. Keep 38 calls in reserve for a
separately authorized `--scope remediation` run; all attempts across the
baseline and remediation must stay at or below 160. Do not spend the reserve
to repeat a successful baseline merely for a larger sample.

The remediation CLI defaults to 38 and rejects a higher value. It is a
separate explicitly authorized run, not an automatic extension of a baseline.
Preflight the remediation identity before its separately authorized execution.

```bash
RUN_ID="2026-08-23-korean-editor-remediation"
python3 skills/kws-korean-writing-editor/evals/live_matrix.py \
  --preflight --scope remediation --run-id "$RUN_ID" --jobs 3 --max-calls 38 \
  --evidence-root .superpowers/kws-korean-writing-editor/live
```

```bash
RUN_ID="2026-08-23-korean-editor-remediation"
python3 skills/kws-korean-writing-editor/evals/live_matrix.py \
  --execute --scope remediation --run-id "$RUN_ID" --jobs 3 --max-calls 38 \
  --evidence-root .superpowers/kws-korean-writing-editor/live
```

## Evidence Layout

For a run ID, the ignored evidence root contains the preflight receipt,
`receipts/`, `raw/`, and `normalized/` evidence. Receipt metadata binds the
identity and response hashes. Raw and normalized bodies are local operational
evidence, not report attachments. The optional dated report is written only to
`docs/operations/YYYY-MM-DD-kws-korean-writing-editor-cross-model-evaluation.md`.

## Limitations

An explicit host invocation and a compliant returned body do not prove that
the host activated the skill internally. Cases whose activation is not
observable are intentionally `partially_verified`; do not infer hidden routing
or activation from a self-report. Offline fixtures and synthetic live evidence
also cannot establish general writing quality or authorship.
