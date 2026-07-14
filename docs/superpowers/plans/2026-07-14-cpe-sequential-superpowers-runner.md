# CPE Sequential Superpowers Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. For this tightly coupled reduction, choose Inline Execution with `superpowers:executing-plans`; do not create a CPE run to modify CPE itself.

**Goal:** Replace the current CPE platform with a four-module sequential Superpowers plan runner and remove every obsolete CPE file, document, phrase, test, and ignored residue covered by the approved design.

**Architecture:** One private state file records immutable input snapshots and an ordered list of plans. One worktree is shared by fresh plan-level Codex processes; each process uses the existing Superpowers workflow to implement, review, verify, and commit its plan. CPE validates the result, exact `HEAD`, ancestry, verification evidence, and clean handoff, then advances or resumes without owning task mapping or quality roles.

**Tech Stack:** Python 3 standard library, Git worktrees, Codex CLI structured output, JSON/JSONL, Bash, `unittest`, temporary Git repositories.

## Global Constraints

- Approved design: `docs/superpowers/specs/2026-07-14-cpe-sequential-superpowers-runner-design.md`.
- Do not modify installed Superpowers skills, Waygent runtime, Claude executor behavior, external run roots, external worktrees, or evidence branches.
- Plan flag order is execution order. All specification snapshots are offered to each current plan process.
- One worktree and one writer are active at a time. There is no parallel runner or test pool.
- Superpowers owns implementation, review, fixes, commits, and product verification inside each plan process. CPE must not duplicate them.
- Automatic execution is limited to the initial attempt plus one recovery attempt per plan. Only explicit `resume --retry-failed` grants one more attempt.
- The public CLI contains only `run`, `resume`, and `inspect`.
- The final tracked skill inventory must exactly match the twelve files listed in Task 2.
- Active runtime Python must be at most 2,000 lines. Eval Python plus `run.sh` must be at most 600 lines.
- The deterministic suite must be sequential, credential-free, network-free, target 10 seconds, and remain below 15 real seconds on the development machine.
- Use `apply_patch` for tracked edits and deletions. Preserve unrelated user changes.
- Run focused tests during RED/GREEN. Run the complete deterministic gate once at the final revision.
- Remove the repository's retired generated-map integration and do not recreate it.

---

## Task 1: Build The Plan-Level State, Launcher, And Sequential Runner

**Files:**

- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py`
- Rewrite: `skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py`
- Create: `skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py`
- Rewrite: `skills/kws-codex-plan-executor/evals/fake_codex.py`
- Create: `skills/kws-codex-plan-executor/evals/check_runner.py`
- Create: `skills/kws-codex-plan-executor/templates/plan-result-schema.json`
- Reference: `docs/superpowers/specs/2026-07-14-cpe-sequential-superpowers-runner-design.md`

**Interfaces:**

- `StateStore.create()` validates and snapshots ordered specs and plans before a child starts.
- `StateStore.open()` accepts only `format_version: 1` and never mutates unsupported formats.
- `StateStore.save()` uses a temporary sibling, file and directory `fsync`, and atomic replacement.
- `StateStore.append_event()` writes one concise JSONL record per run transition, plan transition, and attempt.
- `CodexLauncher.launch()` executes one fresh Codex process with one current plan, all spec paths, one result schema, and bounded stdout/stderr logs.
- `SequentialRunner.run()` creates one worktree and executes plan records in order.
- `SequentialRunner.resume()` verifies recorded Git identity and advances from the first incomplete plan.
- `SequentialRunner.inspect()` returns a bounded read-only summary.

The state JSON shape is fixed:

```json
{
  "format_version": 1,
  "run_id": "cpe-example",
  "status": "running",
  "source_repository": "/abs/repository",
  "source_commit": "40-hex-sha",
  "worktree": "/abs/codex-home/worktrees/cpe-example",
  "branch": "codex/cpe-example",
  "current_plan_index": 0,
  "inputs": [
    {
      "document_id": "spec-01",
      "role": "spec",
      "source_path": "/abs/spec.md",
      "snapshot_path": "/abs/run/inputs/spec-01.md",
      "sha256": "64-hex-digest",
      "byte_length": 100,
      "input_order": 0
    },
    {
      "document_id": "plan-01",
      "role": "plan",
      "source_path": "/abs/plan.md",
      "snapshot_path": "/abs/run/inputs/plan-01.md",
      "sha256": "64-hex-digest",
      "byte_length": 100,
      "input_order": 0
    }
  ],
  "plans": [
    {
      "plan_id": "plan-01",
      "status": "pending",
      "starting_commit": null,
      "accepted_commit": null,
      "attempt_count": 0,
      "result_path": null
    }
  ]
}
```

The plan result schema is fixed:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["plan_id", "status", "head_commit", "verification", "summary"],
  "properties": {
    "plan_id": {"type": "string", "minLength": 1},
    "status": {
      "type": "string",
      "enum": ["completed", "interrupted", "blocked", "failed"]
    },
    "head_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
    "verification": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["command", "exit_code"],
        "properties": {
          "command": {"type": "string", "minLength": 1},
          "exit_code": {"type": "integer"}
        }
      }
    },
    "summary": {"type": "string", "minLength": 1, "maxLength": 2000}
  }
}
```

