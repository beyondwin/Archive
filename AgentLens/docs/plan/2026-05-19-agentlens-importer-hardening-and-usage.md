# AgentLens Importer Hardening + Usage Summary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `kws-claude-multi-agent-executor` (Opus orchestrator + Sonnet implementers) to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Risk default for all tasks: **mid**.

**Goal:** Adopt ADR `docs/adr/2026-05-19-agentlens-ecosystem-benchmark.md` §5.2, §5.3, and §5.6 by making imported sessions bounded, sealed, usage-aware, title-aware, and visible in CLI/API/dashboard projections without changing locked v1 schemas.

**Companion design spec:** `AgentLens/docs/spec/2026-05-19-agentlens-importer-hardening-and-usage.md` (read first; its §0.1 source-review corrections are binding).

**Tech stack:** Python 3.11+, Typer, JSON Schema, pytest, FastAPI, React/Vite/TypeScript, existing AgentLens importers (`store/{claude,codex}_session.py`, `commands/import_{claude,codex}_session.py`).

---

## Deep Source Review Findings

| ID | Severity | Finding | Plan correction |
|----|----------|---------|-----------------|
| E1 | Blocker | Locked v1 schemas (`run.json`, `events.jsonl`, `final.json`, `eval.json`, `manifest.json`) have `additionalProperties:false`. | Do not add schema fields. New data lives in `artifacts/import_report.json`, `artifacts/usage.json`, query/API projection keys, and nullable SQLite cache columns. |
| E2 | Blocker | Current importers do not write `final.json`, `eval.json`, `manifest.json`, or index rows. Existing docs that claim imported transcripts are manifest-covered are not true for current code. | Add shared importer finalization in `commands/import_common.py`: write `final.json`, `seal(pre_eval)`, `evaluate()`, `seal(final)`, then `index_run()`. |
| E3 | Blocker | Evaluator check `run_started` requires the first event to be `run.started`; current importers start with `command.started`. | Importers must prepend `run.started`, then keep existing `command.started` / `command.finished` events so current tests and users still see those markers. |
| E4 | High | `_iter_jsonl()` in both parsers loads the entire source with `path.read_text()`. Byte-cap logic cannot wrap that safely. | Replace with binary streaming iteration that counts byte offsets and line sizes before decoding or `json.loads`. |
| E5 | High | `ParsedSession` / `ParsedCodexSession` do not expose first user message or usage-bearing raw records. | Extend parsed dataclasses with `first_user_message_text: str | None` and `usage_records: list[dict[str, Any]]`. |
| E6 | High | The plan previously said query projection only, but title needs a source of truth and Claude normalized events do not include user messages. | Store the redacted derived title under `import_report.derived.display_title`; query/API project it from that artifact. |
| E7 | High | `store.writer.atomic_write_json()` requires a `schema` field; `import_report.json` and `usage.json` deliberately are not schema documents. | Add `importers/artifacts.py::write_artifact_json()` for atomic non-schema artifact JSON writes. |
| E8 | High | Adding `display_title`, `usage`, and `import_state` affects locked JSON projectors, snapshots, generated TS types, and `/api/v1/runs`, not just `store/query.py`. | Task 8 owns `store/query.py`, `commands/_format.py`, snapshot fixtures, generated frontend types, API typings, and route tests together. |
| E9 | Medium | Existing `input.import_key` behaviour is a real no-op on duplicate import. Overwriting report/usage on re-import would break the v1 contract. | Preserve no-op idempotency. Defer a future `--refresh` mode. |
| E10 | Medium | Imported transcript copy uses `shutil.copyfile()` and bypasses writer redaction. | Do not claim transcript redaction. New artifacts must avoid full prompt/output bodies except the capped redacted title. Patch `docs/security.md` honestly. |
| E11 | Medium | Counting every non-emitted vendor line as unsupported would mark normal sessions partial. | Count `skipped_unsupported_type` only for lines the parser cannot classify; valid-but-not-emitted vendor lines remain supported. |
| E12 | Medium | `pyproject.toml` test extras only include `pytest`; property testing with Hypothesis is not currently available. | Use deterministic fuzz loops in title tests unless the implementation explicitly adds a test dependency. |

