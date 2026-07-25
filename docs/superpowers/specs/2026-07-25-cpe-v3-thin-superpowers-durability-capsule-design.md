# CPE v3 Thin Superpowers Durability Capsule Design

**Date:** 2026-07-25

**Status:** Approved design

**Repository:** `/Users/kws/source/private/Archive`

**Target:** `skills/kws-codex-plan-executor/`

**Release boundary:** Clean-room CPE v3 replacement

## 1. Summary

CPE v3 is a thin, Codex-specific durability capsule around one Superpowers
root-controller execution contract. It accepts any number of approved design,
specification, implementation-plan, incident, context, and authority documents,
seals their bytes as one immutable document bundle, assigns one Git worktree,
and launches one Codex root controller with one explicitly selected Superpowers
entry skill.

CPE does not interpret the documents. It does not compile tasks, keep a task
database, advance an ordered plan queue, infer completed work, mirror
Superpowers progress, select or execute product verification, track reviews or
findings, or decide that engineering work is complete.

Superpowers owns engineering workflow meaning. In
`subagent-driven-development`, the plan-scoped
`.superpowers/sdd/<plan-basename>/` workspace, its `progress.md`, task reports,
review packages, fix rounds, and Git history are the semantic recovery source
of truth. In `executing-plans`, the root controller session is the primary
continuity source. CPE resumes that session first and permits one fresh
controller only when the provider explicitly classifies the session as missing
or corrupt.

CPE owns only external execution facts:

- immutable document bytes and identities;
- one run ID;
- one source repository, base commit, branch, and worktree;
- one Codex controller session at a time;
- process lifecycle and mutual exclusion;
- the last observed Git HEAD and bounded worktree facts;
- bounded, opaque recovery facts;
- one optional, opaque resume capsule;
- a truthful local handoff.

The successful CPE terminal state is `handed_off`, not `completed`. It means
that a controller claimed completion and the recorded local Git handoff is
mechanically self-consistent. It does not mean that CPE independently verified
tests, review quality, product behavior, integration, publication, or remote
state.

## 2. Governing Rule

> Superpowers owns engineering workflow meaning. CPE preserves one local Codex
> execution boundary.

Every CPE field, command, module, test, report, and recovery decision must be
justified by the right-hand side of that sentence. If a feature requires CPE
to understand tasks, reviews, test meaning, implementation strategy, or
workflow completion, it belongs to Superpowers or a higher-level provider plan
runner instead.

### 2.1 Design precedence

This design supersedes earlier CPE 2.x designs for the future CPE runtime,
including their executable legacy migration, plan-level state, completion
receipts, verification arrays, optimization reporting, and default
`danger-full-access` decisions.

It also supersedes the CPE-retirement portion of earlier provider-runner
designs. The approved product decision is now to retain CPE only as an
independent single-execution-contract Codex durability capsule. It does not
change the separately approved thin-boundary redesign of the Codex and Claude
provider plan runners.

## 3. Context And Evidence

### 3.1 Superpowers v6.2.0 changed the ownership boundary

Superpowers v6.2.0 introduced plan-scoped SDD workspaces under
`.superpowers/sdd/<plan-basename>/`. The workspace contains the recovery ledger,
task briefs and reports, review packages, and bounded fix-loop state. A clean
final review removes the temporary workspace while Git history remains the
durable record.

This makes a separate CPE task ledger, review ledger, completed-task inference
model, or fix-round state redundant and conflicting. CPE must not reconstruct
or validate those semantics.

Reference:

- <https://github.com/obra/superpowers/releases/tag/v6.2.0>

### 3.2 Direct Superpowers succeeds because it has one control plane

When a user gives a well-written design and implementation plan directly to
Superpowers, the root session already owns:

- the complete conversation and authority;
- installed skill selection;
- task interpretation;
- implementer and reviewer coordination;
- plan-scoped SDD progress;
- Git commits and review history;
- implementation and verification meaning.

The legacy CPE adds a second control plane around that workflow. It asks the
controller to emit CPE-specific progress and completion artifacts, then tries
to validate them independently. Failures at that added boundary can stop an
otherwise healthy Superpowers execution.

### 3.3 The current implementation is not thin

At the observed recovery candidate HEAD
`0450c65252368cc7c49a755ec909d7085aef4141`, the tracked CPE implementation
contains approximately:

- 9,773 lines in ten Python runtime modules;
- 9,709 lines in `evals/check_runner.py`;
- 2,768 lines in `scripts/cpe_runtime/runner.py`;
- 2,111 lines in `scripts/cpe_runtime/migration.py`;
- 1,626 lines in `scripts/cpe_runtime/launcher.py`;
- 1,063 lines in `scripts/cpe_runtime/state.py`;
- 1,057 lines in `scripts/cpe_runtime/reporting.py`.

The candidate added roughly 12,526 lines and removed 7,767 lines relative to
its original base. A paused Fix Round 5 then added another 605 lines and removed
69 lines across result publication, launcher, runner, state, and fake-provider
tests.

The problem is not line count by itself. The line count reveals responsibilities
that do not belong in a document-and-session durability wrapper:

- format migration and crash-consistent publication transactions;
- task and checkpoint schemas;
- review, finding, and obligation receipts;
- verification arrays and final-verification interpretation;
- result-file attestation against a same-UID child;
- artifact inventory and optimization reporting;
- capability and environment inference;
- duplicated workflow completion rules.

### 3.4 Incident response expanded authority instead of removing it

Historical incidents were addressed by adding ledgers, schemas, guards,
journals, repair paths, result sealing, and migration safety layers. Those
changes attempted to make the second control plane safe. They did not remove
the duplicate control plane.

CPE v3 takes the opposite approach: delete every semantic authority that
requires the extra evidence system.

## 4. Goals

1. Make direct Superpowers behavior the normal implementation path inside CPE.
2. Accept multiple approved documents without compiling or interpreting them.
3. Preserve one run, worktree, branch, and Codex root-controller session across
   process interruption.
4. Prefer same-session resume for both supported Superpowers entry skills.
5. Permit one fresh-controller fallback only for proven missing or corrupt
   sessions.
6. Seal and inject one valid Git author/committer identity without copying a
   general Git configuration.
7. Preserve bounded, workflow-neutral recovery facts without a task ledger.
8. Produce a truthful local Git handoff without claiming engineering
   completion.
9. Default to `workspace-write`; make `danger-full-access` explicit and
   immutable.
10. Preserve legacy artifacts and recovery worktrees in place without
   migration.
11. Make the production runtime and deterministic test surface small enough to
    audit as one mechanical boundary.

## 5. Non-Goals

CPE v3 does not:

- parse Markdown headings or tasks;
- build a dependency graph;
- own an ordered multi-plan queue;
- create one controller session per plan document;
- read or write Superpowers `progress.md`;
- create a task, review, or finding ledger;
- infer completed tasks from Git or workspace files;
- select implementers, reviewers, models, or fix strategies;
- select, execute, cache, or interpret product verification commands;
- require a final-review receipt;
- aggregate open findings or obligations;
- prove that controller claims are semantically correct;
- migrate format-3 or format-4 runs;
- repair arbitrary run-state corruption;
- merge, push, open a PR, tag, publish, release, or deploy;
- become a Waygent runtime dependency;
- become a shared production runtime for provider plan runners;
- provide Windows process and locking support in v3.

## 6. Product Topology

There are three independent entry paths.

```text
bounded work that fits one session
    -> direct Superpowers

one execution contract that needs Codex process/session durability
    -> CPE v3
       -> one Codex root controller
       -> one selected Superpowers entry skill

multiple plans that require separate provider sessions and ordered handoffs
    -> provider plan runner
       -> one provider root session per plan
```

CPE and provider plan runners do not call or nest one another. Nesting would
create two run IDs, worktree authorities, session authorities, recovery loops,
and terminal-state definitions.

Mechanical utilities such as canonical JSON encoding or Git fact collection
may be duplicated or shared only when they do not introduce shared state,
runtime authority, or recovery policy. There is no common production executor
layer.

## 7. Ownership Matrix

