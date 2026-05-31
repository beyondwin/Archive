#!/usr/bin/env python3
"""Single entry point for headless-role dispatches via the Anthropic API (v2.22 §2.B1).

Replaces the per-role ``claude -p`` dispatch for the headless roles
(plan_reviewer, verifier, docs_updater, transition_combined). The role-prompt is
split into a STATIC scaffold (cached, ``cache_control: ephemeral``) and a
per-invocation PAYLOAD (carries the ``{placeholder}`` tokens). Structured output
is forced via a single tool + ``tool_choice``.

The ``anthropic`` SDK is imported LAZILY (only inside ``dispatch`` when a live
client must be constructed), so this module imports and unit-tests cleanly with
no SDK installed. Tests inject a fake ``client=`` to avoid any live call.

CLI:
    dispatch_via_api.py --role <plan_reviewer|verifier|docs_updater|transition_combined> \\
      --task-context <path-to-json> --output <path-to-json> \\
      --model <claude-...> --orch-dir <abs-path>

Failure mode: API errors (rate limit / 5xx) get exponential backoff (3 retries),
then an ENV_BLOCKER ESCALATE result dict ``{"status":"ESCALATE","type":"ENV_BLOCKER",...}``
is returned and written to ``--output``. Non-retryable errors ENV_BLOCKER
immediately. The orchestrator does NOT silently fall back to ``-p`` (spec §guardrail).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

MAX_TOKENS = 4096

# Tool-call name per role: report_<role>.
RETRYABLE_STATUS = {429, 500, 502, 503, 529}
RETRYABLE_NAME_HINTS = (
    "RateLimit", "Overloaded", "APIStatus",
    "InternalServer", "ServiceUnavailable",
)

SCAFFOLD_BEGIN = "<!-- SCAFFOLD_BEGIN -->"
SCAFFOLD_END = "<!-- SCAFFOLD_END -->"
PAYLOAD_BEGIN = "<!-- PAYLOAD_BEGIN -->"
PAYLOAD_END = "<!-- PAYLOAD_END -->"

# Combined Transition (v2.22 §2.A2) issues TWO tools in one turn.
TRANSITION_ROLE = "transition_combined"
VERIFY_TOOL = "verify_low_batch"
DOCS_TOOL = "update_phase_docs"

# Roles whose prompt filename does not follow the simple ``role.replace("_","-")``
# convention. The combined-transition prompt lives at ``transition-prompt.md``
# (role token ``transition_combined``) so its scaffold sibling is
# ``_scaffolds/transition-scaffold.md`` (matches the Task 5 linter mapping).
PROMPT_FILE_ROLE = {
    TRANSITION_ROLE: "transition",
}

# Roles whose prompt lives at an EXACT filename that the simple
# ``<file_role>-prompt.md`` template cannot produce (e.g. a plural stem). The
# Docs Updater (v2.22 §2.B2) shares one template across the Phase and Final call
# sites; its file is ``docs-updater-prompts.md`` (plural). The matching scaffold
# sibling is ``_scaffolds/docs_updater_prompts-scaffold.md`` (the linter's
# ``scaffold_path_for`` derives it from the ``docs-updater-prompts`` stem).
PROMPT_FILE_OVERRIDE = {
    "docs_updater": "docs-updater-prompts.md",
}


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def load_prompt(role: str, sk_root) -> tuple[str, str]:
    """Read ``references/<role>-prompt.md`` and return ``(scaffold, payload)``.

    Parses the four SCAFFOLD/PAYLOAD HTML-comment markers (each alone on its own
    line). The dispatched prompt is ``scaffold + "\\n" + payload``. Raises
    ``ValueError`` if any marker is missing or out of order.
    """
    # Role tokens use underscores; the prompt filenames use hyphens
    # (e.g. role "plan_reviewer" -> "plan-reviewer-prompt.md"). A few roles map
    # to a differently-named prompt file (see ``PROMPT_FILE_ROLE``).
    override = PROMPT_FILE_OVERRIDE.get(role)
    if override is not None:
        path = Path(sk_root) / "references" / override
    else:
        file_role = PROMPT_FILE_ROLE.get(role, role.replace("_", "-"))
        path = Path(sk_root) / "references" / f"{file_role}-prompt.md"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    def _index(marker: str) -> int:
        try:
            return lines.index(marker)
        except ValueError:
            raise ValueError(
                f"{path}: missing or malformed marker line {marker!r}")

    sb, se = _index(SCAFFOLD_BEGIN), _index(SCAFFOLD_END)
    pb, pe = _index(PAYLOAD_BEGIN), _index(PAYLOAD_END)
    if not (sb < se < pb < pe):
        raise ValueError(f"{path}: markers out of order (got {sb},{se},{pb},{pe})")

    scaffold = "\n".join(lines[sb + 1:se])
    payload = "\n".join(lines[pb + 1:pe])
    return scaffold, payload


def load_schema(role: str, sk_root) -> dict:
    """Read ``references/_schemas/<role>_result.schema.json``."""
    path = Path(sk_root) / "references" / "_schemas" / f"{role}_result.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _substitute(payload: str, task_context: dict) -> str:
    """Replace ``{key}`` tokens in the payload with values from task_context.

    Unknown tokens are left intact (defensive — the orchestrator owns the
    contract for which keys are supplied).
    """
    def repl(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key in task_context:
            return str(task_context[key])
        return match.group(0)

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, payload)


def build_request(scaffold: str, payload: str, schema: dict, role: str,
                  model: str, task_context: dict) -> dict:
    """Build the kwargs dict for ``client.messages.create``.

    The SCAFFOLD becomes a cached ``system`` content block
    (``cache_control: ephemeral``); the substituted PAYLOAD is the per-call user
    message. Structured output is forced with one tool + ``tool_choice``.
    """
    rendered_payload = _substitute(payload, task_context)
    req = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [
            {
                "type": "text",
                "text": scaffold,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {"role": "user", "content": rendered_payload},
        ],
    }

    if role == TRANSITION_ROLE:
        # Combined Transition (v2.22 §2.A2): offer BOTH tool specs verbatim from
        # the schema and force at least one tool use ("any" disables free text
        # and permits both tools in the same turn).
        req["tools"] = schema["tools"]
        req["tool_choice"] = {"type": "any"}
        return req

    # Single-tool roles (plan_reviewer, verifier, docs_updater): force the one
    # report_<role> tool. Unchanged behavior.
    tool_name = f"report_{role}"
    input_schema = schema.get("input_schema", schema)
    req["tools"] = [
        {
            "name": tool_name,
            "description": f"Report the structured {role} result.",
            "input_schema": input_schema,
        }
    ]
    req["tool_choice"] = {"type": "tool", "name": tool_name}
    return req


def _is_retryable(exc: BaseException) -> bool:
    """Classify an exception as retryable without importing anthropic."""
    code = getattr(exc, "status_code", None)
    if code in RETRYABLE_STATUS:
        return True
    name = type(exc).__name__
    return any(hint in name for hint in RETRYABLE_NAME_HINTS)


def _extract_tool_input(response, tool_name: str) -> dict:
    """Pull the forced tool_use block's ``.input`` from the response."""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
            return dict(block.input)
    # Fall back to the first tool_use block if name match fails.
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    raise ValueError("no tool_use block in response content")


