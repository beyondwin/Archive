#!/usr/bin/env python3
"""Fail closed when the maintained eval harness can satisfy itself."""

from __future__ import annotations

import ast
import builtins
import json
import re
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


EVAL_DIR = Path(__file__).resolve().parent
INVENTORY = EVAL_DIR / "maintained-checks.json"
RUN_SH = EVAL_DIR / "run.sh"
ORACLE = EVAL_DIR / "public-cli-oracles.json"
RUNNER = EVAL_DIR / "public_cli_fixture_runner.py"
STATIC_RUNNERS = ("static_execution_runner.py", "static_prompt_runner.py")


def _wired_paths() -> list[str]:
    if INVENTORY.is_file():
        payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
        entries = payload.get("checks") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError("maintained inventory must contain a checks list")
        return [str(entry.get("path", "")) for entry in entries if isinstance(entry, dict)]
    return re.findall(r'python3 "\$EVAL_DIR/([^"]+\.py)"', RUN_SH.read_text(encoding="utf-8"))


def _production_backed(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module == "cpe" or node.module.startswith("cpe_runtime")
        ):
            return True
        if isinstance(node, ast.Call):
            rendered = ast.unparse(node)
            if "scripts" in rendered and "cpe.py" in rendered and (
                "subprocess.run" in rendered or "subprocess.Popen" in rendered
            ):
                return True
    return False


def _literal_success_main(tree: ast.Module) -> bool:
    main = next(
        (node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"),
        None,
    )
    if main is None:
        return False
    observable = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"print"}
    ]
    returns = [node for node in ast.walk(main) if isinstance(node, ast.Return)]
    return bool(observable and returns) and all(
        isinstance(node.value, ast.Constant) and node.value.value == 0 for node in returns
    ) and not _production_backed(tree)


def _runner_opened_paths() -> set[Path]:
    if not RUNNER.is_file():
        return set()
    opened: set[Path] = set()
    original_open = builtins.open
    original_path_open = Path.open

    def guarded_open(file, *args, **kwargs):
        path = Path(file).expanduser().resolve()
        opened.add(path)
        if path == ORACLE.resolve():
            raise PermissionError("fixture runner attempted to read its oracle")
        return original_open(file, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        resolved = path.expanduser().resolve()
        opened.add(resolved)
        if resolved == ORACLE.resolve():
            raise PermissionError("fixture runner attempted to read its oracle")
        return original_path_open(path, *args, **kwargs)

    old_argv = sys.argv
    with tempfile.TemporaryDirectory(prefix="cpe-oracle-guard-") as raw:
        sys.argv = [str(RUNNER), "--output-dir", raw, "--dry-run"]
        try:
            with patch("builtins.open", guarded_open), patch("pathlib.Path.open", guarded_path_open):
                try:
                    runpy.run_path(str(RUNNER), run_name="__main__")
                except SystemExit as exc:
                    if exc.code not in (0, None):
                        raise AssertionError(f"fixture runner guard failed: {exc.code}") from exc
        finally:
            sys.argv = old_argv
    return opened


def _inventory_mutation_checks() -> dict[str, bool]:
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    entries = payload["checks"]
    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-inventory-mutation-") as raw:
        root = Path(raw)
        mutations = {
            "duplicate_inventory_rejected": {**payload, "checks": entries + [entries[0]]},
            "missing_inventory_path_rejected": {
                **payload,
                "checks": entries + [{
                    "path": "check_missing_inventory_sentinel.py",
                    "production_entrypoint": "cpe_runtime.missing",
                    "mutation_assertion": "missing path is rejected",
                }],
            },
        }
        for name, mutated in mutations.items():
            path = root / f"{name}.json"
            path.write_text(json.dumps(mutated) + "\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(RUN_SH)],
                cwd=EVAL_DIR.parent,
                env={**dict(__import__("os").environ), "CPE_MAINTAINED_CHECKS": str(path)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            results[name] = result.returncode != 0 and (
                "duplicated" in result.stderr or "missing" in result.stderr
            )
    return results


def main() -> int:
    failures: list[str] = []
    paths = _wired_paths()
    if len(paths) != len(set(paths)):
        failures.append("maintained inventory contains duplicate check paths")
    for relative in paths:
        path = EVAL_DIR / relative
        if not path.is_file():
            failures.append(f"missing maintained check: {relative}")
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"invalid maintained check: {relative}: {exc}")
            continue
        if _literal_success_main(tree):
            failures.append(f"literal-success maintained check: {relative}")
        if not _production_backed(tree):
            failures.append(f"maintained check lacks production/public behavior: {relative}")
    for relative in STATIC_RUNNERS:
        if (EVAL_DIR / relative).exists():
            failures.append(f"self-fulfilling static runner remains: {relative}")
    if INVENTORY.is_file() and RUNNER.is_file():
        opened = _runner_opened_paths()
        if ORACLE.resolve() in opened:
            failures.append("public fixture runner read oracle outcomes")
        if (EVAL_DIR / "public-cli-cases.json").resolve() not in opened:
            failures.append("public fixture runner did not read case stimuli")
        mutation_checks = _inventory_mutation_checks()
        failures.extend(name for name, passed in mutation_checks.items() if not passed)
    else:
        mutation_checks = {}
    checks = {
        "unique_inventory": len(paths) == len(set(paths)),
        "all_paths_exist": all((EVAL_DIR / path).is_file() for path in paths),
        "ast_anti_stub": not any("literal-success" in item or "lacks production" in item for item in failures),
        "static_runners_removed": not any("static runner" in item for item in failures),
        "oracle_isolated": not any("oracle" in item for item in failures),
        **mutation_checks,
    }
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
