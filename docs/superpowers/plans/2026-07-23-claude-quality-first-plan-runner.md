# Claude Quality-First Plan Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the independent `kws-claude-plan-runner` skill with the same public semantics as the Codex runner, Claude-native stream/session handling, and a repository-level parity gate that prevents provider contract drift.

**Architecture:** The Claude skill owns a separate copy of managed-runtime preflight, state, Git, evidence, helper, recovery, and engine code; it imports no Codex runtime. Its self-locating executable selects a preinstalled uv-managed normal-GIL CPython `>=3.13,<3.14` without downloads. Its provider adapter uses `claude -p --output-format stream-json`, captures the explicit session UUID from the init event, resumes healthy same-plan sessions, and falls back to a fresh session from durable Git/ledger/receipt state. A root test-only parity runner invokes both public CLIs with deterministic fake providers and compares only versioned semantic outcomes.

**Tech Stack:** uv-managed normal-GIL CPython 3.13 standard library, POSIX launchers, Git CLI, Claude Code stream-json CLI, Unix domain sockets, `unittest`, Bash eval entrypoint, root Python parity harness, Bun/TypeScript repository verification mapping.

## Global Constraints

- Execute after `docs/superpowers/plans/2026-07-23-codex-quality-first-plan-runner.md`.
- Design source: `docs/superpowers/specs/2026-07-23-quality-first-provider-plan-runners-design.md`.
- Create `skills/kws-claude-plan-runner/`; do not modify or delete legacy executors in this plan.
- Require uv-managed normal-GIL CPython `>=3.13,<3.14` and standard-library dependencies only; do not support system Python 3.9.
- Public invocation is `./scripts/runner`; it must self-locate and use `uv python find --managed-python --no-python-downloads --no-project --no-config --resolve-links 3.13`.
- Never install or download Python during `run`, `resume`, or `inspect`; preflight must fail before worktree/provider mutation with `runtime_missing` or `runtime_incompatible`.
- Record uv version, exact CPython patch, resolved path, architecture, and GIL mode separately from target verification-command environment identity.
- Do not import any production module from `skills/kws-codex-plan-runner/`.
- Do not create a shared production runtime or third skill.
- The root contract fixture and parity harness are test-only and must not be imported by either installed runtime.
- Preserve repeated `--spec` and `--plan` inputs, immutable source snapshots/digests, and CLI order.
- Supply all specs and exactly one current plan per implementation attempt; never supply future-plan snapshot paths.
- Use one branch `claude-plan/<run-id>` and one worktree for all plans.
- Use a fresh Claude session at every plan boundary; resume a healthy same-plan session by explicit ID.
- On stall, repeated failure, strategy fixation, context damage, session corruption, or failed resume, use a fresh session with durable checkpoint state and a changed technical strategy.
- Do not use `--bare`, `--safe-mode`, `--continue`, or an implicit recent-session selector.
- Keep `--permission-mode bypassPermissions` plus bounded deny rules as accidental-side-effect guards, not a security boundary.
- Strip Claude nesting markers and unrelated credentials while preserving required `ANTHROPIC_*` provider authentication.
- The runner never chooses model strength, price, escalation, subagents, roles, test scope, or performance thresholds.
- No total token, cost, or run-wall budget is allowed.
- Automatic child recovery occurs inside a live controller; `resumable` requires controller absence.
- Final verification and review use a fresh session and the exact final candidate HEAD.
- Keep deterministic evals network-free, credential-free, and model-free.
- Run focused tests during tasks; run each complete provider eval and `bun run agent:verify` once at the final candidate HEAD.

---

## File Structure

Create:

```text
skills/kws-claude-plan-runner/
├── AGENTS.md
├── CHANGELOG.md
├── README.md
├── SKILL.md
├── evals/
│   ├── fake_claude.py
│   ├── run.sh
│   ├── test_contracts.py
│   ├── test_engine.py
│   ├── test_evidence.py
│   ├── test_git_ops.py
│   ├── test_helper.py
│   ├── test_independence.py
│   ├── test_provider.py
│   ├── test_recovery.py
│   ├── test_runtime.py
│   └── test_storage.py
├── scripts/
│   ├── runner
│   ├── runner.py
│   └── plan_runner/
│       ├── __init__.py
│       ├── contracts.py
│       ├── engine.py
│       ├── evidence.py
│       ├── git_ops.py
│       ├── helper.py
│       ├── process.py
│       ├── provider.py
│       ├── recovery.py
│       ├── runtime.py
│       └── storage.py
└── templates/
    ├── final-verification-set.schema.json
    ├── finalization-result.schema.json
    └── plan-result.schema.json
```

