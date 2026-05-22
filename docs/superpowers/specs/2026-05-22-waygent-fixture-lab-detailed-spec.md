# Waygent Fixture-Lab Defect Remediation — Detailed Technical Specification

Date: 2026-05-22
Status: Source-audited contract specification (companion to
`2026-05-22-waygent-fixture-lab-defect-remediation-design.md`)

This document is the **formal interface contract** for the remediation
work. The design spec (S0–S13) answers *why* and *what*; this document
answers *exactly what code must exist*. Every new module, function,
type, event payload, and invariant is declared here in TypeScript with
pre/post-conditions. An implementer should be able to write production
code by following this document alone; an evaluator should be able to
write conformance tests from it directly.

Scope rules:

- **No new package boundary.** Every new module lives inside an existing
  workspace package (`provider-adapters`, `orchestrator`,
  `context-packer`, `apps/cli`).
- **All schema changes are additive.** No bumps to `waygent.run_state.v2`
  or `agentlens.event.v3` envelopes. New optional fields and new
  `event_type` enum entries only.
- **Backward-compatible signatures.** Any modified exported function
  keeps its prior call sites working (verified against 27 internal
  callers of `runWaygent`, all callers of `parseWorkerOutput`,
  `metadataFromParsed`, `buildTaskPacket`, etc.).

Cross-reference: section numbers like `[D-09]` refer to defect IDs in
`docs/2026-05-22-waygent-vs-cme-fixture-lab-analysis.md`. Section
numbers like `[S2.1]` refer to the design spec.

---

## 1. Module Inventory

| # | Module | Status | Owner Package |
|---|--------|--------|---------------|
| M01 | `processAdapters.ts` | modified | `provider-adapters` |
| M02 | `recoveryExecutor.ts` | **new** | `orchestrator` |
| M03 | `planParser.ts` | modified | `orchestrator` |
| M04 | `planNormalizer.ts` | modified | `orchestrator` |
| M05 | `planAdapters/projectScriptCatalog.ts` | **new** | `orchestrator` |
| M06 | `planAdapters/riskInference.ts` | **new** | `orchestrator` |
| M07 | `planAdapters/verifyQuality.ts` | **new** | `orchestrator` |
| M08 | `planAdapters/instructionsExtract.ts` | **new** (move) | `orchestrator` |
| M09 | `runIdDerivation.ts` | **new** | `orchestrator` |
| M10 | `taskExecutor.ts` | modified | `orchestrator` |
| M11 | `orchestrator.ts` | modified | `orchestrator` |
| M12 | `orphanRuns.ts` | modified | `orchestrator` |
| M13 | `taskPacket.ts` | modified | `context-packer` |
| M14 | `apps/cli/src/index.ts` | modified | `apps/cli` |
| M15 | `contracts/src/types.ts` | modified (additive) | `contracts` |
| M16 | `contracts/src/events.ts` | modified (additive) | `contracts` |

Dependency edges (`A → B` = A imports from B):

```
recoveryExecutor      → contracts (FailureClass)
projectScriptCatalog  → (none — fs only)
riskInference         → contracts (RiskLevel, FileClaim)
verifyQuality         → contracts (ParsedWaygentTask, FileClaim)
instructionsExtract   → (none — string ops)
runIdDerivation       → (none — string + Date)
taskExecutor          → recoveryExecutor, contracts
planNormalizer        → projectScriptCatalog, riskInference, verifyQuality, instructionsExtract
planParser            → instructionsExtract
taskPacket            → projectScriptCatalog
processAdapters       → (no orchestrator deps; new helpers internal)
orchestrator          → runIdDerivation
orphanRuns            → orchestrator (defaultRunRoot)
apps/cli              → orchestrator, runIdDerivation
```

No cycles. `planAdapters/*` forms a leaf cluster under
`orchestrator/src/planAdapters/`.

---

## 2. M01 — `processAdapters.ts`

### 2.1 `parseJsonText` (modified)

```ts
/**
 * Parse a string that may contain a worker_result JSON, possibly wrapped
 * in markdown narrative or multiple code fences.
 *
 * Resolution order:
 *   1. Direct JSON.parse(trimmed) — accept if isWorkerResultCandidate.
 *   2. Enumerate ALL fenced blocks via /```(\w+)?\s*([\s\S]*?)```/g.
 *      Try in priority: `json` label → unlabeled → other language.
 *   3. Enumerate balanced {...} spans (string-aware, largest first).
 *   4. Fall through to the direct parse (worker-result-shaped or not)
 *      for legacy demo plans whose result is raw JSON without a fence.
 *
 * PRE:  value is a string of any length, possibly empty.
 * POST: returns either `unknown` satisfying isWorkerResultCandidate,
 *       OR the direct-parsed value (worker-shaped or not),
 *       OR null when no parse path yields a JSON value.
 */
export function parseJsonText(value: string): unknown | null;
```

Invariant `I-PARSE-1`: if `parseJsonText(s) !== null` and the returned
value satisfies `isWorkerResultCandidate`, then `isWorkerResultCandidate`
holds **structurally** — i.e., the value has `status` AND at least one
of `{changed_files, summary, evidence}`.

Invariant `I-PARSE-2`: `parseJsonText` does NOT throw on any string
input. All `JSON.parse` calls happen inside `tryParseJson`, which
returns null on failure.

### 2.2 `enumerateBalancedBraceSpans` (new internal helper)