- [ ] **Step 1: Write the complete runner contract eval first**

Create `check_runner.py` with one shared temporary Git repository and these six `unittest` methods:

```text
test_snapshots_preserve_spec_and_plan_order
test_two_plans_execute_sequentially_in_one_worktree
test_resume_skips_completed_plan_and_continues_current_git_state
test_completed_requires_exact_head_ancestry_cleanliness_and_verification
test_initial_plus_one_recovery_attempt_is_the_automatic_limit
test_explicit_retry_failed_grants_exactly_one_attempt
```

The fake Codex executable supports only these scenarios:

```text
completed
interrupted
blocked
failed
wrong_commit
dirty_handoff
resume_completed
```

Each completed fake plan writes and commits `plan-<number>.txt`, writes the exact result JSON, and appends its plan ID to a test-owned invocation log. Recovery uses the existing worktree and creates no second worktree.

- [ ] **Step 2: Run RED and confirm the missing sequential APIs are the only failure**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_runner.py
```

Expected: import failure for `cpe_runtime.state` or `cpe_runtime.runner`. A fixture, Git, syntax, or environment failure is not accepted RED evidence.

- [ ] **Step 3: Implement the minimal atomic state store**

Implement only the state fields and operations named above. Reject duplicate paths, non-UTF-8 bytes, non-regular files, unknown statuses, path traversal, unsupported formats, missing snapshots, and state paths outside the private run root. Use permissions `0700` for private directories and `0600` for private files.

Do not implement immutable artifact indexing, hash-chained replay, map generations, authority records, task graphs, or compatibility adapters.

- [ ] **Step 4: Implement the bounded child launcher**

The launcher command has this exact policy shape:

```text
codex exec
--ignore-user-config
--json
--sandbox workspace-write
-C <worktree>
--add-dir <results-directory>
--output-schema <plan-result-schema.json>
--output-last-message <attempt-result.json>
-
```

The prompt names one current plan snapshot, every spec snapshot, repository-instruction discovery, starting/current commits, result path, and the completion contract. It instructs the child to use the plan-declared Superpowers workflow and return only after implementation, review, fixes, verification, and commit are complete.

Use `subprocess.run()` with `timeout=3600` and `start_new_session=True`; expose
`timeout_seconds` as a constructor argument so deterministic tests can select a
shorter value. On timeout, perform one best-effort termination of the launched
process. Do not add descendant enumeration, platform-specific process tables,
process-group polling, signal escalation trees, environment-policy matrices,
model selection, or pricing logic.

Preserve inherited `PATH` and `CODEX_HOME`. Remove only common provider secrets from the child environment: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, and `GITHUB_TOKEN`.

- [ ] **Step 5: Implement the sequential runner and handoff validation**

Create one branch `codex/<run_id>` and one worktree. For each plan:

1. Record `starting_commit` and increment `attempt_count` before launch.
2. Launch one fresh child.
3. For `completed`, require matching plan ID, exact worktree `HEAD`, descendant ancestry, clean tracked and untracked status, and at least one zero-exit verification record.
4. Atomically mark the plan complete and advance the index.
5. For `interrupted` or ordinary `failed`, allow one automatic recovery attempt.
6. After the second non-completed result, mark the run failed.
7. For `blocked`, stop without automatic retry.
8. For invalid output, wrong commit, dirty success, missing worktree, or broken ancestry, fail immediately as runner integrity.

When a process yields no valid result, record a synthetic failed attempt containing the observed `HEAD`, process exit or timeout, and log path. Never fabricate verification.

- [ ] **Step 6: Run GREEN and focused hygiene**

```bash
python3 evals/check_runner.py
python3 -m py_compile \
  scripts/cpe_runtime/state.py \
  scripts/cpe_runtime/launcher.py \
  scripts/cpe_runtime/runner.py \
  evals/fake_codex.py \
  evals/check_runner.py
