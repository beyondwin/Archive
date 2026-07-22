#!/usr/bin/env python3
"""Unit evals for clpe.py pure functions."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import clpe


class SchemaFileTest(unittest.TestCase):
    def test_schema_is_valid_json_with_status_enum(self):
        schema = json.loads(clpe.SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["properties"]["status"]["enum"],
            ["completed", "blocked", "failed"],
        )
        self.assertEqual(
            sorted(schema["required"]),
            ["head_commit", "open_findings", "status", "summary"],
        )


class ResultShapeTest(unittest.TestCase):
    def completed(self):
        return {
            "status": "completed",
            "head_commit": "a" * 40,
            "summary": "done",
            "open_findings": [],
        }

    def test_completed_shape_passes(self):
        self.assertEqual(clpe.validate_result_shape(self.completed()), [])

    def test_non_dict_rejected(self):
        self.assertTrue(clpe.validate_result_shape(["x"]))
        self.assertTrue(clpe.validate_result_shape(None))

    def test_missing_fields_reported(self):
        errors = clpe.validate_result_shape({"status": "completed"})
        self.assertTrue(any("head_commit" in e for e in errors))
        self.assertTrue(any("summary" in e for e in errors))
        self.assertTrue(any("open_findings" in e for e in errors))

    def test_bad_status_and_sha_rejected(self):
        record = self.completed()
        record["status"] = "done"
        record["head_commit"] = "not-a-sha"
        errors = clpe.validate_result_shape(record)
        self.assertTrue(any("status" in e for e in errors))
        self.assertTrue(any("head_commit" in e for e in errors))

    def test_blocked_requires_blocker(self):
        record = self.completed()
        record["status"] = "blocked"
        errors = clpe.validate_result_shape(record)
        self.assertTrue(any("blocker" in e for e in errors))
        record["blocker"] = {"kind": "env", "detail": "docker missing"}
        self.assertEqual(clpe.validate_result_shape(record), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
