# CPE v3 Quality And Model Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship CPE `3.0.0` as an independent, event-sourced Codex plan executor with fixed Sol/high core execution, fixed Terra/high read-only scouting, deterministic validation/reconciliation/repair/inspection, and no v2 runtime compatibility or unused model configuration.

**Architecture:** Keep the public skill and Python CLI surfaces, but replace the mutable v2 state internals with `scripts/cpe_runtime/`: immutable manifest, content-addressed evidence, hash-chained events, a pure projector, and one transition kernel. All write-capable work is sequential; only bounded read-only scouts may run concurrently. Public validator, reconciliation, repair, resume, prompt/handoff, and inspection entry points remain, but they consume the v3 kernel instead of v2 state helpers.

**Tech Stack:** Python 3.11+, standard library, PyYAML 6.0.3 for YAML fixtures, Bash eval harness, Git worktrees, Codex CLI JSONL, JSON/JSONL filesystem artifacts, Graphify.

## Global Constraints

- Source design: `docs/superpowers/specs/2026-07-10-cpe-v3-quality-model-routing-design.md`.
- Target release is exactly `3.0.0`; this is a major, intentionally incompatible runtime release.
- CPE remains independent from Waygent. Do not import, invoke, or route through Waygent runtime packages.
- V2 state is never interpreted, resumed, repaired, migrated, or rewritten. Read only `schema_version` and report `unsupported_schema`.
- The only active routes are core `gpt-5.6-sol/high` and scout `gpt-5.6-terra/high`.
- Do not accept model, reasoning, profile, alias, implementer-model, or fallback overrides.
- Do not write `~/.codex/config.toml` or a target repository `.codex/config.toml`; enforce models with per-process Codex CLI flags.
- Core coordination, implementation, review, verification judgment, recovery, repair, analysis, and completion always use Sol/high.
- Terra/high is allowed only for read-only scout attempts with no write claim and no implementation, review, verification, or completion verdict.
- Write-capable tasks execute sequentially. Independent read-only scouts may use bounded concurrency.
- Prompts do not contain model-routing prose. Launchers carry the fixed model and reasoning flags.
- Missing or conflicting model attestation blocks completion. There is no silent downgrade.
- `events.jsonl` is authoritative; `state.json` is a rebuildable projection.
- Models never edit manifest, events, evidence indexes, or state directly. Only the CPE transition kernel writes durable run state.
- Every task with a supplied spec has explicit `spec_refs`; full-spec fallback is removed.
- Preserve worktree isolation under `~/.codex/worktrees/<run_id>` and run artifacts under `~/.codex/orchestrator/<run_id>`.
- Preserve validator, reconciliation, repair, resume, recent-run inspection, prompt, and handoff capabilities.
- Use TDD for every behavior change and keep the package passing after every task commit.
- Run implementation tasks sequentially because the shared runtime package and eval harness overlap heavily. Parallel work is limited to read-only investigation.

---

## File Structure Map

| Path | Responsibility |
| --- | --- |
| `skills/kws-codex-plan-executor/scripts/cpe.py` | Public `run`, `resume`, and `export` command router |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/model_policy.py` | The only two routes, launcher construction, attestation |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/manifest.py` | Immutable v3 run manifest creation and loading |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py` | Content-addressed immutable evidence writes and verification |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/events.py` | Canonical event hashing, JSONL append, chain verification |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/projector.py` | Pure manifest + events to state projection |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py` | Valid transitions, event append, atomic snapshot replacement |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py` | Sequential write scheduling and bounded read-only scouting |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/worker.py` | Codex CLI execution, JSONL parsing, retries, usage evidence |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/validation.py` | One v3 validator used by completion, reconciliation, repair, and inspection |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py` | Manifest/event/snapshot/artifact/git drift detection |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/repair.py` | Dry-run repair plans and explicit safe compensating events |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/inspection.py` | Read-only current/recent run projections and metrics |
| `skills/kws-codex-plan-executor/scripts/cpe_runtime/prompt_export.py` | One fenced, paste-ready launcher plus prompt bundle |
| `skills/kws-codex-plan-executor/data/pricing-snapshot.json` | Versioned two-model standard-pricing evidence |
| `skills/kws-codex-plan-executor/requirements-eval.txt` | Reproducible eval-only dependency pin |

## Replacement And Removal Map

| Current surface | V3 treatment |
| --- | --- |
| `scripts/validate_state.py` | Retain CLI; replace internals with `cpe_runtime.validation` |
| `scripts/reconcile_state.py` | Retain CLI; replace direct state edits with v3 reconciliation and kernel repair |
| `scripts/repair_runs.py` | Retain dry-run/apply CLI; use v3 repair plans and leave v2 untouched |
| `scripts/inspect_runs.py`, `scripts/analyze_recent_runs.py` | Retain CLI; derive all results from v3 projection and immutable evidence |
| `scripts/normalize_cpe_run.py` | Retain name; rewrite as a stable v3 inspection serializer |
| `scripts/cpe_state_validation/` | Remove after the v3 validator passes all consumer tests |
| `scripts/run_quality_debt.py` | Remove; derived inspection owns quality classification |
| `scripts/append_trajectory_event.py` | Remove; v3 event store owns trajectory |
| `scripts/update_progress_ledger.py` | Remove; state projector owns progress |
| `scripts/update_decisions_register.py` | Remove; decision evidence is immutable and projected |
| `scripts/record_cache_observation.py` | Remove; worker usage evidence is attached through the kernel |
| `scripts/classify_recovery.py` | Remove after recovery classification moves into `cpe_runtime.repair` |
| `templates/spark-scout-bullets.ko.txt` | Delete |
| `evals/fixtures/02-no-spark.yaml` | Delete; no Spark/no-Spark behavior exists in v3 |
| `evals/baselines/v2*.json*` | Delete after `v3.0.0.json` is reviewed and tracked |
| Historical `HISTORY.md`, committed designs, `docs/experiments/` | Retain as history, never load as runtime configuration |

## Execution Order

- Required order: T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11 → T12.
- T6 is logically independent after T1, but still execute it sequentially to avoid overlapping harness edits.
- Do not begin T7 until model policy, manifest/evidence, event kernel, task packets, and Superpowers compatibility all pass.
- Do not remove v2 helpers until the replacement public CLI and consumer-parity checks pass.
- Human approval gate: before the non-dry-run live migration matrix in T11, show the exact treatment/case count and enforce the `$50.00` hard cap. Never start the paid run without explicit approval in that execution session.
- T1 creates `skills/kws-codex-plan-executor/.venv` explicitly for development verification. At the start of T2-T12, run `export PATH="$PWD/.venv/bin:$PATH"` from the skill directory. Runtime preflight only diagnoses dependencies and never installs them.

---

### Task 1: Make Eval Dependencies And Failures Reproducible

```yaml
id: T1
title: Reproducible dependency and eval runner
owner_boundary: Eval environment and command reporting only
files:
  - path: skills/kws-codex-plan-executor/requirements-eval.txt
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/preflight_dependencies.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/run_check.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/check_runtime_dependencies.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/check_eval_harness.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/run.sh
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_runtime_dependencies.py
    expected: passed=true, including a simulated missing-PyYAML diagnostic
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_eval_harness.py
    expected: passed=true and first failing command output is visible
risks:
  - The harness currently imports yaml before it can explain that PyYAML is absent.
```

**Interfaces:**

- Produces `preflight_dependencies.check_requirements() -> dict[str, object]`.
- Produces a `run_check.py` CLI that accepts report path, check name, and command arguments for all deterministic checks.
- Later tasks may add checks to `run.sh`; they must use this runner rather than redirecting output to `/dev/null`.

- [ ] **Step 1: Add a failing dependency contract check**

Create `evals/check_runtime_dependencies.py` with direct checks for the real pin and a simulated missing import:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from preflight_dependencies import Requirement, check_requirement


def main() -> int:
    actual = check_requirement(Requirement("PyYAML", "yaml", "6.0.3"))
    missing = check_requirement(
        Requirement("AbsentFixture", "absent_fixture_module", "1.0.0"),
        finder=lambda _: None,
        version_getter=lambda _: "1.0.0",
    )
    checks = {
        "pyyaml_pin_is_available": actual["passed"] is True,
        "missing_import_is_actionable": (
            missing["passed"] is False
            and missing["reason"] == "missing_import"
            and "python3 -m pip install -r requirements-eval.txt" in missing["preparation_command"]
        ),
    }
    payload = {"passed": all(checks.values()), "checks": checks}
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the check and confirm RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_runtime_dependencies.py`

Expected: FAIL with `ModuleNotFoundError: preflight_dependencies`.

- [ ] **Step 3: Add the dependency pin and preflight implementation**

Create `requirements-eval.txt`:

```text
PyYAML==6.0.3
```

Create and activate the ignored development environment explicitly:

```bash
cd skills/kws-codex-plan-executor
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-eval.txt
export PATH="$PWD/.venv/bin:$PATH"
```

Create `scripts/preflight_dependencies.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Requirement:
    distribution: str
    module: str
    version: str


REQUIREMENTS = (Requirement("PyYAML", "yaml", "6.0.3"),)
PREPARATION_COMMAND = "python3 -m pip install -r requirements-eval.txt"