| Concern | CPE | Superpowers | Provider plan runner |
| --- | --- | --- | --- |
| Immutable document bytes | Owns | Reads | Owns for its runs |
| One CPE run ID | Owns | Observes | Does not nest |
| CPE worktree and branch | Owns identity | Mutates through implementation | Does not nest |
| Git author/committer identity | Seals and injects | Uses | Owns for its runs |
| Codex process/session | Owns | Runs inside | Owns its own provider session |
| Task decomposition | Must not own | Owns | Must not own |
| SDD `progress.md` | Must not read or write | Owns | Must not parse |
| Task completion | Must not infer | Owns | Must not infer |
| TDD and implementation | Must not direct | Owns | Must not direct |
| Task and final review | Must not track | Owns | Must not duplicate |
| Fix rounds | Must not track | Owns | Must not duplicate |
| Product verification | Must not execute or interpret | Owns | May mechanically execute its approved exact set |
| Session-loss fallback | Owns one CPE fallback | Reconstructs meaning from its sources | Owns its own provider recovery |
| Local Git handoff | Owns mechanical facts | Produces candidate history | Owns its own handoff |
| Merge and remote mutation | Prohibited | Prohibited by CPE contract | Separate explicit authority only |

## 8. One Run, One Execution Contract, Multiple Documents

One CPE run is not limited to one Markdown file. It represents one user-approved
execution contract and may contain any number of documents.

Supported immutable input roles are:

- `spec`;
- `plan`;
- `context`;
- `authority`.

Each role is repeatable. The declared role and input order are external facts,
not semantic instructions interpreted by CPE.

Example:

```bash
python3 scripts/cpe.py run \
  --spec /abs/design-a.md \
  --spec /abs/design-b.md \
  --plan /abs/implementation-1.md \
  --plan /abs/implementation-2.md \
  --context /abs/incident-report.md \
  --authority /abs/execution-contract.md \
  --workspace /abs/repository \
  --superpowers-skill subagent-driven-development
```

All documents go to one root controller in one immutable bundle. Superpowers
decides how their contents relate and in what semantic order to execute them.
CPE never advances a `current_plan_index` and never marks one input document
complete.

## 9. CLI Contract

CPE v3 has three primary commands:

```text
run
resume
inspect
```

`run` accepts:

- repeatable `--spec`;
- repeatable `--plan`;
- repeatable `--context`;
- repeatable `--authority`;
- required `--workspace`;
- required `--superpowers-skill`, with values:
  - `subagent-driven-development`;
  - `executing-plans`;
- optional `--sandbox`, defaulting to `workspace-write`;
- optional explicit `--adopt-worktree`;
- required `--base` when adopting an existing worktree.

At run creation, CPE resolves one Git author and committer identity from the
source repository's effective Git configuration. Missing or malformed identity
is a pre-execution blocker. CPE records the private identity in the immutable
manifest and injects only the required `GIT_AUTHOR_*` and `GIT_COMMITTER_*`
variables into the controller process. It does not copy the user's complete
Git configuration.

`resume` accepts one run ID. It does not accept a different sandbox, document
bundle, worktree, base, or entry skill.

`inspect` is read-only.

Removed commands and options include:

- `migrate-run`;
- plan-specific retry or advancement commands;
- ledger append, inspect, repair, or recovery commands;
- verification helper commands;
- workflow finalization commands.

The selected Superpowers skill is an immutable launch input. It does not change
CPE state shape, recovery rules, terminal rules, or artifact interpretation.

## 10. Immutable Document Bundle

For every input, CPE records:

- role;
- declaration order within the role;
- original absolute path;
- private snapshot path;
- SHA-256;
- byte length.

The snapshot name is deterministic and collision-resistant at the filename
level:

```text
<role>-<ordinal>-<original-basename>
```

For example:

```text
plan-001-implementation.md
plan-002-implementation.md
```

The filename prefix reduces collisions in Superpowers plan-scoped workspace
names without changing document bytes. CPE does not rewrite headings,
references, or content.

Repository instructions such as `AGENTS.md` remain authoritative through the
recorded base commit and live worktree. Explicit parent authority that is not
already in the approved documents must be supplied through repeatable
`--authority` inputs rather than reconstructed from chat history.

## 11. Run Artifacts

A new run root contains only:

```text
run-root/
  manifest.json
  state.json
  inputs/
  receipts/
  handoff.json        # only after successful handoff
```

The default location is:

```text
${CODEX_HOME:-~/.codex}/cpe-v3/runs/<run-id>/
```

The v3 namespace is separate from legacy run roots. A default new worktree uses
the existing Codex worktree area and a `codex/<run-id>` branch. Paths and IDs
are resolved and recorded before the immutable manifest is sealed.

There is no CPE task ledger, review ledger, optimization report, artifact
inventory, migration directory, obsolete-artifact quarantine, or branch-wide
verification cache.

### 11.1 `manifest.json`

