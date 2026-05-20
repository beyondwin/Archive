# AgentLens Storage & Lifecycle Contract (v1 locked)

This document re-narrates spec section S1.4 (디렉터리 / 파일 트리) and the relevant lifecycle invariants from S1.2. The shape of every artifact described here is **v1 잠금 / v1 locked**: once a field name, file name, or seal phase is shipped under the `agentlens.*.v1` family, it is treated as a stable wire contract. Breaking changes require a new versioned schema (`v2`) and a deliberate migration plan — never an in-place edit.

## 1. Run directory layout

All durable run state lives under the user's home directory:

```
~/.agentlens/
  runs/<workspace_id>/<run_id>/
    run.json           # agentlens.run.v1     — run header, parent/child links, agent/mode
    events.jsonl       # agentlens.event.v1   — append-only, line-delimited timeline
    final.json         # agentlens.final.v1   — outcome summary (optional until final)
    eval.json          # agentlens.eval.v1    — evaluator output (after pre_eval seal)
    manifest.json      # agentlens.manifest.v1 — artifact sha256+size, sealed_phase, redaction notes
    artifacts/         # binary attachments (logs, screenshots, diffs)
  current-runs/<workspace_id>/<run_id>     # active-run pointer / lock marker
  shims/                                    # 0700; per-binary shim script + .real lockfile
  config.yaml
```

`workspace_id` is derived from the working directory's content hash (see S1.6); `run_id` is a ULID. CLI surfaces never print absolute paths — they show `<workspace_id_short>/<run_id>` and relative artifact paths only.

## 2. Source of truth — JSON artifacts

The **source of truth for any run is the JSON artifacts on disk**, not SQLite. The SQLite store under `~/.agentlens/index.db` is a best-effort secondary index used solely to accelerate `latest`, `failures`, and `risks` queries. Per S1.2:

- JSON writes go through `store/writer.py` and are **atomic** (write to tmp + rename within the same directory).
- SQLite writes are **best-effort**: failure is swallowed and logged. JSON write failure **raises**.
- The writer applies redaction before persistence and re-validates the document against its JSON Schema.
- The evaluator is read-only — it must never mutate a durable artifact.

If the SQLite index disagrees with the JSON artifacts, the JSON wins. `agentlens doctor` will detect the drift and rebuild the index from disk.

## 3. Two-phase seal — `pre_eval` and `final`

A run transitions through two seal points; the current state is recorded in `manifest.sealed_phase`:

1. **`pre_eval` seal.** Triggered by `agentlens seal` (without `--final`) or implicitly at the start of `agentlens eval`. This freezes `run.json`, `events.jsonl`, `final.json`, and `manifest.json` so the evaluator sees a stable input. Once the `pre_eval` seal is taken, no further events may be appended to that run.
2. **`final` seal.** Triggered by `agentlens seal --final` (typically immediately after `agentlens eval` writes `eval.json`). This freezes `eval.json` as well and stamps the manifest with the final artifact hashes. After the `final` seal the run is immutable — any subsequent mutation attempt is a writer error.

The two-phase shape exists to give the evaluator a hermetic input set without coupling its completion to the freeze of its own output. Both seals are recorded in `manifest.json` with timestamps and sha256 sums for every artifact present.

## 3a. Additive v1 schema fields (S1.5.1 unification)

The v1 lock is preserved by adding **only** additive optional fields. Three groups land in `run.json` and one pattern lands in `events.jsonl`. None of them rename, remove, or change the meaning of an existing field.

### 3a.1 `run.json` additive fields

| Field                                | Type / values                                                                                                | Default          | Purpose                                                                                                                                                  |
|--------------------------------------|--------------------------------------------------------------------------------------------------------------|------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `run_kind`                           | `"capture"` \| `"container"`                                                                                 | `"capture"`      | `"capture"` is a normal recorded run. `"container"` is an orchestrator-scope run opened by `agentlens run-open` that does not own a child process.       |
| `agent.label`                        | string                                                                                                       | `agent.name`     | Human-facing label distinct from the canonical `agent.name` enum. Lets container runs carry a skill-specific identity (e.g. `agentrunway`).     |
| `recording.has_transcript`           | boolean                                                                                                      | `false`          | True when this run has a full prompt-level transcript attached. Process-wrapper runs are always `false`.                                                 |
| `recording.transcript_source`        | `"none"` \| `"claude-session-jsonl"` \| `"codex-rollout-jsonl"` \| `"wrapper-stream-json"` \| `"external"`    | `"none"`         | Provenance for the transcript when `has_transcript=true`. The wrapper itself never produces transcripts — see §3a.3.                                     |
| `input.import_key`                   | string                                                                                                       | absent           | Idempotency key for importers. Convention: `"claude-session:<id>"`, `"codex-rollout:<id>"`. A re-import with the same key is a no-op.                    |

**Container-run shape.** When `run_kind="container"` the writer also stamps:

- `agent.name = "generic"`
- `agent.mode = "unknown"`
- `agent.label = "<skill>-orchestrator"` (caller-supplied)
- `recording.adapter = "agentlens_container"`
- `recording.has_transcript = false`

### 3a.2 `events.jsonl` namespace pattern

The `type` field is no longer a fixed enum; it is a lower-case dotted namespace:

```
^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)+$
```

