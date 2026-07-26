from __future__ import annotations

import io
import unittest


class V2EvalDiscoveryTest(unittest.TestCase):
    def test_affected_eval_modules_execute_against_the_v2_runner_contract(self):
        suite = unittest.defaultTestLoader.loadTestsFromNames(
            [
                "evals.test_contracts",
                "evals.test_engine",
                "evals.test_storage",
                "evals.test_helper",
                "evals.test_evidence",
                "evals.test_provider",
                "evals.test_recovery",
            ]
        )
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)


if __name__ == "__main__":
    unittest.main()
