# Waygent — Claude Host Execution Enhancements

Date: 2026-05-25
Owner: Waygent runtime
Status: Draft

## 1. Background

Waygent runs worker tasks through provider adapters in
`packages/provider-adapters/src/`. The Codex path uses `codex exec --json -`
which streams JSONL events, exposes a stable `result` envelope, and feeds
`process.event_stream` for Lens observability. The Claude path uses
`claude -p --output-format json` which returns a single non-streaming JSON
blob.

The Claude adapter therefore lags the Codex adapter on observability,
caching, role isolation, retry/resume, and capability-manifest honesty.
This spec catalogs the 11 concrete gaps and sequences the fixes into four
phases that each ship independently.

Scope: enhancements to the *host execution path* when Waygent runs Claude
as a provider. Out of scope: Codex-side changes, Claude Code SDK
(in-process) integration, Lens schema additions, and subagent model auto
selection (already owned by `ExecutionProfile`).

## 2. Goals / Non-Goals

### Goals

- Make `claudeCapabilityManifest` reflect actual capabilities.
- Differentiate Claude args by worker role (implement / review / verify).
- Enable Claude stream-json output so `event_stream` is non-null.
- Harden worker_result parsing against fenced / interleaved output.
- Capture model + usage attestation from a single authoritative source.
- Restructure the prompt so prompt caching becomes possible.
- Allow Waygent runs to inject `--settings` and `--mcp-config`.
- Detect and sanitize nested Claude Code host environment variables.
- Plumb `--session-id` / `--resume` into the orchestrator retry path.

### Non-Goals

- Replacing the CLI process adapter with the Claude Code TypeScript SDK.
- Adding new Lens event schemas. Streaming output is preserved as text.
- Changing the `--profile` preset semantics (`max-quality` /
  `balanced` / `cost-saver`).
- Auto-selecting different models per worker role (Profile owns that).
- Touching the Codex adapter except where shared code changes apply.

## 3. Gap Analysis (Claude vs Codex)

| # | Gap | Current Claude | Current Codex |
|---|---|---|---|
| 1 | Output stream | `--output-format json` (single blob) | `--json` (JSONL stream) |
| 2 | Tool / MCP / settings flags | none | n/a (different surface) |
| 3 | Permission mode | hardcoded `acceptEdits` | n/a |
| 4 | Role-aware args | not propagated | n/a |
| 5 | Capability manifest | copies codex (`streaming: true`, `approvals: true`) | accurate |
| 6 | Prompt caching | full prompt rebuilt every call | n/a |
| 7 | Nested host env | parent `CLAUDECODE=1` leaks to child | n/a |
| 8 | Resume on retry | no `--resume` | n/a |
| 9 | Per-role timeout | single 30 min default | single default |
| 10 | Result parsing | brace/fence fallback only | JSONL line parser |
| 11 | Model attestation | `modelUsage` keys[0] heuristic | provider_json from stream |

## 4. Phased Plan

```
Phase 1 (Truth + Role)  ──┐
                          ├─→ Phase 2 (Stream + Parsing)
                          │           │
                          │           └─→ Phase 3 (Caching + Prompt)
                          │                       │
                          └───────────────────────┴─→ Phase 4 (Resume)
```

Each phase ships independently. Phase 2 depends on Phase 1's manifest
split (Phase 1 sets `streaming: false`; Phase 2 flips to `true`). Phase 4
benefits from Phase 2's session_id capture.

## 5. Phase 1 — Truth & Role-aware Foundation

### What

Stop misrepresenting Claude capabilities and propagate `AdapterRequest.role`
into `providerProcessArgs` so review and verify get appropriate permission
and tool isolation. Allow per-role timeout overrides.

### Files touched

- `packages/provider-adapters/src/capabilities.ts`
- `packages/provider-adapters/src/processAdapters.ts`
  (`providerProcessArgs`)
- `packages/provider-adapters/src/types.ts` (`ProviderProcessOptions`)
- `packages/provider-adapters/tests/claudeAdapter.test.ts`

### Behavior change

- `claudeCapabilityManifest` defined independently:
  `{ streaming: false, approvals: false, shell: true, file_edits: true,
  tool_calls: true, supported_modes: ["single-agent", "multi-agent",
  "review", "verify"], result_schema: "runway.worker_result.v1" }`.
