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
HARNESS = EVAL_DIR / "run.sh"
STATIC_RUNNERS = ("static_execution_runner.py", "static_prompt_runner.py")
REQUIRED_MAINTAINED = frozenset({
    "check_task_contract_v4.py",
    "check_checkpoint_lifecycle_v4.py",
    "check_method_evidence_v4.py",
    "check_autonomy_supervisor_v4.py",
    "check_v4_state_contract.py",
    "check_scheduler_v4.py",
    "check_prompt_bundle_v4.py",
    "check_quality_matrix_v4.py",
    "check_release_transaction_v4.py",
    "check_cpe_v4_e2e.py",
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
        target = EVAL_DIR / relative
        declaration = entry.get("production_entrypoint")
        if target.is_file() and isinstance(declaration, str):
            try:
                tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
            except SyntaxError:
                tree = None
            if tree is None or not _declared_entrypoints_backed(tree, declaration):
                failures.append(
                    f"declared production entrypoint is not reachable: {relative}:{declaration}"
                )
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


def _production_aliases(statements: list[ast.stmt]) -> set[str]:
    """Return production bindings created directly in one execution scope."""
    aliases: set[str] = set()
    for node in statements:
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module == "cpe"
            or node.module.startswith("cpe_runtime")
            or node.module.startswith("live_migration")
            or ".live_migration" in node.module
            or node.module.endswith(("live_model_migration", "live_model_runner"))
        ):
            aliases.update(item.asname or item.name for item in node.names if item.name != "*")
        elif isinstance(node, ast.Import):
            for item in node.names:
                if (
                    item.name == "cpe"
                    or item.name.startswith("cpe_runtime")
                    or item.name.startswith("live_migration")
                    or ".live_migration" in item.name
                    or item.name.endswith(("live_model_migration", "live_model_runner"))
                ):
                    aliases.add(item.asname or item.name.split(".")[0])
        if _statement_terminates(node):
            break
    return aliases


def _constant_truth(node: ast.AST) -> bool | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            nested = _constant_truth(node.operand)
            return None if nested is None else not nested
        return None
    return bool(value)


def _statements_terminate(statements: list[ast.stmt]) -> bool:
    return any(_statement_terminates(statement) for statement in statements)


def _statement_terminates(node: ast.stmt) -> bool:
    if isinstance(node, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
        return True
    if isinstance(node, ast.If):
        truth = _constant_truth(node.test)
        if truth is True:
            return _statements_terminate(node.body)
        if truth is False:
            return _statements_terminate(node.orelse)
        return bool(node.body and node.orelse) and (
            _statements_terminate(node.body) and _statements_terminate(node.orelse)
        )
    return False


class _ExecutableCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self.visit(statement)
            if _statement_terminates(statement):
                break

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        truth = _constant_truth(node.test)
        if truth is None:
            self.visit_statements(node.body)
            self.visit_statements(node.orelse)
            return
        self.visit_statements(node.body if truth else node.orelse)

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        truth = _constant_truth(node.test)
        selected = node.orelse if truth is False else [*node.body, *node.orelse]
        self.visit_statements(selected)


def _entrypoint_truth(node: ast.AST) -> bool | None:
    if (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "__name__"
        and len(node.ops) == 1
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value == "__main__"
    ):
        if isinstance(node.ops[0], ast.Eq):
            return True
        if isinstance(node.ops[0], ast.NotEq):
            return False
    return _constant_truth(node)


class _GuaranteedEntrypointCallVisitor(_ExecutableCallVisitor):
    """Collect calls only from branches proven to run for script execution."""

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        truth = _entrypoint_truth(node.test)
        if truth is None:
            return
        self.visit_statements(node.body if truth else node.orelse)

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        truth = _entrypoint_truth(node.test)
        if truth is False:
            self.visit_statements(node.orelse)


def _entrypoint_calls(tree: ast.Module) -> list[ast.Call]:
    definitions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    visitor = _GuaranteedEntrypointCallVisitor()
    visitor.visit_statements(tree.body)
    calls = list(visitor.calls)
    pending = [
        call.func.id
        for call in calls
        if isinstance(call.func, ast.Name) and call.func.id in definitions
    ]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        function_visitor = _GuaranteedEntrypointCallVisitor()
        function_visitor.visit_statements(definitions[name].body)
        calls.extend(function_visitor.calls)
        pending.extend(
            call.func.id
            for call in function_visitor.calls
            if isinstance(call.func, ast.Name)
            and call.func.id in definitions
            and call.func.id not in seen
        )
    return calls


def _executable_calls(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    visitor = _ExecutableCallVisitor()
    visitor.visit_statements(function.body)
    return visitor.calls


def _discoverable_test_methods(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    module_aliases = {"unittest": "unittest", "pytest": "pytest"}
    testcase_aliases = {"TestCase"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name in {"unittest", "pytest"}:
                    module_aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.ImportFrom) and node.module == "unittest":
            for item in node.names:
                if item.name == "TestCase":
                    testcase_aliases.add(item.asname or item.name)

    runner_kinds: set[str] = set()
    for call in _entrypoint_calls(tree):
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "main":
            continue
        if isinstance(call.func.value, ast.Name):
            runner = module_aliases.get(call.func.value.id)
            if runner:
                runner_kinds.add(runner)

    methods: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        unittest_case = "unittest" in runner_kinds and any(
            (isinstance(base, ast.Name) and base.id in testcase_aliases)
            or (
                isinstance(base, ast.Attribute)
                and base.attr == "TestCase"
                and isinstance(base.value, ast.Name)
                and module_aliases.get(base.value.id) == "unittest"
            )
            for base in node.bases
        )
        pytest_case = "pytest" in runner_kinds and node.name.startswith("Test")
        if unittest_case or pytest_case:
            methods.extend(
                method
                for method in node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                and method.name.startswith("test_")
            )
    return methods


def _reachable_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    definitions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    pending = ["main"]
    seen: set[str] = set()
    reachable = _discoverable_test_methods(tree)
    while pending:
        name = pending.pop()
        if name in seen or name not in definitions:
            continue
        seen.add(name)
        function = definitions[name]
        reachable.append(function)
        for node in _executable_calls(function):
            if isinstance(node.func, ast.Name) and node.func.id in definitions and node.func.id not in seen:
                pending.append(node.func.id)
    return reachable


def _declared_entrypoints_backed(tree: ast.Module, declaration: str) -> bool:
    """Bind declared production modules to AST imports and reachable calls."""

    reachable = _reachable_functions(tree)
    definitions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    selected = {function.name for function in reachable}
    pending = [
        node.id
        for function in reachable
        for node in ast.walk(function)
        if isinstance(node, ast.Name) and node.id in definitions
    ]
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        selected.add(name)
        function = definitions[name]
        reachable.append(function)
        pending.extend(
            node.id
            for node in ast.walk(function)
            if isinstance(node, ast.Name)
            and node.id in definitions
            and node.id not in selected
        )
    calls = [call for function in reachable for call in _executable_calls(function)]
    imports: dict[str, set[str]] = {}
    statements = list(tree.body)
    for function in reachable:
        statements.extend(function.body)
    for node in statements:
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.setdefault(node.module, set()).update(
                item.asname or item.name for item in node.names if item.name != "*"
            )
        elif isinstance(node, ast.Import):
            for item in node.names:
                imports.setdefault(item.name, set()).add(
                    item.asname or item.name.split(".")[0]
                )

    called_roots: set[str] = set()
    public_cpe_subprocess = False
    for call in calls:
        root = call.func
        while isinstance(root, ast.Attribute):
            root = root.value
        if isinstance(root, ast.Name):
            called_roots.add(root.id)
        if ast.unparse(call.func) in {"subprocess.run", "subprocess.Popen"}:
            rendered = ast.unparse(call)
            if "cpe.py" in rendered:
                public_cpe_subprocess = True

    for raw in declaration.split(","):
        declared = raw.strip()
        module = (
            declared
            if declared.startswith(("cpe_runtime.", "live_migration."))
            else "cpe"
            if declared == "cpe" or declared.startswith("cpe.")
            else declared
        )
        aliases = imports.get(module, set())
        if not aliases.intersection(called_roots) and not (
            module == "cpe" and public_cpe_subprocess
        ):
            return False
    return True


def _production_backed(tree: ast.Module) -> bool:
    reachable = _reachable_functions(tree)
    if not reachable:
        return False
    module_aliases = _production_aliases(tree.body)
    assignments = {
        target.id: ast.unparse(node.value)
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and (targets := ([node.target] if isinstance(node, ast.AnnAssign) else node.targets))
        for target in targets
        if isinstance(target, ast.Name)
    }
    for function in reachable:
        aliases = module_aliases | _production_aliases(function.body)
        for node in _executable_calls(function):
            if isinstance(node.func, ast.Name) and node.func.id in aliases:
                return True
            if isinstance(node.func, ast.Attribute):
                root = node.func.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in aliases:
                    return True
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
    forbidden_identifiers = (oracle_text, ORACLE.name, "public-cli-oracles", "ORACLE_TARGET")

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

    def inspect_surface(value: object, surface: str) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                inspect_surface(key, surface)
                inspect_surface(item, surface)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                inspect_surface(item, surface)
            return
        rendered = str(value)
        if any(identifier in rendered for identifier in forbidden_identifiers):
            raise PermissionError(f"fixture runner subprocess {surface} attempted to reference its oracle")

    def inspect_subprocess(argv_value: object, kwargs: dict[str, object]) -> tuple[str, ...]:
        normalized = _argv_strings(argv_value)
        launched.append(normalized)
        inspect_surface(argv_value, "argv")
        for key in ("env", "cwd", "input", "args"):
            inspect_surface(kwargs.get(key), key)
        if kwargs.get("shell"):
            inspect_surface(argv_value, "shell command")
        return normalized

    def guarded_run(argv_value=None, *args, **kwargs):
        actual = kwargs.get("args") if argv_value is None else argv_value
        inspect_subprocess(actual, kwargs)
        return original_run(*args, **kwargs) if argv_value is None else original_run(argv_value, *args, **kwargs)

    def guarded_popen(argv_value=None, *args, **kwargs):
        actual = kwargs.get("args") if argv_value is None else argv_value
        inspect_subprocess(actual, kwargs)
        return original_popen(*args, **kwargs) if argv_value is None else original_popen(argv_value, *args, **kwargs)

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
        environment_reader = root / "environment_oracle_read.py"
        environment_reader.write_text(
            "import os, subprocess, sys\n"
            f"env = {{**os.environ, 'ORACLE_TARGET': {str(ORACLE.resolve())!r}}}\n"
            "subprocess.run([sys.executable, '-c', \"import os; open(os.environ['ORACLE_TARGET']).read()\"], env=env, check=True)\n",
            encoding="utf-8",
        )
        caught: dict[str, bool] = {}
        for name, script in (
            ("conditional_full_path_oracle_read_rejected", conditional),
            ("subprocess_oracle_read_rejected", subprocess_reader),
            ("subprocess_environment_oracle_read_rejected", environment_reader),
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
            "checks": [entry for entry in entries if entry.get("path") != "check_scheduler_v4.py"],
        },
        "declared_production_entrypoint_mismatch_rejected": {
            **payload,
            "checks": [
                {
                    **entry,
                    **(
                        {"production_entrypoint": "cpe_runtime.comment_only"}
                        if index == 0
                        else {}
                    ),
                }
                for index, entry in enumerate(entries)
            ],
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
    assigned_import = ast.parse(
        "from cpe_runtime.validation import validate_run\n"
        "def main():\n    _ = validate_run\n    print('{\"passed\": true}')\n    return 0\n"
    )
    dead_call = ast.parse(
        "from cpe_runtime.validation import validate_run\n"
        "def main():\n    if False:\n        validate_run(None)\n    print('{\"passed\": true}')\n    return 0\n"
    )
    helper_call = ast.parse(
        "from cpe_runtime.validation import validate_run\n"
        "def exercise():\n    return validate_run(None)\n"
        "def main():\n    exercise()\n    return 0\n"
    )
    unused_decoy_test = ast.parse(
        "from cpe_runtime.validation import validate_run\n"
        "class DecoyTests:\n"
        "    def test_production(self):\n        validate_run(None)\n"
        "def main():\n    print('{\"passed\": true}')\n    return 0\n"
    )
    environment_gated_unittest = ast.parse(
        "import os\n"
        "import unittest\n"
        "from cpe_runtime.validation import validate_run\n"
        "class ProductionTests(unittest.TestCase):\n"
        "    def test_production(self):\n        validate_run(None)\n"
        "if os.environ.get('RUN_TESTS'):\n    unittest.main()\n"
    )
    dead_scope_import = ast.parse(
        "def decoy():\n"
        "    from cpe_runtime.validation import validate_run\n"
        "def main():\n"
        "    try:\n        validate_run(None)\n"
        "    except NameError:\n        pass\n"
        "    return 0\n"
    )
    post_return_import = ast.parse(
        "def main():\n"
        "    try:\n        validate_run(None)\n"
        "    except NameError:\n        pass\n"
        "    return 0\n"
        "    from cpe_runtime.validation import validate_run\n"
    )
    reachable_alternate_branch = ast.parse(
        "from cpe_runtime.validation import validate_run\n"
        "def main():\n"
        "    if runtime_condition():\n        return 0\n"
        "    else:\n        validate_run(None)\n"
    )
    guard_checks, trace = _oracle_guard_checks()
    inventory_payload = json.loads(args.inventory.read_text(encoding="utf-8"))
    mutation_checks = _inventory_mutation_checks(inventory_payload)
    harness_text = HARNESS.read_text(encoding="utf-8")
    checks = {
        "required_inventory_exact": set(paths) == REQUIRED_MAINTAINED,
        "unique_inventory": len(paths) == len(set(paths)),
        "all_paths_exist": all((EVAL_DIR / path).is_file() for path in paths),
        "ast_anti_stub": not any("literal-success" in item or "reachable production" in item for item in failures),
        "unused_production_import_rejected": not _production_backed(unused_import),
        "assigned_production_reference_rejected": not _production_backed(assigned_import),
        "dead_branch_production_call_rejected": not _production_backed(dead_call),
        "reachable_helper_production_call_accepted": _production_backed(helper_call),
        "unexecuted_decoy_test_method_rejected": not _production_backed(unused_decoy_test),
        "environment_gated_unittest_runner_rejected": not _production_backed(environment_gated_unittest),
        "dead_scope_production_import_rejected": not _production_backed(dead_scope_import),
        "post_return_production_import_rejected": not _production_backed(post_return_import),
        "reachable_alternate_branch_accepted": _production_backed(reachable_alternate_branch),
        "runner_source_has_no_oracle_reference": "oracle" not in RUNNER.read_text(encoding="utf-8").lower()
        and "check_public_cli_integration" not in RUNNER.read_text(encoding="utf-8"),
        "static_runners_removed": not any("static runner" in item for item in failures),
        "oracle_isolated": ORACLE.resolve() not in trace.opened,
        "oracle_guard_executed_full_runner": trace.results_written,
        "runner_invoked_public_subprocesses": bool(trace.subprocess_argv),
        "subscription_dry_run_wired": all(
            token in harness_text
            for token in (
                "live_model_runner.py",
                "dry-run",
                "--billing-mode",
                "chatgpt_subscription",
                "--output",
            )
        ),
        "pending_baseline_expansion_bounded": all(
            token in harness_text
            for token in (
                "ALLOWED_T8_ADDITIONS",
                "maintained:check_live_matrix_compiler",
                "maintained:check_live_matrix_fixtures",
                "maintained:check_live_matrix_ledger",
                "maintained:check_live_matrix_oracle",
                "maintained:check_live_model_runner",
                "subscription_live_matrix_dry_run",
                "unexpected maintained eval baseline expansion",
            )
        ),
        **guard_checks,
        **mutation_checks,
    }
    failures.extend(name for name, passed in checks.items() if not passed and name not in failures)
    print(json.dumps({"passed": not failures, "checks": checks, "failures": failures}, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
