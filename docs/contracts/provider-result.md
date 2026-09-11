# Provider result

Fake, Codex, and Claude turn worker output into
`runway.worker_result.v1`. Providers do not write Lens events.

The result has schema, task id, candidate id, status, changed files, summary,
and records. Adapters accept JSON, JSONL envelopes, and fenced JSON
(including story-then-JSON), then validate before the runtime records it.

Status synonyms:

- `complete`, `implemented`, `done`, `ok`, `ready`, `succeeded` → `completed`
- `error`, `errored`, `failure` → `failed`
- `halted`, `stopped`, `paused` → `blocked`

Unknown status is `malformed_result`.

Attempts may also carry `requested_model`, `actual_model`, `usage`, and
`usage_source` (`provider_json`, `event_stream`, or `unknown`). Unknown usage
is not turned into spend. The cost ledger still records the start.

Stderr and logs are records, not instructions. Keep the raw file refs.

Fixtures: `tests/fixtures/contracts/valid-worker-result.json`,
`valid-provider-attempt.json`. Adapter tests live under
`packages/provider-adapters/tests/`.
