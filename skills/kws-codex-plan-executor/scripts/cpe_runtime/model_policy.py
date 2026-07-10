from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Route:
    role: str
    model: str
    reasoning: str


POLICY_VERSION = "cpe.model-policy.v1"
CORE_ROUTE = Route("core", "gpt-5.6-sol", "high")
SCOUT_ROUTE = Route("scout", "gpt-5.6-terra", "high")
CORE_ATTEMPT_KINDS = frozenset({
    "coordination", "implementation", "task_review", "verification", "recovery",
    "repair", "analysis", "completion", "prompt_validation", "final_review",
})


def policy_payload() -> dict[str, object]:
    return {
        "version": POLICY_VERSION,
        "core": {"model": CORE_ROUTE.model, "reasoning": CORE_ROUTE.reasoning},
        "scout": {"model": SCOUT_ROUTE.model, "reasoning": SCOUT_ROUTE.reasoning},
    }


def policy_hash() -> str:
    raw = json.dumps(policy_payload(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def route_for(attempt_kind: str, *, read_only: bool, verdict_capable: bool) -> Route:
    attempt_kind = "task_review" if attempt_kind == "review" else attempt_kind
    if attempt_kind == "scout":
        if not read_only or verdict_capable:
            raise PolicyError("Terra scout requires read_only=true and verdict_capable=false")
        return SCOUT_ROUTE
    if attempt_kind not in CORE_ATTEMPT_KINDS:
        raise PolicyError(f"unknown attempt kind: {attempt_kind}")
    return CORE_ROUTE


def launcher_argv(
    route: Route,
    worktree: Path,
    *,
    sandbox: str,
    output_schema: Path | None = None,
    output_last_message: Path | None = None,
) -> list[str]:
    if sandbox not in {"read-only", "workspace-write"}:
        raise PolicyError(f"invalid sandbox: {sandbox}")
    if route == SCOUT_ROUTE and sandbox != "read-only":
        raise PolicyError("scout requires sandbox=read-only")
    argv = [
        "codex", "exec", "--json", "--model", route.model,
        "-c", f'model_reasoning_effort="{route.reasoning}"',
        "--sandbox", sandbox, "-C", str(worktree),
    ]
    if output_schema is not None:
        argv.extend(["--output-schema", str(output_schema)])
    if output_last_message is not None:
        argv.extend(["--output-last-message", str(output_last_message)])
    argv.append("-")
    return argv


def attest_launcher(
    route: Route,
    argv: list[str],
    *,
    provider_model: str | None = None,
    provider_reasoning: str | None = None,
    trusted_source: str | None = None,
) -> dict[str, object]:
    verified = bool(provider_model and provider_reasoning and trusted_source)
    mismatch = (
        (provider_model is not None and provider_model != route.model)
        or (provider_reasoning is not None and provider_reasoning != route.reasoning)
    )
    return {
        "requested_model": route.model,
        "actual_model": provider_model,
        "requested_reasoning": route.reasoning,
        "actual_reasoning": provider_reasoning,
        "source": trusted_source,
        "launcher_sha256": hashlib.sha256(json.dumps(argv).encode()).hexdigest(),
        "verified": verified and not mismatch,
        "mismatch": mismatch,
    }
