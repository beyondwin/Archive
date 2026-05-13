#!/usr/bin/env python3
"""Documentation freshness checks for kws-claude-multi-agent-executor.

Runs deterministic checks for the most regression-prone doc drift:

1. Version consistency across SKILL.md frontmatter / skill README.
2. Internal markdown links resolve.
3. HISTORY.md has an entry matching the current SKILL.md version.
4. Latest minor-version snapshot exists in docs/snapshots/.
5. Every D### ADR under docs/experiments/*/decisions/ is indexed in docs/decision-log.md.
6. Stale TODO/FIXME/XXX/WIP markers count (reported, not failed).

By default NON-BLOCKING: exits 0 even with failures so the eval harness
continues. Set DOC_FRESHNESS_STRICT=1 to fail the harness on any failure.

Run from the skill package root:
    python3 evals/check_doc_freshness.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent


def read_skill_version() -> str | None:
    """Extract metadata.version from SKILL.md frontmatter."""
    skill_md = SKILL_ROOT / "SKILL.md"
    if not skill_md.exists():
        return None
    text = skill_md.read_text(encoding="utf-8")
    match = re.search(r'^\s*version:\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def read_readme_version() -> str | None:
    """Extract the current version from this skill's README."""
    readme = SKILL_ROOT / "README.md"
    if not readme.exists():
        return None
    text = readme.read_text(encoding="utf-8")
    match = re.search(r'\*\*(?:Current version|현재 버전)\*\*:\s*`([^`]+)`', text)
    return match.group(1) if match else None


def check_version_consistency(checks: dict, failures: list) -> None:
    skill = read_skill_version()
    readme = read_readme_version()

    # Skill MUST always be readable.
    if skill is None:
        checks["versions_readable"] = False
        failures.append("SKILL.md frontmatter version unreadable")
        return

    if readme is None:
        checks["versions_readable"] = False
        failures.append("README.md current version unreadable")
        return

    checks["versions_readable"] = True
    checks["versions_consistent"] = skill == readme
    if checks["versions_consistent"] is not True:
        failures.append(
            f"Version drift: SKILL.md={skill}, README.md={readme} — "
            f"see docs/doc-update-protocol.md §Version bump"
        )


def _strip_code_spans(text: str) -> str:
    """Remove inline code spans (``...``, `...`) and fenced code blocks (```...```)
    so we don't pick up link-like syntax in examples or escaped references."""
    # Fenced code blocks first (greedy with newline support).
    text = re.sub(r'```[\s\S]*?```', '', text)
    # Then double-tick spans, then single-tick spans.
    text = re.sub(r'``[^`\n]+``', '', text)
    text = re.sub(r'`[^`\n]+`', '', text)
    return text


def check_internal_links(checks: dict, failures: list) -> None:
    """Verify every relative .md link in the doc tree resolves."""
    link_pat = re.compile(r'\[[^\]]+\]\(([^)]+\.md(?:#[^)]*)?)\)')
    scope_dirs = [SKILL_ROOT, SKILL_ROOT / "docs", SKILL_ROOT / "references", SKILL_ROOT / "evals"]
    md_files: list[Path] = []
    for d in scope_dirs:
        if d.exists():
            md_files.extend(d.glob("**/*.md"))

    broken: list[str] = []
    for md in md_files:
        # Skip template files — they contain placeholder paths by design.
        if "_template" in md.parts:
            continue
        rel_dir = md.parent
        try:
            text = md.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scan_text = _strip_code_spans(text)
        for raw in link_pat.findall(scan_text):
            if raw.startswith(("http://", "https://", "mailto:", "#")):
                continue
            # Skip obvious placeholders ("path.md", "<…>" with angle brackets).
            if "<" in raw or ">" in raw:
                continue
            target = raw.split("#")[0]
            resolved = (rel_dir / target).resolve()
            if not resolved.exists():
                broken.append(f"{md.relative_to(SKILL_ROOT)} → {raw}")

    checks["internal_links_resolve"] = not broken
    if broken:
        msg = f"{len(broken)} broken internal markdown link(s):"
        for b in broken[:10]:
            msg += f"\n  - {b}"
        if len(broken) > 10:
            msg += f"\n  ... ({len(broken) - 10} more)"
        failures.append(msg)


