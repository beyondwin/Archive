import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.recovery import (  # noqa: E402
    ActivityLease,
    ProgressSnapshot,
    RecoveryDecision,
    RecoveryPolicy,
    canonical_failure_signature,
    normalize_strategy_note,
    strategy_note_digest,
)


def progress(tree="tree-a", tasks=(), receipts=(), findings=()):
    return ProgressSnapshot(tree, tuple(tasks), tuple(receipts), tuple(findings))


class RecoveryBehaviorTest(unittest.TestCase):
    def test_activity_lease_accepts_only_unique_tools_or_lifecycle_and_not_heartbeat(self):
        lease = ActivityLease(10, 100)
        self.assertFalse(lease.observe_provider_event("log", "noise", 105))
        self.assertTrue(lease.observe_provider_event("tool_started", "tool-1", 106))
        self.assertFalse(lease.observe_provider_event("tool_started", "tool-1", 109))
        self.assertFalse(lease.expired(115.9))
        self.assertTrue(lease.expired(116))
        lease.cover_command_until(5000)
        self.assertFalse(lease.expired(4999))
        self.assertTrue(lease.expired(5000))

    def test_strategy_notes_are_redacted_bounded_and_stable(self):
        normalized = normalize_strategy_note("  change path API_TOKEN=secret  ")
        self.assertEqual(normalized, "change path API_TOKEN=[REDACTED]")
        self.assertEqual(strategy_note_digest(normalized), strategy_note_digest("change path API_TOKEN=other"))
        self.assertLessEqual(len(normalize_strategy_note("x" * 9000).encode()), 4096)
        with self.assertRaises(ValueError):
            normalize_strategy_note("  ")

    def test_failure_signature_ignores_unstable_logs(self):
        base = {"reason_code": "stall_expired", "provider_code": "x", "input_digest": "i"}
        self.assertEqual(
            canonical_failure_signature({**base, "log": "first"}),
            canonical_failure_signature({**base, "log": "second"}),
        )

    def test_live_controller_recovers_absent_controller_is_resumable(self):
        policy = RecoveryPolicy()
        state = self.state(controller_alive=True)
        live = policy.decide(state, self.outcome("new strategy"))
        self.assertEqual((live.action, live.run_status), ("recover", "recovering"))
        state["controller_alive"] = False
        stopped = policy.decide(state, self.outcome("new strategy"))
        self.assertEqual((stopped.action, stopped.run_status), ("resume", "resumable"))

    def test_healthy_transport_interruption_resumes_but_contamination_goes_fresh(self):
        policy = RecoveryPolicy()
        state = self.state()
        self.assertEqual(policy.decide(state, self.outcome("one")).session_action, "explicit_resume")
        for reason, interruption in (
            ("stall_expired", "stall"),
            ("session_invalid", "session_damage"),
            ("controller_transport_failed", "context_overflow"),
        ):
            outcome = self.outcome(f"strategy {reason}")
            outcome.update(reason_code=reason, interruption=interruption)
            self.assertEqual(policy.decide(state, outcome).session_action, "fresh_session")

    def test_input_change_duplicate_strategy_and_fourth_change_fail_closed(self):
        policy = RecoveryPolicy()
        mismatch = self.outcome("x")
        mismatch["input_digest"] = "different"
        self.assertEqual(policy.decide(self.state(), mismatch).reason_code, "input_changed_requires_new_run")
        signature = canonical_failure_signature(self.outcome("ignored"))
        entries = [
            {"failure_signature": signature, "strategy_note_digest": strategy_note_digest(note)}
            for note in ("one", "two", "three")
        ]
        state = self.state(failure_sequence=entries)
        self.assertEqual(policy.decide(state, self.outcome("four")).reason_code, "recovery_exhausted")

    def test_new_evidence_resets_strategy_cap_but_tree_toggle_does_not(self):
        policy = RecoveryPolicy()
        outcome = self.outcome("new after progress", progress=progress("tree-b", receipts=("r1",)))
        state = self.state(
            failure_sequence=[{"failure_signature": canonical_failure_signature(outcome), "strategy_note_digest": strategy_note_digest("old")}],
            failure_baseline_progress=progress(),
            observed_tree_digests=("tree-a",),
        )
        self.assertEqual(policy.decide(state, outcome).action, "recover")
        outcome["progress"] = progress("tree-a")
        state["observed_tree_digests"] = ("tree-a", "tree-b")
        state["failure_sequence"] = [
            {"failure_signature": canonical_failure_signature(outcome), "strategy_note_digest": strategy_note_digest(x)}
            for x in ("one", "two", "three")
        ]
        self.assertEqual(policy.decide(state, outcome).reason_code, "recovery_exhausted")

    def test_decisions_are_immutable_and_never_choose_models(self):
        decision = RecoveryDecision("recover", "recovering", "fresh_session", "x", True, "stall_expired")
        with self.assertRaises(FrozenInstanceError):
            decision.action = "model-escalation"
        self.assertFalse(hasattr(decision, "model"))

    @staticmethod
    def state(**updates):
        base = {
            "input_digest": "input",
            "controller_alive": True,
            "session_id": "session",
            "session_health": "healthy",
            "failure_sequence": [],
            "failure_baseline_progress": progress(),
            "observed_tree_digests": ("tree-a",),
            "reported_done_evidence": {},
        }
        base.update(updates)
        return base

    @staticmethod
    def outcome(note, progress=progress()):
        return {
            "reason_code": "controller_transport_failed",
            "provider_code": "transport",
            "input_digest": "input",
            "strategy_note": note,
            "progress": progress,
            "reported_done_evidence": {},
        }


if __name__ == "__main__":
    unittest.main()
