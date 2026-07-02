# CPE Release Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic CPE release contract so `SKILL.md` version, history, eval baseline, release docs, and verification evidence stay aligned.

**Architecture:** Treat `skills/kws-codex-plan-executor` as the versioned package. Add one read-only release-contract eval, one release-process document, lightweight cross-links from maintainer docs, and then close the accumulated `2.25.0` CPE changes as the current official version with a matching eval baseline.

**Tech Stack:** Python 3 stdlib, Bash eval harness, Markdown docs, existing CPE deterministic evals under `skills/kws-codex-plan-executor/evals`.

## Global Constraints

- CPE 버저닝 단위는 `skills/kws-codex-plan-executor` package이다.
- Official version source of truth is `skills/kws-codex-plan-executor/SKILL.md` `metadata.version`.
- Do not change CPE runtime state schema or execution behavior.
- Do not make `docs/experiments/v*` the official release source of truth.
- Do not infer release validity from git commit dates.
- Do not auto-update baselines from `check_release_contract.py`.
- Do not use baseline updates to hide failing fixture behavior.
- Keep root-level pruned docs library out of scope.

---

## File Structure

- Create `skills/kws-codex-plan-executor/docs/release-process.md`
  - Responsibility: CPE versioning rules, release checklist, baseline update rules, verification-log rules.
- Create `skills/kws-codex-plan-executor/evals/check_release_contract.py`
  - Responsibility: read-only structural guard for version, history, baseline, and release-doc alignment.
- Modify `skills/kws-codex-plan-executor/evals/run.sh`
  - Responsibility: include `check_release_contract.py` in the deterministic full harness.
- Modify `skills/kws-codex-plan-executor/evals/check_eval_harness.py`
  - Responsibility: assert the full harness invokes release-contract coverage.
- Modify `skills/kws-codex-plan-executor/evals/check_skill_contract.py`
  - Responsibility: stop hard-coding `2.24.0`; assert skill metadata version is parseable and maintenance docs reference release process.
- Modify `skills/kws-codex-plan-executor/SKILL.md`
  - Responsibility: bump official version to `2.25.0`, update `updated_at`, and point Maintenance to release process plus doc update protocol.
- Modify `skills/kws-codex-plan-executor/HISTORY.md`
  - Responsibility: close `2.25.0 - Unreleased` as `2.25.0 - 2026-07-03`.
- Modify `skills/kws-codex-plan-executor/README.md`
  - Responsibility: add a short maintainer note that release-process is the release contract.
- Modify `skills/kws-codex-plan-executor/docs/doc-update-protocol.md`
  - Responsibility: delegate release workflow details to `release-process.md`.
- Modify `skills/kws-codex-plan-executor/docs/future-agent-guide.md`
  - Responsibility: tell future agents to read release process and doc update protocol before skill edits.
- Modify `skills/kws-codex-plan-executor/docs/evals-and-verification.md`
  - Responsibility: document the new release-contract eval.
- Modify `skills/kws-codex-plan-executor/docs/verification-log.md`
  - Responsibility: append release-contract verification evidence.
- Create `skills/kws-codex-plan-executor/evals/baselines/v2.25.0.json`
  - Responsibility: deterministic fixture baseline for official CPE `2.25.0`.

## Task 1: Add Release Contract Eval

**Files:**
- Create: `skills/kws-codex-plan-executor/evals/check_release_contract.py`
- Modify: `skills/kws-codex-plan-executor/evals/run.sh`
- Modify: `skills/kws-codex-plan-executor/evals/check_eval_harness.py`

**Interfaces:**
- Consumes: `SKILL.md`, `HISTORY.md`, `docs/release-process.md`, `docs/doc-update-protocol.md`, `docs/future-agent-guide.md`, `evals/baselines/v<version>.json`
- Produces: read-only CLI `python3 evals/check_release_contract.py` that prints `{"passed": bool, "checks": ..., "failures": ...}` and exits non-zero on drift.

- [ ] **Step 1: Create the release contract checker**

Create `skills/kws-codex-plan-executor/evals/check_release_contract.py`:

```python
#!/usr/bin/env python3
"""Check CPE release metadata, history, baseline, and release docs."""

from __future__ import annotations

import json
import re
from pathlib import Path


SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
SKILL_VERSION_RE = re.compile(r'(?m)^[ \t]*version:[ \t]*"([^"]+)"')
HISTORY_VERSION_RE = re.compile(r"^## (\d+\.\d+\.\d+)(?:\s+-\s+(.+))?$", re.MULTILINE)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    skill_path = skill_dir / "SKILL.md"
    history_path = skill_dir / "HISTORY.md"
    release_path = skill_dir / "docs" / "release-process.md"
    doc_update_path = skill_dir / "docs" / "doc-update-protocol.md"
    future_agent_path = skill_dir / "docs" / "future-agent-guide.md"

    skill_text = read(skill_path)
    match = SKILL_VERSION_RE.search(skill_text)
    version = match.group(1) if match else ""
    baseline_path = skill_dir / "evals" / "baselines" / f"v{version}.json"

    checks: dict[str, bool] = {}
    failures: list[str] = []

    checks["skill_version_parseable_semver"] = bool(version and SEMVER.fullmatch(version))
    if not checks["skill_version_parseable_semver"]:
        failures.append("SKILL.md metadata.version must be a quoted semantic version such as 2.25.0")

    checks["baseline_exists_for_skill_version"] = baseline_path.is_file()
    if not checks["baseline_exists_for_skill_version"]:
        failures.append(f"missing baseline for SKILL.md version: {baseline_path.relative_to(skill_dir)}")

    baseline_payload: dict = {}
    if baseline_path.is_file():
        try:
            baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"baseline JSON is invalid: {baseline_path.relative_to(skill_dir)}: {exc}")
    checks["baseline_version_matches_skill_version"] = baseline_payload.get("version") == version
    if baseline_path.is_file() and not checks["baseline_version_matches_skill_version"]:
        failures.append(
            f"baseline version mismatch: {baseline_path.relative_to(skill_dir)} has "
            f"{baseline_payload.get('version')!r}, SKILL.md has {version!r}"
        )

    history_text = read(history_path)
    history_versions = [item[0] for item in HISTORY_VERSION_RE.findall(history_text)]
    checks["history_has_current_version"] = version in history_versions
    if version and not checks["history_has_current_version"]:
        failures.append(f"HISTORY.md missing section for current version: ## {version} - YYYY-MM-DD")

    duplicate_versions = sorted({item for item in history_versions if history_versions.count(item) > 1})
    checks["history_has_no_duplicate_version_headings"] = not duplicate_versions
    if duplicate_versions:
        failures.append(f"HISTORY.md has duplicate version headings: {', '.join(duplicate_versions)}")

    checks["release_process_exists"] = release_path.is_file()
    if not checks["release_process_exists"]:
        failures.append("missing docs/release-process.md")

    release_text = read(release_path) if release_path.is_file() else ""
    required_release_terms = ["major", "minor", "patch", "no bump", "baseline", "verification-log"]
    missing_terms = [term for term in required_release_terms if term not in release_text]
    checks["release_process_mentions_required_terms"] = not missing_terms
    if missing_terms:
        failures.append(f"docs/release-process.md missing required release terms: {', '.join(missing_terms)}")

    doc_update_text = read(doc_update_path)
    future_agent_text = read(future_agent_path)
    maintenance = skill_text[skill_text.find("## Maintenance") :] if "## Maintenance" in skill_text else ""
    checks["doc_update_links_release_process"] = "release-process.md" in doc_update_text
    checks["future_agent_links_release_process"] = "release-process.md" in future_agent_text
    checks["maintenance_links_release_and_doc_protocol"] = (
        "release-process.md" in maintenance and "doc-update-protocol.md" in maintenance
    )

    if not checks["doc_update_links_release_process"]:
        failures.append("docs/doc-update-protocol.md must reference docs/release-process.md")
    if not checks["future_agent_links_release_process"]:
        failures.append("docs/future-agent-guide.md must reference docs/release-process.md")
    if not checks["maintenance_links_release_and_doc_protocol"]:
        failures.append("SKILL.md Maintenance must mention docs/release-process.md and docs/doc-update-protocol.md")

    payload = {"version": version, "passed": not failures, "checks": checks, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the new eval and verify it fails for missing release docs**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_release_contract.py
```

Expected: FAIL with messages including `missing docs/release-process.md`, `docs/doc-update-protocol.md must reference docs/release-process.md`, and `docs/future-agent-guide.md must reference docs/release-process.md`.

- [ ] **Step 3: Add the checker to the full harness**

In `skills/kws-codex-plan-executor/evals/run.sh`, add this line after `check_baseline_utils.py`:

```bash
python3 "$EVAL_DIR/check_release_contract.py" >/dev/null
```