`manifest.json` is written once and then made read-only. It contains:

- contract version;
- run ID;
- source repository;
- base commit;
- branch;
- worktree;
- immutable input records;
- selected Superpowers skill;
- sealed Git author/committer identity;
- sandbox mode;
- noninteractive approval policy;
- integration policy;
- remote-action policy;
- creation time.

It contains no mutable execution status and no plan or task records.

### 11.2 `state.json`

`state.json` is the only mutable durable state file. Updates use one atomic
same-directory replace.

Conceptual shape:

```json
{
  "status": "running",
  "controller": {
    "session_id": "provider-session-id",
    "generation": 0,
    "fresh_fallback_used": false
  },
  "active_process": {
    "invocation_id": "opaque-id",
    "pid": 123,
    "process_group": 123
  },
  "last_observed_head": "40-hex",
  "worktree": {
    "tracked_clean": false,
    "status_digest": "64-hex"
  },
  "last_process_outcome": {
    "class": "interrupted",
    "exit_code": 1
  },
  "resume_capsule_ref": null,
  "blocker": null,
  "handoff_ref": null,
  "updated_at": "RFC-3339"
}
```

The final schema may use more compact field names, but it must not add workflow
meaning.

Allowed states are:

- `prepared`;
- `running`;
- `interrupted`;
- `blocked`;
- `failed`;
- `handed_off`.

There is no `checkpointed` state. A checkpoint is an optional controller hint,
not a CPE workflow stage.

### 11.3 Process receipts

After each controller process exits, CPE may write one small immutable receipt
containing only:

- invocation identity;
- whether it was initial, same-session resume, or fresh fallback;
- session ID observed;
- generation;
- normalized provider/process outcome;
- exit code;
- before and after Git facts;
- terminal-envelope digest when present.

Receipts do not include task, review, verification, transcript, or product
semantics.

## 12. Controller Launch Packet

The controller packet contains:

1. the immutable document manifest and snapshot paths;
2. the assigned worktree and base commit;
3. the selected Superpowers entry skill;
4. the sealed Git identity supplied through process environment;
5. the local-only integration and remote-action policy;
6. the instruction to read repository `AGENTS.md`;
7. the instruction to use Superpowers and Git as semantic recovery sources;
8. the minimal terminal-envelope contract.

The packet does not restate:

- TDD rules;
- SDD task/report/review procedures;
- fix-round limits;
- final-review procedure;
- verification selection;
- task completion;
- plan progress;
- migration semantics.

Those rules remain in the installed Superpowers skills and approved documents.
CPE must not freeze a private copy of them in Python prompt templates.

## 13. Minimal Terminal Envelope

The controller returns a small structured terminal envelope through its output
stream. It does not publish a result file into the CPE run root.

Successful claim:

```json
{
  "claim": "completed",
  "head_commit": "40-hex",
  "summary": "bounded child-attested summary"
}
```

Incomplete claim:

```json
{
  "claim": "interrupted",
  "head_commit": "40-hex",
  "summary": "bounded child-attested summary",
  "resume_capsule": {
    "head_commit": "40-hex",
    "worktree_status_digest": "64-hex",
    "note": "bounded opaque note",
    "evidence_refs": ["relative/path"]
  }
}
```

A blocked claim may include one normalized external blocker.

The envelope does not contain:

- `plan_id`;
- `verification`;
- `completion_receipt`;
- `final_review_head`;
- `open_finding_ids`;
- `open_obligation_ids`;
- `completed_task_ids`;
- `current_task_id`.

CPE validates structure, bounds, Git object shape, and relative-path safety. It
does not validate the semantic truth of the summary or note.

## 14. Opaque Resume Capsule

The optional resume capsule is bounded and workflow-neutral.

It may contain:

- observed HEAD;
- worktree status digest;
- a UTF-8 note of at most 2 KiB;
- at most sixteen worktree-relative evidence references;
- normalized external-failure facts.

CPE:

- validates type, size, path containment, and digest;
- stores the bytes privately;
- does not parse tasks or rewrite the note;
- does not use the capsule for a healthy same-session resume;
- passes it only to the one permitted fresh controller.

For SDD, the fresh controller is instructed to inspect the plan-scoped
Superpowers workspace and Git before trusting the capsule. For
`executing-plans`, which has no SDD ledger, the controller uses the same
worktree, Git history, and capsule as recovery inputs and independently
revalidates them.

