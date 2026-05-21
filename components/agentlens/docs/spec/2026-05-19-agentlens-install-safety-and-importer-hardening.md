# AgentLens v1.x — Install Safety + Importer Hardening (Combined) — Design Spec

**Date:** 2026-05-19
**Status:** Draft
**Scope:** `agentlens install`, shim integrity model, doctor diagnostics, Claude/Codex session importers, query/API/dashboard projections

This document is the single source of truth for both topics. Two prior per-topic specs (`install-wrapper-safety` + `importer-hardening-and-usage`) were consolidated here and removed; their substance is preserved in §0 (corrections), §3 (install safety design), and §4 (importer hardening design). The companion plan executes this design.

**Local baseline:** `docs/contract.md`, `docs/security.md`, `docs/spec/2026-05-19-agentlens-dashboard-design.md`, `src/agentlens/commands/install.py`, `src/agentlens/adapters/shims.py`, `src/agentlens/commands/doctor.py`, `src/agentlens/commands/import_{claude,codex}_session.py`, `src/agentlens/store/{claude,codex}_session.py`.

---

## 0. Source-Review Corrections (binding)

These corrections were applied after reading current source at `019347ee37747572c28943e80fb18cfad6e58651` and re-checking against `e94babd0144ad4fbbfc41cda096e56bf43319a90`. Where this list contradicts earlier wording elsewhere, this list wins.

### 0.1 Install / shim subsystem

| ID | Severity | Finding | Correction |
|----|----------|---------|------------|
| W1 | Blocker | `.app` refusal at `adapters/shims.py:177-181` landed at commit `7c8df6f` (2026-05-19 09:26). Installs from before that timestamp baked unsafe lockfiles; no later code or `doctor` check detects and corrects them. | Layer 5 (`doctor` wrapper detection) surfaces existing broken installs and prints the exact remediation command. No automatic mutation. |
| W2 | Blocker | `commands/install.py:84` calls `shutil.which(agent)` and accepts the result unconditionally. The result can be any wrapper script that itself routes through PATH. | Layer 1 signature detection + Layer 2 self-reference + Layer 3 PATH-conflict warning at install time. |
| W3 | High | Even with install-time guards, novel wrapper shapes can slip past signature detection. | Layer 4 post-install selftest probe runs the shim once with a reserved env var, actually executes the candidate `.real` under guarded depth, and rolls back if AgentLens re-entry is detected. |
| W4 | High | `SHIM_TEMPLATE` is invariant to the selftest probe. | Add a guarded selftest branch after `REAL_PATH` is read; only enters when `AGENTLENS_INSTALL_SELFTEST=1` AND argv is exactly `--version`. |
| W5 | High | Existing tests use shell-script fixtures and chmodded byte blobs for `install_shim`; wrapper detection and the executable selftest will fail some of them for the wrong reason. | Test audit keeps binary markers scanner-only, uses benign executable fixtures for tests that reach selftest, and uses `skip_selftest=True` / explicit wrapper bypasses only for narrow lockfile or bypass assertions. |
| W6 | Blocker | A print-only selftest branch that exits from the first AgentLens shim never executes the candidate `.real` wrapper, so it cannot catch the novel wrapper loops Layer 4 is meant to catch. | Layer 4 is a guarded **re-entry probe**: the first shim invocation executes `$REAL_PATH --version` under `AGENTLENS_INSTALL_SELFTEST_DEPTH=1` with the new shim dir first in `PATH`; any re-entry into the shim prints `agentlens_selftest_reentry=1` / `chain_depth>1` and fails the install. |
| W7 | Medium | The PATH-conflict warning cannot be computed reliably after the shim is written; if `~/.agentlens/shims` is already on `PATH`, `shutil.which(agent)` may now return the new shim instead of the pre-install wrapper. | Capture `pre_install_resolution = shutil.which(agent)` before any writes and base Layer 3 warning on that captured path after install succeeds. |
| W8 | Medium | Existing shim tests include fake files like `b"hello world\n"` that are chmodded executable but are not valid executables. A real selftest probe would fail them for the wrong reason. | Detection-only tests may use binary markers. Any test that reaches selftest must use a real executable fixture (for example a benign shell script with `--version` support and no wrapper signatures) or pass `skip_selftest=True` in pure lockfile/security unit tests. |

### 0.2 Importer subsystem