git diff --check
```

Expected: six runner tests pass, compilation succeeds, and patch hygiene is clean.

- [ ] **Step 7: Commit the runner core**

```bash
git add \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_runner.py \
  skills/kws-codex-plan-executor/templates/plan-result-schema.json
git commit -m "refactor(cpe): add sequential Superpowers runner"
```

---

## Task 2: Cut Over The CLI And Reduce The Skill To Twelve Files

**Files:**

- Rewrite: `skills/kws-codex-plan-executor/scripts/cpe.py`
- Rewrite: `skills/kws-codex-plan-executor/scripts/cpe_runtime/__init__.py`
- Rewrite: `skills/kws-codex-plan-executor/evals/run.sh`
- Create: `skills/kws-codex-plan-executor/evals/check_cli.py`
- Rewrite: `skills/kws-codex-plan-executor/SKILL.md`
- Rewrite: `skills/kws-codex-plan-executor/README.md`
- Delete: `skills/kws-codex-plan-executor/ARCHITECTURE.md`
- Delete: `skills/kws-codex-plan-executor/HISTORY.md`
- Delete: `skills/kws-codex-plan-executor/docs/`
- Delete: `skills/kws-codex-plan-executor/references/`
- Delete: `skills/kws-codex-plan-executor/evals/check_lean_cli.py`
- Delete: `skills/kws-codex-plan-executor/evals/check_lean_contracts.py`
- Delete: `skills/kws-codex-plan-executor/evals/check_lean_final.py`
- Delete: `skills/kws-codex-plan-executor/evals/check_lean_mapping.py`
- Delete: `skills/kws-codex-plan-executor/evals/check_lean_queue.py`
- Delete: `skills/kws-codex-plan-executor/evals/check_lean_recovery.py`
- Delete: `skills/kws-codex-plan-executor/evals/lean-fixtures/`
- Delete: `skills/kws-codex-plan-executor/scripts/cpe_runtime/contracts.py`
- Delete: `skills/kws-codex-plan-executor/scripts/cpe_runtime/legacy.py`
- Delete: `skills/kws-codex-plan-executor/scripts/cpe_runtime/prompt_export.py`
- Delete: `skills/kws-codex-plan-executor/scripts/cpe_runtime/queue.py`
- Delete: `skills/kws-codex-plan-executor/scripts/cpe_runtime/store.py`
- Delete: `skills/kws-codex-plan-executor/scripts/cpe_runtime/worktree.py`
- Delete: `skills/kws-codex-plan-executor/templates/child-result-schema.json`

**Interfaces:**

- `cpe.py run` delegates to `SequentialRunner.run()` and prints one JSON result.
- `cpe.py resume` delegates to `SequentialRunner.resume()`; `--retry-failed` is invalid unless the current run status is failed.
- `cpe.py inspect` delegates to `SequentialRunner.inspect()` and performs no write.
- Public exit codes are `0` completed/successful inspection, `1` failed or invalid, `2` blocked, and `3` interrupted.

- [ ] **Step 1: Write the public CLI eval and run RED**

Create `check_cli.py` with these four tests:

```text
test_help_exposes_only_run_resume_and_inspect
test_run_requires_absolute_workspace_and_at_least_one_plan
test_repeated_spec_and_plan_flags_preserve_order
test_inspect_is_read_only_and_historical_format_is_rejected
```

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_cli.py
```

Expected: failures because the current CLI still exposes the retired command and format behavior.

- [ ] **Step 2: Replace the public CLI and runner script**

Implement only `run`, `resume`, and `inspect`. Every command prints one bounded JSON object. Do not retain aliases, hidden legacy flags, export modes, program-plan handling, authority answers, input refresh, or compatibility output.

Replace `evals/run.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

python3 "$(dirname "$0")/check_runner.py"
echo "PASS check_runner.py"
python3 "$(dirname "$0")/check_cli.py"
echo "PASS check_cli.py"
echo "2 passed"
```

- [ ] **Step 3: Rewrite the two retained skill documents**

`SKILL.md` contains only:

- when to use the sequential runner;
- the three commands;
- plan order and shared-worktree behavior;
- Superpowers ownership of implementation/review/verification;
- attempt limit and resume behavior;
- the small deterministic gate;
- a direct pointer to `README.md`.

