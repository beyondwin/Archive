# AgentLens Security & Privacy (v1 locked)

This document re-narrates spec section S1.9 (보안 / 프라이버시 구현 디테일). The policies below are **v1 잠금 / v1 locked**: the default-deny posture, the redaction allow-list, the `MAX_EXCERPT_CHARS` budget, and the shim permission model are part of the user-visible privacy contract and cannot be relaxed without a major-version bump and an explicit user opt-in.

## 1. Default-deny posture

AgentLens stores the **minimum** information needed to reconstruct a run timeline. Everything else is either masked, excerpted, or simply not captured. Concretely:

- **Full prompt transcripts are never captured by the process wrapper.** `agentlens run -- <cmd>` and the PATH-shim path do not store prompt-level conversation; `manifest.redaction.full_prompts` is permanently set to `"not_stored"` for these runs, and the resulting `run.json` always carries `recording.has_transcript=false`, `recording.transcript_source="none"`. The only path that can attach a transcript to a run is an **explicit session importer** (`agentlens import claude-session` or `agentlens import codex-session`, see `cli.md` §3a and §6 below).
- **Full command output** is never persisted; only allow-list-extracted excerpts.
- **Absolute home paths** are masked. Any path under the user's `$HOME` is rewritten on the way to disk as `<HOME>/<HASH8>` where `HASH8` is the first 8 hex characters of a salted SHA-256 of the relative remainder. This preserves stable identity across events without leaking the user's directory layout.
- **Credentials** are masked via redaction patterns. The default set covers OpenAI/Anthropic-style API keys, AWS access keys, Bearer/Authorization headers, GitHub tokens, and PEM private-key bodies. Each mask uses a typed sentinel such as `<REDACTED:openai_key>` so downstream tooling can reason about *what* was masked.

## 2. Redaction pipeline

All externally-sourced strings — command `argv`, file paths, log excerpts, stdout/stderr fragments, environment variables surfaced into events — pass through `redaction/redact.py` before they reach the writer. The writer then schema-validates the redacted document; a redaction bug that would have stored a raw secret is therefore caught at write time as a schema violation rather than persisted.

Protected fields are intentionally **not** subject to mutation by the redaction layer: artifact hashes, run IDs, event IDs, status enums, and timestamps must round-trip unchanged. The redaction pipeline operates only on user-visible string content.

## 3. Excerpt allow-list & `MAX_EXCERPT_CHARS=4096`

AgentLens does not store arbitrary free-text slices of command output. Every excerpt that lands in `events.jsonl` or `final.json` is produced by a named extractor from the `EXCERPT_EXTRACTORS` allow-list (test summary lines, traceback head, lint summary, etc.). The writer enforces a hard ceiling of `MAX_EXCERPT_CHARS = 4096` per excerpt; anything longer is truncated and suffixed with a literal `<TRUNCATED>` marker so consumers can tell that the excerpt is partial.

Free-text slicing — "store the last 8 KB of stdout" — is explicitly forbidden. Adding a new excerpt source means adding a new entry to the allow-list with a documented extractor function.

## 4. Shim security

The PATH-shim mechanism used by Integration Level 2 (`shim`) writes per-binary wrapper scripts under `~/.agentlens/shims/`. The directory itself is created with **`0700`** permissions and AgentLens verifies on every shim invocation that:

- The shims directory owner matches the current user.
- The shim file is `0700` (or stricter).
- The companion `.real` lockfile records the absolute path of the wrapped binary plus the sha256 of its content captured at install time.

If the real binary's sha256 has drifted from the lockfile — a system update, a brew upgrade, a swapped Python — the shim immediately falls through to a **passthrough exec** of the real binary and writes a `recording_incomplete=true` marker explaining the drift. The shim never tries to "best-guess" a binary it cannot identify.

`agentlens install` requires explicit user consent before writing any shim files. **It never edits the user's shell rc.** On confirmation, it writes the shim and `.real` lockfile under `~/.agentlens/shims/` and then prints a one-line `export PATH="$HOME/.agentlens/shims:$PATH"` hint that the user must add to their shell rc manually. The `--yes` flag bypasses the interactive consent prompt for CI/automation only; the PATH hint is still printed, and the shell rc remains untouched.