| ID | Severity | Finding | Correction |
|----|----------|---------|------------|
| E1 | Blocker | The locked v1 schemas (`run.json`, `events.jsonl`, `final.json`, `eval.json`, `manifest.json`) have `additionalProperties:false`. Adding fields would break the contract. | All new data lands in `artifacts/import_report.json`, `artifacts/usage.json`, query/API projection keys, and nullable SQLite cache columns. **Zero schema diffs.** |
| E2 | Blocker | Current `commands/import_*_session.py` write `run.json`, `events.jsonl`, transcript copy, and workspace pointer only. They do NOT write `final.json`, `eval.json`, `manifest.json`, or index rows. Earlier wording claiming imported transcripts are manifest-covered is false for current code. | Add `commands/import_common.py::finalize_imported_run()` that writes `final.json`, seals `pre_eval`, runs `evaluate()`, seals `final`, then opens SQLite via `init_db(agentlens_home())` and calls `index_run(conn, run_dir)`. This becomes the importer finalization pipeline. |
| E3 | Blocker | Evaluator check `run_started` requires the first event to be `run.started`; current importers begin with `command.started`. | Importers prepend `run.started`, then keep existing `command.started` / `command.finished` events for compatibility. |
| E4 | High | `_iter_jsonl()` in both parsers loads the entire source with `path.read_text()`. A byte cap wrapped around the existing iterator is unsafe. | Replace with a binary streaming iterator that counts byte offsets and line sizes before decoding. |
| E5 | High | `ParsedSession` / `ParsedCodexSession` do not expose first user message or billable raw records. | Extend with `first_user_message_text: str | None` and `usage_records: list[dict[str, Any]]`. |
| E6 | High | Title needs a source of truth; Claude normalized events do not include user messages. | Store the redacted derived title under `import_report.derived.display_title`; query/API project it from that artifact. |
| E7 | High | `store.writer.atomic_write_json()` requires a `schema` field; `import_report.json` and `usage.json` are deliberately not schema documents. | Add `importers/artifacts.py::write_artifact_json()` for atomic non-schema artifact JSON writes (temp + fsync + replace, deterministic sort). |
| E8 | High | Adding `display_title`, `usage`, `import_state` affects locked JSON projectors, snapshots, generated TS types, AND `/api/v1/runs` — not just `store/query.py`. | Single task owns all of `store/query.py`, `commands/_format.py`, snapshot fixtures, generated frontend types, API typings, and route tests. |
| E9 | Medium | Existing `input.import_key` behaviour is a real no-op on duplicate import. Overwriting report/usage on re-import would break v1 contract. | Preserve no-op idempotency. A future `--refresh` flag is deferred. |
| E10 | Medium | Imported transcript copy uses `shutil.copyfile()` and bypasses `store.writer` redaction. | Do not claim transcript redaction. New artifacts must avoid full prompt/output bodies except the capped redacted title. Patch `docs/security.md` honestly. |
| E11 | Medium | Counting every non-emitted vendor line as unsupported would mark normal sessions partial. | Count `skipped_unsupported_type` only for lines the parser cannot classify; valid-but-not-emitted vendor lines remain supported (use an allowlist). |
| E12 | Medium | `pyproject.toml` test extras only include `pytest`; Hypothesis is not available. | Use deterministic fuzz loops in title tests; do not add `hypothesis` as a dependency. |
| E13 | High | `import_report.source_path` as an absolute vendor JSONL path would bypass the writer redaction pipeline and contradict `docs/security.md`'s absolute-home-path masking contract. | Store a redacted `source_path` label plus `source_path_hash`; never persist the raw absolute source path in `import_report.json`. |
| E14 | High | If parsers only append raw records that already contain usage fields to `usage_records`, `extract_usage()` cannot know how many billable lines were missing usage, so `confidence="exact"` can be falsely emitted. | `usage_records` contains **all billable vendor records**, including records with missing/empty usage. The extractor computes `events_with_usage` and `events_missing_usage` from that full denominator. |
| E15 | High | `sqlite_index.index_run()` requires an initialized SQLite connection (`index_run(conn, run_dir)`), but earlier wording made the finalizer sound like it could call `index_run()` directly. | `finalize_imported_run()` opens via `sqlite_index.init_db(agentlens_home())`, calls `index_run(conn, run_dir)`, closes the connection, and absorbs indexing errors only after JSON artifacts are durable. |

---

## 1. Problem

Two distinct gaps surface in the current AgentLens v1 implementation. They are unrelated in cause but related in code surface (both modify `install`/`shim`/`doctor` and the importer family), so they are best executed in a single sequenced effort.

### 1.1 Install creates an exec-loop trap

`agentlens install <agent>` writes the shim's `.real` lockfile to whatever `shutil.which(<agent>)` returns. The `.app`-bundle refusal added at `7c8df6f` catches only the specific case of cmux's launcher; any other wrapper script (homebrew `/usr/local/bin/<agent>`, user shell functions, vendored launchers outside `.app`) bypasses it. Combined with the post-install hint to prepend `~/.agentlens/shims` to PATH, this creates an A↔B exec loop the moment another wrapper exists earlier in PATH. Each loop iteration may add args (cmux injects ~1.5 KiB of `--session-id` + `--settings <HOOKS_JSON>` per cycle), so argv grows until `ARG_MAX = 1 MiB` is exceeded and execve fails with `E2BIG / Argument list too long`. **Any new user installing AgentLens from inside a cmux terminal session hits this within seconds.**

