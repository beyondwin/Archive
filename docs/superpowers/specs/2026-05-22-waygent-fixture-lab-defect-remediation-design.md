# Waygent Fixture-Lab Defect Remediation — Source-Audited Design Spec

Date: 2026-05-22
Status: Source-audited (paired with fixture-lab failed-run artifacts)

This spec is the source-audited design partner for
`docs/superpowers/plans/2026-05-22-waygent-fixture-lab-defect-remediation.md`.
It is grounded in concrete artifacts from the failed run
`trustworthy_fixture_lab_wg_20260522_200031`, not theoretical gaps. The
companion comparative analysis is
`docs/2026-05-22-waygent-vs-cme-fixture-lab-analysis.md`.

The design rule: **all changes are additive to existing v1/v2 contracts**.
No schema bump on `waygent.run_state.v2`, no change to `agentlens.event.v3`
envelope. New event_types are added (not changed); new optional fields are
attached to existing contracts.

---

## S0. Source Audit Baseline

Re-audit evidence from 2026-05-22:

- `git status --short --branch --untracked-files=all` was clean on
  `main...origin/main` at the start of the comparison run.
- Run dir:
  `/var/folders/01/pttq8zy57654cfd1zm1ps7jm0000gn/T/waygent-runs/trustworthy_fixture_lab_wg_20260522_200031/`
  (still present at audit time; copy artifacts into
  `tests/fixtures/` before macOS tmp cleanup invalidates the source —
  itself the D-05 motivation).
- Failed task: `task_3_fixture_preparation_and_gradle_injection`.
- Provider artifact:
  `artifacts/provider/attempt_task_3_fixture_preparation_and_gradle_injection_1.stdout.txt`
  (7884 bytes, single line — confirmed by `wc -c` at 2026-05-22 23:xx UTC).
- Task packet artifact:
  `artifacts/task_packets/task_3_*.json` — `plan_excerpt:
  "Implement Fixture Preparation And Gradle Injection"` (title only),
  `allowed_exec_commands: null`.

### S0.1 — Post-design source-audit corrections (2026-05-22)

After the design was drafted, the source tree was re-verified file-by-file.
The findings below correct three statements in earlier drafts; the
architectural approach is unaffected.

| Finding | Plan/Spec earlier claim | Source reality | Section corrected |
|---------|------------------------|----------------|-------------------|
| `WaygentTaskPacket.context_budget.max_chars` default | 12 000 chars | 60 000 chars (`packages/context-packer/src/taskPacket.ts:27`) | S4.5 |
| `unwrapProviderEnvelope` envelope-leaf search | "needs to be added" | `result`, `message`, `text`, `item.text` *already* searched (`processAdapters.ts:256–274`); only depth-≤3 generic leaf search + envelope return are new | S2.3 |
| `runWaygent` internal callers | "~30" | ~27 across `packages/orchestrator/tests/`, `packages/testkit/`, and `planChain.ts`. Order-of-magnitude unchanged; backward-compat argument intact | S7.1 |
| `commandUsage.run` text | Implicitly assumed `claude` is the default `run` provider | Default for `run` is `codex` (`apps/cli/src/index.ts:73`). The profile-preset *default profile* change applies only when the user passes `--provider claude`. | S7.4 |
| `FailureClass` entry count | Prose summary said "28" | 29 entries in `packages/contracts/src/types.ts:30–59`; matrix S3.2 also lists 29. No action. | S3.2 |

All other audited claims (`parseWorkerOutput@234–251`,
`SAFE_COMMAND_STARTS@38–55`, `risk: "high"@95`,
`extractInstructionLines@182–193`, `defaultRunRoot → tmpdir`,
`options.run_id ?? "run_demo"@75`, `TASK_BLOCK regex`,
`isWorkerResultCandidate` OR-predicate, `parseJsonText` non-global regex,
`runway.*` event-type set of 15) were verified verbatim.

Active source paths under audit:

- `apps/cli/src/index.ts` — CLI command parser, profile resolution.
- `packages/provider-adapters/src/processAdapters.ts` — claude/codex
  stdout normalization (the D-09 + D-08 fix site).
- `packages/orchestrator/src/orchestrator.ts` — `runWaygent` entry, run_id
  default, run state init.
- `packages/orchestrator/src/planParser.ts` — yaml waygent-task parser
  (the D-02 + D-06 fix site).
- `packages/orchestrator/src/planNormalizer.ts` — superpowers→native
  normalizer (the D-01 + D-07 fix site).
- `packages/context-packer/src/taskPacket.ts` — task_packet builder (the
  D-06 + D-11 fix site).
- `packages/orchestrator/src/costLedger.ts` — accumulator; structurally
  correct, no change.
- `packages/orchestrator/src/taskExecutor.ts` — dispatch loop (the D-10
  retry-wire fix site).
- `packages/orchestrator/src/runEvents.ts` — event publisher (target for
  new `runway.*` event_types).

---

## S1. The failed task_3 byte-level walkthrough

The literal stdout for the failed dispatch is a single-line claude
`--output-format json` envelope:

```jsonc
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "duration_ms": 601963,
  "result": "Implementation complete. ... \n```json\n{\n  \"schema\": \"runway.worker_result.v1\",\n  \"task_id\": \"task_3_...\",\n  \"status\": \"complete\",\n  \"changed_files\": [...],\n  \"summary\": \"...\",\n  \"evidence\": {...}\n}\n```",
  "stop_reason": "end_turn",
  "session_id": "b67427db-...",
  "total_cost_usd": 3.0589039999999996,
  "usage": {
    "input_tokens": 46,
    "cache_creation_input_tokens": 80976,
    "cache_read_input_tokens": 2758848,
    "output_tokens": 29302,
    ...
  },
  "modelUsage": {
    "claude-opus-4-7": { "inputTokens": 70061, "outputTokens": 32923, ... }
  },
  "permission_denials": [
    {"tool_name": "Bash", "tool_input": {"command": "node --test scripts/source-matching-fixtures-test.mjs"}},
    ... 12 more denials
  ],
  "terminal_reason": "completed"
}
```

### S1.1 — Why parsing failed

The fixture artifact is 7884 bytes on a single line; only the first 200
and last 5000 bytes were directly inspected. The middle ~2700 bytes
(narrative body) are not byte-confirmed. The trace below identifies which
function-level branch held and which sub-cause is **plausibly responsible**;
the Task 1.2 fix (try all fenced matches, prefer `json` label) is correct
under any of them.

Trace through current `parseWorkerOutput`
(`packages/provider-adapters/src/processAdapters.ts:234-251`):

1. `trimmed = stdout.trim()` — full envelope string.
2. `candidates = [trimmed, ...reversed_split_by_newline]` — only one
   line, so effectively `[trimmed]`.
3. `parseJsonText(trimmed)`:
   1. `tryParseJson(trimmed)` → SUCCEEDS, returns the envelope object.
4. `unwrapProviderEnvelope(parsed)`:
   1. `typeof value.result === "string"` → true.
   2. `parseJsonText(value.result)`:
      - `tryParseJson(value.result)` fails (starts with "Implementation
        complete." — not JSON).
      - Fenced regex
        `/```(?:json)?\s*([\s\S]*?)```/` (non-global, non-multiline)
        captures the FIRST triple-backtick pair found in `result`. Since
        the regex's `(?:json)?` label is optional and the match is
        non-global, the captured content is NOT guaranteed to be the
        worker_result JSON: any earlier code fence in the narrative
        body (e.g., a `bash` snippet, a `yaml` quote, a `javascript`
        sample) wins the match.
      - If the captured content is not a worker_result, `tryParseJson`
        either parses it as a non-conforming object (rejected by
        `isWorkerResultCandidate`) or fails outright.
      - Brace-span fallback: `start = result.indexOf("{")` and `end =
        result.lastIndexOf("}")` can over-span across multiple unrelated
        code blocks, producing malformed JSON.
      - Returns null.
5. `unwrapProviderEnvelope` keeps `parsed = envelope` (no replacement).
6. `isWorkerResultCandidate(envelope)`: envelope has none of
   `status|changed_files|summary|failure_class` at top level → false.
7. Loop exhausted. `throw new Error("missing worker result JSON")`.
8. Caught at line 65, returns
   `failed(...failure_class: "malformed_result")`.

**Three sub-causes are individually sufficient** to produce this outcome,
and Task 1's fix addresses all three:

- **(a) First-fence collision** — `parseJsonText` matches a non-`json`
  fence ahead of the worker_result fence. Fix S2.1: enumerate all fences,
  prefer `json` label.
- **(b) Brace-span over-spanning** — the fallback `indexOf("{") ..
  lastIndexOf("}")` slice straddles unrelated code. Fix S2.1: replace
  with `enumerateBalancedBraceSpans` that scans nested-brace-aware,
  string-aware spans and tries each candidate.
- **(c) Predicate over-strictness in `unwrapProviderEnvelope`** — even
  if a candidate parses, `isWorkerResultCandidate`'s weak OR-check could
  reject a valid worker_result that happens to omit one optional field.
  Fix S2.2: require `status` AND one of `{changed_files, summary,
  evidence}`.

### S1.2 — Why retries didn't happen

`packages/orchestrator/src/taskExecutor.ts` currently has no
recovery-action dispatch for `failure_class: "malformed_result"`. The
`state.recovery[]` field is the spec's hook for retry policy, but no code
populates it; the worker_result is recorded as the final attempt and
`taskExecutor` returns.

### S1.3 — Why cost wasn't recorded

`metadataFromParsed` (line 310-317) extracts `evidence.usage`. The
worker_result JSON inside the fenced block DOES contain `evidence.usage`,
but `parseWorkerOutput` failed before we ever reached `metadataFromParsed`.
Even if parsing had succeeded with the worker_result, the **provider-attested**
usage at the envelope top level (`{usage: {input_tokens, cache_*}}`) was
never extracted — `metadataFromParsed` only knows about
`worker.evidence.usage`. The envelope is discarded after `unwrapProviderEnvelope`.

---

## S2. Worker output parser hardening (R1 — D-09)

### S2.1 — New `parseJsonText` behavior

```ts
function parseJsonText(value: string): unknown | null {
  const trimmed = value.trim();

  // 1. Try direct JSON.
  const direct = tryParseJson(trimmed);
  if (direct && isWorkerResultCandidate(direct)) return direct;
  if (direct) {
    // Direct JSON parsed but isn't a worker_result — keep as fallback only.
  }

  // 2. Try all fenced blocks, json-labeled first.
  const allFences = [...trimmed.matchAll(/```(\w+)?\s*([\s\S]*?)```/g)];
  const ordered = [
    ...allFences.filter(m => m[1]?.toLowerCase() === "json"),
    ...allFences.filter(m => !m[1]),
    ...allFences.filter(m => m[1] && m[1].toLowerCase() !== "json")
  ];
  for (const match of ordered) {
    const parsed = tryParseJson(match[2]?.trim() ?? "");
    if (parsed && isWorkerResultCandidate(parsed)) return parsed;
  }

  // 3. Brace-span enumeration: try every balanced {...} span, largest first.
  for (const span of enumerateBalancedBraceSpans(trimmed)) {
    const parsed = tryParseJson(span);
    if (parsed && isWorkerResultCandidate(parsed)) return parsed;
  }

  // 4. Fall through to direct (worker_result-shaped or not) for legacy
  // demo plans whose result is JSON without a fence.
  return direct;
}
```

`enumerateBalancedBraceSpans` is **string-aware** brace counting:

```ts
function* enumerateBalancedBraceSpans(text: string): Generator<string> {
  type Span = { start: number; end: number };
  const spans: Span[] = [];
  let i = 0;
  while (i < text.length) {
    if (text[i] !== "{") { i += 1; continue; }
    const start = i;
    let depth = 0;
    let inString = false;
    let escaped = false;
    while (i < text.length) {
      const ch = text[i];
      if (escaped) { escaped = false; i += 1; continue; }
      if (inString) {
        if (ch === "\\") { escaped = true; }
        else if (ch === '"') { inString = false; }
        i += 1;
        continue;
      }
      if (ch === '"') { inString = true; i += 1; continue; }
      if (ch === "{") depth += 1;
      else if (ch === "}") {
        depth -= 1;
        if (depth === 0) {
          spans.push({ start, end: i + 1 });
          i += 1;
          break;
        }
      }
      i += 1;
    }
    if (depth > 0) break;  // unterminated; bail
  }
  // Largest first — worker_result JSON is typically the biggest brace span.
  spans.sort((a, b) => (b.end - b.start) - (a.end - a.start));
  for (const s of spans) yield text.slice(s.start, s.end);
}
```

Key invariants:
- Skips `{`/`}` inside double-quoted strings; honors `\"` escape.
- Skips `\` followed by any char inside a string (preserves `\\`, `\n`,
  `\\\"`, etc.).