```ts
/**
 * Yield each balanced {...} span in `text`, largest first.
 * Skips braces inside double-quoted JSON strings (string-aware).
 * Honors backslash escapes inside strings.
 * Bails (returns) on unterminated input — no infinite loop.
 *
 * PRE:  text is any string.
 * POST: emits each span as a substring; ordering by length DESC.
 *       Spans do not overlap (each opening { is consumed exactly once).
 */
function* enumerateBalancedBraceSpans(text: string): Generator<string>;
```

Invariant `I-BRACE-1`: for every yielded span `s`, the count of
unescaped `{` in `s` equals the count of unescaped `}` in `s`.

Invariant `I-BRACE-2`: if `text` contains zero `{`, the generator
yields nothing (empty generator).

### 2.3 `unwrapProviderEnvelope` (modified return type)

```ts
export interface UnwrappedEnvelope {
  /** The worker_result JSON if found, else the original parsed value. */
  unwrapped: unknown;
  /** The provider's top-level envelope when distinct from unwrapped, else null. */
  envelope: unknown | null;
}

/**
 * Locate a worker_result JSON inside a provider envelope.
 *
 * Search order:
 *   (a) Direct paths: value.result, value.message, value.text,
 *       value.item.text — ALREADY in source; preserved.
 *   (b) NEW: depth-≤3 string-leaf scan. Walks the envelope tree and
 *       collects each string leaf; calls parseJsonText on each;
 *       returns the first one that is a worker_result candidate.
 *
 * PRE:  parsed is any value.
 * POST: if parsed is not an object, returns { unwrapped: parsed, envelope: null }.
 *       Otherwise returns { unwrapped, envelope } where envelope is the
 *       original parsed object iff unwrapped differs from parsed.
 */
export function unwrapProviderEnvelope(parsed: unknown): UnwrappedEnvelope;
```

Invariant `I-UNWRAP-1`: if `unwrapped !== parsed` then `envelope === parsed`
(non-null). If `unwrapped === parsed` then `envelope === null`.

Migration: the single caller in `parseWorkerOutput` destructures
`{ unwrapped }`. No other call sites exist (verified by grep).

### 2.4 `isWorkerResultCandidate` (modified — tightened)

```ts
/**
 * Worker-result predicate. Used to reject bare provider envelopes
 * (which lack `status`) while still accepting both completed and failed
 * worker_results.
 *
 * PRE:  value is any.
 * POST: true iff value is a non-null non-array object AND value.status
 *       is present AND at least one of {changed_files, summary, evidence}
 *       is present at top level.
 */
function isWorkerResultCandidate(value: unknown): value is Partial<WorkerResult>;
```

Source delta: current predicate accepts `status | changed_files | summary | failure_class`
(OR). New predicate requires `status` AND one of `{changed_files, summary, evidence}`.

Invariant `I-CANDIDATE-1`: for the literal task_3 stdout fixture, the
new predicate returns true on the worker_result JSON inside the fenced
block and false on the outer envelope.

### 2.5 `metadataFromParsed` (modified signature)

```ts
function metadataFromParsed(
  provider: "codex" | "claude" | "acp",
  parsed: Partial<WorkerResult>,
  envelope: unknown | null    // NEW — from UnwrappedEnvelope.envelope
): ProviderRunMetadata;
```

Behavior:

```
usage = usageFromEnvelope(envelope)
     ?? usageFromEvidence(parsed.evidence ?? {})
     ?? null

actual_model = modelFromEnvelope(envelope, provider)
            ?? actualModelFromEvidence(parsed.evidence ?? {})

usage_source =
  envelope-derived → "provider_json"
  evidence-derived → existing logic (provider_json | event_stream)
  null             → "missing_in_provider_output"   (renamed from "unknown" when envelope present but lacking usage)
  no envelope at all → "unknown"
```

Invariant `I-META-1`: when `usageFromEnvelope` returns non-null, that
result takes precedence over any `evidence.usage`.

### 2.6 `usageFromEnvelope` (new internal)

```ts
/**
 * Extract token usage from a provider envelope (claude shape).
 *
 * Claude --output-format json places usage at the envelope root:
 *   { usage: { input_tokens, output_tokens,
 *              cache_creation_input_tokens, cache_read_input_tokens } }
 *
 * Lenience rule (S6.2): only input_tokens + output_tokens are required.
 * Cache fields, if absent, default to 0 — they are informational and
 * don't affect cost computation.
 *
 * PRE:  envelope is any.
 * POST: TokenUsage if envelope has usable .usage.{input_tokens,output_tokens};
 *       null otherwise.
 */
function usageFromEnvelope(envelope: unknown): TokenUsage | null;
```

### 2.7 `modelFromEnvelope` (new internal)

```ts
interface ActualModel {
  model: string | null;
  reasoning: string | null;
  source: "provider_json" | "worker_self_report" | "unknown";
}

/**
 * Extract model attestation from a provider envelope.
 *
 * Claude shape: envelope.modelUsage = { "<model-id>": { ... } }.
 * Take the first key as actual_model.model. Reasoning level is not
 * present in the envelope, so reasoning stays null.
 *
 * PRE:  envelope is any.
 * POST: ActualModel with source="provider_json" if a model key was
 *       extracted; null when no extraction succeeded (caller falls
 *       back to evidence-based extraction).
 */
function modelFromEnvelope(
  envelope: unknown,
  provider: "codex" | "claude" | "acp"
): ActualModel | null;
```

### 2.8 `buildProviderPrompt` (modified to surface exec allowlist)

