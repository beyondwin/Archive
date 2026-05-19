# AgentLens Importer Hardening + Usage Summary — Design Spec

**Date:** 2026-05-19
**Status:** Draft
**Scope:** AgentLens v1 importers (`claude-session`, `codex-session`), query projections, dashboard surface
**Adopts:** `docs/adr/2026-05-19-agentlens-ecosystem-benchmark.md` §5.2 (large-session safety), §5.3 (usage ledger), §5.6 (title heuristic)
**Defers:** §5.5 safe export, §5.7 read-only TUI (post-v1.x)
**Local baseline:** `docs/contract.md`, `docs/security.md`, `docs/spec/2026-05-19-agentlens-dashboard-design.md`

---

## 0.1 Deep Source Review Corrections (2026-05-19)

This section supersedes earlier wording in this spec where there is a conflict. The review checked the current source at `019347ee37747572c28943e80fb18cfad6e58651`; `graphify-out/GRAPH_REPORT.md` was read first per repo policy, but it was built from older commit `2b964330`, so source files below are authoritative.

1. **Importer lifecycle correction.** `commands/import_claude_session.py` and `commands/import_codex_session.py` currently write `run.json`, `events.jsonl`, a transcript copy, and a workspace pointer only. They do **not** write `final.json`, `eval.json`, `manifest.json`, or `index.db` rows. This feature must add an importer finalization pipeline before any claim that `import_report.json` / `usage.json` are manifest-covered or dashboard-queryable.
2. **Evaluator first-event correction.** The evaluator requires the first event to be `run.started`. Current importers begin with `command.started`. Import hardening must prepend a `run.started` event and keep the existing `command.started` / `command.finished` events for compatibility.
3. **Parser memory correction.** Both `_iter_jsonl()` helpers currently call `path.read_text()` and split the entire file. The byte cap cannot be a wrapper around the existing iterator; the parser must be replaced with a binary streaming iterator that tracks byte offsets and line sizes before JSON decoding.
4. **Projection contract correction.** Adding `display_title`, `usage`, and `import_state` is not only a `store/query.py` change. It also requires `commands/_format.py`, snapshot fixtures under `tests/fixtures/format_snapshots/`, generated frontend types (`web/scripts/gen-types.ts` output), and `/api/v1/runs` route payload coverage.
5. **Title source correction.** Current parsed dataclasses do not carry a first user message. The parser must capture `first_user_message_text` while streaming. The redacted display title is **not** written to `run.json`; it is stored as derived data in `artifacts/import_report.json` and may be cached in SQLite.
6. **Transcript privacy correction.** Existing importers copy vendor JSONL with `shutil.copyfile()`; that copy bypasses `store.writer` redaction. This feature must not claim that imported transcripts are newly redacted. It may only claim that the new `import_report.json` and `usage.json` artifacts avoid full prompt/output content, except for the derived redacted title field.
7. **Idempotency correction.** Existing `input.import_key` behaviour is a true no-op on re-import. Re-importing an already-imported session must not overwrite `import_report.json` or `usage.json` in this patch. A future `--refresh` flag can revisit that policy.

## 1. Problem

The current importers (`commands/import_claude_session.py`, `commands/import_codex_session.py`) handle the narrow happy path: locate JSONL, parse parseable lines, write `run.json` / `events.jsonl`, copy the transcript, and stop. Four gaps surface as soon as real-world history is imported:

1. **Partial parses are invisible.** A malformed or oversized line is skipped with a `stderr` warning and the import is otherwise reported as successful. Downstream tooling cannot tell "fully parsed" from "best-effort parsed" from "skipped".
2. **No human-readable run identity.** The dashboard runs list (per the v1 design spec) needs a `display_title`, but importers never extract one. The choices today are `run_id` (random uuid) or empty.
3. **No usage/cost summary.** Tools like `ccusage` already answer "what did this run cost?" from raw vendor logs. AgentLens has the strictly better substrate (sealed, evidence-linked) but does not expose token or cost data at all, so users still leave AgentLens to answer that question.
4. **Imported runs are not sealed/indexed.** The current importer code does not run the wrapper's post-drain pipeline (`final.json` → `seal(pre_eval)` → `eval.json` → `seal(final)` → `index_run`). That makes current docs that say transcripts are manifest-covered aspirational rather than true.

This spec fills these gaps with **additive, contract-stable** changes. Nothing in the locked v1 schema moves. All new fields land as artifacts or query projections.

