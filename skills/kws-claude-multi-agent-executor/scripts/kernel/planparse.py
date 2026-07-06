"""planparse.py — deterministic plan parser for CME v3.0.

Ported from kws-codex-plan-executor/scripts/parse_plan.py.

CME adaptations vs CPE original:
- Task id is string ``task_<N>`` (CPE also produces this via _task_id_from_number).
- ``body`` field: raw text after the task header line.
- ``dependencies`` is ``list[int]`` (task numbers), not CPE's ``list[str]`` task ids.
- ``serial`` and ``resource_key`` fields parsed from the task body.
- Accumulates errors instead of calling sys.exit() (_die → error accumulation).
- No repo_root — path validation is purely lexical (no filesystem access).
- No CLI wrapper — kernel calls parse() as an internal function only.

Public interface::

    parse(text: str) -> {
        "header_level": 2 | 3,
        "tasks": [{"id": "task_1", "number": 1, "title": str,
                   "files": [str], "dependencies": [int],
                   "acceptance": str | None,
                   "serial": bool, "resource_key": str | None,
                   "body": str}],
        "errors": [str],
    }
"""

from __future__ import annotations

import posixpath
import re
from pathlib import PurePosixPath

# ---------------------------------------------------------------------------
# Compiled regular expressions (ported from CPE parse_plan.py)
# ---------------------------------------------------------------------------

TASK_RE = re.compile(
    r"(?m)^(#{2,4})[ \t]+(?:Task|작업)[ \t]+(\d+(?:\.\d+)*)[ \t]*(?::|-|–|—)[ \t]*(.+?)[ \t]*$"
)
FENCE_RE = re.compile(r"^(?: {0,3})(?P<marker>`{3,}|~{3,})(?P<suffix>[^\r\n]*)$")
FENCE_CLOSE_SUFFIX_RE = re.compile(r"^[ \t]*$")
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"
COMMENT_LINE_RE = re.compile(r"^(?: {0,3})<!--")
INDENTED_CODE_RE = re.compile(r"^(?: {4,}|\t)")

FILES_HEADING_RE = re.compile(
    r"(?mi)^[ \t]*(?:\*\*)?"
    r"(?:Files|Affected files|Modified files|Changed files|수정 파일|변경 파일|대상 파일|파일)"
    r"[ \t]*:[ \t]*(?:\*\*)?[ \t]*$"
)

AC_COMMAND_FENCE_RE = re.compile(
    r"(?mis)^\s*(?:#{2,5}\s*)?(?:Acceptance(?: Criteria)?|Verification|Done when|검증|완료 기준|Eval)(?:\b|[ \t]*:).*?"
    r"```(?:bash|sh|shell)?\s*\n(?P<body>.*?)\n```"
)
RUN_COMMAND_FENCE_RE = re.compile(
    r"(?mis)^[ \t]*(?:Run|실행)[ \t]*:[^\n]*\n\s*```(?:bash|sh|shell)?\s*\n(?P<body>.*?)\n```"
)
ANY_COMMAND_FENCE_RE = re.compile(
    r"(?mis)^[ \t]*```(?:bash|sh|shell)?\s*\n(?P<body>.*?)\n```"
)

DEPENDS_RE = re.compile(
    r"(?mi)^[ \t]*(?:\*\*)?"
    r"(?:Depends on|Depends|Dependencies|의존|선행 작업)"
    r"[ \t]*:[ \t]*(?P<value>.+?)[ \t]*(?:\*\*)?[ \t]*$"
)

YAML_TASK_RE = re.compile(
    r"```yaml[ \t]+(?:agentrunway|waygent)-task\s*\n(?P<body>.*?)\n```", re.S
)
YAML_FILE_CLAIM_LINE_RE = re.compile(r"(?m)^\s*-\s+path:\s*(?P<path>.+?)\s*$")
YAML_FILE_CLAIM_SCALAR_RE = re.compile(r"^\s*-\s+(?P<path>.+?)\s*$")
YAML_TOP_LEVEL_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*:\s*")
YAML_ACCEPTANCE_KEY_RE = re.compile(r"^(?:verify|acceptance|verification):\s*(?P<inline>.*)$")
YAML_VERIFY_RE = re.compile(r"(?m)^(?:verify|acceptance|verification):\s*(?:$|.+)")

FILE_LINE_RE = re.compile(r"^\s*-\s+(?P<value>.+?)\s*$")
FILE_PREFIX_RE = re.compile(
    r"^(?:"
    r"Create|Modify|Read|Delete|Move|Update|Add|New file|"
    r"생성|수정|읽기|삭제|이동|변경|갱신|새\s*파일(?:\s*또는\s*확장)?|신규"
    r")\s*:?\s+",
    re.IGNORECASE,
)
BACKTICK_PATH_RE = re.compile(r"`([^`\n]+)`")

