"""packets.py — spec manifest + task packets with context budget (CME v3.0 T10).

Ported from kws-codex-plan-executor:
  - scripts/build_spec_manifest.py  → build_manifest() (simplified: accepts spec_text, not a path;
                                      stores section text inline in the manifest dict)
  - scripts/build_task_packet.py    → build_packet() (simplified interface per CME brief;
                                      no decisions register, no unit_manifest, no context_components)

CME simplifications vs CPE originals:
- build_manifest takes spec_text (str) not a Path; no fallback_policy config at manifest level.
- build_manifest stores section "text" directly in each section dict (not just line coords).
- build_packet signature matches the brief exactly: (task, manifest, spec_text, budget_chars).
- budget.used = len(task_body) + Σ len(section text) — NOT json.dumps size estimate.
- budget.status computed pre-trim (sticky "red" if overflow ever occurred).
- trim priority: remove sections with lowest heuristic score first (non-explicit sections only);
  explicit spec_refs sections are never trimmed.
- spec_refs source: task.get("spec_refs") if present; else parsed from task body
  (line matching "Spec Refs: S1, S2" or similar).
- persist() writes <orch_dir>/packets/<task_id>.json (authoritative) + .md (derived view).

Public API
----------
build_manifest(spec_text: str) -> dict
build_packet(task: dict, manifest: dict, spec_text: str, budget_chars: int = 60000) -> dict
persist(packet: dict, orch_dir: str) -> tuple[Path, Path]
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex constants (ported from CPE build_spec_manifest.py)
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
BACKTICK_LITERAL_RE = re.compile(r"`([^`\n]+)`")
CODE_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?\b")
TASK_ID_RE = re.compile(r"\btask[_ -]?\d+(?:[_.]\d+)*\b", re.IGNORECASE)
FENCE_RE = re.compile(r"^(?: {0,3})(?P<marker>`{3,}|~{3,})(?P<suffix>[^\r\n]*)$")
FENCE_CLOSE_SUFFIX_RE = re.compile(r"^[ \t]*$")
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"
COMMENT_LINE_RE = re.compile(r"^(?: {0,3})<!--")
INDENTED_CODE_RE = re.compile(r"^(?: {4,}|\t)")

# Parse "Spec Refs: S1, S2" or "Spec Refs: [S1, S2]" from task body
SPEC_REFS_LINE_RE = re.compile(
    r"(?mi)^[ \t]*(?:\*\*)?Spec[ \t]+Refs?[ \t]*:[ \t]*(?:\*\*)?[ \t]*(?P<value>[^\n]+)[ \t]*$"
)

# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokenize(value: str) -> set[str]:
    return {tok for tok in re.split(r"[^a-z0-9]+", value.lower()) if tok}


def _path_tokens(files: list[str]) -> set[str]:
    tokens: set[str] = set()
    for fp in files:
        tokens.update(_tokenize(fp))
        p = Path(fp)
        tokens.update(_tokenize(p.stem))
        tokens.update(_tokenize(" ".join(p.parts)))
    return tokens


def _task_search_tokens(task: dict) -> set[str]:
    tokens = _path_tokens([f for f in task.get("files", []) if isinstance(f, str)])
    for key in ("title", "body", "acceptance"):
        val = task.get(key)
        if isinstance(val, str):
            tokens.update(_tokenize(val))
    return tokens


# ---------------------------------------------------------------------------
# Markdown visibility filter (ported from CPE build_spec_manifest.py)
# ---------------------------------------------------------------------------


def _read_fence_marker(line: str):
    m = FENCE_RE.match(line)
    if not m:
        return None
    marker = m.group("marker")
    return marker[0], len(marker), m.group("suffix") or ""


def _advance_comment_depth(depth: int, line: str) -> int:
    if depth == 0 and not COMMENT_LINE_RE.match(line):
        return 0
    idx = 0
    active = depth
    while idx < len(line):
        no = line.find(COMMENT_OPEN, idx)
        nc = line.find(COMMENT_CLOSE, idx)
        if no == -1 and nc == -1:
            break
        if no != -1 and (nc == -1 or no < nc):
            active += 1
            idx = no + len(COMMENT_OPEN)
            continue
        if active > 0:
            active -= 1
        idx = nc + len(COMMENT_CLOSE)
    return active


def _visible_heading_lines(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return [(line_number_1based, level, title), ...] for visible headings."""
    headings: list[tuple[int, int, str]] = []
    fence = None
    comment_depth = 0

    for idx, line in enumerate(lines, start=1):
        body = line[:-1] if line.endswith("\n") else line

        if fence is not None:
            marker = _read_fence_marker(body)
            if (marker and marker[0] == fence[0] and marker[1] >= fence[1]
                    and FENCE_CLOSE_SUFFIX_RE.match(marker[2])):
                fence = None
            continue

        if comment_depth > 0 or COMMENT_LINE_RE.match(body):
            comment_depth = _advance_comment_depth(comment_depth, body)
            continue

        if INDENTED_CODE_RE.match(body):
            continue

        marker = _read_fence_marker(body)
        if marker:
            fence = (marker[0], marker[1])
            continue

        m = HEADING_RE.match(body)
        if m:
            headings.append((idx, len(m.group(1)), m.group(2).strip()))

    return headings


