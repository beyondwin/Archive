#!/usr/bin/env python3
"""Fail closed when the maintained eval harness can satisfy itself."""

from __future__ import annotations

import argparse
import ast
import builtins
import json
import os
import runpy
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch


EVAL_DIR = Path(__file__).resolve().parent
INVENTORY = EVAL_DIR / "maintained-checks.json"
ORACLE = EVAL_DIR / "public-cli-oracles.json"
RUNNER = EVAL_DIR / "public_cli_fixture_runner.py"
STATIC_RUNNERS = ("static_execution_runner.py", "static_prompt_runner.py")
REQUIRED_MAINTAINED = frozenset({
    "check_cpe_replay.py",
    "check_event_kernel.py",
    "check_execution_runtime.py",
    "check_fault_injection.py",
    "check_headless_result.py",
    "check_inspect_runs.py",
    "check_manifest_evidence.py",
    "check_model_policy.py",
    "check_operational_run_quality.py",
    "check_plan_executability_audit.py",
    "check_preflight_dispatch.py",
    "check_recent_run_rubric.py",
    "check_recovery_policy.py",
    "check_repair_runs.py",
    "check_run_diffs.py",
    "check_run_readiness.py",
    "check_state_reconciliation.py",
    "check_state_schema.py",
    "check_task_packet.py",
    "check_validate_state_modular_parity.py",
    "check_validation_consumer_parity.py",
    "check_verification_bundle.py",
})


def _inventory_paths(path: Path) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"maintained inventory unreadable: {exc}"]
    entries = payload.get("checks") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return [], ["maintained inventory must contain a checks list"]
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            failures.append("maintained inventory entry is not an object")
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative.endswith(".py"):
            failures.append("maintained inventory path is invalid")
            continue
        if not entry.get("production_entrypoint") or not entry.get("mutation_assertion"):
            failures.append(f"maintained inventory metadata is incomplete: {relative}")
        paths.append(relative)
    if len(paths) != len(set(paths)):
        failures.append("maintained inventory contains duplicate check paths")
    actual = set(paths)
    for missing in sorted(REQUIRED_MAINTAINED - actual):
        failures.append(f"required maintained check omitted: {missing}")
    for unexpected in sorted(actual - REQUIRED_MAINTAINED):
        failures.append(f"unexpected maintained check: {unexpected}")
    for relative in paths:
        if not (EVAL_DIR / relative).is_file():
            failures.append(f"missing maintained check: {relative}")
    return paths, failures


def _production_aliases(tree: ast.Module) -> set[str]:
    aliases: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module == "cpe" or node.module.startswith("cpe_runtime")
        ):
            aliases.update(item.asname or item.name for item in node.names if item.name != "*")
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "cpe" or item.name.startswith("cpe_runtime"):
                    aliases.add(item.asname or item.name.split(".")[0])
    return aliases


def _reachable_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    definitions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    pending = ["main"]
    seen: set[str] = set()
    reachable: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    while pending:
        name = pending.pop()
        if name in seen or name not in definitions:
            continue
        seen.add(name)
        function = definitions[name]
        reachable.append(function)
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in definitions and node.func.id not in seen:
                    pending.append(node.func.id)
    return reachable


