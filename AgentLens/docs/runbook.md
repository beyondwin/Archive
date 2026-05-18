# AgentLens Operational Runbook (v0)

This runbook is the on-call / SRE-style companion to the spec. It assumes the v0
contract documented in `docs/spec/agentlens_v0_implementation_spec.md` and the
locked surfaces in `docs/cli.md`, `docs/contract.md`, `docs/security.md`, and
`docs/integrations.md`. Use this document to triage an incident, recover a
degraded store, or audit the integration surface on a new machine.

## 1. Overview

AgentLens records agent runs into `~/.agentlens/` (or `$AGENTLENS_HOME`) as
*durable*, evaluator-ready trees. Three v0 invariants drive every operational
response:

1. **Non-blocking** (spec §5.16): AgentLens-internal failures never alter the
   wrapped child's exit code. If the child returned 42, the wrapper returns 42
   — even if the manifest write, evaluator, or SQLite index update crashed.
2. **Determinism** (spec §10.5): `eval.json` is byte-equal across repeated
   runs over the same inputs (timestamps normalised). Any drift is a
   regression and surfaces in `tests/integration/test_eval_determinism.py`.
3. **Filesystem is source of truth** (spec §S1.6.9): SQLite is a cache. Every
   query verb falls back to a full-scan when the index is missing or corrupt;
   summary JSON on disk is the durable answer.

## 2. Common commands

| Command | Purpose |
|---|---|
| `agentlens run -- <cmd>` | Recommended entry point. Wraps `cmd`, records to a new run dir, propagates exit code. |
| `agentlens latest` | One-line newest run for the current workspace. |
| `agentlens status` | All known runs (including in-progress). |
| `agentlens show --latest` | Full summary of a run (failures + risks). |
| `agentlens failures --since-days 30` | Eval failures over the trailing window. |
| `agentlens risks --since-days 30` | Aggregated residual risks. |
| `agentlens doctor` | Health check: integrations + paths + shim integrity. |
| `agentlens gc [--dry-run]` | Apply the retention policy. |
| `agentlens mode show / set` | Inspect or change recording mode (disabled/minimal/full). |
| `agentlens install / uninstall <agent>` | Manage PATH shims. |

All query verbs accept `--format json` and produce a stable schema documented
in `docs/cli.md` §3.2. Text output never includes absolute paths.

## 3. Incident response

### 3.1 SQLite index corruption

**Symptoms**: `agentlens latest` returns stale data, or you see warning log
lines mentioning `cannot open index.db` or `index query failed`.

**Action**:

```bash
rm -f "${AGENTLENS_HOME:-$HOME/.agentlens}/index.db"
python -c "from agentlens.store.sqlite_index import rebuild_index; \
           from agentlens.store.paths import agentlens_home; \
           rebuild_index(agentlens_home())"
```

Until the rebuild finishes, every query verb keeps working via full-scan — see
`tests/integration/test_query_fallback.py` for the integration-level guarantee.
There is no need to "stop the world" before deleting the file; queries are
read-only and writers reopen on the next run.

### 3.2 Disk pressure / store growing without bound

**Symptoms**: `~/.agentlens/runs/` exceeds the configured budget, or the host
flags low free space.

**Action**:

1. Inspect the policy applied by `gc`:
   ```bash
   agentlens gc --dry-run --format json
   ```
   This prints the candidate paths and projected freed bytes without touching
   the disk.
2. Apply the policy:
   ```bash
   agentlens gc
   ```
3. If you need a tighter policy than the defaults, set
   `$AGENTLENS_RETENTION_*` overrides or edit
   `~/.agentlens/config.toml` (see spec §S1.7.3 for the priority chain).

`gc` is intentionally SQLite-independent — it never relies on the index — so
it is safe to run when the cache is offline.

### 3.3 Shim integrity drift

**Symptoms**: `agentlens doctor` reports `shim_integrity: drift` for an
adapter, or a wrapped binary suddenly stops recording.