## 2. Goals & Non-Goals

### Goals

- Make every importer emit a **structured `import_report`** that distinguishes `full` / `partial` / `skipped` analysis and counts skipped lines, oversized rows, and unsupported event types.
- Bound importer memory and runtime via an explicit per-file **byte cap**, with `partial` semantics when the cap is hit.
- Extract a redacted **`display_title`** from each session via a pure heuristic; surface it through query projections only.
- Emit an additive **`usage`** artifact + query projection for every imported run (input/output/cache/reasoning tokens, optional cost, mandatory `confidence` field).
- Finalize imported runs so `final.json`, `eval.json`, `manifest.json`, and the SQLite cache reflect imported sessions like other capture runs.
- Keep all new data covered by `manifest.json` like every other artifact.

### Non-Goals

- Modifying the locked v1 `run.json` / `events.jsonl` / `final.json` / `eval.json` schemas.
- Pricing-table maintenance and currency conversion (v1.x emits `pricing_source="unknown"` and leaves `cost_usd=null`; pricing comes later).
- Sanitized transcript copies for export (§5.5 — deferred).
- Redacting or rewriting the existing raw transcript artifact. This patch may add a future-safe hook, but safe transcript export/sanitization remains §5.5.
- TUI / fuzzy search (§5.7 — deferred).
- Vendor session mutation. Importers remain read-only against `~/.claude/projects/*` and `~/.codex/{sessions,archived_sessions}/*`.

## 3. Design

### 3.1 Import report

Each importer writes one artifact per run:

```
~/.agentlens/runs/<workspace_id>/<run_id>/artifacts/import_report.json
```

Shape (frozen for v1.x; additive thereafter):

```json
{
  "schema_version": "1",
  "source": "claude-session" | "codex-rollout",
  "source_path": "<absolute path to vendor JSONL>",
  "source_session_id": "<id from filename>",
  "analysis_state": "full" | "partial" | "skipped",
  "source_bytes": 12345678,
  "byte_cap_bytes": 67108864,
  "byte_cap_hit": false,
  "lines": {
    "total_scanned": 0,
    "parsed": 0,
    "skipped_malformed": 0,
    "skipped_unsupported_type": 0,
    "skipped_oversized": 0
  },
  "first_error": {
    "line_number": 9876,
    "byte_offset": 4194304,
    "reason": "json_decode|line_too_large|unsupported_type:<name>"
  } | null,
  "transcript_artifact": {
    "copied": true,
    "path": "artifacts/transcripts/<source-session-id>.jsonl",
    "bytes": 12345678
  } | null,
  "derived": {
    "display_title": "<redacted title or null>",
    "title_source": "explicit|first_user_message|null",
    "title_algorithm": "agentlens.title.v1"
  },
  "duration_ms": 0,
  "byte_cap_source": "default" | "env:AGENTLENS_IMPORT_BYTE_CAP" | "flag:--byte-cap"
}
```

**Analysis states:**

| State     | Trigger                                                                                                                                              |
|-----------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `full`    | All lines parsed within `byte_cap_bytes` and no skips of any kind.                                                                                   |
| `partial` | At least one line skipped (malformed / oversized / unsupported), OR `byte_cap_hit=true`. Run is still written; canonical events come from parsed lines only. |
| `skipped` | Source larger than `byte_cap_bytes` AND `--deep-parse-only` is set. Run is created (so the user has a record), no vendor-derived events are emitted, transcript artifact is still copied. |

**Byte cap defaults:**

- Default: 64 MiB (`67_108_864` bytes). Rationale: Codex rollouts of dozens of MB are common; parsing more than this line-by-line may still work, but the default import path must remain bounded and predictable.
- Override 1: `AGENTLENS_IMPORT_BYTE_CAP=<bytes>` environment variable.
- Override 2: `--byte-cap <bytes>` on the import command.

Cap is **per-source-file**; multi-session imports re-apply it per session.

**Per-line size cap:** any single JSONL row over **2 MiB** is treated as `skipped_oversized` (counted in the report, never passed to `json.loads`).

**Unsupported event counting:** a valid vendor line that is intentionally not normalized into an AgentLens event is not automatically unsupported. For Claude, top-level `user`, `assistant`, `system`, and tool-result shapes are supported even if only `assistant.message.content[].tool_use` becomes a `claude.tool_use` event. For Codex, known rollout types such as `session_meta`, `message`, `tool_use`, `tool_result`, `reasoning`, and lifecycle/status records are supported. Increment `skipped_unsupported_type` only when the parser cannot classify the line at all.

