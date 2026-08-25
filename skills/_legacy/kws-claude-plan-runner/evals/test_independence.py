import ast
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = SKILL_ROOT / "scripts" / "plan_runner"
CLAUDE_PRODUCTION_PYTHON = (
    SKILL_ROOT / "scripts" / "runner.py",
    *sorted(RUNTIME.glob("*.py")),
)
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


class IndependentRuntimeTest(unittest.TestCase):
    def test_claude_contract_has_one_local_result_schema(self):
        schemas = sorted(
            path.name
            for path in (SKILL_ROOT / "templates").glob("*.schema.json")
        )
        self.assertEqual(schemas, ["plan-result.schema.json"])

    def test_runtime_imports_no_codex_or_root_contract_module(self):
        for path in CLAUDE_PRODUCTION_PYTHON:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            joined = "\n".join(imports) + "\n" + source
            self.assertNotIn(
                "kws-codex-plan-runner",
                joined,
                f"{path} depends on the Codex runner",
            )
            self.assertNotIn(
                "scripts/agent/fixtures",
                joined,
                f"{path} depends on a root contract fixture",
            )

    def test_contract_fixture_is_not_a_runtime_import(self):
        for path in sorted(RUNTIME.glob("*.py")):
            self.assertNotIn(
                "plan-runner-contract-v1.json",
                path.read_text(encoding="utf-8"),
            )

    def test_runtime_vocabulary_is_version_two_and_claude_local(self):
        from plan_runner.contracts import (
            CONTRACT_VERSION,
            FORMAT_VERSION,
            PLAN_STATUSES,
            RUNNER_RUNTIME_CONTRACT,
            TASK_STATUSES,
            ExitCode,
        )

        self.assertEqual((FORMAT_VERSION, CONTRACT_VERSION), (2, 2))
        self.assertEqual(
            PLAN_STATUSES,
            frozenset({"pending", "running", "implemented"}),
        )
        self.assertEqual(TASK_STATUSES, frozenset())
        self.assertEqual(RUNNER_RUNTIME_CONTRACT["managed_by"], "uv")
        self.assertEqual(
            {item.name.lower(): int(item) for item in ExitCode}["ready"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
