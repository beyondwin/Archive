# Waygent Fixture-Lab Defect Remediation — Detailed Implementation Guide

Date: 2026-05-22
Status: Code-level implementation companion to
`2026-05-22-waygent-fixture-lab-defect-remediation.md` (plan) and
`2026-05-22-waygent-fixture-lab-detailed-spec.md` (contract spec)

This document is the **executable** companion to the plan. Where the
plan tells you *what* to do task-by-task, this document tells you
*exactly* what to write — file paths, line numbers, before/after diffs,
complete new-file contents, fixture extraction commands, and the
recommended commit sequence.

An implementer should be able to follow this top-to-bottom and arrive
at a passing `bun run check` + green `bun run waygent:scenarios`
without consulting external context, with two exceptions:

1. The literal stdout artifact bytes for the D-09 fixture must be
   copied from disk (§F1 has the command).
2. The CME comparison data and the existing source code itself.

> **Reading order:** read this top-to-bottom on first pass. On
> subsequent passes (e.g., resuming after interruption), navigate by
> the §T1 .. §T7 section anchors.

---

## §F1 — Fixture Extraction (do this FIRST)

The D-09 regression test depends on the literal failed-run stdout bytes
sitting in `/var/folders/.../T/waygent-runs/...`. Because macOS
periodically clears `/var/folders/.../T/`, capture the bytes
immediately:

```bash
cd /Users/kws/source/private/Archive

# Confirm the source is still present and the byte count matches.
wc -c /var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/waygent-runs/trustworthy_fixture_lab_wg_20260522_200031/artifacts/provider/attempt_task_3_fixture_preparation_and_gradle_injection_1.stdout.txt
# Expected: 7884 <path>

mkdir -p packages/provider-adapters/tests/fixtures

# Copy with no transformation (binary-safe).
cp \
  /var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/waygent-runs/trustworthy_fixture_lab_wg_20260522_200031/artifacts/provider/attempt_task_3_fixture_preparation_and_gradle_injection_1.stdout.txt \
  packages/provider-adapters/tests/fixtures/claude_task_3_narrative_then_json.stdout.txt

# Also copy the task_packet artifact for §T2 / §T6 tests.
cp \
  /var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/waygent-runs/trustworthy_fixture_lab_wg_20260522_200031/artifacts/task_packets/*task_3*.json \
  packages/context-packer/tests/fixtures/task_3_packet_baseline.json

# And the events.jsonl excerpt for §T1 retry-event assertions.
mkdir -p packages/orchestrator/tests/fixtures
cp \
  /var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/waygent-runs/trustworthy_fixture_lab_wg_20260522_200031/events.jsonl \
  packages/orchestrator/tests/fixtures/events_failed_run_baseline.jsonl
```

After this step, every regression test is reproducible from the
checked-in tree even if `/var/folders/.../T/` is reaped.

Additionally, copy the upstream FixThis plan/spec for §T3 tests:

```bash
cp /Users/kws/source/android/FixThis/docs/superpowers/plans/2026-05-20-trustworthy-source-matching-local-fixture-lab.md \
   packages/orchestrator/tests/fixtures/fixture_lab_plan.md

cp /Users/kws/source/android/FixThis/docs/superpowers/specs/2026-05-20-trustworthy-source-matching-local-fixture-lab-design.md \
   packages/orchestrator/tests/fixtures/fixture_lab_design.md
```

---

## §F2 — Source Tree Map (touched by this remediation)

```
apps/cli/src/index.ts                                       (modified)
apps/cli/tests/profilePreset.test.ts                         (new)
apps/cli/tests/runIdAutoGen.test.ts                          (new)
apps/cli/tests/collisionRetry.test.ts                        (new)

packages/contracts/src/types.ts                              (modified, additive)
packages/contracts/src/events.ts                             (modified, additive)

packages/context-packer/src/taskPacket.ts                   (modified)
packages/context-packer/tests/taskPacket.planExcerpt.test.ts  (new)
packages/context-packer/tests/taskPacket.execAllowlist.test.ts (new)
packages/context-packer/tests/fixtures/task_3_packet_baseline.json  (copied)

packages/orchestrator/src/orchestrator.ts                    (modified)
packages/orchestrator/src/orphanRuns.ts                      (modified)
packages/orchestrator/src/planParser.ts                       (modified)
packages/orchestrator/src/planNormalizer.ts                   (modified)
packages/orchestrator/src/taskExecutor.ts                     (modified)
packages/orchestrator/src/recoveryExecutor.ts                 (new)
packages/orchestrator/src/runIdDerivation.ts                  (new)
packages/orchestrator/src/planAdapters/projectScriptCatalog.ts (new)
packages/orchestrator/src/planAdapters/riskInference.ts        (new)
packages/orchestrator/src/planAdapters/verifyQuality.ts        (new)
packages/orchestrator/src/planAdapters/instructionsExtract.ts  (new — moved)

packages/orchestrator/tests/recoveryExecutor.test.ts          (new)
packages/orchestrator/tests/runIdDerivation.test.ts           (new)
packages/orchestrator/tests/planParser.deps.test.ts           (new)
packages/orchestrator/tests/planParser.bodyPropagation.test.ts (new)
packages/orchestrator/tests/projectScriptCatalog.test.ts      (new)
packages/orchestrator/tests/riskInference.test.ts             (new)
packages/orchestrator/tests/planNormalizer.fixtureLab.test.ts (new)
packages/orchestrator/tests/defaultRunRoot.test.ts            (new)
packages/orchestrator/tests/fixtures/fixture_lab_plan.md       (copied)
packages/orchestrator/tests/fixtures/fixture_lab_design.md     (copied)
packages/orchestrator/tests/fixtures/events_failed_run_baseline.jsonl (copied)

packages/provider-adapters/src/processAdapters.ts             (modified)
packages/provider-adapters/tests/parseWorkerOutput.test.ts     (new)
packages/provider-adapters/tests/usageExtraction.test.ts       (new)
packages/provider-adapters/tests/fixtures/claude_task_3_narrative_then_json.stdout.txt (copied)
packages/provider-adapters/tests/fixtures/synthetic_minimal.stdout.txt (new)

docs/operations/state-root-migration.md                       (new)
```

---

## §T1 — Task 1: Parser Hardening + Recovery [D-09, D-10]

### §T1.1 — Modify `packages/provider-adapters/src/processAdapters.ts`

**Source as of audit (line numbers from `processAdapters.ts:234–360`):**

The current `parseWorkerOutput`, `parseJsonText`, `unwrapProviderEnvelope`,
`isWorkerResultCandidate`, and `metadataFromParsed` are listed in the
design spec §S1.1 trace. Apply this patch:

#### Patch 1.1.a — `isWorkerResultCandidate` (lines 279–283)

```diff
 function isWorkerResultCandidate(value: unknown): value is Partial<WorkerResult> {
   if (!value || typeof value !== "object" || Array.isArray(value)) return false;
   const record = value as Record<string, unknown>;
-  return "status" in record || "changed_files" in record || "summary" in record || "failure_class" in record;
+  if (!("status" in record)) return false;
+  return "changed_files" in record || "summary" in record || "evidence" in record;
 }
```

#### Patch 1.1.b — `parseJsonText` (lines ~285–305) — full replacement

Replace the current `parseJsonText` body with:

```ts
function parseJsonText(value: string): unknown | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;

  // (1) Direct.
  const direct = tryParseJson(trimmed);
  if (direct && isWorkerResultCandidate(direct)) return direct;

  // (2) All fenced blocks; json-labeled first, then unlabeled, then other.
  const allFences = [...trimmed.matchAll(/```(\w+)?\s*([\s\S]*?)```/g)];
  const ordered = [
    ...allFences.filter((m) => m[1]?.toLowerCase() === "json"),
    ...allFences.filter((m) => !m[1]),
    ...allFences.filter((m) => m[1] && m[1].toLowerCase() !== "json")
  ];
  for (const match of ordered) {
    const candidate = tryParseJson((match[2] ?? "").trim());
    if (candidate && isWorkerResultCandidate(candidate)) return candidate;
  }

  // (3) Balanced brace spans, largest first.
  for (const span of enumerateBalancedBraceSpans(trimmed)) {
    const candidate = tryParseJson(span);
    if (candidate && isWorkerResultCandidate(candidate)) return candidate;
  }

  // (4) Legacy fallback: direct parse return even if not worker-shaped.
  return direct;
}

function* enumerateBalancedBraceSpans(text: string): Generator<string> {
  type Span = { start: number; end: number };
  const spans: Span[] = [];
  let i = 0;
  while (i < text.length) {
    if (text.charCodeAt(i) !== 0x7b /* '{' */) {
      i += 1;
      continue;
    }
    const start = i;
    let depth = 0;
    let inString = false;
    let escaped = false;
    while (i < text.length) {
      const ch = text.charCodeAt(i);
      if (escaped) {
        escaped = false;
        i += 1;
        continue;
      }
      if (inString) {
        if (ch === 0x5c /* '\' */) escaped = true;
        else if (ch === 0x22 /* '"' */) inString = false;
        i += 1;
        continue;
      }
      if (ch === 0x22 /* '"' */) {
        inString = true;
        i += 1;
        continue;
      }
      if (ch === 0x7b /* '{' */) depth += 1;
      else if (ch === 0x7d /* '}' */) {
        depth -= 1;
        if (depth === 0) {
          spans.push({ start, end: i + 1 });
          i += 1;
          break;
        }
      }
      i += 1;
    }
    if (depth > 0) return;  // unterminated; bail
  }
  spans.sort((a, b) => b.end - b.start - (a.end - a.start));
  for (const s of spans) yield text.slice(s.start, s.end);
}
```

#### Patch 1.1.c — `unwrapProviderEnvelope` (lines 253–278) — full replacement