### 1.2 Importers are unfinalized and unobservable

Current importers handle the narrow happy path: locate JSONL, parse parseable lines, write `run.json`/`events.jsonl`, copy the transcript, stop. Four downstream consequences:

1. **Imported runs are not sealed/indexed.** The wrapper's post-drain pipeline (`final.json` → `seal(pre_eval)` → `eval.json` → `seal(final)` → `index_run`) is not executed. So existing docs that claim transcripts are manifest-covered are aspirational, not true.
2. **Partial parses are invisible.** A malformed or oversized line is skipped with a `stderr` warning; downstream tooling cannot tell "fully parsed" from "best-effort parsed" from "skipped".
3. **No human-readable run identity.** The dashboard runs list (per the v1 design spec) needs a `display_title`, but importers never extract one.
4. **No usage/cost summary.** Tools like `ccusage` already answer "what did this run cost?" from raw vendor logs; AgentLens has the strictly better substrate (sealed, evidence-linked) but does not expose token or cost data at all.

Both gaps are filled by **additive, contract-stable** changes. Nothing in the locked v1 schemas moves. All new fields land as artifacts, query projections, or SQLite cache columns.

## 2. Goals & Non-Goals

### Goals

**Install safety:**
- Refuse at install time when the candidate `.real` is itself a wrapper script that would create an exec loop after PATH is updated.
- Catch any residual loop with a post-install selftest probe; roll back on failure.
- Surface existing broken installs via `agentlens doctor` with the exact remediation command.

**Importer hardening:**
- Make every importer emit a structured `import_report` distinguishing `full` / `partial` / `skipped` analysis with per-skip counters.
- Bound importer memory and runtime via an explicit per-file byte cap, with `partial` semantics when the cap is hit.
- Extract a redacted `display_title` via a pure heuristic; surface through query projections only (storage in `import_report.derived` for re-projection).
- Emit an additive `usage` artifact + query projection for every imported run (input/output/cache/reasoning tokens, optional cost, mandatory `confidence` field).
- Finalize imported runs so `final.json`, `eval.json`, `manifest.json`, and the SQLite index reflect imported sessions like other capture runs.
- Keep all new data covered by `manifest.json` like every other artifact.

### Non-Goals

- Modifying the locked v1 schemas (`run.json` / `events.jsonl` / `final.json` / `eval.json` / `manifest.json`).
- Automatic shell-rc editing (violates consent model — spec §S1.6.18).
- Automatic mutation of existing `.real` lockfiles (consent model).
- Heuristics for "step past a detected wrapper" — the user is asked to pass `--real` explicitly.
- Pricing-table maintenance and currency conversion (v1.x emits `pricing_source="unknown"` and leaves `cost_usd=null`; pricing comes later as a separate spec).
- Sanitized transcript copies for export (ADR §5.5, deferred).
- TUI / fuzzy search (ADR §5.7, deferred).
- Vendor session mutation. Importers remain read-only against `~/.claude/projects/*` and `~/.codex/{sessions,archived_sessions}/*`.
- Windows shim support.
- Migrating `kws-cme` / `kws-cpe` event namespaces to lowercase — already owned by `2026-05-19-agentlens-v1-and-kws-unification.md`.

## 3. Design — Part A: Install Wrapper Safety (5 layers)

Five layers of defense, ordered cheapest-to-most-disruptive. Each closes a slice of the bug class.

### 3.1 Layer 1 — Wrapper-signature detection at install time

`install_shim` reads the first **16 KiB** of the candidate `.real` file. If the head does NOT start with `b"#!"` → accept (Mach-O / ELF). Otherwise scan the read window with these patterns (first-match wins, order matters):

```python
ANTI_WRAPPER_SIGNATURES = [
    # category="agentlens_self"  — self-reference; would loop
    (rb"agentlens\s+run\s+--agent", "agentlens_self"),
    # category="cmux"  — cmux launcher signatures
    (rb"find_real_claude",           "cmux"),
    (rb"CMUX_AGENT_LAUNCH",          "cmux"),
    (rb"CMUX_BUNDLED_CLI_PATH",      "cmux"),
    (rb"HOOKS_JSON",                 "cmux"),
    # category="path_lookup"  — generic "look up binary by name through PATH"
    (rb"command -v (claude|codex)\b", "path_lookup"),
    (rb"which (claude|codex)\b",      "path_lookup"),
    (rb"\bexec\b[^\n]*\$PATH[^\n]*(claude|codex)\b", "path_lookup"),
]
```

