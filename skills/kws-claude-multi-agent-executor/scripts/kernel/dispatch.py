"""dispatch.py — prompt assembly and headless-first command generation (CME v3.0 T7).

Turns a `dispatch` action from transitions.decide() into concrete dispatch
materials: a written prompt file and a `claude -p` shell command (or Agent-tool
materials when transport is "agent").

Public API
----------
build(state, action, skill_dir, orch_dir) -> dict
    Assemble the role-specific prompt, write it to disk, and return the dispatch
    dict with command (or agent_instruction) + all related paths.

T10 seam
--------
Currently uses state["tasks"][task_id]["body"] for task body and a spec stub for
spec content.  T10 will inject packet paths and richer context; the insertion
points are marked with:  # <<T10: inject packet paths here>>
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────────

MODEL_MAP: dict[str, str] = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-8",
}

# Default model for sub-agents (implementer uses implementer_model; others sonnet).
DEFAULT_MODEL_KEY = "sonnet"

# Role → schema filename (under references/_schemas/)
ROLE_SCHEMA: dict[str, str] = {
    "implementer": "implementer_result.schema.json",
    "reviewer": "reviewer_result.schema.json",
    "verifier": "verifier_result.schema.json",
    "docs_updater": "docs_updater_result.schema.json",
    "plan_reviewer": "plan_reviewer_result.schema.json",
}

# Role → prompt filename (relative to references/) — handles non-standard names
ROLE_PROMPT_FILE: dict[str, str] = {
    "implementer": "implementer-prompt.md",
    "reviewer": "reviewer-prompt.md",
    "verifier": "verifier-prompt.md",
    "docs_updater": "docs-updater-prompts.md",
    "plan_reviewer": "plan-reviewer-prompt.md",
}

# Role → dispatch_config gate key that controls transport.
# If state.dispatch_config[gate] == "agent", use agent transport.
ROLE_GATE: dict[str, str] = {
    "implementer": "implementer",
    "reviewer": "reviewer",
    "verifier": "verifier_per_task",
    "docs_updater": "docs_updater_phase",
    "plan_reviewer": "plan_reviewer",
}

# SCAFFOLD/PAYLOAD marker constants (match validate_scaffold_split.py)
SCAFFOLD_BEGIN = "<!-- SCAFFOLD_BEGIN -->"
SCAFFOLD_END = "<!-- SCAFFOLD_END -->"
PAYLOAD_BEGIN = "<!-- PAYLOAD_BEGIN -->"
PAYLOAD_END = "<!-- PAYLOAD_END -->"

# Placeholder detection: {letter...} but NOT {" (JSON object) or {# (template comments)
# Matches substitutable tokens like {task_size}, {context_slice}, {IF ...:}
PLACEHOLDER_RE = re.compile(r"\{[A-Za-z][^{}\n]*\}")

# Conditional block markers in templates — lines of the form {IF ...:}
IF_BLOCK_RE = re.compile(r"^\{IF\s+.+?\}\s*$")

OUTPUT_CONTRACT = """\n\n## Output contract\n\nYour final response MUST be a single schema-conforming JSON object. Do not include any text outside the JSON. The response is parsed directly by the orchestrator and validated against the role schema.\n"""


# ── Template loading ──────────────────────────────────────────────────────────

def _template_path(role: str, skill_dir: str) -> Path:
    filename = ROLE_PROMPT_FILE.get(role, f"{role}-prompt.md")
    return Path(skill_dir) / "references" / filename


def _load_template_body(role: str, skill_dir: str) -> tuple[str, bool]:
    """Return (body_text, has_scaffold_markers).

    For roles with SCAFFOLD/PAYLOAD markers, body_text is the entire file
    content (markers included) so we can preserve them.
    For roles without markers (implementer, reviewer), body_text is the
    content extracted from inside the 4-backtick fence.
    """
    path = _template_path(role, skill_dir)
    text = path.read_text(encoding="utf-8")

    # Detect scaffold markers
    has_markers = SCAFFOLD_BEGIN in text and PAYLOAD_END in text

    if has_markers:
        # Return full file content (with markers) so scaffold bytes stay intact
        # Extract the fenced content (inside ```` ... ````) if present
        fenced = _extract_backtick_fence(text)
        if fenced is not None:
            return fenced, True
        return text, True
    else:
        # No scaffold markers: extract content from 4-backtick fence
        fenced = _extract_backtick_fence(text)
        if fenced is not None:
            return fenced, False
        return text, False