# serial: true — matches "serial: true" anywhere in visible body text
SERIAL_RE = re.compile(r"(?mi)^[ \t]*serial[ \t]*:[ \t]*true[ \t]*$")

# **Resource Key:** slug or Resource Key: slug
RESOURCE_KEY_RE = re.compile(
    r"(?mi)^[ \t]*(?:\*\*)?Resource[ \t]+Key[ \t]*:[ \t]*(?:\*\*)?[ \t]*(?P<slug>[^\n*]+?)[ \t]*(?:\*\*)?[ \t]*$"
)


# ---------------------------------------------------------------------------
# Markdown visibility filter (ported from CPE)
# ---------------------------------------------------------------------------

def _read_fence_marker(line: str):
    match = FENCE_RE.match(line)
    if not match:
        return None
    marker = match.group("marker")
    return marker[0], len(marker), match.group("suffix") or ""


def _advance_comment_depth(depth: int, line: str) -> int:
    if depth == 0 and not COMMENT_LINE_RE.match(line):
        return 0
    index = 0
    active = depth
    while index < len(line):
        next_open = line.find(COMMENT_OPEN, index)
        next_close = line.find(COMMENT_CLOSE, index)
        if next_open == -1 and next_close == -1:
            break
        if next_open != -1 and (next_close == -1 or next_open < next_close):
            active += 1
            index = next_open + len(COMMENT_OPEN)
            continue
        if active > 0:
            active -= 1
        index = next_close + len(COMMENT_CLOSE)
    return active


def _visible_markdown(markdown: str) -> str:
    """Blank fenced-code and HTML-comment regions; preserve line positions."""
    visible: list[str] = []
    fence = None
    comment_depth = 0

    for line in markdown.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        newline = "\n" if line.endswith("\n") else ""

        if fence is not None:
            marker = _read_fence_marker(body)
            if (
                marker
                and marker[0] == fence[0]
                and marker[1] >= fence[1]
                and FENCE_CLOSE_SUFFIX_RE.match(marker[2])
            ):
                fence = None
            visible.append(newline)
            continue

        if comment_depth > 0 or COMMENT_LINE_RE.match(body):
            comment_depth = _advance_comment_depth(comment_depth, body)
            visible.append(newline)
            continue

        if INDENTED_CODE_RE.match(body):
            visible.append(newline)
            continue

        marker = _read_fence_marker(body)
        if marker:
            fence = (marker[0], marker[1])
            visible.append(newline)
            continue

        visible.append(line)

    return "".join(visible)


# ---------------------------------------------------------------------------
# Path validation — purely lexical, no filesystem access
# ---------------------------------------------------------------------------

def _check_path(raw: str) -> tuple[str | None, str | None]:
    """Return (normalized_posix, error_suffix) where error_suffix is set on rejection.

    Strips backticks, comments (#), and rename arrows (a -> b) from raw.
    Rejects absolute paths and paths that escape the repo root via '..' after
    normalization (posixpath.normpath collapses mid-path escapes like a/../../x).
    Returns (None, error_suffix) on rejection — the path is NOT added to files.
    """
    candidate = raw.strip()
    if not candidate:
        return None, "empty_path"

    # rename: "a -> b" → take the destination
    if " -> " in candidate:
        candidate = candidate.split(" -> ", 1)[-1].strip()

    # strip fragment
    if "#" in candidate:
        candidate = candidate.split("#", 1)[0].strip()

    # absolute path
    if candidate.startswith("/"):
        return None, candidate

    # lexical normalization: posixpath.normpath correctly collapses mid-path .. segments
    # e.g. "a/../../escape.py" → "../escape.py" → rejected
    try:
        clean = posixpath.normpath(candidate)
    except Exception:
        return None, candidate

    # check for leading .. after normalization
    if clean.startswith(".."):
        return None, candidate

    return clean, None


# ---------------------------------------------------------------------------
# Files-block extraction (ported from CPE, but uses lexical path check)
# ---------------------------------------------------------------------------