```ts
export function buildProviderPrompt(
  provider: "codex" | "claude",
  request: AdapterRequest
): string;
```

New behavior: when `request.task_packet?.allowed_exec_commands` is a
non-empty array, append two lines to the prompt:

```
You may invoke these commands during self-verification (others will be denied):
  <allowed_exec_commands joined by '\n  '>
You SHOULD invoke the verification commands listed in task_packet.acceptance_commands before returning status:completed.
```

Invariant `I-PROMPT-1`: the prompt always ends with the task's prompt
body (request.prompt). The allowlist block is inserted before the task
body, not after.

---

## 3. M02 — `recoveryExecutor.ts` (new)

### 3.1 Public types

```ts
export type RecoveryAction =
  | "retry_with_strict_prompt"
  | "retry_with_evidence"
  | "request_decision"
  | "halt";

export interface PolicyEntry {
  action: RecoveryAction;
  max_attempts: number;        // 0 = never retry; halt or request_decision
}

export interface RecoveryDecision {
  failure_class: FailureClass;
  attempt_number: number;       // 1-indexed; the NEXT attempt this would be
  max_attempts: number;
  action: RecoveryAction;
  /** Only present when action === "retry_with_strict_prompt". */
  strict_prompt_suffix?: string;
}

export interface NextRecoveryActionInput {
  failure_class: FailureClass;
  prior_attempts: number;       // count of previous attempts (NOT including the one about to be considered)
  prior_summary?: string;        // for prompt suffix building
  max_overrides?: Partial<Record<FailureClass, number>>;
}
```

### 3.2 Policy matrix

```ts
export const RECOVERY_POLICY: Readonly<Record<FailureClass, PolicyEntry>> = {
  adapter_crashed:           { action: "retry_with_strict_prompt", max_attempts: 1 },
  timeout:                   { action: "request_decision",          max_attempts: 1 },
  cancelled:                 { action: "halt",                      max_attempts: 0 },
  malformed_result:          { action: "retry_with_strict_prompt", max_attempts: 2 },
  diff_scope_failed:         { action: "retry_with_evidence",       max_attempts: 2 },
  review_changes_requested:  { action: "retry_with_evidence",       max_attempts: 3 },
  review_rejected:           { action: "request_decision",          max_attempts: 1 },
  verification_failed:       { action: "retry_with_evidence",       max_attempts: 3 },
  merge_conflict:            { action: "request_decision",          max_attempts: 1 },
  needs_rebase:              { action: "request_decision",          max_attempts: 1 },
  needs_plan_fix:            { action: "halt",                      max_attempts: 0 },
  needs_split:               { action: "halt",                      max_attempts: 0 },
  needs_infra_fix:           { action: "request_decision",          max_attempts: 1 },
  missing_checkpoint:        { action: "retry_with_strict_prompt", max_attempts: 1 },
  missing_resume_handler:    { action: "request_decision",          max_attempts: 1 },
  permission_denied:         { action: "request_decision",          max_attempts: 1 },
  service_unreachable:       { action: "retry_with_strict_prompt", max_attempts: 2 },
  dependency_missing:        { action: "request_decision",          max_attempts: 1 },
  environment_blocker:       { action: "request_decision",          max_attempts: 1 },
  flaky_unconfirmed:         { action: "retry_with_evidence",       max_attempts: 2 },
  command_not_found:         { action: "request_decision",          max_attempts: 1 },
  dependency_blocked:        { action: "request_decision",          max_attempts: 1 },
  file_claim_conflict:       { action: "request_decision",          max_attempts: 1 },
  dirty_source_checkout:     { action: "request_decision",          max_attempts: 1 },
  unsafe_apply:              { action: "request_decision",          max_attempts: 1 },
  state_drift:               { action: "request_decision",          max_attempts: 1 },
  artifact_missing:          { action: "retry_with_strict_prompt", max_attempts: 1 },
  stale_activity:            { action: "request_decision",          max_attempts: 1 },
  terminal_rejected:         { action: "halt",                      max_attempts: 0 }
};
```

The matrix has 29 entries — one per `FailureClass` union member
(`packages/contracts/src/types.ts:30–59`). The TypeScript compiler must
enforce this: if a new `FailureClass` is added without an entry, the
`Readonly<Record<FailureClass, PolicyEntry>>` shape forces a compile
error.

### 3.3 `nextRecoveryAction`

```ts
export function nextRecoveryAction(
  input: NextRecoveryActionInput
): RecoveryDecision;
```

Algorithm:

1. `entry = RECOVERY_POLICY[input.failure_class]`.
2. `maxAttempts = input.max_overrides?.[input.failure_class] ?? entry.max_attempts`.
3. If `input.prior_attempts >= maxAttempts`:
   - If `entry.action === "halt"`: return `{ ..., action: "halt", attempt_number: input.prior_attempts + 1 }`.
   - Else: return `{ ..., action: "request_decision", attempt_number: input.prior_attempts + 1 }`.
4. Else:
   - Compute `strict_prompt_suffix` if `entry.action === "retry_with_strict_prompt"`.
   - Return `{ ..., action: entry.action, attempt_number: input.prior_attempts + 1, max_attempts: maxAttempts, strict_prompt_suffix }`.

Invariant `I-RECOVERY-1`: pure function. Output is determined by
input; no I/O, no Date, no random.

Invariant `I-RECOVERY-2`: `action === "halt"` ⇒ `max_attempts === 0`.

### 3.4 `buildStrictPromptSuffix`