- Yields **largest span first** — the worker_result JSON is typically
  larger than any quoted JSON sample inside the narrative.
- Bails on unbalanced (no infinite loop).

### S2.2 — `isWorkerResultCandidate` minor tightening

Current: requires `status | changed_files | summary | failure_class`.
New: requires `status` AND one of `changed_files | summary | evidence`.
This still rejects the bare envelope (no `status` field) and still accepts
both completed and failed worker_results.

### S2.3 — `unwrapProviderEnvelope` recursive search

**Existing behavior** (`processAdapters.ts:256–274`, kept):
the function already iterates `value.result`, `value.message`,
`value.text`, and `value.item.text`, returning the first nested-parsed
worker_result candidate. The bug was *not* missing paths; it was that
(a) the inner `parseJsonText` matched the wrong fence (S2.1) and
(b) the envelope was discarded after unwrap, so envelope-level `usage`
became inaccessible (S6).

**New behavior** (this delta):

```ts
function unwrapProviderEnvelope(
  parsed: unknown
): { unwrapped: unknown; envelope: unknown | null } {
  if (!parsed || typeof parsed !== "object") {
    return { unwrapped: parsed, envelope: null };
  }
  const envelope = parsed;

  // (A) Existing direct paths — unchanged set, but now uses the hardened
  //     parseJsonText from S2.1 and returns the envelope alongside.
  for (const path of [
    ["result"], ["message"], ["text"], ["item", "text"]
  ] as const) {
    const nested = readPath(parsed, path);
    if (typeof nested === "string") {
      const candidate = parseJsonText(nested);
      if (candidate && isWorkerResultCandidate(candidate)) {
        return { unwrapped: candidate, envelope };
      }
    }
  }

  // (B) NEW: depth-≤3 string-leaf fallback for envelope shapes we
  //     haven't seen yet (e.g., codex's stream-json `delta.text`,
  //     ACP-style nested events).
  for (const leaf of stringLeaves(parsed, /*max_depth*/ 3)) {
    const candidate = parseJsonText(leaf);
    if (candidate && isWorkerResultCandidate(candidate)) {
      return { unwrapped: candidate, envelope };
    }
  }
  return { unwrapped: parsed, envelope: null };
}
```

Two changes, both additive:

1. **Return the envelope alongside the unwrapped result** so S6 can
   read `envelope.usage` / `envelope.modelUsage`. Existing callers that
   destructured a plain `unknown` need a one-line shim
   (`const { unwrapped } = unwrapProviderEnvelope(parsed)`); the second
   field is optional and ignored when unused.
2. **Add a depth-≤3 string-leaf scan** as a fallback after the four
   known paths miss. This handles future provider shapes without
   re-enumerating named paths every release. Bounded depth keeps the
   scan O(envelope-size) and avoids cycles (envelopes are tree-shaped
   JSON).

`parseJsonText` is shared with S2.1, so the hardening (fence-label
ordering + balanced-brace fallback) automatically applies to every
nested string leaf as well.

---

## S3. Recovery policy matrix (R2 — D-10)

### S3.1 — `recoveryExecutor.ts` API

```ts
export type RecoveryAction =
  | "retry_with_strict_prompt"
  | "retry_with_evidence"
  | "request_decision"
  | "halt";

export interface RecoveryDecision {
  action: RecoveryAction;
  attempt_number: number;
  max_attempts: number;
  strict_prompt_suffix?: string;
}

export function nextRecoveryAction(
  failure_class: FailureClass,
  prior_attempts: number,
  options?: { max_overrides?: Partial<Record<FailureClass, number>> }
): RecoveryDecision;
```

### S3.2 — Default matrix