`agentlens install` further runs two install-safety layers before the shim is considered installed. **Layer 1 — wrapper-signature scan** inspects the resolved real binary and refuses to wrap anything that itself looks like a wrapper (AgentLens's own shim, a cmux-style proxy script, or a `which`-loop-prone PATH-lookup launcher). It is a **denylist**: it catches the known wrapper patterns, but cannot anticipate every future wrapper shape. **Layer 2 — post-install selftest probe** is the catch-all: after the shim and `.real` lockfile are written, AgentLens executes the shim with a no-op argument; any wrapper that slipped past Layer 1 manifests here as an exec loop or non-zero exit, and the shim plus lockfile are rolled back atomically. The two bypass flags acknowledge the exec-loop risk explicitly: `--no-wrapper-detect` must be paired with `--yes` (so the bypass is always intentional), while `--skip-selftest` stands alone for environments where the probe itself is unreliable. Disabling either layer means the user accepts responsibility if the wrapped target turns out to be a wrapper itself.

`agentlens uninstall <agent>` is the inverse: it removes `~/.agentlens/shims/<agent>` and its `.real` lockfile, and is idempotent (no error if the shim is already absent).

## 5. Kill switch & nested invocation policy

- **`AGENTLENS_DISABLE=1`** is the **unconditional kill switch**. When this environment variable is truthy (`1`, `true`, `yes`, `on`, case-insensitive), the config loader returns `{"mode": "disabled"}` regardless of any YAML file, env var, or workspace setting. This is the recommended way to silence recording in a single shell or CI step without editing config files.
- **Nested invocations.** When a process running under `agentlens run` invokes `agentlens run` again, the wrapper detects the parent via the `AGENTLENS_RUN_ID` environment variable. Two policies are available:
  - `AGENTLENS_NESTED_POLICY=passthrough` (default) — the nested call skips re-recording and acts as a transparent passthrough; only the outer run captures the timeline.
  - `AGENTLENS_NESTED_POLICY=nested` — opens a new run for the child, recording the outer run's id as `parent_run_id` in `run.json`.

  The recording-path environment variables (`AGENTLENS_RUN_ID`, `AGENTLENS_RUN_DIR`, `AGENTLENS_RUN_PID_STAMP`) are only propagated to children on the recording path; passthrough children inherit a clean environment with respect to those variables.

## 6. Retention

Stored runs are bounded by `max_total_store_gb` (default 5). When the cap is exceeded, `agentlens gc` deletes the oldest **sealed** runs' `artifacts/` directories first; `eval.json`, `final.json`, and `manifest.json` are preserved under `keep_eval_summaries=true` so query commands can still surface the run's existence and outcome long after the heavy artifacts are gone. Unsealed and `recording_incomplete` runs are never reaped automatically — the user must seal or remove them explicitly.

### 6.1 Imported transcripts

Session JSONL imported by `agentlens import claude-session` and `agentlens import codex-session` is stored **only** at `artifacts/transcripts/<session-id>.jsonl` under the importing run. There is no root-level `transcript.jsonl` and no other duplicate copy — this single path is the source of truth for the transcript.

- **Manifest-covered.** Each imported transcript file is registered in `manifest.json` with its sha256 and byte size, the same as any other artifact. Tampering or partial writes are detectable via the manifest.
- **Subject to retention.** Imported transcripts live inside `artifacts/` and are therefore reaped by the same `large_artifacts_days` and `max_total_store_gb` rules that govern any other heavy artifact. The summary JSON (`run.json`, `final.json`, `eval.json`, `manifest.json`) is still preserved under `keep_eval_summaries=true`, so a query after garbage collection will surface the run's existence — and the fact that it once had `recording.has_transcript=true` — even after the transcript bytes themselves are gone.
- **Transcript bytes are stored verbatim.** The session importers copy the source JSONL into `artifacts/transcripts/<session-id>.jsonl` byte-for-byte (`shutil.copyfile`), so the transcript hashes recorded in `manifest.json` match the original source file. The redaction pipeline (§2) governs material the **AgentLens writer** produces — `events.jsonl`, `final.json`, derived event payloads — not the verbatim transcript copy. If the source JSONL contains secrets, the imported transcript will too; treat imported transcripts as the same trust class as the source. The derived artifacts written next to the transcript (see below) are produced by AgentLens code and never include the raw absolute path of the source.
- **No transcripts from the wrapper.** The process wrapper never writes into `artifacts/transcripts/`. Only the named session importers do, and they are the only paths that can flip `recording.has_transcript` to `true`.
- **Imported derived artifacts (`import_report.json` + `usage.json`).** Each imported run also carries `artifacts/import_report.json` (parse-time accounting per spec §4.1: counters, first-error, byte-cap status, derived display title, transcript pointer) and `artifacts/usage.json` (aggregated per-model token usage per spec §4.3). Their content scope is intentionally narrow:
  - `import_report.json` carries a **redacted** `source_path` (`"<source>:<session-id>"`, never the raw absolute path) plus a `source_path_hash` (sha256 of the resolved absolute path) sufficient for cross-report correlation without leaking `$HOME` or session-directory layout. Counters and the `first_error` line/byte offset are non-secret structural metadata.
  - `usage.json` carries only aggregate token counts (input, output, cache creation/read, reasoning) per model — no prompt or response text — and is safe to publish alongside redacted query output.
  Both files are manifest-covered and subject to the same retention rules as the transcript.

## 6.2 Host-isolation invariant (failure containment)

AgentLens calls embedded in host orchestrators (kws-cme, kws-cpe, and any
future skill) are wired so that AgentLens **never blocks the host
workflow**. The contract has two enforcement points:

- **Host snippet shape.** Orchestrators invoke AgentLens with
  `agentlens <subcommand> ... 2>/dev/null || true`, which guarantees a
  missing CLI on `PATH` produces a no-op (exit 0). The shape is
  user-visible by design — it is the only mechanism that survives
  scenarios where the user has uninstalled AgentLens entirely.
- **CLI-side non-blocking.** Inside `agentlens event append`,
  `agentlens run-close`, and `agentlens mark`, unexpected exceptions —
  including an unreadable `$AGENTLENS_HOME/runs/`, a stale `run_id`, a
  corrupt index, or a permission-denied transient — are swallowed,
  surfaced on stderr as a single `warning:` line, and the process exits
  with code `0`. The host orchestrator therefore sees a uniformly
  non-error response regardless of AgentLens's internal state.

Automated coverage lives in
`AgentLens/tests/integration/test_failure_isolation.py` (PATH-missing,
unreadable-home, unknown-run-id, namespace-glob, tree-traversal).

## 7. v1 잠금 정책 (v1 lock policy)

- The default-deny posture, the redaction sentinel format (`<REDACTED:*>`), the `<HOME>/<HASH8>` rewrite, the `MAX_EXCERPT_CHARS=4096` budget, the `0700` shim directory permission, and the shim sha256 drift check are **locked** for v1. Relaxing any of them requires a major-version bump and an explicit opt-in flag.
