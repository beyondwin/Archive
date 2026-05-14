# v2.11 — Method Audit + Codex-Inspired Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap between MAE's *required* sub-agent disciplines (TDD, review, verification-before-completion) and its actual *validation* of those disciplines, while pulling in three smaller hardening items the sibling `kws-codex-plan-executor` skill identified in commit `1d10f13`. After this change, an MAE run cannot reach `COMPLETE` for a task that claims executable work without recording verifiable RED/GREEN evidence, review findings, and a verification command list. Three secondary items reduce ENV_BLOCKER escalation noise (triage categories, local-env preflight) and improve parallel-wave correctness when external resources collide (`resource_key`).

**Architecture:** Keep MAE skill-local and file-based. Extend the existing state schema (`state.tasks.task_N.method_audit`), shared learning-log helper (`scripts/append_learning_event.py`), and worktree hook system. Add one new validator script and one new preflight section to `SKILL.md`. No new infrastructure, no daemons, no network dependencies.

**Tech Stack:** Python 3 standard library, bash hook scripts, JSON state files, JSONL learning logs, Markdown references.

---

## Source Basis

This plan combines two inputs:

1. **Sibling skill commit `1d10f13`** — `docs: plan log-driven executor hardening` in `skills/kws-codex-plan-executor/`. Five learning-log run reviews surfaced cross-cutting executor weaknesses, of which five apply to MAE with minor adaptation. See `docs/experiments/2026-05-14-log-driven-executor-hardening/PLAN.md` in `kws-codex-plan-executor` for the upstream findings.
2. **MAE current state (v2.10.1)** — `SKILL.md` Guardrails already mandate `superpowers:test-driven-development`, `superpowers:receiving-code-review`, and `superpowers:verification-before-completion` for Implementer/Reviewer/cleanup paths, but the disciplines are not introspectable: a task can finish `COMPLETE` with no proof TDD ever ran.

## Problems To Solve