**Cause**: the wrapped binary's content sha256 changed since
`agentlens install` captured it (brew upgrade, system update, swapped venv).
The shim *falls through* to passthrough exec and writes a
`recording_incomplete=true` marker so the child runs unchanged.

**Action**:

```bash
agentlens uninstall <agent>
agentlens install <agent> --real "$(command -v <real-binary>)"
agentlens doctor
```

Until you reinstall, the agent works — only recording is paused for that
binary. There is no exit-code regression.

### 3.4 A run sealed as `recording_incomplete`

**Symptoms**: `agentlens show <run_id>` reports `sealed_phase: recording_incomplete`,
or `agentlens risks` lists a `RECORDING_INCOMPLETE` entry for the run.

**Cause**: a non-blocking failure (manifest write, evaluator crash, pre-eval
seal) triggered the §5.16 fallback. The child's exit code was preserved
(invariant #1); recording was sealed early so downstream consumers see a clean
"this run is partial" signal.

**Action** — no rollback is required. If you need a recovery path:

1. Inspect `events.jsonl` and `final.json` to see what was captured.
2. If the evaluator crashed, run `agentlens eval --run-id <run_id>` manually
   to retry. If the second attempt succeeds, the manifest seals to `final`.
3. If the manifest itself is unreadable, the run is read-only at this point.
   Delete the run dir if the data is no longer interesting, or archive it.

### 3.5 Workspace pointer divergence

**Symptoms**: `agentlens latest` doesn't see a run you just produced because
the workspace-local `current-runs` marker points to a different run dir than
the durable home.

**Action**: the workspace-local pointer is advisory; it exists to let tooling
discover an active run from inside a workspace. Delete the stale entry under
`<workspace>/.agentlens/current-runs/` and reconfirm with `agentlens status`.
The durable home under `$AGENTLENS_HOME/runs/<workspace_id>/<run_id>/` is the
source of truth.

## 4. Storage layout

```
$AGENTLENS_HOME/                  # default ~/.agentlens
├── index.db                      # SQLite cache (optional — full-scan fallback)
├── shims/                        # 0700 — PATH-shim binaries, see security.md
│   ├── <agent>                   # 0700 wrapper script
│   └── <agent>.real              # lockfile: real path + sha256
├── config.toml                   # user-level overrides (mode, retention)
└── runs/
    └── <workspace_id>/
        ├── current-runs/         # active-run markers (sibling-per-run)
        └── <run_id>/
            ├── run.json          # schema v1 — agent + workspace + recording
            ├── events.jsonl      # timeline (append-only, JSONL)
            ├── final.json        # outcome (success|failed|partial|unknown|cancelled)
            ├── eval.json         # evaluator output (deterministic, byte-stable)
            ├── manifest.json     # seal record (pre_eval | final | recording_incomplete)
            └── artifacts/        # attached files (sha256 keys, optional)
```

Workspace-local pointer (alongside the source tree, advisory):

```
<workspace_root>/.agentlens/
├── config.toml                   # workspace-level overrides
└── current-runs/<run_id>/run_dir # text file pointing at the durable run dir
```

## 5. Retention policy defaults

Defaults from `RetentionPolicy` (spec §5.9):

| Threshold | Default | Effect |
|---|---|---|
| `sealed_runs_days` | 30 | Non-final runs older than this become fully eligible for deletion. |
| `large_artifacts_days` | 7 | Files under `artifacts/` older than this are deleted regardless of run age. |
| `max_artifact_mb_per_run` | 50 | Any single artifact larger than this is deleted regardless of age. |
| `max_total_store_gb` | 5 | When the cumulative store exceeds this quota, the oldest sealed runs have their bulk artifacts (events.jsonl + artifacts/) deleted oldest-first. |
| `keep_eval_summaries` | True | Summary JSON (`run.json`, `final.json`, `eval.json`, `manifest.json`) is preserved when the quota path triggers. |

`gc` is filesystem-only and never touches `index.db` directly; rerun
`rebuild_index` after a heavy `gc` to refresh the cache.

## 6. Integration adapters

| Agent | Adapter | Install | Uninstall |
|---|---|---|---|
| Claude Code (`claude`) | `claude_code_shim` | `agentlens install claude` | `agentlens uninstall claude` |
| Codex CLI (`codex`) | `codex_cli_shim` | `agentlens install codex_cli` | `agentlens uninstall codex_cli` |
| Codex App (`codex-app`) | `codex_app_shim` | `agentlens install codex_app` | `agentlens uninstall codex_app` |

`agentlens install` writes a 0700 shim under `~/.agentlens/shims/<agent>` and a
companion `<agent>.real` lockfile. It **does not edit your shell rc**; the
command prints the one-line PATH hint and exits. Add the hint manually:

```bash
export PATH="$HOME/.agentlens/shims:$PATH"
```

`agentlens doctor` verifies each installed shim's ownership, mode, and
real-binary sha256 against the lockfile. See `docs/security.md` §4 for the
full integrity contract.

## 7. Determinism & evals

The evaluator (`agentlens.evaluator.engine.evaluate`) is **deterministic**:
two runs over the same inputs produce byte-identical `eval.json` once
timestamps are normalised. Determinism is enforced by:

- Sorted iteration over `REQUIRED_CHECKS` (alphabetical by `__name__`).
- `json.dumps(..., sort_keys=True)` on serialise.
- `normalize_for_diff()` masks every `*_at` ISO-8601-UTC timestamp to the
  fixed placeholder `0000-00-00T00:00:00Z` for byte-equality assertions.
- Pure check functions: no module-level mutable state, no network, no
  reading `time.monotonic()`.

The regression LOCK lives at
`tests/integration/test_eval_determinism.py::test_evaluate_three_run_byte_lock_regression`.
It runs the evaluator three times across all five M2 fixtures. **A failure
means nondeterminism was introduced** — track down the culprit (unstable
iteration, an unmasked timestamp, a non-pure check) before declaring done.

## 8. Privacy & redaction

Default-deny posture from `docs/security.md`:

- **Full prompt transcripts**: never persisted (`manifest.redaction.full_prompts == "not_stored"`).
- **Full command output**: never persisted; only allow-listed excerpts capped
  at `MAX_EXCERPT_CHARS = 4096` with a `<TRUNCATED>` suffix.
- **Absolute home paths**: rewritten to `<HOME>/<HASH8>` before being stored.
- **Credentials**: API keys, bearer tokens, AWS keys, PEM bodies all replaced
  with typed sentinels like `<REDACTED:openai_key>`.

Verify on a fresh install:

```bash
agentlens doctor paths --format json | python -m json.tool
agentlens run -- env  # then: agentlens show --latest --format json
```

Inspect the resulting `events.jsonl` and `final.json` for the run — any token
that looks like a credential should appear as `<REDACTED:*>`. If a real
secret survived the pipeline, the writer's schema validation should have
rejected the document at write time; report the failure as a P0 redaction
bug (see `tests/unit/test_redaction.py` for the policy surface).

## 9. Escalation pointers

| Symptom | First check | Spec ref |
|---|---|---|
| Wrapper exit code != child's | `tests/integration/test_nonblocking.py` (must still pass) | §5.16, §S1.6.17 |
| `eval.json` differs across runs | `tests/integration/test_eval_determinism.py` | §9.5, §10.5 |
| Query verb returns wrong/empty | `tests/integration/test_query_fallback.py` | §S1.6.9, §5.8a |
| Shim leaks PATH or modifies shell rc | `tests/unit/test_shim_security.py` | §S1.9 |
| Recording mode ignored | `agentlens mode show`; check `$AGENTLENS_MODE` and `config.toml` | §S1.7.3 |
