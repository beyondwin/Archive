# KWS Codex Plan Executor 4.0.0

CPE is a durable schema-4 queue for executing one or many approved
Superpowers implementation plans. It snapshots the source documents, maps them
with fresh bounded roles, serializes writers in one isolated worktree, and
resumes from immutable file-backed evidence. It does not keep a coordinating
model session alive.

Use direct Superpowers for a small task that fits one session. Use CPE for a
large, multi-document, interruptible program.

## Requirements

- Python 3 using only the standard library
- Git
- Codex available as codex on PATH
- a clean Git workspace for the source repository
- absolute input and workspace paths

No package install, network access, credential, or provider call is needed for
the deterministic eval suite.

## Start A Run

Spec and plan options may repeat. At least one plan is required. A program plan
is optional and singular.

    cd skills/kws-codex-plan-executor
    python3 scripts/cpe.py run \
      --spec /abs/product-spec.md \
      --spec /abs/security-spec.md \
      --plan /abs/foundation-plan.md \
      --plan /abs/integration-plan.md \
      --program-plan /abs/program-plan.md \
      --workspace /abs/repository

CLI order records input order; it does not grant one document authority over
another. Explicit supersession or a recorded authority answer is required for
incompatible approved requirements.

Every command prints one JSON result. Public statuses and exit codes are:

| Status | Exit | Meaning |
| --- | ---: | --- |
| completed | 0 | terminal integration artifact was published |
| failed | 1 | invocation or integrity failure cannot continue safely |
| waiting_authority | 2 | one of six user-owned decisions blocks affected work |
| interrupted | 3 | durable state is valid and resume is available |

The terminal artifact contains the separate quality verdict. Do not interpret
completed alone as a stronger product-quality claim.

## Resume, Authority, And Refresh

    python3 scripts/cpe.py resume --run-id RUN_ID
    python3 scripts/cpe.py inspect --run-id RUN_ID

Inspect is read-only. Resume validates the run and worktree before continuing.
A completed task, clean review, accepted audit, or accepted final record is not
redispatched.

When inspect reports an open authority item, choose one of that packet's exact
options:

    python3 scripts/cpe.py resume --run-id RUN_ID \
      --authority-id AUTHORITY_ID \
      --authority-answer OFFERED_OPTION

Changed source documents are ignored until an explicit refresh:

    python3 scripts/cpe.py resume --run-id RUN_ID --refresh-inputs

Refresh snapshots the current declared source paths into a new generation. It
preserves earlier generations and invalidates only work whose task identity,
brief, dependency closure, or governing document changed.

## Export Without Execution

    python3 scripts/cpe.py export \
      --spec /abs/spec.md \
      --plan /abs/plan.md \
      --workspace /abs/repository \
      --mode prompt

    python3 scripts/cpe.py export \
      --plan /abs/plan.md \
      --workspace /abs/repository \
      --mode handoff

Export validates paths and renders a launcher document to stdout. It does not
create CODEX_HOME, a run directory, events, or a worktree.

## Artifacts

By default a run owns:

    ~/.codex/orchestrator/RUN_ID/
      run.json
      events.jsonl
      events.head.json
      artifacts.jsonl
      autonomy-decisions.jsonl
      writer.lease
      inputs/
      maps/
      briefs/
      reports/
      reviews/
      verification/
      logs/
      outbox/
      result.json

    ~/.codex/worktrees/RUN_ID/

All durable files are private. Input snapshots and accepted artifacts are
digest-bound. events.jsonl is the authoritative transition history and
events.head.json detects truncation or unsynced tails. artifacts.jsonl binds
logical paths to immutable bytes. result.json exists only after terminal
integration.

Mapping publications are content-addressed under a generation's attempts
directory. One map.generation_created event uniquely selects the accepted
publication. Event-selected evidence is never eligible for automatic deletion.
The store retains one live unselected Program Mapper attempt per generation,
including strict partial pre-manifest groups. It durably tombstones pruned
index records before unlink and finishes interrupted unlinks on open.

## Execution Shape

1. One fresh mapper reads each immutable document.
2. One fresh program mapper composes lossless briefs, dependencies, coverage,
   hotspots, and authority items.
3. The non-LLM queue launches one ready task agent at a time.
4. A fresh reviewer checks the exact task handoff; one consolidated fixer and
   a changed-strategy investigator handle ordinary defects.
5. Fresh document auditors verify source coverage at the final revision.
6. One Program Final Integrator performs cross-program review and one full
   verification.
7. Any later write invalidates affected final evidence before closure repeats.

Superpowers owns TDD, code review, and verification-before-completion inside
the applicable fresh role. CPE owns only durable orchestration and strict
contract validation.

## Schema 3

CPE 4 inspect can summarize an existing schema-3 directory without mutation.
CPE 4 does not migrate or resume it. Use the pre-4.0 Git revision only after an
explicit decision to operate the historical implementation.

## Verify

    ./evals/run.sh
    python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/*.py evals/*.py
    bash -n evals/run.sh
    python3 scripts/cpe.py --help
    python3 scripts/cpe.py run --help
    python3 scripts/cpe.py export --help

The runner executes exactly six deterministic checks and must finish under 60
seconds on the development machine. See docs/evals-and-verification.md for the
coverage boundary and docs/risks-limitations-deferrals.md for known risks.
