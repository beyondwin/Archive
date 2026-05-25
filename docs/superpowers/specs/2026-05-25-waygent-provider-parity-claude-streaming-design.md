# Waygent — Provider Adapter Parity (Codex) + Claude Stream-JSON Activation Design

- **Date**: 2026-05-25
- **Type**: Single implementation design (combined C + D work items)
- **Status**: Approved (brainstorming complete)
- **Depends on**: 5750ab7, e9d258c, dfedacf, 39f898a (Claude host execution enhancements Phase 1–4)
- **Next artifact**: implementation plan via `superpowers:writing-plans`

## Why This Document

The Claude host execution enhancements (just landed) brought Phase 1–4 of
role-aware capability manifests, stream-json activation, system+user prompt
split, MCP/settings pass-through, host env sanitization, and deterministic
session_id resume to the Claude provider adapter. This left two adjacent gaps:

1. **Codex adapter lag** — Several Phase 3-equivalent capabilities (system+user
   prompt split for cache amortization, host env sanitization, retry-context
   prompt prefix, retry resume) are valuable on Codex too, but Codex CLI lacks
   direct flag analogs and so was not addressed in the Claude work.
2. **Stream-json under-utilization** — Claude now emits stream-json by default
   and we parse `result` + `system.init` + usage. The intermediate
   `assistant.tool_use` and `user.tool_result` envelopes carry per-task tool
   audit data we currently discard. Separately, the per-role cost profile
   (e.g., `verify_assist` running on `opus/high`) overprovisions cheap roles.

This document combines both into one implementation. They share the same
files (`packages/provider-adapters/src/{processAdapters.ts, capabilities.ts,
types.ts}` and `packages/orchestrator/src/orchestrator.ts`) and a single
multi-agent run is expected to close them in ~12–14 plan steps.

## Goals

- **G1**. Codex worker spawns benefit from prompt cache amortization across
  workers, equivalent in *effect* (not interface) to Claude's
  `--append-system-prompt` split.
- **G2**. Nested Codex-in-Codex invocations do not inherit parent host signal
  env vars that could confuse the child.
- **G3**. Codex retries reuse the prior attempt's session rather than starting
  cold, mirroring Claude's `--resume` behavior.
- **G4**. Provider options the adapter cannot honor surface as explicit
  warnings rather than silent drops.
- **G5**. Per-task tool-use is captured into worker evidence at standard
  granularity (name + input keys/sizes + result outcome + duration), enabling
  audit and downstream cost analysis without payload bloat or secret leakage.
- **G6**. Worker role (`implement` / `review` / `verify_assist`) drives the
  model and reasoning selection, so cheap roles run on cheap models by
  default and operators can override per role.

## Non-Goals

- D3: partial-message progress events from stream-json to Lens
  (out — unbounded volume; revisit in separate spec).
- SP-3 operator hygiene (alias normalization, `waygent diagnose`,
  `error_code` taxonomy, telemetry triage) — separate sub-project.
- SP-4 apply/resume granularity (partial apply, per-task retry CLI surface) —
  separate sub-project.
- Mapping Claude's `settings_path` / `mcp_config_path` to Codex-native
  mechanisms. Explicitly rejected with warning (C4).
- New provider adapters (acp, etc.).
- Schema version bump. All additions are additive and optional.

## Architecture Overview

Six work items across two themes. All changes are localized to existing files
in `packages/provider-adapters/src/` and `packages/orchestrator/src/`. No new
top-level packages, no new event types, no new CLI subcommands.

| ID | Theme | Primary surface | New CLI |
|---|---|---|---|
| **C1** | Codex env sanitize | `processAdapters.ts:buildSpawnEnv` | none |
| **C2** | Codex system+user prompt split (sentinel) | `buildProviderStdinPrompt` Codex branch | none |
| **C3** | Codex retry resume (`codex exec resume`) | `providerProcessArgs` Codex branch + orchestrator retry path | none |
| **C4** | Unsupported option explicit reject | `runProviderProcess` option validation | none |
| **D1** | Tool-use audit capture | `parseClaudeStreamJson` + `worker_result.evidence.tool_calls` | none |
| **D2** | Role-aware model routing | `orchestrator.ts` profile resolve + CLI parser | `--role-model`, `--role-reasoning` |

