# Change Protocol

CPE is a load-bearing persistence boundary. Change it with focused evidence.

## Before Editing

1. Read SKILL.md, README.md, ARCHITECTURE.md, this file, and the document that
   owns the affected contract.
2. Inspect the current worktree and preserve unrelated changes.
3. Identify the narrowest one of six checks that can prove the behavior.
4. Add or change a failing deterministic test before implementation.

## RED

Run the focused test method or check and confirm it fails for the intended
reason. A syntax error, missing fixture, network dependency, or unrelated
failure is not RED evidence.

The six ownership areas are:

- check_lean_contracts.py: storage, launcher, worktree, strict values
- check_lean_mapping.py: snapshots, maps, coverage, publication
- check_lean_queue.py: task/review/autonomy/writer lifecycle
- check_lean_final.py: audits, integration, invalidation
- check_lean_recovery.py: replay, resume, refresh, legacy inspection
- check_lean_cli.py: command and export side effects

## GREEN

Implement the smallest durable change. Preserve these invariants:

- input and accepted artifact bytes are immutable and digest-bound;
- events are append-only, canonical, hash-chained, and fsynced;
- one event uniquely selects an accepted map publication;
- only one write-capable role owns the worktree;
- completed work is not redispatched;
- only six authority codes can wait for the user;
- final evidence names the exact revision;
- schema-3 inspection is read-only.

Do not add another active runtime module or eval file without an approved
architecture change. Prefer shared strict helpers over duplicated validators.

## Verification

Run the focused test, then:

    ./evals/run.sh
    python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
    bash -n evals/run.sh
    python3 scripts/cpe.py --help
    python3 scripts/cpe.py run --help
    python3 scripts/cpe.py export --help
    git diff --check

Review file inventory, active line count, and suite time when structure changes.
The suite must remain credential-free and below 60 seconds.

Update behavior and its owning kept document in the same change. Record the
reason, focused RED/GREEN evidence, full verification, and any new residual
risk in the handoff or commit.
