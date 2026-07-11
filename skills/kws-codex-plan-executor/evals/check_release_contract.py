#!/usr/bin/env python3
"""Check CPE release metadata, history, baseline, and release docs."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
SKILL_VERSION_RE = re.compile(r'(?m)^[ \t]*version:[ \t]*"([^"]+)"')
RELEASE_STATUS_RE = re.compile(r'(?m)^[ \t]*release_status:[ \t]*"([^"]+)"')
HISTORY_VERSION_RE = re.compile(r"^## (\d+\.\d+\.\d+)(?:\s+-\s+(.+))?$", re.MULTILINE)
VERIFICATION_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
RELEASE_SUBJECT = "release(cpe): publish deterministic integrity 3.0.1"
REQUIRED_COST_FREE_COMMANDS = {
    "./evals/run.sh",
    "python3 -m py_compile scripts/*.py scripts/cpe_runtime/*.py evals/*.py",
    "bash -n evals/run.sh",
    "python3 evals/check_release_contract.py",
    "python3 evals/check_docs_contract.py",
    "bun run check",
    "git diff --check",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def latest_verification(text: str) -> dict:
    for raw in VERIFICATION_BLOCK_RE.findall(text):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if payload.get("schema_version") == "cpe-release-verification.v1":
            return payload
    return {}


def expected_implementation_commit(repo_root: Path) -> str:
    history = subprocess.run(
        ["git", "log", "--format=%H%x09%s"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    release_commit = next(
        (
            line.split("\t", 1)[0]
            for line in history
            if "\t" in line and line.split("\t", 1)[1] == RELEASE_SUBJECT
        ),
        "",
    )
    revision = f"{release_commit}^" if release_commit else "HEAD"
    return subprocess.run(
        ["git", "rev-parse", revision],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    skill_path = skill_dir / "SKILL.md"
    history_path = skill_dir / "HISTORY.md"
    release_path = skill_dir / "docs" / "release-process.md"
    doc_update_path = skill_dir / "docs" / "doc-update-protocol.md"
    future_agent_path = skill_dir / "docs" / "future-agent-guide.md"
    verification_log_path = skill_dir / "docs" / "verification-log.md"
    live_status_path = skill_dir / "evals" / "live-migration" / "release-status.json"

    skill_text = read(skill_path)
    match = SKILL_VERSION_RE.search(skill_text)
    version = match.group(1) if match else ""
    release_match = RELEASE_STATUS_RE.search(skill_text)
    release_status = release_match.group(1) if release_match else ""
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

    active_baselines = sorted(
        path.name for path in (skill_dir / "evals" / "baselines").glob("v*.json")
    )
    partial_baselines = sorted(
        path.name for path in (skill_dir / "evals" / "baselines").glob("v*.json.partial")
    )
    checks["exactly_one_active_v3_baseline"] = (
        version.startswith("3.")
        and active_baselines == [f"v{version}.json"]
        and not partial_baselines
    )
    if not checks["exactly_one_active_v3_baseline"]:
        failures.append(
            "active baseline directory must contain exactly the current v3 baseline and no partials: "
            f"json={active_baselines}, partial={partial_baselines}"
        )

    fixtures = baseline_payload.get("fixtures")
    maintained_checks = baseline_payload.get("checks")
    legacy_fixtures_pass = (
        isinstance(fixtures, list)
        and bool(fixtures)
        and all(
            isinstance(item, dict)
            and isinstance(item.get("fixture"), str)
            and bool(item["fixture"])
            and item.get("passed") is True
            for item in fixtures
        )
    )
    maintained_checks_pass = (
        baseline_payload.get("schema_version") == "maintained-evals.v1"
        and isinstance(maintained_checks, list)
        and bool(maintained_checks)
        and all(
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and bool(item["name"])
            and item.get("exit_code") == 0
            for item in maintained_checks
        )
        and baseline_payload.get("paid_execution") == "skipped_not_approved"
    )
    checks["baseline_has_nonempty_passing_fixtures"] = (
        legacy_fixtures_pass or maintained_checks_pass
    )
    if baseline_path.is_file() and not checks["baseline_has_nonempty_passing_fixtures"]:
        failures.append(
            "current v3 baseline must contain named passing legacy fixtures or maintained checks"
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

    verification_log_text = read(verification_log_path) if verification_log_path.is_file() else ""
    checks["verification_log_has_2026_07_10_asia_seoul_entry"] = (
        "## 2026-07-10 Asia/Seoul" in verification_log_text
        and "live" in verification_log_text[verification_log_text.find("## 2026-07-10 Asia/Seoul") :].lower()
    )
    if not checks["verification_log_has_2026_07_10_asia_seoul_entry"]:
        failures.append(
            "docs/verification-log.md must contain a 2026-07-10 Asia/Seoul entry with live evidence status"
        )

    live_status: dict = {}
    if live_status_path.is_file():
        try:
            live_status = json.loads(read(live_status_path))
        except json.JSONDecodeError as exc:
            failures.append(f"live release status JSON is invalid: {exc}")
    checks["live_evidence_status_is_truthful"] = (
        live_status.get("schema_version") == "1"
        and live_status.get("version") == version
        and (
            (
                live_status.get("status") == "released"
                and live_status.get("deterministic_evidence", {}).get("status") == "passed"
                and live_status.get("paid_live_evidence", {}).get("status") == "passed"
                and live_status.get("release_ready") is True
            )
            or (
                version != "3.0.0"
                and
                live_status.get("status") == "deterministic_ready_paid_pending"
                and live_status.get("deterministic_evidence", {}).get("status") == "passed"
                and live_status.get("paid_live_evidence", {}).get("status") == "pending"
                and live_status.get("release_ready") is False
            )
            or (
                version == "3.0.0"
                and live_status.get("status") == "integrity_closure_pending_paid_pending"
                and live_status.get("deterministic_evidence", {}).get("status") == "pending"
                and live_status.get("paid_live_evidence", {}).get("status") == "pending"
                and live_status.get("release_ready") is False
            )
        )
    )
    if not checks["live_evidence_status_is_truthful"]:
        failures.append(
            "evals/live-migration/release-status.json must truthfully record either released/paid-passed "
            "or deterministic-ready/paid-pending or integrity-closure/paid-pending"
        )

    verification = latest_verification(verification_log_text)
    commands = verification.get("commands", [])
    command_names = {
        item.get("command") for item in commands if isinstance(item, dict)
    }
    expected_commit = expected_implementation_commit(skill_dir.parents[1])
    maintained_check_count = (
        len(maintained_checks)
        if maintained_checks_pass and isinstance(maintained_checks, list)
        else 0
    )
    release_checks = {
        "version_is_301": version == "3.0.1",
        "verification_version_matches": verification.get("version") == version,
        "deterministic_ready": release_status == "deterministic-ready; paid-live-pending",
        "canonical_status_is_deterministic_ready": (
            live_status.get("status") == "deterministic_ready_paid_pending"
            and live_status.get("deterministic_status") == "deterministic-ready"
            and live_status.get("deterministic_evidence", {}).get("status") == "passed"
        ),
        "paid_live_pending": (
            live_status.get("paid_live_status") == "pending"
            and live_status.get("paid_live_evidence", {}).get("status") == "pending"
            and verification.get("paid_live") == "skipped_not_approved"
        ),
        "release_ready_false": live_status.get("release_ready") is False,
        "implementation_commit_recorded": (
            verification.get("implementation_commit") == expected_commit
        ),
        "verification_timestamp_recorded": bool(
            re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})",
                str(verification.get("timestamp", "")),
            )
        ),
        "all_cost_free_commands_recorded": REQUIRED_COST_FREE_COMMANDS <= command_names,
        "all_cost_free_commands_passed": (
            bool(commands)
            and all(
                isinstance(item, dict) and item.get("exit_code") == 0
                for item in commands
            )
        ),
        "current_passing_counts_recorded": (
            maintained_check_count > 0
            and verification.get("eval_passing_count") == maintained_check_count
            and live_status.get("deterministic_evidence", {}).get(
                "maintained_check_count"
            ) == maintained_check_count
            and isinstance(verification.get("bun_passing_count"), int)
            and verification.get("bun_passing_count", 0) > 0
        ),
        "paid_live_residual_risk_recorded": (
            verification.get("residual_risk") == "paid live migration gate pending"
        ),
    }
    checks.update(release_checks)
    for check_name, passed in release_checks.items():
        if not passed:
            failures.append(f"3.0.1 deterministic release contract failed: {check_name}")

    payload = {
        "version": version,
        "passed": not failures,
        "release_ready": live_status.get("release_ready", False),
        "live_evidence_status": live_status.get("status", "missing"),
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
