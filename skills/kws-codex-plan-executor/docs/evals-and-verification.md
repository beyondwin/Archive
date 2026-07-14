# Evals And Verification

CPE 4 has one deterministic suite with exactly six checks. It uses temporary
Git repositories, a fake Codex child, the Python standard library, and no
network or credentials.

    ./evals/run.sh

The runner invokes the six check files directly and sequentially. Each file
owns one shared temporary Git fixture and three or four high-signal scenarios.
Output reports one PASS per check and ends with 6 passed only after all 19
scenarios succeed. There is no discovery layer, worker pool, or per-case runner
policy; child timeout behavior belongs to the launcher contract itself.

## Check Ownership

| Check | Coverage |
| --- | --- |
| check_lean_contracts.py | private files, events, worktree, launcher, process groups |
| check_lean_mapping.py | snapshots, exact references, coverage, publication integrity |
| check_lean_queue.py | task/review/fix/investigation, strategies, writer exclusion |
| check_lean_final.py | document audits, final integration, retry and invalidation |
| check_lean_recovery.py | replay, interruption, refresh, tamper, schema-3 inspection |
| check_lean_cli.py | four commands, repeated flags, export side-effect boundary |

fake_codex.py is a deterministic child boundary. The five fixtures provide two
specs, two plans, and one optional program plan. No maintained inventory,
versioned pass baseline, provider call, or repository-wide product suite is
part of this skill's verification.

## Full Local Gate

    ./evals/run.sh
    python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
    bash -n evals/run.sh
    python3 scripts/cpe.py --help
    python3 scripts/cpe.py run --help
    python3 scripts/cpe.py export --help
    git diff --check

Expected CLI help exposes only run, resume, inspect, and export. The eval target
is under 60 real seconds on the development machine. A timing regression must
be investigated in the covering check rather than hidden with concurrency.

Use one focused method during RED/GREEN work, then run the full gate. Report the
exact commands, pass counts, real time, and any platform-specific variance.
