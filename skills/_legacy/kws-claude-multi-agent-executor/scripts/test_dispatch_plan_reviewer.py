"""Tests for dispatch_plan_reviewer — Plan Reviewer model selection logic."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dispatch_plan_reviewer import (  # noqa: E402
    DEFAULT_PLAN_REVIEWER_MODEL,
    record_model_used,
    select_plan_reviewer_model,
)


class SelectPlanReviewerModelTests(unittest.TestCase):
    def test_default_model_is_opus_when_no_override(self):
        self.assertEqual(
            select_plan_reviewer_model({}),
            "claude-opus-4-8",
        )

    def test_default_constant_is_opus(self):
        self.assertEqual(DEFAULT_PLAN_REVIEWER_MODEL, "claude-opus-4-8")

    def test_default_is_opus(self):
        # v2.25: Plan Reviewer defaults to Opus (Opus-everywhere for this executor)
        state = {"dispatch_config": {}}
        self.assertEqual(select_plan_reviewer_model(state), "claude-opus-4-8")

    def test_override_via_dispatch_config_is_honored(self):
        state = {"dispatch_config": {"plan_reviewer_model": "claude-sonnet-4-6"}}
        self.assertEqual(select_plan_reviewer_model(state), "claude-sonnet-4-6")

    def test_empty_dispatch_config_falls_back_to_default(self):
        state = {"dispatch_config": {}}
        self.assertEqual(
            select_plan_reviewer_model(state),
            "claude-opus-4-8",
        )


class RecordModelUsedTests(unittest.TestCase):
    def test_writes_model_used_into_plan_review(self):
        state = {}
        selected = record_model_used(state)
        self.assertEqual(selected, "claude-opus-4-8")
        self.assertEqual(state["plan_review"]["model_used"], "claude-opus-4-8")

    def test_records_overridden_model(self):
        state = {"dispatch_config": {"plan_reviewer_model": "claude-sonnet-4-6"}}
        selected = record_model_used(state)
        self.assertEqual(selected, "claude-sonnet-4-6")
        self.assertEqual(state["plan_review"]["model_used"], "claude-sonnet-4-6")

    def test_preserves_existing_plan_review_fields(self):
        state = {"plan_review": {"status": "PASS", "warnings": []}}
        record_model_used(state)
        self.assertEqual(state["plan_review"]["status"], "PASS")
        self.assertEqual(state["plan_review"]["warnings"], [])
        self.assertEqual(state["plan_review"]["model_used"], "claude-opus-4-8")


if __name__ == "__main__":
    unittest.main()