- [ ] **Step 4: Add harness self-check coverage**

In `skills/kws-codex-plan-executor/evals/check_eval_harness.py`, add this check before the payload is printed:

```python
    checks["release_contract_eval_in_harness"] = (
        "check_release_contract.py" in run_sh
        and (skill_dir / "evals" / "check_release_contract.py").is_file()
    )
    if not checks["release_contract_eval_in_harness"]:
        failures.append("run.sh should execute release contract eval coverage")
```

- [ ] **Step 5: Run focused checks**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_release_contract.py
python3 evals/check_eval_harness.py
```

Expected: `check_release_contract.py` still FAILS for missing release docs; `check_eval_harness.py` PASSES.

- [ ] **Step 6: Commit the RED release-contract eval**

```bash
cd /Users/kws/source/private/Archive
git add \
  skills/kws-codex-plan-executor/evals/check_release_contract.py \
  skills/kws-codex-plan-executor/evals/run.sh \
  skills/kws-codex-plan-executor/evals/check_eval_harness.py
git commit -m "test: add CPE release contract guard"
```

## Task 2: Add Release Process Docs And Cross-Links

**Files:**
- Create: `skills/kws-codex-plan-executor/docs/release-process.md`
- Modify: `skills/kws-codex-plan-executor/docs/doc-update-protocol.md`
- Modify: `skills/kws-codex-plan-executor/docs/future-agent-guide.md`
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/README.md`
- Modify: `skills/kws-codex-plan-executor/docs/evals-and-verification.md`

**Interfaces:**
- Consumes: `check_release_contract.py` from Task 1.
- Produces: docs and maintenance links that make `python3 evals/check_release_contract.py` pass under the current `2.24.0` version.

- [ ] **Step 1: Add release process documentation**

Create `skills/kws-codex-plan-executor/docs/release-process.md`:

```markdown
# Release Process

This is the release contract for `kws-codex-plan-executor`.

## Version Source Of Truth

The official CPE package version is `metadata.version` in `SKILL.md`.
`HISTORY.md`, `evals/baselines/v<version>.json`, and
`docs/verification-log.md` must agree with that version when a release is
closed.

`docs/experiments/v*` files are design and implementation records. They are not
the official release source of truth.

## Version Bump Rules

Use semantic versioning.

`major` changes break existing state consumers, prompt or headless output
schema, invocation semantics, worktree/runtime layout, deterministic fixture
expectations, or downstream operator workflows.

`minor` changes add compatible behavior: new features, optional state fields,
scripts, evals, prompt or handoff surfaces, inspection, readiness, replay, or
other compatible runtime behavior.

`patch` changes fix bugs, correct docs that disagree with behavior, stabilize
evals, or make compatible corrections to existing behavior.

`no bump` is allowed only for pure documentation cleanup, typo fixes, and
verification-log additions that do not change runtime behavior, scripts, prompt
output, eval behavior, package metadata, or public skill metadata.

## Unreleased Policy

Accumulate in-progress changes under `HISTORY.md` `Unreleased` entries.
Close a release by moving the relevant entries into a dated version section,
for example `## 2.25.0 - 2026-07-03`.

## Baseline Rules

The full harness reads `SKILL.md` version and compares generated fixture output
with `evals/baselines/v<version>.json`.

Run `./evals/run.sh --update-baseline` only after reviewing the intended
fixture output change. Do not update a baseline to hide a failing or
unexplained behavior change.

`check_release_contract.py` is read-only and must never write baseline files.

## Verification Log

Append `docs/verification-log.md` whenever this skill package changes. Keep the
entry compact:

- date and local timezone
- branch and commit when known
- scope of the change
- commands run
- result of each command
- skipped checks with reasons
- residual risk or follow-up

## Release Checklist