`README.md` contains only:

- requirements;
- command examples;
- state/result layout;
- completion and failure meanings;
- plan-level recovery limitation;
- exact verification commands;
- the twelve-file inventory.

Do not describe retired behavior even as a historical comparison. Git history is the history document.

- [ ] **Step 4: Delete every superseded tracked skill file**

Use `apply_patch` to remove every tracked path listed under **Delete**. After deletion, the tracked inventory must be exactly:

```text
skills/kws-codex-plan-executor/README.md
skills/kws-codex-plan-executor/SKILL.md
skills/kws-codex-plan-executor/evals/check_cli.py
skills/kws-codex-plan-executor/evals/check_runner.py
skills/kws-codex-plan-executor/evals/fake_codex.py
skills/kws-codex-plan-executor/evals/run.sh
skills/kws-codex-plan-executor/scripts/cpe.py
skills/kws-codex-plan-executor/scripts/cpe_runtime/__init__.py
skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py
skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py
skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py
skills/kws-codex-plan-executor/templates/plan-result-schema.json
```

- [ ] **Step 5: Remove ignored residue inside the skill only**

Remove these known ignored paths after confirming each is inside
`skills/kws-codex-plan-executor/`:

```text
skills/kws-codex-plan-executor/.DS_Store
skills/kws-codex-plan-executor/evals/.DS_Store
skills/kws-codex-plan-executor/evals/__pycache__/
skills/kws-codex-plan-executor/scripts/__pycache__/
skills/kws-codex-plan-executor/scripts/cpe_runtime/__pycache__/
skills/kws-codex-plan-executor/scripts/cpe_state_validation/
```

Then prove no ignored residue remains:

```bash
git status --ignored --short -- skills/kws-codex-plan-executor
```

Expected: no output.