def check_requirement(
    requirement: Requirement,
    *,
    finder: Callable[[str], object | None] = importlib.util.find_spec,
    version_getter: Callable[[str], str] = importlib.metadata.version,
) -> dict[str, object]:
    if finder(requirement.module) is None:
        return {
            "passed": False,
            "distribution": requirement.distribution,
            "required_version": requirement.version,
            "reason": "missing_import",
            "preparation_command": PREPARATION_COMMAND,
        }
    actual = version_getter(requirement.distribution)
    return {
        "passed": actual == requirement.version,
        "distribution": requirement.distribution,
        "required_version": requirement.version,
        "actual_version": actual,
        "reason": "ok" if actual == requirement.version else "version_mismatch",
        "preparation_command": PREPARATION_COMMAND,
    }


def check_requirements() -> dict[str, object]:
    results = [check_requirement(item) for item in REQUIREMENTS]
    return {"passed": all(item["passed"] for item in results), "requirements": results}


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    payload = check_requirements()
    print(json.dumps(payload, indent=2))
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add a structured per-command harness wrapper**

Create `evals/run_check.py` that records name, argv, duration, status, return code, and bounded failure output:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("command is required after --")
    started = time.monotonic()
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = (result.stdout + result.stderr).strip()
    row = {
        "name": args.name,
        "argv": command,
        "duration_seconds": round(time.monotonic() - started, 3),
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "failure_output": "" if result.returncode == 0 else output[-8000:],
    }
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False))
    if result.returncode:
        print(output)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
```

Modify `evals/run.sh` so dependency preflight is the first Python command, `eval-report.jsonl` is truncated once, and every deterministic checker is executed through `run_check.py`. Remove all checker-level `>/dev/null` redirections.

- [ ] **Step 5: Extend harness self-tests and verify GREEN**

Extend `evals/check_eval_harness.py` to assert that `run.sh` invokes `preflight_dependencies.py` before fixture YAML is read, calls `run_check.py`, writes `eval-report.jsonl`, and contains no checker invocation redirected to `/dev/null`.

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_runtime_dependencies.py
python3 evals/check_eval_harness.py
bash -n evals/run.sh
```

Expected: all commands exit `0` and both JSON payloads contain `"passed": true`.

- [ ] **Step 6: Commit T1**

```bash
git add skills/kws-codex-plan-executor/requirements-eval.txt \
  skills/kws-codex-plan-executor/scripts/preflight_dependencies.py \
  skills/kws-codex-plan-executor/evals/run_check.py \
  skills/kws-codex-plan-executor/evals/check_runtime_dependencies.py \
  skills/kws-codex-plan-executor/evals/check_eval_harness.py \
  skills/kws-codex-plan-executor/evals/run.sh
git commit -m "test(cpe): make eval failures reproducible"
```

---

### Task 2: Enforce The Fixed Two-Route Model Contract

```yaml
id: T2
title: Fixed model policy, launcher, prompt export, and invocation rejection
owner_boundary: Model routing and exported launcher only
files:
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/__init__.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/model_policy.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/prompt_export.py
    mode: owned
  - path: skills/kws-codex-plan-executor/data/pricing-snapshot.json
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/parse_invocation_args.py
    mode: edit
  - path: skills/kws-codex-plan-executor/templates/fresh-session-prompt.txt
    mode: edit
  - path: skills/kws-codex-plan-executor/templates/spark-scout-bullets.ko.txt
    mode: delete
  - path: skills/kws-codex-plan-executor/evals/fixtures/01-prompt-only.yaml
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/fixtures/02-no-spark.yaml
    mode: delete
  - path: skills/kws-codex-plan-executor/evals/fixtures/03-continuation.yaml
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/static_prompt_runner.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_prompt.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_invocation_args.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_model_policy.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/check_model_surface.py
    mode: owned
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_model_policy.py
    expected: exactly Sol/high core and Terra/high read-only scout pass
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_model_surface.py
    expected: no selectable legacy model branch exists
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_invocation_args.py
    expected: model overrides and natural-language model hints fail explicitly
risks:
  - A prompt can mention a model without enforcing it; the exported shell launcher must carry the flags.
```

**Interfaces:**

- Produces `Route`, `CORE_ROUTE`, `SCOUT_ROUTE`, `route_for()`, `launcher_argv()`, and `attest_launcher()`.
- Produces `render_export_bundle(prompt, workspace) -> str` with one fenced text block.
- No later module may define another model ID or reasoning level.

- [ ] **Step 1: Write failing fixed-policy tests**

Create `evals/check_model_policy.py` with these assertions:

```python
from cpe_runtime.model_policy import CORE_ROUTE, SCOUT_ROUTE, PolicyError, launcher_argv, route_for

assert (CORE_ROUTE.model, CORE_ROUTE.reasoning) == ("gpt-5.6-sol", "high")
assert (SCOUT_ROUTE.model, SCOUT_ROUTE.reasoning) == ("gpt-5.6-terra", "high")
assert route_for("implementation", read_only=False, verdict_capable=True) == CORE_ROUTE
assert route_for("scout", read_only=True, verdict_capable=False) == SCOUT_ROUTE
for bad in ((False, False), (True, True), (False, True)):
    try:
        route_for("scout", read_only=bad[0], verdict_capable=bad[1])
    except PolicyError:
        pass
    else:
        raise AssertionError(f"unsafe scout route accepted: {bad}")
argv = launcher_argv(CORE_ROUTE, Path("/tmp/worktree"), sandbox="workspace-write")
assert argv == [
    "codex", "exec", "--json", "--model", "gpt-5.6-sol",
    "-c", 'model_reasoning_effort="high"',
    "--sandbox", "workspace-write", "-C", "/tmp/worktree", "-",
]
```

Add script setup, JSON output, and exit handling consistent with other `evals/check_*.py` files.

- [ ] **Step 2: Run RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_model_policy.py`

Expected: FAIL because `cpe_runtime.model_policy` does not exist.

- [ ] **Step 3: Implement the two-route module and attestation**

Create `scripts/cpe_runtime/__init__.py` with no side effects, then create `model_policy.py`:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Route:
    role: str
    model: str
    reasoning: str


POLICY_VERSION = "cpe.model-policy.v1"
CORE_ROUTE = Route("core", "gpt-5.6-sol", "high")
SCOUT_ROUTE = Route("scout", "gpt-5.6-terra", "high")
CORE_ATTEMPT_KINDS = frozenset({
    "coordination", "implementation", "review", "verification",
    "recovery", "repair", "analysis", "completion", "prompt_validation",
})


def policy_payload() -> dict[str, object]:
    return {
        "version": POLICY_VERSION,
        "core": {"model": CORE_ROUTE.model, "reasoning": CORE_ROUTE.reasoning},
        "scout": {"model": SCOUT_ROUTE.model, "reasoning": SCOUT_ROUTE.reasoning},
    }


def policy_hash() -> str:
    raw = json.dumps(policy_payload(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def route_for(attempt_kind: str, *, read_only: bool, verdict_capable: bool) -> Route:
    if attempt_kind == "scout":
        if not read_only or verdict_capable:
            raise PolicyError("Terra scout requires read_only=true and verdict_capable=false")
        return SCOUT_ROUTE
    if attempt_kind not in CORE_ATTEMPT_KINDS:
        raise PolicyError(f"unknown attempt kind: {attempt_kind}")
    return CORE_ROUTE


def launcher_argv(route: Route, worktree: Path, *, sandbox: str) -> list[str]:
    expected_sandbox = "read-only" if route == SCOUT_ROUTE else "workspace-write"
    if sandbox != expected_sandbox:
        raise PolicyError(f"{route.role} requires sandbox={expected_sandbox}")
    return [
        "codex", "exec", "--json", "--model", route.model,
        "-c", f'model_reasoning_effort="{route.reasoning}"',
        "--sandbox", sandbox, "-C", str(worktree), "-",
    ]


def attest_launcher(
    route: Route,
    argv: list[str],
    *,
    provider_model: str | None = None,
    provider_reasoning: str | None = None,
) -> dict[str, object]:
    if provider_model is not None and provider_model != route.model:
        raise PolicyError(f"model attestation mismatch: {provider_model} != {route.model}")
    if provider_reasoning is not None and provider_reasoning != route.reasoning:
        raise PolicyError(f"reasoning attestation mismatch: {provider_reasoning} != {route.reasoning}")
    return {
        "requested_model": route.model,
        "actual_model": provider_model or route.model,
        "requested_reasoning": route.reasoning,
        "actual_reasoning": provider_reasoning or route.reasoning,
        "source": "provider_metadata" if provider_model else "codex_cli_explicit_flags_v1",
        "launcher_sha256": hashlib.sha256(json.dumps(argv).encode()).hexdigest(),
        "verified": True,
    }
```

The trusted-launcher source is allowed only because CPE itself constructs the explicit `--model` and reasoning flags. Worker self-report is never accepted as attestation. If provider metadata is present, mismatch raises `PolicyError`.

- [ ] **Step 4: Add the two-model pricing snapshot**

Create `data/pricing-snapshot.json` with only standard short/long context rates per one million tokens:

```json
{
  "schema_version": "1",
  "effective_at": "2026-07-10",
  "currency": "USD",
  "unit": "per_1m_tokens",
  "source": "https://developers.openai.com/api/docs/pricing",
  "models": {
    "gpt-5.6-sol": {
      "short_context": {"input": 5.0, "cached_input": 0.5, "cache_write": 6.25, "output": 30.0},
      "long_context": {"input": 10.0, "cached_input": 1.0, "cache_write": 12.5, "output": 45.0}
    },
    "gpt-5.6-terra": {
      "short_context": {"input": 2.5, "cached_input": 0.25, "cache_write": 3.125, "output": 15.0},
      "long_context": {"input": 5.0, "cached_input": 0.5, "cache_write": 6.25, "output": 22.5}
    }
  }
}
```

Extend `check_model_policy.py` to assert the model key set is exactly `{gpt-5.6-sol, gpt-5.6-terra}`.

- [ ] **Step 5: Reject model configuration at invocation parsing**

Modify `parse_invocation_args.py`:

```python
FORBIDDEN_MODEL_KEYS = {"model", "reasoning", "profile", "implementer_model", "fallback_model"}
FORBIDDEN_MODEL_HINTS = {
    "spark", "luna", "opus", "오푸스", "xhigh", "max", "pro", "gpt-5.5", "gpt-5.3-codex-spark"
}
```

Before normal `key=value` handling, reject any `FORBIDDEN_MODEL_KEYS` key with `error: CPE v3 model policy is fixed to Sol/high core and Terra/high scout`. Before ignoring an unrecognized natural-language token, reject exact case-insensitive matches in `FORBIDDEN_MODEL_HINTS`. Remove `implementer_model` from `RECOGNIZED_KEYS`, `CHOICES`, and `NL_HINTS`. Do not add core/scout models to parsed values.

Replace the Opus-positive assertions in `check_invocation_args.py` with rejection cases for `model=gpt-5.6-sol`, `reasoning=xhigh`, `implementer_model=opus`, `오푸스로`, and `gpt-5.5 only`.

- [ ] **Step 6: Export an enforceable launcher plus prompt body**

Create `prompt_export.py`:

```python
from __future__ import annotations

import shlex
from pathlib import Path

from .model_policy import CORE_ROUTE, launcher_argv


def render_export_bundle(prompt: str, workspace: Path) -> str:
    argv = launcher_argv(CORE_ROUTE, workspace, sandbox="workspace-write")
    command = shlex.join(argv)
    body = prompt.rstrip()
    return f"```text\n{command} <<'CPE_PROMPT'\n{body}\nCPE_PROMPT\n```\n"
```

Remove line 44 and all routing prose from `templates/fresh-session-prompt.txt`; the prompt body may describe evidence and permissions but must not name a model ID. Update `static_prompt_runner.py` to import and call `render_export_bundle()`. Update `check_prompt.py` to assert:

```python
checks["fixed_launcher"] = (
    "codex exec --json --model gpt-5.6-sol" in text
    and 'model_reasoning_effort="high"' in text
    and "<<'CPE_PROMPT'" in text
)
prompt_body = text.split("<<'CPE_PROMPT'\n", 1)[1].rsplit("\nCPE_PROMPT", 1)[0]
checks["model_not_in_prompt_body"] = "gpt-5.6-" not in prompt_body
```

Delete the Spark-specific checker branch, Spark template, and no-Spark fixture. Update fixtures 01 and 03 to require the Sol launcher and forbid model IDs inside the prompt body.

- [ ] **Step 7: Add the active-surface audit**

Create `evals/check_model_surface.py` to AST-import `model_policy.py`, assert exactly two `Route` constants, and scan active files. Permit removed-model tokens only in `parse_invocation_args.py`'s `FORBIDDEN_MODEL_HINTS` assignment and in this negative test. Exclude `HISTORY.md`, `docs/experiments/`, committed specs/plans, and `evals/live-migration/`. Fail if removed tokens occur in active choices, defaults, prompt templates, positive fixtures, or current docs.

- [ ] **Step 8: Run GREEN and commit T2**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_model_policy.py
python3 evals/check_model_surface.py
python3 evals/check_invocation_args.py
python3 evals/static_prompt_runner.py --fixture evals/fixtures/01-prompt-only.yaml --output /tmp/cpe-v3-prompt-output.md --run-log /tmp/cpe-v3-prompt-run.jsonl
python3 evals/check_prompt.py --fixture evals/fixtures/01-prompt-only.yaml --output /tmp/cpe-v3-prompt-output.md
```

Expected: all checks pass; no global or project Codex config file is written.

```bash
git add skills/kws-codex-plan-executor
git commit -m "feat(cpe): enforce fixed Sol and Terra routes"
```

---

### Task 3: Add Immutable Manifest And Evidence Stores

```yaml
id: T3
title: Immutable v3 manifest and content-addressed evidence
owner_boundary: Run inputs and immutable artifacts only
files:
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/manifest.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/evidence.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/check_manifest_evidence.py
    mode: owned
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_manifest_evidence.py
    expected: immutable create/read/hash/tamper checks pass
risks:
  - Rewriting a manifest or evidence object would make replay non-reproducible.
```

**Interfaces:**

- Produces `create_manifest(run_id, mode, workspace, worktree, plan, spec, task_graph, pricing_snapshot) -> dict`, `load_manifest(path) -> dict`, and `canonical_hash(payload) -> str`.
- Produces `EvidenceRef`, `put_json(run_dir, kind, payload)`, and `verify_ref(run_dir, ref)`.
- Task graph entries are immutable `{id, title, dependencies, file_claims, spec_refs, acceptance_command}` objects.

- [ ] **Step 1: Write the failing manifest/evidence tests**

Create `evals/check_manifest_evidence.py` to create a temporary plan/spec/pricing file and assert:

```python
manifest = create_manifest(
    run_id="fixture-20260710-010203",
    mode="interactive",
    workspace=repo,
    worktree=worktree,
    plan=plan,
    spec=spec,
    task_graph=[{"id": "task_1", "title": "One", "dependencies": [], "file_claims": ["src/a.py"], "spec_refs": ["goals"], "acceptance_command": "python3 -m pytest"}],
    pricing_snapshot=pricing,
)
assert manifest["schema_version"] == "3"
assert manifest["model_policy"] == policy_payload()
assert manifest["model_policy_hash"] == policy_hash()
assert manifest["plan_graph_hash"]
try:
    write_manifest(run_dir / "run_manifest.json", manifest)
except FileExistsError:
    pass
else:
    raise AssertionError("manifest rewrite must fail")
ref = put_json(run_dir, "verification", {"passed": True})
assert verify_ref(run_dir, ref) == []
(run_dir / ref.path).write_text("{}\n")
assert verify_ref(run_dir, ref) == ["evidence digest mismatch"]
```

Use a small local `raises` context manager or explicit try/except so the check has no pytest dependency.

- [ ] **Step 2: Run RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_manifest_evidence.py`

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement canonical manifest creation**

In `manifest.py`, implement canonical JSON with sorted keys and compact separators, SHA-256 helpers, repo/home-relative refs, and exclusive manifest creation. The manifest must contain:

```python
payload = {
    "schema_version": "3",
    "run_id": run_id,
    "mode": mode,
    "workspace_ref": relative_ref(workspace),
    "execution_worktree_ref": relative_ref(worktree),
    "plan": file_record(plan),
    "spec": file_record(spec) if spec else None,
    "task_graph": task_graph,
    "plan_graph_hash": canonical_hash(task_graph),
    "model_policy": policy_payload(),
    "model_policy_hash": policy_hash(),
    "pricing_snapshot": file_record(pricing_snapshot),
    "pricing_snapshot_hash": sha256_file(pricing_snapshot),
}
```

`write_manifest()` must use `open(path, "x", encoding="utf-8")`, flush, and `os.fsync()` before returning. `load_manifest()` rejects anything other than schema `3`.

- [ ] **Step 4: Implement content-addressed evidence**

In `evidence.py`, use this stable reference type:

```python
@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    path: str
    sha256: str
    media_type: str = "application/json"


def put_json(run_dir: Path, kind: str, payload: object) -> EvidenceRef:
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    relative = Path("artifacts") / "evidence" / kind / f"{digest}.json"
    target = run_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != raw:
        raise EvidenceError("existing evidence path has different content")
    if not target.exists():
        with target.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    return EvidenceRef(kind, relative.as_posix(), digest)
```

`verify_ref()` must reject absolute paths, path escapes, missing files, and digest mismatch.

- [ ] **Step 5: Run GREEN and commit T3**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_manifest_evidence.py
python3 -m py_compile scripts/cpe_runtime/manifest.py scripts/cpe_runtime/evidence.py
git add scripts/cpe_runtime/manifest.py scripts/cpe_runtime/evidence.py evals/check_manifest_evidence.py
git commit -m "feat(cpe): add immutable run and evidence stores"
```

---

### Task 4: Build The Hash-Chained Event Kernel And Projector

```yaml
id: T4
title: Event store, pure projector, and atomic transition kernel
owner_boundary: Durable run transitions only
files:
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/events.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/projector.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/kernel.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/check_event_kernel.py
    mode: owned
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_event_kernel.py
    expected: chain, state-machine, crash recovery, and single-writer checks pass
