# CPE V4 Mainline Residual Risks And Follow-Up Work

This document is the canonical closeout register for the CPE v4 code merged to
`main` on 2026-07-13. It separates deterministic implementation evidence from
live release evidence and lists the remaining work in execution order.

## Current status

Snapshot basis: `main` at `5901a91ad946301489e4c336ec5e1d292f848a0d`.

| Surface | Current state | Claim allowed |
| --- | --- | --- |
| CPE v3.1.0 | Published historical release with its reviewed v3 evidence | `deterministic-ready; paid-live-verified` for v3.1.0 only |
| CPE v4 implementation | Merged; deterministic CPE evals and repository checks passed | Deterministic implementation is present on `main` |
| V4 critical live proof | Not run for the merged checkpoint | Do not claim `critical-path-live verified` |
| V4 full 17-call matrix | Deferred | Report `full paid-live certification deferred` |
| V4 release readiness | Blocked by P0 trust anchoring and current live evidence | Do not publish or label v4 release-ready |

The merged-main cost-free gate passed before push:

- `./evals/run.sh`: passed; `paid_execution=skipped_not_approved`.
- `bun run check`: 820 passed, 10 skipped, 0 failed across 149 files.
- `git diff --check`: passed.
- local `main`, `origin/main`, and `git ls-remote origin refs/heads/main`
  resolved to the same commit.

These checks prove deterministic behavior and integration. They do not prove
real provider quality, subscription availability, account-side cost routing,
or a terminal v4 release generation.

## Risk register

### R1. Release policy and dogfood contract are not anchored to Git blob bytes

**Priority:** P0 / Critical
**Status:** Open; blocks any new credentialed v4 release proof.

`cpe_runtime.release_policy_v4.load_release_policy()` confirms that the policy
and dogfood contract paths are tracked with `git ls-files`, but it reads their
bytes from the mutable worktree. A caller can also supply a different tracked
policy path through the public loader seam. Therefore, a dirty tracked policy
and matching dirty contract can replace the intended trust anchors without
changing `HEAD`. The compiler, runner, finalizer, and validator share this
loader, so the substitution can affect release decisions before a provider
call.

The existing canonical-JSON, digest, ancestry, patch, budget, and closed-root
checks remain valuable. They do not close this specific Git-object boundary.

**Required repair:**

1. Make the production policy path fixed and non-caller-selectable. Keep any
   alternate-path seam private to isolated tests.
2. Resolve policy and dogfood contract bytes from the exact reviewed Git commit
   using blob/object reads, not worktree filesystem reads.
3. Bind policy blob OID, policy SHA-256, contract blob OID, and contract SHA-256
   into the manifest, ledger, terminal generation, and public validation.
4. Reject index drift, worktree drift, path substitution, blob substitution,
   missing objects, and commit mismatch before a credentialed launch.
5. Ensure the sealed launch and dogfood flow consume only bytes derived from
   the verified object binding.

**Required RED cases:** dirty tracked policy, dirty matching contract, alternate
tracked policy path, staged-only substitution, policy blob from another commit,
contract blob from another commit, and post-compilation worktree mutation.

**Done when:** every mutation fails before provider invocation, the full
cost-free CPE suite passes, and a fresh trust/privacy review finds no remaining
mutable source of release authority.

### R2. The merged checkpoint has no current critical-path live proof

**Priority:** P0 / Release blocker
**Status:** Not run.

The current mainline has zero credentialed calls for its checkpoint. Historical
v3 and failed v4 evidence remains lineage context, not current proof.

After R1 is fixed and independently reviewed, execute the risk-first sequence:

1. Run only `sol_v4_candidate / security/migration block` as the qualified
   sentinel. Require top-level `blocked`, `evidence_complete=true`, no forbidden
   side effect, correct hidden-oracle semantics, and exact envelope/schema/route
   bindings. Stop after this one call on any failure.
2. Resume the same run for one candidate normal-success regression, such as the
   single-file implementation case. Stop on failure.
3. Resume one Waygent dogfood run rather than replacing it. Use only as many
   model attempts as needed, with an absolute maximum of four. Stop without
   more calls when the same root cause repeats or a structural finding appears.
4. Aggregate and finalize only if both matrix calls and dogfood evidence are
   terminal, privacy-clean, checkpoint-bound, and independently reviewed.

The staged ceiling is two critical matrix attempts plus four dogfood attempts,
six total. It is a ceiling, not a target. A future session must confirm the
applicable credentialed-call authority before starting; never infer permission
from the existence of this document.

**Done when:** one terminal generation passes public validation and truthfully
reports `critical-path-live verified`. If optional certification is absent, it
must also report `full paid-live certification deferred`.

### R3. The required four-lane whole-branch integration review is not evidenced

**Priority:** P1 / Required before a v4 release claim
**Status:** Open.

The repository contains focused P0 reviews and deterministic E2E coverage, but
the closeout record does not contain one final independent four-lane review of
the exact merged checkpoint. Run the following lanes independently and combine
their findings once:

1. **State/crash:** journal ordering, replay parity, crash windows,
   idempotence, orphan generations, retry budgets, and resume behavior.
2. **Trust/privacy:** Git-object anchors, sealed-envelope/oracle separation,
   sanitized outputs, path/material leakage, auth isolation, and lineage.
3. **Public CLI/dataflow:** production CLI routing, exact bytes from compiler to
   provider, result/ledger/generation cross-binding, error codes, and resume.