- [ ] **Step 6: Run the focused cutover gate and inventory assertion**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py resume --help
python3 scripts/cpe.py inspect --help
git diff --check
```

Expected: two checks pass, only three public commands appear, and no retired import or path remains.

Verify the inventory with:

```bash
python3 -c 'import subprocess; expected = {
"skills/kws-codex-plan-executor/README.md",
"skills/kws-codex-plan-executor/SKILL.md",
"skills/kws-codex-plan-executor/evals/check_cli.py",
"skills/kws-codex-plan-executor/evals/check_runner.py",
"skills/kws-codex-plan-executor/evals/fake_codex.py",
"skills/kws-codex-plan-executor/evals/run.sh",
"skills/kws-codex-plan-executor/scripts/cpe.py",
"skills/kws-codex-plan-executor/scripts/cpe_runtime/__init__.py",
"skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py",
"skills/kws-codex-plan-executor/scripts/cpe_runtime/runner.py",
"skills/kws-codex-plan-executor/scripts/cpe_runtime/state.py",
"skills/kws-codex-plan-executor/templates/plan-result-schema.json",
}; actual = set(subprocess.check_output(["git", "ls-files", "skills/kws-codex-plan-executor"], text=True).splitlines()); assert actual == expected, (sorted(expected - actual), sorted(actual - expected))'
```

- [ ] **Step 7: Commit the single-path cutover**

```bash
git add -A -- skills/kws-codex-plan-executor
git diff --cached --check
git commit -m "refactor(cpe): cut over to sequential plan execution"
```

---

## Task 3: Delete Retired Root CPE Artifacts And Close The Reduction

**Files:**

- Modify: `AGENTS.md`
- Keep: `docs/superpowers/specs/2026-07-14-cpe-sequential-superpowers-runner-design.md`
- Keep: `docs/superpowers/plans/2026-07-14-cpe-sequential-superpowers-runner.md`
- Keep: `docs/superpowers/specs/2026-06-01-waygent-cpe-comparison-benchmark-design.md`
- Keep: `docs/superpowers/plans/2026-06-01-waygent-cpe-comparison-benchmark.md`
- Delete: the 52 CPE-only root artifacts listed in Step 1
- Delete: `.graphifyignore`, `graphify-out/`

**Interfaces:**

- Root `AGENTS.md` describes the Codex executor as a small sequential wrapper and retains Waygent as the active product runtime.
- The current spec and plan are the only active CPE design-only artifacts.
- The two Waygent comparison documents remain historical mixed-product evidence.
- No link outside deleted root artifacts points at a removed CPE document.

- [ ] **Step 1: Delete this exact root-document inventory**

Delete these 28 plans:

```text
docs/superpowers/plans/2026-05-31-cpe-execution-hardening.md
docs/superpowers/plans/2026-05-31-cpe-reliability-improvement-loop.md
docs/superpowers/plans/2026-06-07-cpe-subagent-quality-improvement-implementation.md
docs/superpowers/plans/2026-06-18-cpe-adaptive-delegation-implementation.md
docs/superpowers/plans/2026-06-18-cpe-eval-baseline-update.md
docs/superpowers/plans/2026-06-18-cpe-run-readiness-quality-audit.md
docs/superpowers/plans/2026-06-23-cpe-repair-runs.md
docs/superpowers/plans/2026-06-23-cpe-superpowers-compatibility.md
docs/superpowers/plans/2026-06-25-cpe-completion-quality-normalization.md
docs/superpowers/plans/2026-06-25-cpe-run-quality-debt-surfacing.md
docs/superpowers/plans/2026-06-25-superpowers-cpe-task-packet-quality-audit.md
docs/superpowers/plans/2026-07-01-cpe-run-quality-cleanup-umbrella.md
docs/superpowers/plans/2026-07-02-cpe-human-readable-harness.md
docs/superpowers/plans/2026-07-03-cpe-current-superpowers-plan-gate.md
docs/superpowers/plans/2026-07-03-cpe-release-contract.md
docs/superpowers/plans/2026-07-04-cpe-operational-quality-umbrella.md
docs/superpowers/plans/2026-07-05-cpe-execution-boundary-and-context-optimization.md
docs/superpowers/plans/2026-07-05-cpe-operational-quality-signal.md
docs/superpowers/plans/2026-07-10-cpe-v3-integrity-closure.md
docs/superpowers/plans/2026-07-10-cpe-v3-quality-model-routing.md
docs/superpowers/plans/2026-07-11-cpe-v3-subscription-live-matrix.md
docs/superpowers/plans/2026-07-12-cpe-v4-autonomous-efficient-executor.md
docs/superpowers/plans/2026-07-13-cpe-superpowers-lean-runner.md
docs/superpowers/plans/2026-07-13-cpe-vnext-partial-implementation-handoff.md
docs/superpowers/plans/2026-07-13-cpe-vnext-plan-1-release-trust-foundation.md
docs/superpowers/plans/2026-07-13-cpe-vnext-plan-2-runtime-multiplan-simplification.md
docs/superpowers/plans/2026-07-13-cpe-vnext-plan-3-quality-deduplication-measurement.md
docs/superpowers/plans/2026-07-13-cpe-vnext-workflow-optimization-program.md
```

Delete these 24 specs:

```text
docs/superpowers/specs/2026-05-31-cpe-execution-hardening-design.md
docs/superpowers/specs/2026-05-31-cpe-reliability-improvement-loop-design.md
docs/superpowers/specs/2026-06-07-cpe-subagent-quality-improvement-design.md
docs/superpowers/specs/2026-06-18-cpe-adaptive-delegation-design.md
docs/superpowers/specs/2026-06-18-cpe-eval-baseline-update-design.md
docs/superpowers/specs/2026-06-18-cpe-run-readiness-quality-design.md
docs/superpowers/specs/2026-06-23-cpe-repair-runs-design.md
docs/superpowers/specs/2026-06-23-cpe-superpowers-compatibility-design.md
docs/superpowers/specs/2026-06-25-cpe-completion-quality-normalization-design.md
docs/superpowers/specs/2026-06-25-cpe-run-quality-debt-surfacing-design.md
docs/superpowers/specs/2026-06-25-superpowers-cpe-task-packet-quality-audit-design.md
docs/superpowers/specs/2026-07-01-cpe-run-quality-cleanup-umbrella-design.md
docs/superpowers/specs/2026-07-02-cpe-human-readable-harness-design.md
docs/superpowers/specs/2026-07-03-cpe-current-superpowers-plan-gate-design.md
docs/superpowers/specs/2026-07-03-cpe-release-contract-design.md
docs/superpowers/specs/2026-07-04-cpe-operational-quality-umbrella-design.md
docs/superpowers/specs/2026-07-05-cpe-execution-boundary-and-context-optimization-design.md
docs/superpowers/specs/2026-07-05-cpe-operational-quality-signal-design.md
docs/superpowers/specs/2026-07-10-cpe-v3-integrity-closure-design.md
docs/superpowers/specs/2026-07-10-cpe-v3-quality-model-routing-design.md
docs/superpowers/specs/2026-07-11-cpe-v3-subscription-live-matrix-design.md
docs/superpowers/specs/2026-07-12-cpe-v4-autonomous-efficient-executor-design.md
docs/superpowers/specs/2026-07-13-cpe-superpowers-lean-runner-design.md
docs/superpowers/specs/2026-07-13-cpe-vnext-quality-first-workflow-optimization-design.md
```

Do not delete either `2026-06-01-waygent-cpe-comparison-benchmark` document. They are mixed Waygent comparison evidence, not an active CPE implementation contract.

- [ ] **Step 2: Reduce the active repository instruction text**

Update only the CPE paragraph in `AGENTS.md` so it states:

```text
The Codex executor is a small sequential wrapper for approved Superpowers plan
documents. It snapshots ordered specs and plans, runs one plan at a time in one
isolated worktree, and resumes at the first incomplete plan. Superpowers owns
implementation, review, fixes, verification, and commits. The executor is not
a Waygent product dependency and does not own task mapping or quality policy.
```

Preserve the existing Waygent ownership, namespace, and verification-command guidance.

- [ ] **Step 3: Prove active links and vocabulary are clean**

Search active surfaces, excluding the current design/plan and preserved mixed comparison documents:

```bash
rg -n -i \
  'CPE 4|schema 3|schema 4|document mapper|program mapper|coverage graph|mapping generation|authority queue|Program Final Integrator|writer lease|integration invalidation|compatibility scoring|live matrix' \
  AGENTS.md skills/kws-codex-plan-executor
