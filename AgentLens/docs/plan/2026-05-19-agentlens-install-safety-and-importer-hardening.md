# AgentLens v1.x — Install Safety + Importer Hardening (Combined) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `kws-claude-multi-agent-executor` (Opus orchestrator + Sonnet implementers) to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Risk default: **mid**.
>
> **Execution mode recommendation:** single-plan, mid-risk, parallel=on. Tasks within a phase are mostly file-disjoint; phases are sequenced (Part A finishes before Part B starts — see §Phase ordering).

**Goal:** Close two distinct gaps in AgentLens v1 in a single sequenced effort:
1. **Part A — Install safety:** Refuse exec-loop-prone shim installs, catch novel cases with a post-install selftest, surface existing broken installs via `doctor`.
2. **Part B — Importer hardening + usage:** Make imported sessions bounded (byte cap), sealed (full finalization pipeline), usage-aware, title-aware, and visible in CLI/API/dashboard projections.

**Companion design spec:** `AgentLens/docs/spec/2026-05-19-agentlens-install-safety-and-importer-hardening.md` (read first — its §0 source-review corrections are binding).

**Tech stack:** Python 3.12, Typer, JSON Schema, pytest, FastAPI, React/Vite/TypeScript, existing `src/agentlens/` and `web/` trees.

**Total scope:** 20 tasks across 8 phases. Estimated single-implementer time: ~24h. Wall-clock with Sonnet implementers in parallel: ~8-10h.

---

## Phase ordering

```
Part A (install safety)              Part B (importer hardening)
─────────────────────────            ───────────────────────────────────
Phase 1: pure detection              Phase 5: pure helpers   ─┐
   ├─ Task 1                            ├─ Task 11           │
   └─ Task 2                            ├─ Task 12           │
Phase 2: install integration            └─ Task 13           │
   ├─ Task 3                         Phase 6: parser integration
   ├─ Task 4                            ├─ Task 14           │
   └─ Task 5                            └─ Task 15           │
Phase 3: advisory + diagnostics      Phase 7: commands + projections
   ├─ Task 6                            ├─ Task 16           │
   ├─ Task 7                            ├─ Task 17           │
   └─ Task 8                            └─ Task 18           │
Phase 4: docs + smoke (A)            Phase 8: dashboard + close-out
   ├─ Task 9                            ├─ Task 19           │
   └─ Task 10  ────────────────────→    └─ Task 20           │
                                                              ┘
```

**Hard constraint:** Task 10 (Part A smoke + sign-off) must complete green BEFORE Task 11 starts. Once Part A is sealed, Part B has no upstream dependency on it.

**Parallelism within each phase:**

