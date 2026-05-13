# KWS Codex Plan Executor Learning Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development only when the user explicitly asks for subagents, delegation, parallel work, or `subagents=on`. Otherwise implement this plan in the current Codex session task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add execution-only, user-local JSONL learning logs to `kws-codex-plan-executor` so notable execution failures and improvement signals can drive future skill improvements.

**Architecture:** Add a deterministic helper script that validates, redacts, and appends one learning event per JSONL line under `~/.codex/learning/kws-codex-plan-executor/events.jsonl`. Keep per-run resume state in `.codex-orchestrator/state.json`; the learning log is a separate long-term skill-improvement signal used only by `interactive` and `headless` execution. Runtime docs, prompt export, contract evals, and release metadata must stay aligned.

**Tech Stack:** Codex skill Markdown, Python 3 standard library, JSONL, deterministic eval scripts, shell package tests, graphify.

---

## Source Documents

- Spec: `docs/superpowers/specs/2026-05-13-kws-codex-plan-executor-learning-log-design.md`
- Existing executor package: `ai/skills/kws-skills/package/kws-codex-plan-executor/`
- Change protocol: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/change-protocol.md`

## Scope And Non-Goals

In scope:

- Add `scripts/append_learning_event.py`.
- Add deterministic tests in `evals/check_learning_log.py`.
- Add `references/learning-log.md`.
- Update runtime instructions for `interactive` and `headless` notable-boundary logging.
- Update `templates/fresh-session-prompt.txt` so prompt-exported future execution sessions carry the same execution-only contract.
- Update deterministic contract checks.
- Update version metadata, changelog, README, architecture, history, common mistakes, and change protocol.
- Run `graphify update .` after code-file modifications.

Out of scope:

- Automatic skill self-modification.
- Repository-local learning logs.
- Full transcript capture.
- Logging for `prompt` and `handoff` generation itself.
- Cross-machine syncing.
- Global logging for every skill.

## File Structure

Create:

- `ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/append_learning_event.py` - validates, redacts, and appends learning events.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_learning_log.py` - deterministic helper behavior tests.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/learning-log.md` - schema, event triggers, privacy rules, and helper usage.

Modify:

- `ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md` - add execution-only learning log invariant and bump skill version to `1.3.0`.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/templates/fresh-session-prompt.txt` - carry the execution-mode learning-log contract into generated execution prompts.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/execution-cycle.md` - add notable-boundary helper calls.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/headless-runner.md` - document user-local log location and headless artifact separation.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/prompt-export-checklist.md` - add prompt/runtime learning-log alignment checks.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/change-protocol.md` - add helper eval to verification list.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/references/common-mistakes.md` - add learning-log drift/privacy mistakes.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/ARCHITECTURE.md` - record the learning-log architecture.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/HISTORY.md` - add `v1.3.0`.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_skill_contract.py` - require learning-log contract text.
- `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/run.sh` - run `check_learning_log.py` in deterministic preflight.
- `ai/skills/kws-skills/manifest.json` - bump package to `2.10.0` and executor skill to `1.3.0`.
- `ai/skills/kws-skills/README.md` - bump current versions.
- `ai/skills/kws-skills/CHANGELOG.md` - add `2.10.0`.

## Task 0: Preflight And Worktree State

**Files:**
- Read: `docs/superpowers/specs/2026-05-13-kws-codex-plan-executor-learning-log-design.md`
- Read: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/change-protocol.md`
- Read: `ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md`
- Read: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_skill_contract.py`

- [ ] **Step 1: Confirm working tree state**

Run:

```bash
git status --short
git branch --show-current
```

Expected: no unrelated dirty files. If dirty files exist, classify them before editing and do not overwrite unrelated user changes.

- [ ] **Step 2: Confirm current version targets**

Run:

```bash
python3 - <<'PY'
import json, re
from pathlib import Path
manifest = json.loads(Path("ai/skills/kws-skills/manifest.json").read_text())
skill = Path("ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md").read_text()
print("package", manifest["version"])
print("executor", re.search(r'(?m)^  version: "([^"]+)"', skill).group(1))
PY
```

Expected:

```text
package 2.9.1
executor 1.2.1
```

- [ ] **Step 3: Review the approved spec**