1. **Method discipline is required but unverified.** Implementer prompt at `references/implementer-prompt.md:11–22` *invokes* TDD/debugging/verification skills and *asks* for RED/GREEN evidence, but Combined Reviewer's PASS and Verifier's PASS both clear a task even when the Implementer skipped TDD and silently shipped code without a failing test first. There is no `method_audit` field on `state.tasks.task_N` and no validator that fails the run if required methods are missing.
2. **ENV_BLOCKER triage is too generic.** `references/escalation-playbook.md:47–63` lists 4 generic steps (test run, missing dep, broken path, missing service) and does not distinguish Docker container OOM from real compile failure, Gradle daemon disappearance from metaspace exhaustion, or Node heap OOM from a hard test failure. Generic triage causes false-negative ENV_BLOCKER classification (treats env issue as code defect) and burns Implementer retries.
3. **Learning-log `index.jsonl` outcome can lie.** The shared helper `scripts/append_learning_event.py` (used by both `kws-codex-plan-executor` and MAE per `references/learning-log.md`) writes `outcome=unknown` to `index.jsonl` at run start and does not rewrite the index entry when `close-run` writes `final.json`. Downstream analysis that reads only `index.jsonl` reports closed-success runs as `unknown`. Zero-event success runs (notable-boundary-only logging meeting routine success) are also reported as warnings even though the helper did not fail.
4. **Baseline test failures attributable to missing local config look like ENV_BLOCKERS.** When MAE creates a worktree via Phase 0 Step 2, it inherits the parent repo's tracked files but not gitignored-local-config files (e.g., `local.properties`, `.env`, `*.local.json`). Phase 0 Step 5's baseline run can fail before any task touches code, producing a `baseline.failing > 0` signal that Verifiers then interpret as a regression budget. There is no preflight signal that a *.example/*.template counterpart is unfilled.
5. **Parallel Sub-Flow (P2) cannot model external-resource contention.** SKILL.md Phase 0 Step 6 partitions wave tasks by file-disjointness and respects `serial: true` plan annotation, but cannot detect that two file-disjoint tasks both run `gradle test` against the same project's `build/test-results/` output directory, or that two tasks both bind to the same DB port. Result: parallel groups with hidden resource conflicts produce flaky Verifier failures.

## Non-Goals

- Do not replace the existing shared learning-log helper or its sharded layout.
- Do not auto-copy gitignored local-config files. Detection only; the user decides.
- Do not make all verification serial — only commands with declared `resource_key` collisions serialize.
- Do not mark a method as `applied` just because the sub-agent *invoked* the skill. Evidence references (RED command, GREEN command, finding count, verification command list) are required.
- Do not penalize docs-only, config-only, or generated-only tasks for missing TDD evidence — they explicitly `waive` with a reason.
- Do not change Plan 2 / multi-plan invocation behavior. This plan operates on the active task tree per `state.active_plan` and is plan-transparent.
- Do not introduce a database, daemon, UI dashboard, or external dependency.

## File Map

| File | Responsibility |
|------|----------------|
| `SKILL.md` | Phase 0 Step 4.7 (local-env preflight), Step 6 (`resource_key` in partition), Phase 1 Step 4 (populate `method_audit`), Phase 2 Step 1.5 (validate `method_audit`), Guardrails updates. |
| `references/implementer-prompt.md` | Add structured `METHOD_AUDIT:` output block. Require explicit `RED:` / `GREEN:` lines when TDD applies. |
| `references/reviewer-prompt.md` | Add structured `REVIEW_FINDINGS:` block (count + optional no-findings residual-risk statement). |
| `references/verifier-prompt.md` | No prompt change; result JSON already lists commands. Document that the orchestrator harvests `commands_run` as verification evidence. |
| `references/escalation-playbook.md` | Expand ENV_BLOCKER section: Docker OOM, Gradle daemon disappearance (compile vs OOM vs metaspace vs daemon-crash), Node heap, generic memory triage. Per-category root-cause tag for learning log. |
| `references/plan-reviewer-prompt.md` | Audit `resource_key` collisions within a wave; emit WARN when two tasks share a key. |
| `references/learning-log.md` | Source-of-truth rules: `final.json` wins for terminal outcome, `meta.json` mirrors, `index.jsonl` entries are start records unless explicitly rewritten. Document zero-event success as normal. |
| `references/common-mistakes.md` | New entries: missing local-env counterpart, hidden gradle test output collision, TDD-skipped-silently signature. |
| `references/hooks/check-implementer-output.sh.template` | Extend SubagentStop hook to require `METHOD_AUDIT:` block with TDD evidence on executable tasks (exit 2 → sub-agent retry). |
| `scripts/append_learning_event.py` | `close-run` rewrites the matching `index.jsonl` entry's `outcome` or appends a `_final` record; expose an `outcome` resolver that prefers `final.json`. |
| `scripts/validate_method_audit.py` | **New.** Read `state.json`, iterate completed tasks under the active plan, check each task's `method_audit` against required methods. Exit 0 PASS, exit 1 FAIL with diagnostic JSON. |
| `evals/check_learning_log.py` | New fixtures: `index_unknown_final_success`, `zero_event_success`, `dead_pid_unclosed_run`, `live_pid_unclosed_run`. |
| `evals/check_method_audit.py` | **New.** Fixtures for missing-evidence-on-COMPLETE, applied-with-evidence, docs-only-waived, MID-risk-no-TDD. |
| `evals/check_skill_contract.py` | Add contract checks for new mandatory SKILL.md wording (method audit gate, preflight section, resource_key handling). |
| `HISTORY.md` | v2.11 entry. |
| `ARCHITECTURE.md` | New sections: Method Audit, Local-Env Preflight, Resource-Key Serialization. |
| `README.md` | One-line mention of v2.11 features under "Recent changes". |
| `docs/experiments/v2.11-method-audit-and-hardening/README.md` | MAE-style experiment landing page; status, decisions index, findings index. |
| `docs/experiments/v2.11-method-audit-and-hardening/JOURNAL.md` | Chronological build log. |

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Method audit scope | Top-level `state.tasks.task_N.method_audit = {required, applied, missing, waived}`. Stored per-task, never aggregated. | Per-task locality matches MAE's existing per-task counters; avoids global flag-flipping across plans. |
| What counts as "applied" | The method has at least one evidence reference in the structured output: `RED+GREEN` (TDD), `findings_count + locations` or `no_findings_residual_risk` (review), `commands_run + exit_codes` (verification). | "Invoked the skill" is not evidence — sub-agents can name-drop a skill. Evidence references make the audit grep-able and falsifiable. |
| Default required methods | Executable task: `[test-driven-development, verification-before-completion, code-review-pass]`. Docs/config/generated-only task: `[verification-before-completion]` only. | Matches Implementer prompt's existing TDD waiver clause. Verification is required for *all* tasks (the work was done; we must verify it landed). |
| Halting on missing audit | Phase 2 Step 1.5 validator FAIL → halt run **before** close-run. List missing methods per task. User can re-dispatch the specific task or accept and `waive` with reason. | Hard halt matches existing Phase Transition T3 state-write-fail behavior — wrong shipping cost > wrong-halt cost. |
| Docs-only detection (waive) | Reuse the existing T1 batch pre-filter rule: `files_test == []` AND every `files` entry ends with `.md`. Implementer may also set `METHOD_AUDIT: tdd waived reason=docs-only-task`. | Single source of truth for "docs-only". Don't fork the heuristic. |
| ENV_BLOCKER categories | Five named categories: `docker_oom`, `gradle_daemon_disappearance`, `gradle_metaspace`, `node_heap_oom`, `service_unreachable`. Recorded as `root_cause_category` on `verification_failure` or `env_blocker` learning-log event. | Five matches the observable failure modes from upstream Codex log review. Adding more is cheap (a YAML map); changing the schema later is not. |
| Outcome resolution | `final.json.outcome` wins; if absent, `meta.json.outcome`; if both absent or `unknown`, fall back to `index.jsonl` start-record. | Codex's chosen order. MAE consumers of the learning log (if any future tooling) must use the resolver, not raw `index.jsonl`. |
| Index rewrite vs label | `close-run` *rewrites* the matching `index.jsonl` entry's `outcome` field via a temp-file + atomic rename. Document that the index is now a current-state index for the runs whose `close-run` ran; entries without a matching close are still start-records. | Rewriting the index keeps cheap `jq` queries correct. Atomic rename avoids partial-write corruption. |
| Local-env preflight scope | Phase 0 Step 4.7 detects unfilled counterparts of `*.example`, `*.template`, `*.dist`, and lockfile-vs-install-marker mismatch. Reports only; records `state.preflight_warnings: [...]`. Never auto-copies. | Auto-copy can leak secrets or paste machine-specific paths into the worktree. Detection-only matches Codex's chosen policy. |
| `resource_key` parsing | Plan task may include `**Resource Key:** <slug>` in its body. Orchestrator parses in Phase 0 Step 6 along with `serial: true`. Two tasks with identical non-null `resource_key` in the same wave are split into different parallel groups. Plan Reviewer (Step 6.5) emits WARN on collisions. | Re-uses existing plan-markdown structure. WARN not BLOCKER — single-key collisions don't break a run; they just serialize unexpectedly. |
| Validator failure mode | `scripts/validate_method_audit.py` returns exit 1 with JSON: `{tasks_failing: [...], details: {task_id: {required, applied, missing, waived}}}`. SKILL.md Phase 2 Step 1.5 invokes and parses; halt path matches Phase Transition T3 state-write-fail. | Single Python script keeps the validator unit-testable and grep-friendly. |
| Hook-level gate vs validator | SubagentStop hook enforces *output shape* (`METHOD_AUDIT:` block present, fields well-formed). Validator enforces *semantic completeness* (required methods covered) at Phase 2. Both layers exist — hook prevents accidental skip mid-task, validator catches structural fix-ups that snuck through. | Defense in depth. Matches the existing P1 gate-hook pattern in v2.5. |

## Milestones

### Milestone 1: Method Audit State Contract + Fixtures

Lay down the schema before anything emits or validates it.

Acceptance:

- `state.tasks.task_N.method_audit` shape documented in `ARCHITECTURE.md` with field types and value enums.
- `evals/check_method_audit.py` covers four fixtures: `applied_with_evidence`, `missing_tdd_on_executable`, `docs_only_waived`, `mid_risk_no_verification`.
- `evals/check_learning_log.py` covers four fixtures: `index_unknown_final_success`, `zero_event_success`, `dead_pid_unclosed_run`, `live_pid_unclosed_run`.

### Milestone 2: Learning-Log Outcome Coherence

Helper-side fix shared with `kws-codex-plan-executor`. MAE inherits free.

Acceptance:

- `scripts/append_learning_event.py close-run` rewrites the matching `index.jsonl` entry's `outcome` atomically.
- `scripts/append_learning_event.py resolve-outcome --run-id ...` returns `final.json.outcome` if present, else `meta.json.outcome`, else `index.outcome`.
- `references/learning-log.md` documents the precedence and labels `index.jsonl` entries as start records prior to close-run.
- `evals/check_learning_log.py` fixtures pass.

### Milestone 3: Method Audit Output + Population

Sub-agent prompts emit structured evidence; orchestrator harvests into state.

Acceptance:

- `references/implementer-prompt.md` Section "Output" requires a `METHOD_AUDIT:` block with one line per required method. Lines look like:
  ```
  METHOD_AUDIT: tdd applied red="cmd that failed" green="cmd that passed" tests=test/foo.py::test_bar
  METHOD_AUDIT: tdd waived reason=docs-only-task
  ```
- `references/reviewer-prompt.md` Output section requires `REVIEW_FINDINGS: count=<N> locations=...` or `REVIEW_FINDINGS: no-findings residual-risk="..."`.
- `references/verifier-prompt.md` result-JSON contract documents `commands_run` as the verification-evidence list (already emitted; just documented).
- `SKILL.md` Phase 1 Step 4 Agent Cleanup populates `state.tasks.task_N.method_audit` from parsed sub-agent outputs.
- `references/hooks/check-implementer-output.sh.template` extended to require a `METHOD_AUDIT:` block when STATUS=DONE.

### Milestone 4: Method Audit Validation Gate

The gate that turns "encouraged" into "required".

Acceptance:

- `scripts/validate_method_audit.py` reads `state.json` and prints a JSON report on stdout, exit 0/1.
- `SKILL.md` Phase 2 Step 1.5 invokes the validator before close-run. FAIL → halt with the diagnostic; user re-dispatches specific tasks or edits state to add `waived` with reason.
- `SKILL.md` Guardrails: new row "Method audit is enforced before Phase 2 close-run".
- Learning-log event: validator FAIL emits `method_audit_violation` (severity=high) per failing task before the halt.

### Milestone 5: ENV_BLOCKER Triage Categories

Expand the triage playbook with named root-cause buckets.

Acceptance:

- `references/escalation-playbook.md` ENV_BLOCKER section adds five categories with redaction-safe diagnostic commands per category.
- `root_cause_category` recorded on the `verification_failure` / `env_blocker` learning-log event when category is determined.
- `references/common-mistakes.md` mentions Docker OOM ≠ compile failure and Gradle daemon disappearance distinguishing.

### Milestone 6: Local-Env Preflight

Phase 0 Step 4.7 — between risk assignment and baseline test.

Acceptance:

- `SKILL.md` Phase 0 Step 4.7 added. Detection rules:
  - For every `*.example`, `*.template`, `*.dist` in the worktree, if the corresponding non-suffixed file is absent AND in `.gitignore`: record warning.
  - For each dependency manifest (`package.json`, `pyproject.toml`, `Cargo.toml`, `build.gradle*`), if the lockfile exists but the install marker (`node_modules/.package-lock.json`, `.venv/`, `target/`, etc.) is absent or older than the lockfile: record warning.
- `state.preflight_warnings: [{kind, file, suggestion}]` populated.
- The user receives a one-line summary at the end of Phase 0 setup; never halts.
- ENV_BLOCKER triage step references preflight warnings when matching.

### Milestone 7: Resource-Key Serialization

Plan annotation that the parallel-group partition honors.

Acceptance:

- A task may declare `**Resource Key:** <slug>` in the plan task body.
- `SKILL.md` Phase 0 Step 6 partition algorithm: tasks within a wave with identical non-null `resource_key` go to *different* parallel groups.
- `references/plan-reviewer-prompt.md` audits same-wave `resource_key` collisions and emits a WARN issue with the affected task IDs.
- `state.execution_plan` group entries record `serialization_reason: "resource_key=<key>"` when a singleton group was forced for this reason.

### Milestone 8: Docs, Evals, History, Verification

Synchronize behavior with documentation and verification evidence.

Acceptance:

- `HISTORY.md` v2.11 entry summarizes the five features.
- `ARCHITECTURE.md` new sections on method audit, preflight, resource_key.
- `README.md` Recent-changes one-liner.
- `docs/experiments/v2.11-method-audit-and-hardening/README.md` + `JOURNAL.md` follow MAE experiment template.
- `evals/check_skill_contract.py` updated for new mandatory SKILL.md wording.
- All evals pass.

## Task Plan

### Task 1: Method Audit Fixtures + Learning-Log Outcome Fixtures

**Files:**
- Create: `evals/check_method_audit.py`
- Modify: `evals/check_learning_log.py`

- [ ] Write four fixtures in `check_method_audit.py`:
  - `applied_with_evidence`: COMPLETE task with `method_audit.applied = [{skill: tdd, evidence: {...}}, ...]`. Expect PASS.
  - `missing_tdd_on_executable`: COMPLETE task, executable risk (MID), `method_audit.missing = [tdd]`. Expect FAIL.
  - `docs_only_waived`: COMPLETE task with `files_test=[]` and all `files` `.md`, `method_audit.waived = [{skill: tdd, reason: docs-only-task}]`. Expect PASS.
  - `mid_risk_no_verification`: MID-risk COMPLETE task with `method_audit.applied = [tdd]` only; verification missing. Expect FAIL.
- [ ] Write four fixtures in `check_learning_log.py` (extend existing eval):
  - `index_unknown_final_success`: index says `unknown`, `final.json` says `success`. Resolver returns `success`; warning `index_outcome_stale` until index-rewrite lands.
  - `zero_event_success`: `final.outcome=success`, `event_count=0`, no `events.jsonl`. Expected status `success`, no warning.
  - `dead_pid_unclosed_run`: no `final.json`, `meta.ended_at=null`, pid `999999`. Expected status `stale`, warning `dead_pid_unclosed`. (Stale detector lands in Codex; MAE only verifies resolver handles missing-final.)
  - `live_pid_unclosed_run`: same, pid `os.getpid()`. Expected status `unknown`.
- [ ] Run `python3 evals/check_method_audit.py`.
- [ ] Run `python3 evals/check_learning_log.py`.
- [ ] Commit: `test: cover method audit and learning-log outcome fixtures`.

### Task 2: Learning-Log `close-run` Index Rewrite + Outcome Resolver

**Files:**
- Modify: `scripts/append_learning_event.py`
- Modify: `references/learning-log.md`

- [ ] Add `_rewrite_index_outcome(log_root, run_id, outcome)` helper that reads `index.jsonl`, modifies the matching record, writes to `index.jsonl.tmp`, then `os.replace` to `index.jsonl`. Use a file lock (`fcntl.flock`) to prevent concurrent writers from interleaving.
- [ ] Update `close-run` subcommand: after writing `final.json` and `meta.json`, call `_rewrite_index_outcome`.
- [ ] Add new subcommand `resolve-outcome --run-id <id> [--log-root <path>]` that reads `final.json` → `meta.json` → `index.jsonl` in order and prints the resolved outcome on stdout.
- [ ] Add `--json` flag to `resolve-outcome` for machine-readable output.
- [ ] In `references/learning-log.md`, add a "Source of truth" section documenting: `final.json` is authoritative once written; `meta.json` mirrors; `index.jsonl` is a current-state index for runs whose `close-run` ran, a start record otherwise.
- [ ] Run `python3 evals/check_learning_log.py` — fixtures from Task 1 should pass.
- [ ] Run `python3 scripts/append_learning_event.py resolve-outcome --help`.
- [ ] Commit: `feat: harden learning-log outcome resolution and index rewrite`.

### Task 3: Method Audit Output Block in Sub-Agent Prompts

**Files:**
- Modify: `references/implementer-prompt.md`
- Modify: `references/reviewer-prompt.md`
- Modify: `references/verifier-prompt.md`

- [ ] In `implementer-prompt.md` Output section, add `METHOD_AUDIT:` lines spec. Required: one line per skill listed under "Required Skills" that *applies to this task*. Line format:
  ```
  METHOD_AUDIT: <skill> applied [evidence-kv pairs...]
  METHOD_AUDIT: <skill> waived reason=<short rationale>
  ```
  Evidence kv pairs for TDD: `red="<command>"`, `green="<command>"`, `tests=<path[::test]>` (one or many).
  Document that fabricated evidence (commands that were not run) is grounds for a re-dispatch and a learning-log `method_audit_violation` event.
- [ ] In `reviewer-prompt.md`, add `REVIEW_FINDINGS:` line: `count=<N> locations=<file:line,...>` for ≥1 findings; `no-findings residual-risk="<one-sentence statement>"` otherwise. Document that a Reviewer claiming PASS with `no-findings` and no risk statement triggers re-dispatch.
- [ ] In `verifier-prompt.md`, in the result-JSON contract section, mark `commands_run` as the verification-evidence list. Add `category` field to FAIL results matching the ENV_BLOCKER categories (M5). Document that `category` is optional; absence means "uncategorized" and the orchestrator falls through standard ENV_BLOCKER triage.
- [ ] Re-read all three prompts after edits to confirm consistency.
- [ ] Run `python3 evals/check_skill_contract.py --skill SKILL.md` to confirm nothing references-section-related broke.
- [ ] Commit: `feat: require structured method-audit evidence from sub-agents`.

### Task 4: SubagentStop Hook Extension

**Files:**
- Modify: `references/hooks/check-implementer-output.sh.template`
- Modify: `evals/check_skill_contract.py` (if hook contract is referenced)

- [ ] Extend the existing STATUS / SUMMARY / FILES_CHANGED / FILES_TEST_CHANGED checks with:
  - If STATUS=DONE: require at least one `METHOD_AUDIT:` line.
  - If STATUS=DONE AND `FILES_TEST_CHANGED` is non-empty: require `METHOD_AUDIT: tdd applied red=... green=...` (or `waived reason=...`).
  - On missing or malformed line: print actionable error to stderr and exit 2.
- [ ] Test hook locally with three synthetic inputs: well-formed DONE, DONE missing METHOD_AUDIT, DONE with malformed METHOD_AUDIT. Confirm exit codes 0, 2, 2.
- [ ] No skill-contract eval change required unless hook contract wording in `SKILL.md` Guardrails changes (it will — see Task 6).
- [ ] Commit: `feat: enforce method-audit block via SubagentStop hook`.

### Task 5: Method-Audit Validator + Phase 2 Gate

**Files:**
- Create: `scripts/validate_method_audit.py`
- Modify: `SKILL.md` (Phase 2 Step 1.5, Guardrails)

- [ ] Write `validate_method_audit.py` with arguments `--state <path>` and optional `--active-plan plan1|plan2|auto` (default `auto`, reads `state.active_plan`).
- [ ] For each task with `status == "COMPLETE"`:
  - Compute `required` from risk + complexity + files (executable vs docs-only).
  - Read `method_audit.applied` and `method_audit.waived`.
  - `missing = required - (applied_skills ∪ waived_skills)`.
  - If `missing != []` → record task in failures.
- [ ] Output JSON: `{passed: bool, failures: [{task_id, risk, missing, applied, waived}]}`. Exit 0 if passed, 1 otherwise.
- [ ] In `SKILL.md` Phase 2, insert new Step 1.5 between Step 1 (Final Docs Updater) and Step 2 (Generate Final Summary Report):
  - Run `python3 <skill_dir>/scripts/validate_method_audit.py --state <worktree>/.orchestrator/state.json`.
  - If exit 1: emit a `method_audit_violation` learning-log event per failing task (helper available, env-variable `MAE_LEARNING_RUN_ID` guarded as elsewhere); print the validator JSON; halt with: "Method audit failed for tasks: <list>. Re-dispatch or edit state.tasks.<id>.method_audit.waived with a reason."
  - If exit 0: proceed to Step 2.
- [ ] Add a Guardrails row: "Method audit must pass before Phase 2 close-run".
- [ ] Run `python3 scripts/validate_method_audit.py --help`.
- [ ] Run `python3 evals/check_method_audit.py` — script must pass all four fixtures end-to-end.
- [ ] Commit: `feat: gate Phase 2 close-run on method-audit validation`.

### Task 6: SKILL.md Phase 1 Step 4 Audit Population

**Files:**
- Modify: `SKILL.md` (Phase 1 Step 4 Agent Cleanup)

- [ ] In Phase 1 Step 4 Step 2 "Update state file", extend the task entry with the new field:
  ```json
  "method_audit": {
    "required": ["test-driven-development", "verification-before-completion", "code-review-pass"],
    "applied": [{"skill": "test-driven-development", "evidence": {"red": "...", "green": "...", "tests": [...]}}],
    "missing": [],
    "waived": []
  }
  ```
- [ ] Add a procedural sub-step: "Parse `METHOD_AUDIT:` lines from the Implementer's final output. Parse `REVIEW_FINDINGS:` from the Combined Reviewer's output. Read `commands_run` from the Verifier result JSON (when MID/HIGH) or from the batch verifier (when LOW, post-T1)."
- [ ] Document `required` derivation: executable task → `[tdd, verification, code-review-pass]`; docs-only → `[verification]` only; the same docs-only heuristic as T1 batch pre-filter.
- [ ] Update Guardrails: "Method audit fields are populated at Phase 1 Step 4 from structured sub-agent output."
- [ ] Commit: `feat: populate method_audit during Agent Cleanup`.

### Task 7: ENV_BLOCKER Triage Categories

**Files:**
- Modify: `references/escalation-playbook.md`
- Modify: `references/common-mistakes.md`
- Modify: `references/learning-log.md`

- [ ] In `escalation-playbook.md` ENV_BLOCKER section, add a "Category triage" subsection mapping symptom → category → diagnostic command(s) → resolution path:
  - `docker_oom`: symptom = container exit 137 / "Killed" in build log; diagnostic = `docker inspect <id> --format '{{.State.OOMKilled}}'`; resolution = retry with more memory or escalate.
  - `gradle_daemon_disappearance`: symptom = "Daemon disappeared" / "Gradle build daemon disappeared unexpectedly"; diagnostic = check `~/.gradle/daemon/*/daemon-*.out.log` last 50 lines for OOM / metaspace / crash; resolution = `./gradlew --stop && ./gradlew <task> --no-daemon` once for triage.
  - `gradle_metaspace`: symptom = "Metaspace" in daemon log; resolution = increase `-XX:MaxMetaspaceSize` in `gradle.properties` and retry.
  - `node_heap_oom`: symptom = "JavaScript heap out of memory" or "FATAL ERROR: Reached heap limit"; diagnostic = check `node --version` and current `NODE_OPTIONS`; resolution = retry with `NODE_OPTIONS=--max-old-space-size=4096`.
  - `service_unreachable`: symptom = "connection refused" / "ECONNREFUSED" / "host unreachable"; diagnostic = `nc -z` or `curl --max-time 2`; resolution = start service or escalate.
- [ ] For each category, mark it as recordable via `root_cause_category` on the existing `verification_failure` learning event (no new event type — extend the schema with one optional field).
- [ ] In `references/learning-log.md`, document `root_cause_category` as an optional field on `verification_failure` events, valid values listed above plus `other`.
- [ ] In `common-mistakes.md`, add two entries: "Docker exit 137 mistaken for compile failure" and "Gradle daemon disappearance without category check".
- [ ] Commit: `docs: expand env_blocker triage categories`.

### Task 8: Local-Env Preflight

**Files:**
- Modify: `SKILL.md` (insert Phase 0 Step 4.7)
- Modify: `references/common-mistakes.md`

- [ ] Insert Phase 0 Step 4.7 "Local-env preflight (P11)" between Step 4 (Assign risk levels) and Step 5 (Take baseline test snapshot):
  - Walk the worktree top two levels (depth 2) collecting paths matching `*.example`, `*.template`, `*.dist`.
  - For each match, compute the un-suffixed counterpart. Check: does counterpart exist? Is the suffix-stripped name in `.gitignore`? If counterpart missing AND in `.gitignore`: emit warning `kind=missing_local_config`.
  - For each known manifest pair (`package.json` ↔ `package-lock.json`, `pyproject.toml` ↔ `poetry.lock` / `uv.lock`, `Cargo.toml` ↔ `Cargo.lock`, `build.gradle` / `build.gradle.kts` ↔ `gradle/wrapper/gradle-wrapper.properties`), if the lockfile exists but the conventional install marker (`node_modules/`, `.venv/` or `venv/`, `target/`, `~/.gradle/caches/` is host-global so skip, use repo-local instead) is older than the lockfile by ≥ 1 second: emit warning `kind=dependencies_likely_stale`.
  - Record warnings to `state.preflight_warnings: [{kind, file, suggestion, detected_at}]`.
  - Never halt. Print a single-line summary: `Preflight: <N> warnings (see state.preflight_warnings)` or `Preflight: clean`.
- [ ] Reference Preflight warnings from the ENV_BLOCKER triage section: "Before running the Step-2 dependency check, consult `state.preflight_warnings` — if `dependencies_likely_stale` is present, run install before retrying."
- [ ] In `common-mistakes.md`, add: "Missing `.env` or `local.properties` counterpart causes baseline test failures attributed to code."
- [ ] Commit: `feat: add framework-agnostic local-env preflight`.

### Task 9: Resource-Key Plan Annotation + Partition

**Files:**
- Modify: `SKILL.md` (Phase 0 Step 6 partition algorithm)
- Modify: `references/plan-reviewer-prompt.md`

- [ ] Extend Phase 0 Step 6 partition algorithm with one rule:
  - After file-disjointness merging, before finalizing the parallel-group list: build a `resource_key → [task_ids]` map for this wave. For any key with ≥ 2 task IDs in the same wave, ensure each task is in a separate group (split if needed).
  - When a task ends up as a singleton group purely due to `resource_key`: write `serialization_reason: "resource_key=<key>"` to its group entry in `state.execution_plan`.
- [ ] Document the plan annotation: a task may include a line `**Resource Key:** <slug>` (similar to `**Files:**`). The slug is case-insensitive; whitespace stripped. Examples: `gradle-test-output`, `db-port-5432`, `playwright-browser`.
- [ ] Extend `references/plan-reviewer-prompt.md` Audit Rules section with a new rule:
  - "Resource-key collision audit": parse `Resource Key:` lines from all tasks. For each non-null key, if ≥ 2 tasks share it AND they appear in the same `execution_plan` wave per the supplied YAML, emit WARN issue `category=resource_key_collision`, severity=WARN, with suggested fix: "Add explicit dependency between Task X and Task Y to put them in different waves, or accept serialization within the wave."
- [ ] No state schema change beyond the existing `serialization_reason` field on group entries.
- [ ] Commit: `feat: honor plan resource_key in parallel partition`.

### Task 10: Docs, History, Architecture, Experiment Folder, Final Verification

**Files:**
- Modify: `HISTORY.md`
- Modify: `ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `evals/check_skill_contract.py`
- Create: `docs/experiments/v2.11-method-audit-and-hardening/README.md`
- Create: `docs/experiments/v2.11-method-audit-and-hardening/JOURNAL.md`
- Modify: `SKILL.md` Guardrails table

