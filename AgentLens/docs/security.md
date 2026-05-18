# AgentLens Security & Privacy (v1 locked)

This document re-narrates spec section S1.9 (보안 / 프라이버시 구현 디테일). The policies below are **v1 잠금 / v1 locked**: the default-deny posture, the redaction allow-list, the `MAX_EXCERPT_CHARS` budget, and the shim permission model are part of the user-visible privacy contract and cannot be relaxed without a major-version bump and an explicit user opt-in.

## 1. Default-deny posture

AgentLens stores the **minimum** information needed to reconstruct a run timeline. Everything else is either masked, excerpted, or simply not captured. Concretely:

- **Full prompt transcripts** are never persisted. `manifest.redaction.full_prompts` is permanently set to `"not_stored"`.
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

`agentlens uninstall <agent>` is the inverse: it removes `~/.agentlens/shims/<agent>` and its `.real` lockfile, and is idempotent (no error if the shim is already absent).

## 5. Kill switch & nested invocation policy

- **`AGENTLENS_DISABLE=1`** is the **unconditional kill switch**. When this environment variable is truthy (`1`, `true`, `yes`, `on`, case-insensitive), the config loader returns `{"mode": "disabled"}` regardless of any YAML file, env var, or workspace setting. This is the recommended way to silence recording in a single shell or CI step without editing config files.
- **Nested invocations.** When a process running under `agentlens run` invokes `agentlens run` again, the wrapper detects the parent via the `AGENTLENS_RUN_ID` environment variable. Two policies are available:
  - `AGENTLENS_NESTED_POLICY=passthrough` (default) — the nested call skips re-recording and acts as a transparent passthrough; only the outer run captures the timeline.
  - `AGENTLENS_NESTED_POLICY=nested` — opens a new run for the child, recording the outer run's id as `parent_run_id` in `run.json`.

  The recording-path environment variables (`AGENTLENS_RUN_ID`, `AGENTLENS_RUN_DIR`, `AGENTLENS_RUN_PID_STAMP`) are only propagated to children on the recording path; passthrough children inherit a clean environment with respect to those variables.

## 6. Retention

Stored runs are bounded by `max_total_store_gb` (default 5). When the cap is exceeded, `agentlens gc` deletes the oldest **sealed** runs' `artifacts/` directories first; `eval.json`, `final.json`, and `manifest.json` are preserved under `keep_eval_summaries=true` so query commands can still surface the run's existence and outcome long after the heavy artifacts are gone. Unsealed and `recording_incomplete` runs are never reaped automatically — the user must seal or remove them explicitly.

## 7. v1 잠금 정책 (v1 lock policy)

- The default-deny posture, the redaction sentinel format (`<REDACTED:*>`), the `<HOME>/<HASH8>` rewrite, the `MAX_EXCERPT_CHARS=4096` budget, the `0700` shim directory permission, and the shim sha256 drift check are **locked** for v1. Relaxing any of them requires a major-version bump and an explicit opt-in flag.
