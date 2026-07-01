from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


ADAPTIVE_LOCAL_FAST_PATH_DOCS_ONLY = "adaptive_policy_local_fast_path_docs_only"
ADAPTIVE_LOCAL_FAST_PATH_SMALL_SCOPE = "adaptive_policy_local_fast_path_small_scope"
ADAPTIVE_LOCAL_FAST_PATH_LINEAR_TASK = "adaptive_policy_local_fast_path_linear_task"
ADAPTIVE_LOCAL_FAST_PATH_LOW_PARALLEL_VALUE = "adaptive_policy_local_fast_path_low_parallel_value"
RISK_MARKER_REQUIRES_OPERATOR_REVIEW = "risk_marker_requires_operator_review"

RISKY_PATH_FRAGMENTS = ("migration", "migrations", "auth", "security", "infra", "terraform", "pulumi")
RISKY_EXACT_FILES = {"bun.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.lock"}
BROAD_SCOPES = {"", ".", "*", "**", "**/*", "./", "./*", "./**", "./**/*"}


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def dependency_list(payload: dict[str, Any]) -> list[str]:
    dependencies = list_strings(payload.get("dependencies"))
    if dependencies:
        return dependencies
    return list_strings(payload.get("depends_on"))


def malformed_scope(pattern: str) -> bool:
    stripped = pattern.strip()
    if not stripped:
        return False
    if any(char in stripped for char in "[]{}"):
        return False
    return "," in stripped or "\n" in stripped or "\r" in stripped


def split_scope(pattern: str) -> list[str]:
    if not malformed_scope(pattern):
        return [pattern.strip()] if pattern.strip() else []
    normalized = pattern.replace("\r\n", "\n").replace("\r", "\n").replace(",", "\n")
    return [item.strip() for item in normalized.split("\n") if item.strip()]


def normalized_scopes(patterns: list[str]) -> list[str]:
    result: list[str] = []
    for pattern in patterns:
        for part in split_scope(pattern):
            if part not in result:
                result.append(part)
    return result


def write_scope_too_broad(pattern: str) -> bool:
    return pattern.strip().rstrip("/") in BROAD_SCOPES


def path_risk_markers(paths: list[str], explicit: list[str] | None = None) -> list[str]:
    markers = {item for item in (explicit or []) if item}
    for path in paths:
        normalized = path.strip().lstrip("./")
        if normalized in RISKY_EXACT_FILES:
            markers.add("lockfile")
        lowered = normalized.lower()
        for fragment in RISKY_PATH_FRAGMENTS:
            if fragment in lowered:
                markers.add(fragment)
    return sorted(markers)


def docs_only(paths: list[str]) -> bool:
    return bool(paths) and all(path.startswith("docs/") and path.endswith(".md") for path in paths)


def small_scope(paths: list[str]) -> bool:
    return 0 < len(paths) <= 2


def path_name_tokens(path: str) -> set[str]:
    pure = PurePosixPath(path)
    tokens: set[str] = set()
    for part in pure.parts:
        tokens.update(item for item in part.replace("-", "_").replace(".", "_").split("_") if item)
    return tokens
