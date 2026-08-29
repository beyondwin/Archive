# Operations

Related: [plan authoring](./plan-authoring.md), [recovery](./recovery.md),
[verification](./verification.md), [state root](./state-root-migration.md).

## Loop

1. `waygent run` (or `bun run waygent -- run …`)
2. `inspect` / `explain`
3. `resume`, `repair`, or `review` if blocked
4. `apply` only when readiness is `ready` and the source checkout is clean

`waygent.run_state.v2` decides resume and apply. Events, API, and console show
that evidence. They do not override it.

If PATH has no `waygent` binary, use `bun run waygent -- <command>`.

## Run root

Without `--root`:

| Platform | Default |
| --- | --- |
| macOS | `~/Library/Application Support/waygent/runs/` |
| Linux | `${XDG_DATA_HOME:-$HOME/.local/share}/waygent/runs/` |
| Windows | `%LOCALAPPDATA%/waygent/runs/` |
| other | `$TMPDIR/waygent-runs/` (stderr WARN) |

`waygent orphans` also scans the old `$TMPDIR/waygent-runs/` root and flags
`migration_suggested: true`. Copy steps: [state-root-migration.md](./state-root-migration.md).

## `waygent run`

Source checkout preflight always runs:

- `clean` — dispatch
- `dirty_unrelated` — dispatch, warning recorded
- `dirty_related` — block with `dirty_source_checkout`

If `--run <id>` already has evidence, Waygent stops with `run_id_already_exists`
instead of wiping the old run. Pick another id, omit `--run`, or delete the
directory after you inspect it.

Without `--run`, the id is `<plan-slug>_YYYYMMDD_HHMMSS`, with up to 16 numeric
suffix retries on collision.

`--plan` and `--spec` accept full paths or basenames under
`docs/superpowers/plans/` and `docs/superpowers/specs/`. Ambiguous basenames
fail with candidates. Typos fail; they are not treated as inline spec text.

From Codex, `waygent run` defaults to the Codex provider and `multi-agent`.
`waygent demo` is offline-only.

Useful flags:

| Flag | What it does |
| --- | --- |
| `--profile max-quality\|balanced\|cost-saver` | Packaged model + reasoning. Codex `max-quality` also turns on full preflight, spec slicing, builtin hooks, and method evidence. See [Codex best loop](./codex-best-loop.md). |
| `--plan-preflight off\|deterministic\|full` | Plan/spec audit. Fake/demo defaults to deterministic; live defaults to off during burn-in. |
| `--spec-slice off\|manifest` | Task packet spec context |
| `--budget-cap <USD> --budget-action warn\|pause\|off` | Cost policy. Pauses only at parent-process boundaries. |
| `--hook-config off\|builtin\|<path>` | Runtime hooks |
| `--main-model`, `--subagent-model`, `--plan-preflight`, `--spec-slice` | Override profile values |

File claims: `owned`, `shared_append`, `read_only`. `mode: edit` is an alias
for `owned`.

Red context-budget packets do not dispatch. Waygent records `context_missing`
and the shrink actions.

## Apply

`ready` means:

- completion audit passed
- each verified task has a checkpoint manifest
- patch bytes match digest and length
- dry-run passed
- combined apply evidence exists and matches
- no unrepaired drift

Empty checkpoint patches are valid no-ops (`no_op: true`). A patch that fails
`git apply --check` against current source is `needs_rebase`, not
`missing_checkpoint`.

`waygent apply --run <run_id>` is the only source mutation. It rechecks the
same readiness as `resume`, API, and console.

`waygent apply --require-evidence --run <run_id>` adds the method-evidence
overlay. Docs-only / config-only / generated-only tasks can use allowlisted
waivers. Checkpoints, completion, reconciliation, and clean checkout still
win.

If post-apply verification fails, `runway.apply_failed` includes
`post_apply_verification`. Start there.

Review-required recovered runs show `review_evidence_missing`:

```bash
bun run waygent -- review --run <run_id>
bun run waygent -- explain --run <run_id>
```

Apply only when readiness is `ready`.

## Intake

Strict parse first. If the doc is clearly meant to run but is not a
`waygent-task` block, Waygent normalizes it, writes
`artifacts/intake/normalized-plan.md` plus `recovery-report.json`, then
continues through the normal gates.

Destructive commands, path escapes, ambiguous plan/spec picks, and
source-mutating work with no verify command still stop as
`intake_decision_required`.

## Extra commands

| Command | Use |
| --- | --- |
| `decisions --last` | Decision register |
| `cost --last` | Usage ledger |
| `verify --run <id> [--task <id>]` | Rerun task verify in the existing worktree |
| `watch --last [--filter …]` | Filtered journal |
| `events --last` | Raw journal |
| `orphans [--stale]` | Invalid roots and stale worktrees. Delete one with `--delete <id> --yes`. |
| `run-chain --plan p1.md --plan p2.md` | Plan chain (still v2 state) |
| `scaffold-plan` / `lint-plan` / `lint-design` | Authoring. No run-state mutation. |

`waygent status` on a missing run dir (stale `latest` pointer) is
`status="failed"`, `last_event_type="evidence_cleared"`. That is not an
in-flight run.

Inspect and the console also show diagnostic maturity
(`dogfood_evidence`, `runtime_cost`, `provider_readiness`). Those views never
mark a run apply-ready.

Safe-wave parallelism never skips claims, dependencies, verify, or apply
gates. Raise `WAYGENT_WAVE_CONCURRENCY` only if the machine and account can
take it.

## Stop

- Ambiguous run selection
- Dirty source on apply
- Missing live provider CLI — use fake provider
- Failed verification — `explain` before `resume`
- Apply reports no verified checkpoint