---

## File Structure

### Create

| Path | Responsibility |
|------|----------------|
| `AgentLens/src/agentlens/importers/__init__.py` | Package marker for shared importer helpers. |
| `AgentLens/src/agentlens/importers/title.py` | `extract_display_title()` pure heuristic. |
| `AgentLens/src/agentlens/importers/usage.py` | `UsageSummary`, vendor usage extractors, confidence derivation. |
| `AgentLens/src/agentlens/importers/report.py` | `ImportReport`, counters, state derivation, report dict construction. |
| `AgentLens/src/agentlens/importers/artifacts.py` | Atomic non-schema artifact JSON writer used by report and usage. |
| `AgentLens/src/agentlens/commands/import_common.py` | Byte-cap validation, shared transcript copy metadata, imported-run finalization. |
| `AgentLens/tests/unit/test_importers_title.py` | Title heuristic tests. |
| `AgentLens/tests/unit/test_importers_usage.py` | Usage extractor tests. |
| `AgentLens/tests/unit/test_importers_report.py` | Report counter/state tests and artifact writer test. |
| `AgentLens/tests/integration/test_import_claude_session_report.py` | Claude import end-to-end with report/usage/manifest/projection. |
| `AgentLens/tests/integration/test_import_codex_session_report.py` | Codex import end-to-end with report/usage/manifest/projection. |
| `AgentLens/tests/integration/test_import_byte_cap.py` | Partial vs skipped byte-cap behaviour for both importers. |
| `AgentLens/tests/integration/test_query_projection_usage_title.py` | CLI/API projection shape for imported and non-imported runs. |
| `AgentLens/tests/fixtures/sessions/*.jsonl` | Small vendor fixtures for usage, malformed lines, oversized lines, and titles. |

### Modify

| Path | Change |
|------|--------|
| `AgentLens/src/agentlens/store/claude_session.py` | Stream parser, byte/line caps, counters, first-user extraction, usage records, `(ParsedSession, ImportReport)` return. |
| `AgentLens/src/agentlens/store/codex_session.py` | Same for Codex rollouts. |
| `AgentLens/src/agentlens/commands/import_claude_session.py` | Add byte-cap flags; write `run.started`; write report/usage artifacts; finalize/seal/evaluate/index imported run. |
| `AgentLens/src/agentlens/commands/import_codex_session.py` | Same for Codex importer; preserve parent-link backfill behaviour. |
| `AgentLens/src/agentlens/store/query.py` | Enrich run rows with `display_title`, `usage`, `import_state` from artifacts; nulls for non-imported runs. |
| `AgentLens/src/agentlens/store/sqlite_index.py` | Add nullable `display_title`, `usage_confidence`, `import_state` cache columns and migrations. |
| `AgentLens/src/agentlens/commands/_format.py` | Emit the three additive keys in `run_row` and `show` JSON projectors. |
| `AgentLens/src/agentlens/web/routers/runs.py` | Ensure `/api/v1/runs` and `/api/v1/runs/{id}` carry projector-derived fields only. |
| `AgentLens/web/src/api/runs.ts` | Add typed `display_title`, `usage`, `import_state` fields. |
| `AgentLens/web/src/components/run-list-table.tsx` | Add title, usage/cost/confidence, import-state cells. |
| `AgentLens/web/src/components/run-list-table.test.tsx` | Cover the new dashboard cells and null rendering. |
| `AgentLens/web/src/types/api.ts` | Regenerated from updated snapshot fixtures. |
| `AgentLens/tests/fixtures/format_snapshots/*.json` | Add additive projection keys. |
| `AgentLens/docs/cli.md` | Document import flags and additive JSON fields. |
| `AgentLens/docs/security.md` | Correct imported-transcript privacy wording and document new artifacts. |
| `AgentLens/docs/contract.md` | Changelog/additive-artifacts note; no schema changes. |
| `AgentLens/docs/spec/2026-05-19-agentlens-dashboard-design.md` | Runs-list data points sourced from the projection. |

### Delete

None.

---

# Phase 1 — Pure Helpers