| failure_class | action | max_attempts | rationale |
|--------------|--------|--------------|-----------|
| `malformed_result` | retry_with_strict_prompt | 2 | parser may have caught the wrong fence (S2); strict prompt asks for json-fence-only |
| `verification_failed` | retry_with_evidence | 3 | implementer may have missed a constraint; evidence injection helps |
| `timeout` | request_decision | 1 | usually env issue; surface to operator |
| `adapter_crashed` | retry_with_strict_prompt | 1 | could be transient; retry once |
| `permission_denied` | request_decision | 1 | sandbox tuning needed (cf. D-11) |
| `cancelled` | halt | 0 | user-initiated; do not retry |
| `diff_scope_failed` | retry_with_evidence | 2 | provide diff scope rules in prompt |
| `review_changes_requested` | retry_with_evidence | 3 | reviewer feedback injected |
| `review_rejected` | request_decision | 1 | needs human triage |
| `merge_conflict` | request_decision | 1 | needs rebase context |
| `needs_rebase` | request_decision | 1 | base moved; user picks strategy |
| `needs_plan_fix` | halt | 0 | plan-level defect, not worker-fixable |
| `needs_split` | halt | 0 | plan-level defect |
| `needs_infra_fix` | request_decision | 1 | env-level |
| `missing_checkpoint` | retry_with_strict_prompt | 1 | worker forgot to write artifact |
| `missing_resume_handler` | request_decision | 1 | rare |
| `service_unreachable` | retry_with_strict_prompt | 2 | typically transient |
| `dependency_missing` | request_decision | 1 | env tuning |
| `environment_blocker` | request_decision | 1 | env tuning |
| `flaky_unconfirmed` | retry_with_evidence | 2 | retry to confirm |
| `command_not_found` | request_decision | 1 | env tuning |
| `dependency_blocked` | request_decision | 1 | upstream task needed |
| `file_claim_conflict` | request_decision | 1 | claims need rework |
| `dirty_source_checkout` | request_decision | 1 | env reset needed |
| `unsafe_apply` | request_decision | 1 | needs human approval |
| `state_drift` | request_decision | 1 | needs reconcile |
| `artifact_missing` | retry_with_strict_prompt | 1 | worker should regenerate |
| `stale_activity` | request_decision | 1 | review needed |
| `terminal_rejected` | halt | 0 | hard reject |

### S3.3 — Strict-prompt suffix template

Used when action is `retry_with_strict_prompt`:

```
PRIOR ATTEMPT (#<n>) FAILED.
failure_class: <class>
prior_summary: <truncated to 240 chars>

You MUST respond with ONLY a single fenced ```json block containing the
runway.worker_result.v1 object. Required fields: schema, task_id,
candidate_id, status, changed_files, summary, evidence. No prose before
or after the fence. No additional fenced blocks of any language.
```

### S3.4 — Wire site in `taskExecutor.ts`

After `executeWaygentTask` returns a result with `failure_class`, call
`nextRecoveryAction(failure_class, previousAttempts.length)`. If
`retry_with_*`, build a new `AdapterRequest` with `previous_failures[]`
appended to the task_packet, dispatch again. Emit
`runway.recovery_attempt` event per retry.

---

## S4. Plan body propagation (R3 — D-06)

### S4.1 — Current data flow (broken)

```
plan.md
  → planParser.parseWaygentPlan → ParsedWaygentTask{ instructions: [] /* often empty */ }
    → buildTaskGraphFromPlan
      → taskPacket.build → task_packet { plan_excerpt: task.title }
        → Implementer sees only title
```

### S4.2 — New data flow

```
plan.md
  → planParser.parseWaygentPlan
      → locate each yaml waygent-task fence offset in markdown
      → for each task, find preceding "### Task N:" or "## Task N:" heading
      → slice markdown[heading_end : yaml_fence_start]
      → run extractInstructionLines on the slice
      → if yaml.instructions is empty, replace with the extracted lines
      → ParsedWaygentTask{ instructions: [<step-by-step lines>] }
    → buildTaskGraphFromPlan (unchanged)
      → taskPacket.build → task_packet {
          plan_excerpt: task.title + "\n\n" + task.instructions.join("\n"),
          plan_body_truncated: <true if capped at context_budget>
        }
```

### S4.3 — `extractInstructionLines` reuse

`planNormalizer.ts:182-193` already has `extractInstructionLines` —
strips RUN_BLOCK git-mutating commands, trims, caps at 160 lines. Move
this function out of `planNormalizer.ts` into a new file
`packages/orchestrator/src/planAdapters/instructionsExtract.ts` and
import from both `planParser` and `planNormalizer`.

### S4.4 — Backward compatibility

- If a yaml waygent-task author explicitly sets `instructions:` in the
  block, the explicit value WINS (do not overwrite with extracted prose).
- If a plan has no `### Task N:` heading before a yaml block (pure native
  plan, no superpowers wrapper), `instructions` stays whatever the yaml
  declared (often empty). No behavior change for native plans.
- New optional flag `--inherit-plan-prose <on|off>` (default `on`).

### S4.5 — Token budget interaction

`WaygentTaskPacket.context_budget.max_chars` (sourced from
`BuildTaskPacketInput.max_chars`, default **60 000 chars** —
`packages/context-packer/src/taskPacket.ts:27`) governs total packet size.
The plan-excerpt expansion is capped to preserve the original design
intent (≤ ~12 000 chars for `plan_excerpt`, leaving headroom for
`spec_excerpt`, `decisions`, `previous_failures`, and `evidence`):

```ts
const PLAN_EXCERPT_HARD_CAP = 12_000;          // absolute ceiling
const PLAN_EXCERPT_BUDGET_FRACTION = 0.4;      // share of context_budget
const limit = Math.min(
  PLAN_EXCERPT_HARD_CAP,
  Math.floor(maxChars * PLAN_EXCERPT_BUDGET_FRACTION)
);

const combined = `${task.title}\n\n${task.instructions.join("\n")}`;
if (combined.length <= limit) {
  packet.plan_excerpt = combined;
  packet.plan_body_truncated = false;
} else {
  packet.plan_excerpt = `${combined.slice(0, limit - 12)} [truncated]`;
  packet.plan_body_truncated = true;
}
```

Two reasons for `min(60000 × 0.4, 12000) = 12000`:

1. At the actual 60 000-char default, a naive `× 0.4` would let the plan
   excerpt consume 24 000 chars — 5× the share the design was budgeted
   against. The hard cap keeps the apportionment within the implementer's
   working-context sweet spot (Opus 200K but task-local working set
   stays compact).
2. A small embedded default (`max_chars = 4_000` in some test packets)
   would otherwise yield `1600` for plan_excerpt — fine via the
   `min()` rule.

Naming note: the **spec-level** term `context_budget` is the
`WaygentTaskPacket.context_budget` *object* in the contract; its
controlling integer is `max_chars`. The `BuildTaskPacketInput` parameter
of the same magnitude is also `max_chars`. The two are equivalent.

---

## S5. Project script catalog + risk inference (R4 — D-01, D-07)