def _extract_combined(response) -> dict:
    """Pull the combined ``{verify, docs}`` shape from a two-tool response.

    Scans ``response.content`` for the ``verify_low_batch`` and
    ``update_phase_docs`` tool_use blocks (v2.22 §2.A2 combined transition) and
    returns ``{"verify": <verify input>, "docs": <docs input>}``. Raises
    ``ValueError`` if either tool block is missing.
    """
    by_name: dict = {}
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use":
            by_name[getattr(block, "name", None)] = dict(block.input)
    missing = [name for name in (VERIFY_TOOL, DOCS_TOOL) if name not in by_name]
    if missing:
        raise ValueError(
            "combined transition response missing tool_use block(s): "
            + ", ".join(missing))
    return {"verify": by_name[VERIFY_TOOL], "docs": by_name[DOCS_TOOL]}


def _usage_fields(response) -> dict:
    u = getattr(response, "usage", None)
    return {
        "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
        "cache_read_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
        "cache_creation_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
    }


def _accumulate_cost(orch_dir, role: str, model: str, usage: dict) -> None:
    """Best-effort cost ledger write (mandatory cost invariant; guarded).

    A missing/locked state.json must not crash a unit test, so failures are
    swallowed after a single attempt.
    """
    try:
        sys.path.insert(0, str(_scripts_dir()))
        from accumulate_cost import accumulate  # type: ignore

        state_path = Path(orch_dir) / "state.json"
        if not state_path.is_file():
            return
        accumulate(
            state_path,
            task_id=f"{role}_api",
            role=role,
            model=model,
            usage={
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "cached_read_tokens": usage["cache_read_tokens"],
                "cached_write_tokens": usage["cache_creation_tokens"],
            },
        )
    except Exception:
        # Cost accumulation is mandatory but must never crash the dispatch path
        # in a degraded environment; the orchestrator surfaces ledger gaps.
        pass