- [ ] Add `HISTORY.md` entry for v2.11 summarizing the five features.
- [ ] Add three sections to `ARCHITECTURE.md`: "Method Audit (v2.11)", "Local-Env Preflight (v2.11)", "Resource-Key Serialization (v2.11)". Each section: rationale, data flow, state-schema impact.
- [ ] Add one-line bullet to `README.md` under "Recent changes" or equivalent.
- [ ] Update `evals/check_skill_contract.py` with new mandatory-wording checks:
  - SKILL.md mentions "method_audit" in Phase 1 Step 4 and Phase 2 Step 1.5.
  - SKILL.md mentions "Local-env preflight" / "Preflight" in Phase 0 Step 4.7.
  - SKILL.md mentions "resource_key" in Phase 0 Step 6 partition rules.
  - SKILL.md Guardrails has rows: "Method audit must pass before Phase 2 close-run", "Resource-key collisions force serialization in same wave".
- [ ] Create `docs/experiments/v2.11-method-audit-and-hardening/README.md` per `_template/README.md` with status, decisions/findings indexes.
- [ ] Create `docs/experiments/v2.11-method-audit-and-hardening/JOURNAL.md` per template with a build-log entry per task.
- [ ] Run final verification suite:

```bash
cd /Users/kws/source/private/Archive/skills/kws-claude-multi-agent-executor
python3 evals/check_method_audit.py
python3 evals/check_learning_log.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_doc_freshness.py
python3 scripts/append_learning_event.py resolve-outcome --help
python3 scripts/validate_method_audit.py --help
bash references/hooks/check-implementer-output.sh.template < /dev/null || true  # syntax / shebang check
```

