---
name: kws-claude-plan-executor
description: Use when an approved Superpowers implementation plan must run autonomously in an isolated worktree via a headless child Claude session, with fail-closed completion verification and session-delegated resume.
metadata:
  version: "1.0.0"
  updated_at: "2026-07-22"
---

# KWS Claude Plan Executor (CLPE)

CLPE is a thin local harness for approved Superpowers implementation plans.
CLPE maintains one execution environment and verifies submitted facts. The
child Claude session's Superpowers decides what work, verification, and
parallelism are correct — including whether to dispatch its own subagents.
CLPE never compiles a plan, selects a task, computes review tiers, or judges
quality. It supersedes the v3 multi-agent orchestrator, which for now remains
at `skills/kws-claude-multi-agent-executor/` (its archival to `archive/`, along
with migrating the `scripts/agent` verification tooling that references it, is a
pending follow-up).

## Commands

```bash
python3 scripts/clpe.py run \
  --spec /abs/spec.md --plan /abs/plan.md \
  --workspace /abs/repository \
  [--model MODEL] [--timeout-seconds 1200..7200]
python3 scripts/clpe.py resume --run-id RUN_ID [--timeout-seconds N]
python3 scripts/clpe.py inspect --run-id RUN_ID
```

`--spec` is repeatable (pass it once per spec file). Exit codes: `completed`
0, `failed` 1, `blocked` 2, `resumable` 3. State lives under
`~/.claude/clpe/<run-id>/` (override the prefix with `CLPE_HOME`); the
worktree is `~/.claude/worktrees/<run-id>/`, on branch `clpe/<run-id>`.
No working-tree files are written inside the source repository — the only
additions to it are the `clpe/<run-id>` branch ref and worktree registration
in its `.git`. The worktree is never auto-deleted.

## Launch contract

`run` requires a clean git workspace and readable UTF-8 inputs. It snapshots
the plan and specs, creates one worktree + branch `clpe/<run-id>`, scrubs
`CLAUDECODE` / `CLAUDE_CODE_CHILD_SESSION` / `CLAUDE_CODE_ENTRYPOINT` and
secret-suffixed env vars (keeping `ANTHROPIC_*`), and launches:

`claude -p <facts+delegation prompt> --output-format stream-json --verbose
--json-schema <INLINE JSON Schema content> --permission-mode
bypassPermissions --disallowedTools <the 4 deny rules as one variadic flag:
git push, git merge, rm -rf /, git reset --hard origin>`

Two load-bearing points:

- `--json-schema` carries the schema's **inline JSON content**, not a file
  path. CLPE reads `templates/plan-result.schema.json` and passes its text as
  the argument; the CLI parses the argument itself as JSON.
- `stream-json` (not `json`) is load-bearing: the first init event yields the
  session id early, so a timed-out run remains resumable.

There is no `--bare`; the child auto-loads Superpowers. CLPE imposes the
wall-clock timeout itself (SIGTERM the process group, then SIGKILL).

The prompt prohibitions (no merge/push/deploy/outside-worktree writes) are a
guard, not a sandbox substitute. Accepted residual risk: under
bypassPermissions, writes outside the worktree are not fully observable or
reversible; the deny rules and the git gates below are the remaining controls.

Billing (measured 2026-07-22, claude v2.1.206): headless `claude -p` bills the
subscription (OAuth) on this machine — the init event reports
apiKeySource="none" and a five-hour subscription rate-limit window. The
envelope's total_cost_usd is an API-equivalent display, not a metered credit
charge.

## Fail-closed completion

A run is `completed` only if ALL hold: envelope subtype is `success` AND
`structured_output` is present; the child reports `status=completed`; the
worktree is clean; the reported `head_commit` matches `git rev-parse HEAD`;
`merge-base --is-ancestor <starting_commit> HEAD` passes; `open_findings` is
empty. `handoff.json` records branch/head facts and `integration=not_observed`
— it never claims merge, push, deploy, or product acceptance.

The child's result envelope carries `structured_output` as a top-level field
on the result event (verified 2026-07-22). CLPE reads that field and
fail-closed-validates its shape; a `success` envelope without a valid
`structured_output` is treated as an invalid result, never `completed`.

A harness wall-clock timeout — and any incomplete-but-recoverable outcome that
captured a session id — is `resumable` (exit 3), not a failure. Provider
conditions become operator-owned `blocked` facts (see below).

## Known limitation: provider-block classification

Only the SUCCESS stream shapes are verified against claude v2.1.206. Provider
blocks are detected defensively from a rate_limit_event whose
rate_limit_info.status != "allowed" and from a non-null result
api_error_status; the exact rejected/error shapes are INFERRED and not verified
against a real rate-limit or auth failure. A real provider block is classified
"blocked" (exit 2) defensively, but the usage-vs-auth distinction may be
imprecise (both map to provider_unavailable via the api_error path).

Not-yet-observed: which project `.claude/` settings load in the reused worktree
cwd is not yet observed on a first real run; CLPE plants no settings in the
worktree, so this does not affect behavior.

## Resume

Resume is delegated to Claude Code's session store: CLPE re-invokes
`claude -p --resume <session_id>` with the same schema and verification.
Resume never relaxes the completion gates. A run without a captured session
id cannot resume — start a new run. Launches are bounded (max 5 per run).

## Verify

For any behavior change, add a focused deterministic eval first, then run the
complete local gate at the final clean revision:

```bash
./evals/run.sh
python3 -m py_compile scripts/clpe.py evals/*.py
```

Evals are sequential, network-free, credential-free, and model-free
(`fake_claude.py` stands in for the CLI).