```ts
function buildStrictPromptSuffix(input: {
  failure_class: FailureClass;
  attempt_number: number;
  prior_summary?: string;
}): string;
```

Output template (matches design S3.3, exact format):

```
PRIOR ATTEMPT (#<attempt_number - 1>) FAILED.
failure_class: <failure_class>
prior_summary: <truncated to 240 chars; "(none recorded)" if absent>

You MUST respond with ONLY a single fenced ```json block containing the
runway.worker_result.v1 object. Required fields: schema, task_id,
candidate_id, status, changed_files, summary, evidence. No prose before
or after the fence. No additional fenced blocks of any language.
```

---

## 4. M05 — `planAdapters/projectScriptCatalog.ts` (new)

### 4.1 Public types

```ts
export type CatalogSource = "npm" | "pnpm" | "yarn" | "bun" | "make" | "poetry" | "project";

export interface ProjectScriptCatalog {
  /** Verbatim command strings, e.g. "npm run lint", "make test". */
  commands: ReadonlySet<string>;
  /** Map from command to where it was discovered. */
  sources: ReadonlyMap<string, CatalogSource>;
  workspace_root: string;
}

export function buildProjectScriptCatalog(workspace: string): ProjectScriptCatalog;
```

### 4.2 Discovery rules

| Source file | Pattern | Emitted command(s) |
|-------------|---------|--------------------|
| `<ws>/package.json` `scripts.<name>` | object key | `npm run <name>`, `pnpm run <name>`, `bun run <name>`, `yarn <name>` |
| `<ws>/Makefile` `^([a-zA-Z][a-zA-Z0-9_-]*):` (non-`.PHONY:` lines) | first column | `make <target>` |
| `<ws>/pyproject.toml` `[tool.poetry.scripts]` keys | TOML key | `poetry run <name>`, `<name>` |
| `<ws>/pyproject.toml` `[project.scripts]` keys | TOML key | `<name>`, `python -m <module>` (when value parseable) |

Discovery is non-throwing — a missing/malformed file yields zero
contributions from that source, never an exception.

Invariant `I-CATALOG-1`: `catalog.commands.size === catalog.sources.size`.
Every command has exactly one source attribution.

Invariant `I-CATALOG-2`: the catalog is **read-only** from the
implementer's perspective. Mutations after construction are forbidden.

### 4.3 `isCommandInCatalog`

```ts
/**
 * Check if a single command (no && chains) is in the catalog.
 * Accepts exact match OR prefix match where the rest is an argument list.
 *
 * Example: catalog has "npm run lint";
 *   isCommandInCatalog("npm run lint")            → true (exact)
 *   isCommandInCatalog("npm run lint -- --fix")   → true (prefix + args)
 *   isCommandInCatalog("npm run linter")          → false
 */
export function isCommandInCatalog(
  command: string,
  catalog: ProjectScriptCatalog
): boolean;
```

---

## 5. M06 — `planAdapters/riskInference.ts` (new)

### 5.1 Public API

```ts
export type RiskLevel = "low" | "medium" | "high";

export interface RiskInferenceInput {
  title: string;
  body: string;
  file_claims: ReadonlyArray<{ path: string; mode?: string }>;
}

export interface RiskInferenceResult {
  risk: RiskLevel;
  reason: string;
  matched_signals: string[];  // for diagnostics
}

export function inferRiskLevel(input: RiskInferenceInput): RiskInferenceResult;
```

### 5.2 Rules (evaluated top-down; first match wins)

```ts
const HIGH_KEYWORDS = /\b(schema migration|database migration|public api|breaking change|production deploy|secrets?|credentials?|auth(entication)?)\b/i;
const HIGH_PATHS    = /(migration|schema|public-api|production|secrets?)/i;
const HIGH_CLAIM_COUNT = 10;
```

1. **HIGH** if title+body matches `HIGH_KEYWORDS` →
   `reason: "high-risk keyword match"`.
2. **HIGH** if `file_claims.length > HIGH_CLAIM_COUNT` OR any
   `file_claim.path` matches `HIGH_PATHS` →
   `reason: "high file_claim count or sensitive path"`.
3. **MEDIUM** if the set of top-level dirs in `file_claims.path.split("/")[0]`
   has size > 1 →
   `reason: "cross-package claims"`.
4. **LOW** otherwise →
   `reason: "single-package, no risk keyword"`.

Invariant `I-RISK-1`: pure function of input. No fs, no Date.

Invariant `I-RISK-2`: `matched_signals` is non-empty for every result
(includes at minimum the rule label).

---

## 6. M07 — `planAdapters/verifyQuality.ts` (new)

### 6.1 Public API

```ts
export const TRIVIAL_TOKENS: ReadonlySet<string> =
  new Set(["printf", "true", ":", "echo", "/usr/bin/true", "/bin/true"]);

export function isTrivialVerifyCommand(cmd: string): boolean;

export interface VerifyTheaterResult {
  is_theater: boolean;
  reasons: string[];
}

