import ast
import json
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1]
RUNTIME = SKILL_ROOT / "scripts" / "plan_runner"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


class IndependentRuntimeTest(unittest.TestCase):
    def test_public_result_schemas_match_codex_contract_bytes(self):
        peer = REPO_ROOT / "skills" / "kws-codex-plan-runner" / "templates"
        local = SKILL_ROOT / "templates"
        for name in ("plan-result.schema.json", "finalization-result.schema.json"):
            self.assertEqual(
                (local / name).read_bytes(),
                (peer / name).read_bytes(),
                f"{name} semantic contract drifted",
            )

    def test_runtime_imports_no_codex_runner_module(self):
        forbidden = {
            "kws-codex-plan-runner",
            "kws_codex_plan_runner",
            "codex_plan_runner",
        }
        for path in sorted(RUNTIME.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            joined = "\n".join(imports) + "\n" + source
            for marker in forbidden:
                self.assertNotIn(marker, joined, f"{path} depends on {marker}")

    def test_contract_fixture_is_not_a_runtime_import(self):
        for path in sorted(RUNTIME.glob("*.py")):
            self.assertNotIn(
                "plan-runner-contract-v1.json",
                path.read_text(encoding="utf-8"),
            )

    def test_runtime_vocabulary_matches_contract(self):
        from plan_runner.contracts import (
            CONTRACT_VERSION,
            FAILURE_TAXONOMY,
            FORMAT_VERSION,
            PLAN_STATUSES,
            RUNNER_RUNTIME_CONTRACT,
            RUN_STATUSES,
            TASK_STATUSES,
            ExitCode,
        )

        fixture = json.loads(
            (REPO_ROOT / "scripts/agent/fixtures/plan-runner-contract-v1.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(CONTRACT_VERSION, fixture["contract_version"])
        self.assertEqual(FORMAT_VERSION, fixture["state_format_version"])
        self.assertEqual(sorted(RUN_STATUSES), sorted(fixture["run_statuses"]))
        self.assertEqual(sorted(PLAN_STATUSES), sorted(fixture["plan_statuses"]))
        self.assertEqual(sorted(TASK_STATUSES), sorted(fixture["task_statuses"]))
        self.assertEqual(sorted(FAILURE_TAXONOMY), sorted(fixture["failure_taxonomy"]))
        self.assertEqual(RUNNER_RUNTIME_CONTRACT, fixture["runner_runtime"])
        self.assertEqual(
            {item.name.lower(): int(item) for item in ExitCode},
            fixture["exit_codes"],
        )


if __name__ == "__main__":
    unittest.main()