On match, refuse with a structured `ValueError`:

| Category         | Refusal message remediation                                                                          |
|------------------|------------------------------------------------------------------------------------------------------|
| `agentlens_self` | "Candidate is itself an AgentLens shim. Pass `--real <ultimate binary>` explicitly."                 |
| `cmux`           | "Candidate is the cmux launcher. Use `--cmux` for chained mode, OR `--real <ultimate binary>` to bypass cmux." |
| `path_lookup`    | "Candidate is a shell script that resolves `<agent>` through PATH; baking it risks an exec loop. Pass `--real <ultimate binary>`." |

The existing `.app` refusal stays (defense in depth) but is no longer the primary guard.

### 3.2 Layer 2 — Self-reference guard

After `real = Path(real_path).resolve(strict=True)`:

```python
if real.parent.resolve() == _shim_dir().resolve():
    raise ValueError(
        f"refusing to bake {real} as .real — it is itself in the AgentLens "
        f"shim directory. Pass --real <ultimate binary>."
    )
```

Catches re-install accidents where `shutil.which` returns the already-installed shim.

### 3.3 Layer 3 — PATH-conflict warning (advisory)

Before any install writes, capture `pre_install_resolution = shutil.which(agent)`. Immediately before printing the "Add to your shell rc" hint, evaluate the captured path (not a fresh post-install lookup) and:
- If `pre_install_resolution is None` → no warning.
- If `Path(pre_install_resolution).resolve() == Path(real_path).resolve()` → no warning.
- If `pre_install_resolution` is NOT a shell script (no `#!` prefix) → no warning (binary-vs-binary is normal homebrew/cask state).
- Otherwise → emit to stderr:

```
warning: your shell currently resolves `<agent>` to <current>,
which is a wrapper script. The proposed PATH change makes AgentLens's shim
resolve first, but that shim execs <real_path> — bypassing <current>.
If you intended the wrapper to remain in the chain, use:
  agentlens install <agent> --real <wrapper> --no-wrapper-detect   (NOT RECOMMENDED)
or for cmux specifically:
  agentlens install claude --cmux
```

Non-blocking.

### 3.4 Layer 4 — Post-install selftest probe + rollback

After writing shim+lockfile and BEFORE returning success, run a guarded re-entry probe. The install command intentionally simulates the user's future PATH by putting the shim directory first:

```python
result = subprocess.run(
    [str(shim_path), "--version"],
    timeout=5,
    capture_output=True,
    env={
        **os.environ,
        "PATH": f"{shim_path.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        "AGENTLENS_INSTALL_SELFTEST": "1",
        "AGENTLENS_INSTALL_SELFTEST_DEPTH": "0",
        "AGENTLENS_INSTALL_SELFTEST_SHIM": str(shim_path),
    },
    check=False,
)
```

The shim template detects `AGENTLENS_INSTALL_SELFTEST=1` AND `$1 == "--version"` after it has read `REAL_PATH` from the lockfile. In depth `0`, it executes `"$REAL_PATH" --version` with `AGENTLENS_INSTALL_SELFTEST_DEPTH=1` and captures the child output. If that child resolves back to the AgentLens shim, the depth `1` invocation prints `agentlens_selftest_reentry=1` and exits with a reserved non-zero status. The depth `0` invocation then reports failure to the installer.

On a non-reentering candidate, the depth `0` invocation prints:

```
shim_path=<shim path>
real_path=<resolved real path>
real_kind=<output of `file -b $REAL_PATH` first comma-segment>
chain_depth=1
real_exit_code=<exit code from REAL_PATH --version, informational only>
```

then `exit 0`. The probe parses stdout as key=value lines and validates:
- exit code is 0
- `chain_depth == 1`
- `shim_path` matches the installed shim
- `agentlens_selftest_reentry` is absent

On any failure (timeout, malformed output, `chain_depth != 1`, re-entry marker, reserved re-entry exit code) → delete shim + lockfile, restore prior versions if a snapshot exists, raise `RuntimeError` with captured stderr. A non-zero `real_exit_code` from the underlying binary's own `--version` handler is informational and does not by itself fail the install; the selftest is about AgentLens re-entry, not vendor CLI option support.

The selftest branch in the shim only triggers when argv is **exactly** `--version`; every other invocation falls through normally so a real user invocation cannot be hijacked.

`--skip-selftest` CLI flag is available for environments where the probe itself is unreliable. Default off.

### 3.5 Layer 5 — Doctor wrapper-chain detection

`agentlens doctor` reads each `<agent>.real` lockfile, runs Layer-1 signature scan against the target, and surfaces:

```json
{
  "integration_level": "shim",
  "shim_integrity": "wrapper_chain_warning",
  "wrapper_detected": "cmux",
  "remediation": "agentlens install claude --real /opt/homebrew/bin/claude --yes"
}
```

`shim_integrity` enum gains the new value `wrapper_chain_warning`. Existing values (`ok`, `drift_warning`, `missing`) unchanged. Text output prints one line per warning with the recommended remediation command.

This is the only mechanism that surfaces installs broken before any of layers 1-4 land. **No automatic mutation** — the user runs the printed command themselves.

## 4. Design — Part B: Importer Hardening (4 sub-designs)

### 4.1 Import report

Each imported run gains:

```
~/.agentlens/runs/<workspace_id>/<run_id>/artifacts/import_report.json
```

Shape (frozen for v1.x; additive thereafter):

```json
{
  "schema_version": "1",
  "source": "claude-session" | "codex-rollout",
  "source_path": "<redacted path label; never raw absolute>",
  "source_path_hash": "sha256:<hash of resolved absolute source path>",
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

| State     | Trigger |
|-----------|---------|
| `full`    | All lines parsed within `byte_cap_bytes`; no skips of any kind. |
| `partial` | At least one skip (malformed/oversized/unsupported), OR `byte_cap_hit=true`. Run is still written; canonical events come from parsed lines only. |
| `skipped` | Source larger than `byte_cap_bytes` AND `--deep-parse-only` set. Run is created with no vendor-derived events (just `run.started`/`command.started`/`command.finished`); transcript artifact still copied. |

**Byte caps:**
- Default `byte_cap_bytes = 64 MiB`. Overrides: `AGENTLENS_IMPORT_BYTE_CAP=<bytes>` env var; `--byte-cap <bytes>` CLI flag. Validated `1 MiB ≤ value ≤ 1 GiB`.
- **Per-line cap = 2 MiB.** Any single row over 2 MiB is `skipped_oversized` (size probe before `json.loads`).

**`skipped_unsupported_type` policy (per E11):** count only lines that the parser cannot classify into a known vendor type at all. Valid-but-not-emitted lifecycle/status lines stay supported via a per-vendor allowlist. This prevents normal sessions from being marked `partial` for benign reasons.

### 4.2 Display-title heuristic

Pure function `importers/title.py::extract_display_title()`:

1. If `explicit` is truthy after strip → return it (capped at `max_chars=120`).
2. If `first_user_message` is empty after strip → return `None`.
3. Strip in order, then collapse whitespace:
   - Triple-backtick fenced code blocks (entire block).
   - Inline `` `…` `` code spans.
   - `<<HEADLESS_KWS_ORCHESTRATOR>>` and any `<<…>>` sentinels.
   - `<AGENTS>…</AGENTS>` and `<system-reminder>…</system-reminder>` blocks (multiline).
   - Lines starting with `AGENTS:` / `# AGENTS` / `Environment:` / `Working directory:`.
   - Absolute file paths (regex `(?:/[\w.\-]+){2,}`) → `<path>`.
   - Control chars `\x00-\x08\x0b\x0c\x0e-\x1f`.
   - URLs preserved but capped at 64 chars with U+2026 if longer.
4. Take the first non-empty line of what remains.
5. Cap at `max_chars`; if truncated, append U+2026 (single char, not `...`).
6. If only punctuation/whitespace → `None`.

**Storage:** the result lives in `import_report.derived.display_title` (per E6). The full first-user-message text is **not** persisted — the heuristic runs in-memory during import; only the redacted output reaches disk.

**Why store in `import_report.derived` AND project from there:** the heuristic will evolve. Future runs use the new algorithm automatically through the projection layer; existing runs keep their already-computed redacted title (no reprocess needed). Versioned via `title_algorithm` field.

### 4.3 Usage summary

Pure function `importers/usage.py::extract_usage()` consumes vendor-specific `usage_records` (raw billable vendor-line dicts, captured by the parser per E5/E14, including records with missing usage fields) and emits:

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

| Condition | confidence |
|-----------|-----------|
| Every billable line in the source has a populated token field; no fallbacks. | `exact` |
| Mix of populated and inferred sources (e.g., one line missing `cache_read_tokens`, treated as 0). | `estimated` |
| No token fields recoverable, OR `events_with_usage == 0`, OR fewer than 50% of billable lines had any usage field. | `unknown` |

**Cost rules (v1.x):**
- Always emit `cost_usd: null`, `pricing_source: "unknown"`. Shape is reserved from day one so the eventual pricing patch is additive (value-only).
- Dashboard renders `cost = —` for `cost_usd == null`.

**Eval interaction:** `eval.json` MUST NOT fail when usage is missing or partial. Usage is observation, not evidence.