### S5.1 — `ProjectScriptCatalog` interface

```ts
export interface ProjectScriptCatalog {
  commands: Set<string>;        // e.g. {"npm run test", "npm run source-matching:fixtures:test", "make build"}
  sources: Map<string, "npm" | "pnpm" | "yarn" | "bun" | "make" | "poetry" | "project">;
  workspace_root: string;
}

export function buildProjectScriptCatalog(workspace: string): ProjectScriptCatalog;
```

Discovery rules:

- `package.json` `scripts.*`: emit `npm run <name>`, `pnpm run <name>`,
  `bun run <name>`, `yarn <name>` (4 variants per script).
- `Makefile` non-comment top-level targets (`^([a-zA-Z][a-zA-Z0-9_-]*):
  `): emit `make <name>`.
- `pyproject.toml` `[tool.poetry.scripts]` and `[project.scripts]`:
  emit `poetry run <name>` and bare `<name>`.
- Cargo.toml: skip (cargo subcommands already in hard-coded allowlist).

### S5.2 — Updated `isSafeVerificationCommand`

```ts
function isSafeVerificationCommand(
  command: string,
  catalog: ProjectScriptCatalog,
  options: { unsafe: boolean }
): boolean {
  if (options.unsafe) return true;
  const normalized = command.replace(/\s+/g, " ").trim();
  const parts = normalized.split(/\s+&&\s+/);
  return parts.every((part, idx) => {
    if (idx === 0 && part.startsWith("cd ")) return true;
    return HARD_CODED_PREFIXES.some(p => part.startsWith(p)) ||
           catalog.commands.has(part) ||
           [...catalog.commands].some(cmd => part.startsWith(cmd + " "));
  });
}
```

`HARD_CODED_PREFIXES` keeps the existing build-tool list (`bun test`,
`cargo test`, `git diff --check`, etc.) for cases where no
package.json/Makefile is present.

### S5.3 — Risk inference rules

```ts
export function inferRiskLevel(input: {
  title: string;
  body: string;
  file_claims: FileClaim[];
}): { risk: RiskLevel; reason: string } {
  const text = `${input.title}\n${input.body}`;
  const highKeywords = /\b(schema migration|database migration|public api|breaking change|production deploy|secrets?|credentials?|auth(entication)?)\b/i;
  if (highKeywords.test(text)) {
    return { risk: "high", reason: "high-risk keyword match" };
  }
  const highPaths = /(migration|schema|public-api|production|secrets?)/i;
  if (input.file_claims.length > 10 || input.file_claims.some(c => highPaths.test(c.path))) {
    return { risk: "high", reason: "high file_claim count or sensitive path" };
  }
  const topLevelDirs = new Set(input.file_claims.map(c => c.path.split("/")[0]));
  if (topLevelDirs.size > 1) {
    return { risk: "medium", reason: "cross-package claims" };
  }
  return { risk: "low", reason: "single-package, no risk keyword" };
}
```

Persist the chosen risk + reason in `normalized_plan.diagnostics[]` so the
operator can see WHY a level was picked.

### S5.4 — Trivial-verify guard (D-07)

```ts
const TRIVIAL_TOKENS = new Set(["printf", "true", ":", "echo", "/usr/bin/true"]);

export function isTrivialVerifyCommand(cmd: string): boolean {
  const first = cmd.trim().split(/\s+/)[0] ?? "";
  return TRIVIAL_TOKENS.has(first);
}

export function detectVerifyTheater(task: ParsedWaygentTask): {
  is_theater: boolean;
  reasons: string[];
} {
  const reasons: string[] = [];
  if (task.verification_commands.length === 0) {
    reasons.push("no verify commands");
  } else if (task.verification_commands.every(isTrivialVerifyCommand)) {
    reasons.push("all verify commands are trivial");
  }
  const claimPaths = new Set(task.file_claims.map(c => c.path));
  const referencedPaths = task.verification_commands.flatMap(extractPathTokens);
  if (claimPaths.size > 0 && !referencedPaths.some(p => [...claimPaths].some(c => p.includes(c.replace(/\*+$/, ""))))) {
    reasons.push("verify does not reference any claimed file");
  }
  return { is_theater: reasons.length > 0, reasons };
}
```

When detected, emit `runway.verification_quality_warning` event. With
`--reject-trivial-verify`, the normalizer throws instead.

---

## S6. Cost ledger envelope extraction (R5 — D-08)

### S6.1 — New `metadataFromParsed` signature

```ts
function metadataFromParsed(
  provider: "codex" | "claude" | "acp",
  parsed: Partial<WorkerResult>,
  envelope: unknown | null
): ProviderRunMetadata;
```

The `envelope` param is the original provider envelope returned by
`unwrapProviderEnvelope` (S2.3).

### S6.2 — Envelope usage extraction (claude shape)

```ts
function usageFromEnvelope(envelope: unknown): TokenUsage | null {
  if (!envelope || typeof envelope !== "object") return null;
  const e = envelope as Record<string, unknown>;
  const u = e.usage;
  if (!u || typeof u !== "object") return null;
  const r = u as Record<string, unknown>;
  const input = numberField(r.input_tokens);
  const output = numberField(r.output_tokens);
  // Cache fields are LENIENT: older claude versions may omit
  // cache_read_input_tokens / cache_creation_input_tokens entirely.
  // Treat missing/null as 0 (no caching happened) rather than failing
  // the whole extraction. Only input_tokens + output_tokens are
  // load-bearing for cost; cache fields are informational.
  const cacheRead = numberField(r.cache_read_input_tokens) ?? 0;
  const cacheCreate = numberField(r.cache_creation_input_tokens) ?? 0;
  if (input === null || output === null) return null;
  return {
    input_tokens: input,
    output_tokens: output,
    cached_read_tokens: cacheRead,
    cached_write_tokens: cacheCreate
  };
}
```