| Phase | Parallelism |
|-------|-------------|
| 1 | Task 1 ∥ Task 2 |
| 2 | Task 3 → Task 4 → Task 5 (serial — Task 5 depends on Task 4's template change) |
| 3 | Task 6 ∥ Task 7 ∥ Task 8 |
| 4 | Task 9 → Task 10 (serial) |
| 5 | Task 11 ∥ Task 12 ∥ Task 13 |
| 6 | Task 14 ∥ Task 15 |
| 7 | Task 16 → Task 17 → Task 18 (serial — Task 18 query layer touches both importers' output) |
| 8 | Task 19 → Task 20 (serial) |

---

## Engineering Review Findings (consolidated)

### Install safety (W*)

| ID | Severity | Finding | Plan correction |
|----|----------|---------|-----------------|
| W1 | Blocker | `.app` refusal at `adapters/shims.py:177-181` landed at commit `7c8df6f` (2026-05-19 09:26). Installs before that timestamp baked unsafe lockfiles; no later code or `doctor` detects them. | Task 8 surfaces existing broken installs via doctor + remediation string. |
| W2 | Blocker | `commands/install.py:84` calls `shutil.which(agent)` and accepts the result unconditionally. | Tasks 1-3 add signature detection (Layer 1), self-reference check (Layer 2), and PATH-conflict warning (Layer 3). |
| W3 | High | Novel wrapper shapes can slip past signature detection. | Task 5 adds post-install selftest probe (Layer 4) that runs the shim once with a reserved env var. |
| W4 | High | `SHIM_TEMPLATE` invariant to the selftest probe. | Task 4 adds inert selftest branch; only entered when `AGENTLENS_INSTALL_SELFTEST=1` AND argv exactly `--version`. |
| W5 | High | Existing tests use shell-script fixtures for `install_shim`. | Task 7 audits, swaps to Mach-O markers or adds explicit `allow_wrapper=True`. |
| W6 | Medium | Layer 3 warning is non-blocking; tests must check stderr, not stdout. | Task 6 includes a regression assertion. |
| W7 | Medium | New `shim_integrity` enum value `wrapper_chain_warning` may break strict JSON consumers. | Task 8 surveys consumers (`web/`, text formatter, `scripts/`). |
| W8 | Medium | `--no-wrapper-detect` is a footgun. | Task 3 pairs it with `--yes` (cannot be used in interactive mode without explicit consent) and prints a loud stderr line. |
| W9 | Low | `--repair` mode considered but deferred. | Documented in spec §10 as deferred. |

### Importer hardening (E*)

| ID | Severity | Finding | Plan correction |
|----|----------|---------|-----------------|
| E1 | Blocker | Locked v1 schemas have `additionalProperties:false`. | Zero schema diffs. New data → `artifacts/import_report.json`, `artifacts/usage.json`, projection keys, nullable SQLite columns. |
| E2 | Blocker | Current importers don't write `final.json`/`eval.json`/`manifest.json`/index rows. | Task 16 adds `commands/import_common.py::finalize_imported_run()`. |
| E3 | Blocker | Evaluator requires first event `run.started`; current importers start with `command.started`. | Tasks 16-17 prepend `run.started`, then keep existing markers. |
| E4 | High | `_iter_jsonl()` reads entire file with `path.read_text()`. | Tasks 14-15 replace with binary streaming iteration that counts byte offsets/line sizes before decoding. |
| E5 | High | `ParsedSession`/`ParsedCodexSession` don't expose first user message or usage records. | Tasks 14-15 extend dataclasses with `first_user_message_text` and `usage_records`. |
| E6 | High | Title needs a source of truth; normalized events don't include user messages. | Task 11 stores redacted derived title under `import_report.derived.display_title`; Task 18 projects from there. |
| E7 | High | `store.writer.atomic_write_json()` requires `schema` field; `import_report.json`/`usage.json` are not schema documents. | Task 13 adds `importers/artifacts.py::write_artifact_json()`. |
| E8 | High | Projection touches projectors, snapshots, generated TS types, AND `/api/v1/runs`. | Task 18 owns all of them in one task. |
| E9 | Medium | Re-import is a true no-op via `input.import_key`. Overwriting report/usage would break it. | Preserve no-op idempotency. `--refresh` deferred. |
| E10 | Medium | `shutil.copyfile()` transcript copy bypasses redaction. | Don't claim transcript redaction. Patch `docs/security.md` honestly. |
| E11 | Medium | Counting normal vendor lines as unsupported marks sessions partial. | Use a per-vendor allowlist; count `skipped_unsupported_type` only for unclassifiable lines. |
| E12 | Medium | `hypothesis` not in test deps. | Use deterministic fuzz with `random.Random(0)` in title tests. |

---

## File Structure

### Create

**Install safety:**

| Path | Responsibility |
|------|----------------|
| `AgentLens/src/agentlens/adapters/wrapper_detect.py` | Pure signature-detection helpers (Layer 1). |
| `AgentLens/tests/unit/test_install_wrapper_detect.py` | Detection unit tests. |
| `AgentLens/tests/unit/test_install_self_reference.py` | Self-reference guard tests. |
| `AgentLens/tests/unit/test_install_path_conflict_warning.py` | PATH-conflict warning tests. |
| `AgentLens/tests/integration/test_install_cmux_detection.py` | End-to-end refusal + escape-hatch tests. |
| `AgentLens/tests/integration/test_install_selftest_probe.py` | Selftest rollback tests. |
| `AgentLens/tests/integration/test_doctor_wrapper_warning.py` | Doctor wrapper-chain warning tests. |
| `AgentLens/tests/fixtures/install_wrapper_safety/cmux-launcher.sh` | Cmux signature fixture. |
| `AgentLens/tests/fixtures/install_wrapper_safety/self-shim.sh` | Self-reference signature fixture. |
| `AgentLens/tests/fixtures/install_wrapper_safety/path-lookup.sh` | Generic-PATH-lookup signature fixture. |
| `AgentLens/tests/fixtures/install_wrapper_safety/safe-binary.bin` | Mach-O-shaped marker (no shebang). |
| `AgentLens/tests/fixtures/install_wrapper_safety/loop-trap.sh` | Pathological recursive script for selftest. |

**Importer hardening:**

| Path | Responsibility |
|------|----------------|
| `AgentLens/src/agentlens/importers/__init__.py` | Package marker. |
| `AgentLens/src/agentlens/importers/title.py` | `extract_display_title()` pure heuristic. |
| `AgentLens/src/agentlens/importers/usage.py` | `UsageSummary` + vendor extractors + confidence rules. |
| `AgentLens/src/agentlens/importers/report.py` | `ImportReport` + counters + state derivation. |
| `AgentLens/src/agentlens/importers/artifacts.py` | Atomic non-schema artifact JSON writer. |
| `AgentLens/src/agentlens/commands/import_common.py` | Byte-cap validation + `finalize_imported_run()`. |
| `AgentLens/tests/unit/test_importers_title.py` | Title heuristic tests. |
| `AgentLens/tests/unit/test_importers_usage.py` | Usage extractor tests. |
| `AgentLens/tests/unit/test_importers_report.py` | Report counter/state/artifact-writer tests. |
| `AgentLens/tests/integration/test_import_claude_session_report.py` | Claude e2e: report/usage/manifest/projection. |
| `AgentLens/tests/integration/test_import_codex_session_report.py` | Codex e2e: report/usage/manifest/projection. |
| `AgentLens/tests/integration/test_import_byte_cap.py` | Partial vs skipped byte-cap behaviour. |
| `AgentLens/tests/integration/test_query_projection_usage_title.py` | CLI/API projection shape. |
| `AgentLens/tests/fixtures/sessions/claude-with-usage.jsonl` | Full-tokens Claude fixture. |
| `AgentLens/tests/fixtures/sessions/claude-mixed-usage.jsonl` | Partial-tokens Claude fixture. |
| `AgentLens/tests/fixtures/sessions/claude-malformed-line.jsonl` | One bad JSON line. |
| `AgentLens/tests/fixtures/sessions/codex-cli-with-usage.jsonl` | Codex CLI with tokens. |
| `AgentLens/tests/fixtures/sessions/codex-desktop-no-usage.jsonl` | Codex Desktop without tokens. |
| `AgentLens/tests/fixtures/sessions/codex-oversized-line.jsonl` | One row > 2 MiB. |
| `AgentLens/tests/fixtures/titles/*.input.txt` / `*.expected.txt` | Paired title-heuristic fixtures (≥8). |

### Modify

**Install safety:**

| Path | Change |
|------|--------|
| `AgentLens/src/agentlens/adapters/shims.py` | `install_shim`: call `wrapper_detect.scan_real_candidate`; self-reference check; selftest probe + rollback. Update `SHIM_TEMPLATE` + `CMUX_SHIM_TEMPLATE` with selftest branch. Add `wrapper_chain_warning` to `verify_shim_integrity` return type. |
| `AgentLens/src/agentlens/commands/install.py` | Add `--no-wrapper-detect` (requires `--yes`) and `--skip-selftest` flags. PATH-conflict warning before rc-hint. Wire flags to `install_shim`. |
| `AgentLens/src/agentlens/commands/doctor.py` | Layer 5: scan each lockfile target; surface `wrapper_chain_warning`, `wrapper_detected`, `remediation` in JSON; print remediation line in text mode. |
| `AgentLens/tests/unit/test_install_shim.py` (existing) | Convert script fixtures to Mach-O marker or add `allow_wrapper=True`. |
| `AgentLens/tests/integration/test_doctor.py` (existing, if present) | Add wrapper-chain branch coverage. |
| `AgentLens/docs/cli.md` | Document `--no-wrapper-detect`, `--skip-selftest`, doctor's new fields. |
| `AgentLens/docs/security.md` | One paragraph on wrapper detection (denylist) + selftest (catch-all). |

**Importer hardening:**

| Path | Change |
|------|--------|
| `AgentLens/src/agentlens/store/claude_session.py` | Stream parser; byte/line caps; counters; first-user extraction; usage records; `(ParsedSession, ImportReport)` return. |
| `AgentLens/src/agentlens/store/codex_session.py` | Same for Codex rollouts. |
| `AgentLens/src/agentlens/commands/import_claude_session.py` | Byte-cap flags; `run.started` first event; report/usage artifacts; `finalize_imported_run()` call. |
| `AgentLens/src/agentlens/commands/import_codex_session.py` | Same for Codex; preserve parent-link backfill. |
| `AgentLens/src/agentlens/store/query.py` | Enrich rows with `display_title`/`usage`/`import_state` from artifacts. |
| `AgentLens/src/agentlens/store/sqlite_index.py` | Add `display_title`/`usage_confidence`/`import_state` nullable columns + migration. |
| `AgentLens/src/agentlens/commands/_format.py` | Three additive keys in `project_run_row()` and `project_show()`. |
| `AgentLens/src/agentlens/web/routers/runs.py` | `/api/v1/runs` and `/api/v1/runs/{id}` carry projector-derived fields only. |
| `AgentLens/web/src/api/runs.ts` | Typed `display_title`/`usage`/`import_state` fields. |
| `AgentLens/web/src/components/run-list-table.tsx` | Title/usage/cost/confidence/import-state cells. |
| `AgentLens/web/src/components/run-list-table.test.tsx` | Cover new cells + null rendering. |
| `AgentLens/web/src/types/api.ts` | Regenerated from snapshots. |
| `AgentLens/tests/fixtures/format_snapshots/*.json` | Additive projection keys. |
| `AgentLens/docs/cli.md` | Document import flags and additive JSON fields. |
| `AgentLens/docs/security.md` | Correct imported-transcript privacy wording + new artifacts. |
| `AgentLens/docs/contract.md` | Changelog note: artifacts + projection keys; no schema changes. |
| `AgentLens/docs/spec/2026-05-19-agentlens-dashboard-design.md` | Run-list signature screen: five new data points sourced from projection only. |

### Delete

None.

---

# Part A — Install Wrapper Safety

## Phase 1 — Pure detection modules (parallel)

### Task 1: Wrapper-signature scanner

**Files:** `adapters/wrapper_detect.py`, `tests/unit/test_install_wrapper_detect.py`, fixtures under `tests/fixtures/install_wrapper_safety/`

- [ ] Create `wrapper_detect.py` exporting `WrapperCategory` (Literal `"agentlens_self"|"cmux"|"path_lookup"`), `WrapperDetection` (NamedTuple: `category`, `matched_pattern: bytes | None`, `remediation: str`), and `scan_real_candidate(path: Path) -> WrapperDetection`.
- [ ] Read first 16 KiB. If head does NOT start with `b"#!"` → return `WrapperDetection(None, None, "")`. Otherwise scan with patterns in spec §3.1 order (first-match wins).
- [ ] Build per-category remediation strings: each begins with `agentlens install` and includes a `--real` or `--cmux` flag.
- [ ] Create fixtures: `cmux-launcher.sh` (shebang + `find_real_claude() { … }` + `HOOKS_JSON=` line); `self-shim.sh` (shebang + `exec "$INSTALLED_AGENTLENS_BIN" run --agent claude_code -- "$@"`); `path-lookup.sh` (shebang + `exec "$(command -v claude)" "$@"`); `safe-binary.bin` (256 bytes of `\x00`); `loop-trap.sh` (shebang + `exec "$0" "$@" extra`).
- [ ] Write failing tests for each fixture; assert correct category, matched pattern, remediation prefix.
- [ ] Edge cases: empty file → `category=None`; 32 KiB file with signature past 16 KiB cap → `category=None` (deliberate); binary-with-coincidental-byte-sequence (no shebang) → `category=None`.
- [ ] Run `pytest tests/unit/test_install_wrapper_detect.py -q`.

### Task 2: Self-reference guard

**Files:** `adapters/shims.py::install_shim`, `tests/unit/test_install_self_reference.py`

- [ ] In `install_shim`, after `real = Path(real_path).resolve(strict=True)` and BEFORE the existing `.app` check, add:
  ```python
  if real.parent.resolve() == _shim_dir().resolve():
      raise ValueError(
          f"refusing to bake {real} as .real — it is itself in the "
          f"AgentLens shim directory. Pass --real <ultimate binary>."
      )
  ```
- [ ] Tests: `real == shim_dir/"claude"` → raises; `real == shim_dir/"codex"` → raises (different agent, same dir); `real` in tmpdir → does not raise; symlink into shim_dir → raises (via `.resolve()`).
- [ ] Run `pytest tests/unit/test_install_self_reference.py -q`.

## Phase 2 — Install integration (serial)

### Task 3: Plug detection + flag wiring

**Files:** `adapters/shims.py::install_shim`, `commands/install.py`, `tests/integration/test_install_cmux_detection.py`

- [ ] Extend `install_shim` signature: `def install_shim(name: str, real_path: Path, *, allow_wrapper: bool = False) -> None`.
- [ ] After self-reference + `.app` checks, if `not allow_wrapper`: call `wrapper_detect.scan_real_candidate(real)`. On non-`None` category → raise `ValueError` with category, matched pattern, and remediation.
- [ ] In `commands/install.py`: add `--no-wrapper-detect` Typer option. Add Typer callback that requires `--yes` when `--no-wrapper-detect` is true → otherwise `typer.BadParameter`. When both set, emit loud stderr warning before install.
- [ ] Pass `allow_wrapper=no_wrapper_detect` into `install_shim`.
- [ ] Integration tests:
  - Fake cmux launcher tmpdir → `agentlens install fake-agent --real <that> --yes` → exit ≠ 0, stderr contains `"cmux"`, no shim or lockfile.
  - Same + `--no-wrapper-detect --yes` → exit 0, stderr contains "wrapper detection bypassed", lockfile present.
  - `--no-wrapper-detect` without `--yes` → Typer error before I/O.
- [ ] Run `pytest tests/integration/test_install_cmux_detection.py -q`.

### Task 4: SHIM_TEMPLATE selftest branch

**Files:** `adapters/shims.py::SHIM_TEMPLATE`, `adapters/shims.py::CMUX_SHIM_TEMPLATE`, `tests/unit/test_shim_template.py` (existing or new)

- [ ] In `SHIM_TEMPLATE`, insert selftest branch immediately after the `set -euo pipefail` line and the existing CLI baked variable, BEFORE the lockfile check:
  ```bash
  # AgentLens install self-test (reserved env var). Only honoured when the
  # first positional arg is --version; everything else falls through to the
  # normal exec path so a real invocation cannot be hijacked.
  if [ "${AGENTLENS_INSTALL_SELFTEST:-}" = "1" ] && [ "${1:-}" = "--version" ]; then
    printf 'shim_path=%s\n' "$0"
    printf 'real_path=%s\n' "$REAL_PATH"
    printf 'real_kind=%s\n' "$(file -b "$REAL_PATH" 2>/dev/null | awk -F, '{print $1}')"
    printf 'chain_depth=%s\n' "${AGENTLENS_INSTALL_SELFTEST_DEPTH:-1}"
    exit 0
  fi
  ```
  Verify `REAL_PATH` is set before this block (it currently is via `REAL_PATH="$(awk -F= …)"` reading the lockfile — confirm ordering).
- [ ] Mirror into `CMUX_SHIM_TEMPLATE` for defensive parity.
- [ ] Unit test: render template with sample format args; assert selftest line is present.
- [ ] Run `pytest tests/unit/test_shim_template.py -q`.

### Task 5: Post-install selftest probe + rollback

**Files:** `adapters/shims.py::install_shim`, `tests/integration/test_install_selftest_probe.py`, `commands/install.py`

- [ ] At top of `install_shim` (before any writes), snapshot the prior shim and lockfile if they exist (read bytes into temp memory).
- [ ] At end of `install_shim`, BEFORE returning, run the selftest:
  ```python
  result = subprocess.run(
      [str(shim), "--version"],
      timeout=5,
      capture_output=True,
      env={**os.environ, "AGENTLENS_INSTALL_SELFTEST": "1"},
      check=False,
  )
  ```
- [ ] Parse `result.stdout` into a `dict[str, str]` of `key=value` lines. Validate: exit code 0; `chain_depth == "1"`; `shim_path` equals the installed shim path.
- [ ] On any failure (timeout/non-zero/malformed/depth-mismatch): delete `shim`+`lockfile`; restore snapshots if present; raise `RuntimeError` with captured stderr.
- [ ] Add `--skip-selftest` Typer option in `commands/install.py`. When set, pass `skip_selftest=True` into `install_shim` and document loud stderr.
- [ ] Integration tests: with `safe-binary.bin` (a real Mach-O surrogate or pass `allow_wrapper=True` and use a benign shell script that just `echo`s) → install succeeds and selftest output captured for inspection. With `loop-trap.sh` (after `allow_wrapper=True` bypass to reach the selftest) → install fails, no shim, no lockfile.
- [ ] Run `pytest tests/integration/test_install_selftest_probe.py -q`.

## Phase 3 — Advisory + diagnostics (parallel)

### Task 6: PATH-conflict warning

**Files:** `commands/install.py`, `tests/unit/test_install_path_conflict_warning.py`

- [ ] In `commands/install.py` after `install_shim()` returns, BEFORE the "Add to your shell rc" hint:
  ```python
  current = shutil.which(agent)
  if current and Path(current).resolve() != Path(real_path).resolve():
      with open(current, "rb") as fh:
          head = fh.read(2)
      if head == b"#!":
          typer.echo(WARNING_TEXT, err=True)
  ```
- [ ] Construct `WARNING_TEXT` per spec §3.3 with the two paths substituted.
- [ ] Unit tests:
  - Mock `shutil.which("claude")` returning a wrapper script path different from `real_path` → warning to stderr.
  - Same path → no warning.
  - Mach-O current → no warning.
  - `None` current → no warning.
- [ ] Run `pytest tests/unit/test_install_path_conflict_warning.py -q`.

### Task 7: Existing-test audit

**Files:** `tests/unit/test_install_shim.py` (existing), `tests/integration/test_install.py` (if present), `tests/integration/test_shim_tty_passthrough.py`, `tests/integration/test_cmux_chain.py`

- [ ] grep across all `tests/` for: `install_shim(`, `agentlens install`, and `.real` file writes.
- [ ] For each test creating a shim from a shell-script fixture: either swap to a Mach-O marker (binary header), OR add `allow_wrapper=True` (or pass `--no-wrapper-detect --yes` for CLI tests) with a one-line comment explaining why.
- [ ] Run `pytest tests/unit/ tests/integration/ -q` and confirm pre-existing tests pass after the audit.

### Task 8: Doctor wrapper-chain warning

**Files:** `commands/doctor.py`, `adapters/shims.py::verify_shim_integrity`, `tests/integration/test_doctor_wrapper_warning.py`, `docs/cli.md`

- [ ] Extend `verify_shim_integrity` return type to `Literal["ok", "drift_warning", "missing", "wrapper_chain_warning"]`.
- [ ] After sha256 drift check passes (i.e., would have returned `"ok"`): read `.real` target; run `wrapper_detect.scan_real_candidate(target)`. If category non-`None` → return `"wrapper_chain_warning"`.
- [ ] In `commands/doctor.py::_integrations_block`, when `integrity == "wrapper_chain_warning"`:
  ```python
  # Need to re-scan to get the category/remediation
  lockfile = _shim_dir() / f"{name}.real"
  target = Path(_parse_lockfile(lockfile)["path"])
  detection = wrapper_detect.scan_real_candidate(target)
  out[name] = {
      "integration_level": "shim",
      "shim_integrity": "wrapper_chain_warning",
      "wrapper_detected": detection.category,
      "remediation": detection.remediation,
  }
  ```
- [ ] In `_format_text_integrations`: when `shim_integrity == "wrapper_chain_warning"`, append a second indented line `wrapper_detected=<category> — fix: <remediation>`.
- [ ] Integration test: write a `.real` lockfile pointing at the `cmux-launcher.sh` fixture; matching sha256; run `agentlens doctor --format json`; assert all three fields present.
- [ ] Patch `docs/cli.md`: new `shim_integrity` value + two new keys.
- [ ] Run `pytest tests/integration/test_doctor_wrapper_warning.py -q`.

## Phase 4 — Docs + Part A close-out (serial)

### Task 9: Install-safety docs

**Files:** `docs/cli.md`, `docs/security.md`

- [ ] `docs/cli.md`: document `agentlens install --no-wrapper-detect` (with "NOT RECOMMENDED"), `--skip-selftest`, doctor's `shim_integrity=wrapper_chain_warning`, `wrapper_detected`, `remediation` fields.
- [ ] `docs/security.md`: add one paragraph under install section: wrapper detection is a denylist; selftest is the catch-all; bypass acknowledges exec-loop risk.

### Task 10: Part A smoke + sign-off (GATE)

**Files:** none new

- [ ] Run focused tests: `pytest tests/unit/test_install_wrapper_detect.py tests/unit/test_install_self_reference.py tests/unit/test_install_path_conflict_warning.py tests/unit/test_shim_template.py tests/integration/test_install_cmux_detection.py tests/integration/test_install_selftest_probe.py tests/integration/test_doctor_wrapper_warning.py -q`. All green.
- [ ] Run full Python suite: `pytest -q`. All green.
- [ ] Manual sanity (on a clean tmpdir):
  - `agentlens install claude --real /opt/homebrew/bin/claude --yes` → succeeds, selftest passes, doctor reports `ok`.
  - Hand-edit `.real` lockfile to point at the cmux fixture; run `agentlens doctor` → reports `wrapper_chain_warning` with remediation.
  - Run printed remediation → doctor reports `ok` again.
- [ ] **GATE: Part A must be green before Part B (Task 11) starts.**

---

# Part B — Importer Hardening + Usage

## Phase 5 — Pure helpers (parallel)

### Task 11: `importers.title.extract_display_title`

**Files:** `importers/__init__.py`, `importers/title.py`, `tests/unit/test_importers_title.py`, `tests/fixtures/titles/`

- [ ] Create `importers/__init__.py` (empty package marker).
- [ ] Write failing tests for: `None`/empty/whitespace; fenced code block; inline code; `<<…>>` sentinels; `<AGENTS>`/`<system-reminder>` blocks; lines starting `AGENTS:`/`Environment:`/`Working directory:`; absolute paths → `<path>`; control chars; URLs (preserved up to 64 chars); UTF-8 cap counts code points; 120-char U+2026 truncation; punctuation-only → `None`; Korean/Japanese/emoji passthrough; deterministic over rerun.
- [ ] Create ≥8 paired fixtures under `tests/fixtures/titles/`: one per strip rule + 2 real-session samples (one Claude, one Codex).
- [ ] Add deterministic fuzz: `random.Random(0)` generating 1 KB random bytes, decode with `errors="replace"`, feed to extractor → never raises, returns `str | None`.
- [ ] Implement per spec §4.2. Pure (no FS, no network, no module deps beyond stdlib `re`).
- [ ] Run `pytest tests/unit/test_importers_title.py -q`.

### Task 12: `importers.usage.extract_usage`

**Files:** `importers/usage.py`, `tests/unit/test_importers_usage.py`, fixtures `claude-with-usage.jsonl`/`claude-mixed-usage.jsonl`/`codex-cli-with-usage.jsonl`/`codex-desktop-no-usage.jsonl`

- [ ] Define `UsageSummary` and `ModelUsage` dataclasses matching spec §4.3 (`cost_usd=None`, `pricing_source="unknown"` defaults).
- [ ] Input type: `usage_records: list[dict[str, Any]]` (raw vendor-line dicts, captured by parsers — NOT normalized events).
- [ ] Write failing tests: Claude exact (10 events, all tokens); Claude estimated (3 missing cache fields); Codex CLI exact; Codex Desktop unknown (no token fields anywhere); missing model field; multi-model aggregation.
- [ ] Implement `extract_usage(source: Literal["claude-session","codex-rollout"], usage_records: list[dict]) -> UsageSummary`. Confidence rules per spec §4.3 table.
- [ ] Empty `usage_records` → all-zero summary with `confidence="unknown"`, `diagnostics.events_with_usage=0`.
- [ ] Run `pytest tests/unit/test_importers_usage.py -q`.

### Task 13: `ImportReport` + artifact writer

**Files:** `importers/report.py`, `importers/artifacts.py`, `tests/unit/test_importers_report.py`

- [ ] Define `ImportReport` dataclass with: counters (`total_scanned`, `parsed`, `skipped_malformed`, `skipped_unsupported_type`, `skipped_oversized`), `first_error`, `transcript_artifact`, `derived.display_title`, `byte_cap_bytes`, `byte_cap_hit`, `byte_cap_source`, `source_bytes`, `duration_ms`, `source` (literal), `source_path`, `source_session_id`.
- [ ] Methods: `record_parsed()`, `record_skip(reason, line_number, byte_offset)` (first-error captured only on first call), `record_byte_cap_hit()`, `set_transcript_artifact(path, bytes)`, `set_display_title(title, source)`, `finalize(duration_ms)`, `analysis_state` property (computed from counters + byte_cap_hit + deep_parse_only_skipped flag), `to_dict()`.
- [ ] Implement `importers/artifacts.py::write_artifact_json(path: Path, data: dict)`: temp file in same dir → `fsync` → `os.replace` (atomic). Deterministic `json.dumps(data, sort_keys=True, indent=2)`. No schema validation.
- [ ] Tests: counter aggregation (100 parsed + 3 malformed + 1 oversized → totals); state derivation (`full`/`partial`/`skipped`); `byte_cap_hit=True` → `partial`; deep-parse-only flag → `skipped`; first-error preservation (later errors don't overwrite); atomic write (interrupted write leaves no partial file at target path).
- [ ] Run `pytest tests/unit/test_importers_report.py -q`.

## Phase 6 — Parser integration (parallel across vendors)

### Task 14: Claude parser — streaming + report plumbing

**Files:** `store/claude_session.py`, `tests/unit/test_claude_session_parser.py`, fixture `claude-malformed-line.jsonl`

- [ ] Extend `ParsedSession` with `first_user_message_text: str | None` and `usage_records: list[dict[str, Any]]`.
- [ ] Change signature: `parse_session(path: Path, *, byte_cap: int = 64 * 1024 * 1024, deep_parse_only: bool = False) -> tuple[ParsedSession, ImportReport]`.
- [ ] Replace `_iter_jsonl()` with a binary streaming iterator that opens the file in `"rb"` mode and yields `(line_number, byte_offset, raw_bytes)`. NEVER call `path.read_text()` or load the whole file.
- [ ] If `path.stat().st_size > byte_cap and deep_parse_only`: return stub `ParsedSession` (no events, no first_user_message, empty usage_records) + `ImportReport` with `analysis_state="skipped"`.
- [ ] Stop streaming when next line would exceed `byte_cap` (track running offset); mark `byte_cap_hit=True`; keep events before cap.
- [ ] Per-line: `len(raw_bytes) > 2 MiB` → `report.record_skip("line_too_large", …)`, do NOT call `json.loads` on it.
- [ ] `json.JSONDecodeError` → `report.record_skip("json_decode", …)`.
- [ ] Unknown event type (not in vendor allowlist) → `report.record_skip(f"unsupported_type:<type>", …)`. **Do NOT count normal `user`/`assistant`/`system`/tool-result lines as unsupported** (per E11) — these are supported event sources, not unsupported.
- [ ] Capture first user message: first line where `role == "user"` AND `content` is string OR text-block list. Extract concatenated text, pass to ImportReport via `set_display_title()` later (in the command, not the parser).
- [ ] Capture usage records: every line with `message.usage` and `message.model` → append raw dict to `usage_records`.
- [ ] Update existing parser tests for tuple return; add malformed/byte-cap/oversized/title/usage assertions.
- [ ] Run `pytest tests/unit/test_claude_session_parser.py -q`.

### Task 15: Codex parser — streaming + report plumbing

**Files:** `store/codex_session.py`, `tests/unit/test_codex_session_parser.py`, fixture `codex-oversized-line.jsonl`

- [ ] Mirror Task 14's signature change and binary streaming for `parse_rollout`.
- [ ] Preserve existing session-meta extraction, originator/mode handling, parent-thread extraction.
- [ ] Define a known Codex type allowlist (`session_meta`, `message`, `tool_call`, `tool_result`, lifecycle markers, etc.) — only lines OUTSIDE this allowlist count as `skipped_unsupported_type`.
- [ ] Capture first user message: `type=="message" AND role=="user"`, extract `content` or nested `payload.content`.
- [ ] Capture usage records: every line with `payload.info.tokens` OR equivalent top-level rollout shape → raw dict to `usage_records`.
- [ ] Create `codex-oversized-line.jsonl`: one row with `payload.content` padded to >2 MiB.
- [ ] Tests: oversized/malformed/byte-cap/skipped/first-user/usage-record cases.
- [ ] Run `pytest tests/unit/test_codex_session_parser.py -q`.

## Phase 7 — Commands + projections (serial)

### Task 16: Shared finalization + Claude command

**Files:** `commands/import_common.py`, `commands/import_claude_session.py`, `tests/integration/test_import_claude_session_report.py`, `tests/integration/test_import_byte_cap.py` (Claude half), `docs/cli.md`, `docs/security.md`

- [ ] Create `commands/import_common.py`:
  - Constants: `DEFAULT_IMPORT_BYTE_CAP = 64 * 1024 * 1024`, `MIN_IMPORT_BYTE_CAP = 1 * 1024 * 1024`, `MAX_IMPORT_BYTE_CAP = 1024 * 1024 * 1024`.
  - Typer validation helper for `--byte-cap`.
  - `finalize_imported_run(run_dir: Path, run_id: str, analysis_state: str) -> None`:
    - Write `final.json` (`agent_outcome="unknown"` if `analysis_state=="full"`, else `"partial"`).
    - `manifest.seal(pre_eval)`.
    - `evaluate()` → `eval.json`.
    - `manifest.seal(final)`.
    - `sqlite_index.index_run()` (best-effort; absorb exceptions).
- [ ] Update `import_claude_session._import_one()`:
  - Preserve duplicate-import no-op via existing `_existing_run_for_import_key` BEFORE any writes (E9).
  - Call `parse_session(path, byte_cap=byte_cap, deep_parse_only=deep_parse_only)`.
  - Compute `display_title = extract_display_title(explicit=None, first_user_message=parsed.first_user_message_text)`; `report.set_display_title(display_title, "first_user_message" if display_title else "null")`.
  - Compute `usage = extract_usage("claude-session", parsed.usage_records)`.
  - Write events in order: `run.started` → `command.started` → all parsed `claude.*` events (preserved order) → `command.finished` (with `line_count`, `analysis_state` in payload).
  - Copy transcript to `artifacts/transcripts/<source-session-id>.jsonl`; `report.set_transcript_artifact(...)`.
  - Write `artifacts/import_report.json` via `write_artifact_json`.
  - Write `artifacts/usage.json` via `write_artifact_json` (always, even all-zero for Desktop).
  - Call `finalize_imported_run(run_dir, run_id, analysis_state=report.analysis_state)`.
- [ ] Add Typer options `--byte-cap INTEGER` and `--deep-parse-only/--no-deep-parse-only`. Validate byte-cap range; out-of-range → `typer.BadParameter`.
- [ ] Integration tests:
  - Malformed Claude source → `analysis_state="partial"`, `run.started` is first event, manifest covers transcript+report+usage, eval exists, projection keys returned by `agentlens show <id> --format json`.
  - Byte cap: default over-cap → `partial`; `--deep-parse-only` → `skipped` with no `claude.*` events but `run.started`/`command.started`/`command.finished` still present.
  - Duplicate import remains a no-op: no second run dir, no overwrite of existing report/usage.
- [ ] Patch `docs/cli.md` (new flags + projection keys).
- [ ] Patch `docs/security.md`: add bullet — *"Importers write `artifacts/import_report.json` (line counts, skip reasons, derived title) and `artifacts/usage.json` (token totals). Neither contains prompt or output text beyond the title field (capped 120 chars, redacted per importers/title.py)."* Also correct earlier wording claiming transcripts are newly redacted — they are not (E10).
- [ ] Run `pytest tests/integration/test_import_claude_session_report.py tests/integration/test_import_byte_cap.py -q`.

### Task 17: Codex command

**Files:** `commands/import_codex_session.py`, `tests/integration/test_import_codex_session_report.py`, `tests/integration/test_import_byte_cap.py` (Codex half)

- [ ] Mirror Task 16 for the Codex importer.
- [ ] Preserve existing Codex Desktop vs CLI `agent.label` / `agent.mode` differentiation via `originator` from session_meta.
- [ ] Preserve existing parent linkage and pending-parent backfill — backfill MUST run AFTER `finalize_imported_run()` so the index is consistent.
- [ ] Codex Desktop (no tokens) → `usage.json` is still written with all-zero counters and `confidence="unknown"`.
- [ ] Integration tests: CLI exact usage; Desktop unknown usage; manifest covers all artifacts; projection keys; parent-backfill regression; byte-cap skipped behaviour.
- [ ] Run `pytest tests/integration/test_import_codex_session_report.py tests/integration/test_import_byte_cap.py tests/integration/test_import_codex_session.py -q`.

### Task 18: Query / API / projector / index / type projection

**Files:** `store/query.py`, `store/sqlite_index.py`, `commands/_format.py`, `web/routers/runs.py`, `web/src/api/runs.ts`, `web/src/types/api.ts`, `tests/fixtures/format_snapshots/*.json`, `tests/integration/test_query_projection_usage_title.py`, `tests/integration/test_format_json_snapshot.py`, `tests/integration/test_web_e2e_runs_list.py`, `tests/integration/test_web_e2e_run_detail.py`

- [ ] In `store/query.py`: add helper that locates the run dir from `(home, workspace_id, run_id)` and safely reads `artifacts/import_report.json` + `artifacts/usage.json` (returns `None` on absent/malformed).
- [ ] Enrich `latest()`, `full_scan_runs()`, `list_runs()`, `get_run()` with three additive keys: `display_title` (from `import_report.derived.display_title`), `usage` (public subset of `usage.json`), `import_state` (from `import_report.analysis_state`). Emit `None` when artifacts are missing (container runs).
- [ ] Update `_RUN_ROW_COLUMNS` / SQLite SELECT so SQLite-backed `latest()` returns same enriched shape as full-scan.
- [ ] In `sqlite_index.py`: add nullable columns `display_title TEXT`, `usage_confidence TEXT`, `import_state TEXT`. Idempotent migration (`ALTER TABLE … ADD COLUMN IF NOT EXISTS …` for SQLite — use `PRAGMA table_info` check then `ALTER` because SQLite lacks `IF NOT EXISTS` on `ADD COLUMN`). Populate from artifacts during `index_run()`.
- [ ] In `commands/_format.py`: add three keys to `project_run_row()` and `project_show()` with defaults `None`/`None`/`None`. Always emit keys (never omit) so dashboard/consumers see stable shape.
- [ ] Regenerate snapshot fixtures: `AGENTLENS_UPDATE_SNAPSHOTS=1 pytest tests/integration/test_format_json_snapshot.py`. Commit the updated fixtures.
- [ ] Update `/api/v1/runs` and `/api/v1/runs/{id}` tests so payloads include projector-derived fields and do NOT expose `source_path` (web layer rule: never read importer artifacts directly).
- [ ] Run `npm --prefix AgentLens/web run gen-types` and commit `web/src/types/api.ts` drift.
- [ ] Update `web/src/api/runs.ts` types.
- [ ] Tests:
  - Imported Claude run → all three keys populated; imported Codex Desktop → `usage` populated but `confidence="unknown"`; container run (kws-cme) → all three keys `null`.
  - `test_format_json_snapshot.py` passes against new fixtures.
  - `/api/v1/runs` payload contains the three keys, does NOT contain `source_path`.
- [ ] Run `pytest tests/integration/test_query_projection_usage_title.py tests/integration/test_format_json_snapshot.py tests/integration/test_web_e2e_runs_list.py tests/integration/test_web_e2e_run_detail.py -q`.

## Phase 8 — Dashboard + close-out (serial)

### Task 19: Dashboard UI + design spec patch

**Files:** `web/src/components/run-list-table.tsx`, `web/src/components/run-list-table.test.tsx`, `docs/spec/2026-05-19-agentlens-dashboard-design.md`

- [ ] Add five run-list cells:
  - **Title** ← `display_title`, fallback to short `run_id`
  - **Usage** ← `usage.input_tokens` / `usage.output_tokens`, fallback `—`
  - **Cost** ← `usage.cost_usd`, fallback `—`
  - **Confidence** ← `usage.confidence` badge (`exact`/`estimated`/`unknown`)
  - **Import state** ← `import_state` badge; `partial` and `skipped` visually flagged
- [ ] Keep existing false-success highlighting and failure-count behaviour intact.
- [ ] Vitest coverage: populated usage/title/import-state; null fallback rendering; partial badge visually distinct from full.
- [ ] Patch `docs/spec/2026-05-19-agentlens-dashboard-design.md` "Run list — signature screen" (or equivalent) section with the five new data points and the rule: *"All five fields come from the run projection (`store.query`/projectors); web routes never read derived importer artifacts directly for list rendering."*
- [ ] Run `npm --prefix AgentLens/web test -- run-list-table`.

### Task 20: End-to-end smoke + sign-off

**Files:** `docs/contract.md`

- [ ] Run focused Python tests: `pytest tests/unit/test_importers_title.py tests/unit/test_importers_usage.py tests/unit/test_importers_report.py tests/unit/test_claude_session_parser.py tests/unit/test_codex_session_parser.py -q`. All green.
- [ ] Run importer/query integration: `pytest tests/integration/test_import_claude_session.py tests/integration/test_import_codex_session.py tests/integration/test_import_claude_session_report.py tests/integration/test_import_codex_session_report.py tests/integration/test_import_byte_cap.py tests/integration/test_query_projection_usage_title.py tests/integration/test_format_json_snapshot.py -q`. All green.
- [ ] Run full Python suite: `pytest -q`. All green.
- [ ] Run frontend tests: `npm --prefix AgentLens/web test`. All green.
- [ ] Manual import on real local history:
  - Pick one real Claude session under `~/.claude/projects/*/*.jsonl` → `agentlens import claude-session --session <id>`.
  - Pick one real Codex session under `~/.codex/sessions/*/*.jsonl` → `agentlens import codex-session --session <id>`.
  - For both, confirm:
    - `manifest.json` final phase covers `artifacts/transcripts/*`, `artifacts/import_report.json`, and `artifacts/usage.json` (non-empty sha256 each).
    - `eval.json` exists; eval status is not `failed` solely because usage is unknown or import state is partial.
    - `agentlens latest --format json`, `agentlens status --format json`, `agentlens show <run_id> --format json`, and `curl http://localhost:<port>/api/v1/runs` (start web with `agentlens serve`) include `display_title`, `usage`, `import_state`.
    - Re-import → no second run, no overwrite of report/usage.
- [ ] Update `docs/contract.md` with a short additive-artifacts note:
  > **2026-05-19 — additive:** Importers gained `artifacts/import_report.json` and `artifacts/usage.json`; query/API/dashboard projections gained `display_title`, `usage`, `import_state` (additive null when absent). No v1 schema changed. Install gained wrapper-detection + selftest-probe safety; `agentlens doctor` gained `shim_integrity=wrapper_chain_warning`. No CLI breakage; new flags optional.
- [ ] Run `git diff --check`.

---

## Definition of Done

- [ ] All twenty task checkboxes above are checked.
- [ ] `pytest -q` is green for the full Python suite.
- [ ] `npm --prefix AgentLens/web test` is green.
- [ ] No edits to `run.schema.json`, `event.schema.json`, `final.schema.json`, `eval.schema.json`, or `manifest.schema.json`.
- [ ] **Part A** (Tasks 1-10) sealed before Part B (Task 11) started.
- [ ] Imported runs start `events.jsonl` with `run.started`.
- [ ] Imported runs are finalized: `final.json`, `eval.json`, `manifest.json`, and index row exist.
- [ ] `manifest.json` covers transcript, `import_report.json`, and `usage.json`.
- [ ] Duplicate import remains a no-op via `input.import_key`.
- [ ] `agentlens install` refuses cmux-launcher targets without `--no-wrapper-detect`; selftest probe runs by default.
- [ ] `agentlens doctor` surfaces existing broken installs with `shim_integrity=wrapper_chain_warning` + actionable `remediation`.
- [ ] `docs/cli.md`, `docs/security.md`, `docs/contract.md`, and the dashboard design spec reflect all additions and the corrected transcript-privacy wording.

## Out of Scope

| Item | Reason | Where it goes |
|------|--------|---------------|
| Pricing table for `cost_usd` | Vendor SKU mapping, refresh cadence, currency policy needed. | Follow-up spec; shape already reserved. |
| `agentlens install --repair` one-shot fix | Doctor already prints the remediation command. KISS. | Future follow-up if friction surfaces. |
| Safe HTML export (`agentlens export`) | No dashboard consumer yet. | ADR Phase D, post-v1. |
| Sanitized transcript copies for export | Privacy decision deferred; existing copy is raw vendor JSONL. | ADR §5.5 follow-up. |
| TUI (`agentlens sessions`) | Redundant with dashboard for this patch. | ADR Phase E, post-v1. |
| Windows shim support | Out of v1 scope. | Future. |
| `--refresh` flag for duplicate imports | Would change no-op idempotency semantics. | Follow-up CLI spec. |
| Title heuristic v2 / LLM-assisted titles | Determinism + offline operation win for v1.x. | Revisit after real dashboard samples. |
| Migrating `kws-cme` / `kws-cpe` event namespaces to lowercase | Already owned by `2026-05-19-agentlens-v1-and-kws-unification.md`. | That plan owns it. |
| Heuristics for "step past a detected wrapper" | Vendor-specific; wrong-target risk. | User passes `--real` explicitly. |
| Automatic migration of broken `.real` lockfiles | Violates consent model. | Doctor surfaces; user runs the command. |
| Automatic shell rc editing | AgentLens explicitly does not edit user's rc (spec §S1.6.18). | Not planned. |