def _production_backed(tree: ast.Module) -> bool:
    reachable = _reachable_functions(tree)
    if not reachable:
        return False
    aliases = _production_aliases(tree)
    referenced = {
        node.id
        for function in reachable
        for node in ast.walk(function)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    if aliases & referenced:
        return True
    assignments = {
        target.id: ast.unparse(node.value)
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and (targets := ([node.target] if isinstance(node, ast.AnnAssign) else node.targets))
        for target in targets
        if isinstance(target, ast.Name)
    }
    for function in reachable:
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            target = ast.unparse(node.func)
            if target not in {"subprocess.run", "subprocess.Popen"}:
                continue
            rendered = ast.unparse(node)
            rendered += " " + " ".join(
                assignments.get(name.id, "") for name in ast.walk(node) if isinstance(name, ast.Name)
            )
            if "scripts" in rendered and "cpe.py" in rendered:
                return True
    return False


def _literal_success_main(tree: ast.Module) -> bool:
    main = next((item for item in _reachable_functions(tree) if item.name == "main"), None)
    if main is None:
        return False
    prints = [
        node for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"
    ]
    returns = [node for node in ast.walk(main) if isinstance(node, ast.Return)]
    return bool(prints and returns) and all(
        isinstance(node.value, ast.Constant) and node.value.value == 0 for node in returns
    ) and not _production_backed(tree)


@dataclass(frozen=True)
class GuardTrace:
    opened: frozenset[Path]
    subprocess_argv: tuple[tuple[str, ...], ...]
    results_written: bool


def _argv_strings(argv: object) -> tuple[str, ...]:
    if isinstance(argv, (list, tuple)):
        return tuple(str(item) for item in argv)
    return (str(argv),)


def _guarded_script(script: Path, argv: list[str], output_dir: Path) -> GuardTrace:
    opened: set[Path] = set()
    launched: list[tuple[str, ...]] = []
    original_open = builtins.open
    original_path_open = Path.open
    original_run = subprocess.run
    original_popen = subprocess.Popen
    oracle_text = str(ORACLE.resolve())

    def deny_oracle(path: Path) -> None:
        resolved = path.expanduser().resolve()
        opened.add(resolved)
        if resolved == ORACLE.resolve():
            raise PermissionError("fixture runner attempted to read its oracle")

    def guarded_open(file, *args, **kwargs):
        if isinstance(file, (str, os.PathLike)):
            deny_oracle(Path(file))
        return original_open(file, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        deny_oracle(path)
        return original_path_open(path, *args, **kwargs)

    def inspect_argv(argv_value: object) -> tuple[str, ...]:
        normalized = _argv_strings(argv_value)
        launched.append(normalized)
        if any(oracle_text in item for item in normalized):
            raise PermissionError("fixture runner subprocess attempted to read its oracle")
        return normalized

    def guarded_run(argv_value, *args, **kwargs):
        inspect_argv(argv_value)
        return original_run(argv_value, *args, **kwargs)

    def guarded_popen(argv_value, *args, **kwargs):
        inspect_argv(argv_value)
        return original_popen(argv_value, *args, **kwargs)

    old_argv = sys.argv
    sys.argv = argv
    try:
        with (
            patch("builtins.open", guarded_open),
            patch("pathlib.Path.open", guarded_path_open),
            patch("subprocess.run", guarded_run),
            patch("subprocess.Popen", guarded_popen),
        ):
            try:
                runpy.run_path(str(script), run_name="__main__")
            except SystemExit as exc:
                if exc.code not in (0, None):
                    raise AssertionError(f"guarded script failed: {exc.code}") from exc
    finally:
        sys.argv = old_argv
    return GuardTrace(frozenset(opened), tuple(launched), (output_dir / "results.json").is_file())


def _oracle_guard_checks() -> tuple[dict[str, bool], GuardTrace]:
    with tempfile.TemporaryDirectory(prefix="cpe-oracle-guard-") as raw:
        root = Path(raw)
        results = root / "results"
        trace = _guarded_script(RUNNER, [str(RUNNER), "--output-dir", str(results)], results)
        conditional = root / "conditional_oracle_read.py"
        conditional.write_text(
            "from pathlib import Path\n"
            f"if True:\n    Path({str(ORACLE.resolve())!r}).read_text(encoding='utf-8')\n",
            encoding="utf-8",
        )
        subprocess_reader = root / "subprocess_oracle_read.py"
        child_code = f"print(open({str(ORACLE.resolve())!r}).read())"
        subprocess_reader.write_text(
            "import subprocess, sys\n"
            f"subprocess.run([sys.executable, '-c', {child_code!r}], check=True)\n",
            encoding="utf-8",
        )
        caught: dict[str, bool] = {}
        for name, script in (
            ("conditional_full_path_oracle_read_rejected", conditional),
            ("subprocess_oracle_read_rejected", subprocess_reader),
        ):
            try:
                _guarded_script(script, [str(script)], root / name)
            except PermissionError:
                caught[name] = True
            else:
                caught[name] = False
        return caught, trace


def _inventory_mutation_checks(payload: dict[str, object]) -> dict[str, bool]:
    entries = payload["checks"]
    assert isinstance(entries, list)
    mutations = {
        "duplicate_inventory_rejected": {**payload, "checks": entries + [entries[0]]},
        "referenced_missing_inventory_path_rejected": {
            **payload,
            "checks": entries + [{
                "path": "check_missing_inventory_sentinel.py",
                "production_entrypoint": "cpe_runtime.missing",
                "mutation_assertion": "missing path is rejected",
            }],
        },
        "required_inventory_omission_rejected": {
            **payload,
            "checks": [entry for entry in entries if entry.get("path") != "check_execution_runtime.py"],
        },
    }
    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="cpe-inventory-mutation-") as raw:
        for name, mutated in mutations.items():
            path = Path(raw) / f"{name}.json"
            path.write_text(json.dumps(mutated) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--inventory", str(path), "--inventory-only"],
                cwd=EVAL_DIR.parent,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            results[name] = result.returncode != 0
    return results


def _inventory_only(path: Path) -> int:
    paths, failures = _inventory_paths(path)
    payload = {
        "passed": not failures,
        "checks": {
            "required_inventory_exact": set(paths) == REQUIRED_MAINTAINED,
            "unique_inventory": len(paths) == len(set(paths)),
        },
        "failures": failures,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    if args.inventory_only:
        return _inventory_only(args.inventory)

    paths, failures = _inventory_paths(args.inventory)
    for relative in paths:
        path = EVAL_DIR / relative
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"invalid maintained check: {relative}: {exc}")
            continue
        if _literal_success_main(tree):
            failures.append(f"literal-success maintained check: {relative}")
        if not _production_backed(tree):
            failures.append(f"maintained check lacks reachable production/public behavior: {relative}")
    for relative in STATIC_RUNNERS:
        if (EVAL_DIR / relative).exists():
            failures.append(f"self-fulfilling static runner remains: {relative}")

    unused_import = ast.parse(
        "from cpe_runtime.scheduler import route_verdict\n"
        "def main():\n    print('{\"passed\": true}')\n    return 0\n"
    )
    guard_checks, trace = _oracle_guard_checks()
    inventory_payload = json.loads(args.inventory.read_text(encoding="utf-8"))
    mutation_checks = _inventory_mutation_checks(inventory_payload)
    checks = {
        "required_inventory_exact": set(paths) == REQUIRED_MAINTAINED,
        "unique_inventory": len(paths) == len(set(paths)),
        "all_paths_exist": all((EVAL_DIR / path).is_file() for path in paths),
        "ast_anti_stub": not any("literal-success" in item or "reachable production" in item for item in failures),
        "unused_production_import_rejected": not _production_backed(unused_import),
        "static_runners_removed": not any("static runner" in item for item in failures),
        "oracle_isolated": ORACLE.resolve() not in trace.opened,
        "oracle_guard_executed_full_runner": trace.results_written,
        "runner_invoked_public_subprocesses": bool(trace.subprocess_argv),
        **guard_checks,
        **mutation_checks,
    }
    failures.extend(name for name, passed in checks.items() if not passed and name not in failures)
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
