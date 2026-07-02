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