Run:

```bash
sed -n '1,340p' docs/superpowers/specs/2026-05-13-kws-codex-plan-executor-learning-log-design.md
```

Expected: spec states `execution-only`, `notable-boundaries`, `redacted-context`, and `schema + helper script`.

## Task 1: Add Failing Helper Eval

**Files:**
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_learning_log.py`

- [ ] **Step 1: Write the deterministic helper eval**

Create `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_learning_log.py`:

```python
#!/usr/bin/env python3
"""Deterministic checks for append_learning_event.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def base_event() -> dict:
    return {
        "schema_version": "1",
        "skill": "kws-codex-plan-executor",
        "skill_version": "1.3.0",
        "mode": "interactive",
        "event_type": "verification_failure",
        "severity": "medium",
        "repo": {"name": "Archive", "remote_hash": None, "branch": "codex/example"},
        "execution": {
            "plan_path": "docs/superpowers/plans/example.md",
            "task_id": "task_2",
            "phase": "verification",
            "state_path": ".codex-orchestrator/state.json",
        },
        "summary": "Acceptance command failed after the implementation touched validator code.",
        "context": {
            "user_intent": "Execute the approved implementation plan.",
            "agent_expectation": "Targeted verification would close the task.",
            "actual_outcome": "A broader Python check was required.",
            "root_cause": "The plan under-declared affected files.",
            "evidence": [{"kind": "command", "value": "python3 scripts/validate_state.py state.json"}],
        },
        "improvement": {
            "target": "references/execution-cycle.md",
            "proposal": "Require risk upgrade when implementation touches files outside the declared block.",
        },
        "privacy": {"redacted": True, "notes": "Home directory omitted."},
    }


def run_helper(script: Path, event: dict, log_path: Path, repo_root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    event_path = repo_root / "event.json"
    event_path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(script),
            "--event-json",
            str(event_path),
            "--log-path",
            str(log_path),
            "--repo-root",
            str(repo_root),
            *extra,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "scripts" / "append_learning_event.py"
    checks: dict[str, bool] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="codex-learning-log-") as temp:
        repo_root = Path(temp) / "repo"
        repo_root.mkdir()
        log_path = Path(temp) / "events.jsonl"

        valid = run_helper(script, base_event(), log_path, repo_root)
        checks["valid_event_appends"] = valid.returncode == 0 and log_path.is_file() and len(log_path.read_text().splitlines()) == 1
        if not checks["valid_event_appends"]:
            failures.append("valid event should append one JSONL line")

        appended = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0]) if log_path.is_file() else {}
        checks["event_id_added"] = isinstance(appended.get("event_id"), str) and len(appended.get("event_id", "")) >= 12
        if not checks["event_id_added"]:
            failures.append("appended event should include event_id")

        dry_log = Path(temp) / "dry.jsonl"
        dry = run_helper(script, base_event(), dry_log, repo_root, "--dry-run")
        checks["dry_run_no_write"] = dry.returncode == 0 and not dry_log.exists() and '"event_id"' in dry.stdout
        if not checks["dry_run_no_write"]:
            failures.append("dry-run should validate and print sanitized event without writing")

        missing = base_event()
        del missing["summary"]
        missing_result = run_helper(script, missing, Path(temp) / "missing.jsonl", repo_root)
        checks["missing_required_field_fails"] = missing_result.returncode != 0 and "summary" in (missing_result.stderr + missing_result.stdout)
        if not checks["missing_required_field_fails"]:
            failures.append("missing summary should fail")

        invalid_mode = base_event()
        invalid_mode["mode"] = "prompt"
        invalid_mode_result = run_helper(script, invalid_mode, Path(temp) / "invalid-mode.jsonl", repo_root)
        checks["invalid_mode_fails"] = invalid_mode_result.returncode != 0 and "mode" in (
            invalid_mode_result.stderr + invalid_mode_result.stdout
        )
        if not checks["invalid_mode_fails"]:
            failures.append("prompt mode should fail for learning events")

        home_path = base_event()
        home_path["context"]["evidence"] = [{"kind": "relative_path", "value": str(Path.home() / "secret.txt")}]
        home_result = run_helper(script, home_path, Path(temp) / "home.jsonl", repo_root)
        checks["home_path_rejected"] = home_result.returncode != 0 and "home path" in (home_result.stderr + home_result.stdout)
        if not checks["home_path_rejected"]:
            failures.append("absolute home path should be rejected")

        secret = base_event()
        secret["context"]["evidence"] = [{"kind": "excerpt", "value": "Authorization: Bearer abc123"}]
        secret_result = run_helper(script, secret, Path(temp) / "secret.jsonl", repo_root)
        checks["secret_like_value_rejected"] = secret_result.returncode != 0 and "secret-like" in (
            secret_result.stderr + secret_result.stdout
        )
        if not checks["secret_like_value_rejected"]:
            failures.append("secret-like values should be rejected")

    payload = {"passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the eval and confirm it fails before implementation**

Run:

```bash
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_learning_log.py
```

Expected: FAIL because `scripts/append_learning_event.py` does not exist.

- [ ] **Step 3: Commit the failing eval**

Run:

```bash
git add ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_learning_log.py
git commit -m "test: add executor learning log eval"
```

Expected: commit succeeds with only `check_learning_log.py` staged.

## Task 2: Implement Learning Event Helper

**Files:**
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/append_learning_event.py`
- Test: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_learning_log.py`

- [ ] **Step 1: Write the helper script**

Create `ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/append_learning_event.py`:

```python
#!/usr/bin/env python3
"""Append a redacted kws-codex-plan-executor learning event to user-local JSONL."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = Path("~/.codex/learning/kws-codex-plan-executor/events.jsonl").expanduser()
VALID_MODES = {"interactive", "headless"}
VALID_EVENT_TYPES = {
    "blocker",
    "error",
    "verification_failure",
    "recurring_issue",
    "user_correction",
    "successful_workaround",
    "completion_learning",
}
VALID_SEVERITIES = {"low", "medium", "high"}
REQUIRED_FIELDS = {
    "schema_version",
    "skill",
    "skill_version",
    "mode",
    "event_type",
    "severity",
    "repo",
    "execution",
    "summary",
    "context",
    "improvement",
    "privacy",
}
SECRET_PATTERNS = [
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|cookie|private[_-]?key)\b\s*[:=]"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
]


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def contains_secret_like_value(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def relativize_path_string(value: str, repo_root: Path | None) -> str:
    if not value:
        return value
    expanded_home = str(Path.home())
    if value == expanded_home or value.startswith(expanded_home + os.sep):
        die("home path is not allowed in learning events")
    if repo_root is not None:
        try:
            candidate = Path(value).expanduser()
            if candidate.is_absolute():
                resolved = candidate.resolve(strict=False)
                rel = resolved.relative_to(repo_root)
                return rel.as_posix()
        except ValueError:
            return value
    return value


def sanitize(value: Any, repo_root: Path | None) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize(item, repo_root) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item, repo_root) for item in value]
    if isinstance(value, str):
        if contains_secret_like_value(value):
            die("secret-like value is not allowed in learning events")
        return relativize_path_string(value, repo_root)
    return value


