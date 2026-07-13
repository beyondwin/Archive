# CPE Durable Superpowers Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Replace the oversized CPE harness with a small schema-4 durable queue that executes one or many approved Superpowers specs and plans through fresh bounded Codex roles, survives interruption, resolves ordinary failures autonomously, and reserves user questions for genuine authority boundaries.

**Architecture:** CPE remains Python for this reduction pass, but becomes non-semantic. It snapshots documents, stores a hash-chained event log, owns one isolated worktree, launches fresh document/program/task/review/audit/final sessions, verifies commit and artifact handoffs, and replays queue state on resume. Superpowers role sessions own requirement interpretation, TDD, review, fixes, and the single terminal verification. Release-proof, live-model, Graphify, compatibility-scoring, duplicated verification, and task-level policy machinery are deleted.

**Tech Stack:** Python 3 standard library, Git worktrees, Codex CLI structured output, Bash, temporary Git repositories, JSON/JSONL, Markdown.

## Global Constraints

- The approved design is docs/superpowers/specs/2026-07-13-cpe-superpowers-lean-runner-design.md.
- Change only skills/kws-codex-plan-executor/ during implementation. This plan file is the only root documentation addition.
- Do not modify Waygent, installed Superpowers skills, repository-root graphify-out/, external worktrees, or schema-3 run data.
- Do not run credentialed models, paid/live matrices, dogfood, release, deployment, push, merge, or publication workflows.
- Use test-first steps and apply_patch for tracked edits. Preserve unrelated user changes.
- Keep one write-capable child active at a time. Read-only document mapping/auditing may use bounded parallelism, but event appends remain serialized.
- Task and fix agents must create a commit and leave the isolated worktree clean.
- Reviewers consume focused-test evidence and exact diffs; they do not rerun identical focused tests at the same revision.
- The Program Final Integrator runs the full verification bundle exactly once per final revision. Any later write invalidates it.
- Ordinary implementation failures, test failures, review findings, technical choices, and recoverable local environment problems never open user authority.
- Only the six authority codes below may enter waiting_authority.
- Keep the final deterministic suite credential-free and under 60 seconds.
- Target no more than eight modules under scripts/cpe_runtime/ including __init__.py and roughly 5,000 active runtime plus eval lines. Do not omit required integrity checks merely to hit a cosmetic number.
- Do not implement Bun in this plan. Measure lean Python first.
- Ellipses in interface-only signature blocks denote required callable shapes; they are not source placeholders and must not be copied into implementation files.

---

## Final File Structure

~~~text
skills/kws-codex-plan-executor/
  SKILL.md
  README.md
  ARCHITECTURE.md
  HISTORY.md
  scripts/
    cpe.py
    cpe_runtime/
      __init__.py
      contracts.py
      store.py
      worktree.py
      launcher.py
      queue.py
      legacy.py
      prompt_export.py
  templates/
    child-result-schema.json
  evals/
    run.sh
    fake_codex.py
    check_lean_contracts.py
    check_lean_mapping.py
    check_lean_queue.py
    check_lean_final.py
    check_lean_recovery.py
    check_lean_cli.py
    lean-fixtures/
      spec-a.md
      spec-b.md
      plan-a.md
      plan-b.md
      program.md
  references/
    change-protocol.md
    common-mistakes.md
    execution-cycle.md
    prompt-export-checklist.md
    state-schema.md
  docs/
    doc-update-protocol.md
    evals-and-verification.md
    risks-limitations-deferrals.md
    user-guide.ko.md
~~~

No other tracked Python file under this skill remains active.

## Fixed Contracts

### Status and exit codes

~~~text
mapping -> running -> waiting_authority
                    -> interrupted
                    -> final_audit -> completed
                    -> failed
~~~

| Status | Exit | Meaning |
| --- | ---: | --- |
| completed | 0 | Final integrator artifact is revision-bound and passed |
| waiting_authority | 2 | Genuine authority blocks affected progress |
| interrupted | 3 | Durable state is valid and resume is safe |
| failed | 1 | Runner integrity or unrecoverable CPE infrastructure failed closed |

### Authority and role allowlists

~~~python
AUTHORITY_CODES = frozenset({
    "credential_required",
    "external_side_effect",
    "destructive_outside_worktree",
    "authoritative_document_conflict",
    "material_scope_expansion",
    "legal_security_policy_authority",
})

CHILD_ROLES = frozenset({
    "document_mapper",
    "program_mapper",
    "task_agent",
    "reviewer",
    "fix_agent",
    "investigator",
    "document_auditor",
    "program_final_integrator",
    "integration_fix_agent",
})

WRITE_ROLES = frozenset({"task_agent", "fix_agent", "integration_fix_agent"})
~~~

Any child request outside AUTHORITY_CODES becomes autonomous investigation. A child cannot invent a new approval category.

## Task 1: Schema-4 Contracts And Immutable Run Store

**Files:**

- Create: skills/kws-codex-plan-executor/scripts/cpe_runtime/contracts.py
- Create: skills/kws-codex-plan-executor/scripts/cpe_runtime/store.py
- Create: skills/kws-codex-plan-executor/evals/check_lean_contracts.py
- Create: skills/kws-codex-plan-executor/evals/lean-fixtures/spec-a.md
- Create: skills/kws-codex-plan-executor/evals/lean-fixtures/spec-b.md
- Create: skills/kws-codex-plan-executor/evals/lean-fixtures/plan-a.md
- Create: skills/kws-codex-plan-executor/evals/lean-fixtures/plan-b.md
- Create: skills/kws-codex-plan-executor/evals/lean-fixtures/program.md

**Interfaces:**