```ts
export interface UnwrappedEnvelope {
  unwrapped: unknown;
  envelope: unknown | null;
}

export function unwrapProviderEnvelope(parsed: unknown): UnwrappedEnvelope {
  if (!parsed || typeof parsed !== "object") return { unwrapped: parsed, envelope: null };
  const envelope = parsed;
  const directPaths: ReadonlyArray<ReadonlyArray<string>> = [
    ["result"], ["message"], ["text"], ["item", "text"]
  ];
  for (const path of directPaths) {
    const nested = readPath(parsed as Record<string, unknown>, path);
    if (typeof nested === "string") {
      const candidate = parseJsonText(nested);
      if (candidate && isWorkerResultCandidate(candidate)) {
        return { unwrapped: candidate, envelope };
      }
    }
  }
  for (const leaf of stringLeaves(parsed, 3)) {
    const candidate = parseJsonText(leaf);
    if (candidate && isWorkerResultCandidate(candidate)) {
      return { unwrapped: candidate, envelope };
    }
  }
  return { unwrapped: parsed, envelope: null };
}

function readPath(obj: Record<string, unknown>, path: ReadonlyArray<string>): unknown {
  let cur: unknown = obj;
  for (const seg of path) {
    if (!cur || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[seg];
  }
  return cur;
}

function* stringLeaves(value: unknown, maxDepth: number, depth = 0): Generator<string> {
  if (depth > maxDepth) return;
  if (typeof value === "string") {
    if (value.length > 0) yield value;
    return;
  }
  if (Array.isArray(value)) {
    for (const v of value) yield* stringLeaves(v, maxDepth, depth + 1);
    return;
  }
  if (value && typeof value === "object") {
    for (const v of Object.values(value)) yield* stringLeaves(v, maxDepth, depth + 1);
  }
}
```

#### Patch 1.1.d — `parseWorkerOutput` (lines 234–251) — adjust to consume new return type

```diff
 function parseWorkerOutput(stdout: string): unknown {
   const trimmed = stdout.trim();
   const candidates = [
     trimmed,
     ...trimmed
       .split(/\r?\n/)
       .map((line) => line.trim())
       .filter(Boolean)
       .reverse()
   ];
   for (const candidate of candidates) {
     const parsed = parseJsonText(candidate);
     if (!parsed) continue;
-    const unwrapped = unwrapProviderEnvelope(parsed);
+    const { unwrapped } = unwrapProviderEnvelope(parsed);
     if (isWorkerResultCandidate(unwrapped)) return unwrapped;
   }
   throw new Error("missing worker result JSON");
 }
```

#### Patch 1.1.e — Wire envelope through to `metadataFromParsed`

Locate the call site in `normalizeProcessOutput` (search for
`metadataFromParsed(provider`). Today:

```ts
const parsed = parseWorkerOutput(stdout);
const metadata = metadataFromParsed(provider, parsed);
```

Change `parseWorkerOutput` to also return the envelope, OR refactor
`normalizeProcessOutput` to call `unwrapProviderEnvelope` itself.
The cleaner option is option B:

```ts
// In normalizeProcessOutput:
const directJson = parseDirectJson(stdout);   // raw envelope (NEW helper)
const { unwrapped, envelope } = directJson
  ? unwrapProviderEnvelope(directJson)
  : { unwrapped: parseWorkerOutput(stdout), envelope: null };
const worker = unwrapped as Partial<WorkerResult>;
const metadata = metadataFromParsed(provider, worker, envelope);
```

Where `parseDirectJson` is a new tiny helper:

```ts
function parseDirectJson(stdout: string): unknown | null {
  const trimmed = stdout.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}
```

This keeps `parseWorkerOutput`'s contract for cases where the envelope
is not JSON-shaped (codex JSONL stream).

#### Patch 1.1.f — `metadataFromParsed` (lines 310–317) — add envelope param

```diff
-function metadataFromParsed(provider: "codex" | "claude" | "acp", parsed: Partial<WorkerResult>): ProviderRunMetadata {
+function metadataFromParsed(
+  provider: "codex" | "claude" | "acp",
+  parsed: Partial<WorkerResult>,
+  envelope: unknown | null
+): ProviderRunMetadata {
   const evidence = parsed.evidence && typeof parsed.evidence === "object" ? parsed.evidence as Record<string, unknown> : {};
+  const envelopeUsage = usageFromEnvelope(envelope);
+  const envelopeModel = modelFromEnvelope(envelope, provider);
   return {
-    actual_model: actualModelFromEvidence(evidence),
-    usage: usageFromEvidence(evidence),
-    usage_source: usageSourceFromEvidence(evidence, provider)
+    actual_model: envelopeModel ?? actualModelFromEvidence(evidence),
+    usage: envelopeUsage ?? usageFromEvidence(evidence),
+    usage_source: envelopeUsage
+      ? "provider_json"
+      : usageFromEvidence(evidence)
+        ? usageSourceFromEvidence(evidence, provider)
+        : envelope !== null
+          ? "missing_in_provider_output"
+          : "unknown"
   };
 }
```

#### Patch 1.1.g — New helpers: `usageFromEnvelope`, `modelFromEnvelope`

Append after `metadataFromParsed`:

```ts
function usageFromEnvelope(envelope: unknown): TokenUsage | null {
  if (!envelope || typeof envelope !== "object") return null;
  const root = envelope as Record<string, unknown>;
  const u = root.usage;
  if (!u || typeof u !== "object") return null;
  const r = u as Record<string, unknown>;
  const input = numberField(r.input_tokens);
  const output = numberField(r.output_tokens);
  if (input === null || output === null) return null;
  return {
    input_tokens: input,
    output_tokens: output,
    cached_read_tokens: numberField(r.cache_read_input_tokens) ?? 0,
    cached_write_tokens: numberField(r.cache_creation_input_tokens) ?? 0
  };
}

function modelFromEnvelope(
  envelope: unknown,
  _provider: "codex" | "claude" | "acp"
): { model: string | null; reasoning: string | null; source: "provider_json" } | null {
  if (!envelope || typeof envelope !== "object") return null;
  const root = envelope as Record<string, unknown>;
  const mu = root.modelUsage;
  if (!mu || typeof mu !== "object") return null;
  const keys = Object.keys(mu as Record<string, unknown>);
  if (keys.length === 0) return null;
  return { model: keys[0]!, reasoning: null, source: "provider_json" };
}
```

#### Patch 1.1.h — `buildProviderPrompt` (lines 216–232)

```diff
 export function buildProviderPrompt(provider: "codex" | "claude", request: AdapterRequest): string {
+  const allowedExec = request.task_packet?.allowed_exec_commands;
+  const allowedBlock = Array.isArray(allowedExec) && allowedExec.length > 0
+    ? [
+        "You may invoke these commands during self-verification (others will be denied):",
+        ...allowedExec.map((c) => `  ${c}`),
+        "You SHOULD invoke the verification commands listed in task_packet.acceptance_commands before returning status:completed."
+      ]
+    : [];
   return [
     `You are the ${provider} worker for a Waygent task.`,
     `role: ${request.role ?? "implement"}`,
     `task_id: ${request.task_id}`,
     `candidate_id: ${request.candidate_id}`,
     request.task_packet_path ? `task_packet_path: ${request.task_packet_path}` : "task_packet_path: none",
     "Return only one JSON object matching runway.worker_result.v1 unless the provider wrapper emits JSONL envelopes.",
     "Do not write AgentLens events directly.",
     "Do not apply changes to the source checkout.",
     "Edit only the isolated Waygent worktree.",
     "Obey the task packet write policy.",
     "Required JSON fields: schema, task_id, candidate_id, status, changed_files, summary, evidence.",
+    ...allowedBlock,
     "Task prompt:",
     request.prompt
   ].join("\n");
 }
```

#### Patch 1.1.i — `permission_denials` event emission

In `normalizeProcessOutput`, after envelope is captured:

```ts
if (envelope && typeof envelope === "object") {
  const denials = (envelope as Record<string, unknown>).permission_denials;
  if (Array.isArray(denials)) {
    for (const denial of denials) {
      if (!denial || typeof denial !== "object") continue;
      const d = denial as Record<string, unknown>;
      const input = (d.tool_input ?? {}) as Record<string, unknown>;
      const cmd = typeof input.command === "string" ? input.command : "";
      if (!cmd) continue;
      pendingEvents.push({
        event_type: "runway.worker_permission_denied",
        payload: {
          task_id: request.task_id,
          attempted_command: cmd,
          tool_name: typeof d.tool_name === "string" ? d.tool_name : "Bash",
          suggested_allowlist_entry: cmd.split(/\s+/)[0] ?? cmd
        }
      });
    }
  }
}
```

`pendingEvents` is a new local accumulator returned from
`normalizeProcessOutput` and emitted by the caller in `taskExecutor`.

### §T1.2 — Create `packages/orchestrator/src/recoveryExecutor.ts`

```ts
import type { FailureClass } from "@waygent/contracts";

export type RecoveryAction =
  | "retry_with_strict_prompt"
  | "retry_with_evidence"
  | "request_decision"
  | "halt";

export interface PolicyEntry {
  action: RecoveryAction;
  max_attempts: number;
}

export interface NextRecoveryActionInput {
  failure_class: FailureClass;
  prior_attempts: number;
  prior_summary?: string;
  max_overrides?: Partial<Record<FailureClass, number>>;
}

export interface RecoveryDecision {
  failure_class: FailureClass;
  attempt_number: number;
  max_attempts: number;
  action: RecoveryAction;
  strict_prompt_suffix?: string;
}

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

export function nextRecoveryAction(input: NextRecoveryActionInput): RecoveryDecision {
  const entry = RECOVERY_POLICY[input.failure_class];
  const maxAttempts = input.max_overrides?.[input.failure_class] ?? entry.max_attempts;
  const attemptNumber = input.prior_attempts + 1;

  if (input.prior_attempts >= maxAttempts) {
    return {
      failure_class: input.failure_class,
      attempt_number: attemptNumber,
      max_attempts: maxAttempts,
      action: entry.action === "halt" ? "halt" : "request_decision"
    };
  }

  const decision: RecoveryDecision = {
    failure_class: input.failure_class,
    attempt_number: attemptNumber,
    max_attempts: maxAttempts,
    action: entry.action
  };
  if (entry.action === "retry_with_strict_prompt") {
    decision.strict_prompt_suffix = buildStrictPromptSuffix({
      failure_class: input.failure_class,
      attempt_number: attemptNumber,
      prior_summary: input.prior_summary
    });
  }
  return decision;
}

function buildStrictPromptSuffix(input: {
  failure_class: FailureClass;
  attempt_number: number;
  prior_summary?: string;
}): string {
  const summary = (input.prior_summary ?? "(none recorded)").slice(0, 240);
  return [
    `PRIOR ATTEMPT (#${input.attempt_number - 1}) FAILED.`,
    `failure_class: ${input.failure_class}`,
    `prior_summary: ${summary}`,
    "",
    "You MUST respond with ONLY a single fenced ```json block containing the",
    "runway.worker_result.v1 object. Required fields: schema, task_id,",
    "candidate_id, status, changed_files, summary, evidence. No prose before",
    "or after the fence. No additional fenced blocks of any language."
  ].join("\n");
}
```

### §T1.3 — Wire retry into `packages/orchestrator/src/taskExecutor.ts`

Locate the function that executes a single task (currently a one-shot
dispatch). Replace its body with the retry loop. The exact patch
depends on the current function name (`executeWaygentTask` or similar);
the structural change is:

```ts
import { nextRecoveryAction, type RecoveryDecision } from "./recoveryExecutor.js";

