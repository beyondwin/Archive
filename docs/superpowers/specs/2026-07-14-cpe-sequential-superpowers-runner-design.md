# CPE Sequential Superpowers Runner Design

**Date:** 2026-07-14

**Status:** Approved design

**Repository:** `/Users/kws/source/private/Archive`

**Primary surface:** `skills/kws-codex-plan-executor/`

## 1. Summary

CPE becomes a small sequential runner for existing Superpowers implementation
plans. It accepts one or more specification documents and one or more
implementation-plan documents, snapshots those inputs, creates one isolated
worktree, and runs each plan in CLI order. Every plan is executed by one fresh
Codex session that uses the existing Superpowers workflow named by the plan.

CPE does not interpret requirements, split plans into tasks, dispatch its own
reviewers, judge code quality, or repeat product verification. Superpowers owns
TDD, implementation, task review, fixes, verification, and commits inside each
plan session. CPE owns only durable document order, the shared worktree,
process launch, plan-level checkpoints, bounded retry, resume, and inspection.

This replaces the current persistence platform with a plan-document loop. The
target is easy to understand from the public CLI and four small runtime files.

## 2. Goals

1. Execute multiple plan documents sequentially in one isolated worktree.
2. Make all specification snapshots available to every plan session without
   loading their contents into a persistent controller conversation.
3. Mark a plan complete only when its result names the current clean worktree
   `HEAD` and includes verification evidence.
4. Resume at the first incomplete plan without redispatching completed plans.
5. Bound automatic recovery so an unattended run cannot loop indefinitely.
6. Remove obsolete CPE runtime, documentation, tests, compatibility code, and
   ignored filesystem residue instead of retaining parallel implementations.
7. Keep the deterministic runner suite small, sequential, network-free, and
   fast.

## 3. Non-Goals

CPE will not:

- modify installed Superpowers skills;
- route ordinary requests between Superpowers, Waygent, or KWS executors;
- parse plan prose into a task graph;
- build document maps, requirement coverage, briefs, or authority graphs;
- dispatch separate mapper, reviewer, fixer, investigator, auditor, or final
  integrator roles;
- own product-level TDD, review, quality scoring, or final verification;
- support parallel plan execution or parallel writers;
- maintain legacy CPE run compatibility;
- export launcher prompts or handoff documents;
- merge, push, deploy, publish, or modify Waygent;
- update repository-root Graphify output as part of the CPE runtime;
- delete external run roots, worktrees, evidence branches, or user data.

## 4. Public Interface

The public CLI exposes only `run`, `resume`, and `inspect`.

```bash
python3 scripts/cpe.py run \
  --spec /abs/spec-a.md \
  --spec /abs/spec-b.md \
  --plan /abs/plan-01.md \
  --plan /abs/plan-02.md \
  --workspace /abs/repository

python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py resume --run-id RUN_ID --retry-failed
python3 scripts/cpe.py inspect --run-id RUN_ID
```

Rules:

- at least one `--plan` is required;
- `--spec` and `--plan` may repeat;
- plan flag order is execution order;
- every declared path is absolute, readable, regular, and UTF-8;
- duplicate input paths are rejected;
- the source workspace must be a Git repository without tracked changes;
- `run` creates one worktree from source `HEAD`;
- `resume` and `inspect` address only the new runner format;
- `inspect` is read-only;
- there is no `export` command.

Specification order records presentation order only. Every plan session
receives the immutable paths for all specification snapshots and its one
current plan snapshot. Requirement authority and conflicts remain matters for
the plan and Superpowers session, not CPE state.

## 5. Runtime Model

### 5.1 Run Creation

`run` performs the following steps once:

1. Validate the workspace and all input paths.
2. Create a private run directory under
   `CODEX_HOME/orchestrator/<run_id>/`.
3. Copy every input document into `inputs/` and record its SHA-256, size, role,
   and input order.
4. Create one branch and worktree under `CODEX_HOME/worktrees/<run_id>/` from
   source `HEAD`.
5. Write the initial plan list to `state.json` using atomic replacement.
6. Start the first plan.

Input hashes detect accidental input drift; CPE does not create an immutable
artifact index or content-addressed publication system.

### 5.2 Plan Execution

For each plan in order, CPE launches one fresh Codex process. The child prompt
contains only:

- the repository and worktree paths;
- the current immutable plan path;
- the ordered immutable specification paths;
- repository-instruction discovery requirements;
- the starting and current commits;
- the result-file path;
- the instruction to follow the plan's declared Superpowers workflow through
  implementation, review, fixes, verification, and commit;