- `providerProcessArgs` branches on `request.role` (using
  `ProviderRole = "implement" | "review" | "fix" | "verify_assist"`):
  - `implement` → existing `--permission-mode acceptEdits`.
  - `fix` → same as `implement`.
  - `review` → `--permission-mode plan` +
    `--disallowedTools Edit,Write,MultiEdit`
    (Bash kept for grep / find inspection; plan mode prevents writes).
  - `verify_assist` → `--permission-mode acceptEdits` +
    `--allowedTools Bash,Read,Glob,Grep`.
  - undefined / unknown → implement defaults; append warning to
    `stderr_summary` only for unknown values, not undefined.
- Role wiring note: today `packages/orchestrator/src/taskExecutor.ts`
  only constructs requests with `role: "implement"`. This phase lays the
  adapter-side infrastructure so future review / verify_assist callers
  get correct args without re-touching the adapter.
- `ProviderProcessOptions.timeout_ms_by_role?: Partial<Record<ProviderRole,
  number>>`. Resolution order: role override → `timeout_ms` → default
  (30 min).

### Acceptance

- Object-inequality test between Claude and Codex manifests.
- Snapshot tests of `providerProcessArgs` per role.
- Per-role timeout resolution unit test.
- `bun run waygent:scenarios` green; no behavior change on implement role.

### Release gate

Unit tests + scenarios + `bun run platform:demo` green. Manual Claude run
verifying review/verify args render as expected.

## 6. Phase 2 — Streaming & 견고한 파싱

### What

Switch Claude to stream-json, persist the JSONL into `event_stream`, add a
first-class parsing path for the `result` event, and use `system.init` for
model attestation.

### Files touched

- `packages/provider-adapters/src/claudeAdapter.ts` (default args)
- `packages/provider-adapters/src/processAdapters.ts`
  (`runProviderProcess`, `normalizeProcessOutput`, `parseWorkerOutput`,
  `modelFromEnvelope`, `usageFromEnvelope`)
- `packages/provider-adapters/src/capabilities.ts`
  (flip `streaming` to `true`)
- `packages/provider-adapters/tests/usageExtraction.test.ts`
- new fixture in `packages/provider-adapters/tests/fixtures/`

### Behavior change

- Default Claude args:
  `["-p", "--output-format", "stream-json",
  "--include-partial-messages", "--verbose"]`.
- `runProviderProcess` accumulates stdout into `eventStream` when args
  declare `stream-json` (line-buffered; each non-empty line attempted as
  JSON, raw line stored regardless).
- `parseWorkerOutput` priority:
  1. Last JSONL line with `type: "result"` — extract worker_result from
     its `result` text field (existing unwrap helpers).
  2. Existing fence / balanced-brace fallback.
  3. Otherwise `malformed_result`.
- `modelFromEnvelope` priority:
  1. First `system.init` event `model` field.
  2. Existing `modelUsage` keys[0].
  3. Existing `model` string.
- `usageFromEnvelope` reads final `result.usage` including
  `cache_read_input_tokens` and `cache_creation_input_tokens`.

### Acceptance

- Fixture-driven test: JSONL with `system.init` + assistant messages +
  `result` produces non-null `event_stream`, correct worker_result,
  `actual_model.source === "provider_json"`, non-zero usage fields.
- `claudeCapabilityManifest.streaming === true` (updated lock test).
- `system.init.model` overrides `modelUsage` keys[0] in attestation test.

### Release gate

Unit tests green; one manual Claude run shows `event_stream` populated and
worker_result extracted from the `result` line. Scenarios green.

## 7. Phase 3 — Caching & Prompt 구조화

### What

Split the prompt into a stable per-role system prompt (delivered via
`--append-system-prompt`) and a per-task user prompt (stdin). Expose
`--settings` / `--mcp-config`. Sanitize nested Claude Code host env.

### Files touched

- `packages/provider-adapters/src/processAdapters.ts`
  (`buildProviderPrompt` split, env sanitize in `runProviderProcess`,
  args additions in `providerProcessArgs`)
- `packages/provider-adapters/src/types.ts`
  (`ProviderProcessOptions.settings_path?`, `mcp_config_path?`)
- `apps/cli/src/index.ts` if a flag surface is needed to forward
  settings paths (likely just orchestrator option).

### Behavior change

- New `buildProviderSystemPrompt(role: ProviderRole): string`. Returns a
  byte-stable string per role containing role description and the
  worker_result contract reminder.
- `buildProviderUserPrompt(request)` returns only variable content:
  task_id, candidate_id, task_packet_path, prompt.
- `providerProcessArgs` (Claude branch) injects
  `--append-system-prompt <system-prompt>` and optionally
  `--settings <path>` / `--mcp-config <path>` when options supply them.