export function detectVerifyTheater(input: {
  verify: ReadonlyArray<string>;
  file_claims: ReadonlyArray<{ path: string }>;
}): VerifyTheaterResult;
```

### 6.2 Algorithm

`isTrivialVerifyCommand(cmd)`:
1. Take first whitespace-delimited token of `cmd.trim()`.
2. Return `TRIVIAL_TOKENS.has(token)`.

`detectVerifyTheater({ verify, file_claims })`:
1. If `verify.length === 0`: push `"no verify commands"`.
2. Else if `verify.every(isTrivialVerifyCommand)`: push
   `"all verify commands are trivial"`.
3. Let `claimGlobs = file_claims.map(c => globToRegex(c.path))`.
   If `claimGlobs.length > 0` AND no `verify` command's tokenized path
   arguments match any `claimGlob`: push
   `"verify does not reference any claimed file"`.
4. `is_theater = reasons.length > 0`.

`globToRegex` is a minimal converter: `*` → `[^/]*`, `**` → `.*`, otherwise
literal. Compiled regex anchored at `^...$`.

Invariant `I-VERIFY-1`: `detectVerifyTheater({ verify: [], file_claims: [] }).is_theater === true`
(no verify is trivially theater).

---

## 7. M08 — `planAdapters/instructionsExtract.ts` (new — extracted)

### 7.1 Public API

```ts
/**
 * Strip RUN_BLOCK git-mutating commands and normalize an instruction
 * section into a line array, capped at 160 lines.
 *
 * Originally located in planNormalizer.ts:182–193; moved here so
 * planParser.ts can also consume it without circular deps.
 *
 * PRE:  section is any string.
 * POST: array of trimmed non-empty lines, length ≤ 160.
 */
export function extractInstructionLines(section: string): string[];
```

No behavior change vs. the current implementation — pure move.

---

## 8. M09 — `runIdDerivation.ts` (new)

### 8.1 Public API

```ts
/**
 * Derive a default run_id from a plan path and timestamp.
 *
 *   <plan_basename_slug>_<YYYYMMDD_HHMMSS>
 *
 * Slug rules (applied to basename without extension):
 *   1. Strip leading "YYYY-MM-DD-" date prefix if present.
 *   2. Lowercase.
 *   3. Replace runs of [^a-z0-9]+ with single "_".
 *   4. Strip leading/trailing "_".
 *
 * Timestamp: ISO date+time without separators, e.g. "20260522_193045".
 *
 * If `now` is omitted, uses `new Date()` (and is therefore impure;
 * callers requiring determinism inject a fixed Date).
 */
export function deriveAutoRunId(planPath: string, now?: Date): string;
```

Examples (PRE → POST):

```
("plans/2026-05-20-trustworthy-source-matching-local-fixture-lab.md", 2026-05-22T19:30:45Z)
  → "trustworthy_source_matching_local_fixture_lab_20260522_193045"

("waygent-task.md", 2026-05-22T00:00:00Z)
  → "waygent_task_20260522_000000"

("unnamed-plan", 2026-05-22T00:00:00Z)
  → "unnamed_plan_20260522_000000"
```

Invariant `I-RUNID-1`: output matches `/^[a-z0-9_]+_[0-9]{8}_[0-9]{6}$/`.

Invariant `I-RUNID-2`: for fixed inputs, output is deterministic.

---

## 9. M10 — `taskExecutor.ts` (modified)

### 9.1 Retry-loop integration

The current dispatch returns after one attempt. The modified flow:

```
attempts: AttemptRecord[] = []
loop:
  result = executeProviderAttempt(task, packet)
  attempts.push(result)
  if result.worker.status === "completed" without failure_class: break
  decision = nextRecoveryAction({
    failure_class: result.worker.failure_class,
    prior_attempts: attempts.length,
    prior_summary: result.worker.summary
  })
  emit "runway.recovery_attempt" event with decision
  switch decision.action:
    case "retry_with_strict_prompt":
      packet = { ...packet, previous_failures: [...packet.previous_failures ?? [], {...}] }
      // strict prompt suffix is consumed by buildProviderPrompt via task_packet
      continue loop
    case "retry_with_evidence":
      packet = { ...packet, previous_failures: [...], evidence_hint: result.worker.summary }
      continue loop
    case "request_decision":
      record decision_required; break loop
    case "halt":
      break loop
return final attempts
```

Invariant `I-TASKEX-1`: loop iterations are bounded by
`max(RECOVERY_POLICY[fc].max_attempts) + 1 = 4` (verification_failed +
review_changes_requested both cap at 3).

Invariant `I-TASKEX-2`: every retry emits exactly one
`runway.recovery_attempt` event before re-dispatch.

---

## 10. M11 — `orchestrator.ts` (modified)

### 10.1 `runWaygent` — run_id derivation

Replace `const runId = options.run_id ?? "run_demo"` at line 75 with:

```ts
const runId = options.run_id
  ?? deriveAutoRunId(typeof options.plan === "string" ? options.plan : "unnamed-plan");
```

No signature change. Existing callers passing explicit `run_id` are
unaffected.

### 10.2 `defaultRunRoot` — platform-aware

```ts
export function defaultRunRoot(): string {
  switch (process.platform) {
    case "darwin":
      return join(homedir(), "Library", "Application Support", "waygent", "runs");
    case "linux": {
      const xdg = process.env.XDG_DATA_HOME;
      return xdg && xdg.length > 0
        ? join(xdg, "waygent", "runs")
        : join(homedir(), ".local", "share", "waygent", "runs");
    }
    case "win32":
      return join(process.env.LOCALAPPDATA ?? join(homedir(), "AppData", "Local"),
                  "waygent", "runs");
    default:
      process.stderr.write(
        `WARN: unsupported platform '${process.platform}'; using tmpdir for waygent runs (volatile)\n`
      );
      return join(tmpdir(), "waygent-runs");
  }
}
```

Invariant `I-ROOT-1`: returns an absolute path on supported platforms.

Invariant `I-ROOT-2`: pure function of `process.platform`, `homedir()`,
`process.env.XDG_DATA_HOME`, `process.env.LOCALAPPDATA`. No fs access
during computation. Directory creation happens at the call site,
not here.

### 10.3 `mkdirSync` on first use

In `runWaygent` setup, before calling `hasExistingRunEvidence`, ensure
the parent directory exists:

```ts
mkdirSync(paths.root, { recursive: true });
```

Idempotent; safe when the directory pre-exists.

---

## 11. M12 — `orphanRuns.ts` (modified)

### 11.1 Dual-root scan

New signature additive:

```ts
export interface OrphanRunsScanInput {
  root?: string;             // existing
  /** When `root` is omitted AND `auto_scan_legacy` is true (default),
   *  also scan the legacy tmpdir/waygent-runs root. */
  auto_scan_legacy?: boolean;
}