These tasks are independent and can run in parallel.

### Task 1: `importers.title.extract_display_title`

**Files:** `AgentLens/src/agentlens/importers/title.py`, `AgentLens/tests/unit/test_importers_title.py`, `AgentLens/tests/fixtures/sessions/title-*.txt`

- [ ] Write failing tests for `None`, empty, fenced code, inline code, `<<...>>` sentinels, `<AGENTS>` / `<system-reminder>` blocks, env lines, absolute paths, control chars, URL preservation, punctuation-only input, Korean text, and 120-char U+2026 truncation.
- [ ] Add a deterministic fuzz test using `random.Random(0)` over decoded random bytes; assert the function never raises and returns `str | None`.
- [ ] Implement `extract_display_title()` exactly as spec §3.2. Keep it pure: no filesystem, no network, no redaction module dependency.
- [ ] Run `pytest tests/unit/test_importers_title.py -q`.

### Task 2: `importers.usage.extract_usage`

**Files:** `AgentLens/src/agentlens/importers/usage.py`, `AgentLens/tests/unit/test_importers_usage.py`, `AgentLens/tests/fixtures/sessions/claude-with-usage.jsonl`, `AgentLens/tests/fixtures/sessions/claude-mixed-usage.jsonl`, `AgentLens/tests/fixtures/sessions/codex-cli-with-usage.jsonl`, `AgentLens/tests/fixtures/sessions/codex-desktop-no-usage.jsonl`

- [ ] Define `UsageSummary` and `ModelUsage` dataclasses matching spec §3.3 (`cost_usd=None`, `pricing_source="unknown"`).
- [ ] Define extractor input as `usage_records` captured by the parsers, not normalized AgentLens events.
- [ ] Write failing tests for Claude exact, Claude estimated, Codex exact, Codex Desktop unknown, missing model fields, and multi-model aggregation.
- [ ] Implement `extract_usage(source: Literal["claude-session","codex-rollout"], usage_records: list[dict]) -> UsageSummary`.
- [ ] Ensure imported runs with no token fields still produce a valid all-zero summary with `confidence="unknown"`.
- [ ] Run `pytest tests/unit/test_importers_usage.py -q`.

### Task 3: `ImportReport` + artifact writer

**Files:** `AgentLens/src/agentlens/importers/report.py`, `AgentLens/src/agentlens/importers/artifacts.py`, `AgentLens/tests/unit/test_importers_report.py`

- [ ] Define `ImportReport` with counters, `first_error`, transcript metadata, `derived.display_title`, byte-cap metadata, and `duration_ms`.
- [ ] Implement methods: `record_parsed()`, `record_skip(reason, line_number, byte_offset)`, `record_byte_cap_hit()`, `set_transcript_artifact(path, bytes)`, `set_display_title(title, source)`, and `to_dict()`.
- [ ] Implement `write_artifact_json(path: Path, data: dict)` using temp-file + `fsync` + `os.replace`; no schema validation, deterministic `sort_keys=True`.
- [ ] Write tests for full/partial/skipped state derivation, first-error preservation, transcript metadata, display-title metadata, and atomic artifact output.
- [ ] Run `pytest tests/unit/test_importers_report.py -q`.

---

# Phase 2 — Parser Integration

Tasks 4 and 5 touch disjoint parser files and can run in parallel.

### Task 4: Claude parser streaming + report plumbing

**Files:** `AgentLens/src/agentlens/store/claude_session.py`, `AgentLens/tests/unit/test_claude_session_parser.py`