- the exact completion contract.

The child may use whatever implementer and reviewer behavior the installed
Superpowers skill requires. CPE neither reproduces that behavior nor launches
additional quality roles around it.

Plans share the same worktree. A later plan starts from the accepted commit of
the preceding plan and can use all earlier changes.

### 5.3 Accepted Handoff

The single result schema contains:

```text
plan_id
status: completed | interrupted | blocked | failed
head_commit
verification: [{command, exit_code}]
summary
```

`head_commit` is required for every child-written result and names the observed
worktree `HEAD`. `verification` may be empty only when status is not
`completed`. If the process exits or times out without a valid result, the
launcher records a synthetic failed attempt containing the observed `HEAD`,
exit information, and log path; it does not fabricate child verification.

For `completed`, CPE requires:

- the result file parses and has exactly the allowed fields;
- `head_commit` equals worktree `HEAD`;
- `HEAD` descends from the plan's starting commit;
- the tracked and untracked worktree is clean;
- `verification` is non-empty and every exit code is zero;
- `summary` is present and bounded.

CPE validates this evidence but does not rerun the reported product commands.
The Superpowers session is the sole owner of product verification at that
revision.

### 5.4 Completion

After accepting a plan, CPE atomically records its starting commit, accepted
commit, result path, and completion time, then advances to the next plan. The
run becomes `completed` after the last plan handoff is accepted. There is no
additional final integrator or duplicate full-suite run.

If cross-plan integration work is required, the caller supplies an integration
plan as the final `--plan` input. CPE does not infer or synthesize one.

## 6. Durable State And Resume

The run directory contains only:

```text
<run_id>/
  state.json
  events.jsonl
  inputs/
  results/
  logs/
```

`state.json` is the source of truth and is written through a temporary sibling,
`fsync`, and atomic replacement. It records:

- `format_version: 1`;
- run ID and status;
- source repository, source commit, worktree, and branch;
- the ordered input-document records;
- the ordered plan records;
- current plan index;
- per-plan starting commit, accepted commit, attempt count, status, and result
  path.

`events.jsonl` is a bounded operational log for inspection, with one concise
record per run transition, plan transition, and attempt. Child stdout and
stderr remain in `logs/` and are never copied into the event stream. The event
stream is not a security ledger, is not hash-chained, and is not replayed to
derive state.

`resume` validates the run format, worktree identity, branch, current `HEAD`,
and the ancestry of accepted commits. It then starts the first plan not marked
complete. A completed plan is never relaunched.

An interrupted plan may already have commits. Its recovery prompt receives the
original starting commit, current `HEAD`, prior logs, and prior result if one
exists. The fresh Superpowers session inspects Git and its own progress
artifacts before continuing. CPE does not maintain task-level checkpoints.

## 7. Bounded Failure Policy

Each plan receives at most two automatic attempts: the initial attempt and one
recovery attempt using the existing worktree. The second non-completed result
marks the run `failed` and preserves state, logs, and commits.

`blocked` is terminal for the current invocation and is not automatically
retried. CPE does not create an authority queue or ask a sequence of questions.

An explicit `resume --retry-failed` grants exactly one additional attempt for
the failed current plan. Repeating that command is an explicit operator action,
not an unattended loop. No internal path can retry indefinitely.

Runner-integrity failures such as an invalid result, dirty successful handoff,
wrong commit, missing worktree, or broken ancestry fail immediately without an
automatic product retry.

## 8. Final Tracked File Set

The active skill contains exactly these tracked files:

```text
skills/kws-codex-plan-executor/
  SKILL.md
  README.md
  scripts/
    cpe.py
    cpe_runtime/
      __init__.py
      state.py
      launcher.py
      runner.py
  templates/
    plan-result-schema.json
  evals/
    run.sh
    fake_codex.py
    check_runner.py
    check_cli.py
```

`SKILL.md` is the agent-facing contract. `README.md` contains the complete user
guide, runtime layout, failure behavior, limitations, and change/verification
notes. A four-module runtime does not justify separate architecture, history,
reference, user-guide, risk, or protocol documents. Git history preserves the
retired designs and implementations.

## 9. Required Deletions

### 9.1 Skill Files

Delete every tracked skill file not listed in Section 8, including:

- `ARCHITECTURE.md` and `HISTORY.md`;
- the skill-local `docs/` and `references/` trees;
- `contracts.py`, `store.py`, `queue.py`, `worktree.py`, `legacy.py`, and
  `prompt_export.py`;