def _extract_files_from_body(
    body_text: str, task_num: int, errors: list[str]
) -> tuple[list[str], bool]:
    """Extract files from a task body using FILES_HEADING_RE aliases.

    Returns (files, has_files_block).
    """
    match = FILES_HEADING_RE.search(body_text)
    if not match:
        return [], False

    files: list[str] = []
    for line in body_text[match.end():].splitlines():
        stripped = line.strip()
        if not stripped:
            if files:
                break
            continue
        if stripped.startswith("#") or (stripped.startswith("**") and stripped.endswith("**")):
            break
        item = FILE_LINE_RE.match(line)
        if not item:
            if files:
                break
            continue
        raw_value = item.group("value").strip()
        # backtick extraction
        backtick_match = BACKTICK_PATH_RE.search(raw_value)
        value = backtick_match.group(1).strip() if backtick_match else FILE_PREFIX_RE.sub("", raw_value).strip()
        if value.lower() in {"n/a", "none"}:
            continue
        clean, err = _check_path(value)
        if err is not None:
            errors.append(f"task_{task_num}_out_of_repo_path:{err}")
        else:
            if clean and clean not in files:
                files.append(clean)

    return sorted(dict.fromkeys(files)), True


# ---------------------------------------------------------------------------
# YAML waygent-task / agentrunway-task block file_claims extraction
# ---------------------------------------------------------------------------

def _clean_yaml_scalar(value: str) -> str:
    return value.strip().strip("'\"")


def _extract_yaml_file_claims(yaml_body: str, task_num: int, errors: list[str]) -> list[str]:
    """Extract file_claims from a yaml waygent-task/agentrunway-task block."""
    files: list[str] = []

    # path: <value> style
    for item in YAML_FILE_CLAIM_LINE_RE.finditer(yaml_body):
        raw = _clean_yaml_scalar(item.group("path"))
        clean, err = _check_path(raw)
        if err is not None:
            errors.append(f"task_{task_num}_out_of_repo_path:{err}")
        elif clean and clean not in files:
            files.append(clean)

    # walk file_claims: section for bare scalar items
    in_file_claims = False
    for line in yaml_body.splitlines():
        stripped = line.strip()
        if YAML_TOP_LEVEL_KEY_RE.match(line):
            in_file_claims = stripped.startswith("file_claims:")
            continue
        if in_file_claims:
            item = YAML_FILE_CLAIM_SCALAR_RE.match(line)
            if item:
                value = _clean_yaml_scalar(item.group("path"))
                if value and not value.startswith("{") and not value.startswith("path:"):
                    clean, err = _check_path(value)
                    if err is not None:
                        errors.append(f"task_{task_num}_out_of_repo_path:{err}")
                    elif clean and clean not in files:
                        files.append(clean)

    return sorted(dict.fromkeys(files))


def _extract_yaml_task_files(raw_body: str, task_num: int, errors: list[str]) -> list[str]:
    """If raw task body contains a yaml waygent-task/agentrunway-task block, extract file_claims."""
    match = YAML_TASK_RE.search(raw_body)
    if not match:
        return []
    return _extract_yaml_file_claims(match.group("body"), task_num, errors)


# ---------------------------------------------------------------------------
# Acceptance criteria extraction (ported from CPE)
# ---------------------------------------------------------------------------

def _commands_from_fence_body(body: str) -> str | None:
    commands = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return "\n".join(commands) if commands else None


def _extract_yaml_acceptance(yaml_body: str) -> str | None:
    lines = yaml_body.splitlines()
    for index, line in enumerate(lines):
        match = YAML_ACCEPTANCE_KEY_RE.match(line)
        if not match:
            continue
        inline = _clean_yaml_scalar(match.group("inline"))
        if inline:
            return inline
        commands: list[str] = []
        for following in lines[index + 1:]:
            fstripped = following.strip()
            if not fstripped:
                continue
            if YAML_TOP_LEVEL_KEY_RE.match(following):
                break
            if fstripped.startswith("- "):
                fstripped = fstripped[2:].strip()
            if fstripped and not fstripped.startswith("#"):
                commands.append(_clean_yaml_scalar(fstripped))
        return "\n".join(commands) if commands else None
    return None


def _extract_acceptance(body: str) -> str | None:
    """Extract shell command(s) from acceptance/verification section in a task body."""
    # 1. yaml block acceptance key
    yaml_match = YAML_TASK_RE.search(body)
    if yaml_match:
        cmd = _extract_yaml_acceptance(yaml_match.group("body"))
        if cmd:
            return cmd

    # 2. Acceptance Criteria / Verification section with a shell fence
    m = AC_COMMAND_FENCE_RE.search(body)
    if m:
        return _commands_from_fence_body(m.group("body"))

    # 3. Run: block (last one)
    run_matches = list(RUN_COMMAND_FENCE_RE.finditer(body))
    if run_matches:
        return _commands_from_fence_body(run_matches[-1].group("body"))

    # 4. Any shell fence (first)
    m = ANY_COMMAND_FENCE_RE.search(body)
    if m:
        return _commands_from_fence_body(m.group("body"))

    return None