def require_object(data: Any, field: str) -> dict:
    item = data.get(field)
    if not isinstance(item, dict):
        die(f"{field} must be an object")
    return item


def validate_event(data: dict) -> None:
    missing = sorted(REQUIRED_FIELDS - set(data))
    if missing:
        die("missing required field(s): " + ", ".join(missing))
    if data.get("schema_version") != "1":
        die("schema_version must be 1")
    if data.get("skill") != "kws-codex-plan-executor":
        die("skill must be kws-codex-plan-executor")
    if data.get("mode") not in VALID_MODES:
        die("mode must be one of: " + ", ".join(sorted(VALID_MODES)))
    if data.get("event_type") not in VALID_EVENT_TYPES:
        die("event_type must be one of: " + ", ".join(sorted(VALID_EVENT_TYPES)))
    if data.get("severity") not in VALID_SEVERITIES:
        die("severity must be one of: " + ", ".join(sorted(VALID_SEVERITIES)))
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        die("summary must be a non-empty string")
    if len(data["summary"]) > 500:
        die("summary must be 500 characters or less")
    require_object(data, "repo")
    require_object(data, "execution")
    require_object(data, "context")
    require_object(data, "improvement")
    privacy = require_object(data, "privacy")
    if privacy.get("redacted") is not True:
        die("privacy.redacted must be true")


