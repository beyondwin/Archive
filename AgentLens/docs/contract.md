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
