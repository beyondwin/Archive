---
name: kws-codex-plan-executor
description: Use when one approved Superpowers execution contract needs a durable local Codex worktree and session-resume boundary.
metadata:
  version: "3.0.0"
  updated_at: "2026-07-25"
---

# KWS Codex Plan Executor

Use direct Superpowers in the current worktree when bounded work fits one
controller session. Use CPE when one execution contract needs a durable local
Codex run ID, immutable inputs, one worktree, and process or session continuity.
CPE is not a product orchestrator and does not replace Superpowers.

## One Contract, Opaque Inputs

CPE accepts multiple documents through repeated `--document` options. It
snapshots their exact bytes in caller order and passes them to one selected
Superpowers skill. The documents are opaque: CPE assigns no document roles,
creates no plan queue, and performs no document review. Unfamiliar structure,
extensions, or repeated basenames do not create CPE workflow meaning.

Superpowers owns document interpretation, implementation, testing, review,
commits, and engineering completion. CPE maintains only the immutable bundle,
Git/worktree identity, controller transport, bounded resume facts, and local
handoff.

New runs persist format-5 state under public contract 3.

## Run, Resume, Inspect

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
The selected `--superpowers-skill` is required and immutable; supported values
are `subagent-driven-development` and `executing-plans`.

Superpowers owns engineering completion; CPE only reports a mechanical
`handed_off`, `failed`, `blocked`, or `interrupted` status.
CPE has no public retry, recovery, or verification command.

## Continuity And Handoff

An explicit `resume` performs same-session resume against the unchanged run,
worktree, document bundle, sandbox, and selected skill. Only a recognized
saved-session-unavailable outcome permits one fresh fallback. Generation one
is final; CPE never creates a second fallback.

A successful local result is mechanical `handed_off`. Its receipt records
`integration=not_observed`; it does not claim product acceptance, integration,
merge, push, deployment, publication, or any other remote action.

`inspect` is read-only. Recognized old roots return `legacy_read_only` and stay
untouched. Continuing their work requires an explicit new v3 run with
`--adopt-worktree /abs/worktree --base COMMIT`; CPE never converts the old run.

## Safety Boundary

CPE is local-only and prohibits remote actions. It targets POSIX process groups
and advisory locks. The default sandbox limits writes, but neither it nor
prompts defend against a malicious same-UID process or direct operator
tampering. With explicit `danger-full-access`, writes outside the worktree may
be neither observable nor reversible. No prompt or Git check substitutes for
host isolation.

## Installation And Evidence

The tracked `skills/kws-codex-plan-executor/` directory is the source of truth.
Install it for Codex and Claude Code with symlinks from `skills/README.md`; do
not copy this skill into either tool directory and do not edit Superpowers
upstream.

Offline verification is deterministic, network-free, credential-free, and
model-free:

```bash
./evals/run.sh
```

Real-provider evidence is separate and opt-in. `evals/live_canary.py` refuses
before creating temporary artifacts unless `CPE_LIVE_CANARY=1`; run its three
named scenarios only when live access and preserved temporary evidence are
explicitly intended. Offline checks never invoke those scenarios.