Lenience rule rationale: claude `--output-format json` envelope schema
varies across versions. Required fields for cost computation are
`input_tokens` and `output_tokens` only (priced via PRICE_TABLE_USD_PER_MILLION
in `costLedger.ts`). Cache token counts ride along for telemetry but
don't affect billing, so a missing cache field should not collapse the
extraction to `usage: null` (which would then propagate as
`usage_source: "missing_in_provider_output"` and trigger
`--require-cost-data` failures incorrectly).

```ts
// numberField signature reminder (unchanged):
function numberField(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.trunc(value)
    : null;
}
```

Precedence in `metadataFromParsed`:

1. `usageFromEnvelope(envelope)` — provider-attested, most authoritative.
2. `usageFromEvidence(worker.evidence)` — worker self-report (legacy).
3. `null` → `usage_source: "missing_in_provider_output"`.

### S6.3 — Model attestation from envelope

Claude envelope has `modelUsage: { "<model-id>": {...} }`. Take the first
key as `actual_model.model`. Source: `"provider_json"`.

### S6.4 — Codex parity (already correct)

Codex JSONL stream emits `usage` at the result event already; existing
`metadataFromParsed` path that reads `parsed.evidence` works because
codex puts usage at worker_result.evidence.usage. The envelope path is
no-op for codex (envelope === parsed worker_result, no nesting).

### S6.5 — `--require-cost-data` fail-fast

New CLI flag on `waygent run`. When set, after each task dispatch:

```ts
if (metadata.usage_source === "missing_in_provider_output" || metadata.usage_source === "unknown") {
  throw new Error(`cost_data_missing: task ${task_id} dispatch produced no usage telemetry`);
}
```

Default off (additive); CI users can opt in.

### S6.6 — `waygent cost` zero-output warning

In `runCommands.ts` `costRun`, after building the ledger view, write to
stderr if `totals.input_tokens + totals.output_tokens === 0` AND
`totals.dispatches > 0`:

```
WARN: cost ledger has 0 token usage across <N> dispatches. Provider
adapter may not be parsing usage. Inspect:
  artifacts/provider/*.stdout.txt (look for top-level "usage" key)
  events.jsonl (look for platform.cost_accumulated events with usage:null)
```

---

## S7. CLI surface (R6 — D-02, D-03, D-04)

### S7.1 — `--run` auto-generation

When `parsed.flags.run` is unset for `run` / `run-chain` / `demo`:

```ts
// New shared module: packages/orchestrator/src/runIdDerivation.ts
export function deriveAutoRunId(planPath: string, now: Date = new Date()): string {
  const base = basename(planPath, ".md").replace(/^\d{4}-\d{2}-\d{2}-/, "");
  const slug = base.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const ts = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "").replace("T", "_");
  return `${slug}_${ts}`;
}
```

Example: plan `2026-05-20-trustworthy-source-matching-local-fixture-lab.md` →
run_id `trustworthy_source_matching_local_fixture_lab_20260522_193045`.

**`runWaygent` signature stays backward-compatible.** `options.run_id?`
remains OPTIONAL. The current default at
`packages/orchestrator/src/orchestrator.ts:75`
(`const runId = options.run_id ?? "run_demo";`) is replaced with:

```ts
const runId = options.run_id ?? deriveAutoRunId(planInput.path ?? "unnamed-plan");
```

The literal `"run_demo"` magic constant disappears from `orchestrator.ts`.
~25+ existing internal callers in `packages/orchestrator/tests/` and
`packages/orchestrator/src/planChain.ts` pass `run_id` explicitly
(typically `"run_demo"` or a test-specific value) and continue to work
unchanged. Only the *default* changes, not the *signature*. (Verified
counter at 2026-05-22 source audit: 24 calls across 7 test files +
1 in `planChain.ts` + 1 internal wrapper in `runWaygentDemo`.)

CLI layer (`apps/cli/src/index.ts`) also calls `deriveAutoRunId` so the
user sees a meaningful, plan-derived id in the dispatch echo line (S7.5)
even when not passing `--run`. The shared module guarantees CLI and
orchestrator derive the same id for the same plan path within the same
second.

**Collision handling — strictly at the CLI layer.** When two
`runWaygent` calls within the same second derive the same id, the second
`hasExistingRunEvidence(paths)` check (`orchestrator.ts:471–478`) throws
`run_id_already_exists` synchronously *during* `runWaygent` setup. The
orchestrator does NOT retry internally — retrying inside `runWaygent`
would require restructuring its setup-then-dispatch flow and could
break the contract that "after `runWaygent` resolves, the run is
mounted at the resolved `run_id`."

Instead, retry lives in `runCli` (`apps/cli/src/index.ts`):

```ts
let attempt = 0;
let runId = deriveAutoRunId(planPath);
while (true) {
  try {
    return await runWaygent({ ...options, run_id: runId });
  } catch (err) {
    if (!(err instanceof Error) || err.message !== "run_id_already_exists") throw err;
    attempt += 1;
    if (attempt > 9) throw new Error(`run_id_already_exists after 9 retries: ${runId}`);
    runId = `${deriveAutoRunId(planPath)}_${attempt + 1}`;
  }
}
```

Programmatic callers (tests, `planChain`) pass explicit `run_id` and
therefore never hit this path. The retry is a CLI-ergonomics affordance,
not part of the orchestrator's contract.

### S7.2 — Block-list `dependencies` (D-02)

```ts
// Inside parseTaskBlock loop, when key === "dependencies":
if (line === "dependencies:" || line.startsWith("dependencies:")) {
  const inline = line.slice("dependencies:".length).trim();
  if (inline.startsWith("[")) {
    scalar.set("dependencies", inline);  // existing inline path
  } else if (inline.length === 0) {
    const deps: string[] = [];
    index = readStringList(lines, index + 1, deps) - 1;
    scalar.set("dependencies", `[${deps.join(", ")}]`);  // synthesize inline shape
  } else {
    scalar.set("dependencies", inline);  // legacy bare-token shape
  }
  continue;
}
```