- the current child-result schema;
- the six `check_lean_*.py` files;
- the current deterministic fixtures.

Delete ignored residue physically from the skill directory, including
`.DS_Store`, `__pycache__/`, compiled Python files, and the retired
`scripts/cpe_state_validation/` tree. No cleanup may reach outside the CPE skill
or delete user-owned run evidence.

### 9.2 Root Design Artifacts

Once this design and its implementation plan supersede the prior CPE program:

- retain this design and its matching implementation plan as the current CPE
  design-only artifacts;
- delete older root `docs/superpowers/specs/` and
  `docs/superpowers/plans/` documents whose primary subject is a retired CPE
  schema, harness, release model, quality model, or hardening program;
- preserve Waygent, Claude executor, and other product documents even when they
  mention CPE context;
- remove or update active links whose targets are deleted;
- reduce the root `AGENTS.md` CPE description to the sequential runner boundary
  without changing Waygent ownership.

The implementation plan must inventory every proposed root-document deletion
before staging it. Filename matching alone is insufficient; mixed Waygent/CPE
documents are retained unless their active CPE claim must be corrected.

### 9.3 Retired Vocabulary

The active CPE skill and active repository instructions must not retain prose
for deleted behavior, including:

- CPE 4, schema 3, or schema 4;
- document mapper, program mapper, coverage graph, mapping generation, or
  content-addressed mapping bundle;
- authority queue or authority-code allowlists;
- reviewer, fixer, investigator, document auditor, or Program Final Integrator
  as CPE-owned roles;
- writer lease, integration invalidation, release proof, live matrix,
  compatibility scoring, or Graphify as a CPE runtime dependency;
- parallel workers, task-level CPE review, or repeated final verification.

Historical Git objects and unrelated Waygent or Claude documentation are not
rewritten merely because they contain a retired term.

## 10. Deterministic Verification

The eval surface contains two check files and one small fake Codex executable.
It covers only runner-owned behavior.

`check_runner.py` proves:

1. input snapshots and plan order are stable;
2. two plans execute sequentially in one worktree;
3. completed plans are not relaunched on resume;
4. an interrupted plan resumes from its current Git state;
5. exact-HEAD, ancestry, verification, and clean-handoff checks reject invalid
   success results;
6. automatic attempts stop at two and explicit retry grants one attempt.

`check_cli.py` proves:

1. only `run`, `resume`, and `inspect` are public;
2. repeated input flags preserve order and invalid argument combinations fail;
3. inspect is read-only and bounded;
4. an unsupported historical run format fails clearly without mutation.

`fake_codex.py` implements only completed, interrupted, blocked, failed,
wrong-commit, dirty-handoff, and resume scenarios. It does not emulate mapping,
review, audit, final integration, process groups, or product tests.

The complete gate is:

```bash
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py resume --help
python3 scripts/cpe.py inspect --help
git diff --check
```

Budgets are acceptance constraints:

- no more than 2,000 active runtime Python lines;
- no more than 600 eval and runner-script lines;
- deterministic suite target of 10 seconds and hard ceiling of 15 seconds on
  the development machine;
- exactly the tracked file inventory in Section 8;
- no parallel test runner and no network, credentials, or live model calls.

## 11. Cutover

The sequential runner replaces the current active CPE implementation in one
cutover. There is no dual path and no migration module. Existing run directories
remain untouched on disk, but the new CLI reports `unsupported_run_format` for
them. Historical source remains available through Git.

Implementation commits may be split into understandable steps, but the branch
is not complete until the old active files, stale root documents, dead links,
retired terminology, and ignored residue are removed and the final inventory
matches Section 8.

## 12. Accepted Trade-offs And Risks

- Recovery is plan-grained rather than task-grained. If a Superpowers progress
  artifact and Git history do not identify completed tasks within an interrupted
  plan, the recovery session may need to inspect more code before continuing.
- CPE trusts Superpowers verification evidence instead of rerunning product
  commands. Commit identity and cleanliness remain mechanically enforced, but
  product-quality judgment is deliberately not duplicated.
- All specs are offered to every plan session. A plan or its Superpowers worker
  decides which documents are relevant; CPE does not provide semantic slicing.
- A conflict among approved documents may make the child return `blocked`. CPE
  records that result but does not implement a separate decision workflow.
- There is no automatic garbage collector for external run roots or worktrees.
  Cleanup outside the repository remains an explicit operator action.

These trade-offs are intentional. The runner exists to preserve ordered plan
progress across interruptions, not to become a second implementation method or
quality platform around Superpowers.