def _extract_backtick_fence(text: str) -> str | None:
    """Extract the content inside a 4-backtick (````) fence, if present."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("````") and start is None:
            start = i
        elif line.startswith("````") and start is not None:
            return "\n".join(lines[start + 1:i])
    return None


# ── Placeholder substitution ──────────────────────────────────────────────────

def _build_subs(state: dict, action: dict, skill_dir: str, orch_dir: str) -> dict[str, str]:
    """Build the substitution map for template placeholders.

    T10 seam: packet paths (context_slice, diff, etc.) will be injected here
    from the T10 packet directory once T10 is implemented.
    """
    task_id = action["task_id"]
    role = action["role"]
    active_tasks = state.get("tasks", {})
    task = active_tasks.get(task_id, {})

    # Task body (from planparse result stored on the task)  # <<T10: inject packet paths here>>
    task_body = task.get("body", f"[Task body for {task_id} — T10 packet injection pending]")
    task_title = task.get("title", task_id)
    files_list = task.get("files", [])
    files_str = "\n".join(f"- {f}" for f in files_list) if files_list else "(none listed)"

    # Model name for template substitution
    model_key = state.get("implementer_model", DEFAULT_MODEL_KEY)
    model_name = MODEL_MAP.get(model_key, MODEL_MAP[DEFAULT_MODEL_KEY])

    # Spec excerpt  # <<T10: pull from spec manifest + packet>>
    spec_excerpt = task.get(
        "spec_excerpt",
        "[Spec excerpt — T10 packet injection pending. Refer to the spec file for now.]"
    )
    spec_section_label = task.get("spec_section_label", "all")
    task_size = task.get("task_size", "MEDIUM")
    risk_level = state.get("risk_levels", {}).get(task_id, "mid").upper()

    effort_guidance = (
        "SMALL — complete in one focused session. Minimal tool calls.\n"
        "MEDIUM — thorough but scoped. Use TDD and verification.\n"
        "LARGE — multi-step. Plan before code; verify each major piece."
    )

    # Context slice  # <<T10: inject from pre-resolved context>>
    context_slice = task.get(
        "context_slice",
        "[Context slice — T10 pre-resolved context injection pending.]"
    )

    # Decisions register (empty for now)
    decisions_register = ""

    # Reviewer-specific: files changed + diff
    files_changed = task.get("files_changed", files_list)
    files_changed_str = "\n".join(f"- {f}" for f in files_changed) if files_changed else "(none)"
    diff_text = task.get("diff", "(diff not available — injected by orchestrator)")

    # Verifier-specific: test command, acceptance criteria, baseline
    test_command = task.get("test_command", "python3 -m pytest")
    acceptance_criteria = task.get("acceptance", "none provided")
    baseline_pass = task.get("baseline_pass", 0)
    baseline_fail = task.get("baseline_fail", 0)
    result_json_path = os.path.join(orch_dir, "results", f"{role}_{task_id}_a{action['attempt']}.json")

    # Plan reviewer: plan/spec paths and content
    plan_path = state.get("plan", "")
    spec_path = state.get("spec", "")
    plan_text = ""
    spec_text = ""
    if plan_path and os.path.exists(plan_path):
        plan_text = Path(plan_path).read_text(encoding="utf-8")
    if spec_path and os.path.exists(spec_path):
        spec_text = Path(spec_path).read_text(encoding="utf-8")
    risk_levels_yaml = "\n".join(
        f"{tid}: {lvl}" for tid, lvl in state.get("risk_levels", {}).items()
    )

    return {
        # implementer
        "{implementer_model}": model_name,
        "{decisions_register}": decisions_register,
        "{task_size}": task_size,
        "{effort_guidance}": effort_guidance,
        "{full text of the task from the plan — copy the entire task section verbatim, at whichever heading level the plan uses (`### Task N:` or `## Task N:`), including all substeps and blocks belonging to that task}": task_body,
        "{spec_section_label}": spec_section_label,
        "{relevant excerpt from the design spec — copy the section(s) that apply to this task}": spec_excerpt,
        "{list from the task's Files: block — create / modify / test}": files_str,
        "{files to touch}": files_str,
        "{context_slice}": context_slice,
        "{orch_dir}": orch_dir,
        "{risk level}": risk_level,
        # implementer re-dispatch: previous review issues (T10 will supply full list)
        "{issues list — RECURRING issues are marked \"[RECURRING — your previous fix did not address this]\"}": (
            task.get("previous_issues", "(prior review issues — injected by T10 on re-dispatch)")
        ),
        # reviewer
        "{exact spec requirement text — same excerpt given to the Implementer}": spec_excerpt,
        "{list from the implementer's FILES_CHANGED: output — one per line}": files_changed_str,
        "{inline git diff output injected by orchestrator}": diff_text,
        "{previous_issues list}": "(no previous issues — first attempt)",
        # verifier
        "{MID | HIGH | LOW (BATCH)}": risk_level,
        "{list of changed files — for LOW BATCH, all files from accumulated LOW tasks since last compaction point}": files_changed_str,
        "{N}": str(baseline_pass),
        "{M}": str(baseline_fail),
        "{test_command}": test_command,
        "{acceptance_criteria — executable shell commands from the task's ## Acceptance Criteria block, or \"none provided\"}": (acceptance_criteria or "none provided"),
        "{result_json_path}": result_json_path,
        # docs_updater
        "{list of implementation files changed across tasks in this phase — from orchestrator's state file}": files_changed_str,
        # plan_reviewer
        "{plan_path}": plan_path,
        "{plan_full_text}": plan_text,
        "{spec_path}": spec_path,
        "{spec_full_text}": spec_text,
        "{risk_levels_yaml}": risk_levels_yaml,
        "{spec_manifest_json}": "{}",
    }


def _drop_if_blocks(text: str, attempt: int) -> str:
    """Remove {IF ...:} conditional blocks from the template body.

    On attempt 1: no re-dispatch context → drop the entire IF block.
    On attempt > 1: keep the content inside the IF block (drop only the marker lines).

    A conditional block starts with a line matching {IF ...:} and ends just
    before the blank line that immediately precedes the next top-level section
    heading (## or ### ) or the next {IF...:} marker.  Blank lines INSIDE the
    block (between paragraphs) are consumed along with the block.
    """
    lines = text.splitlines(keepends=False)
    result_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if IF_BLOCK_RE.match(line.strip()):
            if attempt <= 1:
                # Skip this marker line and everything until the block boundary.
                # Boundary = blank line that is immediately followed by a
                # top-level heading (## /### ) or another IF marker.
                i += 1  # skip the IF marker itself
                while i < len(lines):
                    cur = lines[i]
                    if IF_BLOCK_RE.match(cur.strip()):
                        # Another IF marker — stop without consuming it
                        break
                    if not cur.strip():
                        # Blank line: peek ahead
                        peek = lines[i + 1] if i + 1 < len(lines) else ""
                        if (peek.startswith("## ")
                                or peek.startswith("### ")
                                or IF_BLOCK_RE.match(peek.strip())):
                            # This blank introduces the next outer section;
                            # stop — leave it for outer document structure
                            break
                        # Blank line is inside the block (paragraph separator)
                        i += 1
                        continue
                    i += 1  # non-blank block content — skip
                continue  # resume outer loop
            else:
                # Keep content, drop only the marker line
                i += 1
                continue
        result_lines.append(line)
        i += 1
    return "\n".join(result_lines)


def _substitute(body: str, subs: dict[str, str]) -> str:
    """Apply substitution map to body text."""
    for token, value in subs.items():
        body = body.replace(token, value)
    return body


def _append_output_contract_to_payload(body: str, has_markers: bool) -> str:
    """Append ## Output contract inside the PAYLOAD region (if markers) or at end."""
    if not has_markers:
        return body + OUTPUT_CONTRACT

    # Locate PAYLOAD_END and insert before it
    lines = body.splitlines(keepends=False)
    pe_indices = [i for i, ln in enumerate(lines) if ln == PAYLOAD_END]
    if not pe_indices:
        # No PAYLOAD_END found — append at end
        return body + OUTPUT_CONTRACT

    pe_idx = pe_indices[0]
    # Insert OUTPUT_CONTRACT lines before PAYLOAD_END
    contract_lines = OUTPUT_CONTRACT.splitlines(keepends=False)
    new_lines = lines[:pe_idx] + contract_lines + lines[pe_idx:]
    return "\n".join(new_lines)


def _assemble_prompt(
    role: str,
    state: dict,
    action: dict,
    skill_dir: str,
    orch_dir: str,
) -> tuple[str, bool]:
    """Return (assembled_prompt_text, has_scaffold_markers)."""
    body, has_markers = _load_template_body(role, skill_dir)
    subs = _build_subs(state, action, skill_dir, orch_dir)
    attempt = action.get("attempt", 1)

    # Drop/expand {IF ...:} conditional blocks
    body = _drop_if_blocks(body, attempt)

    # Substitute all known placeholders
    body = _substitute(body, subs)

    # Append ## Output contract
    body = _append_output_contract_to_payload(body, has_markers)

    return body, has_markers


# ── Path helpers ──────────────────────────────────────────────────────────────

def _prompt_filename(role: str, task_id: str, attempt: int) -> str:
    """Build prompt filename: <role>_<task_id>_a<attempt>.md
    task_id is already 'task_3', so produce 'implementer_task_3_a1'.
    """
    return f"{role}_{task_id}_a{attempt}.md"


def _result_filename(role: str, task_id: str, attempt: int) -> str:
    return f"{role}_{task_id}_a{attempt}.json"


# ── Main public API ───────────────────────────────────────────────────────────

def build(
    state: dict,
    action: dict,
    skill_dir: str,
    orch_dir: str,
) -> dict[str, Any]:
    """Assemble prompt and generate headless dispatch materials.

    Parameters
    ----------
    state     : current CME v3 state dict
    action    : dispatch action dict from transitions.decide()
                {"action": "dispatch", "role": str, "task_id": str, "attempt": int}
    skill_dir : absolute path to skills/kws-claude-multi-agent-executor/
    orch_dir  : absolute path to the orchestrator working directory

    Returns
    -------
    dict with keys:
        prompt_path, schema_path, result_path, transport, model, cwd
        command  (transport=="p")  OR  agent_instruction  (transport=="agent")
    """
    role = action["role"]
    task_id = action["task_id"]
    attempt = action.get("attempt", 1)

    # -- Model resolution --
    model_key = state.get("implementer_model", DEFAULT_MODEL_KEY)
    model_name = MODEL_MAP.get(model_key, MODEL_MAP[DEFAULT_MODEL_KEY])

    # -- Transport resolution --
    gate_key = ROLE_GATE.get(role, role)
    dispatch_config = state.get("dispatch_config") or {}
    transport = dispatch_config.get(gate_key, "p")

    # -- Paths --
    prompts_dir = os.path.join(orch_dir, "prompts")
    results_dir = os.path.join(orch_dir, "results")
    os.makedirs(prompts_dir, exist_ok=True)
    os.makedirs(results_dir, exist_ok=True)

    prompt_filename = _prompt_filename(role, task_id, attempt)
    result_filename = _result_filename(role, task_id, attempt)
    prompt_path = os.path.join(prompts_dir, prompt_filename)
    result_path = os.path.join(results_dir, result_filename)

    schema_filename = ROLE_SCHEMA.get(role, f"{role}_result.schema.json")
    schema_path = str(Path(skill_dir) / "references" / "_schemas" / schema_filename)

    # -- Assemble and write prompt --
    prompt_text, _has_markers = _assemble_prompt(role, state, action, skill_dir, orch_dir)
    Path(prompt_path).write_text(prompt_text, encoding="utf-8")

    # -- cwd from worktree --
    cwd = state.get("worktree", orch_dir)

    # -- Return dict --
    base = {
        "prompt_path": prompt_path,
        "schema_path": schema_path,
        "result_path": result_path,
        "transport": transport,
        "model": model_name,
        "cwd": cwd,
    }

    if transport == "agent":
        base["agent_instruction"] = {
            "description": f"Run {role} sub-agent for {task_id} attempt {attempt}",
            "prompt_path": prompt_path,
            "model": model_name,
            "result_path": result_path,
            "schema_path": schema_path,
            "instruction": (
                f"You are a {role} sub-agent. Read the prompt at {prompt_path}, "
                f"complete the task, and write your structured JSON result to {result_path}."
            ),
        }
    else:
        # headless -p command
        # Paths are shlex-quoted so a space in orch_dir/skill_dir does not
        # word-split in the shell.  model_name is a controlled MODEL_MAP literal
        # and stays unquoted.
        cmd = (
            f'claude -p "$(cat {shlex.quote(prompt_path)})" --output-format json '
            f"--json-schema {shlex.quote(schema_path)} --model {model_name} "
            f"--dangerously-skip-permissions > {shlex.quote(result_path)}"
        )
        base["command"] = cmd

    return base