This keeps `parseInlineList` downstream signature unchanged but
normalizes block-list input to inline-list form before parsing.

### S7.3 — Help text exposure (D-04)

`commandUsage.run` becomes:

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

### S7.4 — Profile presets

| Preset | provider=claude | provider=codex | provider=fake |
|--------|-----------------|----------------|---------------|
| `cost-saver` | main=sonnet(medium), sub=haiku(low) | main=gpt-5.3-codex(medium), sub=gpt-5.3-codex(low) | main=fake, sub=fake |
| `balanced` (new per-provider default) | main=opus(high), sub=sonnet(medium) | main=gpt-5.4(high), sub=gpt-5.3-codex(medium) | main=fake, sub=fake |
| `max-quality` | main=opus(high), sub=opus(high) | main=gpt-5.5(high), sub=gpt-5.4(high) | main=fake, sub=fake |

Two distinct defaults that must not be conflated:

1. **`--provider` default for `waygent run` stays `codex`**
   (`apps/cli/src/index.ts:73`, `defaultProvider`). The audit-time
   default is unchanged; only the *profile* shape changes.
2. **`--profile` default becomes `balanced`** (was: implicit
   `provider`-keyed default that produced `main=opus, sub=opus` for
   `provider=claude`). This change is observable only when the user
   explicitly chooses `--provider claude`.

Resolution order: explicit `--main-model` / `--subagent-model`
(`apps/cli/src/index.ts:81–84`, already parsed) > `--profile` >
provider default. Echo line (S7.5) records the resolution path, e.g.,
`main=opus[from balanced preset], sub=sonnet[from balanced preset]` so
operators can see which knob actually picked the model.

### S7.5 — Dispatch-start echo line

Before first task dispatch, emit `runway.dispatch_plan_echoed`
agentlens event AND stderr line:

```
[waygent] Parsed: <N> task(s) [<task_1_id>...<task_N_id>], provider=<provider>,
main=<model>(<reasoning>)[from <source>], sub=<model>(<reasoning>)[from <source>],
budget=<usd or off>, run_id=<id>.
```

---

## S8. Worker sandbox exec allowlist (R7 — D-11)

### S8.1 — `task_packet.allowed_exec_commands` population

```ts
function buildAllowedExecCommands(
  workspace: string,
  task: ParsedWaygentTask
): string[] {
  const catalog = buildProjectScriptCatalog(workspace);
  return [
    ...catalog.commands,              // all project scripts
    ...task.verification_commands,    // the task's own verify commands
    ...READ_ONLY_UTILITIES            // ls, cat, head, tail, grep, etc.
  ];
}

const READ_ONLY_UTILITIES = [
  "ls", "cat", "head", "tail", "grep", "find . -name",
  "git status", "git diff", "git log --oneline -n",
  "node --test", "node -e",
  "bun test", "bun run check"
];
```

### S8.2 — Prompt surfacing

In `buildProviderPrompt`, when `task_packet.allowed_exec_commands` is
non-null/non-empty, append:

```
You may invoke these commands during self-verification (others will be denied):
  <allowed_exec_commands.join("\n  ")>
You SHOULD invoke the verification commands listed in task_packet.acceptance_commands
before returning status:completed.
```

### S8.3 — Denial event emission

In `processAdapters.ts`, after parsing the envelope, if envelope has
`permission_denials: [...]`:

```ts
for (const denial of envelope.permission_denials ?? []) {
  emit({
    event_type: "runway.worker_permission_denied",
    payload: {
      task_id,
      attempted_command: denial.tool_input?.command,
      suggested_allowlist_entry: suggestAllowlistEntry(denial.tool_input?.command),
      tool_name: denial.tool_name
    }
  });
}
```

`suggestAllowlistEntry` extracts the first token; for `node --test foo`
suggests adding `"node --test"` to `READ_ONLY_UTILITIES` or to project
package.json scripts.

---

## S9. Persistent state root (R8 — D-05)

### S9.1 — Platform defaults

| Platform | Default root |
|----------|--------------|
| darwin | `$HOME/Library/Application Support/waygent/runs/` |
| linux | `${XDG_DATA_HOME:-$HOME/.local/share}/waygent/runs/` |
| win32 | `%LOCALAPPDATA%/waygent/runs/` |
| other | `$TMPDIR/waygent-runs/` (with stderr WARN) |

Auto-create on first use via `mkdirSync(root, { recursive: true })`.

### S9.2 — Backward-compatible orphan scan

`waygent orphans` (with no `--root` flag) scans:

1. The new default per S9.1.
2. The legacy `$TMPDIR/waygent-runs/` (current production behavior).
3. Both lists merged in the output; entries from #2 are tagged
   `migration_suggested: true` and the report ends with:
   `Consider copying old runs to new default: cp -r "$TMPDIR/waygent-runs/." "<new default>/"`.

### S9.3 — Migration doc

`docs/operations/state-root-migration.md` covers:

- Rationale (macOS `/var/folders/.../T/` is volatile).
- Manual copy command (above).
- `--root <path>` override (unchanged; CI users can pin).
- Disk-usage note: each run averages ~50 MB; runs accumulate unless
  pruned via `waygent orphans --delete <id> --yes`.

---

## S10. Schema deltas (additive only)

### S10.1 — `waygent.task_packet.v1`

Add OPTIONAL fields:

```ts
interface WaygentTaskPacketV1 {
  // ... existing fields ...
  allowed_exec_commands?: string[] | null;   // already in artifact, now typed
  plan_body_truncated?: boolean;             // NEW
  previous_failures?: Array<{                 // NEW (for retry context)
    failure_class: FailureClass;
    summary: string;
    attempt_number: number;
  }>;
}
```

### S10.2 — `agentlens.event.v3` — new `event_type` values

All additive (no envelope change):