- InputDocument contains document_id, role, original_path, snapshot_path, sha256, byte_length, and input_order.
- ChildResult contains role, status, item_id, commit, verdict, failure_code, authority_id, strategy_key, affected_document_ids, artifact_paths, and summary.
- RunStore.create snapshots every input before a child launch.
- RunStore.append_event is the sole event writer and hash-chains canonical JSON.
- RunStore.put_artifact is immutable: identical bytes are idempotent; different bytes at the same path fail.
- RunStore.replay derives queue state from run.json and events.jsonl.

- [ ] **Step 1: Write the failing contract/store eval**

check_lean_contracts.py must:

1. snapshot two specs, two plans, and one program plan in stable role-local order;
2. prove source changes after create do not alter snapshots or hashes;
3. reject duplicate paths and non-UTF-8 inputs before run creation;
4. prove files are mode 0600 and private directories are 0700;
5. verify a two-event prev_event_sha256/event_sha256 chain;
6. detect a tampered event;
7. accept an identical artifact rewrite and reject different bytes at the same path;
8. reject unknown child role/status/extra field/authority code;
9. replay mapping -> running -> interrupted.

Use temporary CODEX_HOME and Git repositories. The document assertion is:

~~~python
store = RunStore.create(
    codex_home=home,
    workspace=repo,
    specs=[spec_a, spec_b],
    plans=[plan_a, plan_b],
    program_plan=program,
)
self.assertEqual(
    [(item.document_id, item.role) for item in store.document_set()],
    [
        ("spec-01", "spec"),
        ("spec-02", "spec"),
        ("plan-01", "plan"),
        ("plan-02", "plan"),
        ("program-plan", "program_plan"),
    ],
)
~~~

- [ ] **Step 2: Run RED**

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_lean_contracts.py
~~~

Expected: ModuleNotFoundError for contracts or store.

- [ ] **Step 3: Implement strict contracts**

contracts.py defines:

~~~python
SCHEMA_VERSION = 4
RUN_STATUSES = frozenset({
    "mapping", "running", "waiting_authority", "interrupted",
    "final_audit", "completed", "failed",
})
CHILD_STATUSES = frozenset({
    "completed", "changes_requested", "waiting_authority",
    "interrupted", "failed",
})
VERDICTS = frozenset({"pass", "changes_requested", "blocked", None})


@dataclass(frozen=True)
class InputDocument:
    document_id: str
    role: str
    original_path: str
    snapshot_path: str
    sha256: str
    byte_length: int
    input_order: int

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ChildResult:
    role: str
    status: str
    item_id: str
    commit: str | None
    verdict: str | None
    failure_code: str | None
    authority_id: str | None
    strategy_key: str | None
    affected_document_ids: tuple[str, ...]
    artifact_paths: tuple[str, ...]
    summary: str
~~~

Implement validate_child_result(payload, expected_role, expected_item_id) with exact-key validation. Enforce matching identity, bounded summary, required commit for successful write roles, legal verdict roles, allowlisted authority codes, and normalized relative artifact paths without parent traversal. Use no validation framework.

- [ ] **Step 4: Implement the immutable store**

store.py provides:

~~~python
@dataclass(frozen=True)
class RunPaths:
    root: Path
    manifest: Path
    events: Path
    result: Path
    inputs: Path
    maps: Path
    briefs: Path
    reports: Path
    reviews: Path
    verification: Path
    logs: Path
    outbox: Path


class RunStore:
    @classmethod
    def create(cls, *, codex_home: Path, workspace: Path,
               specs: Sequence[Path], plans: Sequence[Path],
               program_plan: Path | None) -> "RunStore": ...
    @classmethod
    def open(cls, *, codex_home: Path, run_id: str) -> "RunStore": ...
    def document_set(self) -> tuple[InputDocument, ...]: ...
    def append_event(self, event_type: str,
                     payload: Mapping[str, object]) -> dict[str, object]: ...
    def validate_event_chain(self) -> tuple[dict[str, object], ...]: ...
    def put_artifact(self, relative_path: str, data: bytes) -> Path: ...
    def read_artifact(self, relative_path: str) -> bytes: ...
    def allocate_outbox(self, attempt_id: str) -> Path: ...
    def ingest_outbox(self, attempt_id: str,
                      relative_paths: Sequence[str]) -> tuple[str, ...]: ...
    def replay(self) -> dict[str, object]: ...
~~~

The ellipses are interface signatures; implement every method here. Canonical JSON is:

~~~python
def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
~~~

Hash each event without event_sha256. Use temporary sibling files, fsync, os.replace, and O_APPEND. Never rewrite an existing manifest, event, or immutable artifact. Child roles read snapshot paths only.

- [ ] **Step 5: Run GREEN and commit**

~~~bash
python3 evals/check_lean_contracts.py
python3 -m py_compile scripts/cpe_runtime/contracts.py scripts/cpe_runtime/store.py evals/check_lean_contracts.py
git diff --check
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/contracts.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/store.py \
  skills/kws-codex-plan-executor/evals/check_lean_contracts.py \
  skills/kws-codex-plan-executor/evals/lean-fixtures
git commit -m "feat(cpe): add lean immutable run store"
~~~

Expected: checks pass and the commit succeeds.

## Task 2: Isolated Worktree And Fresh Codex Launcher

**Files:**

- Create: skills/kws-codex-plan-executor/scripts/cpe_runtime/worktree.py
- Create: skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py
- Create: skills/kws-codex-plan-executor/templates/child-result-schema.json
- Replace: skills/kws-codex-plan-executor/evals/fake_codex.py
- Modify: skills/kws-codex-plan-executor/evals/check_lean_contracts.py

**Interfaces:**