Reserved core namespaces — `run.*`, `command.*`, `checkpoint.*`, `artifact.*`, `task.*`, `failure.*`, `recording.*`, `agentlens.*` — remain pinned to their locked event-name enum (see `event.schema.json`). AgentRunway (`agentrunway.*`), neutral external namespaces (`example.*`, …), and importer namespaces (`claude.*`, `codex.*`) are unconstrained beyond the general pattern, so external producers can append structured events under their own prefix without coordinating an enum change.

```bash
agentlens run-open --agent agentrunway --workspace "$PWD"
agentlens event append --run "$RUN_ID" --type agentrunway.run_started --payload-json '{"schema":"agentrunway.event.v1","summary":"started"}'
agentlens events --run "$RUN_ID" --type 'agentrunway.*'
```

### 3a.3 Transcript source policy

A note that belongs at the contract layer because it interacts with §1 (run directory layout) and `security.md` §1:

- The **process wrapper does not capture full prompt transcripts.** `agentlens run -- <cmd>` always produces a run with `recording.has_transcript=false` and `recording.transcript_source="none"`. The wrapper sees stdout/stderr fragments only, and those are filtered by the allow-list excerpt extractors (§3 of `security.md`).
- Transcripts come from **session-JSONL importers** only — `agentlens import claude-session` and `agentlens import codex-session` (see `cli.md`). Those importers set `recording.has_transcript=true` and a matching `transcript_source`.
- Imported session JSONL is copied into `artifacts/transcripts/<session-id>.jsonl` under the run directory; it is never written to a root-level `transcript.jsonl` and it is manifest-covered (`manifest.json` records sha256 and size like any other artifact). It is therefore subject to the same retention rules as other heavy artifacts — see `security.md` §6.

## 4. `recording_incomplete` semantics

If **any** AgentLens write fails after `agentlens start` has produced a run directory — a `events.jsonl` append error, a `final.json` schema failure, a disk-full error during seal — the run is marked `recording_incomplete=true` in `manifest.json` with a structured `reason` field. The contract is intentionally asymmetric:

- The **fact of incompleteness is itself recorded** whenever possible (manifest update is best-effort but tried).
- The child command's exit status is **never altered** by AgentLens write failures. `agentlens run -- <command>` returns the child's exit code verbatim. If the run directory cannot even be created (S1.2 invariant #6), AgentLens silently degrades to passthrough — the child still runs.
- A `recording_incomplete=true` run is still queryable by `show` / `latest`; queries that depend on missing artifacts return `null` instead of raising.

`pre_eval` and `final` seals on an incomplete run are permitted and preserve the `recording_incomplete` flag — sealing locks the partial state in place rather than erasing it.

## 5. Retention & garbage collection

`agentlens gc` enforces a `RetentionPolicy` (frozen dataclass in `store/retention.py`) against the durable run tree and returns a `GcReport` summarising `deleted_paths`, `freed_bytes`, `kept_summaries`, and the `dry_run` flag. The policy is filesystem-only — it never touches `index.db` — so it is safe to run when the SQLite cache is offline or corrupt. Summary JSON (`run.json`, `final.json`, `eval.json`, `manifest.json`) is preserved under the default `keep_eval_summaries=true`, so query commands continue to surface run identity and outcome after the heavy artifacts are reaped. See `runbook.md` §5 for the defaults table and `security.md` §6 for the privacy framing.

## 6. Non-blocking fault-inject contract

The §10.4 non-blocking contract is a six-scenario regression LOCK pinned by `tests/integration/test_nonblocking.py`. The wrapped child's exit code MUST be propagated verbatim across all six AgentLens-internal failures: (1) `compute_workspace_id` raise at init, (2) `manifest` seal failure, (3) evaluator crash, (4) SQLite index update failure, (5) `pre_eval` seal failure, and (6) SIGINT delivered to the child (wrapper exits `128 + signum`, `agent_outcome=cancelled`). Determinism is similarly locked at `tests/integration/test_eval_determinism.py::test_evaluate_three_run_byte_lock_regression` — three evaluator runs × five fixtures, pairwise byte-equal under `sort_keys=True` and `normalize_for_diff` timestamp masking.

## 7. v1 잠금 정책 (v1 lock policy)

- File names (`run.json`, `events.jsonl`, `final.json`, `eval.json`, `manifest.json`) are **locked**.
- Schema names (`agentlens.run.v1`, `agentlens.event.v1`, `agentlens.final.v1`, `agentlens.eval.v1`, `agentlens.manifest.v1`) are **locked**.
- Field semantics for `sealed_phase ∈ {none, pre_eval, final}` and `recording_incomplete: bool` are **locked**.
- New fields may be added only when they are optional and additive; renames or removals require `v2`.
- The directory layout under `~/.agentlens/runs/<workspace_id>/<run_id>/` is **locked**; tooling outside AgentLens may rely on this path shape.

## 8. Additive changes log

**2026-05-19 — additive:** Importers gained `artifacts/import_report.json` and `artifacts/usage.json`; query/API/dashboard projections gained `display_title`, `usage`, `import_state` (additive null when absent). No v1 schema changed. Install gained wrapper-detection + selftest-probe safety; `agentlens doctor` gained `shim_integrity=wrapper_chain_warning`. No CLI breakage; new flags optional.