1. Decide `major`, `minor`, `patch`, or `no bump`.
2. Update `SKILL.md metadata.version` when a bump is required.
3. Close relevant `HISTORY.md` entries under the release version.
4. Update docs according to `docs/doc-update-protocol.md`.
5. Run `./evals/run.sh --update-baseline` when fixture output intentionally changes or when a new version needs its baseline.
6. Review the baseline diff.
7. Run `./evals/run.sh`.
8. Run `python3 -m py_compile scripts/*.py evals/*.py`.
9. Run `bash -n evals/run.sh`.
10. Run `git diff --check`.
11. Append `docs/verification-log.md`.
```

- [ ] **Step 2: Link release process from doc update protocol**

In `skills/kws-codex-plan-executor/docs/doc-update-protocol.md`, add this paragraph after the opening paragraph:

```markdown
For version bump rules, baseline handling, release closeout, and verification
history requirements, follow [release-process.md](release-process.md). This
document maps changed surfaces to docs; it does not replace the release
process.
```

- [ ] **Step 3: Link release process from future agent guide**

Replace the first paragraph of `skills/kws-codex-plan-executor/docs/future-agent-guide.md` with:

```markdown
Before editing this skill, read [release-process.md](release-process.md) and
[doc-update-protocol.md](doc-update-protocol.md), then update tests first. Keep
the active contract aligned across `SKILL.md`,
`templates/fresh-session-prompt.txt`, references, scripts, docs, evals, history,
and baselines.
```

- [ ] **Step 4: Update SKILL maintenance guidance**

Replace the Maintenance section in `skills/kws-codex-plan-executor/SKILL.md` with:

```markdown
## Maintenance

Use `docs/release-process.md` and `docs/doc-update-protocol.md` before editing
this skill. Update `HISTORY.md`, `ARCHITECTURE.md`, package metadata,
compatibility docs, and eval baselines for behavior changes.

For eval harness runs, the outer harness runs `evals/check_execution.py`. The
target executor must not inspect fixture YAML, baseline files, `.harness`
metadata, or expected values.
```

- [ ] **Step 5: Add README maintainer note**

In `skills/kws-codex-plan-executor/README.md`, add this section before `## Design Notes`:

```markdown
## Release Contract

`docs/release-process.md` defines the CPE package versioning and release
closeout contract. `SKILL.md` metadata is the official version source of truth;
`HISTORY.md`, `evals/baselines/v<version>.json`, and
`docs/verification-log.md` must stay aligned with it when a release is closed.
```

- [ ] **Step 6: Document the new eval**

In `skills/kws-codex-plan-executor/docs/evals-and-verification.md`, add `python3 evals/check_release_contract.py` after `python3 evals/check_baseline_utils.py` in the command list.

Add this paragraph after the baseline utility paragraph:

```markdown
`check_release_contract.py` verifies CPE release metadata and docs alignment:
`SKILL.md` semantic version, matching baseline file, matching baseline version,
current `HISTORY.md` section, release-process docs, and maintainer cross-links.
The check is read-only and never updates baselines.
```

- [ ] **Step 7: Run release contract eval**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_release_contract.py
```

Expected: PASS under the current `2.24.0` version.

- [ ] **Step 8: Commit docs and links**

```bash
cd /Users/kws/source/private/Archive
git add \
  skills/kws-codex-plan-executor/docs/release-process.md \
  skills/kws-codex-plan-executor/docs/doc-update-protocol.md \
  skills/kws-codex-plan-executor/docs/future-agent-guide.md \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/README.md \
  skills/kws-codex-plan-executor/docs/evals-and-verification.md
git commit -m "docs: add CPE release process"
```

## Task 3: Close Official CPE 2.25.0 Release

**Files:**
- Modify: `skills/kws-codex-plan-executor/SKILL.md`
- Modify: `skills/kws-codex-plan-executor/HISTORY.md`
- Modify: `skills/kws-codex-plan-executor/evals/check_skill_contract.py`
- Create: `skills/kws-codex-plan-executor/evals/baselines/v2.25.0.json`

**Interfaces:**
- Consumes: release process and release contract eval from Tasks 1-2.
- Produces: official CPE `2.25.0` package metadata and matching deterministic baseline.

- [ ] **Step 1: Bump official skill metadata**

In `skills/kws-codex-plan-executor/SKILL.md`, change:

```yaml
metadata:
  version: "2.24.0"
  updated_at: "2026-06-25"
```

to:

```yaml
metadata:
  version: "2.25.0"
  updated_at: "2026-07-03"
```

- [ ] **Step 2: Close HISTORY 2.25.0**

In `skills/kws-codex-plan-executor/HISTORY.md`, change:

```markdown
## 2.25.0 - Unreleased
```

to:

```markdown
## 2.25.0 - 2026-07-03
```

Leave older `## 2.23.0 - Unreleased` unchanged unless a separate review decides to backfill its release date. This plan only closes the current official release.

- [ ] **Step 3: Replace hard-coded skill version check**

In `skills/kws-codex-plan-executor/evals/check_skill_contract.py`, replace:

```python
        "version_2240": 'version: "2.24.0"' in text,
```

with:

```python
        "version_parseable_semver": re.search(r'(?m)^[ \t]*version:[ \t]*"\d+\.\d+\.\d+"', text) is not None,
```

This keeps `check_skill_contract.py` from forcing every future release to edit a hard-coded version token.

- [ ] **Step 4: Run release contract and observe missing baseline**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_release_contract.py
```

Expected: FAIL with `missing baseline for SKILL.md version: evals/baselines/v2.25.0.json`.

- [ ] **Step 5: Generate the 2.25.0 baseline**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
./evals/run.sh --update-baseline
```

Expected: PASS and creates `evals/baselines/v2.25.0.json` with `"version": "2.25.0"`.

- [ ] **Step 6: Run focused release checks**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_release_contract.py
python3 evals/check_skill_contract.py --skill SKILL.md
```

Expected: both PASS.

- [ ] **Step 7: Commit official version closeout**

```bash
cd /Users/kws/source/private/Archive
git add \
  skills/kws-codex-plan-executor/SKILL.md \
  skills/kws-codex-plan-executor/HISTORY.md \
  skills/kws-codex-plan-executor/evals/check_skill_contract.py \
  skills/kws-codex-plan-executor/evals/baselines/v2.25.0.json
git commit -m "chore: release CPE 2.25.0"
```

## Task 4: Verification Log And Final Quality Gate

**Files:**
- Modify: `skills/kws-codex-plan-executor/docs/verification-log.md`

**Interfaces:**
- Consumes: all changes from Tasks 1-3.
- Produces: final verification evidence and a clean worktree ready for review or merge.

- [ ] **Step 1: Run full verification**

Run:

```bash
cd /Users/kws/source/private/Archive/skills/kws-codex-plan-executor
python3 evals/check_release_contract.py
./evals/run.sh
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
cd /Users/kws/source/private/Archive
git diff --check
```

Expected:

- `check_release_contract.py`: PASS with `version` `2.25.0`
- `./evals/run.sh`: PASS with all fixture entries matching `v2.25.0`
- Python compile: PASS
- Shell syntax: PASS
- `git diff --check`: PASS

- [ ] **Step 2: Append verification log entry**

Add this entry at the top of `skills/kws-codex-plan-executor/docs/verification-log.md`, updating the branch/commit line after committing if needed:

````markdown
## 2026-07-03 - Release Contract And 2.25.0 Closeout

Scope:

- Added CPE release process documentation.
- Added deterministic release-contract eval coverage.
- Wired release-contract coverage into the full eval harness.
- Closed CPE `2.25.0` as the current official `SKILL.md` version.
- Added matching `evals/baselines/v2.25.0.json`.

Commands:

```bash
python3 evals/check_release_contract.py
./evals/run.sh --update-baseline
./evals/run.sh
python3 evals/check_skill_contract.py --skill SKILL.md
python3 -m py_compile scripts/*.py evals/*.py
bash -n evals/run.sh
git diff --check
```

Result:

- Release contract eval: pass.
- Baseline update: pass; `v2.25.0` generated after review.
- Full deterministic fixture harness: pass.
- Skill contract eval: pass.
- Python compile, shell syntax, and diff whitespace checks: pass.

Residual risk:

- Git-date verification-log freshness is intentionally not enforced by the
  first release-contract eval to avoid false positives.
````

- [ ] **Step 3: Re-run changed docs whitespace check**

Run:

```bash
cd /Users/kws/source/private/Archive
git diff --check
```

Expected: PASS.

- [ ] **Step 4: Commit verification evidence**

```bash
cd /Users/kws/source/private/Archive
git add skills/kws-codex-plan-executor/docs/verification-log.md
git commit -m "docs: record CPE release contract verification"
```

- [ ] **Step 5: Final status check**

Run:

```bash
cd /Users/kws/source/private/Archive
git status --short --branch --untracked-files=all
```

Expected: no uncommitted changes. The branch may be ahead of `origin/main`.

## Self-Review Notes

- Spec coverage: Tasks cover release-process docs, cross-links, deterministic eval, harness wiring, `2.25.0` closeout, baseline creation, and verification-log evidence.
- Scope: This plan does not alter runtime execution, state schema, prompt output, headless result shape, or Waygent platform versioning.
- Known intentional limit: `check_release_contract.py` remains structural and read-only; it does not infer verification freshness from git dates.