- `runway.recovery_attempt`
- `runway.verification_quality_warning`
- `runway.unsafe_verification_enabled`
- `runway.dispatch_plan_echoed`
- `runway.worker_permission_denied`
- `runway.cost_data_missing` (only emitted with `--require-cost-data`)

Each payload spec:

```ts
"runway.recovery_attempt": {
  task_id: string;
  attempt_number: number;
  max_attempts: number;
  failure_class: FailureClass;
  recovery_action: RecoveryAction;
};

"runway.verification_quality_warning": {
  task_id: string;
  verify: string[];
  reasons: string[];      // e.g. ["all verify commands are trivial"]
};

"runway.unsafe_verification_enabled": { run_id: string };

"runway.dispatch_plan_echoed": {
  run_id: string;
  task_count: number;
  task_ids: string[];
  provider: string;
  main: { model: string | null; reasoning: string | null; source: string };
  subagent: { model: string | null; reasoning: string | null; source: string };
  budget_cap_usd: number | null;
  expected_cost_estimate_usd: number;
};

"runway.worker_permission_denied": {
  task_id: string;
  attempted_command: string;
  tool_name: string;
  suggested_allowlist_entry: string;
};
```

### S10.3 — `waygent.run_state.v2` — no change

All retry/recovery state lives in the existing
`state.tasks[id].attempts[]` array. The new `recoveryExecutor` only reads
from this array and writes new attempt entries; no new top-level fields.

---

## S11. Test strategy

### S11.1 — Fixture files (placed under `tests/fixtures/`)

| Fixture | Source | Purpose |
|---------|--------|---------|
| `claude_task_3_narrative_then_json.stdout.txt` | failed run artifact bytes | D-09 parser regression |
| `claude_envelope_with_top_usage.stdout.txt` | same artifact (used for S6) | D-08 usage extraction |
| `fixture_lab_plan.md` | copy of FixThis plan | D-01 normalizer accept |
| `fixture_lab_design.md` | copy of FixThis spec | D-06 plan-body propagation (paired with above) |
| `superpowers_plan_with_block_deps.md` | hand-crafted | D-02 deps parsing |
| `superpowers_plan_with_trivial_verify.md` | hand-crafted | D-07 trivial-verify detection |
| `package.json.fixture_lab` | hand-crafted (mirrors FixThis npm scripts) | D-01/D-11 catalog source |

### S11.2 — Test matrix

| Module | New test files | Coverage targets |
|--------|----------------|-------------------|
| `provider-adapters` | `parseWorkerOutput.test.ts`, `usageExtraction.test.ts` | 100% of `parseJsonText`, `unwrapProviderEnvelope`, `metadataFromParsed`; envelope shapes for claude json, claude stream-json (skip if unavailable), codex JSONL |
| `orchestrator` | `recoveryExecutor.test.ts`, `planParser.bodyPropagation.test.ts`, `planParser.deps.test.ts`, `projectScriptCatalog.test.ts`, `riskInference.test.ts`, `planNormalizer.fixtureLab.test.ts`, `defaultRunRoot.test.ts` | each policy matrix entry; both inline and block deps; npm/pnpm/yarn/bun/make/poetry catalog; 6 risk inference cases; fixture-lab plan accept; per-platform root paths |
| `context-packer` | `taskPacket.planExcerpt.test.ts`, `taskPacket.execAllowlist.test.ts` | plan body propagation cap; allowlist union content |
| `apps/cli` | `runIdAutoGen.test.ts`, `profilePreset.test.ts` | uniqueness across calls; preset resolution order |

### S11.3 — Scenario replay

Add 2 new scenarios to `bun run waygent:scenarios`:

1. `claude_narrative_wrapped_worker_result` — round-trips the literal
   task_3 stdout and asserts task completes (with the parser fix). Asserts
   `cost.totals.input_tokens > 0` (with S6 fix).
2. `superpowers_plan_with_project_scripts` — runs a fake-provider plan
   with `npm run domain:test` verify commands and a fake package.json;
   asserts the plan normalizes without throw and the dispatched task
   includes the verify commands in `allowed_exec_commands`.

### S11.4 — End-to-end replay (manual, post-merge)

Documented in plan § "Cross-cutting verification". The original failed
fixture-lab plan must run to 5/5 COMPLETE with `--profile balanced` at
expected cost ≤ $0.50.

---

## S12. Non-changes / explicit out-of-scope

- **No** modification of `agentlens.event.v3` envelope shape; only new
  `event_type` enum entries.
- **No** modification of `costLedger.ts` (the bug was upstream in
  `metadataFromParsed`).
- **No** modification of `waygent.run_state.v2` top-level fields.
- **No** changes to per-task worktree model (waygent's per-task isolation
  is a strength worth keeping — see comparison analysis § 4.5).
- **No** plan reviewer addition (kws-CME's Phase 0 Step 6.5 pattern is a
  separate sprint).
- **No** sub-agent per-call cost split beyond what `costLedger.by_role`
  already supports (the role bucket is populated by `recordProviderAttemptCost`
  if `role` is passed; current dispatch already passes `role: "implement"`
  vs `role: "review"` where applicable).

---

## S13. Migration & rollout

This is a code change to the waygent runtime; no data migration needed
beyond the optional state-root move (S9). Sequence:

1. Land Task 1 (parser) — alone, this rescues claude runs that have been
   silently failing. Lowest-risk single-PR landing.
2. Land Task 5 (cost extraction) immediately after — depends on Task 1's
   envelope-preserving `unwrapProviderEnvelope`.
3. Land Tasks 2 + 3 + 6 together — they share the
   `ProjectScriptCatalog` module and the planAdapters/instructionsExtract
   refactor.
4. Land Task 4 (CLI) — depends only on prior tasks for `--profile`'s
   model wiring.
5. Land Task 7 (state root) — independent, can land first or last;
   includes its own backward-compat orphan scan.

Each task ships with regression tests. After all tasks merge, the
end-to-end replay in plan § "Cross-cutting verification" is the
acceptance gate.