## 15. Execution Lifecycle

### 15.1 Initial run

1. Validate immutable inputs and selected sandbox.
2. Resolve the source repository and base commit.
3. Create a new branch/worktree or explicitly adopt an existing one.
4. Write the immutable manifest and initial state.
5. Acquire the run lock.
6. Launch one Codex root controller.
7. Persist the first valid session ID as soon as it is observed.
8. Stream provider output without storing a full transcript.
9. Normalize the process outcome and observe current Git facts.
10. Either produce a local handoff or record an incomplete external state.

### 15.2 Same-session resume

Same-session resume is the default recovery for:

- user or host interruption;
- controller process interruption;
- temporary provider transport failure;
- an incomplete local handoff;
- a controller that stopped before submitting a terminal envelope.

The resume prompt does not reconstruct workflow progress. It points the same
session at the same worktree and immutable contract and instructs it to
continue from the actual Superpowers and Git state.

One CLI invocation performs at most one automatic same-session retry. CPE never
runs an unbounded internal resume loop. Later attempts require an explicit
`resume` invocation.

### 15.3 Fresh-controller fallback

A fresh controller is allowed only when all of these facts hold:

1. the provider explicitly classifies the stored session as missing or corrupt;
2. the outcome is not a generic nonzero exit, timeout, auth failure, quota
   failure, invalid envelope, or provider outage;
3. the run has not used a fresh fallback before;
4. the immutable inputs, run ID, branch, worktree, and base remain unchanged.

The controller generation changes from zero to one exactly once. A missing or
corrupt generation-one session produces `blocked`; there is no second fallback.

The fresh controller receives:

- the complete immutable document bundle;
- the same run ID, branch, and worktree;
- base commit and current observed HEAD;
- bounded Git facts;
- the opaque resume capsule when available;
- normalized facts explaining why the old session is unavailable.

It does not receive CPE-inferred task completion.

### 15.4 Repeated external failure

Material progress for CPE recovery is limited to:

- observed HEAD change;
- tracked worktree status-digest change;
- successful controller-session acquisition;
- successful local-handoff creation.

Task completion, review progress, test output, or narrative claims are not CPE
progress signals.

If the same normalized external-failure fingerprint repeats at the same Git
facts twice, automatic recovery stops. The state becomes `blocked` or
`interrupted` according to the external class.

The fingerprint is built from normalized facts such as outcome class,
operation, provider code, and resource. It is not a hash of raw error text.

## 16. Process And Locking Model

CPE v3 targets POSIX hosts.

- Each run has one advisory file lock.
- The controller child inherits the lock descriptor.
- If the parent CPE process dies while the child remains alive, another CPE
  invocation cannot acquire the run lock and edit the same worktree.
- The controller runs in its own process group.
- SIGINT and SIGTERM trigger bounded process-group termination.
- After termination, state records `interrupted`.
- `inspect` never acquires mutation authority or resumes a controller.

Provider output is consumed as a stream. CPE extracts only the session ID,
normalized process/provider facts, and terminal envelope. It does not persist
a full raw transcript by default.

Initial, resumed, and fallback controllers use the same noninteractive Codex
profile, selected sandbox, and approval policy `never`. The controller uses the
active installed Superpowers skills; CPE does not create a private skill copy
or an isolated home that loses provider-session continuity. A command requiring
authority outside the immutable sandbox fails rather than prompting for
interactive escalation.

This removes the need for child-published result paths, reserved result files,
held output descriptors, hard-link no-clobber publication, or a result
publication journal.

## 17. Git And Worktree Contract

CPE may observe and enforce only:

- repository identity;
- branch identity;
- worktree association;
- base commit existence;
- observed HEAD;
- base ancestry;
- tracked clean or dirty state;
- a bounded status digest.

CPE does not interpret changed files as completed tasks or decide which tests
are affected.

### 17.1 New worktree

The normal path creates one branch and linked worktree for the run. CPE does
not reset, rebase, merge, cherry-pick, or rewrite it.

### 17.2 Explicit worktree adoption

Legacy or externally interrupted work can be continued only through explicit
adoption. Adoption validates:

- the path is an actual Git worktree;
- it belongs to the declared repository;
- its branch and HEAD exist;
- the declared base is an ancestor of HEAD;
- no live v3 worktree lock owns it.

