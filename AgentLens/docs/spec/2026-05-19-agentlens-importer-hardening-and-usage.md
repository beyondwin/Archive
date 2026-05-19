# AgentLens Importer Hardening + Usage Summary — Design Spec

**Date:** 2026-05-19
**Status:** Draft
**Scope:** AgentLens v1 importers (`claude-session`, `codex-session`), query projections, dashboard surface
**Adopts:** `docs/adr/2026-05-19-agentlens-ecosystem-benchmark.md` §5.2 (large-session safety), §5.3 (usage ledger), §5.6 (title heuristic)
**Defers:** §5.5 safe export, §5.7 read-only TUI (post-v1.x)
**Local baseline:** `docs/contract.md`, `docs/security.md`, `docs/spec/2026-05-19-agentlens-dashboard-design.md`

---

## 1. Problem

The current importers (`commands/import_claude_session.py`, `commands/import_codex_session.py`) handle the happy path: locate JSONL, parse line-by-line, write canonical artifacts, seal the manifest. Three gaps surface as soon as real-world history is imported:

1. **Partial parses are invisible.** A malformed or oversized line is skipped with a `stderr` warning and the import is otherwise reported as successful. Downstream tooling cannot tell "fully parsed" from "best-effort parsed" from "skipped".
2. **No human-readable run identity.** The dashboard runs list (per the v1 design spec) needs a `display_title`, but importers never extract one. The choices today are `run_id` (random uuid) or empty.
3. **No usage/cost summary.** Tools like `ccusage` already answer "what did this run cost?" from raw vendor logs. AgentLens has the strictly better substrate (sealed, evidence-linked) but does not expose token or cost data at all, so users still leave AgentLens to answer that question.

This spec fills the three gaps with **additive, contract-stable** changes. Nothing in the locked v1 schema moves. All new fields land as artifacts or query projections.

## 2. Goals & Non-Goals

### Goals

- Make every importer emit a **structured `import_report`** that distinguishes `full` / `partial` / `skipped` analysis and counts skipped lines, oversized rows, and unsupported event types.
- Bound importer memory and runtime via an explicit per-file **byte cap**, with `partial` semantics when the cap is hit.
- Extract a redacted **`display_title`** from each session via a pure heuristic; surface it through query projections only.
- Emit an additive **`usage`** artifact + query projection (input/output/cache/reasoning tokens, optional cost, mandatory `confidence` field).
- Keep all new data covered by `manifest.json` like every other artifact.

### Non-Goals