def check_history_entry_for_current_version(checks: dict, failures: list) -> None:
    skill_version = read_skill_version()
    if skill_version is None:
        checks["history_entry_present"] = False
        return
    history = SKILL_ROOT / "HISTORY.md"
    if not history.exists():
        checks["history_entry_present"] = False
        failures.append("HISTORY.md missing")
        return
    text = history.read_text(encoding="utf-8")
    # Match either "### v2.9.0" or "### v2.9.0 — ..." style headings.
    pattern = re.compile(rf'^###\s+v{re.escape(skill_version)}\b', re.MULTILINE)
    present = bool(pattern.search(text))
    checks["history_entry_present"] = present
    if not present:
        failures.append(
            f"HISTORY.md has no §1 entry for v{skill_version} — required per "
            f"docs/doc-update-protocol.md §Version bump"
        )


def check_latest_snapshot_exists(checks: dict, failures: list) -> None:
    skill_version = read_skill_version()
    if skill_version is None:
        checks["latest_snapshot_exists"] = False
        return
    # Only require snapshot for X.Y.0 minor releases.
    parts = skill_version.split(".")
    is_minor_release = len(parts) >= 3 and parts[2] == "0"
    if not is_minor_release:
        checks["latest_snapshot_exists"] = True
        return

    snapshot = SKILL_ROOT / "docs" / "snapshots" / f"v{skill_version}.md"
    exists = snapshot.exists()
    checks["latest_snapshot_exists"] = exists
    if not exists:
        failures.append(
            f"Minor release v{skill_version} requires snapshot at "
            f"docs/snapshots/v{skill_version}.md — required per "
            f"docs/doc-update-protocol.md §Version bump"
        )


def check_decision_log_indexes_all_adrs(checks: dict, failures: list) -> None:
    decision_log = SKILL_ROOT / "docs" / "decision-log.md"
    if not decision_log.exists():
        checks["decision_log_complete"] = False
        failures.append("docs/decision-log.md missing")
        return
    log_text = decision_log.read_text(encoding="utf-8")
    experiments_dir = SKILL_ROOT / "docs" / "experiments"
    if not experiments_dir.exists():
        checks["decision_log_complete"] = True
        return
    missing: list[str] = []
    for adr in experiments_dir.glob("*/decisions/D*.md"):
        # Skip the template directory.
        if "_template" in adr.parts:
            continue
        adr_stem = adr.stem  # e.g. D001-initial-design
        # Decision-log should reference either the filename (D001-initial-design)
        # or the ADR number in context (D001).
        # We check by filename presence — the link is what matters.
        if adr_stem not in log_text:
            missing.append(str(adr.relative_to(SKILL_ROOT)))
    checks["decision_log_complete"] = not missing
    if missing:
        failures.append(
            f"{len(missing)} ADR(s) not indexed in docs/decision-log.md:\n  - " + "\n  - ".join(missing[:10])
        )


def count_stale_markers(checks: dict) -> dict:
    """Count TODO/FIXME/XXX/WIP markers across docs and references.
    Reported but not failed."""
    counts = {"TODO": 0, "FIXME": 0, "XXX": 0, "WIP": 0}
    scope_dirs = [SKILL_ROOT / "docs", SKILL_ROOT / "references"]
    for d in scope_dirs:
        if not d.exists():
            continue
        for md in d.glob("**/*.md"):
            try:
                text = md.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for marker in counts:
                # Word-boundary match, avoid matching inside identifiers.
                counts[marker] += len(re.findall(rf'\b{marker}\b', text))
    checks["stale_marker_counts"] = counts
    return counts


def main() -> int:
    checks: dict = {}
    failures: list[str] = []

    check_version_consistency(checks, failures)
    check_internal_links(checks, failures)
    check_history_entry_for_current_version(checks, failures)
    check_latest_snapshot_exists(checks, failures)
    check_decision_log_indexes_all_adrs(checks, failures)
    count_stale_markers(checks)

    strict = os.environ.get("DOC_FRESHNESS_STRICT") == "1"

    payload = {
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "mode": "strict" if strict else "non-blocking",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not failures:
        return 0
    return 1 if strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