def _assign_section_ids(headings: list[tuple[int, int, str]]) -> list[tuple[str, int, int, str]]:
    """Return [(section_id, line_1based, level, title), ...]."""
    stack: list[tuple[int, int]] = []
    child_counts: dict[tuple[int, ...], int] = {}
    assigned: list[tuple[str, int, int, str]] = []

    for line, level, title in headings:
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_key = tuple(n for _, n in stack)
        next_n = child_counts.get(parent_key, 0) + 1
        child_counts[parent_key] = next_n
        stack.append((level, next_n))
        sid = "S" + ".".join(str(n) for _, n in stack)
        assigned.append((sid, line, level, title))

    return assigned


def _section_signals(title: str, text: str) -> dict:
    path_literals = sorted({
        m.group(1).strip()
        for m in BACKTICK_LITERAL_RE.finditer(text)
        if "/" in m.group(1) or "." in m.group(1)
    })
    code_identifiers = sorted({
        item
        for item in CODE_IDENTIFIER_RE.findall(text)
        if "_" in item or "." in item or any(c.isupper() for c in item)
    })
    task_ids = sorted({
        m.group(0).lower().replace(" ", "_").replace("-", "_")
        for m in TASK_ID_RE.finditer(text)
    })
    return {
        "title_tokens": sorted(_tokenize(title)),
        "path_literals": path_literals,
        "code_identifiers": code_identifiers,
        "task_ids": task_ids,
    }


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------


def build_manifest(spec_text: str) -> dict:
    """Split spec into sections (by heading), each with id, content hash, and text.

    Args:
        spec_text: Raw spec Markdown text.

    Returns:
        {
            "schema_version": "1",
            "spec_sha256": str,
            "spec_total_chars": int,
            "sections": {section_id: {"id", "title", "level", "chars", "sha256", "text", "signals"}, ...},
            "section_order": [section_id, ...],
        }
    """
    lines = spec_text.splitlines(keepends=True)
    total_lines = len(lines)
    headings = _visible_heading_lines(lines)
    sections: dict[str, dict] = {}
    section_order: list[str] = []

    if not headings:
        # S0 fallback: entire spec as one section
        sections["S0"] = {
            "id": "S0",
            "title": "document",
            "level": 0,
            "chars": len(spec_text),
            "sha256": _sha256(spec_text),
            "text": spec_text,
            "signals": _section_signals("document", spec_text),
        }
        section_order.append("S0")
    else:
        assigned = _assign_section_ids(headings)
        for idx, (sid, line_start, level, title) in enumerate(assigned):
            # Section spans to the next SAME-OR-HIGHER-level heading (CPE
            # section_end_line semantics), so a parent section INCLUDES its
            # subsections' text.  Default to EOF for the last such section.
            end_line = total_lines
            for _, ns, nl, _ in assigned[idx + 1:]:
                if nl <= level:
                    end_line = ns - 1
                    break

            section_text = "".join(lines[line_start - 1 : end_line])
            sections[sid] = {
                "id": sid,
                "title": title,
                "level": level,
                "chars": len(section_text),
                "sha256": _sha256(section_text),
                "text": section_text,
                "signals": _section_signals(title, section_text),
            }
            section_order.append(sid)

    return {
        "schema_version": "1",
        "spec_sha256": _sha256(spec_text),
        "spec_total_chars": len(spec_text),
        "sections": sections,
        "section_order": section_order,
    }