- Worktree.create creates codex/<run_id> from source HEAD without editing the source checkout.
- Worktree.verify_write_handoff requires the reported commit to equal HEAD and the worktree to be clean.
- ChildLauncher launches a new codex exec process per role.
- Read-only roles use read-only sandbox; write roles use workspace-write.
- The only additional writable path is the attempt outbox.

- [ ] **Step 1: Extend the eval and run RED**

Add cases for tracked source dirt, wrong commit, dirty handoff, a read-only role changing Git state, artifact traversal, timeout cleanup, and a PATH containing only a temporary fake codex. Then run:

~~~bash
python3 evals/check_lean_contracts.py
~~~

Expected: missing worktree or launcher module.

- [ ] **Step 2: Implement worktree ownership**

~~~python
@dataclass(frozen=True)
class Worktree:
    source: Path
    root: Path
    branch: str
    base_commit: str

    @classmethod
    def create(cls, *, source: Path, root: Path, run_id: str) -> "Worktree": ...
    @classmethod
    def open(cls, *, source: Path, root: Path,
             branch: str, base_commit: str) -> "Worktree": ...
    def head(self) -> str: ...
    def status(self) -> tuple[str, ...]: ...
    def verify_identity(self) -> None: ...
    def verify_read_only_handoff(
        self, before_head: str, before_status: tuple[str, ...]
    ) -> None: ...
    def verify_write_handoff(self, reported_commit: str) -> None: ...
    def diff(self, start: str, end: str) -> str: ...
~~~

Source preflight checks tracked changes with --untracked-files=no. Isolated handoff checks all visible changes with --untracked-files=all. Do not reset, delete, merge, or push.

- [ ] **Step 3: Add the single child-result schema**

templates/child-result-schema.json must require every field:

~~~json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "role", "status", "item_id", "commit", "verdict", "failure_code",
    "authority_id", "strategy_key", "affected_document_ids",
    "artifact_paths", "summary"
  ],
  "properties": {
    "role": {"type": "string"},
    "status": {
      "type": "string",
      "enum": ["completed", "changes_requested", "waiting_authority", "interrupted", "failed"]
    },
    "item_id": {"type": "string", "minLength": 1},
    "commit": {"type": ["string", "null"]},
    "verdict": {
      "type": ["string", "null"],
      "enum": ["pass", "changes_requested", "blocked", null]
    },
    "failure_code": {"type": ["string", "null"]},
    "authority_id": {"type": ["string", "null"]},
    "strategy_key": {"type": ["string", "null"]},
    "affected_document_ids": {"type": "array", "items": {"type": "string"}},
    "artifact_paths": {"type": "array", "items": {"type": "string"}},
    "summary": {"type": "string", "minLength": 1, "maxLength": 2000}
  }
}
~~~

- [ ] **Step 4: Implement ChildLauncher**

The command builder is:

~~~python
argv = [
    codex_bin, "exec", "--ignore-user-config", "--json",
    "--sandbox", "workspace-write" if request.role in WRITE_ROLES else "read-only",
    "-C", str(request.worktree),
    "--add-dir", str(request.outbox),
    "--output-schema", str(self.schema_path),
    "--output-last-message", str(last_message),
    "-",
]
~~~

Do not pass model, profile, pricing, release, or compatibility policy. Preserve inherited PATH and CODEX_HOME; remove OPENAI_API_KEY, ANTHROPIC_API_KEY, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN, and GITHUB_TOKEN.

Each role prompt includes Goal, exact input paths, repository/worktree, write boundary, applicable Superpowers skills, outbox report path, fixed result contract, standing autonomy, six authority codes, and Done when. Task/fix prompts require using-superpowers, TDD for behavior changes, focused checks, self-review, one commit, and clean status. Reviewer prompts prohibit identical test reruns. Final prompts require verification-before-completion.

The launcher records HEAD/status, starts a new process group, sends prompt through stdin, terminates then kills on timeout, parses the last message, verifies Git invariants, ingests only normalized outbox files, and returns the compact ChildResult plus event digest and elapsed milliseconds.

- [ ] **Step 5: Replace fake_codex.py**

Parse stdin for CPE_ROLE and ITEM. Select behavior with CPE_FAKE_SCENARIO. Required scenarios:

~~~text
success
review_changes_requested
ordinary_failure
authority
timeout
dirty_handoff
wrong_commit
tampered_artifact_path
~~~

The fake writes requested artifacts and, for write roles, can create a real Git commit. It emits minimal JSONL and writes structured JSON to --output-last-message. It never uses network.

- [ ] **Step 6: Run GREEN and commit**

~~~bash
python3 evals/check_lean_contracts.py
python3 -m py_compile scripts/cpe_runtime/worktree.py scripts/cpe_runtime/launcher.py evals/fake_codex.py
git diff --check
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/worktree.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/templates/child-result-schema.json \
  skills/kws-codex-plan-executor/evals/fake_codex.py \
  skills/kws-codex-plan-executor/evals/check_lean_contracts.py
git commit -m "feat(cpe): launch bounded fresh Codex roles"
~~~

Expected: checks pass and the commit succeeds.
## Task 3: Multi-Document Mapping And Lossless Task Briefs

**Files:**

- Create: skills/kws-codex-plan-executor/scripts/cpe_runtime/queue.py
- Create: skills/kws-codex-plan-executor/evals/check_lean_mapping.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/contracts.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py
- Modify: skills/kws-codex-plan-executor/evals/fake_codex.py

**Interfaces:**

- QueueEngine.map_documents launches one fresh mapper per immutable input.
- QueueEngine.map_program launches after every document map is valid.
- Document maps carry exact excerpts and source hashes, not summaries alone.
- Program maps contain topological task order, dependencies, coverage, final verification commands, and one immutable brief per task.
- CPE validates shapes, IDs, hashes, dependency existence, acyclicity, and coverage disposition without interpreting prose.

