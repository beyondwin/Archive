# CPE Current Superpowers Plan Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve `kws-codex-plan-executor` so it only executes current Superpowers-compatible plans, reports real blocker reasons, and never auto-supports legacy plan shapes.

**Architecture:** Keep Superpowers as an external contract and change only CPE internals. `audit_plan_executability.py` becomes the CPE-side gate that reads parsed plan JSON plus raw plan text, classifies current/unsupported/operator-review/fixable shapes, and prioritizes real blocking reasons before task contracts or edits.

**Tech Stack:** Python 3 standard library, Markdown contract docs, existing CPE deterministic eval harness, Graphify.

## Global Constraints

- Do not modify `/Users/kws/.codex/skills` or any Superpowers skill implementation.
- Do not auto-normalize or execute legacy plan shapes.
- Do not weaken worktree isolation, task contracts, TDD, completion audit, Graphify, or state validation gates.
- Preserve existing user changes. At plan creation time these files were already dirty: `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`, `skills/kws-codex-plan-executor/README.md`, `skills/kws-codex-plan-executor/docs/verification-log.md`, and `skills/kws-codex-plan-executor/docs/mental-model.ko.md`.
- Use `apply_patch` for manual edits and stage only the files intentionally changed by each task.
- This is a CPE patch release: use version `2.25.1`.

---

## File Structure

- Modify `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py` to add deterministic regression cases for current Superpowers headers, unsupported plan shape, operator-review risk, and blocker reason priority.
- Modify `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py` to read raw plan text, classify plan support, and make `block` reasons come from real blocking issues.
- Modify `skills/kws-codex-plan-executor/evals/check_skill_contract.py` to lock the CPE-only external Superpowers boundary and legacy-plan non-support contract.
- Modify `skills/kws-codex-plan-executor/SKILL.md`, `README.md`, `references/execution-cycle.md`, `references/state-schema.md`, `docs/user-guide.ko.md`, and `docs/evals-and-verification.md` to document the current-plan gate.
- Modify `skills/kws-codex-plan-executor/HISTORY.md`, `SKILL.md` metadata, `evals/baselines/v2.25.1.json`, and `docs/verification-log.md` for release alignment.
- Update `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json` only by running `graphify update .` after the code/docs change.

---

### Task 1: Implement Plan Audit Classification And Blocker Reason Priority

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`
- Modify: `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py`

**Interfaces:**
- Consumes: parsed plan JSON with `plan`, `mode`, and `tasks`.
- Produces: audit JSON with existing fields plus `plan_support` at payload, summary, and task levels.
- Produces: `subagent_fit=block` with `subagent_reason` equal to the highest-priority real blocking issue.

- [ ] **Step 1: Add failing eval fixture helpers**

In `skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py`, replace `write_plan_json` with this implementation and add the two helper functions above it:

````python
CURRENT_PLAN_MARKDOWN = """# Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exercise the CPE plan executability audit.

**Architecture:** The fixture keeps raw plan text current enough for the CPE gate while parsed JSON drives the individual task cases.

**Tech Stack:** Python 3 standard library.

## Global Constraints

- Keep fixture edits scoped to the temporary repository.

---

### Task 1: Fixture Task

**Files:**
- Modify: `src/app.py`

```bash
python3 -m pytest
````
"""


def legacy_plan_markdown() -> str:
    return """# Legacy Fixture Plan

> **For agentic workers:** Implement task-by-task. Keep edits scoped.

### Task 1: Legacy Task

**Files:**
- Modify: `src/app.py`