- [ ] Commit: `chore: document v2.11 method audit and codex-inspired hardening`.

## Final Verification

Run from `skills/kws-claude-multi-agent-executor/`:

```bash
python3 evals/check_method_audit.py
python3 evals/check_learning_log.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_doc_freshness.py
python3 scripts/validate_method_audit.py --state docs/experiments/v2.11-method-audit-and-hardening/fixtures/sample_state.json  # if fixture exists
```

If any check is skipped, record the reason in the experiment's `JOURNAL.md` with an honest substitute (e.g., "live-pid fixture cannot run under headless CI without psutil; substituted dead-pid only").

## Self-Review Notes

- The plan is scoped to the five Codex-cross-pollinated items the prior analysis identified as Tier 1 + Tier 2 extensions for MAE.
- It does not change Plan 2 / multi-plan execution behavior, the chain-resume protocol, or the existing P1–P15 gates.
- Method audit is the largest change. It is *intentionally* gated at Phase 2 (not per-task) so a task can still complete and proceed; the validator catches the absent-evidence pattern across the run. The hook in Task 4 prevents the most common path (Implementer forgetting to emit the block at all) at the per-task layer.
- ENV_BLOCKER categories are additive — un-categorized escalations still flow through the existing generic triage.
- Local-env preflight is *report-only*. The orchestrator never edits or copies env files. Codex's prior decision (detection-only) is preserved.
- Resource-key parsing is a one-line addition to the existing partition algorithm. No new graph structure.
- All learning-log additions use existing event types or extend with optional fields — no breaking schema change. The v2.8 single-writer rule (orchestrator only) is preserved.
- The plan is self-contained and does not require user project changes, network access, or new external dependencies.