async function executeWaygentTask(
  task: NormalizedWaygentTask,
  baseRequest: AdapterRequest,
  runContext: RunContext
): Promise<TaskAttempts> {
  const attempts: AdapterAttemptResult[] = [];
  let packet = baseRequest.task_packet;

  while (true) {
    const request: AdapterRequest = { ...baseRequest, task_packet: packet };
    const result = await runContext.adapter.dispatch(request);
    attempts.push(result);

    if (result.worker.status === "completed" && !result.worker.failure_class) {
      break;
    }

    const failureClass = result.worker.failure_class ?? "malformed_result";
    const decision = nextRecoveryAction({
      failure_class: failureClass as FailureClass,
      prior_attempts: attempts.length,
      prior_summary: result.worker.summary
    });

    await runContext.events.emit({
      event_type: "runway.recovery_attempt",
      payload: {
        task_id: task.id,
        attempt_number: decision.attempt_number,
        max_attempts: decision.max_attempts,
        failure_class: decision.failure_class,
        recovery_action: decision.action,
        prior_summary: result.worker.summary
      }
    });

    if (decision.action === "halt" || decision.action === "request_decision") {
      break;
    }

    packet = {
      ...packet,
      previous_failures: [
        ...(packet?.previous_failures ?? []),
        {
          failure_class: decision.failure_class,
          summary: result.worker.summary ?? "",
          attempt_number: decision.attempt_number - 1
        }
      ]
    };

    if (decision.action === "retry_with_strict_prompt" && decision.strict_prompt_suffix) {
      packet = { ...packet, strict_prompt_suffix: decision.strict_prompt_suffix };
    }
  }

  return { attempts, final_status: deriveFinalStatus(attempts) };
}
```

The `strict_prompt_suffix` field is consumed by `buildProviderPrompt`
(append to prompt body when set). Add to `WaygentTaskPacket` interface
in `contracts/src/types.ts`:

```ts
strict_prompt_suffix?: string;   // internal — consumed by buildProviderPrompt
```

### §T1.4 — Test: `packages/provider-adapters/tests/parseWorkerOutput.test.ts`

```ts
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { normalizeProcessOutput } from "../src/processAdapters.js";

const FIXTURE_DIR = join(import.meta.dir, "fixtures");

describe("parseWorkerOutput — claude narrative wrapping fenced json", () => {
  test("extracts worker_result from D-09 task_3 fixture (7884 bytes)", () => {
    const stdout = readFileSync(
      join(FIXTURE_DIR, "claude_task_3_narrative_then_json.stdout.txt"),
      "utf8"
    );
    expect(stdout.length).toBeGreaterThan(7000);  // sanity

    const result = normalizeProcessOutput("claude", "task_3_fixture", "cand_1", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false,
      startedAt: "2026-05-22T20:02:51.000Z",
      completedAt: "2026-05-22T20:12:54.000Z"
    });

    expect(result.worker.status).toBe("complete");
    expect(result.worker.failure_class).toBeUndefined();
    expect(result.worker.changed_files).toBeDefined();
    expect(result.metadata.usage).not.toBeNull();
    expect(result.metadata.usage?.output_tokens).toBeGreaterThan(0);
    expect(result.metadata.usage_source).toBe("provider_json");
    expect(result.metadata.actual_model?.model).toContain("claude");
  });

  test("rejects empty stdout", () => {
    const result = normalizeProcessOutput("claude", "task_x", "cand_1", {
      exitCode: 0, stdout: "", stderr: "", timedOut: false,
      startedAt: "now", completedAt: "now"
    });
    expect(result.worker.status).toBe("failed");
    expect(result.worker.failure_class).toBe("malformed_result");
  });

  test("synthetic minimal envelope with raw worker_result", () => {
    const stdout = JSON.stringify({
      type: "result",
      result: '```json\n{"schema":"runway.worker_result.v1","task_id":"t","candidate_id":"c","status":"complete","changed_files":["a.ts"],"summary":"ok","evidence":{}}\n```',
      usage: { input_tokens: 100, output_tokens: 200 }
    });
    const result = normalizeProcessOutput("claude", "t", "c", {
      exitCode: 0, stdout, stderr: "", timedOut: false,
      startedAt: "now", completedAt: "now"
    });
    expect(result.worker.status).toBe("complete");
    expect(result.metadata.usage?.input_tokens).toBe(100);
  });

  test("multi-fence: json-labeled wins over bash fence", () => {
    const stdout = JSON.stringify({
      type: "result",
      result: 'See ```bash\necho hi\n```\nResult:\n```json\n{"status":"complete","changed_files":[],"summary":"ok","evidence":{}}\n```'
    });
    const result = normalizeProcessOutput("claude", "t", "c", {
      exitCode: 0, stdout, stderr: "", timedOut: false,
      startedAt: "now", completedAt: "now"
    });
    expect(result.worker.status).toBe("complete");
  });
});
```

### §T1.5 — Test: `packages/orchestrator/tests/recoveryExecutor.test.ts`

```ts
import { describe, expect, test } from "bun:test";
import { nextRecoveryAction, RECOVERY_POLICY } from "../src/recoveryExecutor.js";
import type { FailureClass } from "@waygent/contracts";

describe("recoveryExecutor — policy matrix exhaustiveness", () => {
  const ALL_CLASSES = Object.keys(RECOVERY_POLICY) as FailureClass[];

  test("covers all 29 FailureClass entries", () => {
    expect(ALL_CLASSES.length).toBe(29);
  });

  for (const fc of ALL_CLASSES) {
    test(`policy entry for ${fc} is well-formed`, () => {
      const entry = RECOVERY_POLICY[fc];
      expect(entry.action).toMatch(/^(retry_with_strict_prompt|retry_with_evidence|request_decision|halt)$/);
      expect(entry.max_attempts).toBeGreaterThanOrEqual(0);
      if (entry.action === "halt") expect(entry.max_attempts).toBe(0);
    });
  }
});

describe("recoveryExecutor — decision logic", () => {
  test("malformed_result first attempt → retry_with_strict_prompt", () => {
    const d = nextRecoveryAction({ failure_class: "malformed_result", prior_attempts: 0 });
    expect(d.action).toBe("retry_with_strict_prompt");
    expect(d.max_attempts).toBe(2);
    expect(d.attempt_number).toBe(1);
    expect(d.strict_prompt_suffix).toContain("PRIOR ATTEMPT (#0) FAILED");
  });

  test("malformed_result after 2 attempts → request_decision", () => {
    const d = nextRecoveryAction({ failure_class: "malformed_result", prior_attempts: 2 });
    expect(d.action).toBe("request_decision");
  });

  test("cancelled always halts", () => {
    const d0 = nextRecoveryAction({ failure_class: "cancelled", prior_attempts: 0 });
    expect(d0.action).toBe("halt");
  });

  test("max_overrides apply", () => {
    const d = nextRecoveryAction({
      failure_class: "verification_failed",
      prior_attempts: 2,
      max_overrides: { verification_failed: 5 }
    });
    expect(d.action).toBe("retry_with_evidence");
    expect(d.max_attempts).toBe(5);
  });
});
```

---

## §T2 — Task 2: Plan Body Propagation [D-06]

### §T2.1 — Create `packages/orchestrator/src/planAdapters/instructionsExtract.ts`

Move (don't reimplement) the function from `planNormalizer.ts:182–193`:

```ts
const RUN_BLOCK = /Run:\n```bash\n([\s\S]*?)\n```/g;

function logicalCommandLines(rawCommands: string): string[] {
  return rawCommands
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+$/, ""))
    .filter((line) => line.trim().length > 0);
}

function isProviderInstructionCommand(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return false;
  return !/^git\s+(add|commit|push|reset|checkout|merge|rebase|stash|cherry-pick)\b/.test(trimmed);
}

export function extractInstructionLines(section: string): string[] {
  const normalized = section.replace(RUN_BLOCK, (_block, rawCommands: string) => {
    const implementationCommands = logicalCommandLines(rawCommands).filter(isProviderInstructionCommand);
    if (implementationCommands.length === 0) return "";
    return ["Run:", "```bash", ...implementationCommands, "```"].join("\n");
  });
  return normalized
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.trim().length > 0)
    .slice(0, 160);
}
```

Then in `planNormalizer.ts`, replace the local `extractInstructionLines`
with `import { extractInstructionLines } from "./planAdapters/instructionsExtract.js";`.

### §T2.2 — Modify `packages/orchestrator/src/planParser.ts`

Add prose-capture between section heading and yaml fence:

```ts
import { extractInstructionLines } from "./planAdapters/instructionsExtract.js";