```bash
python3 -m pytest
```
"""


def write_plan_json(path: Path, tasks: list[dict], *, plan_markdown: str | None = None) -> None:
    markdown_path = path.with_suffix(".md")
    markdown_path.write_text(plan_markdown if plan_markdown is not None else CURRENT_PLAN_MARKDOWN, encoding="utf-8")
    path.write_text(
        json.dumps({"plan": str(markdown_path), "mode": "interactive", "tasks": tasks}, indent=2),
        encoding="utf-8",
    )
```

- [ ] **Step 2: Add failing eval cases**

In the same file, insert these cases in `main()` after the existing `red_broad_scope` case and before the existing lockfile risk case:

```python
    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-acceptance-block-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(plan_json, [task("task_1", ["src/app.py"], acceptance_command=None, title="App change without acceptance")])
        result, payload = run_audit(repo, plan_json)
        task_audit = payload.get("tasks", [{}])[0]
        checks["block_reason_prioritizes_acceptance_missing"] = (
            result.returncode == 1
            and payload.get("grade") == "red"
            and task_audit.get("plan_support") == "current_superpowers_compatible"
            and task_audit.get("subagent_fit") == "block"
            and task_audit.get("subagent_reason") == "acceptance_command_missing"
            and "acceptance_command_missing" in task_audit.get("blocking_issues", [])
        )
        if not checks["block_reason_prioritizes_acceptance_missing"]:
            failures.append("non-docs missing acceptance should block with acceptance_command_missing reason")

    with tempfile.TemporaryDirectory(prefix="cpe-exec-audit-unsupported-header-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        init_repo(repo)
        plan_json = repo / "plan.json"
        write_plan_json(
            plan_json,
            [task("task_1", ["src/app.py"], title="Legacy header shape")],
            plan_markdown=legacy_plan_markdown(),
        )
        result, payload = run_audit(repo, plan_json)
        task_audit = payload.get("tasks", [{}])[0]
        checks["unsupported_plan_shape_missing_required_header"] = (
            result.returncode == 1
            and payload.get("plan_support") == "blocked_unsupported_plan_shape"
            and task_audit.get("plan_support") == "blocked_unsupported_plan_shape"
            and task_audit.get("subagent_fit") == "block"
            and task_audit.get("subagent_reason") == "blocked_unsupported_plan_shape"
            and "blocked_unsupported_plan_shape" in task_audit.get("blocking_issues", [])
        )
        if not checks["unsupported_plan_shape_missing_required_header"]:
            failures.append("legacy header should be blocked as unsupported current Superpowers/CPE plan shape")
```

Then tighten the existing `red_missing_files`, `risk_marker_operator_review`, and `yellow_fixable_acceptance` checks to assert support classification:

```python
        task_audit = payload.get("tasks", [{}])[0]
        checks["yellow_fixable_acceptance"] = (
            result.returncode == 0
            and payload.get("grade") == "yellow"
            and task_audit.get("plan_support") == "cpe_fixable_metadata"
            and "acceptance_command_missing" in kinds
        )
```

```python
        task_audit = payload.get("tasks", [{}])[0]
        checks["red_missing_files"] = (
            result.returncode == 1
            and payload.get("grade") == "red"
            and task_audit.get("plan_support") == "blocked_unsupported_plan_shape"
            and task_audit.get("subagent_reason") == "blocked_unsupported_plan_shape"
        )
```

```python
        task_audit = payload.get("tasks", [{}])[0]
        checks["risk_marker_operator_review"] = (
            result.returncode == 1
            and "risk_marker_requires_operator_review" in blockers
            and task_audit.get("plan_support") == "operator_review_required"
            and task_audit.get("subagent_reason") == "risk_marker_requires_operator_review"
        )
```

- [ ] **Step 3: Run RED**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_plan_executability_audit.py
```

Expected: FAIL. The current script does not emit `plan_support`, does not block legacy headers, and can leave `subagent_reason` as `adaptive_policy_local_fast_path_small_scope` for a blocked missing-acceptance task.

- [ ] **Step 4: Implement audit classification constants and helpers**

In `skills/kws-codex-plan-executor/scripts/audit_plan_executability.py`, add these constants after the imports:

```python
CURRENT_SUPERPOWERS_PLAN_MARKERS = (
    "REQUIRED SUB-SKILL",
    "subagent-driven-development",
    "executing-plans",
)

CURRENT_SUPERPOWERS_COMPATIBLE = "current_superpowers_compatible"
CPE_FIXABLE_METADATA = "cpe_fixable_metadata"
OPERATOR_REVIEW_REQUIRED = "operator_review_required"
BLOCKED_UNSUPPORTED_PLAN_SHAPE = "blocked_unsupported_plan_shape"

BLOCKING_REASON_PRIORITY = (
    BLOCKED_UNSUPPORTED_PLAN_SHAPE,
    "acceptance_command_missing",
    "files_missing",
    "allowed_write_globs_empty",
    "write_scope_too_broad",
    RISK_MARKER_REQUIRES_OPERATOR_REVIEW,
)
```

Add these helper functions after `load_json`:

```python
def read_plan_text(plan: dict[str, Any], plan_json: Path) -> str:
    raw_plan_path = plan.get("plan")
    if not isinstance(raw_plan_path, str) or not raw_plan_path.strip():
        return ""
    plan_path = Path(raw_plan_path).expanduser()
    if not plan_path.is_absolute():
        plan_path = (plan_json.parent / plan_path).resolve(strict=False)
    try:
        return plan_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def current_superpowers_header_present(plan_text: str) -> bool:
    return all(marker in plan_text for marker in CURRENT_SUPERPOWERS_PLAN_MARKERS)


def primary_blocking_reason(blocking: list[str]) -> str:
    unique = list(dict.fromkeys(blocking))
    for reason in BLOCKING_REASON_PRIORITY:
        if reason in unique:
            return reason
    return unique[0] if unique else "all pre-dispatch prerequisites passed"


def support_classification(blocking: list[str], fixable: list[str], risks: list[str]) -> str:
    if BLOCKED_UNSUPPORTED_PLAN_SHAPE in blocking:
        return BLOCKED_UNSUPPORTED_PLAN_SHAPE
    if risks or RISK_MARKER_REQUIRES_OPERATOR_REVIEW in blocking:
        return OPERATOR_REVIEW_REQUIRED
    if fixable:
        return CPE_FIXABLE_METADATA
    return CURRENT_SUPERPOWERS_COMPATIBLE


def strongest_plan_support(tasks: list[dict[str, Any]], global_blocking: list[str]) -> str:
    if global_blocking:
        return BLOCKED_UNSUPPORTED_PLAN_SHAPE
    supports = [item.get("plan_support") for item in tasks]
    for candidate in (BLOCKED_UNSUPPORTED_PLAN_SHAPE, OPERATOR_REVIEW_REQUIRED, CPE_FIXABLE_METADATA):
        if candidate in supports:
            return candidate
    return CURRENT_SUPERPOWERS_COMPATIBLE
```

- [ ] **Step 5: Update `subagent_fit`, `audit_task`, and `build_payload`**

Change `subagent_fit` so non-docs missing acceptance is considered before the small-scope local fast path:

```python
def subagent_fit(files: list[str], depends_on: list[str], acceptance_missing: bool, risks: list[str]) -> tuple[str, str]:
    if risks:
        return "block", RISK_MARKER_REQUIRES_OPERATOR_REVIEW
    if acceptance_missing and not docs_only(files):
        return "block", "acceptance_command_missing"
    if docs_only(files):
        return "local_fast_path", ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY
    if 0 < len(files) <= 2 and len(depends_on) <= 1:
        reason = ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE if not depends_on else ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK
        return "local_fast_path", reason
    return "delegate", "all pre-dispatch prerequisites passed"
```

Change the `audit_task` signature and its blocking initialization:

```python
def audit_task(task: dict[str, Any], packet: dict[str, Any] | None, repo_root: Path, plan_shape_blocking: list[str]) -> dict[str, Any]:
    task_id = str(task.get("id") or task.get("task_id") or "unknown_task")
    files = list_strings(task.get("files"))
    depends_on = dependency_list(task)
    packet_policy = packet.get("write_policy") if isinstance(packet, dict) and isinstance(packet.get("write_policy"), dict) else {}
    allowed = list_strings(packet_policy.get("allowed_write_globs")) if packet_policy else files
    packet_acceptance = packet.get("acceptance") if isinstance(packet, dict) and isinstance(packet.get("acceptance"), dict) else {}
    acceptance_command = task.get("acceptance_command") or packet_acceptance.get("command")
    acceptance_missing = not isinstance(acceptance_command, str) or not acceptance_command.strip()
    risks = path_risk_markers(files + allowed, list_strings(task.get("risk_markers")))

    fixable: list[str] = []
    blocking: list[str] = list(plan_shape_blocking)
    suggested = normalized_scopes(allowed or files)

    if not files_exist_or_are_declared(files, repo_root):
        blocking.append("files_missing")
        blocking.append(BLOCKED_UNSUPPORTED_PLAN_SHAPE)
```

Keep the existing write-scope, acceptance, fallback, and risk checks, then replace the fit/reason block and returned dictionary tail with:

```python
    fit, reason = subagent_fit(files, depends_on, acceptance_missing, risks)
    if blocking:
        fit = "block"
        reason = primary_blocking_reason(blocking)
    plan_support = support_classification(blocking, fixable, risks)

    return {
        "task_id": task_id,
        "files_status": "green" if files and "files_missing" not in blocking else "red",
        "acceptance_status": "yellow"
        if "acceptance_command_missing" in fixable
        else ("red" if "acceptance_command_missing" in blocking else "green"),
        "write_policy_status": "red"
        if any(item in blocking for item in ("allowed_write_globs_empty", "write_scope_too_broad"))
        else ("yellow" if "write_scope_format_invalid" in fixable else "green"),
        "spec_mapping_status": "yellow" if "full_spec_fallback" in fixable else "green",
        "plan_support": plan_support,
        "subagent_fit": fit,
        "subagent_reason": reason,
        "risk_markers": risks,
        "fixable_issues": sorted(dict.fromkeys(fixable)),
        "blocking_issues": sorted(dict.fromkeys(blocking)),
        "suggested_write_scopes": suggested,
    }
```

Replace `build_payload` with:

```python
def build_payload(plan_json: Path, repo_root: Path, packet_dir: Path | None) -> dict[str, Any]:
    plan = load_json(plan_json)
    if not isinstance(plan, dict):
        raise ValueError("plan JSON must be an object")
    plan_text = read_plan_text(plan, plan_json)
    plan_shape_blocking = [] if current_superpowers_header_present(plan_text) else [BLOCKED_UNSUPPORTED_PLAN_SHAPE]
    packets = load_packets(packet_dir)
    tasks = []
    for task in plan.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id") or task.get("task_id") or "")
        tasks.append(audit_task(task, packets.get(task_id), repo_root, plan_shape_blocking))

    global_blocking = []
    if not tasks:
        global_blocking.append(BLOCKED_UNSUPPORTED_PLAN_SHAPE)
    blocking_count = len(global_blocking) + sum(len(item["blocking_issues"]) for item in tasks)
    fixable_count = sum(len(item["fixable_issues"]) for item in tasks)
    grade = "red" if blocking_count else ("yellow" if fixable_count else "green")
    plan_support = strongest_plan_support(tasks, global_blocking)
    support_counts = {
        CURRENT_SUPERPOWERS_COMPATIBLE: sum(1 for item in tasks if item.get("plan_support") == CURRENT_SUPERPOWERS_COMPATIBLE),
        CPE_FIXABLE_METADATA: sum(1 for item in tasks if item.get("plan_support") == CPE_FIXABLE_METADATA),
        OPERATOR_REVIEW_REQUIRED: sum(1 for item in tasks if item.get("plan_support") == OPERATOR_REVIEW_REQUIRED),
        BLOCKED_UNSUPPORTED_PLAN_SHAPE: sum(1 for item in tasks if item.get("plan_support") == BLOCKED_UNSUPPORTED_PLAN_SHAPE) + len(global_blocking),
    }
    summary = {
        "route": "thin_stateful_bridge",
        "plan_support": plan_support,
        "plan_support_counts": support_counts,
        "task_count": len(tasks),
        "delegate_ready_count": sum(1 for item in tasks if item["subagent_fit"] == "delegate"),
        "local_fast_path_count": sum(1 for item in tasks if item["subagent_fit"] == "local_fast_path"),
        "fixable_issue_count": fixable_count,
        "blocking_issue_count": blocking_count,
    }
    return {
        "schema_version": "1",
        "passed": blocking_count == 0,
        "grade": grade,
        "plan_support": plan_support,
        "summary": summary,
        "tasks": tasks,
        "global_followups": sorted(dict.fromkeys(global_blocking)),
    }
```

- [ ] **Step 6: Run GREEN**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_plan_executability_audit.py
```

Expected: PASS with JSON containing `"passed": true`.

- [ ] **Step 7: Run focused compatibility checks**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 scripts/audit_superpowers_compatibility.py --superpowers-root /Users/kws/.codex/skills --skill-root /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 -m py_compile scripts/audit_plan_executability.py evals/check_plan_executability_audit.py
```

Expected: compatibility audit passes with `recommended_direction=thin_stateful_bridge`; compile exits 0.

- [ ] **Step 8: Commit**

Run:

```bash
cd /Users/kws/source/private/Archive
git status --short --branch --untracked-files=all
git add skills/kws-codex-plan-executor/scripts/audit_plan_executability.py skills/kws-codex-plan-executor/evals/check_plan_executability_audit.py
git commit -m "fix(cpe): gate unsupported Superpowers plan shapes"
```

Expected: commit includes only the audit script and its eval.

---

### Task 2: Document The Current-Plan Gate And Lock The Skill Contract

**Files:**
- Modify: `skills/kws-codex-plan-executor/evals/check_skill_contract.py`
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/references/execution-cycle.md`
- Modify: `skills/kws-codex-plan-executor/references/state-schema.md`
- Modify: `skills/kws-codex-plan-executor/docs/user-guide.ko.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`

**Interfaces:**
- Consumes: Task 1 audit JSON fields `plan_support`, `blocked_unsupported_plan_shape`, `operator_review_required`, and `cpe_fixable_metadata`.
- Produces: durable CPE contract text that says Superpowers is external, legacy plan auto-support is absent, unsupported shapes block before task contracts, and block reasons come from real blocking issues.

- [ ] **Step 1: Add failing contract checks**

In `skills/kws-codex-plan-executor/evals/check_skill_contract.py`, add this block to the `checks` dictionary after `plan_executability_eval_in_harness`:

```python
        "current_superpowers_plan_gate_contract": all(
            token in runtime + user_guide + state_logging
            for token in (
                "external Superpowers contract",
                "current Superpowers-compatible plan",
                "blocked_unsupported_plan_shape",
                "legacy plan auto-support is not provided",
                "before task contracts or edits",
            )
        ),
        "plan_executability_block_reason_contract": all(
            token in plan_executability + runtime
            for token in (
                "BLOCKING_REASON_PRIORITY",
                "primary_blocking_reason",
                "subagent_reason",
                "real blocking issue",
            )
        ),
        "plan_support_classification_contract": all(
            token in plan_executability + runtime + user_guide
            for token in (
                "current_superpowers_compatible",
                "cpe_fixable_metadata",
                "operator_review_required",
                "blocked_unsupported_plan_shape",
            )
        ),
```

- [ ] **Step 2: Run RED**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_skill_contract.py --skill SKILL.md
```

Expected: FAIL because the durable contract docs do not yet include the new current-plan gate language.

- [ ] **Step 3: Update `SKILL.md` core invariants and workflow**

In `skills/kws-codex-plan-executor/SKILL.md`, extend the plan executability audit invariant near the existing plan audit bullet with this exact text:

```markdown
- CPE treats Superpowers as an external Superpowers contract: it reads and
  audits installed Superpowers skill contracts but does not modify them.
  Interactive execution supports only current Superpowers-compatible plan
  shapes. Legacy plan auto-support is not provided. Plans missing the current
  `REQUIRED SUB-SKILL` header, task file scope, or other required execution
  shape are classified as `blocked_unsupported_plan_shape` and stop before task
  contracts or edits. Operator-review risks such as lockfiles, security, infra,
  and migration paths are classified separately as `operator_review_required`.
- Plan executability `subagent_reason` for `block` results must come from a
  real blocking issue using deterministic blocker priority; adaptive local fast
  path reasons must not mask `acceptance_command_missing`, missing files, broad
  write scope, unsupported plan shape, or operator-review risk.
```

Also update workflow step 4 so it reads:

```markdown
4. Before task contracts or edits, run `scripts/audit_plan_executability.py`
   against parsed plan JSON and generated task packets when present. Store the
   JSON under the run directory and copy its summary into state as
   `plan_executability_audit`. If `parse_plan.py` fails in execution mode, treat
   the plan as `blocked_unsupported_plan_shape`; do not infer missing task
   files or legacy shape from raw prose.
```

- [ ] **Step 4: Update `README.md` plan executability paragraph**

In `skills/kws-codex-plan-executor/README.md`, replace the current two-sentence plan executability paragraph with:

```markdown
Plan executability is checked with `scripts/audit_plan_executability.py`. It
summarizes whether the parsed plan is a current Superpowers-compatible plan,
which tasks are ready for CPE task packets, local fast path, delegation,
operator review, or blocking before task contracts or edits. CPE treats
Superpowers as an external contract and does not modify installed Superpowers
skills. Legacy plan auto-support is not provided: plans missing the current
`REQUIRED SUB-SKILL` header, task file scope, or other required execution shape
are classified as `blocked_unsupported_plan_shape`.
```

- [ ] **Step 5: Update execution-cycle and state-schema references**

In `skills/kws-codex-plan-executor/references/execution-cycle.md`, extend step 11 with:

```markdown
If the audit reports `blocked_unsupported_plan_shape`, stop before task
contracts or edits and ask for a current Superpowers-compatible plan. Do not
auto-normalize a legacy plan. If it reports `operator_review_required`, keep it
separate from unsupported shape and require explicit operator review before
continuing.
```

In `skills/kws-codex-plan-executor/references/state-schema.md`, extend the `plan_executability_audit` bullet with:

```markdown
The audit may include `plan_support` as
`current_superpowers_compatible`, `cpe_fixable_metadata`,
`operator_review_required`, or `blocked_unsupported_plan_shape`. A finished
state cannot retain `blocked_unsupported_plan_shape`; operator-reviewed risk
must remain auditable through raw/effective counts and operator decision
fields.
```

- [ ] **Step 6: Update Korean user guide and eval docs**

In `skills/kws-codex-plan-executor/docs/user-guide.ko.md`, add this paragraph under `## 실행 전 Readiness` after the `audit_plan_executability.py` bullet list:

```markdown
이 audit는 현재 Superpowers-compatible plan만 실행 대상으로 봅니다. Superpowers는
외부 계약이므로 CPE가 `/Users/kws/.codex/skills` 아래 스킬을 수정하지 않습니다.
오래된 header, 누락된 `Files` block, 파서 계약 밖 task 구조는
`blocked_unsupported_plan_shape`로 차단되며 legacy plan auto-support is not
provided. lockfile, security, infra, migration 같은 위험 신호는 legacy가 아니라
`operator_review_required`로 분리됩니다. `block` 결과의 `subagent_reason`은 항상
실제 blocking issue에서 와야 하며 local fast path reason으로 덮이지 않습니다.
```

In `skills/kws-codex-plan-executor/docs/evals-and-verification.md`, replace the plan executability eval paragraph with:

```markdown
Plan executability evals cover the read-only audit that runs before task
contracts or edits. They verify green current Superpowers-compatible task
packets, yellow docs-only acceptance gaps, red missing files as
`blocked_unsupported_plan_shape`, red broad write scopes, non-docs missing
acceptance with `subagent_reason=acceptance_command_missing`,
lockfile/operator-review risk as `operator_review_required`, legacy header
blocking without auto-support, and thin-stateful-bridge summary counts.
```

- [ ] **Step 7: Run GREEN**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_skill_contract.py --skill SKILL.md
python3 evals/check_plan_executability_audit.py
```

Expected: both commands pass.

- [ ] **Step 8: Commit**

Run:

```bash
cd /Users/kws/source/private/Archive
git status --short --branch --untracked-files=all
git add skills/kws-codex-plan-executor/evals/check_skill_contract.py skills/kws-codex-plan-executor/SKILL.md skills/kws-codex-plan-executor/README.md skills/kws-codex-plan-executor/references/execution-cycle.md skills/kws-codex-plan-executor/references/state-schema.md skills/kws-codex-plan-executor/docs/user-guide.ko.md skills/kws-codex-plan-executor/docs/evals-and-verification.md
git commit -m "docs(cpe): document current Superpowers plan gate"
```

Expected: commit includes only the contract eval and the documented CPE contract surfaces. If `README.md` has existing unrelated edits, review and preserve them before staging only the intended hunks.

---

### Task 3: Align Release Metadata, Run Full Verification, And Record Evidence

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Create: `skills/kws-codex-plan-executor/evals/baselines/v2.25.1.json`
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`
- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`

**Interfaces:**
- Consumes: Task 1 and Task 2 behavior/docs.
- Produces: patch release metadata, baseline file for `2.25.1`, verification log, and refreshed Graphify evidence.

- [ ] **Step 1: Bump CPE metadata and history**

In `skills/kws-codex-plan-executor/SKILL.md`, change:

```yaml
  version: "2.25.0"
```

to:

```yaml
  version: "2.25.1"
```

In `skills/kws-codex-plan-executor/HISTORY.md`, add this section above `## 2.25.0 - 2026-07-03`:

```markdown
## 2.25.1 - 2026-07-03

- Fixed plan executability audit blocker reasons so blocked tasks report the
  real blocking issue instead of stale adaptive local-fast-path reasons.
- Added current Superpowers plan support classification:
  `current_superpowers_compatible`, `cpe_fixable_metadata`,
  `operator_review_required`, and `blocked_unsupported_plan_shape`.
- Documented that CPE treats Superpowers as an external contract and does not
  provide legacy plan auto-support.
```

- [ ] **Step 2: Refresh release baseline**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh --update-baseline
```

Expected: command passes and creates `evals/baselines/v2.25.1.json` with `"version": "2.25.1"`.

- [ ] **Step 3: Run full verification**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
python3 scripts/audit_superpowers_compatibility.py --superpowers-root /Users/kws/.codex/skills --skill-root /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
cd /Users/kws/source/private/Archive
git diff --check
```

Expected: all commands exit 0; compatibility audit still recommends `thin_stateful_bridge`.

- [ ] **Step 4: Refresh Graphify**

Run:

```bash
cd /Users/kws/source/private/Archive
graphify update .
git rev-parse HEAD
rg -n "Built from commit" graphify-out/GRAPH_REPORT.md
```

Expected: `graphify update .` exits 0. `GRAPH_REPORT.md` records the current commit prefix from `git rev-parse HEAD` after the implementation commits.

- [ ] **Step 5: Append verification log**

Append this shape to `skills/kws-codex-plan-executor/docs/verification-log.md`, filling in the actual branch, commit, and command results from Steps 2-4:

```markdown
## 2026-07-03 Asia/Seoul - CPE current Superpowers plan gate

- Branch/commit: `main`; record the output of `git rev-parse --short HEAD` before the release commit.
- Scope: fixed plan executability blocker reason priority, added current Superpowers plan support classification, documented no legacy plan auto-support, and released CPE `2.25.1`.
- Commands:
  - `./evals/run.sh --update-baseline` - PASS, wrote `evals/baselines/v2.25.1.json`.
  - `./evals/run.sh` - PASS.
  - `python3 -m py_compile scripts/*.py evals/*.py` - PASS.
  - `bash -n evals/run.sh` - PASS.
  - `python3 scripts/audit_superpowers_compatibility.py --superpowers-root /Users/kws/.codex/skills --skill-root /Users/kws/source/private/Archive/skills/kws-codex-plan-executor` - PASS, `thin_stateful_bridge`.
  - `graphify update .` - PASS.
  - `git diff --check` - PASS.
- Residual risk: legacy Superpowers plan shapes are intentionally unsupported and require regeneration with current `writing-plans`.
```

- [ ] **Step 6: Final status review**

Run:

```bash
cd /Users/kws/source/private/Archive
git status --short --branch --untracked-files=all
git diff --stat
```

Expected: only intended CPE and Graphify files are changed. Existing user changes outside the intended scope remain preserved and are not staged by accident.

- [ ] **Step 7: Commit**

Run:

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/SKILL.md skills/kws-codex-plan-executor/HISTORY.md skills/kws-codex-plan-executor/evals/baselines/v2.25.1.json skills/kws-codex-plan-executor/docs/verification-log.md graphify-out/GRAPH_REPORT.md graphify-out/graph.json
git commit -m "chore(cpe): release current Superpowers plan gate"
```

Expected: commit includes release metadata, generated baseline, verification log, and Graphify refresh. Do not stage `.DS_Store` or unrelated local files.