## Detailed Design

### C1. Codex Environment Sanitization

`processAdapters.ts:buildSpawnEnv` currently sanitizes only Claude host
keys when the parent process appears to be a Claude Code host:

```ts
const HOST_ENV_KEYS_TO_DROP = [
  "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PROJECT_DIR"
] as const;
```

Extend with Codex host keys and parallel detection:

- Add to drop list: `CODEX_APP`, `CODEX_CLI`, `CODEX_ENTRYPOINT`
- Detect Codex host parent: `parentEnv.CODEX_APP === "1"` OR
  `parentEnv.CODEX_CLI === "1"` OR `typeof parentEnv.CODEX_ENTRYPOINT === "string"`
- Sanitize when either Claude OR Codex parent host is detected
- `WAYGENT_KEEP_HOST_ENV=1` opt-out applies to both
- **Preserve `CODEX_HOME`** — it points at auth credential storage; dropping
  it breaks the child's ability to authenticate. Document this exception
  inline.

### C2. Codex System + User Prompt Split (Sentinel Block)

Claude uses OS-level split via `--append-system-prompt` (system) + stdin (user).
Codex CLI has no equivalent flag, so we use a sentinel-marked single message:

```
<system_instructions role="${role}">
${buildProviderSystemPrompt(role)}
</system_instructions>

<user_request>
${buildProviderUserPrompt("codex", request)}
</user_request>
```

- `buildProviderSystemPrompt(role)` and `buildProviderUserPrompt(provider,
  request)` already exist (provider-neutral). Reuse as-is.
- `buildProviderStdinPrompt("codex", request)` returns the wrapped
  concatenation. Claude branch unchanged (still returns just the user prompt).
- Sentinel tag names are part of the design contract — workers' downstream
  test fixtures depend on exact strings. Document them as cross-path
  invariants.
- Cache amortization mechanism: Codex provider caches the leading prefix of
  the message. As long as `<system_instructions role="${role}">...` is
  byte-stable per role, second and subsequent workers in the same role hit
  cache on that prefix. Variable task content sits inside `<user_request>`
  and does not break the prefix.

### C3. Codex Retry Resume

Codex exposes resume via subcommand `codex exec resume <SESSION_ID> [PROMPT]`
(not via flag on `codex exec`).

**First attempt path** (no resume):
- Spawn args: `["exec", "--json", "-"]` (current behavior; unchanged)
- After exit, parse first stream-json envelope to capture
  `session_id` → store in `worker_result.evidence.session_id`
- Field name to confirm in plan step against a real `codex exec --json`
  capture fixture (Risk R1)

**Retry path** (resume):
- When `options.resume_session_id` is set, spawn args become:
  `["exec", "resume", options.resume_session_id, "--json", "-"]`
- The retry user-prompt prefix from `buildProviderUserPrompt` (already used
  for Claude) flows on stdin same as first attempt

**Orchestrator wiring**:
- Generalize the existing `injectClaudeSessionContext(provider_processes, ctx)`
  to be provider-aware, or add a parallel `injectCodexResumeContext`. Decision
  deferred to plan author (small, mechanical; both viable). Whichever path
  chosen, the orchestrator must:
  - Set `resume_session_id` only on attempts where the prior attempt produced
    a captured `session_id` in evidence
  - Leave first attempts unchanged

**Codex `session_missing` detection** (parallel to Claude's
`detectResumeSessionMissing`):
- On retry stderr matching `/session.*not.*found/i` (or Codex-specific
  pattern — confirm in plan step), set
  `worker_result.evidence.resume_session_missing: true`
- Pattern alignment: if Codex stderr differs materially from Claude's, use
  Codex-specific regex; do not force shared pattern

### C4. Unsupported Provider Option Explicit Reject