Create root parity files:

```text
scripts/agent/check-plan-runner-parity
scripts/agent/check-plan-runner-parity.py
scripts/agent/fixtures/plan-runner-parity-v1.json
```

Modify:

```text
scripts/agent/contract.ts
scripts/agent/check-contract.test.ts
scripts/agent/verification-map.ts
scripts/agent/verification-map.test.ts
```

The Claude file responsibility boundaries are identical in name but independent
in code ownership. The only provider-specific production file is
`provider.py`; `engine.py` also supplies Claude state-home, worktree-home,
branch-prefix, permission metadata, and nested-session environment settings.

## Task 1: Independent Claude Runtime Foundation

**Files:**

- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/__init__.py`
- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/contracts.py`
- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/storage.py`
- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/git_ops.py`
- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/process.py`
- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/evidence.py`
- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/helper.py`
- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/recovery.py`
- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/runtime.py`
- Create: `skills/kws-claude-plan-runner/evals/test_contracts.py`
- Create: `skills/kws-claude-plan-runner/evals/test_storage.py`
- Create: `skills/kws-claude-plan-runner/evals/test_git_ops.py`
- Create: `skills/kws-claude-plan-runner/evals/test_evidence.py`
- Create: `skills/kws-claude-plan-runner/evals/test_helper.py`
- Create: `skills/kws-claude-plan-runner/evals/test_recovery.py`
- Create: `skills/kws-claude-plan-runner/evals/test_runtime.py`
- Create: `skills/kws-claude-plan-runner/evals/test_independence.py`
- Create: `skills/kws-claude-plan-runner/templates/final-verification-set.schema.json`

**Interfaces:**

- Consumes: semantic contract v1 and the validated public interfaces documented
  in Plan 1.
- Produces: a provider-private implementation of the same constants,
  `StateStore`, `RunLock`, `GitWorkspace`, `ExactCommand`, `EvidenceStore`,
  `HelperServer`, `ActivityLease`, `RecoveryPolicy`, `RuntimeIdentity`,
  `probe_runtime`, and `require_compatible_runtime` interfaces.

- [ ] **Step 1: Write the independence test before creating the runtime**

```python
# skills/kws-claude-plan-runner/evals/test_independence.py
import ast
import json
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1]
RUNTIME = SKILL_ROOT / "scripts" / "plan_runner"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