# ---------------------------------------------------------------------------
# Depends-on extraction → list[int]
# ---------------------------------------------------------------------------

def _extract_depends_on(body: str) -> list[int]:
    """Return a sorted list of dependency task numbers (ints) from the task body."""
    match = DEPENDS_RE.search(body)
    if not match:
        return []
    values: list[int] = []
    for item in re.split(r"[, \[\]]+", match.group("value").strip()):
        normalized = item.strip().removeprefix("task_").replace("_", ".")
        # Plain integers only; dotted sub-task ids like "1.1" are excluded.
        if re.fullmatch(r"\d+", normalized):
            values.append(int(normalized))
    seen: set[int] = set()
    result: list[int] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return sorted(result)


# ---------------------------------------------------------------------------
# serial / resource_key extraction
# ---------------------------------------------------------------------------

def _extract_serial(body: str) -> bool:
    return bool(SERIAL_RE.search(body))


def _extract_resource_key(body: str) -> str | None:
    m = RESOURCE_KEY_RE.search(body)
    if not m:
        return None
    return m.group("slug").strip()


# ---------------------------------------------------------------------------
# Header-level detection
# ---------------------------------------------------------------------------

def _detect_header_level(matches) -> int:
    """Return 3 if any match uses ###, else 2.  Prefer ### per CME spec."""
    for m in matches:
        if len(m.group(1)) == 3:
            return 3
    return 2


# ---------------------------------------------------------------------------
# Line-number helpers (ported from CPE)
# ---------------------------------------------------------------------------

def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _slice_lines(text: str, start_line: int, end_line: int) -> str:
    lines = text.splitlines(keepends=True)
    return "".join(lines[max(start_line - 1, 0) : max(end_line, start_line - 1)])


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def parse(text: str) -> dict:
    """Parse a Markdown implementation plan and return structured task data.

    Args:
        text: Raw Markdown text of the plan.

    Returns:
        {
            "header_level": 2 | 3,
            "tasks": [...],
            "errors": [...],
        }
    """
    errors: list[str] = []
    tasks: list[dict] = []

    markdown = _visible_markdown(text)
    matches = list(TASK_RE.finditer(markdown))

    if not matches:
        errors.append("no_task_headers")
        return {"header_level": 3, "tasks": [], "errors": errors}

    header_level = _detect_header_level(matches)

    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)

        # Slice body from VISIBLE markdown (files/depends/serial/resource_key headings are visible)
        body_text = markdown[body_start:body_end]

        # Slice raw body from ORIGINAL text using line numbers from visible markdown.
        # _visible_markdown preserves line endings, so line numbers agree with original text.
        # body_start = match.end() points AT the header line's trailing "\n", so it counts
        # 0 newlines before it and _line_number returns the HEADER's own line number.
        # Add 1 so the body starts on the FIRST line AFTER the header (spec: "헤더 이후 원문").
        # body_end is the offset of the next header's first character (or end of text).
        # Subtract 1 from raw_body_end_line so the next header line is excluded from body.
        raw_body_start_line = _line_number(markdown, body_start) + 1
        if index + 1 < len(matches):
            next_header_line = _line_number(markdown, matches[index + 1].start())
            raw_body_end_line = next_header_line - 1
        else:
            raw_body_end_line = _line_number(markdown, len(markdown))
        raw_body = _slice_lines(text, raw_body_start_line, raw_body_end_line)

        task_num_str = match.group(2)
        if task_num_str.isdigit():
            task_num = int(task_num_str)
        else:
            # sub-task like "1.1" — use first numeric part
            task_num = int(task_num_str.split(".")[0])
        task_id = "task_" + task_num_str.replace(".", "_")

        # Files: prefer explicit Files block (visible), fall back to yaml file_claims (raw)
        files, has_files = _extract_files_from_body(body_text, task_num, errors)
        if not files:
            yaml_files = _extract_yaml_task_files(raw_body, task_num, errors)
            if yaml_files:
                files = yaml_files
                has_files = True

        if not has_files:
            errors.append(f"task_{task_num}_missing_files")

        # Acceptance criteria comes from raw body (shell fences are stripped in visible)
        acceptance = _extract_acceptance(raw_body)
        dependencies = _extract_depends_on(body_text)
        serial = _extract_serial(body_text)
        resource_key = _extract_resource_key(body_text)

        tasks.append({
            "id": task_id,
            "number": task_num,
            "title": match.group(3).strip(),
            "files": files,
            "dependencies": dependencies,
            "acceptance": acceptance,
            "serial": serial,
            "resource_key": resource_key,
            "body": raw_body.strip(),
        })

    return {
        "header_level": header_level,
        "tasks": tasks,
        "errors": errors,
    }