export interface OrphanRunEntry {
  // ... existing fields ...
  migration_suggested?: boolean;  // NEW — true for entries from legacy root
}
```

Behavior when `input.root` is omitted:

1. Scan `defaultRunRoot()` → entries without `migration_suggested`.
2. If `auto_scan_legacy !== false`, also scan
   `join(tmpdir(), "waygent-runs")` → entries with
   `migration_suggested: true`.
3. Merge into a single list, deduplicated by `run_id` (legacy entries
   replaced by new-root entries when both exist).

Invariant `I-ORPHAN-1`: when `input.root` is set, scan only that root;
no auto-scan.

---

## 12. M13 — `taskPacket.ts` (modified)

### 12.1 Modified `BuildTaskPacketInput`

```ts
export interface BuildTaskPacketInput {
  // ... existing fields ...
  /** Workspace root for catalog discovery. Optional; when absent, no
   *  catalog is built and allowed_exec_commands stays null. */
  workspace?: string;
  /** Full plan section body (title + step lines). Used to build the
   *  plan_excerpt. When absent, plan_excerpt stays the task title. */
  plan_body?: string;
  /** Existing optional field. */
  max_chars?: number;       // default 60_000
}
```

### 12.2 `plan_excerpt` building rule (Step 2.3)

```ts
const maxChars = input.max_chars ?? 60_000;
const PLAN_EXCERPT_HARD_CAP = 12_000;
const limit = Math.min(PLAN_EXCERPT_HARD_CAP, Math.floor(maxChars * 0.4));

let plan_excerpt: string;
let plan_body_truncated: boolean;

if (input.plan_body && input.plan_body.length > 0) {
  const combined = `${input.title}\n\n${input.plan_body}`;
  if (combined.length <= limit) {
    plan_excerpt = combined;
    plan_body_truncated = false;
  } else {
    plan_excerpt = `${combined.slice(0, limit - 12)} [truncated]`;
    plan_body_truncated = true;
  }
} else {
  plan_excerpt = input.title;
  plan_body_truncated = false;
}
```

### 12.3 `allowed_exec_commands` building (Step 6.2)

```ts
const READ_ONLY_UTILITIES: ReadonlyArray<string> = [
  "ls", "cat", "head", "tail", "grep",
  "find . -name", "find . -type",
  "git status", "git diff", "git log --oneline -n",
  "node --test", "node -e",
  "bun test", "bun run check"
];

let allowed_exec_commands: string[] | null = null;
if (input.workspace) {
  const catalog = buildProjectScriptCatalog(input.workspace);
  allowed_exec_commands = [
    ...catalog.commands,
    ...input.verification_commands,
    ...READ_ONLY_UTILITIES
  ];
}
```

### 12.4 Modified packet contract (additive)

```ts
export interface WaygentTaskPacket {
  // ... existing fields ...
  allowed_exec_commands?: string[] | null;       // NEW typed (was implicit)
  plan_body_truncated?: boolean;                  // NEW
  previous_failures?: ReadonlyArray<{             // NEW (Task 1 retry context)
    failure_class: FailureClass;
    summary: string;
    attempt_number: number;
  }>;
  // context_budget unchanged:
  context_budget: { max_chars: number; ... };
}
```

---

## 13. M14 — `apps/cli/src/index.ts` (modified)

### 13.1 New flags (added to `runCli`'s flag parser)

| Flag | Type | Default | Applies to |
|------|------|---------|------------|
| `--profile` | `cost-saver \| balanced \| max-quality` | `balanced` (for `--provider claude`); provider-default otherwise | `run`, `run-chain` |
| `--inherit-plan-prose` | `on \| off` | `on` | `run`, `run-chain` |
| `--unsafe-verification` | bool flag | off | `run`, `run-chain` |
| `--reject-trivial-verify` | bool flag | off | `run`, `run-chain` |
| `--require-cost-data` | bool flag | off | `run`, `run-chain` |
| `--plan-adapter` | `superpowers \| native \| auto` | `auto` | `run`, `run-chain` |

### 13.2 Updated `commandUsage.run`

```
waygent run \
  --plan <waygent-task.md> [--spec <design.md>] \
  [--provider codex|claude|fake] \
  [--execution-mode multi-agent|single-agent] \
  [--plan-preflight off|deterministic|full] \
  [--plan-adapter superpowers|native|auto] \
  [--inherit-plan-prose on|off] \
  [--unsafe-verification] [--reject-trivial-verify] \
  [--main-model <name>] [--subagent-model <name>] \
  [--main-reasoning low|medium|high|xhigh] [--subagent-reasoning low|medium|high|xhigh] \
  [--profile cost-saver|balanced|max-quality] \
  [--run <id>] [--budget-cap <usd>] [--budget-action warn|pause|off] \
  [--require-cost-data] [--root <path>]