const TASK_HEADING = /^(#{2,3})\s+Task\s+\d+\s*[:.]/gm;
// existing: const TASK_BLOCK = /```yaml\s+waygent-task\r?\n([\s\S]*?)\r?\n```/g;

export function parseWaygentPlan(markdown: string, options?: { inherit_plan_prose?: boolean }): ParsedWaygentTask[] {
  const inheritProse = options?.inherit_plan_prose !== false;
  const headings: Array<{ index: number }> = [];
  for (const m of markdown.matchAll(TASK_HEADING)) {
    if (m.index !== undefined) headings.push({ index: m.index + m[0].length });
  }

  const tasks: ParsedWaygentTask[] = [];
  let lastBlockEnd = 0;
  for (const m of markdown.matchAll(TASK_BLOCK)) {
    if (m.index === undefined) continue;
    const blockStart = m.index;
    const yamlBody = m[1] ?? "";
    const task = parseTaskBlock(yamlBody);

    if (inheritProse && (task.instructions ?? []).length === 0) {
      // Find the heading immediately before this block (between lastBlockEnd and blockStart).
      const headingBefore = [...headings]
        .reverse()
        .find((h) => h.index > lastBlockEnd && h.index < blockStart);
      if (headingBefore) {
        const proseSlice = markdown.slice(headingBefore.index, blockStart);
        task.instructions = extractInstructionLines(proseSlice);
      }
    }

    tasks.push(task);
    lastBlockEnd = blockStart + m[0].length;
  }
  return tasks;
}
```

### §T2.3 — Add block-list `dependencies` parsing (D-02 piggyback)

In `parseTaskBlock`, when encountering `dependencies:`:

```ts
if (line === "dependencies:" || /^dependencies:\s*$/.test(line)) {
  const deps: string[] = [];
  index = readStringList(lines, index + 1, deps) - 1;
  scalar.set("dependencies", `[${deps.join(", ")}]`);
  continue;
}
if (line.startsWith("dependencies:")) {
  const value = line.slice("dependencies:".length).trim();
  if (value.startsWith("[")) {
    scalar.set("dependencies", value);
  } else {
    // Single bare token, e.g. "dependencies: task_1"
    scalar.set("dependencies", `[${value}]`);
  }
  continue;
}
```

### §T2.4 — Modify `packages/context-packer/src/taskPacket.ts`

Replace the existing `plan_excerpt: input.plan_excerpt` line with the
cap logic from the detailed spec §12.2:

```diff
 export function buildTaskPacket(input: BuildTaskPacketInput): WaygentTaskPacket {
-  const maxChars = input.max_chars ?? 60000;
+  const maxChars = input.max_chars ?? 60_000;
+  const PLAN_EXCERPT_HARD_CAP = 12_000;
+  const planLimit = Math.min(PLAN_EXCERPT_HARD_CAP, Math.floor(maxChars * 0.4));
+
+  let plan_excerpt: string;
+  let plan_body_truncated = false;
+  if (input.plan_body && input.plan_body.length > 0) {
+    const combined = `${input.title}\n\n${input.plan_body}`;
+    if (combined.length <= planLimit) {
+      plan_excerpt = combined;
+    } else {
+      plan_excerpt = `${combined.slice(0, Math.max(0, planLimit - 12))} [truncated]`;
+      plan_body_truncated = true;
+    }
+  } else {
+    plan_excerpt = input.title;
+  }
+
   const base: Omit<WaygentTaskPacket, "context_budget" | "sha256"> = {
     // ... existing fields, but replace plan_excerpt: input.plan_excerpt
-    plan_excerpt: input.plan_excerpt,
+    plan_excerpt,
+    plan_body_truncated,
     // ...
```

Add `plan_body?: string` to `BuildTaskPacketInput`. Add
`plan_body_truncated?: boolean` to `WaygentTaskPacket` in contracts.

### §T2.5 — Tests

`packages/orchestrator/tests/planParser.bodyPropagation.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { parseWaygentPlan } from "../src/planParser.js";

const FIXTURE_WITH_PROSE = `
## Task 3: Implement Feature

Some context paragraph.

Step 1: Do this thing.
- bullet line one
- bullet line two

Step 2: Then this thing.

\`\`\`yaml waygent-task
id: task_3
title: implement feature
dependencies: []
file_claims:
  - path: src/**
    mode: owned
verify:
  - bun test
risk: medium
\`\`\`
`;

describe("planParser — body propagation", () => {
  test("captures pre-yaml prose into instructions when yaml has no instructions", () => {
    const tasks = parseWaygentPlan(FIXTURE_WITH_PROSE);
    expect(tasks).toHaveLength(1);
    expect(tasks[0]!.instructions.join("\n")).toContain("Step 1: Do this thing");
    expect(tasks[0]!.instructions.join("\n")).toContain("Step 2: Then this thing");
  });

  test("inherit_plan_prose=false disables capture", () => {
    const tasks = parseWaygentPlan(FIXTURE_WITH_PROSE, { inherit_plan_prose: false });
    expect(tasks[0]!.instructions).toEqual([]);
  });
});
```

`packages/orchestrator/tests/planParser.deps.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { parseWaygentPlan } from "../src/planParser.js";

const INLINE = `\`\`\`yaml waygent-task
id: t1
title: x
dependencies: [task_a, task_b]
file_claims:
  - path: a
    mode: owned
verify: [printf hi]
risk: low
\`\`\``;

const BLOCK = `\`\`\`yaml waygent-task
id: t1
title: x
dependencies:
  - task_a
  - task_b
file_claims:
  - path: a
    mode: owned
verify: [printf hi]
risk: low
\`\`\``;

describe("planParser — dependencies dual form", () => {
  test("inline list parses", () => {
    const tasks = parseWaygentPlan(INLINE);
    expect(tasks[0]!.dependencies).toEqual(["task_a", "task_b"]);
  });

  test("block list parses identically", () => {
    const tasks = parseWaygentPlan(BLOCK);
    expect(tasks[0]!.dependencies).toEqual(["task_a", "task_b"]);
  });
});
```

`packages/context-packer/tests/taskPacket.planExcerpt.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { buildTaskPacket } from "../src/taskPacket.js";

describe("buildTaskPacket — plan_excerpt cap", () => {
  test("title-only when no plan_body", () => {
    const p = buildTaskPacket({
      title: "Hello",
      plan_excerpt: "ignored",
      spec_excerpt: "",
      verification_commands: [],
      file_claims: []
    } as any);
    expect(p.plan_excerpt).toBe("Hello");
    expect(p.plan_body_truncated).toBe(false);
  });

  test("body inlined under cap", () => {
    const p = buildTaskPacket({
      title: "Hello",
      plan_body: "Step 1: do it.",
      plan_excerpt: "",
      spec_excerpt: "",
      verification_commands: [],
      file_claims: []
    } as any);
    expect(p.plan_excerpt).toContain("Step 1: do it.");
  });

  test("body truncated when over cap", () => {
    const body = "x".repeat(20_000);
    const p = buildTaskPacket({
      title: "T",
      plan_body: body,
      max_chars: 60_000,
      plan_excerpt: "", spec_excerpt: "", verification_commands: [], file_claims: []
    } as any);
    expect(p.plan_excerpt.length).toBeLessThanOrEqual(12_000);
    expect(p.plan_body_truncated).toBe(true);
    expect(p.plan_excerpt.endsWith("[truncated]")).toBe(true);
  });

  test("hard cap respected even when 40% of max_chars > 12000", () => {
    const p = buildTaskPacket({
      title: "T",
      plan_body: "y".repeat(30_000),
      max_chars: 100_000,
      plan_excerpt: "", spec_excerpt: "", verification_commands: [], file_claims: []
    } as any);
    expect(p.plan_excerpt.length).toBeLessThanOrEqual(12_000);
  });
});
```

---

## §T3 — Task 3: Project Script Catalog + Risk Inference [D-01, D-07]

### §T3.1 — Create `packages/orchestrator/src/planAdapters/projectScriptCatalog.ts`

```ts
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

export type CatalogSource = "npm" | "pnpm" | "yarn" | "bun" | "make" | "poetry" | "project";

export interface ProjectScriptCatalog {
  commands: ReadonlySet<string>;
  sources: ReadonlyMap<string, CatalogSource>;
  workspace_root: string;
}

export function buildProjectScriptCatalog(workspace: string): ProjectScriptCatalog {
  const commands = new Set<string>();
  const sources = new Map<string, CatalogSource>();

  addPackageJson(workspace, commands, sources);
  addMakefile(workspace, commands, sources);
  addPyproject(workspace, commands, sources);

  return { commands, sources, workspace_root: workspace };
}

export function isCommandInCatalog(
  command: string,
  catalog: ProjectScriptCatalog
): boolean {
  const norm = command.replace(/\s+/g, " ").trim();
  if (catalog.commands.has(norm)) return true;
  for (const c of catalog.commands) {
    if (norm.startsWith(`${c} `)) return true;
  }
  return false;
}

function addPackageJson(ws: string, cmds: Set<string>, src: Map<string, CatalogSource>): void {
  const p = join(ws, "package.json");
  if (!existsSync(p)) return;
  let pkg: { scripts?: Record<string, unknown> };
  try {
    pkg = JSON.parse(readFileSync(p, "utf8"));
  } catch {
    return;
  }
  const scripts = pkg.scripts;
  if (!scripts || typeof scripts !== "object") return;
  for (const name of Object.keys(scripts)) {
    if (typeof scripts[name] !== "string") continue;
    for (const [cmd, source] of [
      [`npm run ${name}`, "npm"],
      [`pnpm run ${name}`, "pnpm"],
      [`bun run ${name}`, "bun"],
      [`yarn ${name}`, "yarn"]
    ] as const) {
      if (!cmds.has(cmd)) {
        cmds.add(cmd);
        src.set(cmd, source);
      }
    }
  }
}

function addMakefile(ws: string, cmds: Set<string>, src: Map<string, CatalogSource>): void {
  const p = join(ws, "Makefile");
  if (!existsSync(p)) return;
  let body: string;
  try {
    body = readFileSync(p, "utf8");
  } catch {
    return;
  }
  for (const line of body.split(/\r?\n/)) {
    const m = /^([a-zA-Z][a-zA-Z0-9_-]*):/.exec(line);
    if (!m) continue;
    const name = m[1]!;
    if (name === "PHONY" || name === "phony") continue;
    const cmd = `make ${name}`;
    if (!cmds.has(cmd)) {
      cmds.add(cmd);
      src.set(cmd, "make");
    }
  }
}

function addPyproject(ws: string, cmds: Set<string>, src: Map<string, CatalogSource>): void {
  const p = join(ws, "pyproject.toml");
  if (!existsSync(p)) return;
  let body: string;
  try {
    body = readFileSync(p, "utf8");
  } catch {
    return;
  }
  // Minimal TOML section scan — sufficient for [tool.poetry.scripts] and [project.scripts]
  for (const [header, source] of [
    ["[tool.poetry.scripts]", "poetry"],
    ["[project.scripts]", "project"]
  ] as const) {
    const idx = body.indexOf(header);
    if (idx === -1) continue;
    const after = body.slice(idx + header.length);
    const nextHeader = after.search(/\n\[/m);
    const section = nextHeader === -1 ? after : after.slice(0, nextHeader);
    for (const line of section.split(/\r?\n/)) {
      const m = /^([a-zA-Z_][a-zA-Z0-9_-]*)\s*=/.exec(line);
      if (!m) continue;
      const name = m[1]!;
      const cmd = source === "poetry" ? `poetry run ${name}` : name;
      if (!cmds.has(cmd)) {
        cmds.add(cmd);
        src.set(cmd, source);
      }
    }
  }
}
```

### §T3.2 — Create `packages/orchestrator/src/planAdapters/riskInference.ts`

```ts
import type { FileClaim, RiskLevel } from "@waygent/contracts";

export interface RiskInferenceInput {
  title: string;
  body: string;
  file_claims: ReadonlyArray<Pick<FileClaim, "path">>;
}

export interface RiskInferenceResult {
  risk: RiskLevel;
  reason: string;
  matched_signals: string[];
}

const HIGH_KEYWORDS = /\b(schema migration|database migration|public api|breaking change|production deploy|secrets?|credentials?|auth(entication)?)\b/i;
const HIGH_PATHS = /(migration|schema|public-api|production|secrets?)/i;
const HIGH_CLAIM_COUNT = 10;

export function inferRiskLevel(input: RiskInferenceInput): RiskInferenceResult {
  const matched: string[] = [];
  const text = `${input.title}\n${input.body}`;

  if (HIGH_KEYWORDS.test(text)) {
    matched.push("high_keyword");
    return { risk: "high", reason: "high-risk keyword match", matched_signals: matched };
  }

  if (input.file_claims.length > HIGH_CLAIM_COUNT) {
    matched.push("many_claims");
    return { risk: "high", reason: "high file_claim count or sensitive path", matched_signals: matched };
  }
  const sensitivePath = input.file_claims.find((c) => HIGH_PATHS.test(c.path));
  if (sensitivePath) {
    matched.push(`sensitive_path:${sensitivePath.path}`);
    return { risk: "high", reason: "high file_claim count or sensitive path", matched_signals: matched };
  }

  const topLevelDirs = new Set(input.file_claims.map((c) => c.path.split("/")[0]));
  if (topLevelDirs.size > 1) {
    matched.push("cross_package");
    return { risk: "medium", reason: "cross-package claims", matched_signals: matched };
  }

  matched.push("default_low");
  return { risk: "low", reason: "single-package, no risk keyword", matched_signals: matched };
}
```

### §T3.3 — Create `packages/orchestrator/src/planAdapters/verifyQuality.ts`

```ts
export const TRIVIAL_TOKENS: ReadonlySet<string> = new Set([
  "printf", "true", ":", "echo", "/usr/bin/true", "/bin/true"
]);

export function isTrivialVerifyCommand(cmd: string): boolean {
  const first = cmd.trim().split(/\s+/)[0] ?? "";
  return TRIVIAL_TOKENS.has(first);
}

export interface VerifyTheaterInput {
  verify: ReadonlyArray<string>;
  file_claims: ReadonlyArray<{ path: string }>;
}

export interface VerifyTheaterResult {
  is_theater: boolean;
  reasons: string[];
}

export function detectVerifyTheater(input: VerifyTheaterInput): VerifyTheaterResult {
  const reasons: string[] = [];

  if (input.verify.length === 0) {
    reasons.push("no verify commands");
    return { is_theater: true, reasons };
  }

  if (input.verify.every(isTrivialVerifyCommand)) {
    reasons.push("all verify commands are trivial");
  }

  if (input.file_claims.length > 0) {
    const claimRegexes = input.file_claims.map((c) => globToRegex(c.path));
    const referenced = input.verify.flatMap((cmd) => extractPathTokens(cmd));
    const anyMatch = referenced.some((tok) => claimRegexes.some((re) => re.test(tok)));
    if (!anyMatch) {
      reasons.push("verify does not reference any claimed file");
    }
  }

  return { is_theater: reasons.length > 0, reasons };
}

function globToRegex(glob: string): RegExp {
  const escaped = glob
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*\*/g, "::DOUBLESTAR::")
    .replace(/\*/g, "[^/]*")
    .replace(/::DOUBLESTAR::/g, ".*");
  return new RegExp(`^${escaped}$`);
}

function extractPathTokens(cmd: string): string[] {
  return cmd
    .split(/\s+/)
    .filter((t) => t.includes("/") || t.includes(".") || /^[\w-]+$/.test(t));
}
```

### §T3.4 — Modify `packages/orchestrator/src/planNormalizer.ts`

Three changes:

1. Replace the prefix-only `isSafeVerificationCommand` with a
   catalog-aware version.
2. Replace the hardcoded `risk: "high"` with `inferRiskLevel(...)`.
3. Add verify-theater detection emitting diagnostics.

```diff
+import { buildProjectScriptCatalog, isCommandInCatalog, type ProjectScriptCatalog } from "./planAdapters/projectScriptCatalog.js";
+import { inferRiskLevel } from "./planAdapters/riskInference.js";
+import { detectVerifyTheater } from "./planAdapters/verifyQuality.js";

 const SAFE_COMMAND_STARTS = [
   "bun test",
   /* ... unchanged hard-coded list, kept as fallback for projects with no package.json ... */
 ];

-function isSafeVerificationCommand(command: string): boolean {
+function isSafeVerificationCommand(
+  command: string,
+  catalog: ProjectScriptCatalog | null,
+  options: { unsafe: boolean }
+): boolean {
+  if (options.unsafe) return true;
   const normalized = command.replace(/\s+/g, " ").trim();
   if (!normalized) return false;
   const parts = normalized.split(/\s+&&\s+/);
   return parts.every((part, index) => {
     if (index === 0 && part.startsWith("cd ")) return true;
-    return SAFE_COMMAND_STARTS.some((prefix) => part === prefix.trim() || part.startsWith(prefix));
+    if (SAFE_COMMAND_STARTS.some((prefix) => part === prefix.trim() || part.startsWith(prefix))) return true;
+    if (catalog && isCommandInCatalog(part, catalog)) return true;
+    return false;
   });
 }
```

In `normalizeWaygentPlanInput`:

```diff
 export function normalizeWaygentPlanInput(input: NormalizeWaygentPlanInput): NormalizedWaygentPlan {
+  const catalog = input.workspace
+    ? buildProjectScriptCatalog(input.workspace)
+    : null;
+  const unsafe = input.unsafe_verification === true;
+  const rejectTrivial = input.reject_trivial_verify === true;
+  const diagnostics: NormalizedDiagnostic[] = [];

   // ... existing parsing ...

   for (const section of sections) {
-    const verifyCommands = parseVerifyList(section);
-    if (!verifyCommands.every(isSafeVerificationCommand)) {
+    const verifyCommands = parseVerifyList(section);
+    const unsafeCommands = verifyCommands.filter((c) => !isSafeVerificationCommand(c, catalog, { unsafe }));
+    if (unsafeCommands.length > 0) {
       throw new Error(`Task "${section.title}" is missing safe verification commands: ${unsafeCommands.join(", ")}`);
     }

-    const risk: "high" = "high";
+    const inferred = inferRiskLevel({ title: section.title, body: section.body, file_claims: section.file_claims });
+    diagnostics.push({ task: section.title, risk: inferred.risk, reason: inferred.reason });

+    const theater = detectVerifyTheater({ verify: verifyCommands, file_claims: section.file_claims });
+    if (theater.is_theater) {
+      if (rejectTrivial) {
+        throw new Error(`Task "${section.title}" verify is trivial: ${theater.reasons.join("; ")}`);
+      }
+      diagnostics.push({ task: section.title, warning: "verification_quality_warning", reasons: theater.reasons });
+    }

     tasks.push({
       // ...
-      risk: "high",
+      risk: inferred.risk,
       // ...
     });
   }
+
+  if (unsafe) {
+    diagnostics.push({ run: true, warning: "unsafe_verification_enabled" });
+  }

-  return { tasks, /* ... */ };
+  return { tasks, diagnostics, /* ... */ };
 }
```

### §T3.5 — Surface diagnostics as events

In `runWaygent` setup, after normalization, walk
`normalized.diagnostics[]` and emit:

- `runway.verification_quality_warning` for each
  `warning: "verification_quality_warning"` entry.
- `runway.unsafe_verification_enabled` once for the run-level entry.

### §T3.6 — Tests

`packages/orchestrator/tests/projectScriptCatalog.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { buildProjectScriptCatalog, isCommandInCatalog } from "../src/planAdapters/projectScriptCatalog.js";

function tempWorkspace(): string {
  return mkdtempSync(join(tmpdir(), "catalog-test-"));
}

describe("projectScriptCatalog", () => {
  test("reads package.json scripts (4 variants per script)", () => {
    const ws = tempWorkspace();
    writeFileSync(join(ws, "package.json"), JSON.stringify({
      scripts: { lint: "eslint .", "test:lab": "node --test" }
    }));
    const cat = buildProjectScriptCatalog(ws);
    expect(cat.commands.has("npm run lint")).toBe(true);
    expect(cat.commands.has("bun run lint")).toBe(true);
    expect(cat.commands.has("yarn lint")).toBe(true);
    expect(cat.commands.has("npm run test:lab")).toBe(true);
  });

  test("reads Makefile targets", () => {
    const ws = tempWorkspace();
    writeFileSync(join(ws, "Makefile"), "build:\n\tgcc x.c\ntest:\n\t./run\n.PHONY: all\n");
    const cat = buildProjectScriptCatalog(ws);
    expect(cat.commands.has("make build")).toBe(true);
    expect(cat.commands.has("make test")).toBe(true);
    expect(cat.commands.has("make PHONY")).toBe(false);
  });

  test("missing files do not throw", () => {
    const ws = tempWorkspace();
    expect(() => buildProjectScriptCatalog(ws)).not.toThrow();
  });

  test("isCommandInCatalog exact and prefix match", () => {
    const ws = tempWorkspace();
    writeFileSync(join(ws, "package.json"), JSON.stringify({ scripts: { lint: "eslint ." } }));
    const cat = buildProjectScriptCatalog(ws);
    expect(isCommandInCatalog("npm run lint", cat)).toBe(true);
    expect(isCommandInCatalog("npm run lint -- --fix", cat)).toBe(true);
    expect(isCommandInCatalog("npm run linter", cat)).toBe(false);
  });
});
```

`packages/orchestrator/tests/riskInference.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { inferRiskLevel } from "../src/planAdapters/riskInference.js";

describe("riskInference", () => {
  test("keyword match → high", () => {
    expect(inferRiskLevel({ title: "Add schema migration", body: "", file_claims: [] }).risk).toBe("high");
  });
  test("sensitive path → high", () => {
    expect(inferRiskLevel({ title: "x", body: "", file_claims: [{ path: "db/migration/x.sql" }] }).risk).toBe("high");
  });
  test("many claims → high", () => {
    const fc = Array.from({ length: 11 }, (_, i) => ({ path: `src/a${i}.ts` }));
    expect(inferRiskLevel({ title: "x", body: "", file_claims: fc }).risk).toBe("high");
  });
  test("cross-package → medium", () => {
    expect(inferRiskLevel({ title: "x", body: "", file_claims: [{ path: "apps/a" }, { path: "pkgs/b" }] }).risk).toBe("medium");
  });
  test("single-package → low", () => {
    expect(inferRiskLevel({ title: "x", body: "", file_claims: [{ path: "src/a" }] }).risk).toBe("low");
  });
  test("matched_signals always non-empty", () => {
    expect(inferRiskLevel({ title: "x", body: "", file_claims: [] }).matched_signals.length).toBeGreaterThan(0);
  });
});
```

`packages/orchestrator/tests/planNormalizer.fixtureLab.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { readFileSync, mkdtempSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { normalizeWaygentPlanInput } from "../src/planNormalizer.js";

describe("planNormalizer — fixture-lab acceptance", () => {
  test("accepts FixThis fixture-lab plan when package.json has matching scripts", () => {
    const planBytes = readFileSync(join(import.meta.dir, "fixtures", "fixture_lab_plan.md"), "utf8");
    const ws = mkdtempSync(join(tmpdir(), "fixture-lab-"));
    writeFileSync(join(ws, "package.json"), JSON.stringify({
      scripts: { "source-matching:fixtures:test": "node --test scripts/source-matching-fixtures-test.mjs" }
    }));

    const result = normalizeWaygentPlanInput({
      plan: planBytes,
      workspace: ws,
      spec: ""
    } as any);

    expect(result.tasks.length).toBeGreaterThanOrEqual(5);
    for (const task of result.tasks) {
      expect(task.verify.length).toBeGreaterThan(0);
    }
  });

  test("rejects when no catalog and no safe prefix matches", () => {
    expect(() => normalizeWaygentPlanInput({
      plan: "## Task 1\nverify: npm run unknown",
      spec: ""
    } as any)).toThrow();
  });
});
```

---

## §T4 — Task 4: CLI Surface [D-02, D-03, D-04]

### §T4.1 — Create `packages/orchestrator/src/runIdDerivation.ts`

```ts
import { basename } from "node:path";

export function deriveAutoRunId(planPath: string, now: Date = new Date()): string {
  const base = basename(planPath, ".md").replace(/^\d{4}-\d{2}-\d{2}-/, "");
  const slug = base
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "plan";
  const ts = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "").replace("T", "_");
  return `${slug}_${ts}`;
}
```

### §T4.2 — Modify `packages/orchestrator/src/orchestrator.ts`

```diff
+import { deriveAutoRunId } from "./runIdDerivation.js";
+import { mkdirSync } from "node:fs";

 export async function runWaygent(options: RunWaygentOptions): Promise<WaygentRunResult> {
-  const runId = options.run_id ?? "run_demo";
+  const planRef = typeof options.plan === "string" ? options.plan : "unnamed-plan";
+  const runId = options.run_id ?? deriveAutoRunId(planRef);
   // ... existing logic ...
+  mkdirSync(paths.root, { recursive: true });
   if (hasExistingRunEvidence(paths)) {
     throw new Error("run_id_already_exists");
   }
 }

 export function defaultRunRoot(): string {
-  return join(tmpdir(), "waygent-runs");
+  switch (process.platform) {
+    case "darwin":
+      return join(homedir(), "Library", "Application Support", "waygent", "runs");
+    case "linux": {
+      const xdg = process.env.XDG_DATA_HOME;
+      return xdg && xdg.length > 0
+        ? join(xdg, "waygent", "runs")
+        : join(homedir(), ".local", "share", "waygent", "runs");
+    }
+    case "win32":
+      return join(process.env.LOCALAPPDATA ?? join(homedir(), "AppData", "Local"),
+                  "waygent", "runs");
+    default:
+      process.stderr.write(
+        `WARN: unsupported platform '${process.platform}'; using tmpdir for waygent runs (volatile)\n`
+      );
+      return join(tmpdir(), "waygent-runs");
+  }
 }
```

Add `import { homedir } from "node:os";` at the top if missing.

### §T4.3 — Modify `apps/cli/src/index.ts`

Update `commandUsage.run`:

```ts
const commandUsage = {
  run: [
    "waygent run --plan <waygent-task.md> [--spec <design.md>]",
    "  [--provider codex|claude|fake]",
    "  [--execution-mode multi-agent|single-agent]",
    "  [--plan-preflight off|deterministic|full]",
    "  [--plan-adapter superpowers|native|auto]",
    "  [--inherit-plan-prose on|off]",
    "  [--unsafe-verification] [--reject-trivial-verify]",
    "  [--main-model <name>] [--subagent-model <name>]",
    "  [--main-reasoning low|medium|high|xhigh] [--subagent-reasoning low|medium|high|xhigh]",
    "  [--profile cost-saver|balanced|max-quality]",
    "  [--run <id>] [--budget-cap <usd>] [--budget-action warn|pause|off]",
    "  [--require-cost-data] [--root <path>]"
  ].join("\n"),
  // ... unchanged demo / run-chain ...
};
```

Add flag parsing to `runCli` (the existing parser handles unknown
flags as keyed strings; add boolean detection for the new bool flags):

```ts
const BOOL_FLAGS = new Set(["unsafe-verification", "reject-trivial-verify", "require-cost-data"]);

// In parseCliArgs, after the existing flag loop:
for (const k of BOOL_FLAGS) {
  if (parsed.flags[k] === "true" || parsed.flags[k] === "") parsed.flags[k] = true;
}
```

In `resolveCliProfile`, add profile preset resolution:

```ts
type ProfileName = "cost-saver" | "balanced" | "max-quality";

const PROFILE_PRESETS: Record<ProfileName, Record<"claude" | "codex" | "fake",
  { main: [string, string]; subagent: [string, string] }>> = {
  "cost-saver": {
    claude: { main: ["sonnet", "medium"], subagent: ["haiku", "low"] },
    codex: { main: ["gpt-5.3-codex", "medium"], subagent: ["gpt-5.3-codex", "low"] },
    fake: { main: ["fake", "low"], subagent: ["fake", "low"] }
  },
  balanced: {
    claude: { main: ["opus", "high"], subagent: ["sonnet", "medium"] },
    codex: { main: ["gpt-5.4", "high"], subagent: ["gpt-5.3-codex", "medium"] },
    fake: { main: ["fake", "low"], subagent: ["fake", "low"] }
  },
  "max-quality": {
    claude: { main: ["opus", "high"], subagent: ["opus", "high"] },
    codex: { main: ["gpt-5.5", "high"], subagent: ["gpt-5.4", "high"] },
    fake: { main: ["fake", "low"], subagent: ["fake", "low"] }
  }
};

function applyProfile(profile: ResolvedProfile, presetName: ProfileName | undefined, parsed: ParsedCli): ResolvedProfile {
  const name = presetName ?? "balanced";
  const preset = PROFILE_PRESETS[name][profile.provider as "claude" | "codex" | "fake"];
  if (!profile.main_model)        profile.main_model        = preset.main[0];
  if (!profile.main_reasoning)    profile.main_reasoning    = preset.main[1] as any;
  if (!profile.subagent_model)    profile.subagent_model    = preset.subagent[0];
  if (!profile.subagent_reasoning) profile.subagent_reasoning = preset.subagent[1] as any;
  profile.profile_name = name;
  return profile;
}
```

Then call `applyProfile(profile, parsed.flags.profile as ProfileName | undefined, parsed)` at the end of `resolveCliProfile`.

### §T4.4 — Collision-retry wrapper

In `runCli`, replace direct `await runWaygent(options)` with the
retry wrapper from detailed spec §13.4:

```ts
async function runWithCollisionRetry(planPath: string, options: RunWaygentOptions): Promise<WaygentRunResult> {
  const hasExplicit = typeof options.run_id === "string" && options.run_id.length > 0;
  if (hasExplicit) return runWaygent(options);

  const baseId = deriveAutoRunId(planPath);
  for (let attempt = 0; attempt <= 9; attempt++) {
    const id = attempt === 0 ? baseId : `${baseId}_${attempt + 1}`;
    try {
      return await runWaygent({ ...options, run_id: id });
    } catch (err) {
      if (!(err instanceof Error) || err.message !== "run_id_already_exists") throw err;
      if (attempt === 9) throw new Error(`run_id_already_exists after 9 retries: ${baseId}`);
    }
  }
  throw new Error("unreachable");
}
```

### §T4.5 — Dispatch echo line

In `taskExecutor.ts` (or wherever the first task dispatch is initiated),
before the first dispatch:

```ts
await ctx.events.emit({
  event_type: "runway.dispatch_plan_echoed",
  payload: {
    run_id: ctx.run_id,
    task_count: tasks.length,
    task_ids: tasks.map((t) => t.id),
    provider: ctx.profile.provider,
    main: {
      model: ctx.profile.main_model,
      reasoning: ctx.profile.main_reasoning,
      source: ctx.profile.main_source ?? "default"
    },
    subagent: {
      model: ctx.profile.subagent_model,
      reasoning: ctx.profile.subagent_reasoning,
      source: ctx.profile.subagent_source ?? "default"
    },
    budget_cap_usd: ctx.budget?.cap_usd ?? null,
    expected_cost_estimate_usd: estimateCost(tasks, ctx.profile),
    profile_name: ctx.profile.profile_name ?? null
  }
});

process.stderr.write(
  `[waygent] Parsed: ${tasks.length} task(s), main=${ctx.profile.main_model}(${ctx.profile.main_reasoning}), ` +
  `sub=${ctx.profile.subagent_model}(${ctx.profile.subagent_reasoning}), ` +
  `budget=${ctx.budget?.cap_usd ?? "off"}.\n`
);
```

`estimateCost` is informational only: `tasks.length * 20_000 * price_per_output_token`.

### §T4.6 — Tests

`apps/cli/tests/runIdAutoGen.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { deriveAutoRunId } from "@waygent/orchestrator/dist/runIdDerivation.js";

describe("deriveAutoRunId", () => {
  test("strips date prefix and slugifies", () => {
    const fixed = new Date("2026-05-22T19:30:45.000Z");
    expect(deriveAutoRunId("plans/2026-05-20-trustworthy-source-matching.md", fixed))
      .toBe("trustworthy_source_matching_20260522_193045");
  });
  test("empty slug falls back to 'plan'", () => {
    const fixed = new Date("2026-05-22T00:00:00.000Z");
    expect(deriveAutoRunId("plans/2026-05-22-.md", fixed))
      .toMatch(/^plan_20260522_000000$/);
  });
});
```

`apps/cli/tests/profilePreset.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { resolveCliProfile } from "../src/index.js";

describe("--profile preset resolution", () => {
  test("claude balanced default", () => {
    const p = resolveCliProfile({ command: "run", flags: { provider: "claude" } } as any);
    expect(p.main_model).toBe("opus");
    expect(p.subagent_model).toBe("sonnet");
  });
  test("claude cost-saver", () => {
    const p = resolveCliProfile({ command: "run", flags: { provider: "claude", profile: "cost-saver" } } as any);
    expect(p.main_model).toBe("sonnet");
    expect(p.subagent_model).toBe("haiku");
  });
  test("explicit --main-model overrides preset", () => {
    const p = resolveCliProfile({ command: "run", flags: { provider: "claude", profile: "cost-saver", "main-model": "opus" } } as any);
    expect(p.main_model).toBe("opus");
  });
});
```

---

## §T5 — Task 5: Cost Ledger Envelope Extraction [D-08]

This task's code is mostly shipped in §T1 (the `metadataFromParsed`
signature change and `usageFromEnvelope` helper). What remains:

### §T5.1 — Test: `packages/provider-adapters/tests/usageExtraction.test.ts`

```ts
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { normalizeProcessOutput } from "../src/processAdapters.js";

describe("usage extraction", () => {
  test("envelope-level usage extracted from claude task_3 fixture", () => {
    const stdout = readFileSync(
      join(import.meta.dir, "fixtures", "claude_task_3_narrative_then_json.stdout.txt"),
      "utf8"
    );
    const result = normalizeProcessOutput("claude", "t", "c", {
      exitCode: 0, stdout, stderr: "", timedOut: false,
      startedAt: "now", completedAt: "now"
    });
    expect(result.metadata.usage?.input_tokens).toBe(46);
    expect(result.metadata.usage?.output_tokens).toBe(29302);
    expect(result.metadata.usage?.cached_read_tokens).toBe(2_758_848);
    expect(result.metadata.usage?.cached_write_tokens).toBe(80_976);
    expect(result.metadata.usage_source).toBe("provider_json");
  });

  test("missing usage with envelope present → missing_in_provider_output", () => {
    const stdout = JSON.stringify({
      type: "result",
      result: '```json\n{"status":"complete","summary":"ok","evidence":{}}\n```'
      // no usage field
    });
    const result = normalizeProcessOutput("claude", "t", "c", {
      exitCode: 0, stdout, stderr: "", timedOut: false,
      startedAt: "now", completedAt: "now"
    });
    expect(result.metadata.usage).toBeNull();
    expect(result.metadata.usage_source).toBe("missing_in_provider_output");
  });

  test("cache fields default to 0 when absent", () => {
    const stdout = JSON.stringify({
      type: "result",
      result: '```json\n{"status":"complete","summary":"ok","evidence":{}}\n```',
      usage: { input_tokens: 1, output_tokens: 2 }
    });
    const result = normalizeProcessOutput("claude", "t", "c", {
      exitCode: 0, stdout, stderr: "", timedOut: false,
      startedAt: "now", completedAt: "now"
    });
    expect(result.metadata.usage?.cached_read_tokens).toBe(0);
    expect(result.metadata.usage?.cached_write_tokens).toBe(0);
  });
});
```

### §T5.2 — `waygent cost` zero-output warning

In `packages/orchestrator/src/runCommands.ts` `costRun` (or wherever
the cost subcommand is implemented), after building the ledger:

```ts
const totals = ledger.totals;
if (totals.dispatches > 0 && totals.input_tokens + totals.output_tokens === 0) {
  process.stderr.write(
    `WARN: cost ledger has 0 token usage across ${totals.dispatches} dispatches. ` +
    `Provider adapter may not be parsing usage. Inspect:\n` +
    `  artifacts/provider/*.stdout.txt (look for top-level "usage" key)\n` +
    `  events.jsonl (look for platform.cost_accumulated events with usage:null)\n`
  );
}
```

### §T5.3 — `--require-cost-data` enforcement

In `taskExecutor.ts`, after each dispatch, when
`ctx.options.require_cost_data === true`:

```ts
if (result.metadata.usage_source === "missing_in_provider_output" || result.metadata.usage_source === "unknown") {
  await ctx.events.emit({
    event_type: "runway.cost_data_missing",
    payload: {
      task_id: task.id,
      usage_source: result.metadata.usage_source,
      dispatch_index: attempts.length
    }
  });
  throw new Error(`cost_data_missing: task ${task.id} dispatch produced no usage telemetry`);
}
```

---

## §T6 — Task 6: Worker Sandbox `allowed_exec_commands` [D-11]

This is mostly contract wiring; code mostly already exists in §T3
(catalog) and §T1 (prompt surface).

### §T6.1 — Modify `taskPacket.ts` to populate `allowed_exec_commands`

```ts
// New BuildTaskPacketInput field: workspace?: string

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

// Add to base:
allowed_exec_commands,
```

### §T6.2 — Test: `packages/context-packer/tests/taskPacket.execAllowlist.test.ts`

```ts
import { describe, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { buildTaskPacket } from "../src/taskPacket.js";

describe("buildTaskPacket — allowed_exec_commands", () => {
  test("union of catalog + verify + read-only utilities", () => {
    const ws = mkdtempSync(join(tmpdir(), "exec-allowlist-"));
    writeFileSync(join(ws, "package.json"), JSON.stringify({
      scripts: { "test:lab": "node --test scripts/*" }
    }));
    const p = buildTaskPacket({
      title: "x",
      plan_excerpt: "",
      spec_excerpt: "",
      verification_commands: ["node --test scripts/test.mjs"],
      file_claims: [],
      workspace: ws
    } as any);

    expect(p.allowed_exec_commands).toBeTruthy();
    expect(p.allowed_exec_commands).toContain("npm run test:lab");
    expect(p.allowed_exec_commands).toContain("node --test scripts/test.mjs");
    expect(p.allowed_exec_commands).toContain("git status");
  });

  test("workspace absent → allowed_exec_commands is null", () => {
    const p = buildTaskPacket({
      title: "x", plan_excerpt: "", spec_excerpt: "", verification_commands: [], file_claims: []
    } as any);
    expect(p.allowed_exec_commands).toBeNull();
  });
});
```

---

## §T7 — Task 7: Persistent State Root [D-05]

Code change is in §T4.2 (`defaultRunRoot` platform-aware). Remaining:

### §T7.1 — Modify `packages/orchestrator/src/orphanRuns.ts`

```diff
+import { defaultRunRoot } from "./orchestrator.js";
+import { tmpdir } from "node:os";
+import { join } from "node:path";

 export function scanOrphanRuns(input: { root?: string; auto_scan_legacy?: boolean }): OrphanRunAdvisory {
-  const root = input.root;
+  const explicit = typeof input.root === "string";
+  const autoLegacy = input.auto_scan_legacy !== false;
+  const rootsToScan = explicit
+    ? [{ root: input.root!, legacy: false }]
+    : [
+        { root: defaultRunRoot(), legacy: false },
+        ...(autoLegacy ? [{ root: join(tmpdir(), "waygent-runs"), legacy: true }] : [])
+      ];

   const orphans: OrphanRunEntry[] = [];
-  if (!existsSync(input.root)) return { ... };
+  for (const { root, legacy } of rootsToScan) {
+    if (!existsSync(root)) continue;
+    for (const entry of scanRoot(root)) {
+      orphans.push({ ...entry, migration_suggested: legacy || undefined });
+    }
+  }
+  // Dedupe by run_id; new-root entries win.
+  const byId = new Map<string, OrphanRunEntry>();
+  for (const o of orphans) {
+    const existing = byId.get(o.run_id);
+    if (!existing || existing.migration_suggested) byId.set(o.run_id, o);
+  }
+  return { root: explicit ? input.root! : "auto", checked_at: new Date().toISOString(), orphans: [...byId.values()] };
 }
```

### §T7.2 — Create `docs/operations/state-root-migration.md`

```md
# Waygent state-root migration (2026-05-22)

## Why

waygent run state was previously written under
`$TMPDIR/waygent-runs/` (typically `/var/folders/.../T/waygent-runs/`
on macOS). macOS periodically reaps `/var/folders/.../T/`, which means
in-flight runs can be cleared during reboots, low-disk events, or
extended idle periods. Forensic analysis of failed runs (D-09–style
debugging) is impossible once the directory has been reaped.

## New defaults

| Platform | Default `defaultRunRoot()` |
|----------|----------------------------|
| darwin   | `~/Library/Application Support/waygent/runs/` |
| linux    | `${XDG_DATA_HOME:-$HOME/.local/share}/waygent/runs/` |
| win32    | `%LOCALAPPDATA%/waygent/runs/` |
| other    | `$TMPDIR/waygent-runs/` (with stderr WARN) |

The directory is auto-created on first use.

## Migration of existing runs

To preserve existing runs, copy them once:

```bash
# macOS example
mkdir -p ~/Library/Application\ Support/waygent/runs/
cp -r "$TMPDIR/waygent-runs/." ~/Library/Application\ Support/waygent/runs/
```

`waygent orphans` (without `--root`) automatically scans BOTH roots
during a transition period and flags legacy-root entries with
`migration_suggested: true`.

## CI compatibility

`--root <path>` flag is unchanged. CI users pinning a custom root
remain unaffected. The new defaults apply only when `--root` is
omitted.

## Disk usage

Each run averages ~50 MB. Runs accumulate unless pruned via
`waygent orphans --delete <id> --yes`.
```

### §T7.3 — Test: `packages/orchestrator/tests/defaultRunRoot.test.ts`

```ts
import { describe, expect, test, beforeEach, afterEach } from "bun:test";
import { defaultRunRoot } from "../src/orchestrator.js";

describe("defaultRunRoot — platform paths", () => {
  const origPlatform = process.platform;
  const origXdg = process.env.XDG_DATA_HOME;
  const origLocal = process.env.LOCALAPPDATA;

  function setPlatform(p: NodeJS.Platform): void {
    Object.defineProperty(process, "platform", { value: p, writable: true });
  }
  afterEach(() => {
    setPlatform(origPlatform);
    process.env.XDG_DATA_HOME = origXdg;
    process.env.LOCALAPPDATA = origLocal;
  });

  test("darwin → Library/Application Support", () => {
    setPlatform("darwin");
    expect(defaultRunRoot()).toContain("Library/Application Support/waygent/runs");
  });
  test("linux without XDG → ~/.local/share", () => {
    setPlatform("linux");
    delete process.env.XDG_DATA_HOME;
    expect(defaultRunRoot()).toContain(".local/share/waygent/runs");
  });
  test("linux with XDG", () => {
    setPlatform("linux");
    process.env.XDG_DATA_HOME = "/custom/data";
    expect(defaultRunRoot()).toBe("/custom/data/waygent/runs");
  });
  test("win32 → LOCALAPPDATA", () => {
    setPlatform("win32");
    process.env.LOCALAPPDATA = "C:\\Users\\u\\AppData\\Local";
    expect(defaultRunRoot()).toContain("waygent");
  });
});
```

---

## §C1 — Commit Sequence

Following the rollout in design §S13, ship as 5 sequenced PRs/commits.
Each is independently revertible; later commits build on earlier
contracts.

| # | Commit / PR title | Touches | Tests |
|---|--------------------|---------|-------|
| 1 | `fix: harden worker output parser (D-09)` | M01 (parseJsonText, isWorkerResultCandidate, unwrapProviderEnvelope, parseWorkerOutput) | parseWorkerOutput.test.ts |
| 2 | `feat: envelope-level usage extraction (D-08)` | M01 (metadataFromParsed signature, usageFromEnvelope, modelFromEnvelope) + apps/cli costRun warning | usageExtraction.test.ts |
| 3 | `feat: recovery executor with policy matrix (D-10)` | M02 + M10 (taskExecutor retry wiring) + M15 (FailureClass-keyed types) + M16 (new event) | recoveryExecutor.test.ts |
| 4 | `feat: plan-adapter pattern (D-01, D-06, D-07)` | M03, M04, M05, M06, M07, M08, M13 (plan_body) | planParser.deps + bodyPropagation + projectScriptCatalog + riskInference + planNormalizer.fixtureLab + taskPacket.planExcerpt |
| 5 | `feat: CLI surface + state root (D-02, D-03, D-04, D-05, D-11)` | M09, M11 (defaultRunRoot), M12 (orphanRuns dual), M13 (allowed_exec_commands), M14 (cli flags + retry wrapper) | runIdDerivation + profilePreset + collisionRetry + defaultRunRoot + taskPacket.execAllowlist |

After all 5: end-to-end replay (next section) is the acceptance gate.

---

## §C2 — End-to-End Replay

```bash
cd /Users/kws/source/private/Archive

# Sanity
bun test \
  packages/provider-adapters/tests \
  packages/orchestrator/tests \
  packages/context-packer/tests \
  apps/cli/tests

bun run waygent:scenarios
bun run check
git diff --check

# Replay the original failed plan, now expected to succeed.
waygent run \
  --plan /Users/kws/source/android/FixThis/docs/superpowers/plans/2026-05-20-trustworthy-source-matching-local-fixture-lab.md \
  --spec /Users/kws/source/android/FixThis/docs/superpowers/specs/2026-05-20-trustworthy-source-matching-local-fixture-lab-design.md \
  --provider claude \
  --profile balanced \
  --execution-mode multi-agent \
  --plan-preflight deterministic
```

Expected:

- 5/5 tasks COMPLETE.
- Worker successfully runs `node --test scripts/source-matching-fixtures-test.mjs`
  inside the sandbox (no `permission_denials` in any `attempt_*.stdout.txt`).
- `waygent cost --last` shows non-zero `input_tokens` and `output_tokens`
  on every task; `usage_source: provider_json` on each
  `platform.cost_accumulated` event.
- Total cost ≤ ~$0.50 (balanced preset: opus orchestration + sonnet sub-agents).
- Run dir under `~/Library/Application Support/waygent/runs/`, not
  `/var/folders/.../T/`.

If any of these fail, see §C3 below for triage.

---

## §C3 — Triage Quick Reference

| Symptom | First thing to check |
|---------|----------------------|
| Task still BLOCKED with `malformed_result` | `bun test packages/provider-adapters/tests/parseWorkerOutput.test.ts` — fixture passing? If yes, retry logic in taskExecutor likely not wired. |
| `usage_source: unknown` on every task | `metadataFromParsed` signature not getting envelope. Check call site in `normalizeProcessOutput`. |
| Plan rejected as "missing safe verification commands" | Catalog not being built. Confirm `--workspace` is being passed by CLI or that `process.cwd()` is being used as fallback. |
| `node --test` blocked by sandbox | `allowed_exec_commands` not surfacing in prompt. Verify `buildProviderPrompt` patch §T1.1.h applied. |
| `run_id_already_exists` despite no `--run` | `runWithCollisionRetry` wrapper not used in `runCli`. |
| Run state in `/var/folders/...` | `defaultRunRoot` returning tmpdir on the user's platform. Check `process.platform` value. |

---

## §C4 — Out-of-scope reminders

(Copied from plan § "Non-goals" for ease of triage during execution.)

- **Method audit framework** — separate sprint.
- **Polite-stop antipattern guard for reviewer skip** — tracked in
  `2026-05-22-waygent-runtime-improvements-implementation.md`.
- **Sub-agent per-call cost split** — deferred.
- **Multi-plan chain validation** — separate experiment.
- **Plan adapter externalization as separate npm package** — internal
  module only for this remediation.

---

## §C5 — Implementer Checklist

Use this for human or agent execution; one box per file group.

- [ ] §F1 — fixtures copied (3 source files into 3 dirs)
- [ ] §T1.1 — processAdapters.ts patches 1.1.a–1.1.i applied
- [ ] §T1.2 — recoveryExecutor.ts created with 29-entry matrix
- [ ] §T1.3 — taskExecutor retry loop wired
- [ ] §T1.4–5 — parseWorkerOutput + recoveryExecutor tests pass
- [ ] §T2.1 — instructionsExtract.ts moved (no behavior change)
- [ ] §T2.2 — planParser body-propagation patch applied
- [ ] §T2.3 — planParser block-list deps patch applied
- [ ] §T2.4 — taskPacket plan_excerpt cap applied
- [ ] §T2.5 — all 3 test files pass
- [ ] §T3.1 — projectScriptCatalog.ts created
- [ ] §T3.2 — riskInference.ts created
- [ ] §T3.3 — verifyQuality.ts created
- [ ] §T3.4 — planNormalizer integrates catalog + risk + verify-quality
- [ ] §T3.5 — diagnostics surfaced as events
- [ ] §T3.6 — all 3 test files pass
- [ ] §T4.1 — runIdDerivation.ts created
- [ ] §T4.2 — orchestrator.ts default + defaultRunRoot patched
- [ ] §T4.3 — apps/cli help text + flag parsing + profile preset
- [ ] §T4.4 — runWithCollisionRetry wrapper integrated
- [ ] §T4.5 — dispatch echo line emits
- [ ] §T4.6 — runIdAutoGen + profilePreset tests pass
- [ ] §T5.1 — usageExtraction test passes against D-09 fixture
- [ ] §T5.2 — costRun zero-token warning emits
- [ ] §T5.3 — --require-cost-data fail-fast emits and throws
- [ ] §T6.1 — taskPacket populates allowed_exec_commands from workspace
- [ ] §T6.2 — execAllowlist test passes
- [ ] §T7.1 — orphanRuns dual-root scan applied
- [ ] §T7.2 — state-root-migration.md created
- [ ] §T7.3 — defaultRunRoot platform test passes
- [ ] §C1 — 5 commits/PRs in stated order
- [ ] §C2 — end-to-end replay succeeds at 5/5 COMPLETE under ~$0.50

When every box is ticked: the remediation is complete; D-01..D-11 are
closed.
