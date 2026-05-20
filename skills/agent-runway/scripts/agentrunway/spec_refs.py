from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from .plan_parser import parse_spec_manifest


NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\b")


@dataclass(frozen=True)
class SpecRefResolution:
    input_ref: str
    canonical_ref: str | None
    status: Literal["resolved", "unresolved"]
    title: str | None = None
    text: str = ""
    suggestion: str | None = None


class SpecRefResolver:
    def __init__(self, sections: Mapping[str, Mapping[str, object]]) -> None:
        self._sections = dict(sections)
        self._aliases = self._build_aliases(self._sections)

    @classmethod
    def from_spec(cls, spec_path: Path) -> "SpecRefResolver":
        manifest = parse_spec_manifest(spec_path)
        sections = manifest.sections if hasattr(manifest, "sections") else manifest["sections"]
        return cls(sections)

    def resolve_one(self, input_ref: str) -> SpecRefResolution:
        lookup_ref = input_ref.strip()
        canonical_ref = self._aliases.get(lookup_ref)
        if canonical_ref is None:
            return SpecRefResolution(
                input_ref=input_ref,
                canonical_ref=None,
                status="unresolved",
                suggestion=self._suggest(lookup_ref),
            )

        section = self._sections[canonical_ref]
        return SpecRefResolution(
            input_ref=input_ref,
            canonical_ref=canonical_ref,
            status="resolved",
            title=str(section.get("title", "")) or None,
            text=str(section.get("text", "")),
        )

    @staticmethod
    def _build_aliases(sections: Mapping[str, Mapping[str, object]]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for section_id, section in sections.items():
            aliases[section_id] = section_id

        for section_id, section in sections.items():
            if section_id.startswith("S1."):
                rootless = section_id.removeprefix("S1.")
                aliases.setdefault(f"S{rootless}", section_id)
                aliases.setdefault(rootless, section_id)

            title_number = NUMBERED_HEADING_RE.match(str(section.get("title", "")))
            if title_number:
                numbered = title_number.group(1)
                aliases.setdefault(f"S{numbered}", section_id)
                aliases.setdefault(numbered, section_id)

        return aliases

    def _suggest(self, input_ref: str) -> str | None:
        candidates = sorted(self._aliases)
        matches = difflib.get_close_matches(input_ref, candidates, n=1, cutoff=0.5)
        return matches[0] if matches else (candidates[0] if candidates else None)