The worktree may be dirty. CPE records the starting HEAD and status digest but
does not alter files or infer prior completion.

Adoption does not read legacy CPE state. The new controller reconstructs
meaning from approved documents, the worktree, Git, and Superpowers artifacts.

`--adopt-worktree` is also an explicit operator assertion that no legacy
controller still owns the worktree. CPE v3 can verify its own locks but cannot
prove liveness for every older runtime format. It never scans for or terminates
an unknown legacy process.

## 18. Local Handoff

CPE creates `handoff.json` only after:

- the controller submits `claim: completed`;
- the submitted HEAD equals the observed worktree HEAD;
- the observed HEAD descends from the base;
- the tracked worktree is clean;
- branch and worktree identity still match the manifest.

The handoff records:

- run ID;
- branch;
- saved worktree;
- base commit;
- observed HEAD;
- `controller_claim: completed`;
- controller session and generation;
- `integration: not_observed`;
- `remote_actions_by_cpe: none`.

It does not contain verification results, review results, findings,
obligations, or an assertion that remote actions by the controller were proven
absent.

If Git checks fail, CPE does not publish a handoff. A healthy controller session
may be resumed so Superpowers can finish the work.

## 19. Sandbox And Security Boundary

### 19.1 Default sandbox

`workspace-write` is the default. `danger-full-access` requires explicit opt-in
at run creation and becomes immutable.

CPE never upgrades permissions during resume or fallback. If the immutable
sandbox cannot perform the approved work, CPE records a bounded blocker rather
than bypassing the boundary.

All controller launches use noninteractive approval policy `never`. This is
separate from sandbox authority: `never` prevents an unattended controller
from waiting for an approval prompt, while the sandbox still determines which
operations are permitted.

### 19.2 Private artifacts

- run root directories use mode `0700`;
- private mutable files use mode `0600`;
- immutable snapshots and manifests may become `0400`;
- symlinked input, run-root, state, or output targets are rejected;
- paths in resume capsules must be relative and contained by the worktree.

### 19.3 Threat-model limit

CPE does not defend against a malicious same-UID controller, direct operator
tampering with the run root, a dishonest provider, or arbitrary external
mutation under `danger-full-access`.

Trying to provide that guarantee caused the previous inode, no-clobber,
publication, journal, and attestation layers. Those mechanisms are not part of
v3.

CPE's security claim is narrower:

- private-by-default local artifacts;
- no CPE-authored remote mutation;
- explicit sandbox authority;
- fail-closed local state and Git identity;
- bounded external data;
- no hidden workflow authority.

## 20. Legacy Format Policy

Format-3 and format-4 artifacts remain in place and read-only.

CPE v3:

- does not migrate them;
- does not quarantine or clean them;
- does not project them into v3 state;
- does not recover task or review meaning from them;
- does not create a replacement run automatically.

When `inspect` encounters a recognized legacy version, it returns only:

- `status: legacy_read_only`;
- detected version;
- run-root location;
- a recommendation to preserve the artifact and use explicit worktree
  adoption when continuation is required.

It must not mutate the legacy run while identifying it.

The current branch
`codex/cpe-thin-superpowers-v62-recovery`, its committed history, and its paused
Fix Round 5 worktree remain forensic evidence. They are not merged into the
v3 implementation branch and are not rewritten or cleaned by this design.

## 21. Error Classification

CPE error classes remain external and small.

| Class | Example | CPE action |
| --- | --- | --- |
| `interrupted` | signal or stopped process | preserve state; same-session resume |
| `transport` | temporary provider transport failure | at most one automatic same-session retry |
| `session_unavailable` | explicit missing/corrupt session | one fresh fallback |
| `auth` | authentication unavailable | `blocked`; no credential guessing |
| `quota` | provider quota | `blocked`; no fallback |
| `provider_unavailable` | persistent provider outage | `blocked` |
| `invalid_envelope` | malformed terminal claim | preserve facts; same session may repair |
| `handoff_incomplete` | dirty tree or HEAD mismatch | no handoff; same session may continue |
| `integrity` | manifest, path, branch, base, or state violation | `failed`; no automatic repair |

CPE does not run project capability probes or infer implementation failure from
test output.

## 22. Clean-Room Runtime Structure

The implementation is rewritten against this design rather than trimmed from
the v2 runtime.

Proposed production modules:

- `scripts/cpe.py` — CLI and JSON exit contract;
- `scripts/cpe_runtime/state.py` — manifest, state, bounds, atomic replace;
- `scripts/cpe_runtime/git.py` — worktree and Git facts;
- `scripts/cpe_runtime/controller.py` — Codex stream, session, process group;
- `scripts/cpe_runtime/runtime.py` — run, resume, inspect, handoff transitions.

The target is approximately 1,500 to 2,000 production Python lines, with no
module larger than roughly 600 lines. The exact line count is not an acceptance
substitute; responsibility tests are authoritative.

Modules and surfaces removed from the v3 production design include:

- `migration.py`;
- `progress.py`;
- `reporting.py`;
- `capabilities.py`;
- `result_validation.py`;
- completion, verification, execution-ledger, migration, and optimization
  schemas;
- branch-wide artifact inventory;
- token-attribution reporting;
- task and review evidence projection.

Existing filenames may be deleted rather than retained as compatibility shims.

## 23. Deterministic Verification

Deterministic tests cover only CPE-owned contracts:

1. multiple immutable inputs by role and order;
2. deterministic same-basename snapshot names;
3. manifest immutability;
4. atomic single-file state updates;
5. worktree creation;
6. explicit clean and dirty worktree adoption;
7. lock inheritance and concurrent-resume refusal;
8. process-group interruption;
9. immediate session-ID persistence;
10. Git identity capture, private sealing, and process injection;
11. missing Git identity as a pre-execution blocker;
12. same-session resume;
13. one fallback only for explicit missing/corrupt session;
14. no fallback for auth, quota, generic nonzero, timeout, or invalid envelope;
15. bounded resume capsule;
16. immutable sandbox and noninteractive approval configuration;
17. HEAD equality and ancestry;
18. tracked-clean handoff;
19. legacy read-only detection and byte preservation;
20. truthful `handed_off` output.

Architecture tests reject reintroduction of semantic state fields or commands,
including:

- `task_id`;
- `current_plan_index`;
- `completed_task`;
- `fix_round`;
- `final_review`;
- `finding`;
- `obligation`;
- `verification`;
- `migrate-run`.

Tests are split by contract. A fake controller implements only provider JSONL,
session resume, process exit, and terminal-envelope behavior. It does not model
Superpowers tasks or reviews.

## 24. Live Canaries

### 24.1 SDD multi-document canary

The canary uses:

- multiple design, plan, context, and authority documents;
- one root controller;
- `subagent-driven-development`;
- an interruption followed by same-session resume.

Acceptance:

- Superpowers owns its plan workspace and task/review semantics;
- CPE state contains no task or review projection;
- the same run, branch, worktree, and session are retained;
- local handoff is `handed_off`;
- integration remains `not_observed`.

### 24.2 Executing-plans session-loss canary

The canary demonstrates:

- no SDD ledger dependency;
- same-session resume attempted first;
- explicit provider classification of a missing session;
- one generation-zero to generation-one fallback;
- identical run, branch, worktree, inputs, base, and current HEAD;
- use of the bounded opaque capsule;
- no second fallback;
- no task-completion reconstruction.

### 24.3 Legacy adoption canary

The canary demonstrates:

- format-3/4 artifact hashes remain unchanged;
- no migration, quarantine, or cleanup occurs;
- an existing dirty worktree is explicitly adopted;
- the new controller derives meaning from documents, Git, worktree contents,
  and Superpowers artifacts;
- the new run has a distinct v3 identity without altering the legacy run.

Canary receipts contain only run/session/process/Git/handoff facts.

## 25. Change-Impact Canary Selection

During implementation, live canaries may be selected by a small fixed path map:

- prompt or input-bundle changes:
  - SDD multi-document canary;
- controller or recovery changes:
  - SDD multi-document and session-loss canaries;
- Git or worktree changes:
  - SDD multi-document and legacy-adoption canaries;
- state or security changes:
  - full deterministic suite;
- release candidate:
  - full deterministic suite and all three live canaries.

The path map must remain declarative and small. CPE must not grow a dependency
analysis engine to optimize its own canaries.

## 26. Independent Review And Release Gate

The v3 candidate receives a full BASE..HEAD review after all release canaries.
The reviewer checks:

- the ownership matrix in this design;
- absence of task/review/verification authority;
- multiple-document behavior without a plan queue;
- same-session resume;
- exactly one fresh fallback;
- bounded workflow-neutral capsule;
- legacy read-only preservation;
- default `workspace-write`;
- explicit full-access opt-in;
- process and lock behavior;
- truthful handoff wording;
- runtime and eval size;
- tracked worktree cleanliness;
- no remote mutation.

Critical and Important findings must be resolved through the installed
Superpowers fix/re-review procedure. CPE does not create a separate review
ledger for its own implementation.

## 27. Rollout

1. Preserve the existing recovery branch and dirty WIP unchanged.
2. Implement v3 on a new branch from the latest local `main`.
3. Write a fresh implementation plan from this approved design.
4. Use direct `subagent-driven-development` to implement the plan.
5. Do not self-host CPE while modifying CPE.
6. Run deterministic contract tests throughout implementation.
7. Run impact-selected canaries after relevant changes.
8. Run all release canaries at the final candidate HEAD.
9. Perform independent full-diff review.
10. Merge only the clean v3 candidate to the then-current local `main`.
11. Re-run deterministic verification after the merge.
12. Do not push, open a PR, tag, publish, release, or deploy without separate
    authority.

## 28. Residual Risks

1. **Same-basename upstream behavior:** deterministic snapshot prefixes reduce
   collisions, but future Superpowers workspace naming may use a different
   source identity.
2. **Explicit full access:** `danger-full-access` permits same-UID mutation
   outside the worktree and cannot be fully audited by CPE.
3. **Provider truth:** CPE cannot prove that a controller's completion claim or
   summary is honest.
4. **Session API drift:** Codex JSONL and session-resume behavior may change.
5. **No full transcript:** minimized private evidence limits some forensic
   debugging.
6. **Git identity scope:** a sealed process identity does not reproduce every
   repository-local signing, credential, or commit-hook configuration.
7. **POSIX-only:** lock inheritance and process groups do not provide Windows
   support.
8. **Legacy interpretation:** preserved legacy artifacts may require manual
   analysis because v3 intentionally does not parse their semantics.
9. **Dirty adoption:** an adopted worktree may contain incomplete or unrelated
   work, and an unobserved legacy controller could still be live; the operator,
   controller, and approved documents must resolve those risks.

## 29. Alternatives Considered

### 29.1 Trim the current v2 runtime in place

Rejected. The existing state schema, migration path, result contract, and test
harness encode the duplicate authority. Proving that every implicit dependency
was removed would be harder than implementing the permitted boundary directly.

### 29.2 Retire CPE completely

Rejected for now. Direct Superpowers and provider plan runners cover most
execution, but a narrow need remains for one long-lived Codex execution
contract with a stable local worktree and session-resume boundary.

### 29.3 Use CPE as the provider runner's execution engine

Rejected. Nesting would duplicate run, worktree, session, recovery, and
terminal-state authority. The tools remain independent.

### 29.4 Keep executable legacy migration

Rejected. Migration safety dominated the current remediation and required a
second transaction system. Read-only preservation plus explicit worktree
adoption retains user work without keeping migration in the core runtime.

## 30. Acceptance Criteria

CPE v3 is ready to implement when the implementation plan preserves all of the
following:

1. One run represents one execution contract and accepts multiple documents.
2. One run has one worktree, branch, and root controller at a time.
3. There is no CPE-owned plan queue or semantic progress model.
4. Superpowers remains the only owner of task, TDD, review, fix, verification,
   and engineering completion meaning.
5. Same-session resume is the default.
6. Fresh fallback is permitted exactly once and only for explicit missing or
   corrupt sessions.
7. The fallback preserves run ID, worktree, branch, inputs, base, HEAD, and
   bounded capsule facts.
8. `workspace-write` is the default and full access is explicit.
9. Git author/committer identity is valid, private, immutable, and consistent
   across initial, resumed, and fallback controllers.
10. Success is `handed_off`, not `completed`.
11. The handoff contains only mechanical local facts and child-attested claim.
12. Legacy format-3/4 artifacts remain byte-for-byte untouched.
13. The current recovery branch and Fix Round 5 WIP remain unmerged forensic
    evidence.
14. The production runtime contains no migration, task, review, finding,
    obligation, or verification authority.
15. All deterministic contracts and three release canaries pass.
16. Independent full-diff review reports Critical 0 and Important 0.
17. The implementation and local merge perform no push, PR, tag, publish,
    release, or deploy.