- [ ] **Step 1: Write the failing mapping eval**

check_lean_mapping.py must prove:

1. two specs, two plans, and a program plan each receive one mapper launch;
2. each mapper reads exactly one snapshot;
3. program mapper receives document maps and repository instructions, not the full corpus;
4. a mismatched source SHA fails;
5. each normative requirement has implemented, deferred_with_reason, non_goal, superseded, or authority_required disposition;
6. an unmapped requirement blocks task dispatch;
7. unknown dependencies and cycles fail closed;
8. briefs contain exact excerpts, source document ID/range/SHA, task dependencies, and acceptance;
9. an oversized task is split without changing source coverage;
10. completed immutable maps are reused after interruption.

Use global IDs plan-01:T1, plan-01:T2, plan-02:T1 and requirement IDs spec-01:R1, spec-02:R1.

- [ ] **Step 2: Run RED**

~~~bash
python3 evals/check_lean_mapping.py
~~~

Expected: QueueEngine or mapping validators are missing.

- [ ] **Step 3: Add structural map validators**

contracts.py adds:

~~~python
def validate_document_map(
    payload: object, *, document: InputDocument
) -> dict[str, object]: ...


def validate_program_map(
    payload: object, *, document_ids: set[str]
) -> dict[str, object]: ...


def validate_task_brief(
    payload: object, *, program_map_sha256: str,
    document_hashes: Mapping[str, str]
) -> dict[str, object]: ...
~~~

Document map shape:

~~~json
{
  "schema_version": 1,
  "document_id": "spec-01",
  "role": "spec",
  "source_sha256": "64-hex",
  "requirements": [
    {
      "requirement_id": "spec-01:R1",
      "kind": "normative",
      "heading": "Accepted Inputs",
      "line_start": 10,
      "line_end": 20,
      "exact_excerpt": "verbatim source text",
      "constraints": ["repeatable specs"]
    }
  ],
  "task_candidates": [],
  "dependencies": [],
  "authority_items": [],
  "verification_commands": []
}
~~~

Program map shape:

~~~json
{
  "schema_version": 1,
  "generation": 1,
  "document_map_sha256s": {"spec-01": "64-hex"},
  "tasks": [
    {
      "task_id": "plan-01:T1",
      "title": "Implement one bounded change",
      "dependencies": [],
      "document_ids": ["plan-01", "spec-01"],
      "requirement_ids": ["spec-01:R1"],
      "brief_path": "briefs/plan-01-T1.json"
    }
  ],
  "coverage": {
    "spec-01:R1": {
      "disposition": "implemented",
      "task_ids": ["plan-01:T1"],
      "reason": null
    }
  },
  "final_verification_commands": ["./evals/run.sh"],
  "authority_items": []
}
~~~

- [ ] **Step 4: Implement mapping phases**

~~~python
class QueueEngine:
    def __init__(self, store: RunStore, worktree: Worktree,
                 launcher: ChildLauncher) -> None: ...
    def map_documents(self) -> tuple[str, ...]: ...
    def map_program(self) -> str: ...
    def run_until_terminal(self) -> dict[str, object]: ...
~~~

Document mappers may use ThreadPoolExecutor with max_workers=min(4, pending_count). Worker threads do not append events. Collect results, sort by document input_order, ingest artifacts, then append deterministic map events.

The program mapper reads document maps plus applicable AGENTS.md files and writes program-map.json, coverage.json, authority-queue.json, and briefs. Validate all paths and digests before accepting generation-0001.

If mapping opens allowlisted authority, append authority.opened. Independent tasks may continue only when the program graph proves they do not depend on the authority item.

- [ ] **Step 5: Run GREEN and commit**

~~~bash
python3 evals/check_lean_mapping.py
python3 evals/check_lean_contracts.py
python3 -m py_compile scripts/cpe_runtime/contracts.py scripts/cpe_runtime/queue.py
git diff --check
git add skills/kws-codex-plan-executor/scripts/cpe_runtime/contracts.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/queue.py \
  skills/kws-codex-plan-executor/evals/check_lean_mapping.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py
git commit -m "feat(cpe): map multi-document Superpowers programs"
~~~

Expected: all checks pass.

## Task 4: Durable Task, Review, Fix, And Autonomous Recovery Queue

**Files:**

- Create: skills/kws-codex-plan-executor/evals/check_lean_queue.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/queue.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/store.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/launcher.py
- Modify: skills/kws-codex-plan-executor/evals/fake_codex.py

**Interfaces:**

- Ready tasks are program-map tasks whose dependencies passed review.
- A single writer lease prevents overlapping task/fix/integration-fix children.
- Task/fix results are accepted only after commit and clean-worktree verification.
- A fresh reviewer reads the brief, report, upstream interface reports, and exact commit diff.
- Critical/Important findings are consolidated into one fix launch.
- Same strategy_key with unchanged evidence launches an investigator and requires a changed strategy.
- Non-authority failures never become waiting_authority.

- [ ] **Step 1: Write the failing queue eval**

check_lean_queue.py must assert:

1. dependencies enforce plan-01:T1 before plan-01:T2;
2. write roles never overlap;
3. a task commit is recorded before review;
4. review receives the exact commit range and does not rerun the focused command;
5. changes_requested launches one consolidated fix;
6. the fix creates a commit and a fresh reviewer sees the expanded range;
7. ordinary_failure launches investigator/fix and records autonomy-decisions.jsonl;
8. an unchanged strategy_key cannot be redispatched;
9. credential_required opens authority while test_failure does not;
10. a completed task/review is not launched again on another tick.

- [ ] **Step 2: Run RED**

~~~bash
python3 evals/check_lean_queue.py
~~~

Expected: task lifecycle methods/events are missing.

- [ ] **Step 3: Add the only event vocabulary and replay**