risks:
  - Snapshot writes can fail after an event is durable; replay must recover without losing the event.
```

**Interfaces:**

- `append_event(path, unsigned) -> dict`, `read_events(path) -> list[dict]`, `validate_chain(events) -> list[str]`.
- `initial_state(manifest) -> dict`, `apply_event(state, event) -> dict`, `project(manifest, events) -> dict`.
- `Kernel.transition(command) -> dict` is the only state mutation API.
- `rebuild_snapshot(run_dir) -> dict` replays valid events and atomically replaces only the derived snapshot.

- [ ] **Step 1: Write RED tests for chain integrity and replay**

Create `evals/check_event_kernel.py` with cases for valid transitions, sequence gaps, reordered events, changed payload hashes, invalid run/task jumps, non-runtime actor rejection, and simulated snapshot-write failure. The recovery case must assert:

```python
kernel = Kernel(run_dir)
kernel.transition(Transition("run.status_changed", {"from": "created", "to": "ready"}))
kernel._snapshot_writer = lambda *_: (_ for _ in ()).throw(OSError("fixture crash"))
try:
    kernel.transition(Transition("run.status_changed", {"from": "ready", "to": "running"}))
except OSError:
    pass
recovered = rebuild_snapshot(run_dir)
assert recovered["lifecycle"] == "running"
assert recovered["last_event"]["seq"] == 2
```

- [ ] **Step 2: Run RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_event_kernel.py`

Expected: FAIL because event-kernel modules do not exist.

- [ ] **Step 3: Implement canonical hash-chained events**

`events.py` must define an event without its `hash`, calculate SHA-256 over canonical JSON, append one JSON line under an exclusive `fcntl.flock`, flush and fsync, then release the lock. The envelope is:

```python
{
    "seq": next_seq,
    "event_id": uuid.uuid4().hex,
    "type": event_type,
    "at": now_iso(),
    "actor": "cpe-runtime",
    "task_id": task_id,
    "attempt_id": attempt_id,
    "payload": payload,
    "previous_hash": previous_hash,
    "hash": event_hash,
}
```

`validate_chain()` returns stable messages for invalid sequence, predecessor, event hash, and duplicate event ID.

- [ ] **Step 4: Implement the pure projector and state machines**

Use these exact transition tables in `projector.py`:

```python
RUN_TRANSITIONS = {
    "created": {"ready", "blocked", "failed"},
    "ready": {"running", "blocked", "failed"},
    "running": {"completed", "blocked", "failed"},
    "blocked": {"ready", "failed"},
    "failed": set(),
    "completed": set(),
}
TASK_TRANSITIONS = {
    "pending": {"ready", "blocked", "failed"},
    "ready": {"scouting", "implementing", "blocked", "failed"},
    "scouting": {"implementing", "blocked", "failed"},
    "implementing": {"reviewing", "repairing", "blocked", "failed"},
    "reviewing": {"verifying", "repairing", "blocked", "failed"},
    "verifying": {"completed", "repairing", "blocked", "failed"},
    "repairing": {"reviewing", "verifying", "blocked", "failed"},
    "completed": set(),
    "blocked": {"ready", "failed"},
    "failed": set(),
}
```

The projected state contains only v3 fields: schema version, run ID, lifecycle, current task, task summaries, attempts, blockers, context health, completion audit, usage totals, artifact index, and last event sequence/hash. Event handlers are limited to `run.status_changed`, `task.status_changed`, `attempt.recorded`, `evidence.attached`, `context.updated`, `completion.recorded`, and `repair.applied`.

- [ ] **Step 5: Implement the transition kernel**

`kernel.py` must expose:

```python
@dataclass(frozen=True)
class Transition:
    event_type: str
    payload: dict[str, object]
    task_id: str | None = None
    attempt_id: str | None = None


class Kernel:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir.resolve()
        self._snapshot_writer = atomic_write_snapshot

    def transition(self, command: Transition) -> dict[str, object]:
        return transition_run(self.run_dir, command, snapshot_writer=self._snapshot_writer)
```

`transition()` loads manifest and events, projects the current state, validates the requested jump, appends the event, reprojects, then atomically writes `state.json` through a same-directory temporary file, fsync, and `os.replace`. It accepts no caller-supplied actor; actor is always `cpe-runtime`.

- [ ] **Step 6: Run GREEN and commit T4**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_event_kernel.py
python3 -m py_compile scripts/cpe_runtime/events.py scripts/cpe_runtime/projector.py scripts/cpe_runtime/kernel.py
git add scripts/cpe_runtime/events.py scripts/cpe_runtime/projector.py scripts/cpe_runtime/kernel.py evals/check_event_kernel.py
git commit -m "feat(cpe): add replayable event transition kernel"
```

---

### Task 5: Require Explicit Spec Mapping And Deterministic Preflight

```yaml
id: T5
title: V3 task packets with no full-spec fallback
owner_boundary: Plan compilation, task packet context, readiness, and executability
files:
  - path: skills/kws-codex-plan-executor/scripts/parse_invocation_args.py
    mode: edit
  - path: skills/kws-codex-plan-executor/scripts/build_spec_manifest.py
    mode: edit
  - path: skills/kws-codex-plan-executor/scripts/build_task_packet.py
    mode: edit
  - path: skills/kws-codex-plan-executor/scripts/audit_run_readiness.py
    mode: edit
  - path: skills/kws-codex-plan-executor/scripts/audit_plan_executability.py
    mode: edit
  - path: skills/kws-codex-plan-executor/scripts/build_context_snapshot.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_invocation_args.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_spec_manifest.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_task_packet.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_run_readiness.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_task_packet.py
    expected: explicit mappings pass and missing mappings block before execution
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_run_readiness.py
    expected: no full-spec fallback result shape remains
risks:
  - Heuristic spec matching can appear convenient while silently loading excessive or wrong context.
```

**Interfaces:**

- `build_manifest(spec_path) -> dict` no longer accepts a fallback policy.
- `resolve_sections(task, manifest) -> list[str]` accepts explicit refs only.
- Task packets use schema `3` and live under `artifacts/task-packets/`.

- [ ] **Step 1: Convert packet tests to the v3 contract and run RED**

Change task-packet tests so an explicit task maps exactly to listed sections and a task without `spec_refs` exits non-zero with `missing_explicit_spec_mapping`. Assert the output never contains `fallback_used`, `fallback_reason`, `suggested_spec_refs`, `suggested_plan_patch`, or a full raw spec.

Run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
```

Expected: FAIL because current code still performs heuristic/full-spec fallback.

- [ ] **Step 2: Remove fallback from invocation and spec manifest**

Remove `manifest_fallback` from parser defaults, recognized keys, choices, echo, docs-facing output, and tests. Input `manifest_fallback=full_spec_on_blocker` must fail as an unknown removed option. Change `build_spec_manifest.build_manifest()` to:

```python
def build_manifest(spec_path: Path) -> dict:
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError:
        die(f"spec is not readable: {spec_path}")
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    headings = visible_heading_lines(lines)
    sections: dict[str, dict] = {}
    section_order: list[str] = []
    if not headings:
        sections["S0"] = {
            "id": "S0", "title": "document", "level": 0,
            "line_start": 1, "line_end": total_lines if total_lines else 1,
            "chars": len(text), "sha256": sha256_text(text),
            "signals": section_signals("document", text),
        }
        section_order.append("S0")
    else:
        assigned = assign_section_ids(headings)
        for index, (section_id, line_start, level, title) in enumerate(assigned):
            line_end = section_end_line(index, assigned, total_lines)
            body = "".join(lines[line_start - 1 : line_end])
            sections[section_id] = {
                "id": section_id, "title": title, "level": level,
                "line_start": line_start, "line_end": line_end,
                "chars": len(body), "sha256": sha256_text(body),
                "signals": section_signals(title, body),
            }
            section_order.append(section_id)
    return {
        "schema_version": "3",
        "spec_path": str(spec_path),
        "spec_sha256": sha256_text(text),
        "spec_total_chars": len(text),
        "sections": sections,
        "section_order": section_order,
        "task_to_sections": {},
    }
```

- [ ] **Step 3: Replace heuristic resolution with explicit mapping**

Replace `build_task_packet.resolve_sections()` with:

```python
def resolve_sections(task: dict, manifest: dict) -> list[str]:
    refs = task.get("spec_refs")
    if not isinstance(refs, list) or not refs:
        die(f"missing_explicit_spec_mapping: {task.get('id', 'unknown')}")
    sections = manifest.get("sections")
    available = set(sections) if isinstance(sections, dict) else set()
    unknown = [item for item in refs if item not in available]
    if unknown:
        die(f"unknown_spec_refs: {', '.join(unknown)}")
    return refs
```

Delete `heuristic_sections`, `fallback_reason`, `suggested_spec_refs`, `suggested_plan_patch`, `fallback_next_action`, and fallback-policy CLI handling. `spec_context()` concatenates only mapped sections and returns their digest.

- [ ] **Step 4: Align readiness, executability, and context snapshots**

