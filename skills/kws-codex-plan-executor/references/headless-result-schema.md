# Headless Result Schema

Public `run` and `resume` emit exactly one JSON object to stdout. Expected
runtime failures use the same shape and never require parsing stderr or a
traceback.

The common fields are `status`, `run_id`, `state_path`, `summary`,
`changed_files`, `verification`, `open_gaps`, `residual_risk`,
`context_artifacts`, and `next_action`.

- `success` exits 0 and requires non-null `run_id` and `state_path`. CPE calls
  canonical `validate_completion` immediately before returning it.
- `blocked` exits 1 and requires `blocker` with category, summary,
  recoverability, next action, and evidence references.
- `failed` exits 2 and requires `failure_decision` with the same failure
  metadata and a machine decision.

The only public failure categories are `preflight`, `environment`,
`transient`, `implementation`, `review`, `verification`, `policy_violation`,
`state_integrity`, and `operator_review`.

The machine-readable contract is
`templates/headless-output-schema.json`; `scripts/cpe_runtime/public_result.py`
is its serializer and exit-code owner.