### 3.2 Display-title heuristic

Add a pure function:

```python
# src/agentlens/importers/title.py
def extract_display_title(
    *,
    explicit: str | None,
    first_user_message: str | None,
    max_chars: int = 120,
) -> str | None:
    ...
```

**Algorithm (deterministic; no LLM):**

1. If `explicit` is truthy after strip → return it (capped at `max_chars`).
2. If `first_user_message` is `None` or empty after strip → return `None`.
3. Strip these patterns in order, then collapse whitespace:
   - Triple-backtick fenced code blocks (`` ``` `` ... `` ``` ``) — entire block removed.
   - Inline code spans `` ` ... ` `` — span removed (content gone, leaves space).
   - `<<HEADLESS_KWS_ORCHESTRATOR>>` and similar `<<...>>` sentinels — removed.
   - `<AGENTS>...</AGENTS>` and `<system-reminder>...</system-reminder>` blocks — entire block removed (multiline).
   - Lines that begin with `AGENTS:` / `# AGENTS` / `Environment:` / `Working directory:` — line removed.
   - Absolute file paths (regex `(?:/[\w.\-]+){2,}`) — replaced by `<path>`.
   - Control chars `\x00-\x08\x0b\x0c\x0e-\x1f` — removed.
   - URLs (regex `https?://\S+`) — preserved (they often *are* the topic) but capped at 64 chars then truncated with `…`.
4. Take the first non-empty line of what remains.
5. Cap at `max_chars`; if truncated, append `…` (the U+2026 single-character ellipsis, not three dots).
6. If the result is empty or only punctuation/whitespace → return `None`.

**Where it runs:**

- Claude importer: `first_user_message` = first top-level `type=="user"` line whose `message.content` is a string or text block list.
- Codex importer: `first_user_message` = first body line with `type=="message"` and `role=="user"`; content comes from `content` or `payload.content` depending on rollout shape.

**Storage:** the title is **not** written to canonical `run.json`. The redacted title (or `null`) is stored under `import_report.derived.display_title`, then surfaced in the query projection (see §3.4) and optionally cached in SQLite. The full first-user-message is not persisted by this feature, but the existing raw transcript artifact may already contain it; this spec does not claim otherwise.

**Why a projection and not a contract field:** title heuristics will evolve (different vendors, future runtimes). Locking the canonical schema to today's algorithm guarantees regrets. The query projection reads a derived artifact field and can be rebuilt by re-import or a future refresh command.

### 3.3 Usage summary

Add an artifact per run:

```
~/.agentlens/runs/<workspace_id>/<run_id>/artifacts/usage.json
```

Shape:

```json
{
  "schema_version": "1",
  "source": "claude-session" | "codex-rollout",
  "input_tokens": 0,
  "output_tokens": 0,
  "cache_creation_tokens": 0,
  "cache_read_tokens": 0,
  "reasoning_tokens": 0,
  "model_breakdown": [
    {
      "model": "claude-opus-4-7",
      "input_tokens": 0,
      "output_tokens": 0,
      "cache_creation_tokens": 0,
      "cache_read_tokens": 0,
      "reasoning_tokens": 0
    }
  ],
  "cost_usd": null,
  "pricing_source": "unknown",
  "confidence": "exact" | "estimated" | "unknown",
  "diagnostics": {
    "events_with_usage": 0,
    "events_missing_usage": 0,
    "model_field_missing_events": 0
  }
}
```

**Confidence rules:**

| Condition                                                                                                                              | `confidence`  |
|----------------------------------------------------------------------------------------------------------------------------------------|---------------|
| Every billable line in the source has a populated token field; no fallbacks taken.                                                     | `exact`       |
| Token totals derived from a mix of populated and inferred sources (e.g., one line missing `cache_read_tokens`, treated as 0).          | `estimated`   |
| No token fields recoverable, OR fewer than 50% of billable lines had any usage field.                                                  | `unknown`     |

**Cost rules (v1.x):**

- Always emit `cost_usd: null`, `pricing_source: "unknown"`. The pricing table comes in a follow-up patch — until then the dashboard renders `cost = —` for these runs.
- The shape includes `cost_usd` / `pricing_source` from day one so the eventual pricing patch is additive, not contract-changing.

**Vendor extractors:**