- [ ] Extend `ParsedSession` with `first_user_message_text: str | None` and `usage_records: list[dict[str, Any]]`.
- [ ] Change `parse_session(path: Path, *, byte_cap: int = 64 * 1024 * 1024, deep_parse_only: bool = False) -> tuple[ParsedSession, ImportReport]`.
- [ ] Replace `_iter_jsonl()` with a binary streaming iterator that yields `(line_number, byte_offset, raw_bytes, obj)` and never reads the full file.
- [ ] If `path.stat().st_size > byte_cap and deep_parse_only`, return a stub `ParsedSession` with no vendor events plus `ImportReport.analysis_state="skipped"`.
- [ ] Stop parsing when the next line would exceed `byte_cap`; mark `byte_cap_hit=True`; keep parsed events before the cap.
- [ ] Treat a row over 2 MiB as `skipped_oversized` without `json.loads`.
- [ ] Count malformed JSON as `skipped_malformed`.
- [ ] Do not count normal `user`, `assistant`, `system`, or tool-result lines as unsupported merely because they do not emit `claude.*` events.
- [ ] Capture first user message text from string content or text-block content.
- [ ] Capture Claude usage records from `line["message"]["usage"]` plus `line["message"]["model"]`.
- [ ] Update existing parser tests for tuple return and add malformed/report/cap/title/usage assertions.
- [ ] Run `pytest tests/unit/test_claude_session_parser.py -q`.

### Task 5: Codex parser streaming + report plumbing

**Files:** `AgentLens/src/agentlens/store/codex_session.py`, `AgentLens/tests/unit/test_codex_session_parser.py`, `AgentLens/tests/fixtures/sessions/codex-oversized-line.jsonl`

- [ ] Extend `ParsedCodexSession` with `first_user_message_text: str | None` and `usage_records: list[dict[str, Any]]`.
- [ ] Change `parse_rollout(path: Path, *, byte_cap: int = 64 * 1024 * 1024, deep_parse_only: bool = False) -> tuple[ParsedCodexSession, ImportReport]`.
- [ ] Replace `_iter_jsonl()` with the same binary streaming pattern as Task 4.
- [ ] Preserve existing session-meta extraction, originator/mode handling, and parent-thread extraction.
- [ ] Define a known Codex type allowlist so valid non-emitted lifecycle/status lines do not make the import partial.
- [ ] Capture first user message from `type=="message" and role=="user"` using `content` or nested `payload.content`.
- [ ] Capture usage records from `payload.info.tokens`, `payload.info.model`, and equivalent top-level rollout shapes.
- [ ] Add oversized-line, malformed-line, byte-cap, skipped, first-user, and usage-record tests.
- [ ] Run `pytest tests/unit/test_codex_session_parser.py -q`.

---

# Phase 3 — Import Commands + Projections

### Task 6: Shared finalization + Claude command

**Files:** `AgentLens/src/agentlens/commands/import_common.py`, `AgentLens/src/agentlens/commands/import_claude_session.py`, `AgentLens/tests/integration/test_import_claude_session_report.py`, `AgentLens/tests/integration/test_import_byte_cap.py`, `AgentLens/docs/cli.md`, `AgentLens/docs/security.md`

- [ ] Add constants `DEFAULT_IMPORT_BYTE_CAP = 64 * 1024 * 1024`, `MIN_IMPORT_BYTE_CAP = 1 * 1024 * 1024`, `MAX_IMPORT_BYTE_CAP = 1 * 1024 * 1024 * 1024`, and Typer validation helper.
- [ ] Add `finalize_imported_run(run_dir, run_id, import_state)` that writes `final.json` (`agent_outcome="unknown"` for `full`, `"partial"` for `partial|skipped`), seals `pre_eval`, runs `evaluate()`, seals `final`, and best-effort indexes with `sqlite_index.index_run()`.
- [ ] Update `import_claude_session._import_one()` to call `parse_session(..., byte_cap=..., deep_parse_only=...)` and preserve duplicate-import no-op before any writes.
- [ ] Copy the transcript before seal and set `report.transcript_artifact`.
- [ ] Write `run.started` as the first event, followed by existing `command.started`, parsed `claude.*` events, and `command.finished` with `line_count` and `analysis_state`.
- [ ] Compute `display_title` from `parsed.first_user_message_text`; set it on `ImportReport`.
- [ ] Write `artifacts/import_report.json` and `artifacts/usage.json` before `finalize_imported_run()`.
- [ ] Add Typer options `--byte-cap INTEGER` and `--deep-parse-only/--no-deep-parse-only`.
- [ ] Integration test malformed Claude source: import succeeds, `analysis_state="partial"`, `run.started` is first event, manifest covers transcript/report/usage, eval exists, and `agentlens show --format json` includes projection keys.
- [ ] Integration test byte cap: default over-cap → `partial`; `--deep-parse-only` → `skipped` with no vendor-derived events.
- [ ] Patch CLI/security docs with the new flags and corrected transcript/new-artifact privacy wording.
- [ ] Run `pytest tests/integration/test_import_claude_session_report.py tests/integration/test_import_byte_cap.py -q`.