# ---------------------------------------------------------------------------
# Section scoring (ported from CPE build_task_packet.py)
# ---------------------------------------------------------------------------


def _path_literal_matches(path_literal: str, files: list[str]) -> bool:
    literal = path_literal.strip().strip("/")
    if not literal:
        return False
    for fp in files:
        candidate = fp.strip().strip("/")
        if (candidate == literal
                or candidate.endswith("/" + literal)
                or literal.endswith("/" + candidate)):
            return True
    return False


def _score_section(task: dict, section: dict) -> tuple[int, list[str]]:
    """Return (score, reasons) for a section vs task."""
    files = [f for f in task.get("files", []) if isinstance(f, str)]
    search_tokens = _task_search_tokens(task)
    signals = section.get("signals") if isinstance(section.get("signals"), dict) else {}
    score = 0
    reasons: list[str] = []

    for pl in signals.get("path_literals", []):
        if _path_literal_matches(str(pl), files):
            score += 8
            reasons.append("path_literal")
            break

    identifiers = set(signals.get("code_identifiers", []))
    if identifiers and identifiers.intersection(search_tokens):
        score += 4
        reasons.append("code_identifier")

    title_tokens = set(signals.get("title_tokens", [])) or _tokenize(str(section.get("title", "")))
    overlap = title_tokens.intersection(search_tokens)
    if title_tokens and title_tokens.issubset(search_tokens):
        score += 2
        reasons.append("title_token")
    elif overlap:
        score += 1
        reasons.append("partial_title_token")

    task_ids = set(signals.get("task_ids", []))
    if str(task.get("id", "")).lower() in task_ids:
        score += 6
        reasons.append("task_id")

    return score, reasons


def _heuristic_sections(task: dict, manifest: dict) -> list[str]:
    """Return list of section_ids with score >= 2 (file/title/task_id signal match).

    CPE early-exit guard: if the task yields no path tokens (no files / no useful
    tokens), return [] rather than false-matching sections on generic title-word
    overlap (e.g. a task titled "Overview" matching any "overview" section).
    """
    if not _path_tokens([f for f in task.get("files", []) if isinstance(f, str)]):
        return []
    sections = manifest.get("sections", {})
    matched: list[str] = []
    for sid in manifest.get("section_order", []):
        section = sections.get(sid, {})
        score, _ = _score_section(task, section)
        if score >= 2:
            matched.append(sid)
    return matched


def _heuristic_scored(task: dict, manifest: dict) -> list[dict]:
    """Return sorted list of {section_id, score, signals} for ALL sections with score > 0."""
    sections = manifest.get("sections", {})
    result = []
    for sid in manifest.get("section_order", []):
        section = sections.get(sid, {})
        score, reasons = _score_section(task, section)
        if score > 0:
            result.append({"section_id": sid, "score": score, "signals": reasons})
    result.sort(key=lambda item: (-item["score"], item["section_id"]))
    return result


# ---------------------------------------------------------------------------
# spec_refs extraction from task body
# ---------------------------------------------------------------------------


def _parse_spec_refs_from_body(body: str) -> list[str]:
    """Extract section ids from 'Spec Refs: S1, S2' line in task body."""
    m = SPEC_REFS_LINE_RE.search(body)
    if not m:
        return []
    raw = m.group("value")
    # Strip brackets, quotes, markdown formatting
    raw = raw.strip().strip("[]")
    parts = re.split(r"[,\s]+", raw)
    refs: list[str] = []
    for p in parts:
        p = p.strip().strip('"\'')
        if re.match(r"^S\d+(\.\d+)*$", p):
            refs.append(p)
    return refs