- Claude: read `usage.input_tokens`, `usage.output_tokens`, `usage.cache_creation_input_tokens`, `usage.cache_read_input_tokens` from `message` events. `model` from `message.model`.
- Codex: read `payload.info.tokens` / `payload.info.model` where present; tolerate both top-level rollout fields and nested `payload` fields. Codex Desktop sometimes omits tokens entirely → `confidence="unknown"` for those runs.

**Eval interaction:** `eval.json` MUST NOT fail when usage is missing or partial. Usage is observation, not evidence; it does not satisfy or break any verification check.

### 3.4 Query projections

Extend `store/query.py`'s run projection (the in-memory view returned by `agentlens show`/`latest`/`status --format json` and the dashboard) with three additive fields:

```json
{
  "run_id": "...",
  ...existing fields unchanged...
  "display_title": "<string or null>",
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_tokens": 0,
    "cache_read_tokens": 0,
    "reasoning_tokens": 0,
    "cost_usd": null,
    "pricing_source": "unknown",
    "confidence": "unknown"
  } | null,
  "import_state": "full" | "partial" | "skipped" | null
}
```

- `display_title` is `null` for runs without a recovered title.
- `usage` is `null` for non-imported runs without a `usage.json` artifact (e.g., container runs from `kws-cme`). Imported runs always write `usage.json`; when no tokens are recoverable, all counters are `0` and `confidence="unknown"`.
- `import_state` is `null` for non-imported runs (live captures). Imported runs always have a state.

Existing consumers see only added keys; no rename, no removal. The dashboard runs-list spec (`docs/spec/2026-05-19-agentlens-dashboard-design.md`) gains:

| Column         | Source                          |
|----------------|---------------------------------|
| Title          | `display_title`                 |
| Usage (in/out) | `usage.input_tokens` / `usage.output_tokens` |
| Cost           | `usage.cost_usd` (renders `—` when `null`) |
| Confidence     | `usage.confidence` badge        |
| Import state   | `import_state` badge (`partial` runs flagged) |

Dashboard spec patch is one paragraph added to its "Runs list columns" section, not a rewrite.

### 3.5 CLI surface

No new commands. Existing import commands gain optional flags:

```
agentlens import claude-session [--byte-cap BYTES] [--deep-parse-only]
agentlens import codex-session  [--byte-cap BYTES] [--deep-parse-only]
```

- `--byte-cap`: override the per-file byte cap; min 1 MiB, max 1 GiB. Out-of-range → `typer.BadParameter`.
- `--deep-parse-only`: when set, sources over the byte cap produce `analysis_state="skipped"` (a stub imported run with no vendor-derived events) instead of `partial`. Default is `partial`.

Existing selector and idempotency behaviour is unchanged when both flags are absent. The run tree gains additional derived artifacts and finalization output.

## 4. Architecture

### 4.1 Module layout

```
AgentLens/src/agentlens/
  importers/
    __init__.py
    title.py              ← NEW: extract_display_title()
    usage.py              ← NEW: extract_usage(parsed) → UsageSummary
    report.py             ← NEW: ImportReport dataclass + emit()
    artifacts.py          ← NEW: atomic writer for non-schema derived artifact JSON
  store/
    claude_session.py     ← MODIFY: track lines/skips/oversized; cap bytes; return populated ImportReport
    codex_session.py      ← MODIFY: same
    query.py              ← MODIFY: merge display_title / usage / import_state into projection
  commands/
    import_common.py          ← NEW: shared byte-cap validation + imported-run finalization
    import_claude_session.py  ← MODIFY: --byte-cap, --deep-parse-only, write artifacts
    import_codex_session.py   ← MODIFY: same
```

`importers/` is a new package; nothing else lives there yet, so there is no naming collision with the existing `adapters/` package (which wraps subprocess execution).

### 4.2 Data flow per import

```
discover source path
    │
    ▼
probe size (os.stat)
    │  ├─ > byte_cap + --deep-parse-only → ImportReport(skipped); stub run + transcript copy
    │  └─ otherwise → continue
    ▼
stream JSONL line-by-line (buffered read)
    ├─ malformed JSON      → report.skipped_malformed += 1
    ├─ line > 2 MiB        → report.skipped_oversized += 1
    ├─ unsupported type    → report.skipped_unsupported_type += 1
    └─ ok                  → events += [event]; usage extractor sees raw line
    ▼
[at EOF or byte_cap reached]
    │
    ▼
build ParsedSession (existing) + ImportReport (new) + UsageSummary (new) + display_title (new)
    │
    ▼
copy source JSONL → artifacts/transcripts/<source-session-id>.jsonl
write run.started as first event
write command.started / vendor-derived events / command.finished
write artifacts/import_report.json
write artifacts/usage.json
write final.json with agent_outcome = "unknown" or "partial" when import_state != full
manifest.seal(pre_eval)
evaluate(run_dir)
manifest.seal(final)
sqlite_index.index_run(run_dir)
```

