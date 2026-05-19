#!/usr/bin/env python3
"""Detect likely local environment blockers without mutating the repository."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


TEMPLATE_SUFFIXES = (".example", ".template", ".dist")
NODE_LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock")
PY_LOCKFILES = ("poetry.lock", "uv.lock")
GRADLE_BUILDS = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_ignored(root: Path, path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", rel(path, root)],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def template_counterpart(path: Path) -> Path | None:
    name = path.name
    for suffix in TEMPLATE_SUFFIXES:
        if name.endswith(suffix):
            return path.with_name(name[: -len(suffix)])
    return None


def walk_templates(root: Path) -> list[Path]:
    templates: list[Path] = []
    for path in root.rglob("*"):
        if ".git" in path.parts:
            continue
        if not path.is_file():
            continue
        try:
            depth = len(path.relative_to(root).parts)
        except ValueError:
            continue
        if depth > 3:
            continue
        if template_counterpart(path) is not None:
            templates.append(path)
    return sorted(templates)


def missing_local_config_warnings(root: Path, detected_at: str) -> list[dict]:
    warnings: list[dict] = []
    for template in walk_templates(root):
        counterpart = template_counterpart(template)
        if counterpart is None or counterpart.exists():
            continue
        if not is_ignored(root, counterpart):
            continue
        warnings.append(
            {
                "kind": "missing_local_config",
                "file": rel(counterpart, root),
                "template": rel(template, root),
                "suggestion": f"Copy {rel(template, root)} to {rel(counterpart, root)} and fill in local values.",
                "detected_at": detected_at,
            }
        )
    return warnings


def newer_than(path: Path, marker: Path) -> bool:
    if not path.exists():
        return False
    if not marker.exists():
        return True
    return path.stat().st_mtime > marker.stat().st_mtime


def first_existing(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = root / name
        if path.exists():
            return path
    return None


def dependency_warning(manifest: Path, lockfile: Path, marker: Path, suggestion: str, detected_at: str, root: Path) -> dict | None:
    if not manifest.exists() or not lockfile.exists() or not newer_than(lockfile, marker):
        return None
    return {
        "kind": "dependencies_likely_stale",
        "manifest": rel(manifest, root),
        "lockfile": rel(lockfile, root),
        "marker": rel(marker, root),
        "suggestion": suggestion,
        "detected_at": detected_at,
    }


def dependency_warnings(root: Path, detected_at: str) -> list[dict]:
    warnings: list[dict] = []

    node_lock = first_existing(root, NODE_LOCKFILES)
    if node_lock:
        warning = dependency_warning(
            root / "package.json",
            node_lock,
            root / "node_modules/.package-lock.json",
            "Run install before baseline, for example `npm install`.",
            detected_at,
            root,
        )
        if warning:
            warnings.append(warning)

    py_lock = first_existing(root, PY_LOCKFILES)
    if py_lock:
        markers = [root / ".venv/pyvenv.cfg", root / "venv/pyvenv.cfg"]
        marker = next((item for item in markers if item.exists()), markers[0])
        warning = dependency_warning(
            root / "pyproject.toml",
            py_lock,
            marker,
            "Run the project dependency bootstrap before baseline.",
            detected_at,
            root,
        )
        if warning:
            warnings.append(warning)

    if (root / "Cargo.toml").exists() and (root / "Cargo.lock").exists():
        warning = dependency_warning(
            root / "Cargo.toml",
            root / "Cargo.lock",
            root / "target/.rustc_info.json",
            "Run `cargo build` before baseline.",
            detected_at,
            root,
        )
        if warning:
            warnings.append(warning)

    gradle_build = first_existing(root, GRADLE_BUILDS)
    if gradle_build and (root / "gradlew").exists():
        marker = root / ".gradle"
        if not marker.exists():
            marker = root / "build"
        warning = dependency_warning(
            gradle_build,
            root / "gradlew",
            marker,
            "Run the Gradle wrapper before baseline.",
            detected_at,
            root,
        )
        if warning:
            warnings.append(warning)

    return warnings


def build_report(root: Path) -> dict:
    detected_at = now_iso()
    warnings = missing_local_config_warnings(root, detected_at)
    warnings.extend(dependency_warnings(root, detected_at))
    return {"schema_version": "1", "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    root = Path(args.repo_root).expanduser().resolve()
    if not root.is_dir():
        die(f"repo root is not a directory: {root}")
    report = build_report(root)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(output)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
