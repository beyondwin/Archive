# KWS Codex Plan Executor

Version 3.0.0 is a small, local durability capsule for one execution contract.
Use direct Superpowers when bounded work fits one controller session. Use CPE
when that contract needs immutable inputs, one stable worktree, a durable run
ID, and Codex process or session continuity.

## Boundary

CPE accepts multiple documents through repeated `--document` options. It
preserves exact bytes and caller order, including repeated basenames and
unfamiliar structures. Inputs are opaque: there is no document review, role
assignment, plan queue, content linting, or cross-document approval in CPE.

One explicitly selected Superpowers skill owns interpretation, implementation,
testing, review, commits, and engineering completion. CPE owns only the
document bundle, local Git/worktree identity, controller transport, bounded
resume facts, and mechanical handoff.

New runs persist format-5 state under public contract 3.

This tracked directory is the release source of truth. Install the source of
truth with the Codex and Claude Code symlinks in [`../README.md`](../README.md).
Do not copy the skill into tool directories and do not modify Superpowers
upstream.

## Requirements

- Python 3 standard library
- Git
- `codex` on `PATH`
- POSIX advisory locks and process groups
- a Git workspace with repository-local or otherwise effective Git identity
- absolute readable document paths

## Commands

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
The required `--superpowers-skill` is immutable and accepts
`subagent-driven-development` or `executing-plans`.

## Resume And Local Handoff

`resume --run-id RUN_ID` performs same-session resume first, using the same
run, worktree, documents, sandbox, Git identity, and selected skill. Only an
explicit saved-session-unavailable outcome permits one fresh fallback. The
generation can advance from zero to one once and never to generation two.

Superpowers owns engineering completion; CPE only reports a mechanical
`handed_off`, `failed`, `blocked`, or `interrupted` status.
CPE has no public retry, recovery, or verification command.

A `handed_off` receipt records branch, saved worktree, base and observed
HEAD, tracked and untracked status facts, controller session generation, and
`integration=not_observed`. It never claims merge, push, deployment,
publication, or product acceptance.

Run state lives under
`${CODEX_HOME:-~/.codex}/cpe-v3/runs/<run-id>/`; a linked worktree normally
lives under `${CODEX_HOME:-~/.codex}/worktrees/`.

## Legacy And Security

`inspect` is read-only. A recognized older root returns `legacy_read_only`.
Continuation requires a distinct v3 run with explicit
`--adopt-worktree /abs/worktree --base COMMIT`; the older root remains
untouched and is never converted.

CPE is local-only and prohibits remote actions. It targets POSIX hosts. A
same-UID controller can still tamper with accessible files, and direct operator
changes are outside CPE's threat model. With explicit `danger-full-access`,
writes outside the worktree may be neither observable nor reversible.
Worktree checks and prompt restrictions are not a sandbox substitute.

## Offline And Opt-In Live Evidence

Offline verification is sequential, network-free, credential-free, and
model-free:

```bash
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
```

Real-provider canaries are separate and opt-in:

```bash
CPE_LIVE_CANARY=1 python3 evals/live_canary.py --scenario sdd-multi-document
CPE_LIVE_CANARY=1 python3 evals/live_canary.py --scenario session-loss
CPE_LIVE_CANARY=1 python3 evals/live_canary.py --scenario legacy-adoption
```

Without the exact environment opt-in, the harness exits before creating a
temporary repository or run. Successful roots and bounded receipts are
preserved for operator inspection. Offline gates do not invoke live canaries.

## Tracked Inventory

```text
README.md
SKILL.md
evals/check_architecture.py
evals/fake_codex.py
evals/live_canary.py
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
