# Waygent Provider Result Contract

## Providers

Fake, Codex, and Claude providers normalize worker output into
`runway.worker_result.v1`. Providers do not write AgentLens events directly.
Waygent records provider attempts and converts accepted worker output into
runtime-owned evidence.

## Normalized Result

The worker result contains the schema, task id, candidate id, status, changed
files, summary, and evidence. The provider adapter accepts supported direct
JSON, JSONL envelopes, and fenced JSON forms, then validates the normalized
shape before the runtime records it.

## Evidence

Provider attempts record stdout, stderr, event stream, and worker-result refs
when available. Runtime evidence must be tied back to task packets, file
claims, verification, review, checkpoints, and completion audit.

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
