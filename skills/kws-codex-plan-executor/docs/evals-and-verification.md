# Evals And Verification

CPE 4 has one deterministic suite with exactly six checks. It uses temporary
Git repositories, a fake Codex child, the Python standard library, and no
network or credentials.

    ./evals/run.sh

The runner discovers every unittest method in the six files and schedules each
in an isolated subprocess through a bounded global pool. CPE_EVAL_JOBS may be
set from 1 through 8; the development default is 7. Output reports one PASS per
check and ends with 6 passed only after all methods succeed.
Each case starts in a new process group with a 12-second default deadline.
CPE_EVAL_CASE_TIMEOUT is bounded from 0.1 through 30 seconds and
CPE_EVAL_TERM_GRACE from 0.05 through 5 seconds. Timeout sends SIGTERM, waits
the grace interval, SIGKILLs a surviving process group, reaps the leader, and
reports sorted deterministic failures. An internal synthetic regression proves
that a descendant which ignores SIGTERM does not survive.

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
be investigated before increasing timeouts or concurrency; preserve semantic
coverage and keep the global pool bounded.

Use one focused method during RED/GREEN work, then run the full gate. Report the
exact commands, pass counts, real time, and any platform-specific variance.