~~~python
EVENT_TYPES = frozenset({
    "run.created",
    "documents.snapshotted",
    "map.generation_created",
    "task.started",
    "task.reported",
    "review.reported",
    "autonomy.recorded",
    "authority.opened",
    "authority.resolved",
    "run.interrupted",
    "audit.reported",
    "integration.reported",
    "run.completed",
    "run.failed",
})
~~~

Events store only IDs, hashes, commits, statuses, strategies, and artifact paths. Never embed prompts, diffs, source bytes, logs, or full reports.

RunStore.append_autonomy_decision writes:

~~~json
{
  "decision_id": "D0001",
  "issue": "focused test failed after the first fix",
  "alternatives": ["repeat patch", "fresh root-cause investigation"],
  "selected": "fresh root-cause investigation",
  "rationale": "same strategy and evidence made no progress",
  "evidence_paths": ["reports/plan-01-T1/attempt-2.md"],
  "affected_tasks": ["plan-01:T1"],
  "reversible": true,
  "created_at": "RFC3339 UTC"
}
~~~

- [ ] **Step 4: Implement task lifecycle**

~~~python
def _next_ready_task(self, state: Mapping[str, object]) -> dict[str, object] | None: ...
def _run_task(self, task: Mapping[str, object]) -> None: ...
def _run_review(self, task: Mapping[str, object],
                start_commit: str, end_commit: str) -> None: ...
def _run_consolidated_fix(
    self, task: Mapping[str, object],
    finding_paths: Sequence[str]
) -> None: ...
def _run_investigation(
    self, task: Mapping[str, object],
    evidence_paths: Sequence[str]
) -> None: ...
def _handle_child_failure(self, result: ChildResult, task_id: str) -> None: ...
~~~

Store reports/<task>/attempt-N.md, reviews/<task>/review-N.md, and reports/<task>/diff-N.patch. Pass only dependency reports named by the program map. Track strategy keys in replayed state. Reject unallowlisted authority requests and investigate instead.

Continue until review passes, genuine authority is proven, the process is interrupted, or store/worktree integrity fails. There is no arbitrary retry count. Never weaken tests or requirements to escape a loop.

- [ ] **Step 5: Run GREEN and commit**

~~~bash
python3 evals/check_lean_queue.py
python3 evals/check_lean_mapping.py
python3 evals/check_lean_contracts.py
git diff --check
git add skills/kws-codex-plan-executor/scripts/cpe_runtime \
  skills/kws-codex-plan-executor/evals/check_lean_queue.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py
git commit -m "feat(cpe): persist task review and autonomous recovery"
~~~

Expected: all checks pass.

## Task 5: Document Coverage Audits And Single Terminal Verification

**Files:**

- Create: skills/kws-codex-plan-executor/evals/check_lean_final.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/queue.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/contracts.py
- Modify: skills/kws-codex-plan-executor/evals/fake_codex.py

**Interfaces:**

- One fresh auditor checks each immutable document against its map and relevant task evidence.
- Program Final Integrator consumes program map, all audit verdicts, autonomy decisions, authority state, whole diff, and final verification commands.
- Integrator runs each final command once at exact final HEAD.
- A final fix invalidates all document audits and prior integration evidence.
- CPE completes only from pass at a clean matching HEAD.

- [ ] **Step 1: Write the failing final-closure eval**

check_lean_final.py must cover:

1. every input document gets one auditor at final revision;
2. each auditor receives only its source document and relevant evidence;
3. one failed auditor prevents integrator launch;
4. integrator receives all verdicts and the complete base-to-HEAD diff;
5. final verification executes once for one revision;
6. a pass with stale commit is rejected;
7. integration changes_requested launches one consolidated integration fix;
8. that commit invalidates earlier audits;
9. the new revision reruns audits and final verification;
10. result.json and run.completed appear only after a clean pass.

- [ ] **Step 2: Run RED**

~~~bash
python3 evals/check_lean_final.py
~~~

Expected: final-audit methods are missing.

- [ ] **Step 3: Add audit and terminal validators**

Auditor artifacts contain document_id, source_sha256, revision, coverage verdicts, missing requirements, conflicts, and verdict.

Terminal artifact shape:

~~~json
{
  "schema_version": 1,
  "quality_verdict": "pass",
  "revision": "git commit",
  "auditor_verdicts": {"spec-01": "pass", "plan-01": "pass"},
  "verification": [
    {
      "command": "./evals/run.sh",
      "exit_code": 0,
      "output_path": "verification/final-HEAD-1.log"
    }
  ],
  "authority_open": [],
  "residual_limitations": [],
  "whole_diff_sha256": "64-hex"
}
~~~

quality_verdict may be pass, blocked, or failed. completed is legal only for pass.

- [ ] **Step 4: Implement final closure**

~~~python
def _run_document_audits(self, revision: str) -> tuple[str, ...]: ...
def _run_program_final_integrator(
    self, revision: str, audit_paths: Sequence[str]
) -> ChildResult: ...
def _run_integration_fix(self, finding_paths: Sequence[str]) -> None: ...
def _invalidate_final_evidence(
    self, previous_revision: str, new_revision: str
) -> None: ...
~~~

Auditors may use max_workers=min(4, pending_documents); accept events in document order. Write one whole-diff artifact before integrator launch. The integrator owns final commands and raw verification logs. CPE verifies paths, exit codes, commit binding, clean status, and artifact shape but does not rerun commands.

If integration requests changes, send all findings to one integration_fix_agent. After its commit, rerun all document auditors conservatively; this rare repeat is simpler and safer than a semantic Python impact analyzer.

- [ ] **Step 5: Run GREEN and commit**

