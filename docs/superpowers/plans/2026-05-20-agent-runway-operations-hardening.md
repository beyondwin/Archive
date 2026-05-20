# AgentRunway Operations Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an AgentRunway operations layer that freezes Superpowers spec/plan inputs into a run contract, records local and AgentLens evidence, supports idempotent resume/watchdog reconciliation, and requires reviewer/verifier gates before production candidates merge.

**Architecture:** Keep `runner.py` as the command-level coordinator and move operational responsibilities into focused helpers: contract preflight, event journal/outbox, artifact graph diagnostics, watchdog reconciliation planning, and role-generic worker supervision. Implement in the milestone order from the design: observability first, resume/watchdog second, review/verify gates third.

**Tech Stack:** Python 3.11+ stdlib (`argparse`, `dataclasses`, `json`, `sqlite3`, `pathlib`, `subprocess`, `time`, `datetime`, `os`, `hashlib`), git worktrees/cherry-pick, pytest, deterministic fake Codex/Claude CLIs, AgentLens best-effort event mirroring.

---

## Changes from Initial Draft (2026-05-20 review)

A source audit against `skills/agent-runway/scripts/agentrunway/` and
`skills/agent-runway/evals/` produced the following corrections. Each is
folded into the task it belongs to; this list exists so a top-down reader
sees the deltas without diffing the previous revision.