### 4.3 Manifest coverage

`manifest.json`'s `final` phase already iterates the run directory and seals every durable file with sha256. The importer must write `import_report.json`, `usage.json`, and the transcript before `seal(pre_eval)` so evaluator hash checks and the final manifest cover them. No manifest schema change is required. Tests must verify the manifest covers both new files and the existing transcript file.

## 5. Security & Privacy

- **No new full prompt/output artifact.** Title heuristic runs in-memory; only the redacted title (≤120 chars after stripping fences, agents blocks, paths, control chars) reaches `import_report.json`. If the user's first message was a 4 KB code-pasted prompt, what lands in the new artifact is the title-strip result, capped.
- **Raw transcript reality.** The existing transcript artifact is a vendor JSONL copy. It may contain prompts and outputs. This patch does not newly sanitize it; safe export/sanitized transcript copies remain deferred.
- **Usage is non-sensitive by definition** (token counts, model names). No new redaction needed.
- **Import report contains file paths** (`source_path` is absolute). It is **not** exposed through query/API projections and is intended only for local forensic traceability.
- `docs/security.md` patch: add one bullet to "Imported transcripts" — *"Importers also write `artifacts/import_report.json` (line counts, byte-cap state, absolute source path, and a redacted display title) and `artifacts/usage.json` (token totals, model breakdown, optional cost). They do not contain full prompt or output bodies."*

## 6. Backward compatibility

| Surface                  | Compatibility                                                              |
|--------------------------|----------------------------------------------------------------------------|
| `run.json` schema        | Unchanged.                                                                 |
| `events.jsonl` schema    | Unchanged.                                                                 |
| `final.json` / `eval.json` | Unchanged.                                                              |
| `manifest.json`          | Unchanged (existing globbing picks up new artifacts).                      |
| `agentlens import` CLI   | New optional flags; selectors/idempotency unchanged when flags are absent; imported run trees gain final/eval/manifest/index artifacts. |
| `agentlens latest/status/show --format json` | Three new keys appended (`display_title`, `usage`, `import_state`); null when absent. Snapshot fixtures and frontend generated types must update. |
| Existing runs on disk    | `display_title=null`, `usage=null`, `import_state=null`; no migration required. |
| SQLite index             | Three columns added (nullable); rebuild from JSON unchanged.               |

Re-importing a session that already has a run remains a no-op via the existing `input.import_key` scan. This patch does not overwrite `import_report.json` or `usage.json` on duplicate import; a future `--refresh` flag can deliberately rebuild derived artifacts.

## 7. Test plan

### 7.1 Unit tests

- `tests/unit/test_importers_title.py`
  - Empty / None / whitespace-only input → `None`.
  - Triple-backtick fenced block at start → block removed, next line used.
  - `<AGENTS>...</AGENTS>` block stripped (multi-line).
  - Absolute path → `<path>` substitution.
  - Korean / Japanese / emoji input passes through (UTF-8 cap counts code points, not bytes).
  - 5000-char input → capped at 120 with U+2026 suffix.
  - Title-only-punctuation input (`"!!!"`) → `None`.
  - Stable across reruns (deterministic).

- `tests/unit/test_importers_usage.py`
  - Claude session with full token fields → `confidence="exact"`.
  - Claude session with one event missing `cache_read_input_tokens` → `confidence="estimated"`, treated as 0.
  - Codex Desktop fixture without tokens → `confidence="unknown"`, all counts 0.
  - Multiple models in one session → `model_breakdown` length matches distinct models, aggregates correctly.

- `tests/unit/test_importers_report.py`
  - Counter aggregation: 100 parsed + 3 malformed + 1 oversized → totals match.
  - `byte_cap_hit=true` when stream stops before EOF.
  - `analysis_state` derivation: any skip → `partial`; cap-hit → `partial`; deep-parse-only + oversized source → `skipped`.

### 7.2 Integration tests

- `tests/integration/test_import_claude_session_report.py`
  - Synthetic Claude session with one malformed line: import succeeds, run exists, `import_report.json` shows `analysis_state="partial"`, manifest covers the new artifacts.