class IndependentRuntimeTest(unittest.TestCase):
    def test_runtime_imports_no_codex_runner_module(self):
        forbidden = {
            "kws-codex-plan-runner",
            "kws_codex_plan_runner",
            "codex_plan_runner",
        }
        for path in sorted(RUNTIME.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            joined = "\n".join(imports) + "\n" + source
            for marker in forbidden:
                self.assertNotIn(marker, joined, f"{path} depends on {marker}")

    def test_contract_fixture_is_not_a_runtime_import(self):
        for path in sorted(RUNTIME.glob("*.py")):
            self.assertNotIn(
                "plan-runner-contract-v1.json",
                path.read_text(encoding="utf-8"),
            )

    def test_runtime_vocabulary_matches_contract(self):
        from plan_runner.contracts import (  # noqa: E402
            CONTRACT_VERSION,
            FAILURE_TAXONOMY,
            FORMAT_VERSION,
            PLAN_STATUSES,
            RUNNER_RUNTIME_CONTRACT,
            RUN_STATUSES,
            TASK_STATUSES,
            ExitCode,
        )

        fixture = json.loads(
            (REPO_ROOT / "scripts/agent/fixtures/plan-runner-contract-v1.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(CONTRACT_VERSION, fixture["contract_version"])
        self.assertEqual(FORMAT_VERSION, fixture["state_format_version"])
        self.assertEqual(sorted(RUN_STATUSES), sorted(fixture["run_statuses"]))
        self.assertEqual(sorted(PLAN_STATUSES), sorted(fixture["plan_statuses"]))
        self.assertEqual(sorted(TASK_STATUSES), sorted(fixture["task_statuses"]))
        self.assertEqual(sorted(FAILURE_TAXONOMY), sorted(fixture["failure_taxonomy"]))
        self.assertEqual(RUNNER_RUNTIME_CONTRACT, fixture["runner_runtime"])
        self.assertEqual(
            {item.name.lower(): int(item) for item in ExitCode},
            fixture["exit_codes"],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the independence test and confirm the missing runtime failure**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-claude-plan-runner/evals/test_independence.py -v
```

Expected: FAIL when importing `plan_runner.contracts`.

- [ ] **Step 3: Add independent copies of the validated provider-neutral modules**

Using `apply_patch`, add provider-private copies of these Plan 1 files:

```text
skills/kws-codex-plan-runner/scripts/plan_runner/__init__.py
skills/kws-codex-plan-runner/scripts/plan_runner/contracts.py
skills/kws-codex-plan-runner/scripts/plan_runner/storage.py
skills/kws-codex-plan-runner/scripts/plan_runner/git_ops.py
skills/kws-codex-plan-runner/scripts/plan_runner/process.py
skills/kws-codex-plan-runner/scripts/plan_runner/evidence.py
skills/kws-codex-plan-runner/scripts/plan_runner/helper.py
skills/kws-codex-plan-runner/scripts/plan_runner/recovery.py
skills/kws-codex-plan-runner/scripts/plan_runner/runtime.py
skills/kws-codex-plan-runner/templates/final-verification-set.schema.json
```

The destination is the same relative path under
`skills/kws-claude-plan-runner/`. Make these exact provider-specific changes:

```python
provider = "claude"
branch = "claude-plan/" + run_id
provider_auth_prefixes = ("ANTHROPIC_",)
```

Do not retain a Codex state path, branch prefix, prompt, executable name,
sandbox option, or authentication prefix anywhere in the Claude runtime.

- [ ] **Step 4: Add provider-private copies of the focused neutral tests**

Using `apply_patch`, add Claude-path copies of Plan 1:

```text
evals/test_contracts.py
evals/test_storage.py
evals/test_git_ops.py
evals/test_evidence.py
evals/test_helper.py
evals/test_recovery.py
evals/test_runtime.py
```

Change expected provider identity to `claude`, branch prefix to
`claude-plan/`, and preserved authentication variables to `ANTHROPIC_*`.
Retain every crash, symlink, receipt, deadline, lease, recovery, managed
runtime, and runner-versus-target-environment identity assertion.

- [ ] **Step 5: Run the foundation tests**

Run:

```bash
PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
"$PYTHON_313" -m unittest \
  skills/kws-claude-plan-runner/evals/test_independence.py \
  skills/kws-claude-plan-runner/evals/test_contracts.py \
  skills/kws-claude-plan-runner/evals/test_runtime.py \
  skills/kws-claude-plan-runner/evals/test_storage.py \
  skills/kws-claude-plan-runner/evals/test_git_ops.py \
  skills/kws-claude-plan-runner/evals/test_evidence.py \
  skills/kws-claude-plan-runner/evals/test_helper.py \
  skills/kws-claude-plan-runner/evals/test_recovery.py -v
```

Expected: all copied contract and durability tests PASS.

- [ ] **Step 6: Commit the independent Claude foundation**

```bash
git add skills/kws-claude-plan-runner/scripts/plan_runner \
  skills/kws-claude-plan-runner/evals/test_independence.py \
  skills/kws-claude-plan-runner/evals/test_contracts.py \
  skills/kws-claude-plan-runner/evals/test_storage.py \
  skills/kws-claude-plan-runner/evals/test_git_ops.py \
  skills/kws-claude-plan-runner/evals/test_evidence.py \
  skills/kws-claude-plan-runner/evals/test_helper.py \
  skills/kws-claude-plan-runner/evals/test_recovery.py \
  skills/kws-claude-plan-runner/evals/test_runtime.py \
  skills/kws-claude-plan-runner/templates/final-verification-set.schema.json
git commit -m "feat(claude-runner): add independent durable foundation"
```

## Task 2: Claude Stream, Session, Permission, and Environment Adapter

**Files:**

- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/provider.py`
- Create: `skills/kws-claude-plan-runner/evals/fake_claude.py`
- Create: `skills/kws-claude-plan-runner/evals/test_provider.py`

**Interfaces:**

- Consumes: the same `ActivityLease`, exact process, environment, and helper
  descriptor contracts used by the Codex adapter.
- Produces:

Contractual API:

- immutable `ProviderRequest` fields: `worktree`, `prompt`, inline
  `output_schema`, optional `model`, explicit `session_id`, and `resume`;
- immutable `ProviderOutcome` fields: `kind`, `return_code`, explicit
  `session_id`, structured `result`, `provider_code`, bounded `usage`,
  distinct `activity_keys`, and scrubbed `stderr_tail`;
- `ClaudeAdapter.build_argv(request) -> list[str]`;
- `ClaudeAdapter.launch(request, lease) -> ProviderOutcome`.

- [ ] **Step 1: Write the fake Claude and adapter tests**

The fake emits:

```json
{"type":"system","subtype":"init","session_id":"00000000-0000-4000-8000-000000000001"}
{"type":"assistant","message":{"id":"message-1"}}
{"type":"result","subtype":"success","session_id":"00000000-0000-4000-8000-000000000001","structured_output":{}}
```

It must log argv, cwd, launch count, nesting-marker presence, sensitive
credential presence, and whether the launch used explicit resume.

Tests assert:

- initial argv is `claude -p <prompt>` plus `--output-format stream-json`,
  `--verbose`, inline JSON after `--json-schema`,
  `--permission-mode bypassPermissions`, one variadic `--disallowedTools`,
  `--session-id <explicit uuid>`, and optional `--model`;
- resume argv uses `--resume <explicit uuid>` and omits `--session-id`;
- argv never contains `--bare`, `--safe-mode`, `--continue`, or
  `--max-budget-usd`;
- the deny list includes `AskUserQuestion`, `EnterPlanMode`, `ExitPlanMode`,
  `Bash(git push*)`, `Bash(git merge*)`, `Bash(gh pr create*)`,
  `Bash(glab mr create*)`, `Bash(rm -rf /*)`, and
  `Bash(git reset --hard origin*)`;
- `--disallowedTools` appears exactly once;
- `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`, and
  `CLAUDE_CODE_ENTRYPOINT` are absent;
- `ANTHROPIC_*` is preserved while SSH/Git-host/unrelated cloud credentials are
  absent;
- init session ID is persisted before result handling;
- success without structured output fails closed;
- rate-limit and API error stream shapes classify as provider blockers;
- interrupted/resume-failed/context-damaged/session-missing scenarios are
  distinguishable;
- repeated message chunks or logs do not refresh the activity lease.

- [ ] **Step 2: Run the provider test and confirm missing module failure**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-claude-plan-runner/evals/test_provider.py -v
```

Expected: FAIL with missing `plan_runner.provider`.

- [ ] **Step 3: Implement exact initial argv**

Use one variadic deny flag:

```python
DENY_TOOLS = (
    "AskUserQuestion",
    "EnterPlanMode",
    "ExitPlanMode",
    "Bash(git push*)",
    "Bash(git merge*)",
    "Bash(gh pr create*)",
    "Bash(glab mr create*)",
    "Bash(rm -rf /*)",
    "Bash(git reset --hard origin*)",
)

argv = [
    "claude", "-p", request.prompt,
    "--output-format", "stream-json",
    "--verbose",
    "--json-schema", json.dumps(
        request.output_schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ),
    "--permission-mode", "bypassPermissions",
    "--disallowedTools", *DENY_TOOLS,
    "--session-id", request.session_id,
]
if request.model is not None:
    argv.extend(["--model", request.model])
```

- [ ] **Step 4: Implement explicit resume argv**

For `request.resume`:

```python
argv = [
    "claude", "-p", request.prompt,
    "--output-format", "stream-json",
    "--verbose",
    "--json-schema", inline_schema,
    "--permission-mode", "bypassPermissions",
    "--disallowedTools", *DENY_TOOLS,
    "--resume", request.session_id,
]
if request.model is not None:
    argv.extend(["--model", request.model])
```

Reject a non-UUID session ID. Do not combine `--resume` and `--session-id`.

- [ ] **Step 5: Implement bounded stream-json parsing**

Normalize:

- `system/init` → session capture and lifecycle advance;
- new assistant/tool-use message IDs → lifecycle/tool activity;
- `result` → structured result and informational usage;
- `rate_limit_event.rate_limit_info.status != "allowed"` → usage blocker;
- nonempty `result.api_error_status` → provider-unavailable blocker unless a
  more specific observed auth code exists.

Bound event lines, retained stderr, and result strings. Do not store the raw
stream as a second transcript.

- [ ] **Step 6: Run the provider tests**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-claude-plan-runner/evals/test_provider.py -v
```

Expected: all Claude adapter tests PASS.

- [ ] **Step 7: Recheck the installed Claude CLI contract without invoking a model**

Run:

```bash
claude --version
claude --help
```

Expected: version prints successfully; help contains `-p`, `--output-format`,
`stream-json`, `--verbose`, `--json-schema`, `--permission-mode`,
`bypassPermissions`, `--disallowedTools`, `--session-id`, and `--resume`.

- [ ] **Step 8: Commit the Claude adapter**

```bash
git add skills/kws-claude-plan-runner/scripts/plan_runner/provider.py \
  skills/kws-claude-plan-runner/evals/fake_claude.py \
  skills/kws-claude-plan-runner/evals/test_provider.py
git commit -m "feat(claude-runner): add stream session adapter"
```

## Task 3: Claude Sequential Engine and Public CLI

**Files:**

- Create: `skills/kws-claude-plan-runner/scripts/plan_runner/engine.py`
- Create: `skills/kws-claude-plan-runner/scripts/runner`
- Create: `skills/kws-claude-plan-runner/scripts/runner.py`
- Create: `skills/kws-claude-plan-runner/templates/plan-result.schema.json`
- Create: `skills/kws-claude-plan-runner/templates/finalization-result.schema.json`
- Create: `skills/kws-claude-plan-runner/evals/test_engine.py`

**Interfaces:**

- Consumes: every Claude foundation and provider interface.
- Produces: the same `RuntimePaths` and `PlanRunner` public signatures as the
  Codex runtime, with no public `--sandbox` option.

- [ ] **Step 1: Write the Claude engine tests**

Port the complete Plan 1 engine scenario matrix and add Claude-specific checks:

- state defaults to `~/.claude/plan-runner/<run-id>/`;
- worktree defaults to `~/.claude/worktrees/plan-runner/<run-id>`;
- branch is `claude-plan/<run-id>`;
- immutable config records `permission_mode=bypassPermissions` and deny-list
  digest;
- managed-runtime identity is recorded before worktree/provider mutation and
  remains separate from target verification-command environment identity;
- missing uv/interpreter and incompatible/free-threaded Python block without a
  worktree, provider launch, or download;
- invoking the absolute launcher from an unrelated current directory still
  locates `runner.py`;
- each new plan gets a new generated session UUID;
- healthy same-plan interruption uses `--resume`;
- missing session, explicit resume failure, session corruption, stall,
  repeated failure, context overflow, or abnormal compaction creates a fresh
  UUID and durable changed-strategy packet;
- a fresh fallback never replays an implemented plan;
- the next plan receives Git, ledger, and receipt facts but no prior Claude
  conversation;
- finalization uses a new Claude session and the same candidate-HEAD evidence
  rules as Codex;
- the public CLI has no timeout budget, token budget, model-routing, or sandbox
  selection;
- result states, task states, exit codes, final handoff, and integrity failures
  match contract v1.

- [ ] **Step 2: Run the engine test and confirm the missing engine failure**

Run:

```bash
"$(uv python find --managed-python --no-python-downloads --no-project \
  --no-config --resolve-links 3.13)" -m unittest \
  skills/kws-claude-plan-runner/evals/test_engine.py -v
```

Expected: FAIL with missing `plan_runner.engine`.

- [ ] **Step 3: Add schemas matching semantic contract v1**

Use the same bounded plan/finalization schema shapes as Plan 1. Provider-private
stream envelopes are not part of the schema. Assert the schema files are
byte-for-byte equal between providers in `test_independence.py`; semantic
schema changes must therefore be deliberate in both skills.

- [ ] **Step 4: Implement the Claude engine from the fixed provider-neutral interface**

Using `apply_patch`, add an independent copy of the validated Plan 1 engine and
CLI logic, then make only these provider changes:

```python
provider_name = "claude"
state_home = Path.home() / ".claude" / "plan-runner"
worktree_home = Path.home() / ".claude" / "worktrees" / "plan-runner"
branch_prefix = "claude-plan/"
immutable_provider_config = {
    "permission_mode": "bypassPermissions",
    "deny_tools_digest": sha256_json(list(DENY_TOOLS)),
}
```

Remove the Codex `--sandbox` argument and Git-common-directory
`--add-dir` launch field. Retain every common state transition, multi-plan
packet rule, helper flow, automatic recovery rule, finalization rule, and
completion gate.

- [ ] **Step 5: Implement Claude environment setup**

Before provider launch:

```python
child_env = sanitized_child_env(
    os.environ,
    provider_auth_prefixes=("ANTHROPIC_",),
    remotes=git_workspace.remotes(),
    run_id=run_id,
)
for key in (
    "CLAUDECODE",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_ENTRYPOINT",
):
    child_env.pop(key, None)
```

Do not preserve arbitrary `CLAUDE_*` secrets merely because of their prefix.

- [ ] **Step 6: Implement public and hidden CLI commands**

Public:

```bash
./scripts/runner run --spec ABS [--spec ABS ...] \
  --plan ABS [--plan ABS ...] --workspace ABS \
  [--stall-seconds 3600] [--model MODEL]
./scripts/runner resume --run-id RUN_ID
./scripts/runner resume --run-id RUN_ID --retry-blocked
./scripts/runner resume --run-id RUN_ID \
  --retry-failed --strategy-note TEXT
./scripts/runner inspect --run-id RUN_ID
```

Hidden `_helper` behavior and request schema must match the Codex runner exactly.

Create `scripts/runner` with the same exact self-locating POSIX launcher body
specified in Plan 1. Its `uv python find` argv must include
`--managed-python --no-python-downloads --no-project --no-config
--resolve-links 3.13`. The hidden helper client uses `sys.executable` plus the
absolute internal `runner.py`, not uv lookup. Run runtime preflight before any
input snapshot, worktree, or provider mutation.

- [ ] **Step 7: Run all focused Claude-runner tests**

Run:

```bash
PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
"$PYTHON_313" -m unittest \
  skills/kws-claude-plan-runner/evals/test_independence.py \
  skills/kws-claude-plan-runner/evals/test_contracts.py \
  skills/kws-claude-plan-runner/evals/test_runtime.py \
  skills/kws-claude-plan-runner/evals/test_storage.py \
  skills/kws-claude-plan-runner/evals/test_git_ops.py \
  skills/kws-claude-plan-runner/evals/test_evidence.py \
  skills/kws-claude-plan-runner/evals/test_helper.py \
  skills/kws-claude-plan-runner/evals/test_recovery.py \
  skills/kws-claude-plan-runner/evals/test_provider.py \
  skills/kws-claude-plan-runner/evals/test_engine.py -v
```

Expected: all tests PASS without network or model calls.

- [ ] **Step 8: Commit the Claude engine**

```bash
chmod +x skills/kws-claude-plan-runner/scripts/runner
git add skills/kws-claude-plan-runner/scripts/plan_runner/engine.py \
  skills/kws-claude-plan-runner/scripts/runner \
  skills/kws-claude-plan-runner/scripts/runner.py \
  skills/kws-claude-plan-runner/templates/plan-result.schema.json \
  skills/kws-claude-plan-runner/templates/finalization-result.schema.json \
  skills/kws-claude-plan-runner/evals/test_engine.py
git commit -m "feat(claude-runner): execute sequential plans to verified handoff"
```

## Task 4: Root Semantic Parity Harness

**Files:**

- Create: `scripts/agent/check-plan-runner-parity`
- Create: `scripts/agent/check-plan-runner-parity.py`
- Create: `scripts/agent/fixtures/plan-runner-parity-v1.json`
- Modify: `skills/kws-codex-plan-runner/evals/fake_codex.py`
- Modify: `skills/kws-claude-plan-runner/evals/fake_claude.py`

**Interfaces:**

- Consumes: both public `scripts/runner` CLIs and the versioned contract
  fixture.
- Produces: `./scripts/agent/check-plan-runner-parity`, returning zero
  only when normalized public outcomes match.

- [ ] **Step 1: Write the parity scenario fixture**

```json
{
  "fixture_version": 1,
  "scenarios": [
    {
      "id": "ordered-two-plan-ready",
      "fake_sequence": ["implemented", "implemented", "finalized"],
      "expected_status": "ready_for_integration",
      "expected_plan_statuses": ["implemented", "implemented"],
      "expected_exit": 0
    },
    {
      "id": "authority-blocked",
      "fake_sequence": ["blocked"],
      "expected_status": "blocked",
      "expected_plan_statuses": ["running", "pending"],
      "expected_exit": 3
    },
    {
      "id": "healthy-resume",
      "fake_sequence": ["interrupted", "implemented", "implemented", "finalized"],
      "expected_status": "ready_for_integration",
      "expected_session_action": "resume",
      "expected_exit": 0
    },
    {
      "id": "stalled-fresh-strategy",
      "fake_sequence": ["stalled", "implemented", "implemented", "finalized"],
      "expected_status": "ready_for_integration",
      "expected_session_action": "fresh",
      "expected_exit": 0
    },
    {
      "id": "recovery-exhausted",
      "fake_sequence": ["same-failure", "same-failure", "same-failure", "same-failure"],
      "expected_status": "failed",
      "expected_failure": "recovery_exhausted",
      "expected_exit": 4
    }
  ]
}
```

- [ ] **Step 2: Write the parity harness and run it red**

The harness must:

1. validate both runtime vocabularies against
   `plan-runner-contract-v1.json`;
2. create a separate disposable `HOME`, Git source, state, and worktree per
   provider/scenario;
3. install fake `codex` and `claude` shims in a temporary `PATH`;
4. create two spec files and two plan files in deliberately different name
   orders;
5. invoke each public CLI with repeated `--spec` and `--plan`;
6. call `inspect` afterward;
7. normalize only contract fields: exit, top status, plan statuses, task
   statuses, failure taxonomy, verification receipt identity fields,
   candidate-HEAD equality, review outcome, session action, and integration;
8. compare provider results and the fixture expectation;
9. print bounded scenario-specific diffs without raw provider streams.

The executable `scripts/agent/check-plan-runner-parity` must self-locate the
repository, resolve the same preinstalled CPython with the exact no-download
`uv python find` argv, and execute the absolute `.py` path. It must never call
`uv run` or install Python.

Run:

```bash
./scripts/agent/check-plan-runner-parity
```

Expected before fake updates: FAIL because the fakes do not consume the common
scenario sequence.

- [ ] **Step 3: Make both fakes consume one provider-neutral scenario protocol**

Both fakes read:

```text
PLAN_RUNNER_FAKE_SEQUENCE=<absolute JSON file>
PLAN_RUNNER_FAKE_LOG=<absolute JSONL file>
```

Each launch atomically consumes the next sequence item under a file lock. Both
must implement the same semantic actions while retaining provider-native stream
shapes. For finalization, the fake reads the helper descriptor from the prompt,
declares a final command set, invokes every command through `_helper`, and
returns a structured review at the resulting candidate HEAD.

- [ ] **Step 4: Run the parity harness**

Run:

```bash
./scripts/agent/check-plan-runner-parity
```

Expected: every scenario prints `PASS`; final line is
`plan runner parity: PASS`.

- [ ] **Step 5: Commit parity coverage**

```bash
chmod +x scripts/agent/check-plan-runner-parity
git add scripts/agent/check-plan-runner-parity \
  scripts/agent/check-plan-runner-parity.py \
  scripts/agent/fixtures/plan-runner-parity-v1.json \
  skills/kws-codex-plan-runner/evals/fake_codex.py \
  skills/kws-claude-plan-runner/evals/fake_claude.py
git commit -m "test: enforce provider plan runner parity"
```

## Task 5: Claude Skill Contract and Repository Verification Routing

**Files:**

- Create: `skills/kws-claude-plan-runner/AGENTS.md`
- Create: `skills/kws-claude-plan-runner/CHANGELOG.md`
- Create: `skills/kws-claude-plan-runner/README.md`
- Create: `skills/kws-claude-plan-runner/SKILL.md`
- Create: `skills/kws-claude-plan-runner/evals/run.sh`
- Modify: `scripts/agent/contract.ts`
- Modify: `scripts/agent/check-contract.test.ts`
- Modify: `scripts/agent/verification-map.ts`
- Modify: `scripts/agent/verification-map.test.ts`

**Interfaces:**

- Consumes: Claude public CLI, Claude evals, root parity command.
- Produces: discoverable version `1.0.0`, deterministic provider eval, and
  parity-aware verification scopes for both new runners.

- [ ] **Step 1: Write failing repository mapping tests**

Assert:

- the Claude runner AGENTS/eval files are required;
- path `skills/kws-claude-plan-runner/scripts/runner` selects scope
  `claude-plan-runner`;
- both `codex-plan-runner` and `claude-plan-runner` scopes include
  `plan-runner-parity`;
- `full-offline` includes both new provider evals and parity;
- legacy scopes remain present until the cutover plan.

Define:

```typescript
const claudePlanRunnerEval = command(
  "claude-plan-runner-eval",
  ["./evals/run.sh"],
  "skills/kws-claude-plan-runner",
);
const planRunnerParity = command(
  "plan-runner-parity",
  ["./scripts/agent/check-plan-runner-parity"],
);
```

- [ ] **Step 2: Run focused repository tests and confirm failure**

Run:

```bash
bun test scripts/agent/check-contract.test.ts scripts/agent/verification-map.test.ts
```

Expected: FAIL because Claude runner and parity are not mapped.

- [ ] **Step 3: Add Claude/parity contract roots and scopes**

Extend `ScopeId` with `"claude-plan-runner"`. Add the Claude eval and parity
commands. Append parity to both new runner scopes and to `OFFLINE_COMMANDS`.
Do not remove the legacy CPE, CLPE, or CME references in this task.

- [ ] **Step 4: Write Claude skill documentation**

`SKILL.md` frontmatter:

```yaml
---
name: kws-claude-plan-runner
description: Use when approved Superpowers specifications and one or more ordered implementation plans must run autonomously through Claude Code with durable recovery and fail-closed ready-for-integration evidence.
metadata:
  version: "1.0.0"
  updated_at: "2026-07-23"
---
```

Document the exact common CLI plus:

- stream-json and inline JSON schema;
- uv-managed normal-GIL CPython `>=3.13,<3.14`, self-locating public launcher,
  and no download or system-Python fallback during active commands;
- explicit new UUID versus `--resume`;
- healthy resume and durable fresh fallback;
- nested-session environment scrub;
- one variadic deny flag and its non-security status;
- multiple specs/common context and current-plan-only execution;
- automatic `recovering`;
- helper-owned command deadlines and receipts;
- candidate-HEAD fresh finalization;
- `implemented` versus `ready_for_integration`;
- no legacy state support;
- deterministic versus live validation.

`AGENTS.md` requires the managed-runtime contract, standard-library-only
production code, and a real `claude --help`/stream recheck whenever flags or
event parsing change. `CHANGELOG.md` records 1.0.0.

- [ ] **Step 5: Add the Claude deterministic eval entrypoint**

```bash
#!/usr/bin/env bash
set -euo pipefail

PYTHON_313="$(uv python find --managed-python --no-python-downloads \
  --no-project --no-config --resolve-links 3.13)"
"$PYTHON_313" -m unittest discover -s evals -p 'test_*.py' -v
"$PYTHON_313" -m py_compile scripts/runner.py scripts/plan_runner/*.py evals/*.py
bash -n evals/run.sh
bash -n scripts/runner
```

Mark `evals/run.sh`, `evals/fake_claude.py`, and `scripts/runner` executable.

- [ ] **Step 6: Run focused repository tests**

Run:

```bash
bun test scripts/agent/check-contract.test.ts scripts/agent/verification-map.test.ts
```

Expected: PASS.

- [ ] **Step 7: Run provider and parity gates**

Run:

```bash
cd skills/kws-codex-plan-runner && ./evals/run.sh
cd /Users/kws/source/private/Archive/skills/kws-claude-plan-runner && ./evals/run.sh
cd /Users/kws/source/private/Archive && \
  ./scripts/agent/check-plan-runner-parity
```

Expected: Codex PASS, Claude PASS, parity PASS.

- [ ] **Step 8: Run repository verification once at the candidate HEAD**

Run:

```bash
bun run agent:verify
```

Expected: agent contract PASS, both new provider evals PASS, parity PASS, no
live model evidence claimed.

- [ ] **Step 9: Review the complete Plan 2 diff**

Review against `code_review.md` and verify:

- no production cross-provider imports;
- no shared production runtime;
- no `--bare`, `--safe-mode`, `--continue`, or budget flag;
- no repeated `--disallowedTools` flag;
- no nesting markers or unrelated credentials in child env;
- no implicit session selection;
- no future-plan paths;
- parity compares semantics rather than provider-private fields;
- legacy sources, state, symlinks, and processes remain untouched.

Expected: no unresolved Critical or Important findings.

- [ ] **Step 10: Commit the Claude release and parity routing**

```bash
git add skills/kws-claude-plan-runner \
  scripts/agent/contract.ts \
  scripts/agent/check-contract.test.ts \
  scripts/agent/verification-map.ts \
  scripts/agent/verification-map.test.ts
git commit -m "feat: add Claude quality-first plan runner"
```

## Plan 2 Completion Evidence

Before starting cutover work:

```bash
git status --short
git log -1 --oneline
cd skills/kws-codex-plan-runner && ./evals/run.sh
cd /Users/kws/source/private/Archive/skills/kws-claude-plan-runner && ./evals/run.sh
cd /Users/kws/source/private/Archive && \
  ./scripts/agent/check-plan-runner-parity
bun run agent:verify
```

Required result:

- clean feature worktree;
- both provider deterministic gates PASS;
- parity PASS;
- repository gate PASS;
- no real provider canary claimed yet;
- every legacy source, installed symlink, runtime state, and live process remains
  unchanged.