`runProviderProcess` entry adds a manifest-driven option check. The
`ProviderCapabilityManifest` gains:

```ts
type ProviderCapabilityManifest = {
  // ... existing fields ...
  supports?: {
    settings_path: boolean;
    mcp_config_path: boolean;
    session_id_first_attempt: boolean;  // injectable pre-session UUID
    reasoning: boolean;                   // per-process reasoning control
  };
};
```

Initial values:

| Field | Claude | Codex |
|---|---|---|
| `settings_path` | true | false |
| `mcp_config_path` | true | false |
| `session_id_first_attempt` | true | false |
| `reasoning` | true | false |

On `runProviderProcess` entry, for every option set but reported unsupported:
- Append a structured string to `evidence.adapter_warnings`:
  `unsupported_provider_option: <option_name> (<provider>)`
- Continue execution (do not fail)
- Emit the same string to stderr summary so it surfaces in run output
- Silent skip is forbidden — the contract is that the operator either sees a
  warning or sees the option honored

### D1. Tool-Use Audit Capture

Extend `parseClaudeStreamJson` to additionally accumulate two envelope types
already present in Claude stream-json output but currently discarded:

- `{type: "assistant", message: {content: [{type: "tool_use", id, name,
  input}, ...]}, ...}` — tool invocation
- `{type: "user", message: {content: [{type: "tool_result", tool_use_id,
  content, is_error}, ...]}, ...}` — tool result

Existing `result` priority path and `system.init.model` attestation path are
unchanged. The new pass only accumulates side data.

**Schema** (`worker_result.evidence.tool_calls`):

```ts
type ToolCall = {
  tool_use_id: string;
  name: string;
  input_summary: {
    keys: string[];
    sizes_bytes: Record<string, number>;
  };
  result: {
    status: "ok" | "error";
    summary_bytes: number;
    is_error: boolean;
  } | null;
  duration_ms: number | null;
};
```

**Capture rules**:
- `input_summary.keys`: top-level keys of `input` object, sorted
- `input_summary.sizes_bytes`: for each string-valued top-level field,
  `Buffer.byteLength(value, "utf8")`; non-string fields omitted
- `result.summary_bytes`: total `Buffer.byteLength` across all `content`
  entries in the matching `tool_result`
- `result` is `null` when no `tool_result` envelope arrives before stream
  end (worker aborted mid-tool-call)
- `duration_ms`: difference between assistant envelope timestamp and user
  envelope timestamp; `null` if either timestamp is absent or unparseable
- Never store `input` values themselves or `tool_result.content` body
  (secret leakage prevention)

**Emission**:
- `tool_calls: ToolCall[]` attaches to existing `worker_result.evidence`
- No new lens event (per design: per-task rollup keeps store load bounded)
- Empty array when stream-json is the format and no tool calls occurred
- Key absent when stream-json is not the format or parse failed
  (preserves existing evidence contract)

### D2. Role-Aware Model Routing

**Profile resolution** changes from 2-slot (main, subagent) to per-role:

```ts
type RoleRouting = {
  implement:     { model: string; reasoning: ReasoningLevel };
  review:        { model: string; reasoning: ReasoningLevel };
  verify_assist: { model: string; reasoning: ReasoningLevel };
};
type ProfileResolved = {
  main: { model: string; reasoning: ReasoningLevel };
  roles: RoleRouting;
};
type ReasoningLevel = "medium" | "high" | "xhigh";
```

**Built-in profiles**:

| Profile | main | implement | review | verify_assist |
|---|---|---|---|---|
| `max-quality` | opus/high | opus/high | opus/high | opus/high |
| `balanced` | opus/high | opus/high | sonnet/medium | sonnet/medium |
| `cost-saver` | haiku/medium | sonnet/medium | haiku/medium | haiku/medium |

`max-quality` keeps current behavior. `balanced` and `cost-saver` are
redefined to be role-aware.

**New CLI flags**:

- `--role-model implement=opus,review=sonnet-4-6,verify_assist=haiku-4-5`
- `--role-reasoning implement=high,review=medium,verify_assist=medium`
- Both accept comma-separated `key=value` pairs
- Partial set is OK (unspecified roles inherit profile default)
- Unknown role key (anything other than `implement|review|verify_assist`) →
  CLI parse error
- Unknown reasoning value → CLI parse error

**Resolution priority** (higher wins):
1. `--main-model` / `--main-reasoning` (host coordinator only)
2. `--subagent-model` / `--subagent-reasoning` (every worker role, en masse —
   semantics preserved from current behavior; not deprecated)
3. `--role-model` / `--role-reasoning` (worker role individually)
4. `--profile <name>` defaults

`--subagent-model` and `--role-model` compose: subagent-model fills all roles
that `--role-model` does not specify. No conflict.

**Orchestrator integration**:
- At worker dispatch time, the orchestrator looks up the resolved
  `(model, reasoning)` for the worker's role and sets
  `ProviderProcessOptions.model` / `.reasoning` to the resolved single value
  before spawning. No change to `ProviderProcessOptions` shape.
- `lens.model_attestation_confirmed` will report different `expected_model`
  values per worker (one per role). Mismatch noise from alias-only
  differences (e.g., `opus` vs `claude-opus-4-7`) is **accepted** for this
  spec; alias normalization is SP-3 scope.

**Codex coupling**:
- For Codex workers, resolved `model` maps to `codex exec -m <model>`.
- Resolved `reasoning` for a Codex worker is **not passed to the Codex
  CLI** (Codex has no per-process reasoning flag) and is surfaced via the
  C4 mechanism as an `adapter_warnings` entry
  (`unsupported_provider_option: reasoning (codex)`), driven by manifest
  `supports.reasoning = false` for Codex. The operator sees the warning
  whenever a `--role-reasoning` / `--main-reasoning` / `--subagent-reasoning`
  value would have applied to a Codex worker.

## Schema and Event Changes (Summary)

Additive only. No schema version bump.

- `worker_result.evidence.tool_calls?: ToolCall[]` — D1
- `worker_result.evidence.adapter_warnings?: string[]` — C4
- `worker_result.evidence.session_id?: string` — C3 (Codex; field already
  defined for Claude)
- `worker_result.evidence.resume_session_missing?: boolean` — C3 (Codex;
  field already defined for Claude)
- `ProviderCapabilityManifest.supports?: { settings_path, mcp_config_path,
  session_id_first_attempt, reasoning }` — C4

No new event types. `lens.model_attestation_confirmed` payload unchanged
(only the data it reports diversifies under D2).

## Cross-Path Invariants

- **CP-1**. Sentinel tag strings `<system_instructions role="...">` and
  `<user_request>` (C2) appear in two places that must stay in sync:
  `buildProviderStdinPrompt` (Codex branch) and the fixture-based parser
  tests. Test fixture asserts exact strings.
- **CP-2**. The HOST_ENV_KEYS_TO_DROP list (C1) and the host-detection
  predicate are co-located in `buildSpawnEnv`. If either changes, the unit
  test enumerating each key + each detected parent host combination must be
  updated.
- **CP-3**. `ProviderCapabilityManifest.supports` (C4) and the unsupported
  option check in `runProviderProcess` are paired: every key in `supports`
  must have a corresponding check; every check must look up exactly one key
  in `supports`. A manifest test enumerates this.
- **CP-4**. Profile resolution priority (D2) is implemented in
  `orchestrator.ts` and asserted by an explicit matrix test:
  every combination of `(profile, --subagent-*, --role-*, --main-*)` set/unset
  is covered once.

## Testing Strategy

Each plan task uses the established TDD 6-step pattern (failing test →
verify red → implement → verify green → full package test → commit), same
as the Claude host enhancements plan.

**Unit tests**:
- `packages/provider-adapters/tests/processAdapters.test.ts`:
  - Codex env sanitize: parent Codex host detection, key drop, opt-out,
    CODEX_HOME preservation
  - Codex sentinel prompt format (exact string)
  - Codex retry resume args transformation
  - Unsupported option warning emission (each manifest field)
  - Tool-use parser: assistant→user pairing, ok/error result, null result
    on incomplete pair, duration_ms computation
