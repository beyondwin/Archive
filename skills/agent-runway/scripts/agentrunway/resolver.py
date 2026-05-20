from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .worktrees import workspace_id


class ResolutionError(ValueError):
    def __init__(self, message: str, payload: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.payload = payload or {}


@dataclass(frozen=True)
class RunInputResolution:
    plan_path: Path
    spec_path: Path | None
    adapter: str
    source: str


DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
DESIGN_REF_RE = re.compile(r"(?im)\bDesign\b\s*:\s*`?([^`\n]+?\.md)`?\s*$")


def normalize_topic(value: str) -> str:
    normalized = DATE_PREFIX_RE.sub("", value.strip().lower())
    normalized = normalized.removesuffix("-design")
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def _agentrunway_home() -> Path:
    return Path(os.environ.get("AGENTRUNWAY_HOME", str(Path.home() / ".agentrunway"))).expanduser()


def _resolve_existing(repo_root: Path, value: Path | str, *, label: str) -> Path:
    path = Path(value).expanduser()
    candidate = path if path.is_absolute() else repo_root / path
    if not candidate.exists():
        raise ResolutionError(f"{label} does not exist: {value}", {"path": str(value)})
    return candidate.resolve()


def _doc_time(repo_root: Path, path: Path) -> float:
    rel = path.relative_to(repo_root).as_posix() if path.is_relative_to(repo_root) else str(path)
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", rel],
        cwd=repo_root,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0 and result.stdout.strip().isdigit():
        return float(result.stdout.strip())
    return path.stat().st_mtime


def _find_design_reference(repo_root: Path, plan_path: Path) -> Path | None:
    match = DESIGN_REF_RE.search(plan_path.read_text(encoding="utf-8"))
    if not match:
        return None
    raw = match.group(1).strip()
    candidate = Path(raw)
    resolved = candidate if candidate.is_absolute() else repo_root / candidate
    return resolved.resolve() if resolved.exists() else None


def _strip_plan_slug(path: Path) -> str:
    return normalize_topic(path.stem)


def _strip_spec_slug(path: Path) -> str:
    return normalize_topic(path.stem)


def _complete_pairs(repo_root: Path) -> list[tuple[str, Path, Path]]:
    plan_dir = repo_root / "docs" / "superpowers" / "plans"
    spec_dir = repo_root / "docs" / "superpowers" / "specs"
    if not plan_dir.exists() or not spec_dir.exists():
        return []
    plans_by_slug = {_strip_plan_slug(path): path for path in plan_dir.glob("*.md")}
    specs_by_slug = {_strip_spec_slug(path): path for path in spec_dir.glob("*.md")}
    pairs: list[tuple[str, Path, Path]] = []
    for slug, plan_path in plans_by_slug.items():
        spec_path = specs_by_slug.get(slug)
        if spec_path is not None:
            pairs.append((slug, plan_path.resolve(), spec_path.resolve()))
    return sorted(pairs, key=lambda item: item[0])


def _candidate_payload(candidates: Iterable[tuple[str, Path, Path]]) -> list[dict[str, str]]:
    return [
        {"topic": slug, "plan": str(plan), "spec": str(spec)}
        for slug, plan, spec in candidates
    ]


def _infer_spec_from_plan(repo_root: Path, plan_path: Path) -> Path | None:
    referenced = _find_design_reference(repo_root, plan_path)
    if referenced is not None:
        return referenced
    slug = _strip_plan_slug(plan_path)
    for pair_slug, _plan, spec in _complete_pairs(repo_root):
        if pair_slug == slug:
            return spec
    return None


def _resolve_adapter(adapter: str | None) -> str:
    if adapter and adapter != "auto":
        return adapter
    return "local"


def resolve_run_inputs(
    *,
    repo_root: Path,
    plan: Path | None,
    spec: Path | None,
    topic: str | None,
    latest: bool,
    adapter: str | None,
) -> RunInputResolution:
    repo_root = repo_root.resolve()
    resolved_adapter = _resolve_adapter(adapter)
    if plan is not None:
        plan_path = _resolve_existing(repo_root, plan, label="plan")
        spec_path = _resolve_existing(repo_root, spec, label="spec") if spec is not None else _infer_spec_from_plan(repo_root, plan_path)
        return RunInputResolution(plan_path=plan_path, spec_path=spec_path, adapter=resolved_adapter, source="explicit_plan")
    if spec is not None:
        raise ResolutionError("spec requires plan, topic, or latest", {"spec": str(spec)})

    pairs = _complete_pairs(repo_root)
    if topic:
        requested = normalize_topic(topic)
        matches = [item for item in pairs if item[0] == requested or requested in item[0]]
        if not matches:
            raise ResolutionError(f"no topic match: {topic}", {"candidates": _candidate_payload(pairs)})
        if len(matches) > 1:
            raise ResolutionError("ambiguous topic", {"candidates": _candidate_payload(matches)})
        slug, plan_path, spec_path = matches[0]
        return RunInputResolution(plan_path=plan_path, spec_path=spec_path, adapter=resolved_adapter, source="topic")

    if latest:
        if not pairs:
            raise ResolutionError("no complete spec/plan pairs found", {"candidates": []})
        slug, plan_path, spec_path = max(
            pairs,
            key=lambda item: (
                max(_doc_time(repo_root, item[1]), _doc_time(repo_root, item[2])),
                item[1].name,
                item[2].name,
            ),
        )
        return RunInputResolution(plan_path=plan_path, spec_path=spec_path, adapter=resolved_adapter, source="latest")

    raise ResolutionError("run requires --plan, --topic, or --latest", {"candidates": _candidate_payload(pairs)})


def _last_run_path(repo_root: Path) -> Path:
    return _agentrunway_home() / "workspaces" / workspace_id(repo_root.resolve()) / "last_run.json"


def write_last_run(repo_root: Path, run_id: str) -> Path:
    path = _last_run_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_id": run_id}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_last_run(repo_root: Path) -> str | None:
    path = _last_run_path(repo_root)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    run_id = payload.get("run_id") if isinstance(payload, dict) else None
    return str(run_id) if run_id else None


def resolve_run_alias(repo_root: Path, run_id: str | None, last: bool) -> str:
    if run_id:
        return run_id
    if last:
        resolved = read_last_run(repo_root)
        if resolved:
            return resolved
        raise ResolutionError("no last run for current workspace", {"workspace_id": workspace_id(repo_root.resolve())})
    raise ResolutionError("command requires --run or --last")