4. **Live evidence/release lineage:** predecessor attestation, staged proof,
   dogfood checkpoint, terminal generation, labels, and historical/current
   evidence separation.

Apply at most one consolidated fix wave. If a second review wave finds new
issues, freeze and classify instead of automatically patching again. A third
defect in one task requires identifying and redesigning the missing structural
invariant rather than adding another local patch.

**Done when:** all four reports identify the reviewed commit and evidence
digests, findings are resolved or explicitly accepted, and one consolidated
verdict is recorded in the verification log.

### R4. Full paid-live certification remains optional and deferred

**Priority:** P2 / Optional certification
**Status:** Deferred by policy.

The complete 17-call paired matrix is not a merge requirement. Control, Terra,
and non-critical cases are currently covered by fake-provider, contract, and
oracle checks. Run `full_paid_matrix` only when the user explicitly requests
full paid-live certification. Do not reuse the historical 17-call run as proof
for a new checkpoint.

**Done when:** all 17 credentialed slots resolve under the immutable manifest,
the unchanged certification gate passes, privacy review passes, and the report
is explicitly labeled as full paid-live certification for its exact commit.

### R5. Predecessor continuity is local evidence, not external attestation

**Priority:** P2 / Accepted limitation
**Status:** Documented; no immediate code change required for the merge gate.

The predecessor importer validates a filesystem evidence root and stores a
domain-separated digest in the corrected root. It is not a signature,
timestamp authority, or remote transparency log. Loss of the original root
limits later independent re-verification even though tampering is detected
while the root is available.

If stronger provenance becomes a product requirement, design signed evidence
or a remote append-only transparency service as a separate security project.

### R6. Subscription cost attribution is not observable

**Priority:** P2 / Accepted limitation
**Status:** Documented.

The runner can require ChatGPT login and remove API-key credentials from child
environments. It cannot prove whether account-side subscription capacity or an
existing credit bucket paid for a call. Reports must retain `cost_usd=null` and
`cost_observability=unavailable`. Operators must inspect account billing
settings independently.

## Follow-up program: multi-plan support

**Priority:** P1 after v4 closeout
**Status:** Design not started; implementation not authorized.

Create a separate branch/worktree named like
`codex/cpe-v4-multi-plan-program` only when this program resumes. Do not reopen
or mix it with the merged v4 continuation. Use Superpowers brainstorming first,
then write a design spec and implementation plan. Stop before implementation
until the user explicitly requests it.

The design must preserve both document shapes:

- one spec plus one implementation plan;
- one spec plus multiple implementation plans, with an optional program/index
  plan.

Keep the existing single `--plan` CLI valid. Add repeatable `--plan` and an
optional `--program-plan` using explicit-first resolution. Do not require
Superpowers to generate a new manifest document.

Normalize documents, tasks, spec coverage, ownership, cross-plan dependencies,
and integration gates into one `PlanGraph`. The design must cover qualified
task IDs, per-document hashes, downstream invalidation, one run ID and ledger,
per-plan checkpoints, and one final cross-plan integration gate.

Also include these execution-policy improvements:

1. structural-invariant escalation after a task's third defect;
2. runtime automation of the four specialist integration-review lanes;
3. crash-point generation from the transition table;
4. centralized focused/task/full/merged-main verification ladder;
5. a one-page task-report schema with enforced size limits.

The requested canvas-clone fixture commit `6d41fb9` is not present in the
current Archive Git object database. Before design validation, locate the
authoritative repository/object and make its spec-plus-program/wave-plan shape
available through an explicit, reviewable fixture source. Do not invent a
replacement structure from memory.

## Execution order

1. Fix R1 with RED/GREEN coverage.
2. Obtain one fresh independent trust/privacy review and immutable checkpoint.
3. Execute R2's risk-first staged proof only under current credentialed-call
   authority.
4. Run the four R3 lanes and one consolidated fix wave.
5. Run the cost-free full gate on the resulting mainline checkpoint.
6. Publish v4 status only if its exact terminal generation passes.
7. Start the separate multi-plan brainstorming/spec/plan program.
8. Run R4 only on an explicit full-certification request.

## Verification ladder

Use one centralized order for every repair:

1. focused RED/GREEN test while editing;
2. task suite once before task review;
3. full CPE eval plus repository `bun run check` once before an immutable
   checkpoint;
4. the same cost-free full gate on merged `main`;
5. credentialed proof only after all applicable cost-free and review gates pass.

For documentation-only maintenance, run at least `check_docs_contract.py`,
link/path checks, Graphify refresh/freshness, and `git diff --check`.

## Non-goals

- Do not claim the merged deterministic v4 implementation is release-certified.
- Do not automatically spend the six-call staged ceiling.
- Do not run the 17-call matrix as routine closeout.
- Do not implement multi-plan support in the v4 closeout branch.
- Do not treat local predecessor attestation as cryptographic provenance.

## Related documents

- [Release process](release-process.md)
- [Risks, limitations, and deferrals](risks-limitations-deferrals.md)
- [Evals and verification](evals-and-verification.md)
- [Verification log](verification-log.md)
- [CPE v4 design](../../../docs/superpowers/specs/2026-07-12-cpe-v4-autonomous-efficient-executor-design.md)
- [CPE v4 implementation plan](../../../docs/superpowers/plans/2026-07-12-cpe-v4-autonomous-efficient-executor.md)
