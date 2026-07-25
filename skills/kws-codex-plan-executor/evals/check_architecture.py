#!/usr/bin/env python3
"""Fail closed when the active CPE regains duplicate workflow authority."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "scripts" / "cpe_runtime"
EXPECTED_RUNTIME = {
    "__init__.py",
    "state.py",
    "git.py",
    "controller.py",
    "runtime.py",
}
EXPECTED_TEMPLATES = {"terminal-envelope.schema.json"}
DELETED_MODULES = {
    "capabilities",
    "evidence",
    "launcher",
    "progress",
    "reporting",
    "result_validation",
    "runner",
    "verification",
}
FORBIDDEN = {
    "current_plan_index",
    "completed_task_ids",
    "current_task_id",
    "fix_round",
    "final_review_head",
    "open_finding_ids",
    "open_obligation_ids",
    '"verification"',
    "migrate-run",
}
PUBLIC_COMMANDS = {"run", "resume", "inspect"}
PRODUCTION_LIMIT = 1500
MODULE_LIMIT = 450


def production_python() -> list[Path]:
    return [ROOT / "scripts" / "cpe.py", *sorted(RUNTIME_ROOT.glob("*.py"))]


def absolute_import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def imported_deleted_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = [node.module] if node.module else []
            if node.level or node.module == "cpe_runtime":
                names.extend(alias.name for alias in node.names)
        else:
            continue
        for name in names:
            if name is None:
                continue
            found.update(set(name.split(".")) & DELETED_MODULES)
    return found


def active_commands(document: Path) -> set[str]:
    text = document.read_text(encoding="utf-8")
    blocks = re.findall(r"```(?:bash|sh|shell)?\n(.*?)```", text, re.DOTALL)
    commands: set[str] = set()
    pattern = re.compile(
        r"(?:^|\n)\s*(?:python3\s+)?(?:\./)?scripts/cpe\.py\s+([a-z][a-z-]*)"
    )
    for block in blocks:
        commands.update(pattern.findall(block))
    return commands


def check() -> list[str]:
    errors: list[str] = []
    runtime_inventory = {path.name for path in RUNTIME_ROOT.glob("*.py")}
    if runtime_inventory != EXPECTED_RUNTIME:
        errors.append(
            "runtime inventory mismatch: "
            f"expected={sorted(EXPECTED_RUNTIME)} actual={sorted(runtime_inventory)}"
        )
    templates = {path.name for path in (ROOT / "templates").glob("*.json")}
    if templates != EXPECTED_TEMPLATES:
        errors.append(
            "template inventory mismatch: "
            f"expected={sorted(EXPECTED_TEMPLATES)} actual={sorted(templates)}"
        )

    paths = production_python()
    schema = ROOT / "templates" / "terminal-envelope.schema.json"
    searchable = [*paths, schema]
    for path in searchable:
        text = path.read_text(encoding="utf-8")
        for token in sorted(FORBIDDEN):
            if token in text:
                errors.append(f"forbidden token {token!r}: {path.relative_to(ROOT)}")

    total = 0
    stdlib = sys.stdlib_module_names
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lines = len(text.splitlines())
        total += lines
        if lines > MODULE_LIMIT:
            errors.append(
                f"module line limit exceeded: {path.relative_to(ROOT)}={lines}"
            )
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            errors.append(f"invalid Python: {path.relative_to(ROOT)}: {exc}")
            continue
        external = absolute_import_roots(tree) - stdlib - {"cpe_runtime"}
        if external:
            errors.append(
                f"non-stdlib import: {path.relative_to(ROOT)}={sorted(external)}"
            )
        deleted = imported_deleted_modules(tree)
        if deleted:
            errors.append(
                f"deleted-module import: {path.relative_to(ROOT)}={sorted(deleted)}"
            )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    errors.append(
                        f"shell=True is forbidden: {path.relative_to(ROOT)}:{node.lineno}"
                    )
    if total > PRODUCTION_LIMIT:
        errors.append(
            f"production line limit exceeded: total={total} limit={PRODUCTION_LIMIT}"
        )

    for name in ("SKILL.md", "README.md"):
        commands = active_commands(ROOT / name)
        if commands != PUBLIC_COMMANDS:
            errors.append(
                f"active commands mismatch in {name}: "
                f"expected={sorted(PUBLIC_COMMANDS)} actual={sorted(commands)}"
            )
    return errors


def main() -> int:
    errors = check()
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        return 1
    paths = production_python()
    counts = {path.relative_to(ROOT).as_posix(): len(
        path.read_text(encoding="utf-8").splitlines()
    ) for path in paths}
    print(
        "PASS architecture "
        f"modules={len(paths)} total_lines={sum(counts.values())} "
        f"max_module={max(counts.values())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