### Task 7: Codex command

**Files:** `AgentLens/src/agentlens/commands/import_codex_session.py`, `AgentLens/tests/integration/test_import_codex_session_report.py`, `AgentLens/tests/integration/test_import_byte_cap.py`

- [ ] Mirror Task 6 for `codex-session`.
- [ ] Preserve existing Codex Desktop vs CLI `agent.label` / `agent.mode` behaviour.
- [ ] Preserve existing parent linkage and pending-parent backfill after finalization.
- [ ] Write `usage.json` even when Codex Desktop has no token fields (`confidence="unknown"`, all counters zero).
- [ ] Add integration tests for Codex CLI exact usage, Codex Desktop unknown usage, manifest coverage, projection keys, parent-backfill regression, and byte-cap skipped behaviour.
- [ ] Run `pytest tests/integration/test_import_codex_session_report.py tests/integration/test_import_byte_cap.py tests/integration/test_import_codex_session.py -q`.

### Task 8: Query, API, projector, index, and type projection

**Files:** `AgentLens/src/agentlens/store/query.py`, `AgentLens/src/agentlens/store/sqlite_index.py`, `AgentLens/src/agentlens/commands/_format.py`, `AgentLens/src/agentlens/web/routers/runs.py`, `AgentLens/web/src/api/runs.ts`, `AgentLens/web/src/types/api.ts`, `AgentLens/tests/fixtures/format_snapshots/*.json`, `AgentLens/tests/integration/test_query_projection_usage_title.py`, `AgentLens/tests/integration/test_format_json_snapshot.py`, `AgentLens/tests/integration/test_web_e2e_runs_list.py`, `AgentLens/tests/integration/test_web_e2e_run_detail.py`

- [ ] In `store/query.py`, add a helper that locates the run dir from `(home, workspace_id, run_id)` and reads `artifacts/import_report.json` / `artifacts/usage.json`.
- [ ] Enrich rows from `latest()`, `full_scan_runs()`, `list_runs()`, and `get_run()` with `display_title`, `usage`, and `import_state`; emit `None` values when artifacts are missing.
- [ ] Update `_RUN_ROW_COLUMNS` / SQLite SELECT handling so SQLite-backed `latest()` still returns the same enriched shape as full-scan.
- [ ] In `sqlite_index.py`, add nullable columns `display_title`, `usage_confidence`, and `import_state`, idempotent migrations, and population from artifacts during `index_run()`.
- [ ] In `_format.py`, add the three additive keys to `project_run_row()` and `project_show()`, with defaults `None`, `None`, `None`.
- [ ] Update snapshot fixtures and run `AGENTLENS_UPDATE_SNAPSHOTS=1 pytest tests/integration/test_format_json_snapshot.py`.
- [ ] Update `/api/v1/runs` and `/api/v1/runs/{id}` tests so API payloads include the projector-derived fields and do not expose `source_path`.
- [ ] Run `npm --prefix AgentLens/web run gen-types` and commit the generated `web/src/types/api.ts` drift.
- [ ] Update `web/src/api/runs.ts` types to match generated schemas.
- [ ] Run `pytest tests/integration/test_query_projection_usage_title.py tests/integration/test_format_json_snapshot.py -q`.

---

# Phase 4 — Dashboard Surface + Close-Out

### Task 9: Dashboard UI and design spec patch

**Files:** `AgentLens/web/src/components/run-list-table.tsx`, `AgentLens/web/src/components/run-list-table.test.tsx`, `AgentLens/docs/spec/2026-05-19-agentlens-dashboard-design.md`