- `packages/provider-adapters/tests/capabilities.test.ts`:
  - Manifest `supports` lock for Claude and Codex (current values per table
    above)
- `packages/orchestrator/tests/orchestrator.test.ts`:
  - Profile resolve matrix: priority rules (--main, --subagent, --role,
    profile) × (implement, review, verify_assist, main)
- CLI tests (`apps/cli/tests/`):
  - `--role-model` / `--role-reasoning` parse (valid, unknown role, unknown
    reasoning, partial set)

**Fixtures** (new):
- `packages/provider-adapters/tests/fixtures/claude-stream-json-with-tools.jsonl`
  — assistant.tool_use + user.tool_result sequence, plus result envelope
- `packages/provider-adapters/tests/fixtures/codex-stream-json-session-init.jsonl`
  — Codex first-envelope session_id capture (captured live during plan
  execution; field name confirmed against actual Codex output)

**Integration**:
- `bun run waygent:scenarios` — multi-agent scenario assertion that
  `balanced` profile yields different model attestation per role
- `bun run platform:demo` — fake provider regression

**Verify isolation**: cross-package work between `provider-adapters` and
`orchestrator` likely. Plan tasks should declare
`verify_isolation: "isolated"` (see
`docs/operations/verification.md`).

**Manual / observational** (post-plan, not gated):
- Real Codex run: confirm sentinel prompt cache hits via
  `cached_read_tokens` in run summary
- Real Claude run: confirm `tool_calls` populates with realistic worker

## Risks and Mitigations

- **R1 — Codex session_id field name assumption**. The Codex stream-json
  envelope key for session id is inferred, not confirmed. *Mitigation*: First
  plan task in Phase A (C3 fixture capture) runs `codex exec --json -` once
  against a trivial prompt and locks the actual field name into the fixture.
  If the assumption fails, it surfaces in that single step.
- **R2 — `--subagent-model` + `--role-model` conflict semantics**. Operators
  could be surprised by the layering. *Mitigation*: priority matrix is
  documented inline and exhaustively tested (CP-4).
- **R3 — Codex `instructions` config field viability**. We chose option A
  (sentinel) over B/C (`-c instructions=...`) without confirming that field's
  actual support. *Mitigation*: A is self-contained; no rollback cost. If
  post-spec measurement shows poor Codex cache adoption, a follow-up spec
  can swap to `-c instructions=<file>` (C-style) without changing the
  worker contract.
- **R4 — Tool-use envelope schema drift**. Anthropic could change
  `assistant.tool_use` shape in stream-json. *Mitigation*:
  `parseClaudeStreamJson` already skips unknown envelopes gracefully.
  `tool_calls` key absence vs `[]` is meaningful (parser failure vs no
  calls), so consumers see drift as missing data rather than wrong data.
- **R5 — `lens.model_attestation_mismatch` noise under D2**. Different
  models per role increase the surface for alias-only mismatches.
  *Mitigation*: accepted for this spec; alias normalization is explicit
  SP-3 scope and documented as such.

## Plan Shape Estimate

~12–14 waygent-task steps under a single `task_id`. Phase grouping:

- **Phase A** — Codex parity (C1 env, C2 prompt split, C3 resume, C4 reject)
  ~6 steps including R1 fixture capture
- **Phase B** — D1 tool-use audit capture ~3 steps (fixture, parser, evidence
  wiring)
- **Phase C** — D2 role routing ~4 steps (manifest extension + CLI parser +
  orchestrator resolve + profile redefinition)
- **Phase D** — Integration gate ~1 step (`bun run check`, scenarios, demo,
  `git diff --check`)

Plan author is expected to use the
`superpowers:writing-plans` skill and follow the same TDD 6-step pattern,
verify_isolation declarations, and Cross-Path Invariants references as the
Claude host enhancements plan that this design extends.