- Env sanitize: when spawning the child, if parent env has
  `CLAUDECODE === "1"` or `CLAUDE_CODE_ENTRYPOINT` set, the child env
  drops `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_PROJECT_DIR`.
  Disable with `WAYGENT_KEEP_HOST_ENV=1`.

### Acceptance

- Byte-equality test on `buildProviderSystemPrompt(role)` per role.
- Args snapshot showing `--append-system-prompt` injected and stdin
  payload no longer contains the role / contract reminder block.
- Env dump test confirming the three host env vars are absent in the
  spawned child by default and preserved with `WAYGENT_KEEP_HOST_ENV=1`.
- Pass-through test for `settings_path` / `mcp_config_path`.

### Release gate

Unit tests + scenarios green. Manual two-call run with the same role to
observe `cache_read_input_tokens` transition from 0 to >0 on the second
call, recorded as evidence.

## 8. Phase 4 — Resume & 재시도

### What

Assign deterministic session ids to new candidates so failed runs can
retry via `--resume`, carrying the failure context forward.

### Files touched

- `packages/provider-adapters/src/types.ts`
  (`ProviderProcessOptions.session_id?`, `resume_session_id?`;
   `AdapterRequest` retry-context field)
- `packages/provider-adapters/src/processAdapters.ts`
  (`providerProcessArgs` Claude branch — `--session-id` / `--resume`;
   evidence capture of `session_id`, `resume_session_missing` detection)
- `packages/orchestrator/src/taskExecutor.ts` (retry / revive path —
  read prior attempt evidence, set `resume_session_id` and retry prompt
  prefix)

### Behavior change

- `session_id` default constructed as `${run_id}-${task_id}-${candidate_id}`.
  Adapter passes `--session-id <id>` on first attempt.
- Worker evidence captures `session_id` from `system.init`.
- On retry, orchestrator sets `options.resume_session_id` from prior
  attempt evidence. Adapter then passes `--resume <id>` and omits
  `--session-id` (Claude CLI mutual exclusion).
- Retry user prompt prepends:
  `"Prior attempt failed: <failure_class>. stderr summary:
   <stderr_summary[:300]>. Fix and respond with the same
   runway.worker_result.v1 contract."`
- If stderr matches `/session.*not.*found/i`, evidence sets
  `resume_session_missing: true`; orchestrator downgrades to a fresh
  attempt (new session id) once and only once.

### Acceptance

- First-attempt args snapshot includes `--session-id`.
- Retry args snapshot includes `--resume`, excludes `--session-id`.
- Simulated `session not found` stderr triggers fresh-attempt downgrade.
- Retry prompt prefix shape locked by snapshot.
- `bun run waygent:scenarios` exercises one fail → resume cycle through
  a stubbed adapter.

### Release gate

Unit + scenarios green. Manual end-to-end: induce a worker failure,
observe the orchestrator issuing `--resume` with the prior session id,
followed by a success.

## 9. Cross-cutting

### Error handling

- Unknown `worker.status` strings: existing `normalizeWorkerStatus`
  surface unchanged.
- `--resume` failure paths classified as `adapter_crashed` unless
  stderr matches the `session not found` heuristic above.
- Env sanitize is opt-out, not opt-in; document the escape hatch.
- Role fallback warning surfaces through `stderr_summary` rather than
  failing the worker.

### Testing strategy

- Unit tests live alongside existing
  `packages/provider-adapters/tests/*` files.
- New JSONL fixtures under
  `packages/provider-adapters/tests/fixtures/claude/` for Phase 2.
- Integration coverage continues through `bun run waygent:scenarios`
  and `bun run platform:demo`.
- No new top-level test suites introduced.

## 10. Out of Scope (YAGNI)

- Claude Code SDK (in-process) integration.
- Lens schema additions for cache hit ratio or session graph.
- Automatic per-role model selection.
- Codex adapter parity changes triggered by this work.
- Plan-author DSL changes (no new `verify_isolation`-style fields).

## 11. References

- `apps/cli/src/index.ts` — host detection, provider default.
- `packages/orchestrator/src/orchestrator.ts:1131-1145` —
  `resolveProviderProcesses` Claude branch.
- `packages/orchestrator/src/taskExecutor.ts` — adapter wiring and
  retry surface.
- `packages/provider-adapters/src/claudeAdapter.ts` — current defaults.
- `packages/provider-adapters/src/processAdapters.ts` — shared spawn /
  parse / metadata extraction.
- `packages/provider-adapters/src/capabilities.ts` — manifest source.
- `skills/waygent/SKILL.md` — host-agent model policy and CLI mappings.