- `tests/integration/test_import_codex_session_report.py`
  - Codex CLI fixture with full token fields → `usage.json` `confidence="exact"`.
  - Codex Desktop fixture (no tokens) → `usage.json` `confidence="unknown"`, `cost_usd=null`.
- `tests/integration/test_import_byte_cap.py`
  - Source > cap with default behaviour → `analysis_state="partial"`, vendor-derived events present up to cap.
  - Same source with `--deep-parse-only` → `analysis_state="skipped"`, no vendor-derived events, `events.jsonl` still starts with `run.started`, transcript still copied.
- `tests/integration/test_query_projection_usage_title.py`
  - `agentlens latest/status/show --format json` returns `display_title` + `usage` + `import_state` for an imported run.
  - Same calls return `display_title=null`, `usage=null`, `import_state=null` for a container run (no regression).
  - `/api/v1/runs` returns the three fields through `project_run_row()`.

### 7.3 Fixtures

Create under `tests/fixtures/sessions/`:

- `claude-with-usage.jsonl` (10 events, all tokens present)
- `claude-mixed-usage.jsonl` (10 events, 3 missing cache fields)
- `claude-malformed-line.jsonl` (5 events, 1 malformed)
- `codex-cli-with-usage.jsonl` (rollout shape, tokens present)
- `codex-desktop-no-usage.jsonl` (rollout shape, no tokens)
- `codex-oversized-line.jsonl` (one row > 2 MiB synthesised via padding)
- `claude-titles/` (a directory of one-line files, each holds a first-user-message; each pair `(input.txt, expected.txt)`)

## 8. Risk register

| Risk                                                                | Impact                          | Mitigation                                                                                          |
|---------------------------------------------------------------------|---------------------------------|-----------------------------------------------------------------------------------------------------|
| Title heuristic leaks sensitive content via the projection.         | Privacy regression.             | All strip steps run in-memory before the title reaches disk; `tests/unit/test_importers_title.py` asserts known-sensitive patterns (env, paths, AGENTS) never appear in output. |
| Byte cap defaults too small → large real sessions silently truncate. | Data loss on real history.      | Default 64 MiB covers >99% of observed Codex rollouts; emit `byte_cap_hit=true` loudly in the report; dashboard surfaces `partial` badge. |
| Usage confidence appears `exact` when source data was partially fabricated. | Misleading reporting.   | `events_missing_usage` is reported in `diagnostics`; any non-zero value forces `estimated` at minimum; "all-zero with `events_with_usage=0`" forces `unknown`. |
| Projection drift: dashboard expects keys importer omits.            | Dashboard render error.         | Projection layer in `store/query.py` always emits the three new keys (with `null`) regardless of whether artifacts exist. |
| Re-import is a no-op, so derived artifacts can become stale if the vendor source changes. | User expects a refreshed report but sees the first import. | Preserve v1 idempotency; document that refresh is out of scope and add a future `--refresh` open question. |
| Pricing patch arrives and changes `cost_usd` semantics.             | Future contract churn.          | Shape is reserved from day one (`cost_usd: null`, `pricing_source: "unknown"`); pricing patch only changes value, not key. |

## 9. Open questions

1. **Should `display_title` truncation length be a CLI flag?** Default 120 chars feels right for a runs-list cell; we will hardcode for v1.x and revisit when the dashboard ships.
2. **Codex Desktop reasoning tokens — are they recoverable?** Initial reading of fixtures suggests no. v1.x emits `reasoning_tokens=0` with `confidence="unknown"` for those runs and revisits in a follow-up once Desktop fixtures are richer.
3. **Pricing follow-up scope.** Will pricing live in AgentLens (bundled YAML, periodically refreshed) or a separate plugin? Decided in a later spec; this design only reserves the shape.
4. **Should duplicate imports gain `--refresh`?** This patch preserves the existing no-op idempotency contract. A later refresh mode can intentionally rebuild `import_report.json`, `usage.json`, manifest, eval, and index rows.

## 10. References

- ADR: `docs/adr/2026-05-19-agentlens-ecosystem-benchmark.md`
- v1 plan: `docs/plan/2026-05-19-agentlens-v1-and-kws-unification.md`
- Dashboard spec: `docs/spec/2026-05-19-agentlens-dashboard-design.md`
- Contract: `docs/contract.md`
- Security: `docs/security.md`