~~~bash
python3 evals/check_lean_final.py
python3 evals/check_lean_queue.py
python3 evals/check_lean_mapping.py
python3 evals/check_lean_contracts.py
git diff --check
git add skills/kws-codex-plan-executor/scripts/cpe_runtime \
  skills/kws-codex-plan-executor/evals/check_lean_final.py \
  skills/kws-codex-plan-executor/evals/fake_codex.py
git commit -m "feat(cpe): bind completion to final program audit"
~~~

Expected: all checks pass.

## Task 6: Resume, Legacy Inspect, Export, And Public CLI

**Files:**

- Create: skills/kws-codex-plan-executor/scripts/cpe_runtime/legacy.py
- Rewrite: skills/kws-codex-plan-executor/scripts/cpe_runtime/prompt_export.py
- Rewrite: skills/kws-codex-plan-executor/scripts/cpe.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/contracts.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/store.py
- Modify: skills/kws-codex-plan-executor/scripts/cpe_runtime/queue.py
- Create: skills/kws-codex-plan-executor/evals/check_lean_recovery.py
- Create: skills/kws-codex-plan-executor/evals/check_lean_cli.py

**Interfaces:**

- run accepts repeated --spec, repeated --plan, optional --program-plan, and --workspace.
- resume replays schema 4 only. It may resolve one durable authority item or explicitly snapshot changed source documents into a new map generation.
- inspect emits a bounded schema-4 or schema-3 summary without mutation.
- export accepts the same document flags plus prompt or handoff mode and creates no artifacts.
- supervise, --docs, run --mode, maintenance, repair, and release commands are removed.

- [ ] **Step 1: Write recovery and CLI RED evals**

check_lean_recovery.py must prove:

- interruption during mapping, task, review, and final audit yields interrupted;
- resume validates manifest, event chain, inputs, artifacts, worktree branch, and commits;
- completed maps/tasks/reviews are not redispatched;
- an interrupted child restarts with prior evidence;
- genuine authority remains waiting_authority;
- --authority-id plus --authority-answer validates the open item/options, appends authority.resolved, and resumes without mutating the old packet;
- --refresh-inputs snapshots only changed original sources into generation-N, remaps changed documents, creates a new program map, and preserves prior generations;
- unchanged task-brief hashes retain completed task/review state while changed brief hashes invalidate only structurally affected tasks and downstream dependents;
- tampered immutable snapshot, tampered map, divergent worktree, or broken event chain fails closed;
- schema-3 inspect changes no bytes, modes, or mtimes;
- schema-3 resume returns legacy_run_requires_historical_cpe.

check_lean_cli.py must prove:

- repeated specs/plans preserve input order;
- at least one plan is required and program plan is singular;
- resume requires --authority-id and --authority-answer together and rejects answers not offered by the authority packet;
- refresh never happens implicitly merely because an original source file changed;
- public JSON has status, run_id, state_path, summary, next_action, failure_code, authority_items, and terminal_artifact;
- schema-4 inspect reports generation, current item/role, completed and total task counts, open authority IDs, worktree HEAD, last event type, and terminal artifact path without loading full reports;
- exit codes match Fixed Contracts;
- export contains every ordered path and SHA-256;
- export leaves CODEX_HOME/workspace inventories unchanged;
- help lists only run, resume, inspect, export;
- active docs name schema 4 and do not advertise removed commands.

- [ ] **Step 2: Run RED**

~~~bash
python3 evals/check_lean_recovery.py
python3 evals/check_lean_cli.py
~~~

Expected: current CLI and legacy behavior fail the new assertions.

- [ ] **Step 3: Implement bounded legacy inspection**

legacy.py recognizes historical run_manifest.json plus state.json, reads only the bounded fields needed below, and returns:

~~~python
{
    "schema_version": 3,
    "run_id": run_id,
    "status": bounded_status,
    "current_task": bounded_task,
    "worktree": bounded_path,
    "resume_supported": False,
    "failure_code": "legacy_run_requires_historical_cpe",
}
~~~

Do not import schema-3 validators, repair, scheduler, or migration code. Bound strings to 2,000 characters and lists to 100 items. Never write during inspect.

Schema-4 inspection uses RunStore.validate_event_chain plus replay and returns only bounded counters, IDs, hashes, and artifact paths. It never launches a child or reads full prompt/report/diff/log bodies.

- [ ] **Step 4: Rewrite export**

prompt_export.py hashes documents directly without snapshots. Both modes include workspace, ordered specs, ordered plans, optional program plan, each SHA-256, Superpowers instruction, and an explicit statement that no CPE run started.

Handoff mode adds the exact schema-4 run command with repeated flags. Do not include release, Graphify, model, packet, or old verification policy.

- [ ] **Step 5: Rewrite cpe.py as a thin entry**

~~~python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--spec", action="append", default=[])
    run.add_argument("--plan", action="append", required=True)
    run.add_argument("--program-plan")
    run.add_argument("--workspace", required=True)

    resume = sub.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--authority-id")
    resume.add_argument("--authority-answer")
    resume.add_argument("--refresh-inputs", action="store_true")

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--run-id", required=True)

    export = sub.add_parser("export")
    export.add_argument("--spec", action="append", default=[])
    export.add_argument("--plan", action="append", required=True)
    export.add_argument("--program-plan")
    export.add_argument("--workspace", required=True)
    export.add_argument("--mode", choices=("prompt", "handoff"), default="prompt")
    return parser
~~~

cpe.py imports only contracts, store, worktree, launcher, queue, legacy, and prompt_export. The two authority arguments must appear together and cannot be combined with --refresh-inputs. Authority answers are accepted only when the authority ID is open and the answer exactly matches one offered option. Refresh uses the original absolute paths recorded in the document set, writes new immutable snapshots and maps under generation-N, and never rewrites generation-0001.

