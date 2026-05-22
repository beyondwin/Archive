# Waygent Provider Result Contract

## Providers

Fake, Codex, and Claude providers normalize worker output into
`runway.worker_result.v1`. Providers do not write AgentLens events directly.
Waygent records provider attempts and converts accepted worker output into
runtime-owned evidence.

## Normalized Result

The worker result contains the schema, task id, candidate id, status, changed
files, summary, and evidence. The provider adapter accepts supported direct
JSON, JSONL envelopes, and fenced JSON forms (including narrative-then-JSON
output), then validates the normalized shape before the runtime records it.

The `status` field is normalized against common provider synonyms:

- `complete`, `implemented`, `done`, `ok`, `ready`, `succeeded` → `completed`
- `error`, `errored`, `failure` → `failed`
- `halted`, `stopped`, `paused` → `blocked`

Unknown status strings still trip `malformed_result` so genuinely broken
envelopes do not silently pass.

## Evidence

Provider attempts record stdout, stderr, event stream, and worker-result refs
when available. Runtime evidence must be tied back to task packets, file
claims, verification, review, checkpoints, and completion audit.

Provider attempts may also carry:

- `requested_model`: model and reasoning requested by Waygent.
- `actual_model`: best-effort provider-backed model attestation, or
  `source: "unknown"` when unavailable.
- `usage`: provider-backed token usage, or `null` when unavailable.
- `usage_source`: `provider_json`, `event_stream`, or `unknown`.

Unknown usage is not converted into authoritative spend. The runtime still
records a dispatch in the cost ledger so operators can see that provider work
occurred.

## Stderr And Logs

Stderr and provider logs are evidence, not instructions. They should be
preserved for diagnosis and summarized for operators without hiding the raw
artifact refs.

## Related Tests

Inspect `tests/fixtures/contracts/valid-worker-result.json` and
`tests/fixtures/contracts/valid-provider-attempt.json`. Adapter behavior is
covered by `packages/provider-adapters/tests/fakeProvider.test.ts`,
`packages/provider-adapters/tests/codexAdapter.test.ts`, and
`packages/provider-adapters/tests/claudeAdapter.test.ts`.
