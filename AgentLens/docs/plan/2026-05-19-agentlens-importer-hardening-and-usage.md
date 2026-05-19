# AgentLens Importer Hardening + Usage Summary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `kws-claude-multi-agent-executor` (Opus orchestrator + Sonnet implementers) to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Risk default for all tasks: **mid**.

**Goal:** Adopt three ADR (`docs/adr/2026-05-19-agentlens-ecosystem-benchmark.md`) patterns — large-session safety (§5.2), display-title heuristic (§5.6), and usage summary (§5.3) — without modifying the locked v1 contract. Every addition lands as an artifact or query projection.

**Companion design spec:** `docs/spec/2026-05-19-agentlens-importer-hardening-and-usage.md` (read first; this plan executes that spec).

**Tech stack:** Python 3.12, Typer, JSON Schema, pytest, existing AgentLens importers (`store/{claude,codex}_session.py`, `commands/import_{claude,codex}_session.py`).

---

## Engineering Review Findings

| ID | Severity | Finding | Plan correction |
|----|----------|---------|-----------------|
| E1 | Blocker | The locked v1 schemas (`run.json`, `events.jsonl`, `final.json`, `eval.json`) cannot accept new fields without contract revision. | All new data lands as artifacts (`import_report.json`, `usage.json`) and query projections. Zero schema diffs. |
| E2 | Blocker | Existing importers return only `ParsedSession` / `ParsedCodexSession`; there is no place to plumb `ImportReport`. Adding a second return value would break in-tree callers. | Introduce a new `importers.report.ImportReport` dataclass; importer functions return a `(parsed, report)` tuple. All call-sites (currently only `commands/import_*_session.py`) are updated in the same task. |
| E3 | High | The title heuristic could leak prompt content if implemented loosely. | Heuristic is a pure function with deterministic strip rules and unit-test fixtures; no LLM, no network. Result is capped at 120 chars. The full first-user-message is never persisted. |
| E4 | High | Usage extraction with missing fields could silently report `confidence="exact"`. | Confidence derivation is rule-driven (§3.3 of spec); `diagnostics.events_missing_usage > 0` forces at least `estimated`. Test fixture covers each branch. |
| E5 | High | The dashboard spec (`docs/spec/2026-05-19-agentlens-dashboard-design.md`) currently has no column for usage, title, or import state — implementing the projection without patching the design spec will fork the truth. | Task 5 patches the dashboard spec to add the three columns in its "Runs list" section. |
| E6 | Medium | A re-import overwrites the previous `import_report.json` and `usage.json` with no audit trail. | Documented behaviour (spec §6). Manifest's sealed history at the prior `final` phase preserves forensics. Surfaced in `docs/security.md` patch (Task 6). |
| E7 | Medium | `--byte-cap` with extreme values could OOM or accept zero. | Validate in Typer callback: min 1 MiB, max 1 GiB. Out-of-range → `typer.BadParameter` with explicit allowed range. |

---

## File Structure

### Create

| Path | Responsibility |
|------|----------------|
| `AgentLens/src/agentlens/importers/__init__.py` | Package marker. |
| `AgentLens/src/agentlens/importers/title.py` | `extract_display_title()` pure heuristic. |
| `AgentLens/src/agentlens/importers/usage.py` | `extract_usage(parsed) -> UsageSummary` per-vendor extractor. |
| `AgentLens/src/agentlens/importers/report.py` | `ImportReport` dataclass + `emit_report()` writer. |
| `AgentLens/tests/unit/test_importers_title.py` | Pure title-heuristic tests. |
| `AgentLens/tests/unit/test_importers_usage.py` | Vendor-by-vendor usage extractor tests. |
| `AgentLens/tests/unit/test_importers_report.py` | Counter aggregation + state derivation tests. |
| `AgentLens/tests/integration/test_import_claude_session_report.py` | Claude import end-to-end with malformed/oversized lines. |
| `AgentLens/tests/integration/test_import_codex_session_report.py` | Codex CLI + Desktop import end-to-end with/without usage. |
| `AgentLens/tests/integration/test_import_byte_cap.py` | Byte-cap behaviour: partial vs skipped. |
| `AgentLens/tests/integration/test_query_projection_usage_title.py` | Projection shape (imported vs container runs). |
| `AgentLens/tests/fixtures/sessions/claude-with-usage.jsonl` | Full-tokens Claude fixture. |
| `AgentLens/tests/fixtures/sessions/claude-mixed-usage.jsonl` | Partial-tokens Claude fixture. |
| `AgentLens/tests/fixtures/sessions/claude-malformed-line.jsonl` | One bad JSON line in middle. |
| `AgentLens/tests/fixtures/sessions/codex-cli-with-usage.jsonl` | Codex CLI rollout with tokens. |
| `AgentLens/tests/fixtures/sessions/codex-desktop-no-usage.jsonl` | Codex Desktop rollout without tokens. |
| `AgentLens/tests/fixtures/sessions/codex-oversized-line.jsonl` | Single >2 MiB row. |
| `AgentLens/tests/fixtures/titles/` (directory) | Paired `<name>.input.txt` / `<name>.expected.txt` files. |