```

### 13.3 `resolveCliProfile` — new defaults

When `provider === "claude"` and no explicit `--main-model` /
`--subagent-model` / `--profile` flag is set:

```ts
profile.main_model           = "opus";
profile.main_reasoning       = "high";
profile.subagent_model       = "sonnet";
profile.subagent_reasoning   = "medium";
```

When `--profile balanced` is set with `provider === "claude"`: same as
above. With other profile values: see design §S7.4 table.

Invariant `I-CLI-1`: explicit `--main-model` / `--subagent-model` always
override `--profile` and provider defaults.

### 13.4 Collision-retry wrapper

```ts
async function runWithCollisionRetry(
  planPath: string,
  options: RunWaygentOptions,
  hasExplicitRunId: boolean
): Promise<WaygentRunResult> {
  if (hasExplicitRunId) {
    return runWaygent(options);
  }
  let attempt = 0;
  let baseId = deriveAutoRunId(planPath);
  while (true) {
    try {
      return await runWaygent({ ...options, run_id: attempt === 0 ? baseId : `${baseId}_${attempt + 1}` });
    } catch (err) {
      if (!(err instanceof Error) || err.message !== "run_id_already_exists") throw err;
      attempt += 1;
      if (attempt > 9) {
        throw new Error(`run_id_already_exists after 9 retries: ${baseId}`);
      }
    }
  }
}
```

Invariant `I-CLI-2`: collision retry is bounded at 9 attempts. After
the 10th collision, throw a clearly-labeled error.

### 13.5 `costRun` — zero-token warning

After building the cost ledger view, write to stderr when
`totals.input_tokens + totals.output_tokens === 0 && totals.dispatches > 0`:

```
WARN: cost ledger has 0 token usage across <N> dispatches. Provider
adapter may not be parsing usage. Inspect:
  artifacts/provider/*.stdout.txt (look for top-level "usage" key)
  events.jsonl (look for platform.cost_accumulated events with usage:null)
```

### 13.6 `--require-cost-data` fail-fast

When set, after each task dispatch, check the recorded
`ProviderRunMetadata.usage_source`. If
`usage_source === "missing_in_provider_output"` OR
`usage_source === "unknown"`, throw:

```ts
throw new Error(`cost_data_missing: task ${task_id} dispatch produced no usage telemetry`);
```

Emit `runway.cost_data_missing` event before throwing.

---

## 14. M15 — `contracts/src/types.ts` (modified additively)

### 14.1 `WaygentTaskPacket` — added optional fields

(Already specified in §12.4.)

### 14.2 `ProviderRunMetadata` — `usage_source` extension

```ts
export type UsageSource =
  | "provider_json"
  | "event_stream"
  | "missing_in_provider_output"   // NEW — envelope present, usage absent
  | "unknown";                      // legacy — no envelope at all
```

Invariant `I-USAGE-SRC-1`: `"missing_in_provider_output"` may only be
set when `metadataFromParsed` received `envelope !== null`.

---

## 15. M16 — `contracts/src/events.ts` (modified additively)

### 15.1 New event types

```ts
export type AgentLensEventType =
  // ... existing ~15 entries ...
  | "runway.recovery_attempt"
  | "runway.verification_quality_warning"
  | "runway.unsafe_verification_enabled"
  | "runway.dispatch_plan_echoed"
  | "runway.worker_permission_denied"
  | "runway.cost_data_missing";
```

### 15.2 Payload schemas

```ts
export interface RecoveryAttemptPayload {
  task_id: string;
  attempt_number: number;
  max_attempts: number;
  failure_class: FailureClass;
  recovery_action: RecoveryAction;
  prior_summary?: string;
}

export interface VerificationQualityWarningPayload {
  task_id: string;
  verify: ReadonlyArray<string>;
  reasons: ReadonlyArray<string>;   // e.g., ["all verify commands are trivial"]
}

export interface UnsafeVerificationEnabledPayload {
  run_id: string;
  reason: "cli_flag_set";
}

export interface DispatchPlanEchoedPayload {
  run_id: string;
  task_count: number;
  task_ids: ReadonlyArray<string>;
  provider: "codex" | "claude" | "fake";
  main: { model: string | null; reasoning: string | null; source: string };
  subagent: { model: string | null; reasoning: string | null; source: string };
  budget_cap_usd: number | null;
  expected_cost_estimate_usd: number;
  profile_name: string | null;   // "balanced" | "cost-saver" | "max-quality" | null
}

export interface WorkerPermissionDeniedPayload {
  task_id: string;
  attempted_command: string;
  tool_name: string;
  suggested_allowlist_entry: string;
}

export interface CostDataMissingPayload {
  task_id: string;
  usage_source: "missing_in_provider_output" | "unknown";
  dispatch_index: number;
}
```

### 15.3 Discriminated union

```ts
export type AgentLensEventPayload =
  | { event_type: "runway.recovery_attempt"; payload: RecoveryAttemptPayload }
  | { event_type: "runway.verification_quality_warning"; payload: VerificationQualityWarningPayload }
  | { event_type: "runway.unsafe_verification_enabled"; payload: UnsafeVerificationEnabledPayload }
  | { event_type: "runway.dispatch_plan_echoed"; payload: DispatchPlanEchoedPayload }
  | { event_type: "runway.worker_permission_denied"; payload: WorkerPermissionDeniedPayload }
  | { event_type: "runway.cost_data_missing"; payload: CostDataMissingPayload }
  // ... existing 15 entries ...
  ;
```

---

## 16. Cross-Cutting Invariants

`I-X-1` — **Additive only**: no field on `WaygentTaskPacket`,
`ProviderRunMetadata`, `AgentLensEnvelope`, `WaygentRunState` is
removed or has its type narrowed by this change.

`I-X-2` — **Compile gate on FailureClass exhaustion**: every place that
switches on `FailureClass` (recoveryExecutor's POLICY, taskExecutor's
retry switch, event payload type maps) MUST be exhaustive. Compile
error is the spec-mandated outcome when a new `FailureClass` is added
without updating these maps.

`I-X-3` — **Deterministic event ordering**: each task dispatch produces
`runway.dispatch_plan_echoed` exactly once (at task 1 start), and
within a single task: `runway.recovery_attempt` events (zero or more)
precede the final `runway.worker_result.v1`.

`I-X-4` — **Cost data presence under `--require-cost-data`**: at run
end, no `runway.cost_data_missing` event SHALL be present in
`events.jsonl` when the run terminated successfully. Failed runs may
have such events.

`I-X-5` — **Tmp-write safety**: no module writes to
`process.env.TMPDIR` or `os.tmpdir()` for run state by default. Worker
worktrees may still use tmpdir as before (out of scope for D-05).

---

## 17. Test Coverage Matrix (formal)

| Module | Required test cases |
|--------|--------------------|
| M01 `processAdapters` | `parseJsonText`: empty, raw JSON, json-fence, unlabeled fence, multi-fence (json wins), brace-span (largest wins), brace inside strings, no match → null. `unwrapProviderEnvelope`: direct `result`, depth-3 leaf, envelope returned. `metadataFromParsed`: envelope usage extracted, evidence-only fallback, neither present → missing_in_provider_output. `usageFromEnvelope` cache lenience. `isWorkerResultCandidate` AND-logic. |
| M02 `recoveryExecutor` | 29 cases (one per FailureClass) × {prior=0, prior=max-1, prior=max}; max_overrides applied; strict_prompt_suffix shape; halt vs. request_decision when exhausted. |
| M03 `planParser` | block-deps; inline-deps; pre-yaml prose captured; explicit yaml `instructions:` wins over prose. |
| M04 `planNormalizer` | fixture-lab plan accepted (with catalog); risk inference applied; verify-theater warning emitted; `--unsafe-verification` bypass. |
| M05 `projectScriptCatalog` | package.json/Makefile/pyproject.toml each independently; merge order; missing files non-throw; `isCommandInCatalog` exact vs. prefix vs. miss. |
| M06 `riskInference` | 6+ cases covering each rule branch. |
| M07 `verifyQuality` | trivial-only; mixed; no-claims; claims-no-match. |
| M08 `instructionsExtract` | pure move; existing tests in planNormalizer still pass. |
| M09 `runIdDerivation` | 4 examples in §8.1; sub-second collision counter. |
| M10 `taskExecutor` | retry executes; max bound respected; event emitted per retry. |
| M11 `orchestrator` | default platform paths (mocked `process.platform`); `runWaygent` derives run_id when absent. |
| M12 `orphanRuns` | dual-root merge; legacy entries flagged. |
| M13 `taskPacket` | plan_excerpt cap math at min/max boundaries; `allowed_exec_commands` union content; truncation marker present. |
| M14 `apps/cli` | each new flag parsed; help text contains all new flags; collision retry bounded at 9. |
| M15 `contracts/types` | TypeScript-only — compile-time exhaustiveness. |
| M16 `contracts/events` | payload schema parses sample fixtures. |

---

## 18. Conformance Gate

A `bun run check` script SHALL pass with these additions:

```bash
bun test packages/provider-adapters/tests \
         packages/orchestrator/tests \
         packages/context-packer/tests \
         apps/cli/tests
bun run waygent:scenarios
bun run check
git diff --check
```

End-to-end replay (acceptance): see plan §"Cross-cutting verification".

---

## 19. Open Questions (deferred — not in scope)

- **OQ-1**: claude `stream-json` envelope shape — fixture needed; if
  shape diverges from `--output-format json`, S6 envelope extractor
  needs a second mapping. Out of scope until fixture exists.
- **OQ-2**: codex envelope-level usage — already at
  `worker_result.evidence.usage`; no envelope path needed. Validated by
  M01 test "evidence-only fallback".
- **OQ-3**: sub-agent role bucketing in `costLedger.by_role` — partial
  today (`role: "implement"` vs `"review"`); per-call split is a
  follow-up sprint.
- **OQ-4**: plan-adapter externalization (`@waygent/plan-adapters` as
  separate package) — design §S12 keeps it internal; revisit when a
  third adapter is needed.

---

## 20. Document Conventions

- TypeScript snippets are **normative**. Implementations may add helper
  types but the exported shapes shown here are the contract.
- Where a snippet uses `// ...` it means *the rest of the existing type
  is preserved unchanged*. It does NOT mean "implementer fills in."
- Invariants are named `I-<scope>-<n>` and are testable. Each test in
  §17 SHOULD label which invariant(s) it covers.
- `[D-NN]` cross-references point to the analysis document.
  `[S-NN]` cross-references point to the original design spec.