def _emit_agentlens(fields: dict) -> None:
    """Best-effort AgentLens event emit (``kws-cme.dispatch_via_api``).

    Task 11 registers/extends the event; this is the best-effort shim. Tests
    monkeypatch this function to record the call. All failures are swallowed.
    """
    try:
        import subprocess

        subprocess.run(
            [
                "agentlens", "event", "append",
                "--event", "kws-cme.dispatch_via_api",
                "--json", json.dumps(fields),
            ],
            check=False,
            capture_output=True,
        )
    except Exception:
        pass


def _env_blocker(role: str, model: str, retries: int, error: str) -> dict:
    return {
        "status": "ESCALATE",
        "type": "ENV_BLOCKER",
        "role": role,
        "model": model,
        "retries": retries,
        "blocker": f"Anthropic API dispatch for role '{role}' failed: {error}",
    }


def _write_output(output_path, result: dict) -> None:
    Path(output_path).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def dispatch(role: str, task_context: dict, model: str, orch_dir, sk_root,
             output_path, client=None, max_retries: int = 3) -> dict:
    """Dispatch one headless role via the API and persist the result.

    Returns the tool result dict on success, or an ENV_BLOCKER ESCALATE dict on
    persistent/non-retryable API failure. The result is always written to
    ``output_path``.
    """
    scaffold, payload = load_prompt(role, sk_root)
    schema = load_schema(role, sk_root)
    req = build_request(scaffold, payload, schema, role, model, task_context)

    if client is None:
        # Lazy import — only reached for real runs; SDK absent in unit tests.
        import anthropic  # noqa: F401

        client = anthropic.Anthropic()

    start = time.monotonic()
    attempt = 0
    last_error = ""
    while True:
        try:
            response = client.messages.create(**req)
            break
        except Exception as exc:  # noqa: BLE001 - classify, not import-bound
            last_error = f"{type(exc).__name__}: {exc}"
            if not _is_retryable(exc) or attempt >= max_retries:
                result = _env_blocker(role, model, attempt, last_error)
                _write_output(output_path, result)
                return result
            time.sleep(2 ** attempt)
            attempt += 1

    wall_ms = int((time.monotonic() - start) * 1000)
    if role == TRANSITION_ROLE:
        # Combined Transition writes the merged {verify, docs} dict.
        result = _extract_combined(response)
    else:
        result = _extract_tool_input(response, f"report_{role}")
    _write_output(output_path, result)

    usage = _usage_fields(response)
    _accumulate_cost(orch_dir, role, model, usage)

    input_tokens = usage["input_tokens"]
    cache_read = usage["cache_read_tokens"]
    cache_hit_ratio = (cache_read / input_tokens) if input_tokens else 0.0
    _emit_agentlens({
        "event": "kws-cme.dispatch_via_api",
        "role": role,
        "model": model,
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read,
        "output_tokens": usage["output_tokens"],
        "cache_hit_ratio": round(cache_hit_ratio, 4),
        "wall_ms": wall_ms,
        "retries": attempt,
    })
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Dispatch a headless role via the Anthropic API (v2.22 §2.B1).")
    ap.add_argument(
        "--role", required=True,
        choices=["plan_reviewer", "verifier", "docs_updater",
                 "transition_combined"],
        help="headless role to dispatch")
    ap.add_argument("--task-context", required=True,
                    help="path to JSON with the payload placeholder values")
    ap.add_argument("--output", required=True,
                    help="path to write the structured result JSON")
    ap.add_argument("--model", required=True, help="claude model id")
    ap.add_argument("--orch-dir", required=True,
                    help="absolute orchestrator dir (holds state.json)")
    return ap


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    sk_root = Path(__file__).resolve().parents[1]
    task_context = json.loads(Path(args.task_context).read_text(encoding="utf-8"))
    result = dispatch(
        args.role, task_context, args.model, args.orch_dir, sk_root, args.output)
    if result.get("status") == "ESCALATE":
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