- [ ] Add run-list columns/cells for:
  - **Title** ← `display_title` with fallback to short `run_id`
  - **Usage** ← `usage.input_tokens` / `usage.output_tokens`, fallback `—`
  - **Cost** ← `usage.cost_usd`, fallback `—`
  - **Confidence** ← `usage.confidence` badge
  - **Import state** ← `import_state` badge; visually flag `partial` and `skipped`
- [ ] Keep the existing false-success highlighting and failure-count behaviour intact.
- [ ] Add Vitest coverage for populated usage/title/import-state and null fallback rendering.
- [ ] Patch the dashboard design spec's "Run list — signature screen" section with the five new data points and the rule: all five come from `store.query`/projectors; web routes never read derived importer artifacts directly for list rows.
- [ ] Run `npm --prefix AgentLens/web test -- run-list-table`.

### Task 10: End-to-end smoke + sign-off

**Files:** `AgentLens/docs/contract.md`, full repo verification

- [ ] Run focused Python tests: `pytest tests/unit/test_importers_title.py tests/unit/test_importers_usage.py tests/unit/test_importers_report.py tests/unit/test_claude_session_parser.py tests/unit/test_codex_session_parser.py -q`.
- [ ] Run importer/query integration tests: `pytest tests/integration/test_import_claude_session.py tests/integration/test_import_codex_session.py tests/integration/test_import_claude_session_report.py tests/integration/test_import_codex_session_report.py tests/integration/test_import_byte_cap.py tests/integration/test_query_projection_usage_title.py tests/integration/test_format_json_snapshot.py -q`.
- [ ] Run full Python suite: `pytest -q`.
- [ ] Run frontend tests affected by the new fields: `npm --prefix AgentLens/web test`.
- [ ] Manually import one real Claude session and one real Codex session from local history. Confirm:
  - `manifest.json` final phase covers `artifacts/transcripts/*`, `artifacts/import_report.json`, and `artifacts/usage.json`.
  - `eval.json` exists and is not failed solely because usage is unknown or import state is partial.
  - `agentlens latest --format json`, `agentlens status --format json`, `agentlens show <run_id> --format json`, and `/api/v1/runs` include `display_title`, `usage`, and `import_state`.
  - Duplicate import remains a no-op: no second run, no report/usage overwrite.
- [ ] Update `docs/contract.md` with a short additive-artifacts note: importers gained `import_report.json`, `usage.json`, and three additive query projection keys; no v1 schema changed.
- [ ] Run `git diff --check`.

---

## Definition of Done

- [ ] All checkboxes above are checked.
- [ ] `pytest -q` is green.
- [ ] Affected frontend tests are green.
- [ ] No edits to `run.schema.json`, `event.schema.json`, `final.schema.json`, `eval.schema.json`, or `manifest.schema.json`.
- [ ] Imported runs start `events.jsonl` with `run.started`.
- [ ] Imported runs are finalized: `final.json`, `eval.json`, `manifest.json`, and index row exist.
- [ ] `manifest.json` covers transcript, `import_report.json`, and `usage.json`.
- [ ] Duplicate import remains a no-op via `input.import_key`.
- [ ] `docs/cli.md`, `docs/security.md`, `docs/contract.md`, and the dashboard design spec reflect the additions and privacy reality.

## Out of Scope

| Item | Reason | Where it goes |
|------|--------|---------------|
| Pricing table for `cost_usd` | Needs vendor SKU mapping, refresh cadence, currency policy. | Follow-up spec; shape already reserved. |
| Safe HTML export (`agentlens export`) | No dashboard consumer yet. | ADR Phase D, post-v1. |
| Sanitized transcript copies | Existing transcript copy is raw vendor JSONL; redaction/export policy needs separate design. | ADR §5.5 follow-up. |
| TUI (`agentlens sessions`) | Redundant with dashboard for this patch. | ADR Phase E, post-v1. |
| `--refresh` for duplicate imports | Would change no-op idempotency semantics. | Follow-up CLI spec. |
| Title heuristic v2 / LLM-assisted titles | Determinism + offline operation win for v1.x. | Revisit after real dashboard samples. |
| Migrating `kws-cme`/`kws-cpe` event namespaces to lowercase | Already owned by `2026-05-19-agentlens-v1-and-kws-unification.md`. | That plan owns it. |