Make missing mapping a blocking issue named `missing_explicit_spec_mapping`. Readiness and executability must point to the task ID and plan line, but must not suggest automatically inferred refs. `build_context_snapshot.py` budgets the largest explicit task packet, not the entire spec.

- [ ] **Step 5: Run GREEN and commit T5**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_invocation_args.py
python3 evals/check_spec_manifest.py
python3 evals/check_task_packet.py
python3 evals/check_run_readiness.py
python3 evals/check_plan_executability_audit.py
python3 evals/check_context_snapshot.py
git add scripts/parse_invocation_args.py scripts/build_spec_manifest.py scripts/build_task_packet.py \
  scripts/audit_run_readiness.py scripts/audit_plan_executability.py scripts/build_context_snapshot.py \
  evals/check_invocation_args.py evals/check_spec_manifest.py evals/check_task_packet.py \
  evals/check_run_readiness.py evals/check_plan_executability_audit.py
git commit -m "feat(cpe): require explicit task spec mappings"
```

---

### Task 6: Make Superpowers Compatibility Capability-Based

```yaml
id: T6
title: Semantic Superpowers capability audit
owner_boundary: Read-only compatibility discovery only
files:
  - path: skills/kws-codex-plan-executor/scripts/audit_superpowers_compatibility.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_superpowers_compatibility.py
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_superpowers_compatibility.py
    expected: rephrased compatible fixtures pass and missing capabilities block
risks:
  - Exact prose matching breaks whenever an installed skill improves its wording.
```

**Interfaces:**

- Produces `inspect_skill(path) -> SkillContract` and `required_contracts(root) -> dict[str, bool]`.
- The audit remains read-only and requires explicit `--superpowers-root` and `--skill-root` paths.

- [ ] **Step 1: Replace prose-token fixtures with semantic fixtures and run RED**

In `check_superpowers_compatibility.py`, generate four temporary skill folders with valid YAML frontmatter, distinct rephrased prose, required headings, required skill references, approval gates, task review, and fresh verification commands. Add one fixture that removes the approval gate and assert `brainstorming_design_approval` becomes false.

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_superpowers_compatibility.py`

Expected: FAIL because current `has_all()` requires exact English sentences.

- [ ] **Step 2: Implement structural capability extraction**

Replace exact sentence checks with:

```python
import re
from dataclasses import dataclass


HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*$")
SKILL_REF_RE = re.compile(r"(?:superpowers:|\$)([a-z0-9-]+)")


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    _, raw, _ = text.split("---", 2)
    result: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip('"')
    return result


def normalize_heading(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", " ", value.lower()).strip()


def approval_gate_present(text: str) -> bool:
    lowered = text.lower()
    approval = any(term in lowered for term in ("approval", "approve", "승인"))
    implementation = any(term in lowered for term in ("implementation", "implement", "구현"))
    gate = "<hard-gate>" in lowered or any("gate" in item for item in HEADING_RE.findall(lowered))
    return approval and implementation and gate


def verification_command_present(text: str) -> bool:
    headings = {normalize_heading(item) for item in HEADING_RE.findall(text)}
    has_verification_heading = any("verification" in item or "검증" in item for item in headings)
    has_command = bool(re.search(r"```(?:bash|sh|shell)?\n[^`]+\n```", text, re.IGNORECASE))
    return has_verification_heading and has_command


@dataclass(frozen=True)
class SkillContract:
    name: str
    headings: frozenset[str]
    skill_refs: frozenset[str]
    has_approval_gate: bool
    has_task_checkboxes: bool
    has_fresh_verification_command: bool


def inspect_skill(path: Path) -> SkillContract:
    text = read_text(path)
    frontmatter = parse_frontmatter(text)
    headings = frozenset(normalize_heading(item) for item in HEADING_RE.findall(text))
    refs = frozenset(SKILL_REF_RE.findall(text))
    return SkillContract(
        name=str(frontmatter.get("name", "")),
        headings=headings,
        skill_refs=refs,
        has_approval_gate=approval_gate_present(text),
        has_task_checkboxes="- [ ]" in text,
        has_fresh_verification_command=verification_command_present(text),
    )
```

Capabilities are based on frontmatter name, normalized headings, referenced skill names, checkbox plan shape, and gate semantics such as approval before implementation or fresh command evidence before completion. Do not require any full sentence.

- [ ] **Step 3: Remove home-directory assumptions**

The deterministic eval must use only its generated fixture root. Runtime callers resolve the installed Superpowers root from the active skill registry and pass it explicitly. Keep the audit free of worktree, state, or repository mutation.

- [ ] **Step 4: Run GREEN and commit T6**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_superpowers_compatibility.py
git add scripts/audit_superpowers_compatibility.py evals/check_superpowers_compatibility.py
git commit -m "fix(cpe): audit Superpowers by capability"
```

---

### Task 7: Add The Worker Controller, Scheduler, And Public Runtime CLI

```yaml
id: T7
title: Executable v3 plan runtime
owner_boundary: Worker launch, task scheduling, run/resume/export orchestration
files:
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/worker.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/scheduler.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/cpe.py
    mode: owned
  - path: skills/kws-codex-plan-executor/templates/worker-result-schema.json
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/check_execution_runtime.py
    mode: owned
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_execution_runtime.py
    expected: isolated fake-provider run uses Sol for all core attempts, Terra only for safe scouts, and event-projected state
risks:
  - Concurrent write attempts could corrupt the worktree or make review evidence ambiguous.
```

**Interfaces:**

- `Worker.run(request: WorkerRequest) -> WorkerResult`.
- `run_scouts(requests, worker) -> list[WorkerResult]` is the only concurrent path.
- `run_tasks(tasks, worker, kernel) -> dict` executes all write-capable tasks sequentially.
- `scripts/cpe.py` exposes `run`, `resume`, and `export`; no model-selection flags exist.

- [ ] **Step 1: Create a failing fake-provider integration test**

`check_execution_runtime.py` must create a temporary git repository and a fake `codex` executable earlier in `PATH`. The fake executable records argv, rejects missing `--model` or reasoning flags, emits documented Codex JSONL event types, and returns worker-schema JSON. Assert:

```python
assert all_core_launches_use("gpt-5.6-sol", "high", sandbox="workspace-write")
assert all_scout_launches_use("gpt-5.6-terra", "high", sandbox="read-only")
assert max_concurrent_write_launches == 1
assert source_checkout_diff == []
assert user_config_before == user_config_after
assert project_config_before == project_config_after
assert state == project(manifest, read_events(events_path))
```

- [ ] **Step 2: Run RED**

Run: `cd skills/kws-codex-plan-executor && python3 evals/check_execution_runtime.py`

Expected: FAIL because the worker, scheduler, and CLI do not exist.

- [ ] **Step 3: Define the structured worker result schema**

Create `templates/worker-result-schema.json` requiring:

```json
{
  "type": "object",
  "properties": {
    "status": {"enum": ["completed", "blocked", "failed"]},
    "summary": {"type": "string", "maxLength": 2000},
    "changed_files": {"type": "array", "items": {"type": "string"}},
    "findings": {"type": "array", "items": {"type": "string"}},
    "evidence_refs": {"type": "array", "items": {"type": "string"}},
    "missing_evidence": {"type": "array", "items": {"type": "string"}},
    "verification": {"type": "array", "items": {"type": "object"}}
  },
  "required": ["status", "summary", "changed_files", "findings", "evidence_refs", "missing_evidence", "verification"],
  "additionalProperties": false
}
```

Scout validation additionally requires empty `changed_files` and `verification`, and treats any verdict-like output as a policy violation.

- [ ] **Step 4: Implement the worker controller**

Define these types in `worker.py`:

```python
@dataclass(frozen=True)
class WorkerRequest:
    attempt_id: str
    attempt_kind: str
    prompt: str
    worktree: Path
    read_only: bool
    verdict_capable: bool


@dataclass(frozen=True)
class WorkerResult:
    status: str
    payload: dict[str, object]
    attestation: dict[str, object]
    usage: dict[str, int]
    latency_ms: int
    raw_event_digest: str
```

`Worker.run()` derives the route from `route_for()`, builds argv with `launcher_argv()`, adds `--output-schema` and `--output-last-message`, sends the prompt through stdin, and parses only documented JSONL event types. Store a redacted digest and bounded diagnostic summary, never the raw transcript. `turn.completed.usage` supplies input, cached input, output, and reasoning output tokens. Use `attest_launcher()`; provider metadata, when available from a trusted adapter, must match.

- [ ] **Step 5: Implement deterministic scheduling**

`scheduler.py` uses a `ThreadPoolExecutor(max_workers=min(4, len(requests)))` only inside `run_scouts()`. `run_tasks()` iterates topologically sorted plan tasks and performs this sequence through kernel events:

```text
ready -> implementing -> reviewing -> verifying -> completed
                               \-> repairing -> reviewing/verifying
```

Implementation, task review, verification judgment, repair, and whole-diff review are separate Sol attempts. Maximum retries for the same root-cause key are two; the third required attempt records `run.status_changed -> blocked`.

- [ ] **Step 6: Implement `scripts/cpe.py`**

The CLI shape is:

```text
python3 scripts/cpe.py run --plan PLAN [--spec SPEC] [--docs DOC] --workspace REPO --mode interactive|headless
python3 scripts/cpe.py resume --run-id RUN_ID
python3 scripts/cpe.py export --plan PLAN [--spec SPEC] --workspace REPO --mode prompt|handoff
```

There are no `--model`, `--reasoning`, `--profile`, or fallback arguments. `run` performs dependency/capability preflight, parses the plan, requires explicit mappings, allocates a non-conflicting run ID/worktree, writes manifest, creates the initial event, builds packets, and calls the scheduler. `resume` loads only a v3 manifest/event chain and continues dependency-ready work. `export` calls `render_export_bundle()` and creates no worktree or run artifact.

- [ ] **Step 7: Run GREEN and commit T7**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_execution_runtime.py
python3 -m py_compile scripts/cpe.py scripts/cpe_runtime/worker.py scripts/cpe_runtime/scheduler.py
git add scripts/cpe.py scripts/cpe_runtime/worker.py scripts/cpe_runtime/scheduler.py \
  templates/worker-result-schema.json evals/check_execution_runtime.py
git commit -m "feat(cpe): execute v3 plans through fixed model workers"
```

---

### Task 8: Replace The Public Validator And Completion Gate

```yaml
id: T8
title: One v3 validator for all consumers
owner_boundary: Schema, integrity, attestation, and completion decisions
files:
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/validation.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/validate_state.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_state_schema.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_validation_consumer_parity.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/check_validate_state_modular_parity.py
    mode: delete
  - path: skills/kws-codex-plan-executor/evals/check_verification_bundle.py
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_state_schema.py
    expected: v3 integrity cases pass and v2 is unsupported_schema
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_validation_consumer_parity.py
    expected: CLI, completion, reconciliation, repair, and inspection use identical errors
risks:
  - Divergent validators would allow completion while inspection or repair sees different truth.
```

**Interfaces:**

- Produces `ValidationReport(classification, passed, errors, warnings)` and `validate_run(run_dir) -> ValidationReport`.
- Public `validate_state.py <state-or-run-dir>` prints that report as JSON.
- V2 returns classification `unsupported_schema`, exit code `2`, and no mutation.

- [ ] **Step 1: Rewrite state tests around v3 and run RED**

Replace v2 fixture builders in `check_state_schema.py` with a helper that uses manifest/events/kernel. Add failures for manifest hash drift, event gap/hash mismatch, snapshot replay mismatch, missing evidence, out-of-scope diff evidence, missing Sol attestation, Terra used for a core attempt, open blocker, unfinished task, missing whole-diff review, and completion evidence not referencing real digests.

Add a v2 file containing only `{"schema_version":"2.27.0"}` and assert `unsupported_schema`, unchanged bytes, and exit `2`.

- [ ] **Step 2: Implement `ValidationReport` and ordered validation**

`validation.py` must run checks in this order:

```python
CHECK_ORDER = (
    "schema", "manifest", "event_chain", "snapshot_replay", "artifacts",
    "task_states", "model_attestation", "worktree_and_diff", "verification",
    "completion",
)
```

Use one stable error code per finding, including `unsupported_schema`, `manifest_hash_mismatch`, `event_chain_invalid`, `snapshot_replay_mismatch`, `evidence_missing`, `model_attestation_missing`, `model_attestation_mismatch`, `diff_scope_violation`, and `completion_gate_failed`.

- [ ] **Step 3: Replace the public validator**

Reduce `validate_state.py` to argument resolution plus:

```python
path = Path(args.path).expanduser().resolve()
run_dir = path if path.is_dir() else path.parent
report = validate_run(run_dir)
print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
if report.classification == "unsupported_schema":
    return 2
return 0 if report.passed else 1
```

Do not call `_validate_legacy` or `cpe_state_validation`.

- [ ] **Step 4: Add consumer parity checks**

Create `check_validation_consumer_parity.py` that corrupts one event and asserts the public CLI, completion precheck, reconciliation, repair planner, and inspection all surface the same `event_chain_invalid` code. Initially provide simple adapters in those consumers if their full v3 implementations arrive in T9/T10; they must call `validate_run()` directly.

- [ ] **Step 5: Run GREEN and commit T8**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_state_schema.py
python3 evals/check_verification_bundle.py
python3 evals/check_validation_consumer_parity.py
python3 -m py_compile scripts/validate_state.py scripts/cpe_runtime/validation.py
git add scripts/validate_state.py scripts/cpe_runtime/validation.py evals/check_state_schema.py \
  evals/check_validation_consumer_parity.py evals/check_verification_bundle.py
git rm evals/check_validate_state_modular_parity.py
git commit -m "feat(cpe): validate v3 runs from replayed evidence"
```

---

### Task 9: Rebuild Reconciliation And Repair On Compensating Events

```yaml
id: T9
title: Deterministic v3 reconciliation and repair
owner_boundary: Drift detection and explicitly safe repair only
files:
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/reconciliation.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/repair.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/reconcile_state.py
    mode: edit
  - path: skills/kws-codex-plan-executor/scripts/repair_runs.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_state_reconciliation.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_repair_runs.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_recovery_policy.py
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_state_reconciliation.py
    expected: ordered drift checks and non-mutating check mode pass
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_repair_runs.py
    expected: dry-run default, explicit apply, compensating events, and v2 preservation pass
risks:
  - Direct snapshot patches would destroy replay parity and could fabricate success.
```

**Interfaces:**

- `reconcile(run_dir) -> ReconciliationReport` with `clean|repairable|blocking_drift`.
- `plan_repairs(run_dir) -> RepairPlan` is non-mutating.
- `apply_repair(run_dir, action) -> dict` appends a compensating event or atomically rebuilds derived state.

- [ ] **Step 1: Rewrite reconciliation/repair tests and run RED**

Cover checks in the exact design order: manifest hashes, event chain, replayed snapshot, stored snapshot, git identity/diff, file claims, evidence digests, attempt terminal/attestation, verification links. Test that `--check` and repair-plan generation leave all run bytes unchanged.

Test allowed repairs:

- rebuild snapshot from a valid event chain;
- regenerate derived inspection/index output;
- mark a provably dead stale attempt interrupted through `repair.applied`;
- reconnect an evidence digest already present under the run root.

Test forbidden repairs: product-file edit, fabricated success, changed plan/spec hash, invented attestation, failed-to-completed rewrite, damaged event-chain overwrite, and any v2 mutation.

- [ ] **Step 2: Implement ordered reconciliation**

Create `ReconciliationFinding(code, severity, message, repair_action)` and `ReconciliationReport`. A valid event chain with a stale/missing snapshot is `repairable`; invalid event history, plan/spec drift, evidence digest mismatch, model mismatch, or diff-scope violation is `blocking_drift`.

- [ ] **Step 3: Implement dry-run repair planning and safe apply**

`repair.py` defines only these actions:

```python
SAFE_ACTIONS = {
    "rebuild_snapshot",
    "regenerate_derived_reports",
    "mark_stale_attempt_interrupted",
    "reconnect_existing_evidence",
}
```

Every apply requires an explicit run ID and action. Snapshot rebuild does not append an event because it restores a derived cache. Attempt interruption and evidence reconnection append `repair.applied` with before/after evidence. Re-run `validate_run()` before and after; failed post-validation leaves the new event visible and marks the run blocked rather than deleting history.

- [ ] **Step 4: Replace public CLIs without changing their safety posture**

`reconcile_state.py --check` remains read-only. `--repair-safe` applies only `rebuild_snapshot` and `regenerate_derived_reports`; other repairs require an exact command such as `repair_runs.py --run-id fixture-run --action mark_stale_attempt_interrupted --apply`. V2 input prints `unsupported_schema` and never changes bytes.

- [ ] **Step 5: Run GREEN and commit T9**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_state_reconciliation.py
python3 evals/check_repair_runs.py
python3 evals/check_recovery_policy.py
python3 evals/check_validation_consumer_parity.py
git add scripts/cpe_runtime/reconciliation.py scripts/cpe_runtime/repair.py \
  scripts/reconcile_state.py scripts/repair_runs.py \
  evals/check_state_reconciliation.py evals/check_repair_runs.py evals/check_recovery_policy.py
git commit -m "feat(cpe): reconcile and repair v3 event state"
```

---

### Task 10: Rebuild Read-Only Inspection And Recent-Run Metrics

```yaml
id: T10
title: V3 current and recent run inspection
owner_boundary: Read-only projections and aggregate metrics
files:
  - path: skills/kws-codex-plan-executor/scripts/cpe_runtime/inspection.py
    mode: owned
  - path: skills/kws-codex-plan-executor/scripts/inspect_runs.py
    mode: edit
  - path: skills/kws-codex-plan-executor/scripts/analyze_recent_runs.py
    mode: edit
  - path: skills/kws-codex-plan-executor/scripts/normalize_cpe_run.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_inspect_runs.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_recent_run_rubric.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_cpe_replay.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_operational_run_quality.py
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_inspect_runs.py
    expected: current/recent inspection is read-only and schema-aware
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_recent_run_rubric.py
    expected: completion, first-pass, repair, attestation, token, cost, latency, and drift metrics pass
risks:
  - Derived quality fields must not become a second writable source of truth.
```

**Interfaces:**

- `inspect_run(run_dir) -> dict` and `inspect_recent(codex_home, limit) -> dict`.
- `normalize_cpe_run.py` serializes inspection output; it never reads raw prompts or transcripts.
- V2 directories appear only as `{classification: unsupported_schema}`.

- [ ] **Step 1: Rewrite inspection tests and run RED**

Create v3 finished, blocked, failed, stale, corrupted, and v2 fixture directories. Hash every file before and after inspection and assert identical bytes. Expected aggregate fields are:

```python
{
    "run_count", "completed_count", "blocked_count", "failed_count",
    "first_pass_success_rate", "average_repair_attempts",
    "model_attestation_success_rate", "input_tokens", "cached_input_tokens",
    "output_tokens", "reasoning_output_tokens", "estimated_cost_usd",
    "average_latency_ms", "environment_failure_count",
    "drift_count", "repair_count", "missing_evidence_count",
    "unsupported_schema_count",
}
```

- [ ] **Step 2: Implement pure inspection projections**

`inspection.py` loads manifest/events, projects current state, calls `validate_run()` and `reconcile()`, verifies evidence refs, computes metrics from attempt records, and returns recommendations. It does not write `run_quality`, reports, state, timestamps, or repair hints back to disk.

Cost calculation reads the pinned pricing snapshot referenced by the manifest. When billing context class is unknown, report both short- and long-context estimates and leave `estimated_cost_usd` null rather than guessing.

- [ ] **Step 3: Replace public inspection and normalization scripts**

Keep existing CLI flags where they do not imply v2 compatibility: `--codex-home`, `--plan`, `--all-plans`, `--recent`, `--jsonl`, `--output`, and `--include-finished`. Remove v2 run-quality mutation terminology. `normalize_cpe_run.py` outputs stable v3 lifecycle, attestation, evidence, usage, cost, latency, repair, and validation summaries only.

- [ ] **Step 4: Run GREEN and commit T10**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_inspect_runs.py
python3 evals/check_recent_run_rubric.py
python3 evals/check_cpe_replay.py
python3 evals/check_operational_run_quality.py
python3 evals/check_validation_consumer_parity.py
git add scripts/cpe_runtime/inspection.py scripts/inspect_runs.py scripts/analyze_recent_runs.py \
  scripts/normalize_cpe_run.py evals/check_inspect_runs.py evals/check_recent_run_rubric.py \
  evals/check_cpe_replay.py evals/check_operational_run_quality.py
git commit -m "feat(cpe): inspect v3 runs from immutable evidence"
```

---

### Task 11: Replace Static Fixtures, Add Fault Injection, And Build The Live Migration Gate

```yaml
id: T11
title: End-to-end deterministic and live migration evidence
owner_boundary: Eval fixtures and release evidence only
files:
  - path: skills/kws-codex-plan-executor/evals/static_execution_runner.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_execution.py
    mode: edit
  - path: skills/kws-codex-plan-executor/evals/check_fault_injection.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/live-migration/matrix.json
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/live-migration/cases.json
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/live-migration/current-v2-prompt.txt
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/live_model_migration.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/check_live_model_migration.py
    mode: owned
  - path: skills/kws-codex-plan-executor/evals/run.sh
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && python3 evals/check_fault_injection.py
    expected: event/snapshot/evidence/model/worktree fault cases pass
  - command: cd skills/kws-codex-plan-executor && python3 evals/live_model_migration.py --dry-run --budget-usd 50 --output /tmp/cpe-v3-live-plan.json
    expected: four treatments and bounded case commands are emitted without model calls
risks:
  - Live evaluation consumes credentials and budget; dry-run is automatic but paid execution requires explicit approval.
```

**Interfaces:**

- Static execution fixtures must call real v3 kernel/runtime with a fake provider; they may not handcraft `state.json`.
- Live migration files are the only non-historical active eval area permitted to name GPT-5.5.
- Live harness requires `--confirm-live-cost`, `--budget-usd`, and a writable output path for non-dry-run execution.

- [ ] **Step 1: Make static fixtures fail when they handcraft state**

Update `check_execution.py` to require `run_manifest.json`, non-empty `events.jsonl`, replay parity, content-addressed evidence, and fixed attestation. It must reject a state file with no event chain. Run one execution fixture and confirm RED against the old static runner.

- [ ] **Step 2: Route static execution through the v3 runtime**

Replace `static_execution_runner.build_state()` with a fake worker adapter passed into `cpe.py`/scheduler. The fake adapter returns deterministic structured worker results and usage, while all manifest/events/state/evidence are written by production modules. Keep source-checkout isolation assertions.

- [ ] **Step 3: Add deterministic fault injection**

Create `check_fault_injection.py` for:

- interruption immediately after event fsync;
- interruption before snapshot replace;
- snapshot corruption;
- event sequence/hash corruption;
- missing and digest-mismatched evidence;
- model mismatch;
- worker timeout and verification interruption;
- stale attempt and missing worktree;
- source-checkout edit and out-of-claim product diff.

Each case asserts the exact validator/reconciliation classification and whether repair is allowed.

- [ ] **Step 4: Define the isolated migration matrix**

Create `evals/live-migration/matrix.json` with exactly four treatments:

```json
{
  "schema_version": "1",
  "treatments": [
    {"id": "gpt55_current", "model": "gpt-5.5", "reasoning": "high", "prompt": "current-v2-prompt.txt"},
    {"id": "sol_current", "model": "gpt-5.6-sol", "reasoning": "high", "prompt": "current-v2-prompt.txt"},
    {"id": "sol_v3", "model": "gpt-5.6-sol", "reasoning": "high", "prompt": "../../templates/fresh-session-prompt.txt"},
    {"id": "terra_scout", "model": "gpt-5.6-terra", "reasoning": "high", "prompt": "terra-scout-generated"}
  ]
}
```

`cases.json` contains eight bounded cases: single-file implementation, cross-package implementation, root-cause repair, defect review, failed-test interpretation, security/migration block, resume/state repair, and large read-only exploration. Only the large read-only case permits the Terra treatment to count as a candidate route; Terra results for verdict-capable cases are recorded as expected policy failures.

- [ ] **Step 5: Implement the budgeted live harness and deterministic checker**

`live_model_migration.py` validates the matrix, estimates a hard upper bound before launching, refuses to exceed `--budget-usd`, and requires `--confirm-live-cost` unless `--dry-run`. It records task completion, first-pass success, review accuracy, evidence completeness, repairs, regressions, tokens, cache use, latency, cost, attestation, worktree isolation, and drift.

`check_live_model_migration.py` runs dry mode and asserts:

- GPT-5.5 appears only as migration evidence;
- runtime model policy is never imported from the migration matrix;
- Sol current-prompt and Sol v3-prompt treatments remain separate;
- a release-pass result requires zero critical regressions, no task-success regression, 100% core attestation, and at least 25% context-token reduction for Sol v3.

- [ ] **Step 6: Run deterministic GREEN**

```bash
cd skills/kws-codex-plan-executor
python3 evals/check_execution.py --help
python3 evals/check_fault_injection.py
python3 evals/check_live_model_migration.py
python3 evals/live_model_migration.py --dry-run --budget-usd 50 --output /tmp/cpe-v3-live-plan.json
./evals/run.sh
```

Expected: deterministic suite passes and dry-run makes no provider call.

- [ ] **Step 7: Paid live gate with explicit session approval**

Before running, present the generated `/tmp/cpe-v3-live-plan.json`, treatment count, case count, and `$50.00` cap to the user. After explicit approval in the execution session, run:

```bash
cd skills/kws-codex-plan-executor
python3 evals/live_model_migration.py \
  --confirm-live-cost \
  --budget-usd 50 \
  --output /tmp/cpe-v3-live-report.json
```

Expected: `release_gate.passed=true`. If credentials, attestation, budget, or quality gates fail, keep release status blocked and preserve the report as external release evidence; do not weaken thresholds.

- [ ] **Step 8: Commit T11**

```bash
git add skills/kws-codex-plan-executor/evals
git commit -m "test(cpe): gate v3 with replay and model migration evals"
```

---

### Task 12: Remove Superseded V2 Surfaces And Close The 3.0.0 Release

```yaml
id: T12
title: Public contract, documentation, cleanup, release baseline, and Graphify
owner_boundary: Package contract and release closeout
files:
  - path: skills/kws-codex-plan-executor/SKILL.md
    mode: edit
  - path: skills/kws-codex-plan-executor/README.md
    mode: edit
  - path: skills/kws-codex-plan-executor/ARCHITECTURE.md
    mode: edit
  - path: skills/kws-codex-plan-executor/HISTORY.md
    mode: edit
  - path: skills/kws-codex-plan-executor/agents/openai.yaml
    mode: edit
  - path: skills/kws-codex-plan-executor/references
    mode: edit
  - path: skills/kws-codex-plan-executor/docs
    mode: edit
  - path: skills/kws-codex-plan-executor/scripts/cpe_state_validation
    mode: delete
  - path: skills/kws-codex-plan-executor/scripts/run_quality_debt.py
    mode: delete
  - path: skills/kws-codex-plan-executor/scripts/append_trajectory_event.py
    mode: delete
  - path: skills/kws-codex-plan-executor/scripts/update_progress_ledger.py
    mode: delete
  - path: skills/kws-codex-plan-executor/scripts/update_decisions_register.py
    mode: delete
  - path: skills/kws-codex-plan-executor/scripts/record_cache_observation.py
    mode: delete
  - path: skills/kws-codex-plan-executor/scripts/classify_recovery.py
    mode: delete
  - path: skills/kws-codex-plan-executor/evals/baselines
    mode: edit
  - path: graphify-out/GRAPH_REPORT.md
    mode: edit
  - path: graphify-out/graph.json
    mode: edit
acceptance:
  - command: cd skills/kws-codex-plan-executor && ./evals/run.sh
    expected: complete deterministic v3 suite and v3.0.0 baseline pass
  - command: cd skills/kws-codex-plan-executor && python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
    expected: exit 0
  - command: git diff --check
    expected: exit 0
risks:
  - Closing release metadata before live evidence passes would misrepresent readiness.
```

**Interfaces:**

- `SKILL.md metadata.version` is `3.0.0` and remains the version source of truth.
- The public skill routes execution through `scripts/cpe.py` and public inspection/recovery CLIs.
- Only `evals/baselines/v3.0.0.json` remains in the active baseline directory.

- [ ] **Step 1: Rewrite the public skill contract before deleting old helpers**

Reduce `SKILL.md` to v3 invocation, two-route invariant, worktree/run layout, task contract, explicit spec mapping, event authority, completion gates, and links to focused references. It must explicitly retain:

```text
run, resume, prompt, handoff, validate, reconcile, repair, inspect, recent-run inspection
```

It must explicitly reject v2 state as `unsupported_schema`, and it must not contain Spark, GPT-5.5, Luna, Opus, `xhigh`, `max`, Pro mode, model profiles, fallback lists, or model-selection hints as active behavior.

- [ ] **Step 2: Update architecture, operator, maintainer, and state docs**

Update at least:

- `README.md` and `ARCHITECTURE.md`;
- `references/state-schema.md`, `event-journal.md`, `execution-cycle.md`, `mode-contracts.md`, `headless-runner.md`, `prompt-export-checklist.md`, `drift-reconciliation.md`, `subagent-run-store.md`, `cache-strategy.md`, and `change-protocol.md`;
- `docs/how-it-works.md`, `state-and-logging.md`, `evals-and-verification.md`, `eval-coverage-cpe.md`, `risks-limitations-deferrals.md`, `future-agent-guide.md`, `user-guide.ko.md`, and `mental-model.ko.md`.

Update `agents/openai.yaml` so the default prompt describes the v3 run/export CLI without legacy defaults.

- [ ] **Step 3: Delete superseded runtime helpers and their obsolete evals**

After consumer parity is green, delete the paths listed in this task plus obsolete checks that exist only for trajectory/progress/cache mutable-state helpers:

```bash
git rm -r skills/kws-codex-plan-executor/scripts/cpe_state_validation
git rm skills/kws-codex-plan-executor/scripts/run_quality_debt.py \
  skills/kws-codex-plan-executor/scripts/append_trajectory_event.py \
  skills/kws-codex-plan-executor/scripts/update_progress_ledger.py \
  skills/kws-codex-plan-executor/scripts/update_decisions_register.py \
  skills/kws-codex-plan-executor/scripts/record_cache_observation.py \
  skills/kws-codex-plan-executor/scripts/classify_recovery.py \
  skills/kws-codex-plan-executor/evals/check_trajectory_projection.py \
  skills/kws-codex-plan-executor/evals/check_progress_ledger.py \
  skills/kws-codex-plan-executor/evals/check_cache_observations.py
```

Remove these checks from `evals/run.sh`. Do not delete validator, reconciliation, repair, inspection, recent-run analysis, prompt, or handoff entry points.

- [ ] **Step 4: Close release metadata only after live evidence passes**

Set `SKILL.md` version to `3.0.0`. Move all applicable Unreleased entries into `## 3.0.0 - 2026-07-10` in `HISTORY.md`. Delete `evals/baselines/v2*.json` and `v2*.json.partial`; keep historical release facts in Git history and `HISTORY.md`.

Run the intentional baseline update only after reviewing generated fixture output:

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh --update-baseline
git diff -- evals/baselines/v3.0.0.json
./evals/run.sh
```

Expected: exactly one current baseline, `v3.0.0.json`, and all fixture entries pass.

- [ ] **Step 5: Append verification history**

Append a compact `2026-07-10 Asia/Seoul` entry to `docs/verification-log.md` with branch, scope, every final command, exit status, live report result, skipped checks if any, and residual risk. Do not paste transcripts or secrets.

- [ ] **Step 6: Run full package and repository verification**

```bash
cd skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py
bash -n evals/run.sh
python3 evals/check_release_contract.py
python3 evals/check_model_surface.py
cd /Users/kws/source/private/Archive
git diff --check
```

Expected: every command exits `0` and the release contract reports version `3.0.0` with a matching baseline and history section.

- [ ] **Step 7: Refresh Graphify and verify freshness**

```bash
cd /Users/kws/source/private/Archive
graphify update .
python3 skills/kws-codex-plan-executor/scripts/check_graphify_freshness.py --repo-root . --update-ran
```

Expected: `fresh=true`. Move Graphify's dated backup out of the repository before staging; stage only tracked current graph outputs.

- [ ] **Step 8: Perform final code review and commit T12**

Use `/Users/kws/source/private/Archive/code_review.md` against the complete diff. Confirm there are no source-checkout mutations outside declared files, no model configuration branch beyond the two fixed routes, no v2 state interpretation, and no completion claim without fresh evidence.

```bash
git add -A -- . ':(exclude)**/.DS_Store'
git diff --cached --check
git status --short
git commit -m "feat(cpe): release deterministic v3 executor"
git status --short --branch --untracked-files=all
```

Expected: clean working tree, current branch contains all 12 task commits, and release evidence remains inspectable.

---

## Final Verification Matrix

| Area | Command | Required result |
| --- | --- | --- |
| Dependency preflight | `python3 evals/check_runtime_dependencies.py` | Exact PyYAML pin and actionable failure path pass |
| Fixed routing | `python3 evals/check_model_policy.py` | Exactly Sol/high and Terra/high |
| Active model surface | `python3 evals/check_model_surface.py` | No selectable legacy route/config |
| Manifest/evidence | `python3 evals/check_manifest_evidence.py` | Immutable hashes and tamper detection pass |
| Event kernel | `python3 evals/check_event_kernel.py` | Replay, crash recovery, and transition checks pass |
| Runtime | `python3 evals/check_execution_runtime.py` | Sequential writes, safe scouts, config unchanged |
| Validator | `python3 evals/check_state_schema.py` | V3 passes; v2 is unsupported and untouched |
| Consumer parity | `python3 evals/check_validation_consumer_parity.py` | Same error codes across consumers |
| Reconciliation | `python3 evals/check_state_reconciliation.py` | Ordered drift classification passes |
| Repair | `python3 evals/check_repair_runs.py` | Dry-run/default and explicit safe apply pass |
| Inspection | `python3 evals/check_inspect_runs.py` | Read-only projection passes |
| Recent runs | `python3 evals/check_recent_run_rubric.py` | Quality, usage, cost, latency metrics pass |
| Fault injection | `python3 evals/check_fault_injection.py` | All corruption/interruption cases classified |
| Superpowers | `python3 evals/check_superpowers_compatibility.py` | Semantic compatible fixtures pass |
| Full deterministic suite | `./evals/run.sh` | Exit `0`, matching `v3.0.0` baseline |
| Live migration | `python3 evals/live_model_migration.py --confirm-live-cost --budget-usd 50 --output /tmp/cpe-v3-live-report.json` | Release gate passes after explicit cost approval |
| Python syntax | `python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py` | Exit `0` |
| Bash syntax | `bash -n evals/run.sh` | Exit `0` |
| Graphify | `python3 scripts/check_graphify_freshness.py --repo-root ../.. --update-ran` | `fresh=true` |
| Patch hygiene | `git diff --check` | Exit `0` |

## Completion Conditions

Implementation is complete only when:

1. all 12 task commits exist and the complete diff has received final review;
2. deterministic, integration, fault-injection, and live migration gates pass;
3. every core attempt has Sol/high attestation and every Terra attempt satisfies the scout contract;
4. v2 state is reported only as `unsupported_schema` and remains byte-for-byte untouched;
5. validator, reconciliation, repair, completion, and inspection agree on replayed truth;
6. no active model override, profile, alias, fallback, Spark, Luna, Opus, `xhigh`, `max`, or Pro-mode branch remains;
7. prompt/handoff export contains the exact launcher plus prompt body and creates no run artifacts;
8. source checkout isolation and file-claim enforcement show zero accepted violations;
9. Sol v3 has no task-success regression against the GPT-5.5 migration baseline, zero critical regressions, and at least 25% context-token reduction;
10. release metadata, docs, verification log, current baseline, and Graphify all match `3.0.0`.
