# KWS Codex Plan Executor

Release metadata remains at 2.1.1 until the Task 7 publication rewrite. The
active cutover runtime is a small local durability boundary for one
caller-supplied Superpowers execution contract. It keeps ordered document
snapshots, one reused isolated worktree, durable run facts, and a bounded
resume boundary. It is not a product orchestrator or a replacement for
Superpowers.

## Ownership And Installation

CPE maintains one execution environment and verifies submitted facts.
Superpowers decides what work and verification are correct.

The runner performs a direct Superpowers launch inside its one reused isolated
worktree. It supplies immutable submitted inputs and factual execution context;
Superpowers owns plan interpretation, implementation, tests, reviews, fixes,
subagents, commits, and engineering completion. Resume retains the same
worktree and immutable document bundle.

This tracked directory is the release source of truth. Install the source of
truth with the Codex and Claude Code symlinks in [`../README.md`](../README.md).
Do not copy the skill into tool directories and do not modify Superpowers
upstream.

## Requirements And Commands

- Python 3 standard library
- Git
- `codex` on `PATH`
- a Git workspace, one or more absolute readable document paths, and an
  explicitly selected supported Superpowers skill

```bash
python3 scripts/cpe.py run \
  --document /abs/design.md --document /abs/implementation.md \
  --workspace /abs/repository \
  --superpowers-skill subagent-driven-development
python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py inspect --run-id RUN_ID
```

The active CPE commands are exactly `run`, `resume`, and `inspect`.
`run` defaults to `workspace-write`.
`danger-full-access` is an explicit immutable run-creation opt-in.

With `danger-full-access`, writes outside the worktree are not fully observable
or reversible. The controller environment and prompt prohibit remote actions
and outside-worktree writes, while Git gates retain local evidence; those
controls are not a sandbox substitute.

## Execution And Resume Contract

Documents are byte-snapshotted before launch and passed to one selected
Superpowers controller in caller order. CPE does not assign roles, compile a
plan, or reconstruct workflow semantics.

Superpowers owns engineering completion; CPE only reports a mechanical
`handed_off`, `failed`, `blocked`, or `interrupted` status.
CPE has no public retry, recovery, or verification command.

`resume --run-id RUN_ID` uses the saved controller session first. Only an
explicit saved-session-unavailable result permits one fresh controller
fallback. `inspect` is read-only for both active format-5 and recognized legacy
state.

## Mechanical Handoff

A successful local handoff records branch, saved worktree, base and observed
HEAD, tracked and untracked status facts, controller session generation, and
`integration=not_observed`. It never claims merge, push, deployment,
publication, or product acceptance.

Run state lives under
`${CODEX_HOME:-~/.codex}/cpe-v3/runs/<run-id>/`; a linked worktree normally
lives under `${CODEX_HOME:-~/.codex}/worktrees/`.

## Verify

Add or update a focused deterministic eval before changing the public contract.
During implementation, run the exact affected tests and static checks. At the
final clean revision, after the externally owned integration review, run the
complete local gate once:

```bash
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
```

The deterministic evals are sequential, network-free, credential-free, and
model-free.

## Tracked Inventory

```text
README.md
SKILL.md
evals/check_architecture.py
evals/fake_codex.py
evals/run.sh
evals/test_cli.py
evals/test_controller.py
evals/test_git.py
evals/test_runtime.py
evals/test_state.py
scripts/cpe.py
scripts/cpe_runtime/__init__.py
scripts/cpe_runtime/controller.py
scripts/cpe_runtime/git.py
scripts/cpe_runtime/runtime.py
scripts/cpe_runtime/state.py
templates/terminal-envelope.schema.json
```