```

Expected: no output.

```bash
rg -n \
  'docs/superpowers/(specs|plans)/[^ )`]*cpe[^ )`]*' \
  --glob '!docs/superpowers/specs/**' \
  --glob '!docs/superpowers/plans/**' \
  .
```

Expected: no references to a deleted root CPE document.

- [ ] **Step 4: Remove the retired generated-map integration**

Delete `.graphifyignore`, the tracked generated-map output directory, active
repository instructions, product special-casing, fixtures, and current user
documentation for the retired integration. Do not regenerate the output.

- [ ] **Step 5: Run the complete final gate exactly once**

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
/usr/bin/time -p ./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py resume --help
python3 scripts/cpe.py inspect --help
cd /Users/kws/source/private/Archive
git diff --check
```

Expected:

- `2 passed`;
- real time below 15 seconds;
- Python compilation and Bash syntax pass;
- only `run`, `resume`, and `inspect` are public;
- patch hygiene passes.

Measure the hard budgets:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
runtime_lines=$(wc -l scripts/cpe.py scripts/cpe_runtime/*.py | tail -1 | awk '{print $1}')
eval_lines=$(wc -l evals/*.py evals/run.sh | tail -1 | awk '{print $1}')
test "$runtime_lines" -le 2000
test "$eval_lines" -le 600
printf 'runtime_lines=%s eval_lines=%s\n' "$runtime_lines" "$eval_lines"
```

Re-run the twelve-file inventory assertion from Task 2 after all documentation changes. Do not weaken a functional check merely to meet a line budget; simplify the implementation instead.

- [ ] **Step 6: Stage the root cleanup and verify the staged patch**

```bash
cd /Users/kws/source/private/Archive
git add -A -- AGENTS.md README.md .gitignore .graphifyignore graphify-out docs skills/waygent packages
git diff --cached --check
git status --short
```

Confirm that the staged deletion list is exactly the 52 files in Step 1 and that the current design and plan remain tracked.

- [ ] **Step 7: Commit the completed reduction**

```bash
git commit -m "docs(cpe): remove superseded executor artifacts"
git status --short --branch --untracked-files=all
```

Expected: the commit succeeds and the worktree is clean. Do not merge or push unless the user separately requests it after implementation verification.

## Plan Self-Review Checklist

- The approved spec's input, sequential execution, shared worktree, handoff, resume, retry, cleanup, and size/time requirements map to Tasks 1-3.
- The plan has three reviewable milestones rather than one task per module or role.
- The old skill deletion inventory and the 52 root-document deletions are explicit.
- The two mixed Waygent comparison documents and all non-CPE product docs are preserved.
- Product review and verification are not reimplemented by CPE.
- There is one final full gate and no generated-map integration.
- No implementation step modifies installed Superpowers, Waygent, Claude executor behavior, external run data, or evidence branches.