1. **Spec manifest parsing — pick one (Task 1).** The first draft introduced
   a parallel bullet-list parser (`parse_spec_manifest_sections`) that did
   not match any existing fixture. All current specs (`evals/fixtures/*/spec.md`,
   the four embedded specs in eval tests, and the design's own header layout)
   use the heading-derived IDs (`S1.1`, `S2.1`) produced by the existing
   `plan_parser.parse_spec_manifest`. Task 1 now reuses that parser
   verbatim. No fixture or test changes are needed for the manifest format.
2. **Implementer candidate state race (Task 6).** `run_implementer_attempt`
   currently enqueues merge candidates with status `merge_ready`, and the
   merge loop applies anything in that state. Inserting gates between the
   implementer loop and the merge loop without changing the initial status
   means the merge loop applies implementer commits before the reviewer ever
   runs. The implementer attempt now enqueues with status `pending_review`,
   and only a `passed` verifier promotes the candidate to `merge_ready`.
3. **Reviewer/verifier env wiring (Task 6).** Adding `metadata` to
   `WorkerSpec` is necessary but not sufficient; the fake CLIs read
   `AGENTRUNWAY_REVIEWED_WORKER_ID`, `AGENTRUNWAY_FAKE_REVIEW_STATUS`, and
   `AGENTRUNWAY_FAKE_VERIFY_STATUS` from env, and nothing populates them. The
   plan now shows `run_reviewer_attempt`/`run_verifier_attempt` constructing
   `WorkerSpec.metadata` with those keys before the adapter starts.
4. **Production adapter `--spec` enforcement (Task 1).** The runner currently
   accepts `--adapter codex` without `--spec`, which would crash inside the
   new contract preflight. Task 1 adds an explicit guard in `runner.run`:
   non-local adapters and non-planning-only runs require `--spec`.
5. **`contract_path` column migration (Task 1).** `CREATE TABLE IF NOT EXISTS`
   does not add new columns to pre-existing SQLite files, so adding
   `contract_path` to the `runs` schema only helps fresh databases. Task 1
   now adds a guarded `ALTER TABLE` step keyed off `PRAGMA table_info(runs)`.
6. **Artifact graph test setup (Task 3).** The first draft's test wrote a
   `worker_result.json` artifact but never created a `workers` row, so
   `build_artifact_graph` could not produce the asserted
   `task_001:task_001-implementer-001:worker_result` node. The test now
   inserts the matching worker attempt before building the graph.
7. **Reconciliation scope narrowed (Task 4).** The first draft promised
   `abort_cherry_pick`, `retain_orphan`, and `block` actions in the resume
   action plan example but only implemented `reconcile_forward` and `retry`.
   Task 4 now explicitly scopes to those two actions and references the
   design's updated S10 implementation-scope note. The remaining action
   kinds are deferred and intentionally not invented by the planner.
8. **`agentlens_events.local_recorded` removed.** The outbox writer only
   produces `agentlens_disabled`, `agentlens_emitted`, and `agentlens_failed`.
   Task 8 reference doc and the design now drop the unused fourth state.
9. **Dead CLI flags removed (Task 6).** `--skip-review` and `--skip-verify`
   in `invocation.py` lose their meaning the moment gates are mandatory.
   Task 6 deletes them so they cannot mask future regressions.
10. **Gate retry policy: block-on-fail only (Task 7).** Real implementer
    redispatch with reviewer findings is deferred to a later slice (see the
    design's updated S12). Task 7 collapses the dead `if/else` in the
    changes_requested branch into a single block-with-evidence path and
    notes the deferral.
11. **Host-friendly invocation added (Task 0).** The plan now includes a
    resolver before contract preflight so Codex, Claude, and CLI users can
    call AgentRunway with `topic=...`, `--topic`, `--latest`, and `--last`
    instead of the internal Python script path. The resolver only selects
    explicit spec/plan/run ids; contract preflight and the runner still own
    execution.

Task 0 is new and runs before the original contract preflight. All other tests,
file claims, and acceptance commands are updated in place inside the task
definitions below.

---

## Source Documents

- Design: `docs/superpowers/specs/2026-05-20-agent-runway-operations-hardening-design.md`
- Parent design: `docs/superpowers/specs/2026-05-20-agent-runway-design.md`
- Previous slice: `docs/superpowers/specs/2026-05-20-agent-runway-production-supervisor-design.md`
- Current skill root: `skills/agent-runway/`

## Scope Check

The design covers three linked capabilities: observability, resume/watchdog, and review/verify gates. These are not independent subsystems for this implementation because all three depend on the same run contract, event journal, artifact graph, and worker lifecycle state. The plan still splits them into sequential tasks so each task leaves the runner in a testable state.

## File Structure

### Create

| Path | Responsibility |
| --- | --- |
| `skills/agent-runway/scripts/agentrunway/resolver.py` | Resolve host-friendly `topic`, `latest`, explicit path, and `last` run aliases into exact spec/plan/run inputs before runner mutation. |
| `skills/agent-runway/scripts/agentrunway/contract.py` | Preflight Superpowers spec/plan into immutable `contract.json`, validate `spec_refs`, acceptance commands, and parsed task metadata. |
| `skills/agent-runway/scripts/agentrunway/artifact_graph.py` | Build derived artifact graph and coverage summaries from DB, run files, tasks, workers, merge candidates, and applied commits. |
| `skills/agent-runway/scripts/agentrunway/reconciliation.py` | Produce and apply idempotent resume/watchdog action plans from DB, filesystem, process, and git evidence. |
| `skills/agent-runway/evals/test_invocation_resolver.py` | Topic/spec/plan/latest/last resolution tests and ambiguous-match rejection tests. |
| `skills/agent-runway/evals/test_contract_preflight.py` | Contract creation and preflight rejection tests. |
| `skills/agent-runway/evals/test_artifact_graph_status.py` | Artifact graph, coverage, status, inspect, and JSON diagnostics tests. |
| `skills/agent-runway/evals/test_event_journal_agentlens.py` | Local event journal, SQLite outbox, redaction, and best-effort AgentLens failure tests. |
| `skills/agent-runway/evals/test_reconciliation.py` | Resume dry-run, reconcile-forward, retry, merge recovery, and idempotency tests. |
| `skills/agent-runway/evals/test_review_verify_gates.py` | Reviewer/verifier gate sequencing and retry policy tests. |

### Modify

| Path | Change |
| --- | --- |
| `skills/agent-runway/scripts/agentrunway/models.py` | Add dataclasses and constants for run contracts, artifact graph nodes, coverage summaries, event records, and reconciliation actions. |
| `skills/agent-runway/scripts/agentrunway/db.py` | Add repository methods for events/outbox, artifact records, worker listing, retry counting, run contract path, and task/merge summaries. |
| `skills/agent-runway/scripts/agentrunway/events.py` | Replace one-file-per-event artifact writing with canonical `events.jsonl` plus SQLite outbox and optional AgentLens emitter hook. |
| `skills/agent-runway/scripts/agentrunway/status.py` | Return human and JSON diagnostics for status, inspect, events, artifact graph, coverage, and AgentLens state. |
| `skills/agent-runway/scripts/agentrunway/watchdog.py` | Keep low-level classification helpers and call reconciliation planning for resume/watchdog decisions. |
| `skills/agent-runway/scripts/agentrunway/invocation.py` | Parse host-friendly `--topic`, `--latest`, `--last`, and explicit path forms, call the resolver, and preserve long-form CLI compatibility. |
| `skills/agent-runway/scripts/agentrunway/packetizer.py` | Materialize role-specific reviewer and verifier packets/prompts/output paths. |
| `skills/agent-runway/scripts/agentrunway/supervisor.py` | Generalize implementer-only attempt execution into role-generic worker attempts and gate helpers. |
| `skills/agent-runway/scripts/agentrunway/runner.py` | Wire preflight, contract persistence, event emission, artifact graph refresh, resume planning, and review/verify gate sequencing. |
| `skills/agent-runway/evals/fixtures/fake-bin/codex` | Make the fake runtime produce worker, review, or verification result JSON based on `AGENTRUNWAY_WORKER_ROLE`. |
| `skills/agent-runway/evals/fixtures/fake-bin/claude` | Same role-aware fake runtime behavior for Claude. |
| `skills/agent-runway/SKILL.md` | Document natural-language key-value invocation, topic resolution, and required disambiguation behavior for host sessions. |
| `skills/agent-runway/README.md` | Document operations hardening commands, event evidence, AgentLens behavior, resume dry-run, and gate behavior. |
| `skills/agent-runway/references/agentlens-events.md` | Document canonical event types, local journal first, and outbox statuses. |
| `skills/agent-runway/references/watchdog.md` | Document reconciliation actions and resume idempotency. |
| `skills/agent-runway/references/protocol.md` | Document Superpowers spec/plan contract preflight and run evidence bundle. |

---

## Task 0: Host-Friendly Invocation Resolver

```yaml agentrunway-task
task_id: task_000
title: Host-friendly invocation resolver
risk: medium
phase: implementation
dependencies: []
spec_refs: [S5, S6, S13, S14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/resolver.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/invocation.py, mode: owned}
  - {path: skills/agent-runway/SKILL.md, mode: owned}
  - {path: skills/agent-runway/README.md, mode: shared_append}
  - {path: skills/agent-runway/evals/test_invocation_resolver.py, mode: owned}
  - {path: skills/agent-runway/evals/test_invocation_and_config.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_invocation_resolver.py evals/test_invocation_and_config.py -v
  - cd skills/agent-runway && python3 evals/check_skill_contract.py
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/resolver.py`
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`
- Modify: `skills/agent-runway/SKILL.md`
- Modify: `skills/agent-runway/README.md`
- Create: `skills/agent-runway/evals/test_invocation_resolver.py`
- Modify: `skills/agent-runway/evals/test_invocation_and_config.py`

- [ ] **Step 1: Write failing resolver tests**

Create `skills/agent-runway/evals/test_invocation_resolver.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentrunway.resolver import (
    ResolutionError,
    read_last_run,
    resolve_run_alias,
    resolve_run_inputs,
    write_last_run,
)


def _write_pair(repo: Path, slug: str, *, date: str = "2026-05-20") -> tuple[Path, Path]:
    specs = repo / "docs" / "superpowers" / "specs"
    plans = repo / "docs" / "superpowers" / "plans"
    specs.mkdir(parents=True, exist_ok=True)
    plans.mkdir(parents=True, exist_ok=True)
    spec = specs / f"{date}-{slug}-design.md"
    plan = plans / f"{date}-{slug}.md"
    spec.write_text(f"# Design: {slug}\n\n## Summary\n\nSpec.\n", encoding="utf-8")
    plan.write_text(
        f"# Plan: {slug}\n\n"
        f"- Design: `{spec.relative_to(repo)}`\n\n"
        "## Task 1\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: Example\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        "spec_refs: [S1]\n"
        "file_claims:\n"
        "  - {path: example.txt, mode: owned}\n"
        "acceptance_commands: [python -m pytest]\n"
        "required_skills: [test-driven-development]\n"
        "```\n",
        encoding="utf-8",
    )
    return spec, plan


def test_resolve_topic_to_exact_superpowers_pair(git_repo: Path) -> None:
    spec, plan = _write_pair(git_repo, "checkout-flow")

    resolved = resolve_run_inputs(
        repo_root=git_repo,
        plan=None,
        spec=None,
        topic="checkout-flow",
        latest=False,
        adapter="codex",
    )

    assert resolved.plan_path == plan
    assert resolved.spec_path == spec
    assert resolved.adapter == "codex"
    assert resolved.source == "topic"


def test_explicit_plan_can_infer_design_reference(git_repo: Path) -> None:
    spec, plan = _write_pair(git_repo, "billing-ledger")

    resolved = resolve_run_inputs(
        repo_root=git_repo,
        plan=plan,
        spec=None,
        topic=None,
        latest=False,
        adapter="claude",
    )

    assert resolved.plan_path == plan
    assert resolved.spec_path == spec
    assert resolved.source == "explicit_plan"


def test_ambiguous_topic_fails_with_candidates(git_repo: Path) -> None:
    _write_pair(git_repo, "runner-hardening")
    _write_pair(git_repo, "runner-hardening-followup")

    with pytest.raises(ResolutionError) as exc:
        resolve_run_inputs(
            repo_root=git_repo,
            plan=None,
            spec=None,
            topic="runner-hardening",
            latest=False,
            adapter="codex",
        )

    assert "ambiguous topic" in str(exc.value)
    assert len(exc.value.payload["candidates"]) == 2


def test_latest_uses_newest_complete_pair(git_repo: Path) -> None:
    _write_pair(git_repo, "older-topic", date="2026-05-19")
    spec, plan = _write_pair(git_repo, "newer-topic", date="2026-05-20")

    resolved = resolve_run_inputs(
        repo_root=git_repo,
        plan=None,
        spec=None,
        topic=None,
        latest=True,
        adapter="codex",
    )

    assert resolved.plan_path == plan
    assert resolved.spec_path == spec
    assert resolved.source == "latest"


def test_last_run_pointer_is_workspace_scoped(git_repo: Path, isolated_home: Path) -> None:
    write_last_run(git_repo, "run-123")

    assert read_last_run(git_repo) == "run-123"
    workspace_dir = next((isolated_home / "workspaces").glob("*"))
    payload = json.loads((workspace_dir / "last_run.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-123"
    assert resolve_run_alias(git_repo, run_id=None, last=True) == "run-123"
```

Update `skills/agent-runway/evals/test_invocation_and_config.py` so
`parse_run_args(["run", "--topic", "checkout-flow", "--adapter", "codex"])`
is valid and `parse_run_args(["status", "--last"])` is valid.

- [ ] **Step 2: Implement the resolver boundary**

Create `skills/agent-runway/scripts/agentrunway/resolver.py` with:

- `ResolutionError(message: str, payload: dict[str, object])`
- frozen dataclass `RunInputResolution(plan_path, spec_path, adapter, source)`
- `normalize_topic(value: str) -> str`
- `resolve_run_inputs(repo_root, plan, spec, topic, latest, adapter)`
- `resolve_run_alias(repo_root, run_id, last)`
- `write_last_run(repo_root, run_id)` and `read_last_run(repo_root)`

Rules:

- explicit `plan` and `spec` are returned without search, after existence
  checks,
- explicit `plan` without `spec` first reads `Design:` / `Design` source
  references inside the plan, then falls back to normalized slug pairing,
- `topic` searches only `docs/superpowers/specs/` and
  `docs/superpowers/plans/`,
- matching is conservative: exact normalized slug match wins; broad substring
  matches with more than one pair raise `ResolutionError`,
- `latest` considers complete pairs only and ranks by
  `git log -1 --format=%ct -- <path>` for tracked docs, falling back to
  `Path.stat().st_mtime`,
- `last` uses `~/.agentrunway/workspaces/<workspace_id>/last_run.json`, where
  `workspace_id` is the existing `worktrees.workspace_id(repo_root)`.

The resolver must not import `runner.py` or mutate run state except the
last-run pointer helper.

- [ ] **Step 3: Wire host-friendly flags into invocation.py**

In `skills/agent-runway/scripts/agentrunway/invocation.py`:

- make `run --plan` optional,
- add `run --topic <topic>`,
- add `run --latest`,
- preserve `run --spec <path>`,
- add `--last` to `status`, `inspect`, `events`, `resume`, `cancel`, and
  `apply`,
- keep `--run <run_id>` for explicit run ids,
- before `runner.run(args)`, call `resolve_run_inputs(...)` and mutate the
  namespace to exact `args.plan`, `args.spec`, and `args.adapter`,
- after a successful `run`, call `write_last_run(repo_root, payload["run_id"])`,
- before status-like commands, call `resolve_run_alias(...)` when `--last` was
  passed,
- convert `ResolutionError` into a JSON stderr payload with
  `{"error": "...", "candidates": [...]}` and exit code 1.

No worker dispatch behavior belongs in `invocation.py`.

- [ ] **Step 4: Update the AgentRunway skill contract**

Replace the required bootstrap in `skills/agent-runway/SKILL.md` with:

````markdown
## Required Bootstrap

1. Invoke/read `using-superpowers` before doing anything else.
2. Accept either:
   - `plan=<path>` with optional `spec=<path>`, or
   - `topic=<topic>`, or
   - `run_id=<run_id>` / `last` for status, inspect, resume, cancel, or apply.
3. If the user gives only natural language and no clear `plan`, `topic`,
   `run_id`, or `last`, ask for one concise clarification.
4. Shell out to `scripts/agentrunway.py`; do not orchestrate workers from
   conversation context.
````

Add Korean-friendly examples:

````markdown
```text
agent-runway topic=agent-runway-operations-hardening adapter=codex 로 실행해줘
agent-runway plan=docs/superpowers/plans/example.md spec=docs/superpowers/specs/example-design.md adapter=claude 로 실행해줘
agent-runway last 상태 확인해줘
```
````

- [ ] **Step 5: Document short CLI usage**

Append to `skills/agent-runway/README.md`:

````markdown
## Invocation Shortcuts

The internal Python script remains supported, but normal use should go through
the short resolver forms:

```bash
agentrunway run --topic <topic> --adapter codex
agentrunway run --latest --adapter claude
agentrunway status --last
agentrunway inspect --last --json
agentrunway apply --last
```

`--topic` resolves a complete Superpowers design/plan pair under
`docs/superpowers/specs/` and `docs/superpowers/plans/`. Ambiguous topics fail
before dispatch and print candidates. `--last` is scoped to the current
workspace id, not the whole machine.
````

- [ ] **Step 6: Verify and commit Task 0**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_invocation_resolver.py evals/test_invocation_and_config.py -v
cd skills/agent-runway && python3 evals/check_skill_contract.py
```

Then commit:

```bash
git add skills/agent-runway/scripts/agentrunway/resolver.py \
  skills/agent-runway/scripts/agentrunway/invocation.py \
  skills/agent-runway/SKILL.md \
  skills/agent-runway/README.md \
  skills/agent-runway/evals/test_invocation_resolver.py \
  skills/agent-runway/evals/test_invocation_and_config.py
git commit -m "Add AgentRunway invocation resolver"
```

## Task 1: Contract Preflight and Run Evidence Manifest

```yaml agentrunway-task
task_id: task_001
title: Contract preflight and run evidence manifest
risk: medium
phase: implementation
dependencies: [task_000]
spec_refs: [S5, S8, S13, S14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/contract.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/models.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/db.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_contract_preflight.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_contract_preflight.py -v
  - cd skills/agent-runway && python -m pytest evals/test_runner_planning_slice.py evals/test_plan_parser.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/contract.py`
- Modify: `skills/agent-runway/scripts/agentrunway/models.py`
- Modify: `skills/agent-runway/scripts/agentrunway/db.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Create: `skills/agent-runway/evals/test_contract_preflight.py`

- [ ] **Step 1: Write failing contract preflight tests**

The spec helper below mirrors the existing fixture format used across the
repo (`evals/fixtures/*/spec.md`). Section IDs are derived by the existing
`plan_parser.parse_spec_manifest` from heading depth, not from a bullet
list. `## Summary` and `## Acceptance` produce IDs `S1.1` and `S1.2` under
the `# Design: Example` root; the contract preflight reuses that parser.

Create `skills/agent-runway/evals/test_contract_preflight.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentrunway.contract import ContractError, build_run_contract, write_contract
from agentrunway.plan_parser import parse_plan


def _write_spec(path: Path) -> None:
    path.write_text(
        "# Design: Example\n\n"
        "## Summary\n\n"
        "Build the feature.\n\n"
        "## Acceptance\n\n"
        "The run SHALL verify the feature.\n",
        encoding="utf-8",
    )


def _write_plan(path: Path, *, spec_ref: str = "S1.1", acceptance: str = "python -m pytest") -> None:
    path.write_text(
        "## Task 1: Example\n\n"
        "```yaml agentrunway-task\n"
        "task_id: task_001\n"
        "title: Example\n"
        "risk: low\n"
        "phase: implementation\n"
        "dependencies: []\n"
        f"spec_refs: [{spec_ref}]\n"
        "file_claims:\n"
        "  - {path: src/example.py, mode: owned}\n"
        f"acceptance_commands: [{acceptance}]\n"
        "required_skills: [test-driven-development]\n"
        "```\n"
        "Implement the example.\n",
        encoding="utf-8",
    )


def test_build_run_contract_records_hashes_tasks_and_manifest(tmp_path: Path, git_repo: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    _write_spec(spec)
    _write_plan(plan)
    tasks = parse_plan(plan)

    contract = build_run_contract(
        run_id="run-1",
        workspace_id="workspace-1",
        repo_root=git_repo,
        spec_path=spec,
        plan_path=plan,
        base_commit_sha="abc123",
        tasks=tasks,
        adapter="codex",
        model_profile="default",
        allow_dirty_source=False,
        apply_to_source=False,
    )

    assert contract.run_id == "run-1"
    assert contract.spec["path"] == str(spec)
    assert contract.plan["path"] == str(plan)
    assert contract.spec["manifest_sections"]["S1.1"] == "Summary"
    assert contract.spec["manifest_sections"]["S1.2"] == "Acceptance"
    assert contract.tasks[0]["task_id"] == "task_001"
    assert contract.tasks[0]["spec_refs"] == ["S1.1"]
    assert contract.coverage["unreferenced"] == ["S1", "S1.2"]


def test_contract_rejects_missing_spec_refs(tmp_path: Path, git_repo: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    _write_spec(spec)
    _write_plan(plan, spec_ref="S404")

    with pytest.raises(ContractError, match="missing spec_refs: task_001 -> S404"):
        build_run_contract(
            run_id="run-1",
            workspace_id="workspace-1",
            repo_root=git_repo,
            spec_path=spec,
            plan_path=plan,
            base_commit_sha="abc123",
            tasks=parse_plan(plan),
            adapter="codex",
            model_profile="default",
            allow_dirty_source=False,
            apply_to_source=False,
        )


def test_contract_rejects_empty_acceptance_commands(git_repo: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    _write_spec(spec)
    _write_plan(plan, acceptance="")

    with pytest.raises(ContractError, match="task_001 has no acceptance commands"):
        build_run_contract(
            run_id="run-1",
            workspace_id="workspace-1",
            repo_root=git_repo,
            spec_path=spec,
            plan_path=plan,
            base_commit_sha="abc123",
            tasks=parse_plan(plan),
            adapter="codex",
            model_profile="default",
            allow_dirty_source=False,
            apply_to_source=False,
        )


def test_write_contract_creates_immutable_contract_json(tmp_path: Path, git_repo: Path) -> None:
    spec = git_repo / "spec.md"
    plan = git_repo / "plan.md"
    run_dir = tmp_path / "run"
    _write_spec(spec)
    _write_plan(plan)
    contract = build_run_contract(
        run_id="run-1",
        workspace_id="workspace-1",
        repo_root=git_repo,
        spec_path=spec,
        plan_path=plan,
        base_commit_sha="abc123",
        tasks=parse_plan(plan),
        adapter="local",
        model_profile="default",
        allow_dirty_source=False,
        apply_to_source=False,
    )

    path = write_contract(run_dir, contract)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path == run_dir / "contract.json"
    assert payload["run_id"] == "run-1"
    assert payload["coverage"]["covered"] == ["S1.1"]


def test_build_run_contract_requires_spec_for_non_local_adapter(tmp_path: Path, git_repo: Path) -> None:
    plan = git_repo / "plan.md"
    _write_plan(plan)
    tasks = parse_plan(plan)

    with pytest.raises(ContractError, match="non-local adapter requires --spec"):
        build_run_contract(
            run_id="run-1",
            workspace_id="workspace-1",
            repo_root=git_repo,
            spec_path=None,
            plan_path=plan,
            base_commit_sha="abc123",
            tasks=tasks,
            adapter="codex",
            model_profile="default",
            allow_dirty_source=False,
            apply_to_source=False,
        )
```

- [ ] **Step 2: Run the failing contract tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_contract_preflight.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentrunway.contract'`.

- [ ] **Step 3: Add run contract dataclasses**

In `skills/agent-runway/scripts/agentrunway/models.py`, add these dataclasses after `WorkerResult`:

```python
@dataclass(frozen=True)
class RunContract:
    run_id: str
    workspace_id: str
    repo_root: str
    base_commit_sha: str
    spec: dict[str, Any]
    plan: dict[str, Any]
    tasks: tuple[dict[str, Any], ...]
    adapter: str
    model_profile: str
    policy: dict[str, Any]
    coverage: dict[str, list[str]]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactGraphNode:
    id: str
    kind: str
    status: str
    path: str | None = None
    task_id: str | None = None
    worker_id: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ReconciliationAction:
    target: str
    action: str
    reason: str
    writes: bool = False
```

- [ ] **Step 4: Implement `contract.py`**

The implementation reuses the heading-based parser from `plan_parser.py` so
section IDs match every existing fixture and worker prompt slice.

Create `skills/agent-runway/scripts/agentrunway/contract.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import RunContract, TaskSpec
from .plan_parser import canonical_hash, parse_spec_manifest


class ContractError(ValueError):
    pass


def parse_spec_manifest_sections(spec_path: Path) -> dict[str, str]:
    manifest = parse_spec_manifest(spec_path)
    sections = {
        section_id: data["title"]
        for section_id, data in manifest["sections"].items()
    }
    if not sections:
        raise ContractError(f"spec manifest is missing or empty: {spec_path}")
    return sections


def _task_to_contract(task: TaskSpec) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "risk": task.risk,
        "phase": task.phase,
        "dependencies": list(task.dependencies),
        "spec_refs": list(task.spec_refs),
        "file_claims": [{"path": claim.path, "mode": claim.mode} for claim in task.file_claims],
        "acceptance_commands": list(task.acceptance_commands),
        "resource_keys": list(task.resource_keys),
        "required_skills": list(task.required_skills),
        "serial": task.serial,
        "line": task.line,
    }


def _validate_tasks(tasks: list[TaskSpec], manifest_sections: dict[str, str]) -> tuple[dict[str, list[str]], tuple[str, ...]]:
    covered: set[str] = set()
    warnings: list[str] = []
    for task in tasks:
        missing_refs = [ref for ref in task.spec_refs if ref not in manifest_sections]
        if missing_refs:
            raise ContractError(f"missing spec_refs: {task.task_id} -> {', '.join(missing_refs)}")
        if not task.acceptance_commands or any(not command.strip() for command in task.acceptance_commands):
            raise ContractError(f"{task.task_id} has no acceptance commands")
        if task.phase == "implementation" and not task.file_claims:
            raise ContractError(f"{task.task_id} has no file claims")
        for claim in task.file_claims:
            if claim.path in {"*", "**", "**/*"}:
                warnings.append(f"{task.task_id} has broad file claim {claim.path}")
        covered.update(task.spec_refs)
    unreferenced = sorted(set(manifest_sections) - covered)
    warnings.extend(f"unreferenced spec section {ref}" for ref in unreferenced)
    return {"covered": sorted(covered), "partial": [], "blocked": [], "unreferenced": unreferenced}, tuple(warnings)


NON_LOCAL_ADAPTERS = {"codex", "claude"}


def build_run_contract(
    *,
    run_id: str,
    workspace_id: str,
    repo_root: Path,
    spec_path: Path | None,
    plan_path: Path,
    base_commit_sha: str,
    tasks: list[TaskSpec],
    adapter: str,
    model_profile: str,
    allow_dirty_source: bool,
    apply_to_source: bool,
) -> RunContract:
    if spec_path is None:
        if adapter in NON_LOCAL_ADAPTERS:
            raise ContractError(
                f"non-local adapter requires --spec: adapter={adapter}"
            )
        manifest_sections: dict[str, str] = {}
        coverage = {"covered": [], "partial": [], "blocked": [], "unreferenced": []}
        warnings: tuple[str, ...] = ()
        spec_entry: dict[str, object] = {"path": None, "hash": None, "manifest_sections": {}}
    else:
        manifest_sections = parse_spec_manifest_sections(spec_path)
        coverage, warnings = _validate_tasks(tasks, manifest_sections)
        spec_entry = {
            "path": str(spec_path),
            "hash": canonical_hash(spec_path),
            "manifest_sections": manifest_sections,
        }
    return RunContract(
        run_id=run_id,
        workspace_id=workspace_id,
        repo_root=str(repo_root),
        base_commit_sha=base_commit_sha,
        spec=spec_entry,
        plan={
            "path": str(plan_path),
            "hash": canonical_hash(plan_path),
            "task_count": len(tasks),
        },
        tasks=tuple(_task_to_contract(task) for task in tasks),
        adapter=adapter,
        model_profile=model_profile,
        policy={
            "allow_dirty_source": bool(allow_dirty_source),
            "apply_to_source": bool(apply_to_source),
        },
        coverage=coverage,
        warnings=warnings,
    )


def write_contract(run_dir: Path, contract: RunContract) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "contract.json"
    if path.exists():
        raise ContractError(f"contract already exists: {path}")
    path.write_text(json.dumps(asdict(contract), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
```

- [ ] **Step 5: Add DB storage for contract path**

In `skills/agent-runway/scripts/agentrunway/db.py`, add a `contract_path` column to the `runs` table definition:

```sql
contract_path TEXT,
```

Place it after `spec_path TEXT`. `CREATE TABLE IF NOT EXISTS` will not add
columns to pre-existing SQLite files, so also extend `AgentRunwayDb.open` to
run a guarded `ALTER TABLE` for older runs:

```python
    def _ensure_runs_contract_path_column(self) -> None:
        columns = {
            str(item["name"])
            for item in self.conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        if "contract_path" not in columns:
            self.conn.execute("ALTER TABLE runs ADD COLUMN contract_path TEXT")
            self.conn.commit()
```

Call `_ensure_runs_contract_path_column` from `open` right after
`executescript(SCHEMA_SQL)`. Then add:

```python
    def set_run_contract_path(self, run_id: str, contract_path: str) -> None:
        self.conn.execute(
            "UPDATE runs SET contract_path=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            (contract_path, run_id),
        )
        self.conn.commit()
```

- [ ] **Step 6: Wire contract creation into `runner.run`**

In `skills/agent-runway/scripts/agentrunway/runner.py`, import:

```python
from .contract import ContractError, build_run_contract, write_contract
```

After `tasks = parse_plan(plan)` and before packet creation, add:

```python
    contract = build_run_contract(
        run_id=run_id,
        workspace_id=wsid,
        repo_root=repo,
        spec_path=spec,
        plan_path=plan,
        base_commit_sha=base_commit,
        tasks=tasks,
        adapter=args.adapter,
        model_profile=cfg.default_profile,
        allow_dirty_source=bool(args.allow_dirty_source),
        apply_to_source=bool(args.apply_to_source),
    )
    contract_path = write_contract(run_dir, contract)
    db.set_run_contract_path(run_id, str(contract_path))
```

The `--spec` requirement for production adapters is enforced inside
`build_run_contract` (Step 4 of this task). Planning-only runs and the
`local` adapter are still allowed to omit `--spec` because the contract
falls back to an empty manifest in that case, and `_spec_slices` already
returns `[]` for a missing spec. No existing fixture needs to grow a spec
just for the contract step.

- [ ] **Step 7: Run contract tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_contract_preflight.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Run existing parser and planning tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_runner_planning_slice.py evals/test_plan_parser.py -v
```

Expected: all tests pass. Because the contract reuses the existing
heading-based `parse_spec_manifest`, no fixture spec needs to gain a new
`## Spec Manifest` section; existing `## Heading`-derived IDs (e.g. `S1.1`)
remain valid.

- [ ] **Step 9: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/contract.py \
  skills/agent-runway/scripts/agentrunway/models.py \
  skills/agent-runway/scripts/agentrunway/db.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/evals/test_contract_preflight.py
git commit -m "feat: freeze AgentRunway run contracts"
```

## Task 2: Event Journal and AgentLens Outbox

```yaml agentrunway-task
task_id: task_002
title: Event journal and AgentLens outbox
risk: medium
phase: implementation
dependencies: [task_001]
spec_refs: [S7, S9, S13, S14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/events.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/db.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/evals/test_event_journal_agentlens.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_event_journal_agentlens.py evals/test_events_merge_queue.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/events.py`
- Modify: `skills/agent-runway/scripts/agentrunway/db.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Create: `skills/agent-runway/evals/test_event_journal_agentlens.py`

- [ ] **Step 1: Write failing event journal tests**

Create `skills/agent-runway/evals/test_event_journal_agentlens.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.events import EventJournal, build_event_payload


class FailingEmitter:
    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        raise RuntimeError(f"agentlens down for {event_type}")


def test_event_journal_writes_events_jsonl_and_db_outbox(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    journal = EventJournal(db=db, run_dir=run_dir, agentlens_emitter=None)

    record = journal.record(
        "agentrunway.run_started",
        build_event_payload("run-1", "run", "success", "started", token="secret-value"),
    )

    assert record.event_type == "agentrunway.run_started"
    assert record.status == "agentlens_disabled"
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event_type"] == "agentrunway.run_started"
    assert payload["payload"]["token"] == "[REDACTED]"

    rows = db.list_events()
    assert rows[0]["event_type"] == "agentrunway.run_started"
    assert rows[0]["status"] == "agentlens_disabled"


def test_event_journal_records_agentlens_failure_without_raising(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    journal = EventJournal(db=db, run_dir=run_dir, agentlens_emitter=FailingEmitter())

    record = journal.record(
        "agentrunway.contract_created",
        build_event_payload("run-1", "contract", "success", "contract created"),
    )

    assert record.status == "agentlens_failed"
    assert "agentlens down" in str(record.error)
    rows = db.list_events()
    assert rows[0]["status"] == "agentlens_failed"
    assert "agentlens down" in str(rows[0]["error"])


def test_event_journal_query_returns_redacted_payloads(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    journal = EventJournal(db=db, run_dir=run_dir)
    journal.record(
        "agentrunway.worker_result",
        build_event_payload("run-1", "worker", "success", "done", path=str(home / "repo")),
    )

    events = journal.list()

    assert events[0]["payload"]["path"] == "~/repo"
```

- [ ] **Step 2: Run the failing event tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_event_journal_agentlens.py -v
```

Expected: FAIL with missing `EventJournal` or `list_events`.

- [ ] **Step 3: Add event DB repository methods**

In `skills/agent-runway/scripts/agentrunway/db.py`, add:

```python
    def insert_event(self, *, event_type: str, payload: dict[str, Any], status: str, error: str | None = None) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO agentlens_events (event_type, payload_json, status, error)
            VALUES (?, ?, ?, ?)
            """,
            (event_type, json.dumps(payload, ensure_ascii=False, sort_keys=True), status, error),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def list_events(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM agentlens_events ORDER BY id").fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["payload"] = json.loads(data.pop("payload_json"))
            events.append(data)
        return events

    def agentlens_summary(self) -> dict[str, Any]:
        rows = self.list_events()
        failed = [row for row in rows if row["status"] == "agentlens_failed"]
        emitted = [row for row in rows if row["status"] == "agentlens_emitted"]
        return {
            "events": len(rows),
            "emitted": len(emitted),
            "failed": len(failed),
            "last_status": rows[-1]["status"] if rows else "none",
        }
```

- [ ] **Step 4: Implement `EventJournal`**

Replace `write_event_artifact` in `skills/agent-runway/scripts/agentrunway/events.py` with a backward-compatible wrapper around `EventJournal`. Add:

```python
from dataclasses import dataclass
from typing import Protocol

from .db import AgentRunwayDb


class AgentLensEmitter(Protocol):
    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        ...


@dataclass(frozen=True)
class EventRecord:
    id: int
    event_type: str
    status: str
    payload: dict[str, Any]
    error: str | None = None


class EventJournal:
    def __init__(self, *, db: AgentRunwayDb, run_dir: Path, agentlens_emitter: AgentLensEmitter | None = None):
        self.db = db
        self.run_dir = run_dir
        self.agentlens_emitter = agentlens_emitter
        self.events_path = run_dir / "events.jsonl"

    def record(self, event_type: str, payload: dict[str, Any]) -> EventRecord:
        redacted = redact_payload(payload)
        status = "agentlens_disabled"
        error: str | None = None
        if self.agentlens_emitter is not None:
            try:
                self.agentlens_emitter.emit(event_type, redacted)
            except Exception as exc:
                status = "agentlens_failed"
                error = str(exc)
            else:
                status = "agentlens_emitted"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        event_line = {"event_type": event_type, "payload": redacted, "status": status, "error": error}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event_line, ensure_ascii=False, sort_keys=True) + "\n")
        event_id = self.db.insert_event(event_type=event_type, payload=redacted, status=status, error=error)
        return EventRecord(id=event_id, event_type=event_type, status=status, payload=redacted, error=error)

    def list(self) -> list[dict[str, Any]]:
        return self.db.list_events()
```

Keep this wrapper for existing tests:

```python
def write_event_artifact(run_dir: Path, event_type: str, payload: dict[str, Any]) -> Path:
    event_dir = run_dir / "events"
    event_dir.mkdir(parents=True, exist_ok=True)
    safe_type = event_type.replace("/", "_").replace(" ", "_")
    path = event_dir / f"{safe_type}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_payload(payload), ensure_ascii=False, sort_keys=True) + "\n")
    return path
```

- [ ] **Step 5: Emit initial runner events**

In `runner.py`, import `EventJournal` and `build_event_payload`. After DB creation and contract write, create:

```python
    journal = EventJournal(db=db, run_dir=run_dir)
    journal.record("agentrunway.run_started", build_event_payload(run_id, "run", "success", "run started"))
    journal.record(
        "agentrunway.contract_created",
        build_event_payload(run_id, "contract", "success", "contract created", contract_path=str(contract_path)),
    )
```

Before returning from a finished run, add:

```python
    journal.record("agentrunway.run_finished", build_event_payload(run_id, "run", "success", "run finished"))
```

- [ ] **Step 6: Run event tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_event_journal_agentlens.py evals/test_events_merge_queue.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/events.py \
  skills/agent-runway/scripts/agentrunway/db.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/evals/test_event_journal_agentlens.py
git commit -m "feat: record AgentRunway event journal"
```

## Task 3: Artifact Graph, Coverage, and JSON Diagnostics

```yaml agentrunway-task
task_id: task_003
title: Artifact graph, coverage, and JSON diagnostics
risk: medium
phase: implementation
dependencies: [task_002]
spec_refs: [S4, S7, S8, S9, S13, S14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/artifact_graph.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/status.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/invocation.py, mode: owned}
  - {path: skills/agent-runway/evals/test_artifact_graph_status.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_artifact_graph_status.py evals/test_status_watchdog_cost.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/artifact_graph.py`
- Modify: `skills/agent-runway/scripts/agentrunway/status.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`
- Create: `skills/agent-runway/evals/test_artifact_graph_status.py`

- [ ] **Step 1: Write failing artifact graph diagnostics tests**

Create `skills/agent-runway/evals/test_artifact_graph_status.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentrunway.artifact_graph import build_artifact_graph, write_artifact_graph
from agentrunway.db import AgentRunwayDb
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.status import build_inspect_payload, format_inspect_payload


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Example",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )


def test_artifact_graph_marks_contract_packet_result_and_merge_nodes(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "contract.json").parent.mkdir(parents=True)
    (run_dir / "contract.json").write_text(json.dumps({"coverage": {"covered": ["S1"], "unreferenced": ["S2"]}}), encoding="utf-8")
    (run_dir / "packets").mkdir()
    (run_dir / "packets" / "task_001.json").write_text("{}", encoding="utf-8")
    (run_dir / "artifacts" / "task_001" / "task_001-implementer-001").mkdir(parents=True)
    (run_dir / "artifacts" / "task_001" / "task_001-implementer-001" / "worker_result.json").write_text("{}", encoding="utf-8")
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(run_dir / "worker"),
        branch="agentrunway/run-1/task_001-implementer-001",
        state="merged",
        handle_json={},
    )
    db.enqueue_merge_candidate(
        task_id="task_001",
        worker_id="task_001-implementer-001",
        commits=("abc123",),
        changed_files=("src/example.py",),
        status="merged",
    )

    graph = build_artifact_graph(run_dir=run_dir, db=db)

    statuses = {node["id"]: node["status"] for node in graph["nodes"]}
    assert statuses["contract"] == "done"
    assert statuses["task_001:packet"] == "done"
    assert statuses["task_001:task_001-implementer-001:worker_result"] == "done"
    assert statuses["task_001:task_001-implementer-001:merge_candidate"] == "done"
    assert graph["coverage"]["covered"] == ["S1"]


def test_write_artifact_graph_creates_json_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    payload = write_artifact_graph(run_dir=run_dir, db=db)
    assert (run_dir / "artifact_graph.json").exists()
    assert payload["nodes"][0]["id"] == "contract"


def test_inspect_payload_includes_agentlens_and_coverage(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.insert_event(event_type="agentrunway.run_started", payload={"run_id": "run-1"}, status="agentlens_failed", error="down")
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-1", "status": "finished", "run_dir": str(run_dir), "state_db": str(run_dir / "state.sqlite")}),
        encoding="utf-8",
    )
    (run_dir / "coverage.json").write_text(json.dumps({"covered": ["S1"], "partial": [], "blocked": [], "unreferenced": []}), encoding="utf-8")

    payload = build_inspect_payload(run_json=json.loads((run_dir / "run.json").read_text()), db=db)
    text = format_inspect_payload(payload)

    assert payload["agentlens"]["failed"] == 1
    assert payload["coverage"]["covered"] == ["S1"]
    assert "agentlens_failed=1" in text
```

- [ ] **Step 2: Run the failing artifact graph tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_artifact_graph_status.py -v
```

Expected: FAIL with missing `agentrunway.artifact_graph`.

- [ ] **Step 3: Implement `artifact_graph.py`**

Create `skills/agent-runway/scripts/agentrunway/artifact_graph.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import AgentRunwayDb


def _status_for_path(path: Path) -> str:
    return "done" if path.exists() else "missing"


def _load_coverage(run_dir: Path) -> dict[str, list[str]]:
    contract_path = run_dir / "contract.json"
    if contract_path.exists():
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        coverage = contract.get("coverage", {})
        return {
            "covered": list(coverage.get("covered", [])),
            "partial": list(coverage.get("partial", [])),
            "blocked": list(coverage.get("blocked", [])),
            "unreferenced": list(coverage.get("unreferenced", [])),
        }
    return {"covered": [], "partial": [], "blocked": [], "unreferenced": []}


def build_artifact_graph(*, run_dir: Path, db: AgentRunwayDb) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "contract", "kind": "contract", "status": _status_for_path(run_dir / "contract.json"), "path": str(run_dir / "contract.json")},
        {"id": "events", "kind": "events", "status": _status_for_path(run_dir / "events.jsonl"), "path": str(run_dir / "events.jsonl")},
    ]
    for task in db.list_tasks():
        task_id = str(task["task_id"])
        nodes.append({"id": f"{task_id}:packet", "kind": "task_packet", "task_id": task_id, "status": _status_for_path(run_dir / "packets" / f"{task_id}.json")})
    for worker in db.list_workers():
        task_id = str(worker["task_id"])
        worker_id = str(worker["worker_id"])
        result_name = "worker_result.json"
        if worker["role"] == "reviewer":
            result_name = "review_result.json"
        if worker["role"] == "verifier":
            result_name = "verification_result.json"
        result_path = run_dir / "artifacts" / task_id / worker_id / result_name
        nodes.append({
            "id": f"{task_id}:{worker_id}:{result_name.removesuffix('.json')}",
            "kind": result_name.removesuffix(".json"),
            "task_id": task_id,
            "worker_id": worker_id,
            "status": _status_for_path(result_path),
            "path": str(result_path),
        })
    for candidate in db.list_merge_candidates():
        status = "done" if candidate["status"] == "merged" else "failed" if candidate["status"] == "merge_conflict" else "ready"
        nodes.append({
            "id": f"{candidate['task_id']}:{candidate['worker_id']}:merge_candidate",
            "kind": "merge_candidate",
            "task_id": candidate["task_id"],
            "worker_id": candidate["worker_id"],
            "status": status,
            "detail": candidate["status"],
        })
    return {"nodes": nodes, "coverage": _load_coverage(run_dir)}


def write_artifact_graph(*, run_dir: Path, db: AgentRunwayDb) -> dict[str, Any]:
    payload = build_artifact_graph(run_dir=run_dir, db=db)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "artifact_graph.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (run_dir / "coverage.json").write_text(json.dumps(payload["coverage"], ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return payload
```

- [ ] **Step 4: Add `list_workers` to DB**

In `db.py`, add:

```python
    def list_workers(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM workers ORDER BY worker_id").fetchall()
        workers: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["handle_json"] = json.loads(data["handle_json"])
            workers.append(data)
        return workers
```

- [ ] **Step 5: Implement inspect/status payloads**

In `status.py`, keep `format_run_status` and add:

```python
import json
from pathlib import Path
from typing import Any

from .artifact_graph import build_artifact_graph
from .db import AgentRunwayDb


def build_inspect_payload(*, run_json: dict[str, Any], db: AgentRunwayDb) -> dict[str, Any]:
    run_dir = Path(str(run_json["run_dir"]))
    graph = build_artifact_graph(run_dir=run_dir, db=db)
    coverage_path = run_dir / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else graph["coverage"]
    return {
        "run_id": run_json.get("run_id"),
        "status": run_json.get("status"),
        "run_dir": str(run_dir),
        "tasks": db.list_tasks(),
        "workers": db.list_workers(),
        "merge_candidates": db.list_merge_candidates(),
        "artifact_graph": graph,
        "coverage": coverage,
        "agentlens": db.agentlens_summary(),
    }


def format_inspect_payload(payload: dict[str, Any]) -> str:
    agentlens = payload.get("agentlens", {})
    coverage = payload.get("coverage", {})
    return (
        f"{payload.get('run_id')} status={payload.get('status')} "
        f"tasks={len(payload.get('tasks', []))} "
        f"workers={len(payload.get('workers', []))} "
        f"covered={len(coverage.get('covered', []))} "
        f"blocked={len(coverage.get('blocked', []))} "
        f"agentlens_failed={agentlens.get('failed', 0)}"
    )
```

- [ ] **Step 6: Wire inspect/events JSON command output**

In `runner.inspect`, open the DB and return `build_inspect_payload(...)` instead of the current minimal task list.

In `runner.events`, open the DB and return:

```python
    db = AgentRunwayDb.open(Path(data["state_db"]))
    return {"run_id": run_id, "events": db.list_events(), "agentlens": db.agentlens_summary()}
```

In `invocation.py`, add `--json` to `status`, `inspect`, `events`, and `resume` parsers:

```python
        cmd.add_argument("--json", action="store_true")
```

The command can continue printing JSON for all payloads in this slice; the flag reserves a stable interface and keeps backwards compatibility for scripts already parsing JSON.

- [ ] **Step 7: Refresh artifact graph during run**

In `runner.run`, call `write_artifact_graph(run_dir=run_dir, db=db)` after contract creation and after merge processing. Import it from `artifact_graph.py`.

- [ ] **Step 8: Run artifact graph and status tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_artifact_graph_status.py evals/test_status_watchdog_cost.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/artifact_graph.py \
  skills/agent-runway/scripts/agentrunway/status.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/scripts/agentrunway/invocation.py \
  skills/agent-runway/scripts/agentrunway/db.py \
  skills/agent-runway/evals/test_artifact_graph_status.py
git commit -m "feat: expose AgentRunway run diagnostics"
```

## Task 4: Reconciliation Planner and Resume Dry Run

```yaml agentrunway-task
task_id: task_004
title: Reconciliation planner and resume dry run
risk: high
phase: implementation
dependencies: [task_003]
spec_refs: [S10, S12, S13, S14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/reconciliation.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/watchdog.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/invocation.py, mode: owned}
  - {path: skills/agent-runway/evals/test_reconciliation.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_reconciliation.py evals/test_resume_apply.py evals/test_status_watchdog_cost.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Create: `skills/agent-runway/scripts/agentrunway/reconciliation.py`
- Modify: `skills/agent-runway/scripts/agentrunway/watchdog.py`
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/invocation.py`
- Create: `skills/agent-runway/evals/test_reconciliation.py`

- [ ] **Step 1: Write failing reconciliation tests**

Create `skills/agent-runway/evals/test_reconciliation.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from agentrunway.db import AgentRunwayDb
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.reconciliation import apply_reconciliation_plan, plan_reconciliation


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Example",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )


def test_plan_reconciliation_reconciles_valid_result_artifact_forward(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "worker"),
        branch="agentrunway/run/task_001-implementer-001",
        state="running",
        handle_json={},
    )
    result_path = run_dir / "artifacts" / "task_001" / "task_001-implementer-001" / "worker_result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps({
            "schema": "agentrunway.worker_result.v1",
            "worker_id": "task_001-implementer-001",
            "task_id": "task_001",
            "role": "implementer",
            "status": "success",
            "changed_files": [],
            "summary": "ok",
            "method_audit": {},
        }),
        encoding="utf-8",
    )

    plan = plan_reconciliation(run_id="run-1", run_dir=run_dir, db=db)

    assert plan["actions"] == [
        {
            "target": "task_001-implementer-001",
            "action": "reconcile_forward",
            "reason": "valid_result_artifact_exists",
            "writes": True,
        }
    ]


def test_plan_reconciliation_retries_dead_worker_missing_result(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "worker"),
        branch="agentrunway/run/task_001-implementer-001",
        state="running",
        handle_json={"pid": 999999},
    )

    plan = plan_reconciliation(run_id="run-1", run_dir=run_dir, db=db)

    assert plan["actions"][0]["action"] == "retry"
    assert plan["actions"][0]["reason"] == "dead_process_missing_result"


def test_apply_reconciliation_plan_is_idempotent_for_reconcile_forward(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.create_worker_attempt(
        worker_id="task_001-implementer-001",
        task_id="task_001",
        role="implementer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "worker"),
        branch="agentrunway/run/task_001-implementer-001",
        state="running",
        handle_json={},
    )
    plan = {
        "run_id": "run-1",
        "actions": [
            {
                "target": "task_001-implementer-001",
                "action": "reconcile_forward",
                "reason": "valid_result_artifact_exists",
                "writes": True,
            }
        ],
    }

    apply_reconciliation_plan(db=db, plan=plan)
    apply_reconciliation_plan(db=db, plan=plan)

    assert db.get_worker("task_001-implementer-001")["state"] == "result_collected"
    events = [row for row in db.list_events() if row["event_type"] == "agentrunway.resume_action"]
    assert len(events) == 1
```

- [ ] **Step 2: Run the failing reconciliation tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_reconciliation.py -v
```

Expected: FAIL with missing `agentrunway.reconciliation`.

- [ ] **Step 3: Implement `reconciliation.py`**

Scope for this slice is exactly two actions: `reconcile_forward` and
`retry`. `abort_cherry_pick`, `retain_orphan`, and `block` are reserved
names (see design S10's implementation-scope note) and must not be emitted
by the planner until their corresponding evidence detection lands in a
later slice.

Create `skills/agent-runway/scripts/agentrunway/reconciliation.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .db import AgentRunwayDb
from .events import build_event_payload
from .result_validation import ResultValidationError, validate_worker_result


def _result_path(run_dir: Path, worker: dict[str, Any]) -> Path:
    role = str(worker["role"])
    filename = "worker_result.json"
    if role == "reviewer":
        filename = "review_result.json"
    if role == "verifier":
        filename = "verification_result.json"
    return run_dir / "artifacts" / str(worker["task_id"]) / str(worker["worker_id"]) / filename


def _process_alive(handle_json: dict[str, Any]) -> bool:
    pid = handle_json.get("pid")
    if pid is None and isinstance(handle_json.get("process"), dict):
        pid = handle_json["process"].get("pid")
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def _valid_worker_result(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        validate_worker_result(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ResultValidationError):
        return False
    return True


def plan_reconciliation(*, run_id: str, run_dir: Path, db: AgentRunwayDb) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    for worker in db.list_workers():
        state = str(worker["state"])
        if state in {"merged", "blocked", "cancelled", "validated", "result_collected"}:
            continue
        result_path = _result_path(run_dir, worker)
        if _valid_worker_result(result_path):
            actions.append({
                "target": worker["worker_id"],
                "action": "reconcile_forward",
                "reason": "valid_result_artifact_exists",
                "writes": True,
            })
            continue
        if state == "running" and not _process_alive(worker.get("handle_json", {})):
            actions.append({
                "target": worker["worker_id"],
                "action": "retry",
                "reason": "dead_process_missing_result",
                "writes": True,
            })
    return {"run_id": run_id, "actions": actions}


def apply_reconciliation_plan(*, db: AgentRunwayDb, plan: dict[str, Any]) -> None:
    for action in plan.get("actions", []):
        target = str(action["target"])
        if action["action"] == "reconcile_forward":
            worker = db.get_worker(target)
            if worker["state"] != "result_collected":
                db.set_worker_state(target, "result_collected")
                db.insert_event(
                    event_type="agentrunway.resume_action",
                    payload=build_event_payload(str(plan["run_id"]), "resume", "success", "reconciled forward", target=target),
                    status="agentlens_disabled",
                )
        elif action["action"] == "retry":
            worker = db.get_worker(target)
            if worker["state"] == "running":
                db.set_worker_state(target, "stalled")
                db.insert_event(
                    event_type="agentrunway.resume_action",
                    payload=build_event_payload(str(plan["run_id"]), "resume", "partial", "retry required", target=target),
                    status="agentlens_disabled",
                )
```

- [ ] **Step 4: Wire resume dry-run**

In `invocation.py`, add to the `resume` parser only:

```python
    if command == "resume":
        cmd.add_argument("--dry-run", action="store_true")
```

If keeping the loop over commands, split `resume` into its own parser so `--dry-run` is not accepted by `status`, `inspect`, `events`, or `cancel`.

In `runner.resume`, change the signature:

```python
def resume(run_id: str, *, dry_run: bool = False) -> dict[str, Any]:
```

Then implement:

```python
    db = AgentRunwayDb.open(Path(data["state_db"]))
    plan = plan_reconciliation(run_id=run_id, run_dir=Path(data["run_dir"]), db=db)
    if dry_run:
        return plan
    apply_reconciliation_plan(db=db, plan=plan)
    return {"run_id": run_id, "status": data.get("status"), "run_dir": data.get("run_dir"), "reconciliation": plan}
```

Update `invocation.main`:

```python
        elif args.command == "resume":
            payload = runner.resume(args.run, dry_run=bool(args.dry_run))
```

- [ ] **Step 5: Keep watchdog classification helpers stable**

In `watchdog.py`, do not remove `classify_stall` or `classify_worker_snapshot`; existing tests depend on them. Add only a delegating helper:

```python
from pathlib import Path
from typing import Any

from .db import AgentRunwayDb
from .reconciliation import plan_reconciliation


def plan_watchdog_actions(*, run_id: str, run_dir: Path, db: AgentRunwayDb) -> dict[str, Any]:
    return plan_reconciliation(run_id=run_id, run_dir=run_dir, db=db)
```

- [ ] **Step 6: Run reconciliation tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_reconciliation.py evals/test_resume_apply.py evals/test_status_watchdog_cost.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/reconciliation.py \
  skills/agent-runway/scripts/agentrunway/watchdog.py \
  skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/scripts/agentrunway/invocation.py \
  skills/agent-runway/evals/test_reconciliation.py
git commit -m "feat: plan AgentRunway resume reconciliation"
```

## Task 5: Role-Generic Supervisor and Gate Packets

```yaml agentrunway-task
task_id: task_005
title: Role-generic supervisor and gate packets
risk: high
phase: implementation
dependencies: [task_004]
spec_refs: [S7, S11, S12, S13, S14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/packetizer.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/supervisor.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/result_validation.py, mode: owned}
  - {path: skills/agent-runway/evals/test_review_verify_gates.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && python -m pytest evals/test_review_verify_gates.py evals/test_result_validation.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/packetizer.py`
- Modify: `skills/agent-runway/scripts/agentrunway/supervisor.py`
- Modify: `skills/agent-runway/scripts/agentrunway/result_validation.py`
- Create: `skills/agent-runway/evals/test_review_verify_gates.py`

- [ ] **Step 1: Write failing gate helper tests**

Create `skills/agent-runway/evals/test_review_verify_gates.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentrunway.db import AgentRunwayDb
from agentrunway.models import FileClaim, TaskSpec
from agentrunway.packetizer import materialize_role_prompt
from agentrunway.result_validation import ResultValidationError
from agentrunway.supervisor import gate_review_result, gate_verification_result, next_worker_id


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task_001",
        title="Example",
        risk="low",
        phase="implementation",
        dependencies=(),
        spec_refs=("S1",),
        file_claims=(FileClaim(path="src/example.py", mode="owned"),),
        acceptance_commands=("python -m pytest",),
    )


def test_next_worker_id_counts_existing_role_attempts(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.create_worker_attempt(
        worker_id="task_001-reviewer-001",
        task_id="task_001",
        role="reviewer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "w1"),
        branch="b1",
        state="running",
        handle_json={},
    )

    assert next_worker_id(db=db, task_id="task_001", role="reviewer") == ("task_001-reviewer-002", 2)


def test_review_gate_rejects_approved_findings() -> None:
    with pytest.raises(ResultValidationError, match="approved review cannot include findings"):
        gate_review_result(
            {
                "schema": "agentrunway.review_result.v1",
                "worker_id": "task_001-reviewer-001",
                "task_id": "task_001",
                "reviewed_worker_id": "task_001-implementer-001",
                "status": "approved",
                "checks": [],
                "findings": [{"severity": "major", "body": "bug"}],
                "method_audit": {},
            }
        )


def test_verification_gate_accepts_passed_status() -> None:
    status = gate_verification_result(
        {
            "schema": "agentrunway.verification_result.v1",
            "worker_id": "task_001-verifier-001",
            "task_id": "task_001",
            "status": "passed",
            "checks": [{"command": "python -m pytest", "status": "passed"}],
            "method_audit": {},
        }
    )
    assert status == "passed"


def test_materialize_role_prompt_names_output_schema(tmp_path: Path) -> None:
    output_path = tmp_path / "review_result.json"
    prompt_path = materialize_role_prompt(
        role="reviewer",
        task=_task(),
        worker_id="task_001-reviewer-001",
        packet_path=tmp_path / "task_001.json",
        output_path=output_path,
        prompt_dir=tmp_path,
        context={
            "reviewed_worker_id": "task_001-implementer-001",
            "diff": "diff --git a/src/example.py b/src/example.py",
        },
    )

    text = prompt_path.read_text(encoding="utf-8")
    assert "agentrunway.review_result.v1" in text
    assert str(output_path) in text
    assert "task_001-implementer-001" in text
```

- [ ] **Step 2: Run the failing gate tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_review_verify_gates.py -v
```

Expected: FAIL with missing `materialize_role_prompt` or `next_worker_id`.

- [ ] **Step 3: Add role prompt materialization**

In `packetizer.py`, add:

```python
def materialize_role_prompt(
    *,
    role: str,
    task: TaskSpec,
    worker_id: str,
    packet_path: Path,
    output_path: Path,
    prompt_dir: Path,
    context: dict[str, object],
) -> Path:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    schema = "agentrunway.review_result.v1" if role == "reviewer" else "agentrunway.verification_result.v1"
    path = prompt_dir / f"{task.task_id}.{role}.{worker_id}.prompt.txt"
    path.write_text(
        f"You are an AgentRunway {role}. Use using-superpowers.\n"
        f"Task: {task.task_id} - {task.title}\n"
        f"Packet path: {packet_path}\n"
        f"Output path: {output_path}\n"
        f"Write JSON with schema {schema}.\n"
        "Context JSON:\n"
        "```json\n"
        + json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n```\n",
        encoding="utf-8",
    )
    return path
```

- [ ] **Step 4: Add `next_worker_id` and role-aware worker helper**

In `supervisor.py`, add:

```python
def next_worker_id(*, db: AgentRunwayDb, task_id: str, role: str) -> tuple[str, int]:
    prefix = f"{task_id}-{role}-"
    attempts = [
        int(worker["worker_id"].removeprefix(prefix))
        for worker in db.list_workers()
        if str(worker["worker_id"]).startswith(prefix)
    ]
    attempt = max(attempts, default=0) + 1
    return f"{prefix}{attempt:03d}", attempt
```

Then extract common creation logic from `run_implementer_attempt` into a new function:

```python
def run_worker_attempt(
    *,
    db: AgentRunwayDb,
    run_id: str,
    git: Git,
    worktree_root: Path,
    run_dir: Path,
    task: TaskSpec,
    prompt_path: Path,
    output_path: Path,
    adapter: RuntimeAdapter,
    runtime: str,
    model: str,
    reasoning_effort: str,
    role: str,
    base_ref: str,
    attempt: int,
    timeout_seconds: int,
    metadata: dict[str, str] | None = None,
) -> WorkerResultEnvelope:
    worker_id = f"{task.task_id}-{role}-{attempt:03d}"
    branch = f"agentrunway/{run_id}/{worker_id}"
    worker_tree = create_worker_worktree(git, worktree_root / "workers" / worker_id, branch, base_ref)
    spec = WorkerSpec(
        run_id=run_id,
        task_id=task.task_id,
        worker_id=worker_id,
        role=role,
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        prompt_path=str(prompt_path),
        packet_path=str(run_dir / "packets" / f"{task.task_id}.json"),
        output_path=str(output_path),
        worktree_path=str(worker_tree),
        artifact_dir=str(output_path.parent),
        timeout_seconds=timeout_seconds,
        attempt=attempt,
        metadata=dict(metadata or {}),
    )
    db.create_worker_attempt(
        worker_id=worker_id,
        task_id=task.task_id,
        role=role,
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        attempt=attempt,
        worktree_path=str(worker_tree),
        branch=branch,
        state="worktree_created",
        handle_json={},
    )
    handle = adapter.start(adapter.prepare(spec))
    db.set_worker_state(worker_id, "running")
    db.update_worker_handle(worker_id, handle.to_json())
    envelope = adapter.collect(handle)
    db.set_worker_state(worker_id, "result_collected")
    return envelope
```

Keep `run_implementer_attempt` as a wrapper for compatibility until Task 7
rewires runner gate sequencing. While editing the wrapper, change its
`enqueue_merge_candidate(status="merge_ready")` call to
`status="pending_review"`. This is the critical state-race fix from the
review notes: without it, the existing merge loop in `runner.run` applies
implementer commits before reviewer/verifier ever run.

Also update `apply_candidate`/the runner merge loop filter so that only
candidates with status `merge_ready` are processed:

```python
for candidate in db.list_merge_candidates():
    if candidate["status"] != "merge_ready":
        continue
    ...
```

(This filter already exists in `runner.run`, so this change is just
verifying it remains in place after gate code lands.) Candidates promoted
by a passing verifier transition `pending_review -> merge_ready` via
`db.set_merge_candidate_status`.

- [ ] **Step 5: Tighten result validation statuses**

In `result_validation.py`, leave existing review and verification schema checks in place. Ensure `gate_review_result` raises `ResultValidationError` by not swallowing validation errors.

- [ ] **Step 6: Run gate helper tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_review_verify_gates.py evals/test_result_validation.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/packetizer.py \
  skills/agent-runway/scripts/agentrunway/supervisor.py \
  skills/agent-runway/scripts/agentrunway/result_validation.py \
  skills/agent-runway/evals/test_review_verify_gates.py
git commit -m "feat: prepare AgentRunway gate workers"
```

## Task 6: Production Review and Verification Gate Sequencing

```yaml agentrunway-task
task_id: task_006
title: Production review and verification gate sequencing
risk: high
phase: implementation
dependencies: [task_005]
spec_refs: [S11, S12, S13, S14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/supervisor.py, mode: owned}
  - {path: skills/agent-runway/evals/fixtures/fake-bin/codex, mode: owned}
  - {path: skills/agent-runway/evals/fixtures/fake-bin/claude, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: owned}
  - {path: skills/agent-runway/evals/test_review_verify_gates.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && PATH="$PWD/evals/fixtures/fake-bin:$PATH" python -m pytest evals/test_runner_production_e2e.py evals/test_review_verify_gates.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/supervisor.py`
- Modify: `skills/agent-runway/evals/fixtures/fake-bin/codex`
- Modify: `skills/agent-runway/evals/fixtures/fake-bin/claude`
- Modify: `skills/agent-runway/evals/test_runner_production_e2e.py`
- Modify: `skills/agent-runway/evals/test_review_verify_gates.py`

- [ ] **Step 1: Update production e2e tests for real gates**

In `skills/agent-runway/evals/test_runner_production_e2e.py`, remove
`--skip-review` and `--skip-verify` from the Codex and Claude production
runs. (The flags themselves are deleted from `invocation.py` in Step 6
below; once removed the parser will reject them, so the test command must
drop them at the same time as the CLI change.) Add assertions:

```python
    rows = conn.execute("SELECT role, state FROM workers ORDER BY worker_id").fetchall()
    states = [(row["role"], row["state"]) for row in rows]
    assert states == [
        ("implementer", "merged"),
        ("reviewer", "validated"),
        ("verifier", "validated"),
    ]
```

Update the merge candidate assertion:

```python
    assert candidate["status"] == "merged"
```

The full Codex test should still assert:

```python
    assert (main / "src" / "codex_worker.py").read_text(encoding="utf-8") == "VALUE = 'codex'\n"
```

The full Claude test should still assert:

```python
    assert (main / "src" / "claude_worker.py").read_text(encoding="utf-8") == "VALUE = 'claude'\n"
```

- [ ] **Step 2: Run the updated production e2e tests**

Run:

```bash
cd skills/agent-runway && PATH="$PWD/evals/fixtures/fake-bin:$PATH" python -m pytest evals/test_runner_production_e2e.py -v
```

Expected: FAIL because fake CLIs only emit worker results and runner still sends implementers directly to `merge_ready`.

- [ ] **Step 3: Make fake CLIs role-aware**

In both `evals/fixtures/fake-bin/codex` and `evals/fixtures/fake-bin/claude`, read:

```python
    role = os.environ.get("AGENTRUNWAY_WORKER_ROLE", "implementer")
```

For `role == "reviewer"`, write:

```python
    payload = {
        "schema": "agentrunway.review_result.v1",
        "worker_id": os.environ["AGENTRUNWAY_WORKER_ID"],
        "task_id": os.environ["AGENTRUNWAY_TASK_ID"],
        "reviewed_worker_id": os.environ.get("AGENTRUNWAY_REVIEWED_WORKER_ID", ""),
        "status": os.environ.get("AGENTRUNWAY_FAKE_REVIEW_STATUS", "approved"),
        "checks": [{"name": "fake review", "status": "passed"}],
        "findings": [],
        "method_audit": {"superpowers_used": True},
    }
```

For `role == "verifier"`, write:

```python
    payload = {
        "schema": "agentrunway.verification_result.v1",
        "worker_id": os.environ["AGENTRUNWAY_WORKER_ID"],
        "task_id": os.environ["AGENTRUNWAY_TASK_ID"],
        "status": os.environ.get("AGENTRUNWAY_FAKE_VERIFY_STATUS", "passed"),
        "checks": [{"command": "fake acceptance", "status": "passed"}],
        "method_audit": {"superpowers_used": True},
    }
```

Only implementer role should edit files and create commits.

- [ ] **Step 4: Pass gate metadata through adapters**

In `CodexAdapter.prepare` and `ClaudeAdapter.prepare`, include optional environment values from `WorkerSpec` metadata if present. The simplest implementation is to add fields to `WorkerSpec` in `models.py`:

```python
    metadata: dict[str, str] = field(default_factory=dict)
```

Then in both adapters' `env={...}` dictionaries, append:

```python
                **spec.metadata,
```

If adding `metadata` to a frozen dataclass with a mutable default, use `field(default_factory=dict)` and import `field` from `dataclasses`.

`metadata` is opaque to the adapter and merged after the fixed AgentRunway
keys, so a reviewer attempt that wants the fake CLIs to read
`AGENTRUNWAY_REVIEWED_WORKER_ID` must put that key in the dict it passes to
`WorkerSpec(... metadata={"AGENTRUNWAY_REVIEWED_WORKER_ID": ...,
"AGENTRUNWAY_FAKE_REVIEW_STATUS": ...})`. This wiring happens in Step 5;
without it, the fake CLI sees an empty `reviewed_worker_id` field and the
review JSON fails validation.

- [ ] **Step 5: Add gate runner helper**

In `supervisor.py`, add `run_reviewer_attempt` and `run_verifier_attempt` wrappers around `run_worker_attempt`. Use `materialize_role_prompt`, validate the role-specific JSON, and set worker state to `validated` when the result passes.

Reviewer wrapper expected shape:

```python
def run_reviewer_attempt(
    *,
    db: AgentRunwayDb,
    run_id: str,
    git: Git,
    worktree_root: Path,
    run_dir: Path,
    task: TaskSpec,
    adapter: RuntimeAdapter,
    runtime: str,
    model: str,
    reasoning_effort: str,
    reviewed_worker_id: str,
    candidate_diff: str,
    attempt: int,
    timeout_seconds: int,
) -> dict[str, object]:
    worker_id = f"{task.task_id}-reviewer-{attempt:03d}"
    output_path = run_dir / "artifacts" / task.task_id / worker_id / "review_result.json"
    prompt_path = materialize_role_prompt(
        role="reviewer",
        task=task,
        worker_id=worker_id,
        packet_path=run_dir / "packets" / f"{task.task_id}.json",
        output_path=output_path,
        prompt_dir=run_dir / "prompts",
        context={"reviewed_worker_id": reviewed_worker_id, "diff": candidate_diff},
    )
    envelope = run_worker_attempt(
        db=db,
        run_id=run_id,
        git=git,
        worktree_root=worktree_root,
        run_dir=run_dir,
        task=task,
        prompt_path=prompt_path,
        output_path=output_path,
        adapter=adapter,
        runtime=runtime,
        model=model,
        reasoning_effort=reasoning_effort,
        role="reviewer",
        base_ref=f"agentrunway/{run_id}/main",
        attempt=attempt,
        timeout_seconds=timeout_seconds,
        metadata={
            "AGENTRUNWAY_REVIEWED_WORKER_ID": reviewed_worker_id,
        },
    )
    if envelope.result_json is None:
        db.set_worker_state(worker_id, "malformed_result")
        raise RuntimeError("missing_review_result")
    result = validate_review_result(envelope.result_json)
    db.set_worker_state(worker_id, "validated")
    return result
```

Verifier wrapper follows the same shape with `role="verifier"`, output file
`verification_result.json`, `validate_verification_result`, and context
containing commits, changed files, acceptance commands, and review status.
The verifier wrapper also forwards
`metadata={"AGENTRUNWAY_FAKE_VERIFY_STATUS": fake_verify_status}` when a
test injects an override; production runs leave `metadata` empty so the
verifier reads only the standard AgentRunway env keys.

- [ ] **Step 6: Rewire runner production path**

First, delete the dead `--skip-review` and `--skip-verify` arguments from
`invocation.py` (`run.add_argument("--skip-review", ...)` and its sibling).
Neither flag is read by `runner.run`, and once gates are mandatory they
have no meaningful semantics.

In `runner.run`, after `run_implementer_attempt` returns a candidate id, do
not set task status to `merge_ready`. The implementer's
`enqueue_merge_candidate` now produces status `pending_review` (Task 5
Step 4), so the existing merge loop will skip the candidate until a gate
promotes it. Then:

1. Set task status `reviewing`.
2. Run reviewer attempt.
3. If reviewer status is `changes_requested` or `rejected`, set task status
   `blocked`, leave the candidate at `pending_review`, and continue to the
   next task. (No silent retry in this slice — see review notes item 10.)
4. Set task status `verifying`.
5. Run verifier attempt.
6. If verifier status is `passed`, call
   `db.set_merge_candidate_status(candidate_id, "merge_ready")` and set
   task status `merge_ready`. The downstream merge loop will then apply
   the candidate as before.
7. If verifier status is `failed` or `blocked`, set task status `blocked`
   and leave the candidate at `pending_review`.

Emit local events for `review_dispatched`, `review_result`,
`verification_dispatched`, `verification_result`, and `merge_ready`.

Add a runner test that asserts the merge loop does not apply a candidate
while it is still at `pending_review`, even if the gate sequencing is
short-circuited (e.g. when a reviewer attempt raises an exception). This
prevents the state-race regression from quietly re-appearing.

- [ ] **Step 7: Run production e2e gate tests**

Run:

```bash
cd skills/agent-runway && PATH="$PWD/evals/fixtures/fake-bin:$PATH" python -m pytest evals/test_runner_production_e2e.py evals/test_review_verify_gates.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/scripts/agentrunway/supervisor.py \
  skills/agent-runway/scripts/agentrunway/models.py \
  skills/agent-runway/scripts/agentrunway/adapters/codex.py \
  skills/agent-runway/scripts/agentrunway/adapters/claude.py \
  skills/agent-runway/evals/fixtures/fake-bin/codex \
  skills/agent-runway/evals/fixtures/fake-bin/claude \
  skills/agent-runway/evals/test_runner_production_e2e.py \
  skills/agent-runway/evals/test_review_verify_gates.py
git commit -m "feat: require AgentRunway review and verify gates"
```

## Task 7: Gate Retry Policy and Blocked Coverage

```yaml agentrunway-task
task_id: task_007
title: Gate retry policy and blocked coverage
risk: high
phase: implementation
dependencies: [task_006]
spec_refs: [S10, S11, S12, S13, S14]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/db.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/artifact_graph.py, mode: owned}
  - {path: skills/agent-runway/evals/test_review_verify_gates.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && PATH="$PWD/evals/fixtures/fake-bin:$PATH" python -m pytest evals/test_review_verify_gates.py evals/test_artifact_graph_status.py -v
required_skills: [test-driven-development]
resource_keys: []
serial: true
```

**Files:**
- Modify: `skills/agent-runway/scripts/agentrunway/runner.py`
- Modify: `skills/agent-runway/scripts/agentrunway/db.py`
- Modify: `skills/agent-runway/scripts/agentrunway/artifact_graph.py`
- Modify: `skills/agent-runway/evals/test_review_verify_gates.py`

- [ ] **Step 1: Add tests for changes_requested and verifier failed**

Append to `test_review_verify_gates.py`:

```python
def test_review_changes_requested_blocks_after_budget(tmp_path: Path) -> None:
    db = AgentRunwayDb.open(tmp_path / "state.sqlite")
    db.upsert_task(_task())
    db.create_worker_attempt(
        worker_id="task_001-reviewer-001",
        task_id="task_001",
        role="reviewer",
        runtime="codex",
        model="gpt-5.5",
        reasoning_effort="high",
        attempt=1,
        worktree_path=str(tmp_path / "reviewer"),
        branch="reviewer",
        state="validated",
        handle_json={},
    )
    assert db.count_worker_attempts(task_id="task_001", role="reviewer") == 1


def test_coverage_marks_blocked_task_spec_refs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    db = AgentRunwayDb.open(run_dir / "state.sqlite")
    db.upsert_task(_task())
    db.set_task_status("task_001", "blocked")
    (run_dir / "contract.json").write_text(
        json.dumps({"coverage": {"covered": ["S1"], "partial": [], "blocked": [], "unreferenced": []}}),
        encoding="utf-8",
    )

    graph = build_artifact_graph(run_dir=run_dir, db=db)

    assert graph["coverage"]["blocked"] == ["S1"]
```

Import `build_artifact_graph` at the top of the file.

- [ ] **Step 2: Run the failing retry/coverage tests**

Run:

```bash
cd skills/agent-runway && python -m pytest evals/test_review_verify_gates.py -v
```

Expected: FAIL with missing `count_worker_attempts` or blocked coverage not updated.

- [ ] **Step 3: Add retry count helper**

In `db.py`, add:

```python
    def count_worker_attempts(self, *, task_id: str, role: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM workers WHERE task_id=? AND role=?",
            (task_id, role),
        ).fetchone()
        return int(row["count"])
```

- [ ] **Step 4: Update coverage derivation for blocked tasks**

In `artifact_graph.py`, after loading contract coverage, derive blocked refs from DB tasks:

```python
def _derive_coverage(run_dir: Path, db: AgentRunwayDb) -> dict[str, list[str]]:
    coverage = _load_coverage(run_dir)
    blocked_refs: set[str] = set(coverage.get("blocked", []))
    covered_refs: set[str] = set(coverage.get("covered", []))
    for task in db.list_tasks():
        refs = json.loads(task["spec_refs_json"]) if isinstance(task.get("spec_refs_json"), str) else []
        if task["status"] == "blocked":
            blocked_refs.update(refs)
            covered_refs.difference_update(refs)
    coverage["covered"] = sorted(covered_refs)
    coverage["blocked"] = sorted(blocked_refs)
    return coverage
```

Call `_derive_coverage` from `build_artifact_graph`.

- [ ] **Step 5: Apply bounded gate retry policy**

In `runner.py`, the production gate sequencing should treat any
non-`approved` review and any non-`passed` verification as a block, with
no silent retry. The earlier draft had a dead `if/else` that took the
same branch on both `changes_requested` and `rejected`; collapse it:

```python
review_status = str(review_result["status"])
if review_status != "approved":
    db.set_task_status(task.task_id, "blocked")
    continue

verify_status = str(verification_result["status"])
if verify_status != "passed":
    db.set_task_status(task.task_id, "blocked")
    continue
```

`count_worker_attempts` is still added in Step 3 because the design
records it for future retry-budget enforcement, but it is not consulted
here. The `test_review_changes_requested_blocks_after_budget` test in
Step 1 above only asserts that the helper reports the attempt count
correctly; the runner policy itself is "block on any non-pass" for this
slice. Real implementer redispatch with reviewer findings is tracked in
the deferred-tests list in design S13 and lands in a later slice.

- [ ] **Step 6: Run gate retry and coverage tests**

Run:

```bash
cd skills/agent-runway && PATH="$PWD/evals/fixtures/fake-bin:$PATH" python -m pytest evals/test_review_verify_gates.py evals/test_artifact_graph_status.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add skills/agent-runway/scripts/agentrunway/runner.py \
  skills/agent-runway/scripts/agentrunway/db.py \
  skills/agent-runway/scripts/agentrunway/artifact_graph.py \
  skills/agent-runway/evals/test_review_verify_gates.py
git commit -m "feat: block failed AgentRunway gates safely"
```

## Task 8: Documentation, References, and Full Verification

```yaml agentrunway-task
task_id: task_008
title: Documentation, references, and full verification
risk: medium
phase: documentation
dependencies: [task_007]
spec_refs: [S9, S10, S11, S12, S13, S14, S15]
file_claims:
  - {path: skills/agent-runway/README.md, mode: owned}
  - {path: skills/agent-runway/references/agentlens-events.md, mode: owned}
  - {path: skills/agent-runway/references/watchdog.md, mode: owned}
  - {path: skills/agent-runway/references/protocol.md, mode: owned}
  - {path: skills/agent-runway/evals/check_skill_contract.py, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && ./evals/run.sh
  - cd skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
  - cd skills/agent-runway && bash -n evals/run.sh
  - cd skills/agent-runway && python3 evals/check_skill_contract.py
  - git diff --check HEAD
required_skills: [verification-before-completion]
resource_keys: []
serial: true
```

**Files:**
- Modify: `skills/agent-runway/README.md`
- Modify: `skills/agent-runway/references/agentlens-events.md`
- Modify: `skills/agent-runway/references/watchdog.md`
- Modify: `skills/agent-runway/references/protocol.md`
- Modify: `skills/agent-runway/evals/check_skill_contract.py` only if command or event docs need a contract assertion update

- [ ] **Step 1: Update README operations section**

In `skills/agent-runway/README.md`, add:

```markdown
## Operations Evidence

Every non-planning run writes a frozen `contract.json`, `artifact_graph.json`,
`coverage.json`, and `events.jsonl` under `~/.agentrunway/runs/<workspace>/<run_id>/`.
The contract records the exact Superpowers spec and plan paths, hashes, parsed
tasks, file claims, acceptance commands, adapter, model profile, and `spec_refs`
coverage.

Use:

```bash
python3 skills/agent-runway/scripts/agentrunway.py status --run <run_id>
python3 skills/agent-runway/scripts/agentrunway.py inspect --run <run_id> --json
python3 skills/agent-runway/scripts/agentrunway.py events --run <run_id> --json
python3 skills/agent-runway/scripts/agentrunway.py resume --run <run_id> --dry-run --json
```

AgentLens emission is best-effort. Local evidence remains authoritative when
AgentLens is disabled or unavailable.
```

- [ ] **Step 2: Update AgentLens reference**

Replace `skills/agent-runway/references/agentlens-events.md` with:

```markdown
Source-of-truth: the design document wins when this reference and code disagree.

# AgentLens Events

AgentRunway records runner-validated facts locally before attempting AgentLens
emission. The local journal is `events.jsonl` in the run directory. SQLite table
`agentlens_events` is the outbox and stores one of:

- `agentlens_disabled` (no emitter configured; event is local-only)
- `agentlens_emitted` (emit attempt returned without raising)
- `agentlens_failed` (emit attempt raised; `error` column records the reason)

The local journal write always succeeds before the emit attempt, so every
status implies a durable `events.jsonl` row and a matching
`agentlens_events` row.

Core event types:

- `agentrunway.run_started`
- `agentrunway.contract_created`
- `agentrunway.worker_dispatched`
- `agentrunway.worker_result`
- `agentrunway.worker_rejected`
- `agentrunway.review_dispatched`
- `agentrunway.review_result`
- `agentrunway.verification_dispatched`
- `agentrunway.verification_result`
- `agentrunway.merge_ready`
- `agentrunway.merge_applied`
- `agentrunway.merge_conflict`
- `agentrunway.resume_planned`
- `agentrunway.resume_action`
- `agentrunway.apply_started`
- `agentrunway.apply_finished`
- `agentrunway.run_finished`
- `agentrunway.run_blocked`

Payloads are redacted before local write and before AgentLens emission. Home
paths become `~`; secret-like keys such as `token`, `api_key`, `secret`, and
`password` become `[REDACTED]`.
```

- [ ] **Step 3: Update watchdog reference**

Replace `skills/agent-runway/references/watchdog.md` with:

```markdown
Source-of-truth: the design document wins when this reference and code disagree.

# Watchdog and Resume Reconciliation

Resume starts by producing a reconciliation plan. `resume --dry-run --json`
returns that plan without writes. Non-dry-run resume applies the plan
idempotently.

Evidence sources:

- SQLite run, worker, task, merge, artifact, event, and applied commit rows
- `run.json`, `contract.json`, `artifact_graph.json`, `coverage.json`, `events.jsonl`
- worker result artifacts and stdout/stderr logs
- process liveness when a PID exists
- git branch heads, worktree paths, and cherry-pick state

Supported actions in this slice:

- `reconcile_forward`: valid artifact exists but DB state is behind
- `retry`: worker is dead and no valid result artifact is present

Reserved (not yet emitted by the planner — see design S10
implementation-scope note):

- `abort_cherry_pick`: run main has an interrupted cherry-pick
- `retain_orphan`: unmatched worktree is kept for diagnostics
- `block`: budget is exhausted or operator action is required

Resume must not duplicate terminal tasks, merge candidates, worker
attempts, or applied commits.
```

- [ ] **Step 4: Update protocol reference**

Append to `skills/agent-runway/references/protocol.md`:

```markdown
## Superpowers Contract Preflight

AgentRunway consumes Superpowers design and implementation plan documents. It
does not generate them. Before dispatch, the runner writes immutable
`contract.json` with:

- spec path and canonical hash
- plan path and canonical hash
- base commit and workspace id
- parsed task packets
- task `spec_refs`, file claims, dependencies, required skills, and acceptance commands
- adapter and model profile
- initial coverage summary

Preflight rejects missing `spec_refs`, empty acceptance commands, missing file
claims for implementation tasks, dirty source checkouts without explicit
allowance, and plans that cannot produce deterministic task packets.
```

- [ ] **Step 5: Run full eval suite**

Run:

```bash
cd skills/agent-runway && ./evals/run.sh
```

Expected: all tests pass.

- [ ] **Step 6: Run syntax and contract checks**

Run:

```bash
cd skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
cd skills/agent-runway && bash -n evals/run.sh
cd skills/agent-runway && python3 evals/check_skill_contract.py
git diff --check HEAD
```

Expected: every command exits 0.

- [ ] **Step 7: Update graphify after code changes**

Run from repo root:

```bash
graphify update .
```

Expected: `GRAPH_REPORT.md` is rebuilt from the current commit or working tree. If graphify reports the graph is too large for HTML visualization, that is acceptable as long as `graph.json` and `GRAPH_REPORT.md` update successfully.

- [ ] **Step 8: Commit**

Run:

```bash
git add skills/agent-runway/README.md \
  skills/agent-runway/references/agentlens-events.md \
  skills/agent-runway/references/watchdog.md \
  skills/agent-runway/references/protocol.md \
  skills/agent-runway/evals/check_skill_contract.py \
  graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "docs: document AgentRunway operations hardening"
```

If `graphify-out/graph.json` is ignored or unchanged, omit it from `git add`.

## Task 9: Residual Risk Closure

```yaml agentrunway-task
task_id: task_009
title: Residual gate retry and graphify evidence closure
risk: medium
phase: implementation
dependencies: [task_008]
spec_refs: [S11, S12, S13, S14, S15]
file_claims:
  - {path: skills/agent-runway/scripts/agentrunway/runner.py, mode: owned}
  - {path: skills/agent-runway/scripts/agentrunway/packetizer.py, mode: owned}
  - {path: skills/agent-runway/evals/test_runner_production_e2e.py, mode: owned}
  - {path: skills/agent-runway/evals/test_models_and_schemas.py, mode: owned}
  - {path: skills/agent-runway/evals/fixtures/fake-bin/codex, mode: owned}
  - {path: skills/agent-runway/evals/fixtures/fake-bin/claude, mode: owned}
  - {path: skills/agent-runway/references/schemas/review_result.v1.json, mode: owned}
  - {path: skills/agent-runway/README.md, mode: owned}
  - {path: skills/agent-runway/references/failure-policy.md, mode: owned}
  - {path: skills/agent-runway/references/merge-queue.md, mode: owned}
  - {path: skills/agent-runway/references/protocol.md, mode: owned}
  - {path: docs/superpowers/specs/2026-05-20-agent-runway-operations-hardening-design.md, mode: owned}
  - {path: docs/superpowers/plans/2026-05-20-agent-runway-operations-hardening.md, mode: owned}
acceptance_commands:
  - cd skills/agent-runway && PATH="$PWD/evals/fixtures/fake-bin:$PATH" python -m pytest evals/test_runner_production_e2e.py evals/test_models_and_schemas.py -v
  - cd skills/agent-runway && ./evals/run.sh
  - git diff --check HEAD
required_skills: [test-driven-development, verification-before-completion]
resource_keys: []
serial: true
```

Close the two known residual risks from the first implementation pass:

1. Implement bounded redispatch for reviewer `changes_requested` and verifier
   `failed` outcomes. Each retry must use a fresh implementer worker id,
   worktree, prompt, and merge candidate. The previous candidate remains
   non-mergeable evidence, and the retry prompt contains the gate result.
2. Treat graphify output as generated navigation. Do not force ignored
   `graphify-out/` files into git; instead, record `graphify update .` as
   verification evidence after code changes.

Add deterministic fake CLI sequences for review and verification gate outcomes
so production e2e tests can assert both retry paths without model calls.

## Final Verification

After all tasks are complete, run:

```bash
cd skills/agent-runway && ./evals/run.sh
cd skills/agent-runway && python3 -m py_compile scripts/agentrunway.py scripts/agentrunway/*.py scripts/agentrunway/adapters/*.py evals/*.py
cd skills/agent-runway && bash -n evals/run.sh
cd skills/agent-runway && python3 evals/check_skill_contract.py
git diff --check HEAD
graphify update .
git status --short --branch --untracked-files=all
```

Expected:

- the eval suite passes,
- Python files compile,
- shell script syntax check passes,
- skill contract check passes,
- diff check reports no whitespace errors,
- graphify updates successfully,
- git status shows only intentional tracked changes before the final commit, then clean after commit.