### Modify

| Path | Change |
|------|--------|
| `AgentLens/src/agentlens/store/claude_session.py` | Stream parser tracks `lines_*` counters and oversized rows; honours byte cap; returns `(ParsedSession, ImportReport)`. |
| `AgentLens/src/agentlens/store/codex_session.py` | Same change for rollouts. |
| `AgentLens/src/agentlens/store/query.py` | Run projection injects `display_title` / `usage` / `import_state` (null when absent). |
| `AgentLens/src/agentlens/commands/import_claude_session.py` | Add `--byte-cap` + `--deep-parse-only`; extract title; extract usage; write both new artifacts; consume the `(parsed, report)` tuple. |
| `AgentLens/src/agentlens/commands/import_codex_session.py` | Same surface changes for the Codex importer. |
| `AgentLens/src/agentlens/store/sqlite_index.py` | Add nullable `display_title`, `usage_confidence`, `import_state` columns; populated on insert, queryable for dashboard list. |
| `AgentLens/docs/security.md` | One bullet under "Storage rules" documenting the two new artifacts (no prompt/output content). |
| `AgentLens/docs/cli.md` | Document `--byte-cap` and `--deep-parse-only` for both import commands. |
| `AgentLens/docs/spec/2026-05-19-agentlens-dashboard-design.md` | Add Title / Usage / Cost / Confidence / Import-state columns to the Runs list section. |

### Delete

None. This work is purely additive.

---

# Phase 1 — Pure-function building blocks

Each module in this phase ships standalone with unit tests. No importer integration yet. These tasks can run in parallel (no shared file edits).

### Task 1: `importers.title.extract_display_title` + unit tests

**Files:** `importers/title.py`, `tests/unit/test_importers_title.py`, `tests/fixtures/titles/`

**Why:** Pure function. The runs-list column needs this before the importer integrates it. Easiest to land first; no cross-cutting risk.

- [ ] Write failing tests covering each strip rule in spec §3.2: `None` / empty / fenced code block / `<AGENTS>` block / inline code / `<<sentinel>>` / absolute path / control chars / URL preservation / UTF-8 cap / U+2026 suffix / punctuation-only → `None` / deterministic over rerun.
- [ ] Create `tests/fixtures/titles/` with at least 8 paired `<name>.input.txt` and `<name>.expected.txt` files (one per strip rule plus two real-session samples — one Claude, one Codex).
- [ ] Implement `importers/title.py` with the algorithm from spec §3.2 step 1-6. Keep it under 80 lines. No regex flags beyond `re.MULTILINE | re.DOTALL` where needed.
- [ ] Verify all unit tests pass.
- [ ] Add a property test: random-byte input never raises, always returns `str | None`.

### Task 2: `importers.usage.extract_usage` + unit tests

**Files:** `importers/usage.py`, `tests/unit/test_importers_usage.py`, `tests/fixtures/sessions/claude-with-usage.jsonl`, `tests/fixtures/sessions/claude-mixed-usage.jsonl`, `tests/fixtures/sessions/codex-cli-with-usage.jsonl`, `tests/fixtures/sessions/codex-desktop-no-usage.jsonl`