Generation comparison is structural: the new Program Mapper must emit predecessor_task_id for retained tasks. CPE preserves completion only when predecessor_task_id exists and the new brief SHA-256 is identical. A changed brief invalidates that task, every graph descendant, document audits, and terminal verification. Do not add Python semantic diffing.

On KeyboardInterrupt append run.interrupted when possible and emit interrupted. Ordinary exceptions emit failed with a stable failure_code; stdout remains valid JSON.

- [ ] **Step 6: Run GREEN and commit**

~~~bash
python3 evals/check_lean_recovery.py
python3 evals/check_lean_cli.py
python3 evals/check_lean_final.py
python3 evals/check_lean_queue.py
python3 evals/check_lean_mapping.py
python3 evals/check_lean_contracts.py
python3 scripts/cpe.py --help
git diff --check
git add skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime \
  skills/kws-codex-plan-executor/evals/check_lean_recovery.py \
  skills/kws-codex-plan-executor/evals/check_lean_cli.py
git commit -m "feat(cpe): switch public execution to schema 4"
~~~

Expected: all checks pass and help lists four commands.

## Task 7: Delete Superseded Harnesses, Rewrite Docs, And Prove The Lean Boundary

**Files:**

- Delete every tracked top-level file under skills/kws-codex-plan-executor/scripts/ except cpe.py.
- Delete every old tracked file under scripts/cpe_runtime/ except __init__.py and the seven final modules.
- Delete every tracked eval path except the six checks, fake_codex.py, run.sh, and five lean fixtures.
- Delete requirements-eval.txt and every old template.
- Rewrite evals/run.sh.
- Rewrite SKILL.md, README.md, ARCHITECTURE.md, and HISTORY.md.
- Rewrite and keep references/change-protocol.md, common-mistakes.md, execution-cycle.md, prompt-export-checklist.md, and state-schema.md.
- Rewrite and keep docs/doc-update-protocol.md, evals-and-verification.md, risks-limitations-deferrals.md, and user-guide.ko.md.
- Delete every other tracked file under references/ and docs/.

The Final File Structure keep-list is authoritative. Use apply_patch for deletion. Do not touch ignored caches/runtime data, schema-3 runs, external worktrees, root Graphify, or unrelated files.

- [ ] **Step 1: Rewrite run.sh**

~~~bash
#!/usr/bin/env bash
set -euo pipefail

for check in \
  check_lean_contracts.py \
  check_lean_mapping.py \
  check_lean_queue.py \
  check_lean_final.py \
  check_lean_recovery.py \
  check_lean_cli.py
do
  python3 "$(dirname "$0")/$check"
  echo "PASS $check"
done

echo "6 passed"
~~~

Run it before deletion. It must pass without PyYAML, network, credentials, live models, Graphify, or product-wide tests.

- [ ] **Step 2: Delete old top-level scripts**

~~~text
scripts/analyze_recent_runs.py
scripts/audit_plan_executability.py
scripts/audit_prompt_cache.py
scripts/audit_run_readiness.py
scripts/audit_superpowers_compatibility.py
scripts/build_context_snapshot.py
scripts/build_spec_manifest.py
scripts/build_task_packet.py
scripts/check_graphify_freshness.py
scripts/check_run_diffs.py
scripts/cpe_audit_common.py
scripts/inspect_runs.py
scripts/normalize_cpe_run.py
scripts/parse_invocation_args.py
scripts/parse_plan.py
scripts/preflight_dependencies.py
scripts/preflight_dispatch.py
scripts/preflight_local_env.py
scripts/reconcile_state.py
scripts/render_task_packet_view.py
scripts/repair_runs.py
scripts/validate_state.py
~~~

- [ ] **Step 3: Delete old runtime modules**

~~~text
attempt_controller.py
autonomy.py
checkpoints.py
command_evidence.py
document_set.py
dogfood_v4.py
events.py
evidence.py
evidence_store.py
failure_policy.py
git_delta.py
git_objects.py
inspection.py
kernel.py
manifest.py
model_policy.py
operator_decisions.py
packets.py
phase_executor.py
plan_compiler.py
plan_graph.py
privacy.py
projector.py
prompt_bundles.py
public_result.py
quality_v4.py
reconciliation.py
release_closure.py
release_policy_v4.py
release_policy_vnext.py
repair.py
runtime_upgrade.py
scheduler.py
supervisor.py
task_contracts.py
transition_kernel.py
validation.py
verification_workspace.py
worker.py
~~~

The new store.py subsumes event storage. Do not retain compatibility imports.

- [ ] **Step 4: Delete old eval and release surfaces**

Keep exactly:

~~~text
evals/run.sh
evals/fake_codex.py
evals/check_lean_contracts.py
evals/check_lean_mapping.py
evals/check_lean_queue.py
evals/check_lean_final.py
evals/check_lean_recovery.py
evals/check_lean_cli.py
evals/lean-fixtures/spec-a.md
evals/lean-fixtures/spec-b.md
evals/lean-fixtures/plan-a.md
evals/lean-fixtures/plan-b.md
evals/lean-fixtures/program.md
~~~

Delete every other tracked eval path, including baselines/, control-bundles/, dogfood/, fixtures/, golden-cases/, live-migration/, live_migration/, parser-fixtures/, live_model_migration.py, live_model_runner.py, maintained-checks.json, public CLI matrices, judge.md, and historical check files.

- [ ] **Step 5: Delete old templates and dependency pin**

Keep only templates/child-result-schema.json. Delete:

~~~text
templates/cpe-v4-worker-prefix.txt
templates/fresh-session-prompt.txt
templates/headless-output-schema.json
templates/integration-review-vnext.schema.json
templates/task-contract-schema.json
templates/worker-result-schema.json
requirements-eval.txt
~~~