def add_event_id(data: dict) -> dict:
    basis = "|".join(
        [
            str(data.get("timestamp", "")),
            str((data.get("repo") or {}).get("name", "")),
            str(data.get("event_type", "")),
            str((data.get("execution") or {}).get("task_id", "")),
            str(data.get("summary", "")),
        ]
    )
    data["event_id"] = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return data


def load_event(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"event file not found: {path}")
    except json.JSONDecodeError as exc:
        die(f"event JSON is invalid: {exc}")
    if not isinstance(data, dict):
        die("event JSON root must be an object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-json", required=True, help="Path to candidate learning event JSON")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH), help="JSONL log path")
    parser.add_argument("--repo-root", help="Repository root used to relativize absolute paths")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print sanitized event without appending")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve(strict=False) if args.repo_root else None
    event = sanitize(load_event(Path(args.event_json).expanduser()), repo_root)
    event.setdefault("timestamp", utc_now())
    validate_event(event)
    event = add_event_id(event)

    line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if args.dry_run:
        print(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    log_path = Path(args.log_path).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(f"appended learning event {event['event_id']} to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the helper eval**

Run:

```bash
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_learning_log.py
```

Expected: PASS with JSON output containing `"passed": true`.

- [ ] **Step 3: Confirm helper CLI help**

Run:

```bash
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/append_learning_event.py --help
```

Expected: exit 0 and output includes `--event-json`, `--log-path`, `--repo-root`, and `--dry-run`.

- [ ] **Step 4: Commit the helper**

Run:

```bash
git add ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/append_learning_event.py
git commit -m "feat: add executor learning event helper"
```

Expected: commit succeeds with only the helper script staged.

## Task 3: Add Failing Contract Checks

**Files:**
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_skill_contract.py`
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/run.sh`
- Test: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_skill_contract.py`

- [ ] **Step 1: Extend `check_skill_contract.py`**

In `main()`, after `common_mistakes_path`, add:

```python
    learning_path = skill_dir / "references" / "learning-log.md"
    learning_script_path = skill_dir / "scripts" / "append_learning_event.py"
```

After reading `common_mistakes_path`, add:

```python
    learning = learning_path.read_text(encoding="utf-8") if learning_path.is_file() else ""
```

Inside the `expectations` dictionary, add these entries:

```python
        "learning_log_reference_exists": learning_path.is_file(),
        "learning_log_helper_exists": learning_script_path.is_file(),
        "learning_log_execution_only": "execution-only" in text
        and "interactive" in learning
        and "headless" in learning
        and "prompt" in learning
        and "handoff" in learning
        and "not logging modes" in learning,
        "learning_log_user_local_path": "~/.codex/learning/kws-codex-plan-executor/events.jsonl" in learning
        and "~/.codex/learning/kws-codex-plan-executor/events.jsonl" in template,
        "learning_log_notable_boundaries": all(
            token in learning
            for token in (
                "blocker",
                "error",
                "verification_failure",
                "recurring_issue",
                "user_correction",
                "successful_workaround",
                "completion_learning",
            )
        ),
        "learning_log_privacy_guard": all(
            token in learning
            for token in ("redacted-context", "Do not store full conversation transcripts", "Do not store secrets")
        ),
```

- [ ] **Step 2: Add helper eval to `evals/run.sh`**

After this line:

```bash
python3 "$EVAL_DIR/check_state_schema.py" >/dev/null
```

Add:

```bash
python3 "$EVAL_DIR/check_learning_log.py" >/dev/null
```

- [ ] **Step 3: Run contract check and confirm it fails before docs are added**

Run:

```bash
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_skill_contract.py \
  --skill ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md
```

Expected: FAIL with missing learning-log expectations, including `learning_log_reference_exists` and `learning_log_user_local_path`.

- [ ] **Step 4: Commit the failing contract checks**

Run:

```bash
git add \
  ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_skill_contract.py \
  ai/skills/kws-skills/package/kws-codex-plan-executor/evals/run.sh
git commit -m "test: require executor learning log contract"
```

Expected: commit succeeds with only the eval files staged.

## Task 4: Add Runtime Learning Log Contract

**Files:**
- Create: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/learning-log.md`
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md`
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/templates/fresh-session-prompt.txt`
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/headless-runner.md`
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/prompt-export-checklist.md`
- Test: `ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_skill_contract.py`

- [ ] **Step 1: Create `references/learning-log.md`**

Create `ai/skills/kws-skills/package/kws-codex-plan-executor/references/learning-log.md`:

```markdown
# Learning Log

Use this for execution-only learning events from `interactive` and `headless`
mode. `prompt` and `handoff` are not logging modes, although prompts exported
for future execution must carry this same contract.

The log is user-local:

```text
~/.codex/learning/kws-codex-plan-executor/events.jsonl
```

This log is for improving `kws-codex-plan-executor` across repositories. It is
not the resume source of truth for a single run. Keep `.codex-orchestrator/state.json`
as the per-run state file.

## Event Types

Record only notable boundaries:

- `blocker`: plan, path, dirty worktree, resume ambiguity, or unclear scope stops execution.
- `error`: executor procedure fails independently of project code.
- `verification_failure`: test, lint, build, or acceptance command fails.
- `recurring_issue`: the same `ISSUE_KEY` appears again.
- `user_correction`: the user corrects executor scope, assumptions, allowed files, or direction.
- `successful_workaround`: a root-cause-based recovery reveals a reusable improvement.
- `completion_learning`: final completion reveals an actionable executor improvement.

Do not record routine task starts, routine task completions, or ordinary success
with no executor improvement.

## Redacted-Context Rule

Store enough context for a future agent to improve the skill without reading
the original conversation. Do not store sensitive or bulky source material.

Allowed:

- repository name
- branch name
- relative plan path
- task id and phase
- relative file paths
- command names and arguments that do not expose secrets
- short failure excerpt
- root-cause summary
- proposed skill improvement target

Do not store secrets, tokens, API keys, cookies, credentials, private keys, or
authorization headers. Do not store full conversation transcripts. Do not store
long raw logs. Do not store absolute home paths such as `/Users/<name>/<redacted>`.
Do not store large file contents, unrelated user files, or unrelated process details.

If a field cannot be safely summarized, omit the field or replace it with a
short redacted summary before calling the helper.

## Helper

Create an event candidate JSON file and run:

```bash
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/append_learning_event.py \
  --event-json /tmp/kws-codex-plan-executor-event.json \
  --repo-root "$WORKTREE_ABS"
```

For tests, pass `--log-path <temp-events.jsonl>`. For preflight validation,
pass `--dry-run`.

The helper validates required fields, enum values, redaction constraints, and
secret-like strings before appending one compact JSON object per line.

## Minimal Event Shape

```json
{
  "schema_version": "1",
  "skill": "kws-codex-plan-executor",
  "skill_version": "1.3.0",
  "mode": "interactive",
  "event_type": "verification_failure",
  "severity": "medium",
  "repo": {"name": "Archive", "remote_hash": null, "branch": "codex/example"},
  "execution": {
    "plan_path": "docs/superpowers/plans/example.md",
    "task_id": "task_2",
    "phase": "verification",
    "state_path": ".codex-orchestrator/state.json"
  },
  "summary": "Acceptance command failed after the implementation touched validator code.",
  "context": {
    "user_intent": "Execute the approved implementation plan.",
    "agent_expectation": "Targeted verification would close the task.",
    "actual_outcome": "A broader Python check was required.",
    "root_cause": "The plan under-declared affected files.",
    "evidence": [{"kind": "command", "value": "python3 scripts/validate_state.py state.json"}]
  },
  "improvement": {
    "target": "references/execution-cycle.md",
    "proposal": "Require risk upgrade when implementation touches files outside the declared block."
  },
  "privacy": {"redacted": true, "notes": "Home directory omitted."}
}
```

## Failure Policy

Learning-log failure must not fail the user's primary implementation task. If
the helper fails, mention the logging failure briefly in the checkpoint or final
summary and continue according to the original executor state. Do not weaken the
original blocker, verification, or retry rules.
```

- [ ] **Step 2: Update `SKILL.md` core invariant and workflow**

In `SKILL.md`, add this bullet under `## Core Invariants` after the resume-mode bullet:

```markdown
- In `interactive` and `headless` execution, record redacted notable-boundary
  learning events with `scripts/append_learning_event.py` and
  `references/learning-log.md`; `prompt` and `handoff` are not logging modes.
```

In `## Workflow`, change the validation step list by inserting this item before validation:

```markdown
7. For execution modes, record learning events at notable boundaries using
   `references/learning-log.md`.
8. Validate using scripts before claiming completion.
```

- [ ] **Step 3: Update `execution-cycle.md`**

After the preflight dirty-file classification bullet list, add:

```markdown
- For `blocker` outcomes such as unreadable plans, ambiguous resume state,
  related dirty task files, or unclear mid/high-risk acceptance criteria, write
  a redacted learning event using `references/learning-log.md` and
  `scripts/append_learning_event.py`.
```

In `## Review And Retry`, after the recurring issue key rule, add:

```markdown
- Record a `verification_failure` event after raw output is preserved.
- Record a `recurring_issue` event when the same `ISSUE_KEY` appears again.
- Record a `user_correction` event when user feedback changes scope, allowed
  files, or assumptions.
- Record a `successful_workaround` event when a root-cause-based recovery
  exposes a reusable executor improvement.
```

In `## Phase 2: Finish`, add:

```markdown
- Record `completion_learning` only when final completion reveals an actionable
  improvement for this executor. Do not log routine successful completions.
```

- [ ] **Step 4: Update `headless-runner.md`**

After `## Required Artifacts`, add:

```markdown
## Learning Log

Headless artifacts remain under `.codex-orchestrator/`. Learning events are
separate user-local records written to:

```text
~/.codex/learning/kws-codex-plan-executor/events.jsonl
```

Use `references/learning-log.md` and `scripts/append_learning_event.py` for
`blocker`, `error`, `verification_failure`, `recurring_issue`,
`successful_workaround`, and actionable `completion_learning` events. `prompt`
and `handoff` are not logging modes.
```

- [ ] **Step 5: Update `templates/fresh-session-prompt.txt`**

After the `.codex-orchestrator/state.json` bullet, add this Korean contract:

```text
- `interactive`와 `headless` 실행 중 notable boundary가 발생하면 user-local learning log에 redacted-context JSONL 이벤트를 남겨. 저장 위치는 `~/.codex/learning/kws-codex-plan-executor/events.jsonl`이고, helper는 `ai/skills/kws-skills/package/kws-codex-plan-executor/scripts/append_learning_event.py`다. 기록 대상은 `blocker`, `error`, `verification_failure`, `recurring_issue`, `user_correction`, `successful_workaround`, actionable `completion_learning`이다. `prompt`와 `handoff` 생성 자체는 logging mode가 아니다. secrets, 전체 대화 transcript, 긴 raw log, 절대 home path는 저장하지 마.
```

- [ ] **Step 6: Update `prompt-export-checklist.md`**

Under `## Execution Invariants`, add:

```markdown
- execution-only learning-log contract is explicit: `interactive` and
  `headless` record redacted notable-boundary events to
  `~/.codex/learning/kws-codex-plan-executor/events.jsonl`; `prompt` and
  `handoff` are not logging modes
- generated prompts include privacy rules forbidding secrets, full transcripts,
  long raw logs, and absolute home paths in learning events
```

- [ ] **Step 7: Run contract and helper checks**

Run:

```bash
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_learning_log.py
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_skill_contract.py \
  --skill ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md
```

Expected: both commands pass and print JSON with `"passed": true`.

- [ ] **Step 8: Commit runtime contract changes**

Run:

```bash
git add \
  ai/skills/kws-skills/package/kws-codex-plan-executor/references/learning-log.md \
  ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md \
  ai/skills/kws-skills/package/kws-codex-plan-executor/templates/fresh-session-prompt.txt \
  ai/skills/kws-skills/package/kws-codex-plan-executor/references/execution-cycle.md \
  ai/skills/kws-skills/package/kws-codex-plan-executor/references/headless-runner.md \
  ai/skills/kws-skills/package/kws-codex-plan-executor/references/prompt-export-checklist.md
git commit -m "feat: document executor learning log contract"
```

Expected: commit succeeds with only runtime contract files staged.

## Task 5: Update Release Metadata And Maintenance Docs

**Files:**
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md`
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/ARCHITECTURE.md`
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/HISTORY.md`
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/change-protocol.md`
- Modify: `ai/skills/kws-skills/package/kws-codex-plan-executor/references/common-mistakes.md`
- Modify: `ai/skills/kws-skills/manifest.json`
- Modify: `ai/skills/kws-skills/README.md`
- Modify: `ai/skills/kws-skills/CHANGELOG.md`
- Test: `ai/skills/kws-skills/tests/test-sync.sh`

- [ ] **Step 1: Bump executor skill metadata**

In `ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md`, change:

```yaml
  version: "1.2.1"
```

to:

```yaml
  version: "1.3.0"
```

Keep:

```yaml
  updated_at: "2026-05-13"
```

- [ ] **Step 2: Update `HISTORY.md`**

Add this entry above `v1.2.1`:

```markdown
## v1.3.0 - Add execution learning log helper (2026-05-13)

- Added user-local JSONL learning events for `interactive` and `headless`
  execution notable boundaries.
- Added `scripts/append_learning_event.py` to validate, redact, and append
  learning events outside project repositories.
- Added `references/learning-log.md` and deterministic helper checks.
- Aligned runtime instructions, headless docs, prompt export, and contract evals
  around execution-only learning logs.
```

- [ ] **Step 3: Update `ARCHITECTURE.md`**

After `## State File Contract`, add:

```markdown
## Learning Log Contract

Execution modes may append redacted notable-boundary events to the user-local
JSONL log at `~/.codex/learning/kws-codex-plan-executor/events.jsonl`. This log
is for improving the executor across repositories. It does not replace
`.codex-orchestrator/state.json`, checkpoints, headless logs, or raw
verification artifacts.
```

Under `## Eval Surface`, add:

```markdown
- `evals/check_learning_log.py`
```

- [ ] **Step 4: Update `change-protocol.md` verification list**

Add this command after `python3 evals/check_state_schema.py`:

```bash
python3 evals/check_learning_log.py
```

- [ ] **Step 5: Update `common-mistakes.md`**

Add these bullets:

```markdown
- Do not let prompt export drift from execution-mode learning-log policy.
  Prompt and handoff generation do not log events themselves, but generated
  execution prompts must carry the same execution-only contract.
- Do not put learning events in the target repository. Use the user-local
  `~/.codex/learning/kws-codex-plan-executor/events.jsonl` path.
- Do not store secrets, full transcripts, long raw logs, or absolute home paths
  in learning events.
```

- [ ] **Step 6: Update package manifest**

In `ai/skills/kws-skills/manifest.json`, change package version:

```json
"version": "2.10.0"
```

Change the executor skill version:

```json
"kws-codex-plan-executor": {
  "version": "1.3.0",
  "updated_at": "2026-05-13"
}
```

- [ ] **Step 7: Update README current version table**

In `ai/skills/kws-skills/README.md`, change:

```markdown
- 패키지 버전: `2.10.0`
```

and change the executor row to:

```markdown
| `kws-codex-plan-executor` | `1.3.0` | `2026-05-13` |
```

- [ ] **Step 8: Update package changelog**

Add this entry above `2.9.1` in `ai/skills/kws-skills/CHANGELOG.md`:

```markdown
## 2.10.0 - 2026-05-13

- `kws-codex-plan-executor`에 execution-only user-local learning log를 추가했습니다.
- `interactive`와 `headless` 실행 중 blocker, verification failure, recurring issue, user correction, successful workaround, actionable completion learning을 redacted JSONL로 기록할 수 있게 했습니다.
- `append_learning_event.py`, `references/learning-log.md`, `check_learning_log.py`를 추가해 로그 schema와 privacy guard를 deterministic하게 검증합니다.
- prompt export와 headless 문서가 새 learning-log 계약과 drift 나지 않도록 contract eval을 보강했습니다.
```

- [ ] **Step 9: Run metadata and sync checks**

Run:

```bash
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_learning_log.py
python3 ai/skills/kws-skills/package/kws-codex-plan-executor/evals/check_skill_contract.py \
  --skill ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md
sh ai/skills/kws-skills/tests/test-sync.sh
```

Expected: all commands exit 0.

- [ ] **Step 10: Commit release metadata**

Run:

```bash
git add \
  ai/skills/kws-skills/package/kws-codex-plan-executor/SKILL.md \
  ai/skills/kws-skills/package/kws-codex-plan-executor/ARCHITECTURE.md \
  ai/skills/kws-skills/package/kws-codex-plan-executor/HISTORY.md \
  ai/skills/kws-skills/package/kws-codex-plan-executor/references/change-protocol.md \
  ai/skills/kws-skills/package/kws-codex-plan-executor/references/common-mistakes.md \
  ai/skills/kws-skills/manifest.json \
  ai/skills/kws-skills/README.md \
  ai/skills/kws-skills/CHANGELOG.md
git commit -m "chore: release executor learning log support"
```

Expected: commit succeeds with only metadata and maintenance docs staged.

## Task 6: Final Verification And Graph Update

**Files:**
- Read: all changed files
- Generated/updated: `graphify-out/`

- [ ] **Step 1: Run executor package checks**

Run:

```bash
cd ai/skills/kws-skills/package/kws-codex-plan-executor
python3 scripts/parse_plan.py --help
python3 scripts/validate_state.py --help
python3 scripts/append_learning_event.py --help
python3 evals/check_prompt.py --help
python3 evals/check_execution.py --help
python3 evals/check_parse_plan.py --help
python3 evals/check_state_schema.py
python3 evals/check_learning_log.py
python3 evals/check_skill_contract.py --skill SKILL.md
python3 /Users/kws/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
cd /Users/kws/source/private/Archive
sh ai/skills/kws-skills/tests/test-sync.sh
```

Expected: every command exits 0. `check_state_schema.py`, `check_learning_log.py`, and `check_skill_contract.py` print JSON or success output showing passing checks.

- [ ] **Step 2: Inspect final diff**

Run:

```bash
git status --short
git diff --stat HEAD
git diff --check
```

Expected: no whitespace errors. Dirty files should be only intentional uncommitted changes if a prior commit step was intentionally deferred.

- [ ] **Step 3: Update graphify after code changes**

Run:

```bash
graphify update .
```

Expected: command exits 0 and refreshes `graphify-out/` after code-file changes.

- [ ] **Step 4: Commit graph updates if graphify changed generated files**

Run:

```bash
git status --short graphify-out
```

If graphify changed files, run:

```bash
git add graphify-out
git commit -m "chore: update graph after executor learning log changes"
```

Expected: commit succeeds only if graph files changed. If no graph files changed, no commit is needed.

- [ ] **Step 5: Final summary**

Summarize:

```text
changed_files:
- helper script
- helper eval
- learning-log reference
- runtime and prompt contracts
- release metadata

verification:
- helper CLI help
- helper eval
- state schema eval
- skill contract eval
- package sync test
- skill quick validation
- graphify update

residual_risk:
- learning event quality still depends on the executor constructing a concise event candidate
- no aggregation/reporting tool yet
```

Expected: final summary states that logging failures do not block the primary execution task and that `prompt`/`handoff` generation itself does not log events.

## Plan Self-Review

Spec coverage:

- `execution-only`: Task 4 updates runtime docs, prompt template, and contract checks.
- `notable-boundaries`: Task 4 documents each event type and Task 3 enforces them in contract checks.
- `redacted-context`: Task 2 helper rejects home paths and secret-like values; Task 4 documents privacy rules.
- `schema + helper script`: Task 1 and Task 2 add deterministic eval and helper.
- prompt/headless alignment: Task 4 updates template, checklist, and headless runner.
- release metadata: Task 5 updates skill/package versions and docs.
- graph freshness: Task 6 runs `graphify update .`.

Placeholder scan:

- No placeholder tokens, unfinished sections, or missing commands are intentionally left in this plan.

Type consistency:

- Helper path is consistently `scripts/append_learning_event.py`.
- Eval path is consistently `evals/check_learning_log.py`.
- Log path is consistently `~/.codex/learning/kws-codex-plan-executor/events.jsonl`.
- New skill version is consistently `1.3.0`.
- New package version is consistently `2.10.0`.