**Why:** Second pure function. Token extractors are vendor-specific; isolating them simplifies future vendor additions.

- [ ] Define `UsageSummary` dataclass matching spec §3.3 shape (token counters, model_breakdown, cost_usd=None, pricing_source="unknown", confidence, diagnostics).
- [ ] Write failing tests: exact / estimated / unknown branch each; multi-model breakdown; Codex Desktop no-tokens → `confidence="unknown"`.
- [ ] Create the four session fixtures (small, ~10 events each).
- [ ] Implement two extractors: `extract_usage_from_claude(parsed: ParsedSession) -> UsageSummary` and `extract_usage_from_codex(parsed: ParsedCodexSession) -> UsageSummary`. Expose a single `extract_usage(source, parsed) -> UsageSummary` dispatcher.
- [ ] Implement confidence derivation per spec §3.3 table. Hard-code: any non-zero `events_missing_usage` → at least `estimated`; `events_with_usage == 0` → `unknown`.
- [ ] Verify all unit tests pass.

### Task 3: `importers.report.ImportReport` + unit tests

**Files:** `importers/report.py`, `tests/unit/test_importers_report.py`

**Why:** Pure container/aggregator. Independent of the other two tasks.

- [ ] Define `ImportReport` dataclass matching spec §3.1 shape.
- [ ] Write failing tests: counter aggregation, `analysis_state` derivation (`full` / `partial` / `skipped`), `byte_cap_hit` flag, `first_error` recording (first only; later errors don't overwrite).
- [ ] Implement the dataclass + factory helpers (`new_report(source, source_path, ...)`, `report.record_skip(reason, line_no, byte_offset)`, `report.finalize(parsed_lines, duration_ms)`).
- [ ] Implement `emit_report(run_dir: Path, report: ImportReport)` that writes `<run_dir>/artifacts/import_report.json`.
- [ ] Verify all unit tests pass.

---

# Phase 2 — Parser integration

This phase modifies the two existing parsers to honour the byte cap and populate `ImportReport`. Cannot parallelise across Task 4 and Task 5 if they touch the same shared helpers; in practice they touch disjoint files (`claude_session.py` vs `codex_session.py`), so they CAN run in parallel.

### Task 4: Claude parser — byte cap, counters, oversized rows, ImportReport plumbing

**Files:** `store/claude_session.py`, `tests/unit/test_claude_session_parser.py` (existing — extended)

- [ ] Add a new return signature: `parse_session(path: Path, *, byte_cap: int = 64 * 1024 * 1024) -> tuple[ParsedSession, ImportReport]`. Keep the existing function name (no overload).
- [ ] Stream-read line-by-line using a buffered iterator that tracks running byte offset; stop when `byte_offset >= byte_cap` and set `report.byte_cap_hit=True`.
- [ ] On any single-line size probe over **2 MiB** (use `len(line.encode("utf-8"))` from the iterator; do NOT call `json.loads` first), record `skipped_oversized` and continue.
- [ ] On `json.JSONDecodeError`, record `skipped_malformed` (with first-error capture if `report.first_error is None`).
- [ ] On an unrecognised event shape (no known role/kind), record `skipped_unsupported_type:<typestring>`.
- [ ] Update unit tests in `test_claude_session_parser.py`: add cases asserting the report's counters; assert the existing parsed-events behaviour is unchanged when no skips occur.
- [ ] Verify the existing integration test (`tests/integration/test_import_claude_session.py`) still passes.

### Task 5: Codex parser — byte cap, counters, oversized rows, ImportReport plumbing

**Files:** `store/codex_session.py`, `tests/unit/test_codex_session_parser.py` (existing — extended), `tests/fixtures/sessions/codex-oversized-line.jsonl`

- [ ] Same signature change: `parse_rollout(path, *, byte_cap=...) -> tuple[ParsedCodexSession, ImportReport]`.
- [ ] Same stream/cap/skip rules as Task 4.
- [ ] Create `codex-oversized-line.jsonl` fixture (one row padded with `"x" * (2 * 1024 * 1024 + 1)` worth of content inside a `payload.content` string field).
- [ ] Extend `test_codex_session_parser.py` with oversized-line, malformed-line, and byte-cap-hit cases.
- [ ] Verify existing integration tests (`test_import_codex_session.py`) still pass.

---

# Phase 3 — Command integration

### Task 6: Update `import_claude_session` command

**Files:** `commands/import_claude_session.py`, `tests/integration/test_import_claude_session_report.py`, `tests/integration/test_import_byte_cap.py` (Claude half), `docs/cli.md`, `docs/security.md`

- [ ] Add Typer options `--byte-cap INTEGER` (default 64 MiB, validated 1 MiB ≤ value ≤ 1 GiB) and `--deep-parse-only/--no-deep-parse-only` (default false).
- [ ] Replace the parser call to use the new tuple return; thread `byte_cap` through.
- [ ] When the source size exceeds `byte_cap` AND `--deep-parse-only` is set: build a stub run (no events) with `report.analysis_state="skipped"`. Still copy the transcript to `artifacts/transcripts/`.
- [ ] Call `extract_display_title(explicit=None, first_user_message=parsed.first_user_message_text)`. Attach to the in-memory projection layer only — do NOT write into `run.json`.
- [ ] Call `extract_usage(source="claude-session", parsed=parsed)`. If the resulting summary has any non-zero counter or `events_with_usage > 0`, write `artifacts/usage.json`; else skip (null projection).
- [ ] Call `emit_report(run_dir, report)` after the run is otherwise complete and BEFORE the final manifest seal.
- [ ] Confirm the existing seal step picks up both new artifact files (no manifest code change required).
- [ ] Add integration test `test_import_claude_session_report.py` covering: malformed-line source → `analysis_state="partial"`, manifest covers `import_report.json` + `usage.json`, `agentlens show <run_id> --format json` returns the projection.
- [ ] Add a case to `test_import_byte_cap.py` for Claude: source > cap default → `partial`; with `--deep-parse-only` → `skipped`.
- [ ] Patch `docs/cli.md` with the two new flags.
- [ ] Patch `docs/security.md`: add one bullet under Storage rules — *"Importers may write `artifacts/import_report.json` (line counts, skip reasons, byte-cap state) and `artifacts/usage.json` (token totals, model breakdown, optional cost). Neither contains prompt or output text."*

### Task 7: Update `import_codex_session` command

**Files:** `commands/import_codex_session.py`, `tests/integration/test_import_codex_session_report.py`, `tests/integration/test_import_byte_cap.py` (Codex half)

- [ ] Mirror Task 6 changes for the Codex importer.
- [ ] Integration test specifically distinguishes Codex CLI (tokens present → `confidence="exact"`) from Codex Desktop (no tokens → `confidence="unknown"`, `usage.json` still written with all-zero counters and `events_with_usage=0`).
- [ ] Add the Codex byte-cap case to `test_import_byte_cap.py`.

### Task 8: Query projection — `display_title`, `usage`, `import_state`

**Files:** `store/query.py`, `store/sqlite_index.py`, `tests/integration/test_query_projection_usage_title.py`

- [ ] In `store/query.py`, after assembling the existing run projection dict, attempt to read `artifacts/import_report.json` (if missing → `import_state=None`); read `analysis_state` into `import_state`.
- [ ] Attempt to read `artifacts/usage.json` (if missing → `usage=None`); otherwise project the public subset (input/output/cache_creation/cache_read/reasoning tokens, cost_usd, pricing_source, confidence).
- [ ] Re-derive `display_title` at query time by re-running `extract_display_title()` against the first preserved user-message excerpt (which IS persisted in `events.jsonl` via the existing namespaced events). If no first-user event → `None`. **Why query-time:** the heuristic will evolve; rebuilding from artifacts means runs improve automatically as the heuristic improves, no re-import required.
- [ ] In `store/sqlite_index.py`, add three nullable columns: `display_title TEXT`, `usage_confidence TEXT`, `import_state TEXT`. Populate on insert (existing insert path runs after artifacts are sealed). Migrate the index file by adding the columns if missing (the index is rebuildable from JSON, so a destructive rebuild is acceptable, but additive migration avoids unnecessary scans).
- [ ] Write `test_query_projection_usage_title.py`: imported Claude run → all three keys populated; imported Codex Desktop run → `usage` populated but `usage.confidence="unknown"`; container run from `agentlens run-open` → all three keys are `null`.
- [ ] Run the full integration suite; confirm no existing test breaks.

---

# Phase 4 — Dashboard spec patch + close-out

### Task 9: Dashboard design spec patch

**Files:** `docs/spec/2026-05-19-agentlens-dashboard-design.md`

- [ ] In the "Runs list columns" section (or equivalent — read the spec first), append a paragraph listing the five new dashboard data points sourced from this work:
  - **Title** ← `display_title`
  - **Usage (in/out)** ← `usage.input_tokens` / `usage.output_tokens`
  - **Cost** ← `usage.cost_usd` (renders `—` when `null`)
  - **Confidence** ← `usage.confidence` badge (`exact` / `estimated` / `unknown`)
  - **Import state** ← `import_state` badge; `partial` runs visually flagged
- [ ] Add one sentence: *"All five fields come from the run projection (`store.query`); web routes never read artifacts directly."*
- [ ] Confirm the patch is consistent with the dashboard's "Web routes call only `store.query`" rule from the ADR.

### Task 10: End-to-end smoke + sign-off

**Files:** none new

- [ ] Run `pytest -q` against the full suite. All green.
- [ ] Manually import one real Claude session and one real Codex session from local history (`~/.claude/projects/*`, `~/.codex/sessions/*`):
  - Confirm `agentlens show <run_id> --format json` returns `display_title`, `usage`, `import_state`.
  - Confirm `manifest.json` for both runs covers `artifacts/import_report.json` and `artifacts/usage.json` with non-empty sha256.
- [ ] Verify a re-import is still a no-op for the run record itself, and the report+usage artifacts are overwritten (timestamps update; existing `input.import_key` scan unchanged).
- [ ] Confirm `eval.json` of an imported run with `analysis_state="partial"` is NOT failed because of the partial state (partial analysis is observation, not evidence).
- [ ] Tag the commit; update `docs/contract.md`'s changelog with: *"Importers gained `import_report.json` and `usage.json` artifacts and three additive query projection fields (`display_title`, `usage`, `import_state`). No schema fields changed."*

---

## Definition of Done

- [ ] All checkboxes above are checked.
- [ ] `pytest -q` is green.
- [ ] No edits to `run.schema.json`, `event.schema.json`, `final.schema.json`, or `eval.schema.json`.
- [ ] `manifest.json` of every imported run covers both new artifacts.
- [ ] `docs/cli.md`, `docs/security.md`, `docs/spec/2026-05-19-agentlens-dashboard-design.md`, and `docs/contract.md` reflect the additions.
- [ ] The companion design spec (`docs/spec/2026-05-19-agentlens-importer-hardening-and-usage.md`) needs no edits — implementation matched the spec, or the spec was patched in the same PR as the implementation.

## Out of Scope (do not pull in)

| Item | Reason | Where it goes |
|------|--------|---------------|
| Pricing table for `cost_usd` | Needs vendor SKU mapping, refresh cadence, currency policy. | Follow-up spec; shape already reserved. |
| Safe HTML export (`agentlens export`) | No dashboard consumer yet. | ADR Phase D, post-v1. |
| TUI (`agentlens sessions`) | Redundant with dashboard. | ADR Phase E, post-v1. |
| Sanitized transcript copies | Privacy decision deferred. | Future spec when export ships. |
| Title heuristic v2 (LLM-assisted) | Determinism + offline > smarter-but-flaky. | Revisit only if heuristic fails real samples in dashboard testing. |
| Migrating `kws-cme`/`kws-cpe` event namespaces to lowercase | Already handled by `2026-05-19-agentlens-v1-and-kws-unification.md`. | That plan owns it. |