All active Python/eval code must be standard-library-only.

- [ ] **Step 6: Rewrite skill and docs**

SKILL.md metadata:

~~~yaml
---
name: kws-codex-plan-executor
description: Use when executing one or many approved Superpowers implementation plans as a durable schema-4 queue with fresh bounded Codex roles, interruption recovery, and multi-document coverage.
metadata:
  version: "4.0.0"
  updated_at: "2026-07-13"
---
~~~

SKILL.md stays concise: CPE versus direct Superpowers, repeated flags, four commands, fresh role ownership, standing autonomy, six authority boundaries, worktree/snapshots/events/commits/resume/final integration, schema-3 inspection, and exact deterministic verification.

README owns usage and artifacts. ARCHITECTURE owns role/queue boundaries. HISTORY records 4.0.0 as an intentional breaking simplification and points to Git history for schema-3 implementation.

Kept-document ownership:

| File | Sole responsibility |
| --- | --- |
| references/change-protocol.md | RED/GREEN/change/verification; no Graphify/release |
| references/common-mistakes.md | operational mistakes and authority misuse |
| references/execution-cycle.md | mapping/task/review/audit/final |
| references/prompt-export-checklist.md | export-only behavior |
| references/state-schema.md | run.json, events, artifacts, replay |
| docs/doc-update-protocol.md | which kept docs track which contract |
| docs/evals-and-verification.md | six checks and under-60-second target |
| docs/risks-limitations-deferrals.md | mapper/autonomy/Bun/schema-3 risks |
| docs/user-guide.ko.md | Korean operator guide |

Delete every other docs/reference file. Remove active Graphify, release readiness, paid-live, dogfood, model routing, compatibility scoring, task packet, repair tool, and duplicated verification instructions.

- [ ] **Step 7: Run full lean verification**

~~~bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/cpe.py --help
python3 scripts/cpe.py run --help
python3 scripts/cpe.py export --help
cd /Users/kws/source/private/Archive
git diff --check
~~~

Expected: 6 passed; syntax checks pass; help shows only run/resume/inspect/export; diff check is empty.

- [ ] **Step 8: Prove removal, size, and speed**

~~~bash
cd /Users/kws/source/private/Archive
find skills/kws-codex-plan-executor/scripts -type f -name '*.py' | sort
find skills/kws-codex-plan-executor/evals -type f -name '*.py' | sort
wc -l skills/kws-codex-plan-executor/scripts/cpe.py \
  skills/kws-codex-plan-executor/scripts/cpe_runtime/*.py \
  skills/kws-codex-plan-executor/evals/*.py
rg -n "graphify|release_closure|release_policy|live_model|dogfood|paid-live|audit_superpowers_compatibility" \
  skills/kws-codex-plan-executor/scripts \
  skills/kws-codex-plan-executor/templates
/usr/bin/time -p skills/kws-codex-plan-executor/evals/run.sh
/usr/bin/time -p python3 skills/kws-codex-plan-executor/scripts/cpe.py --help
~~~

Expected:

- cpe.py plus eight cpe_runtime files including __init__.py;
- fake_codex.py plus six eval checks;
- active implementation plus evals near or below 5,000 lines, or a documented exact necessary excess;
- runtime/template removal search has no matches; evals and history may name removed surfaces only to assert that they are absent;
- suite real time under 60 seconds.

Do not begin Bun work. These measurements decide whether a separate Bun proposal is justified.

- [ ] **Step 9: Inspect and commit**

~~~bash
git status --short --branch --untracked-files=all
git diff --stat
git diff -- skills/kws-codex-plan-executor
git add -A -- skills/kws-codex-plan-executor ':(exclude)**/.DS_Store'
git diff --cached --check
git commit -m "refactor(cpe): replace harness with durable Superpowers queue"
git status --short --branch --untracked-files=all
~~~

Expected: implementation is committed locally. Do not push or merge.

## Final Acceptance Checklist

- [ ] Repeated specs/plans and optional program plan work in one run.
- [ ] Inputs are immutable and digest-bound before any child starts.
- [ ] Mapping preserves exact excerpts and complete requirement dispositions.
- [ ] No long-lived LLM main controller exists in the successful path.
- [ ] One write-capable child runs at a time.
- [ ] Task/fix handoffs are commit-bound and clean.
- [ ] Superpowers owns TDD, code review, and verification-before-completion.
- [ ] Reviewers do not duplicate identical focused tests.
- [ ] Ordinary failures trigger autonomous recovery and changed strategy.
- [ ] Only six allowlisted boundaries can wait for the user.
- [ ] Resume never redispatches completed work.
- [ ] Audits and final integration bind to exact final revision.
- [ ] Full verification runs once per final revision and a later write invalidates it.
- [ ] Schema-3 inspect is read-only and resume is rejected.
- [ ] Export creates no run or worktree artifacts.
- [ ] Active CPE has no Graphify, release, live-model, dogfood, paid-proof, compatibility-score, or duplicated worker dependency.
- [ ] Deterministic suite is credential-free and under 60 seconds.
- [ ] Runtime has at most eight cpe_runtime modules and is materially smaller than the previous 51,000-line Python surface.
- [ ] Waygent, Superpowers source, root graphify-out/, external worktrees, merge, push, and deployment state are unchanged.

## Stop Conditions

Implementation may ask the user only when repository evidence proves:

- mutually exclusive authoritative product requirements with no precedence;
- required credentials or an unauthorized external side effect;
- unavoidable irreversible action outside the disposable worktree;
- material scope outside skills/kws-codex-plan-executor/.

Do not stop for ordinary defects, failing tests, review findings, documented local dependency setup, or a failed recovery attempt. Diagnose, change strategy, preserve evidence, and continue.
