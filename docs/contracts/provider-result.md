# Provider result

Fake, Codex, and Claude normalize worker output into
`runway.worker_result.v1`. Providers do not write Lens events.

The result has schema, task id, candidate id, status, changed files, summary,
and evidence. Adapters accept JSON, JSONL envelopes, and fenced JSON
(including narrative-then-JSON), then validate before the runtime records it.

Status synonyms:

- `complete`, `implemented`, `done`, `ok`, `ready`, `succeeded` → `completed`
- `error`, `errored`, `failure` → `failed`
- `halted`, `stopped`, `paused` → `blocked`

Unknown status is `malformed_result`.

Attempts may also carry `requested_model`, `actual_model`, `usage`, and
`usage_source` (`provider_json`, `event_stream`, or `unknown`). Unknown usage
is not turned into spend. The cost ledger still records the dispatch.

Stderr and logs are evidence, not instructions. Keep the raw artifact refs.

Fixtures: `tests/fixtures/contracts/valid-worker-result.json`,
`valid-provider-attempt.json`. Adapter tests live under
`packages/provider-adapters/tests/`.