# ---------------------------------------------------------------------------
# Section resolution (like CPE resolve_sections but simplified)
# ---------------------------------------------------------------------------


def _resolve_sections(task: dict, manifest: dict) -> tuple[list[str], bool, str | None, str | None]:
    """Resolve which spec sections to include for a task.

    Returns:
        (section_ids, fallback_used, fallback_reason, next_action)

    fallback_used=True means no task-specific match was found.
    When fallback_used=True, all sections are included (full spec context).
    """
    sections = manifest.get("sections", {})

    # 1. Explicit spec_refs from task dict (set programmatically)
    explicit = [s for s in task.get("spec_refs", []) if isinstance(s, str) and s.strip()]

    # 2. Parse from task body ("Spec Refs: S1, S2")
    if not explicit:
        explicit = _parse_spec_refs_from_body(task.get("body", ""))

    if explicit:
        # Validate refs exist
        valid = [sid for sid in explicit if sid in sections]
        if valid:
            return valid, False, None, None

    # 3. Heuristic file-section matching
    matched = _heuristic_sections(task, manifest)
    if matched:
        return matched, False, None, None

    # 4. Fallback: include all sections
    candidate_scores = _heuristic_scored(task, manifest)
    refs = [item["section_id"] for item in candidate_scores[:3]]

    files = [f for f in task.get("files", []) if isinstance(f, str) and f.strip()]
    if candidate_scores or files:
        reason = "weak_heuristic_match"
    elif not explicit:
        reason = "missing_spec_refs"
    else:
        reason = "manifest_gap"

    if refs:
        next_action = "Add explicit spec_refs to the plan task using one of: " + ", ".join(refs)
    elif reason == "missing_spec_refs":
        next_action = "Add explicit spec_refs to the plan task."
    elif reason == "manifest_gap":
        next_action = "Update spec_manifest task_to_sections or section ids for this task."
    else:
        next_action = "Review spec mapping evidence and add task-specific spec_refs."

    all_ids = manifest.get("section_order", [])
    return all_ids, True, reason, next_action


# ---------------------------------------------------------------------------
# Budget computation
# ---------------------------------------------------------------------------

YELLOW_THRESHOLD = 0.7


def _compute_used(task_body: str, spec_sections: list[dict]) -> int:
    return len(task_body) + sum(len(s["text"]) for s in spec_sections)


def _budget_status_pre_trim(used: int, limit: int) -> str:
    """Compute status based on pre-trim used value."""
    if used > limit:
        return "red"
    if used > int(limit * YELLOW_THRESHOLD):
        return "yellow"
    return "green"


# ---------------------------------------------------------------------------
# build_packet
# ---------------------------------------------------------------------------


