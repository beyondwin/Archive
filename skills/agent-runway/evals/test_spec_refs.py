from __future__ import annotations

from pathlib import Path

import pytest

from agentrunway.spec_refs import SpecRefResolver


@pytest.fixture()
def spec_path(tmp_path: Path) -> Path:
    path = tmp_path / "spec.md"
    path.write_text(
        "# AgentRunway Trust Hardening\n\n"
        "## 1. Overview\n\n"
        "Overview text.\n\n"
        "## 2. Runner\n\n"
        "Runner text.\n\n"
        "## 3. Workers\n\n"
        "Worker text.\n\n"
        "## 4. Review\n\n"
        "Review text.\n\n"
        "## 5. Verification\n\n"
        "Verification text.\n\n"
        "## 6. Spec References\n\n"
        "Spec reference text.\n\n"
        "### 6.1 Manifest\n\n"
        "Manifest text.\n\n"
        "### 6.2 Contract\n\n"
        "Contract text.\n\n"
        "### 6.3 Canonical Resolver\n\n"
        "Resolver text.\n\n"
        "## 7. Coverage\n\n"
        "Coverage text.\n\n"
        "## 8. Errors\n\n"
        "Errors text.\n\n"
        "## 9. Tests\n\n"
        "Tests text.\n\n"
        "## 10. Acceptance\n\n"
        "Acceptance text.\n\n"
        "### 10.3 Heading Number\n\n"
        "Heading-number text.\n",
        encoding="utf-8",
    )
    return path


def test_resolves_canonical_and_alias_refs(spec_path: Path) -> None:
    resolver = SpecRefResolver.from_spec(spec_path)

    assert resolver.resolve_one("S1.6.3").canonical_ref == "S1.6.3"
    assert resolver.resolve_one("S6.3").canonical_ref == "S1.6.3"
    assert resolver.resolve_one("6.3").canonical_ref == "S1.6.3"


def test_resolved_refs_include_title_and_text(spec_path: Path) -> None:
    resolver = SpecRefResolver.from_spec(spec_path)

    result = resolver.resolve_one("6.3")

    assert result.status == "resolved"
    assert result.input_ref == "6.3"
    assert result.canonical_ref == "S1.6.3"
    assert result.title == "6.3 Canonical Resolver"
    assert "Resolver text." in result.text


def test_unresolved_refs_include_suggestions(spec_path: Path) -> None:
    resolver = SpecRefResolver.from_spec(spec_path)

    result = resolver.resolve_one("6.30")

    assert result.status == "unresolved"
    assert result.input_ref == "6.30"
    assert result.suggestion is not None


def test_heading_number_refs_remain_supported(spec_path: Path) -> None:
    resolver = SpecRefResolver.from_spec(spec_path)

    assert resolver.resolve_one("S10.3").canonical_ref == "S1.10.1"