- Modifying the locked v1 `run.json` / `events.jsonl` / `final.json` / `eval.json` schemas.
- Pricing-table maintenance and currency conversion (v1.x emits `pricing_source="unknown"` and leaves `cost_usd=null`; pricing comes later).
- Sanitized transcript copies for export (§5.5 — deferred).
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
  "duration_ms": 0,
  "byte_cap_source": "default" | "env:AGENTLENS_IMPORT_BYTE_CAP" | "flag:--byte-cap"
}
```

**Analysis states:**

| State     | Trigger                                                                                                                                              |
|-----------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `full`    | All lines parsed within `byte_cap_bytes` and no skips of any kind.                                                                                   |
| `partial` | At least one line skipped (malformed / oversized / unsupported), OR `byte_cap_hit=true`. Run is still written; canonical events come from parsed lines only. |
| `skipped` | Source larger than `byte_cap_bytes` AND `--deep-parse-only` opt-out is set. Run is created (so the user has a record), `events.jsonl` is empty, transcript artifact is still copied. |

**Byte cap defaults:**

- Default: 64 MiB (`67_108_864` bytes). Rationale: Codex rollouts of dozens of MB are common; loading more than this into memory + jsonl-parsing line-by-line still works, but bounded.
- Override 1: `AGENTLENS_IMPORT_BYTE_CAP=<bytes>` environment variable.
- Override 2: `--byte-cap <bytes>` on the import command.

Cap is **per-source-file**; multi-session imports re-apply it per session.

**Per-line size cap:** any single JSONL row over **2 MiB** is treated as `skipped_oversized` (counted in the report, never loaded into memory beyond the size probe).

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

- Claude importer: `first_user_message` = first event with `role=="user"` (text content), pre-redaction.
- Codex importer: `first_user_message` = first event with `kind=="user_message"` in the rollout's `payload.content`.

**Storage:** the title is **not** written to canonical `run.json`. It lives in the query projection only (see §3.4). The full first-user-message is **not** persisted — the heuristic runs in-memory during import, only the resulting title (or `None`) is emitted as a derived field on the run JSON projection. This keeps the §2 redaction promise: full prompts never persist.

**Why a projection and not a contract field:** title heuristics will evolve (different vendors, future runtimes). Locking the canonical schema to today's algorithm guarantees regrets. The query projection rebuilds from artifacts when needed.

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
- Codex: read `payload.info.tokens` (where present) and `payload.info.model` from rollout events. Codex Desktop sometimes omits tokens entirely → `confidence="unknown"` for those runs.

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
- `usage` is `null` for runs without a `usage.json` artifact (e.g., container runs from `kws-cme`).
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
- `--deep-parse-only`: when set, sources over the byte cap produce `analysis_state="skipped"` (a stub run with empty `events.jsonl`) instead of `partial`. Default is `partial`.

Existing default behaviour is unchanged when both flags are absent.

## 4. Architecture

### 4.1 Module layout

```
AgentLens/src/agentlens/
  importers/
    __init__.py
    title.py              ← NEW: extract_display_title()
    usage.py              ← NEW: extract_usage(parsed) → UsageSummary
    report.py             ← NEW: ImportReport dataclass + emit()
  store/
    claude_session.py     ← MODIFY: track lines/skips/oversized; cap bytes; return populated ImportReport
    codex_session.py      ← MODIFY: same
    query.py              ← MODIFY: merge display_title / usage / import_state into projection
  commands/
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
writer.write_run() + write_events() + write_final() + write_eval()  [unchanged]
manifest.seal(pre_eval)                                              [unchanged]
write artifacts/import_report.json
write artifacts/usage.json  (when extractor returned a non-empty summary)
copy source JSONL → artifacts/transcripts/<source-session-id>.jsonl  [existing]
manifest.seal(final)                                                 [covers new artifacts]
```

### 4.3 Manifest coverage

`manifest.json`'s `final` phase already iterates `artifacts/**` and seals every file with sha256. The two new artifacts (`import_report.json`, `usage.json`) are picked up automatically — no manifest change required. Tests must verify the manifest covers both files and the existing transcript file.

## 5. Security & Privacy

- **No new persisted prompt content.** Title heuristic runs in-memory; only the redacted title (≤120 chars after stripping fences, agents blocks, paths, control chars) reaches disk. If the user's first message was a 4 KB code-pasted prompt, what lands on disk is the title-strip result, capped.
- **Usage is non-sensitive by definition** (token counts, model names). No new redaction needed.
- **Import report contains file paths** (`source_path` is absolute). This is already true of `run.json`'s `input.import_key` in spirit; `source_path` matches the existing precedent (`store/writer.py` already records the source path on imported runs). It is **not** redacted out; it identifies the source file unambiguously for re-imports.
- `docs/security.md` patch: add one bullet to "Storage rules" — *"Importers may write `artifacts/import_report.json` and `artifacts/usage.json`. Neither contains prompt or output text."*

## 6. Backward compatibility

| Surface                  | Compatibility                                                              |
|--------------------------|----------------------------------------------------------------------------|
| `run.json` schema        | Unchanged.                                                                 |
| `events.jsonl` schema    | Unchanged.                                                                 |
| `final.json` / `eval.json` | Unchanged.                                                              |
| `manifest.json`          | Unchanged (existing globbing picks up new artifacts).                      |
| `agentlens import` CLI   | New optional flags; default behaviour unchanged when flags are absent.     |
| `agentlens show --format json` | Three new keys appended (`display_title`, `usage`, `import_state`); null when absent. |
| Existing runs on disk    | `display_title=null`, `usage=null`, `import_state=null`; no migration required. |
| SQLite index             | Three columns added (nullable); rebuild from JSON unchanged.               |

Re-importing a session that already has a run is still idempotent (existing `input.import_key` scan). The re-import will overwrite the prior `import_report.json` and `usage.json` because the report counts may differ (e.g., a previously-`partial` import that now parses `full` after a byte-cap bump).

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
  - Source > cap with default `--partial` → `analysis_state="partial"`, events present up to cap.
  - Same source with `--deep-parse-only` → `analysis_state="skipped"`, empty `events.jsonl`, transcript still copied.
- `tests/integration/test_query_projection_usage_title.py`
  - `agentlens show --format json` returns `display_title` + `usage` + `import_state` for an imported run.
  - Same call returns `display_title=null`, `usage=null`, `import_state=null` for a container run (no regression).

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
| Re-import overwrites a `full` report with `partial` after a regression. | Forensics confusion.          | Allowed by design; `manifest.json` history (sha256 of each version sealed at final time) lets the user reconstruct prior states from backup. Documented in `docs/security.md`. |
| Pricing patch arrives and changes `cost_usd` semantics.             | Future contract churn.          | Shape is reserved from day one (`cost_usd: null`, `pricing_source: "unknown"`); pricing patch only changes value, not key. |

## 9. Open questions

1. **Should `display_title` truncation length be a CLI flag?** Default 120 chars feels right for a runs-list cell; we will hardcode for v1.x and revisit when the dashboard ships.
2. **Codex Desktop reasoning tokens — are they recoverable?** Initial reading of fixtures suggests no. v1.x emits `reasoning_tokens=0` with `confidence="unknown"` for those runs and revisits in a follow-up once Desktop fixtures are richer.
3. **Pricing follow-up scope.** Will pricing live in AgentLens (bundled YAML, periodically refreshed) or a separate plugin? Decided in a later spec; this design only reserves the shape.

## 10. References

- ADR: `docs/adr/2026-05-19-agentlens-ecosystem-benchmark.md`
- v1 plan: `docs/plan/2026-05-19-agentlens-v1-and-kws-unification.md`
- Dashboard spec: `docs/spec/2026-05-19-agentlens-dashboard-design.md`
- Contract: `docs/contract.md`
- Security: `docs/security.md`