def build_packet(
    task: dict,
    manifest: dict,
    spec_text: str,
    budget_chars: int = 60000,
) -> dict:
    """Build a compact per-task context packet.

    Args:
        task:         planparse.parse() task dict (id, title, files, body, etc.)
        manifest:     build_manifest() output
        spec_text:    raw spec text (to extract section text by id)
        budget_chars: character budget limit (default 60000)

    Returns:
        {
            "task_id": str,
            "task_body": str,
            "files": [str],
            "spec_sections": [{"id": str, "text": str}, ...],
            "fallback_used": bool,
            "fallback_reason": str | None,
            "next_action": str | None,
            "budget": {"limit": int, "used": int, "status": "green"|"yellow"|"red"},
        }
    """
    task_id = str(task.get("id", ""))
    task_body = task.get("body", "") or ""
    files = [f for f in task.get("files", []) if isinstance(f, str)]

    section_ids, fallback_used, fallback_reason_val, next_action = _resolve_sections(task, manifest)

    sections_dict = manifest.get("sections", {})
    spec_sections = [
        {"id": sid, "text": sections_dict[sid]["text"]}
        for sid in section_ids
        if sid in sections_dict
    ]

    # Pre-trim budget computation
    pre_trim_used = _compute_used(task_body, spec_sections)
    status = _budget_status_pre_trim(pre_trim_used, budget_chars)

    # Trim if red (status stays red even after trim — sticky verdict)
    if status == "red":
        # Remove sections in reverse priority order (lowest score first).
        # Explicit spec_refs sections are protected from trimming.
        explicit = [s for s in task.get("spec_refs", []) if isinstance(s, str)]
        if not explicit:
            explicit = _parse_spec_refs_from_body(task_body)

        explicit_set = set(explicit)

        # Score all included sections
        scored = []
        for sec in spec_sections:
            sid = sec["id"]
            if sid in explicit_set:
                score = 999  # protected
            else:
                sc, _ = _score_section(task, sections_dict.get(sid, {}))
                score = sc
            scored.append((score, sec))

        # Sort by score ascending so we can pop from the end (lowest score first)
        scored.sort(key=lambda item: item[0])

        # Trim from lowest-score sections until within budget
        trimmed_sections = [s for _, s in scored]
        while trimmed_sections and _compute_used(task_body, trimmed_sections) > budget_chars:
            # Remove lowest-score non-explicit section
            for i, (sc, sec) in enumerate(scored):
                if sec["id"] not in explicit_set:
                    scored.pop(i)
                    trimmed_sections = [s for _, s in scored]
                    break
            else:
                # All remaining are explicit/protected; can't trim further
                break

        # Re-sort back to section_order
        order = manifest.get("section_order", [])
        order_idx = {sid: i for i, sid in enumerate(order)}
        trimmed_sections.sort(key=lambda s: order_idx.get(s["id"], 9999))
        spec_sections = trimmed_sections

        if not fallback_reason_val:
            fallback_reason_val = "budget_trim"
        else:
            fallback_reason_val = fallback_reason_val + "; budget_trim"

    post_trim_used = _compute_used(task_body, spec_sections)

    return {
        "task_id": task_id,
        "task_body": task_body,
        "files": files,
        "spec_sections": spec_sections,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason_val,
        "next_action": next_action,
        "budget": {
            "limit": budget_chars,
            "used": post_trim_used,
            "status": status,  # pre-trim status (sticky red)
        },
    }


# ---------------------------------------------------------------------------
# persist
# ---------------------------------------------------------------------------


def persist(packet: dict, orch_dir: str) -> tuple[Path, Path]:
    """Write packet to <orch_dir>/packets/<task_id>.json and .md.

    The .json file is authoritative; the .md is a human-readable derived view.

    Returns:
        (json_path, md_path)
    """
    task_id = packet["task_id"]
    packets_dir = Path(orch_dir) / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)

    json_path = packets_dir / f"{task_id}.json"
    md_path = packets_dir / f"{task_id}.md"

    json_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Human-readable markdown view (derived, non-authoritative)
    budget = packet["budget"]
    sections_md = ""
    for sec in packet.get("spec_sections", []):
        sections_md += f"\n### Section {sec['id']}\n\n{sec['text']}\n"

    md_content = f"""\
# Task Packet: {task_id}

**Budget:** {budget['used']}/{budget['limit']} chars ({budget['status'].upper()})
**Fallback used:** {packet['fallback_used']}
**Fallback reason:** {packet['fallback_reason'] or 'none'}
**Next action:** {packet['next_action'] or 'none'}

## Task Body

{packet['task_body']}

## Files

{chr(10).join(f'- {f}' for f in packet['files']) or '(none)'}

## Spec Sections
{sections_md}
"""
    md_path.write_text(md_content, encoding="utf-8")

    return json_path, md_path


# ---------------------------------------------------------------------------
# load_packet
# ---------------------------------------------------------------------------


def load_packet(orch_dir: str, task_id: str) -> dict | None:
    """Load a persisted packet from <orch_dir>/packets/<task_id>.json.

    Returns None if the file does not exist.
    """
    json_path = Path(orch_dir) / "packets" / f"{task_id}.json"
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