**Vendor extractors:**
- Claude: `line["message"]["usage"]` (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`) and `line["message"]["model"]`.
- Codex: `payload.info.tokens` and `payload.info.model`. Codex Desktop often omits tokens → all-zero summary with `confidence="unknown"` (file still written so the projection key exists).

### 4.4 Imported-run finalization pipeline

Per E2, current importers stop after writing `run.json` + `events.jsonl` + transcript copy. The new pipeline (added in `commands/import_common.py::finalize_imported_run`) executes the full capture-run shape:

```
[existing parse] → ParsedSession + ImportReport + UsageSummary
[existing write] → run.json + events.jsonl (with run.started FIRST, then command.started, parsed claude.*/codex.* events, command.finished)
[NEW]            → copy transcript to artifacts/transcripts/  (set report.transcript_artifact)
[NEW]            → write artifacts/import_report.json
[NEW]            → write artifacts/usage.json (always, even all-zero for Desktop)
[NEW]            → final.json  (agent_outcome="unknown" for analysis_state="full", "partial" otherwise)
[NEW]            → manifest.seal(pre_eval)
[NEW]            → evaluate() → eval.json  (NEVER fails on usage missing or import_state=partial)
[NEW]            → manifest.seal(final)
[NEW]            → sqlite_index.init_db(agentlens_home()) → index_run(conn, run_dir)  (best-effort; absorbed exceptions)
```

`finalize_imported_run` is the shared entry point — both importer commands call it.

**Idempotency (per E9):** the existing `input.import_key` scan in `commands/import_*_session.py::_existing_run_for_import_key` runs **before** any writes. Re-importing the same source is a no-op for the run record AND for the report/usage artifacts. A future `--refresh` flag is deferred.

### 4.5 Query / API / projection surface

Per E8, "additive projection" touches more than `store/query.py`. The full set:

| Layer | File | Change |
|-------|------|--------|
| Store query | `store/query.py` | `latest`/`full_scan_runs`/`list_runs`/`get_run` enrich each row by reading `artifacts/import_report.json` + `artifacts/usage.json`; emit `null` when absent. |
| SQLite cache | `store/sqlite_index.py` | Add nullable columns `display_title`, `usage_confidence`, `import_state`. Idempotent migration. Populated from artifacts during `index_run()`. SQLite rows are still rehydrated through the same artifact helper before projection; the DB columns are cache hints, not the source of the full `usage` object. |
| CLI projector | `commands/_format.py` | Three keys added to `project_run_row()` and `project_show()` (always present; default `None`). |
| Snapshot fixtures | `tests/fixtures/format_snapshots/*.json` | Regenerate with `AGENTLENS_UPDATE_SNAPSHOTS=1`. |
| Web API | `web/routers/runs.py` | `/api/v1/runs` and `/api/v1/runs/{id}` carry projector-derived fields only; never read artifacts directly from route handlers. |
| Frontend types | `web/src/types/api.ts` | Regenerated via `npm run gen-types`. |
| Frontend API client | `web/src/api/runs.ts` | Type-only additions. |
| Frontend UI | `web/src/components/run-list-table.tsx` | New cells per §4.6. |

### 4.6 Dashboard runs-list columns

Append five data points to the runs list:

| Column         | Source                          | Fallback |
|----------------|---------------------------------|----------|
| Title          | `display_title`                 | short `run_id` |
| Usage (in/out) | `usage.input_tokens` / `usage.output_tokens` | `—` |
| Cost           | `usage.cost_usd`                | `—` |
| Confidence     | `usage.confidence` badge        | `unknown` |
| Import state   | `import_state` badge; `partial`/`skipped` visually flagged | hidden if `null` |

All five come from `store.query` / projectors; web routes never read importer artifacts directly for list rendering.

## 5. Integration & Interaction

The two topics touch disjoint code surfaces with one minor overlap: both require running `pytest -q` and the test audit (Task 7 in Part A, Task 14/15 in Part B) operates on adjacent files. Execution order: **Part A finishes before Part B starts.** Rationale:

1. The install bug is an *active blocker* — new users installing AgentLens hit it. Importer hardening is an *improvement*. Crisis-first is the safer ordering.
2. Part A's new test fixtures and `wrapper_detect.py` module are completely standalone from Part B's `importers/` package.
3. The shim template change in Part A (new selftest branch) does not affect any importer behaviour.
4. Part B's new `finalize_imported_run` path does not invoke the install/shim/doctor surface.

No file is modified by both parts. The combined test audit in Part B Task 14 only touches importer/dashboard tests, leaving Part A's install/doctor tests intact.

## 6. Backward compatibility

| Surface | Compatibility |
|---------|--------------|
| `run.json` / `events.jsonl` / `final.json` / `eval.json` / `manifest.json` schemas | **Unchanged.** |
| `agentlens install` CLI | New optional flags: `--no-wrapper-detect` (escape hatch, requires `--yes`), `--skip-selftest`. Existing default behaviour is now stricter (wrapper paths refused), which IS a behaviour change. Documented in CLI help and `docs/cli.md`. |
| `agentlens import claude-session` / `import codex-session` CLI | New optional flags `--byte-cap`, `--deep-parse-only`. Default behaviour unchanged when flags absent. |
| `agentlens doctor --format json` | Additive: `wrapper_detected`, `remediation` keys when applicable; `shim_integrity` enum gains `wrapper_chain_warning`. Existing keys unchanged. |
| `agentlens show --format json` / `latest` / `status` | Three new keys appended (`display_title`, `usage`, `import_state`); `null` when absent. |
| Existing `.real` lockfiles | Untouched. If wrapper, Layer 5 surfaces it on next `doctor` call. |
| Existing imported runs on disk | No migration. `display_title=null`, `usage=null`, `import_state=null`. |
| SHIM_TEMPLATE | Adds a guarded selftest branch (no behaviour change without `AGENTLENS_INSTALL_SELFTEST=1` and exact `--version` argv). |
| SQLite index | Three nullable columns added; rebuild from JSON unchanged. |
| Re-importing a session | Still a no-op for run, report, and usage artifacts. |

## 7. Security & Privacy

- **Wrapper detection is a denylist defense.** Layer 4 selftest is the catch-all. Users who bypass with `--no-wrapper-detect` accept exec-loop risk.
- **No new persisted prompt content.** Title heuristic runs in-memory; only the redacted, capped title (≤120 chars) reaches disk.
- **Usage is non-sensitive by definition** (token counts, model names). No new redaction.
- **Import report does not persist raw absolute source paths.** `source_path` is a redacted label and `source_path_hash` preserves provenance identity without leaking `$HOME` layout. This is required because `import_report.json` is deliberately not written through `store.writer.atomic_write_json()`.
- **Imported transcripts are NOT newly redacted** (per E10). `shutil.copyfile()` copies vendor JSONL bytes. Patch `docs/security.md` to state this honestly.
- **Reserved env var `AGENTLENS_INSTALL_SELFTEST`** is documented as reserved; the shim only honours it when argv is exactly `--version` so normal invocation cannot be hijacked.

## 8. Test plan (combined)

### 8.1 Unit tests

**Install safety:**
- `test_install_wrapper_detect.py`: per-signature category match; binary-no-shebang passes; 16 KiB cap; empty file; coincidental byte sequence below shebang.
- `test_install_self_reference.py`: `real == shim_dir/<agent>`; symlink into shim_dir.
- `test_install_path_conflict_warning.py`: wrapper-vs-binary current resolution → warn; same path → no warn; binary-vs-binary → no warn.

**Importer hardening:**
- `test_importers_title.py`: each strip rule; UTF-8 cap; U+2026 suffix; punctuation-only → `None`; deterministic fuzz with `random.Random(0)`.
- `test_importers_usage.py`: exact / estimated / unknown branches; multi-model breakdown; Codex Desktop no-tokens.
- `test_importers_report.py`: counter aggregation; state derivation; `byte_cap_hit`; atomic artifact write.
- `test_claude_session_parser.py` / `test_codex_session_parser.py`: tuple return; malformed/oversized/byte-cap cases; first_user_message capture; usage_records capture.

### 8.2 Integration tests

**Install safety:**
- `test_install_cmux_detection.py`: cmux fixture refused; `--no-wrapper-detect --yes` succeeds with stderr warning; `--no-wrapper-detect` without `--yes` errors.
- `test_install_selftest_probe.py`: benign executable fixture passes; `loop-trap.sh` triggers rollback (no shim, no lockfile on disk). Binary marker files remain scanner-only fixtures.
- `test_doctor_wrapper_warning.py`: hand-written wrapper lockfile → `shim_integrity=wrapper_chain_warning` + correct remediation string.

**Importer hardening:**
- `test_import_claude_session_report.py`: malformed line → `partial`, manifest covers transcript+report+usage, eval exists, `run.started` first event.
- `test_import_codex_session_report.py`: CLI exact / Desktop unknown; parent backfill regression.
- `test_import_byte_cap.py`: default → `partial`; `--deep-parse-only` → `skipped`.
- `test_query_projection_usage_title.py`: imported runs have all three keys; container run from `kws-cme` has all three as `null` (no regression).
- `test_format_json_snapshot.py`: snapshot drift covered.
- `test_web_e2e_runs_list.py` / `test_web_e2e_run_detail.py`: API payload contains projector-derived fields; does not expose `source_path`.

### 8.3 Fixtures

`tests/fixtures/install_wrapper_safety/`:
- `cmux-launcher.sh` (signature fixture)
- `self-shim.sh` (signature fixture)
- `path-lookup.sh` (signature fixture)
- `safe-binary.bin` (no shebang, treated as binary)
- `loop-trap.sh` (recursive exec for selftest)

`tests/fixtures/sessions/`:
- `claude-with-usage.jsonl`, `claude-mixed-usage.jsonl`, `claude-malformed-line.jsonl`
- `codex-cli-with-usage.jsonl`, `codex-desktop-no-usage.jsonl`, `codex-oversized-line.jsonl`

`tests/fixtures/titles/` (paired `<name>.input.txt` / `<name>.expected.txt`):
- ≥8 pairs covering every strip rule + 2 real Claude/Codex samples.

## 9. Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Layer 1 signature scan false-positives a legitimate user wrapper | User can't install without `--no-wrapper-detect` | Refusal message includes the matched signature so the user verifies; escape hatch is one flag away. |
| Layer 1 false-negatives a novel wrapper | Loop reaches Layer 4 selftest | Selftest catches; not dependent on signatures. |
| Layer 4 selftest itself hangs on slow systems | Install feels slow | 5s timeout; runs once per install; `--skip-selftest` available. |
| `AGENTLENS_INSTALL_SELFTEST` env leaks into a real invocation | Shim degrades to printing diagnostic | Shim only honours the var when argv is exactly `--version`; documented as reserved. |
| `--no-wrapper-detect` becomes a footgun | User re-creates the loop | Requires `--yes`; emits loud stderr warning each use; documented in CLI help. |
| Doctor wrapper-warning state breaks an existing JSON consumer | Field reader crashes on unknown enum | Survey current consumers (`web/`, `commands/doctor.py` text formatter); enum extension only. |
| Title heuristic leaks sensitive content via projection | Privacy regression | All strip rules run in-memory before disk; unit tests assert known-sensitive patterns never appear in output. |
| Usage `confidence=exact` when source was partially fabricated | Misleading reporting | `events_missing_usage` in diagnostics; any non-zero forces ≥ `estimated`. |
| Projection drift: dashboard expects keys importer omits | Render error | Projection layer always emits all three keys (with `null`) regardless of artifact presence. |
| Re-importing overwrites a `full` report with `partial` after a regression | Forensics confusion | NOT allowed by design (E9 — re-import is no-op). |
| Pricing patch arrives and changes `cost_usd` semantics | Future contract churn | Shape reserved (`cost_usd: null`, `pricing_source: "unknown"`); patch changes value, not key. |
| Test audit (Task 14) misses an install-shim test using script fixture | CI break post-merge | Grep for all uses of `install_shim` + `agentlens install` in tests, switch fixtures or add `allow_wrapper=True` explicitly. |

## 10. Migration story

Users with broken installs from before this work see the warning on next `agentlens doctor` run. The `remediation` field gives them the exact command. No automatic migration. If repair friction becomes a real complaint after this lands, a follow-up spec can add `agentlens install --repair <agent>` as an explicit opt-in convenience — out of scope here.

Imported runs from before this work have no `import_report.json` / `usage.json` and surface `display_title=null` / `usage=null` / `import_state=null` in projections. Re-importing is a no-op (E9). A future `--refresh` flag is deferred.

## 11. Open questions

1. **Should Layer 4 selftest be opt-out by default?** v1 design: keep on by default; add `--skip-selftest` opt-in if user complaints arise.
2. **Should the title `max_chars` be a CLI flag?** Default 120 feels right for a runs-list cell; hardcode for v1.x and revisit when the dashboard ships.
3. **Codex Desktop reasoning tokens — recoverable?** Initial reading suggests no. v1.x emits `reasoning_tokens=0` with `confidence="unknown"` for those runs and revisits in a follow-up.
4. **Pricing follow-up scope.** Bundled YAML in AgentLens vs separate plugin — decided in a later spec; this design only reserves the shape.

## 12. References

- ADR: `docs/adr/2026-05-19-agentlens-ecosystem-benchmark.md`
- v1 unification plan: `docs/plan/2026-05-19-agentlens-v1-and-kws-unification.md`
- Dashboard spec: `docs/spec/2026-05-19-agentlens-dashboard-design.md`
- Auto-record design: `docs/spec/2026-05-19-agentlens-skill-auto-record-design.md`
- Contract: `docs/contract.md`
- Security: `docs/security.md`
- Subject sources: `src/agentlens/commands/install.py`, `src/agentlens/adapters/shims.py`, `src/agentlens/commands/doctor.py`, `src/agentlens/commands/import_*_session.py`, `src/agentlens/store/{claude,codex}_session.py`
- Bug-introducing commit: `7c8df6f` (`.app` refusal that this work generalizes)
