#!/usr/bin/env python3
"""Fail closed when the active CPE regains duplicate workflow authority."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_RUNTIME = {
    "__init__.py",
    "state.py",
    "git.py",
    "controller.py",
    "runtime.py",
}
EXPECTED_PRODUCTION_PYTHON = {
    "cpe.py",
    "cpe_runtime/__init__.py",
    "cpe_runtime/controller.py",
    "cpe_runtime/git.py",
    "cpe_runtime/runtime.py",
    "cpe_runtime/state.py",
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
SEMANTIC_PATTERNS = {
    "task_id": re.compile(r"task(?:_|-)?id", re.IGNORECASE),
    "completed_task": re.compile(r"completed(?:_|-)?task", re.IGNORECASE),
    "current_plan_index": re.compile(
        r"current(?:_|-)?plan(?:_|-)?index",
        re.IGNORECASE,
    ),
    "fix_round": re.compile(r"fix(?:_|-)?round", re.IGNORECASE),
    "final_review": re.compile(r"final(?:_|-)?review", re.IGNORECASE),
    "finding": re.compile(r"finding", re.IGNORECASE),
    "obligation": re.compile(r"obligation", re.IGNORECASE),
    "verification": re.compile(r"verification", re.IGNORECASE),
    "migrate_run": re.compile(r"migrate(?:_|-)?run", re.IGNORECASE),
}
PUBLIC_COMMANDS = {"run", "resume", "inspect"}
CURRENT_PUBLIC_PHRASES = (
    "The active CPE commands are exactly `run`, `resume`, and `inspect`.",
    "`run` defaults to `workspace-write`.",
    "`danger-full-access` is an explicit immutable run-creation opt-in.",
    "Superpowers owns engineering completion; CPE only reports a mechanical "
    "`handed_off`, `failed`, `blocked`, or `interrupted` status.",
    "CPE has no public retry, recovery, or verification command.",
)
STALE_PUBLIC_PATTERNS = {
    "danger-full-access default": re.compile(
        r"defaults?\s+to\s+`?danger-full-access",
        re.IGNORECASE,
    ),
    "controller slice": re.compile(r"--controller-slice-seconds"),
    "retry blocked": re.compile(r"--retry-blocked"),
    "retry failed": re.compile(r"--retry-failed"),
    "recover ledger": re.compile(r"\brecover-ledger\b", re.IGNORECASE),
    "verify command": re.compile(r"`?verify`?\s+command", re.IGNORECASE),
    "completed status": re.compile(r"`completed`", re.IGNORECASE),
    "checkpointed status": re.compile(r"`checkpointed`", re.IGNORECASE),
}
PYTHON_CPE_COMMAND = re.compile(
    r"(?<![\w/])(?:python3|python)[ \t]+"
    r"(?:[^\s`'\"<>]+/)*scripts/cpe\.py[ \t]+([a-z][a-z-]*)",
    re.IGNORECASE,
)
DIRECT_CPE_COMMAND = re.compile(
    r"(?:^[ \t]*(?:\$[ \t]*)?|(?<=`))"
    r"(?:[^\s`'\"<>]+/)*scripts/cpe\.py[ \t]+([a-z][a-z-]*)",
    re.IGNORECASE | re.MULTILINE,
)
PRODUCTION_LIMIT = 1500
MODULE_LIMIT = 450


def runtime_python(root: Path) -> list[Path]:
    return sorted((root / "scripts" / "cpe_runtime").rglob("*.py"))


def production_python(root: Path = ROOT) -> list[Path]:
    return sorted((root / "scripts").rglob("*.py"))


def production_schemas(root: Path) -> list[Path]:
    return sorted((root / "templates").rglob("*.json"))


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
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module] if node.module else []
            if node.level or node.module == "cpe_runtime":
                names.extend(alias.name for alias in node.names)
        else:
            continue
        for name in names:
            if name is not None:
                found.update(set(name.split(".")) & DELETED_MODULES)
    return found


def active_commands(document: Path) -> set[str]:
    text = document.read_text(encoding="utf-8")
    return {
        command.casefold()
        for pattern in (PYTHON_CPE_COMMAND, DIRECT_CPE_COMMAND)
        for command in pattern.findall(text)
    }


def active_contract_text(text: str) -> str:
    paragraphs = re.split(r"\n\s*\n", text)
    return "\n\n".join(
        paragraph
        for paragraph in paragraphs
        if "historical" not in paragraph.casefold()
    )


def check(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    scripts_root = root / "scripts"
    paths = production_python(root)
    production_inventory = {
        path.relative_to(scripts_root).as_posix() for path in paths
    }
    if production_inventory != EXPECTED_PRODUCTION_PYTHON:
        errors.append(
            "production Python inventory mismatch: "
            f"expected={sorted(EXPECTED_PRODUCTION_PYTHON)} "
            f"actual={sorted(production_inventory)}"
        )

    runtime_root = root / "scripts" / "cpe_runtime"
    runtime_inventory = {
        path.relative_to(runtime_root).as_posix()
        for path in runtime_python(root)
    }
    if runtime_inventory != EXPECTED_RUNTIME:
        errors.append(
            "runtime inventory mismatch: "
            f"expected={sorted(EXPECTED_RUNTIME)} actual={sorted(runtime_inventory)}"
        )
    template_root = root / "templates"
    schemas = production_schemas(root)
    template_inventory = {
        path.relative_to(template_root).as_posix() for path in schemas
    }
    if template_inventory != EXPECTED_TEMPLATES:
        errors.append(
            "template inventory mismatch: "
            f"expected={sorted(EXPECTED_TEMPLATES)} "
            f"actual={sorted(template_inventory)}"
        )

    for path in [*paths, *schemas]:
        text = path.read_text(encoding="utf-8")
        for name, pattern in SEMANTIC_PATTERNS.items():
            if pattern.search(text):
                errors.append(
                    f"forbidden semantic token {name!r}: {path.relative_to(root)}"
                )

    total = 0
    stdlib = sys.stdlib_module_names
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lines = len(text.splitlines())
        total += lines
        if lines > MODULE_LIMIT:
            errors.append(
                f"module line limit exceeded: {path.relative_to(root)}={lines}"
            )
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            errors.append(f"invalid Python: {path.relative_to(root)}: {exc}")
            continue
        external = absolute_import_roots(tree) - stdlib - {"cpe_runtime"}
        if external:
            errors.append(
                f"non-stdlib import: {path.relative_to(root)}={sorted(external)}"
            )
        deleted = imported_deleted_modules(tree)
        if deleted:
            errors.append(
                f"deleted-module import: {path.relative_to(root)}={sorted(deleted)}"
            )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "shell":
                    continue
                literal_false = (
                    isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is False
                )
                if not literal_false:
                    errors.append(
                        "shell keyword must be literal False: "
                        f"{path.relative_to(root)}:{node.lineno}"
                    )
    if total > PRODUCTION_LIMIT:
        errors.append(
            f"production line limit exceeded: total={total} limit={PRODUCTION_LIMIT}"
        )

    for name in ("SKILL.md", "README.md"):
        document = root / name
        text = document.read_text(encoding="utf-8")
        commands = active_commands(document)
        if commands != PUBLIC_COMMANDS:
            errors.append(
                f"active commands mismatch in {name}: "
                f"expected={sorted(PUBLIC_COMMANDS)} actual={sorted(commands)}"
            )
        normalized = " ".join(text.split())
        for phrase in CURRENT_PUBLIC_PHRASES:
            if " ".join(phrase.split()) not in normalized:
                errors.append(f"current contract missing in {name}: {phrase}")
        active_text = active_contract_text(text)
        for stale_name, pattern in STALE_PUBLIC_PATTERNS.items():
            if pattern.search(active_text):
                errors.append(f"stale active contract in {name}: {stale_name}")
    return errors


def main() -> int:
    errors = check()
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        return 1
    paths = production_python()
    counts = {
        path.relative_to(ROOT).as_posix(): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in paths
    }
    print(
        "PASS architecture "
        f"modules={len(paths)} total_lines={sum(counts.values())} "
        f"max_module={max(counts.values())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
