import dataclasses
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from plan_runner.recovery import (  # noqa: E402
    ActivityLease,
    ProgressSnapshot,
    RecoveryPolicy,
    canonical_failure_signature,
    strategy_note_digest,
)


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


def progress(
    tree: str = "tree-a",
    *,
    done: tuple[str, ...] = (),
    receipts: tuple[str, ...] = (),
    findings: tuple[str, ...] = (),
) -> ProgressSnapshot:
    return ProgressSnapshot(tree, done, receipts, findings)


def state(**overrides):
    values = {
        "controller_alive": True,
        "input_digest": "input-a",
        "session_id": "session-1",
        "session_health": "healthy",
        "resume_failed": False,
        "failure_sequence": (),
        "failure_baseline_progress": progress(),
        "reported_done_evidence": {},
        "observed_tree_digests": ("tree-a",),
    }
    values.update(overrides)
    return values


def outcome(**overrides):
    values = {
        "reason_code": "provider_unavailable",
        "provider_code": "transport_closed",
        "command_identity": None,
        "candidate_head": "a" * 40,
        "input_digest": "input-a",
        "interruption": "simple",
        "strategy_note": "retry through the alternate transport",
        "progress": progress(),
        "reported_done_evidence": {},
        "logs": ["unstable"],
        "timestamp": "2026-07-23T00:00:00Z",
        "token_output": 100,
        "model": "gpt-5.6",
    }
    values.update(overrides)
    return values


class ActivityLeaseTest(unittest.TestCase):
    def test_only_distinct_tool_and_lifecycle_events_refresh_provider_activity(self):
        clock = FakeClock(10)
        lease = ActivityLease(5, clock.now)

        clock.advance(4)
        self.assertTrue(lease.observe_provider_event("tool_started", "tool-1", clock.now))
        clock.advance(4)
        self.assertFalse(lease.expired(clock.now))
        self.assertTrue(lease.observe_provider_event("tool_finished", "tool-1", clock.now))
        clock.advance(4)
        self.assertTrue(
            lease.observe_provider_event("lifecycle_advanced", "review", clock.now)
        )
        clock.advance(4)
        self.assertFalse(lease.expired(clock.now))
        self.assertTrue(lease.expired(clock.advance(1)))

    def test_repeated_and_non_material_events_never_refresh_provider_activity(self):
        clock = FakeClock()
        lease = ActivityLease(10, clock.now)
        self.assertTrue(lease.observe_provider_event("tool_started", "tool-1", 1))

        for kind, key in (
            ("tool_started", "tool-1"),
            ("token_delta", "new-token"),
            ("warning", "same-warning"),
            ("output_digest", "digest-1"),
            ("helper_heartbeat", "pid-123"),
            ("process_exists", "pid-123"),
        ):
            self.assertFalse(lease.observe_provider_event(kind, key, 9))

        self.assertFalse(lease.expired(10.999))
        self.assertTrue(lease.expired(11))

    def test_explicit_command_deadline_covers_but_does_not_refresh_provider_lease(self):
        clock = FakeClock()
        lease = ActivityLease(60, clock.now)
        lease.cover_command_until(7_201)

        self.assertFalse(lease.expired(clock.advance(3_601)))
        self.assertFalse(
            lease.observe_provider_event("helper_heartbeat", "heartbeat-1", clock.now)
        )
        self.assertFalse(
            lease.observe_provider_event("process_exists", "pid-1", clock.advance(3_599))
        )
        self.assertFalse(lease.expired(clock.now))
        self.assertTrue(lease.expired(clock.advance(1)))

        lease.command_finished(clock.now)
        self.assertFalse(lease.expired(clock.advance(59.999)))
        self.assertTrue(lease.expired(clock.advance(0.001)))


class FailureSignatureTest(unittest.TestCase):
    def test_signature_uses_only_canonical_stable_failure_facts(self):
        stable = {
            "reason_code": "verification_failed",
            "provider_code": "exit_1",
            "command_identity": "verify-unit",
            "candidate_head": "a" * 40,
            "input_digest": "input-a",
        }
        first = canonical_failure_signature(stable)
        second = canonical_failure_signature(
            {
                **stable,
                "logs": ["different"],
                "timestamp": "later",
                "token_output": 999,
                "model": "some-other-model",
            }
        )
        self.assertEqual(first, second)
        self.assertNotEqual(
            first,
            canonical_failure_signature({**stable, "provider_code": "exit_2"}),
        )

    def test_strategy_notes_are_trimmed_scrubbed_bounded_and_hashed(self):
        secret = "  use API_TOKEN=super-secret then fallback  "
        scrubbed = "use API_TOKEN=[REDACTED] then fallback"
        self.assertEqual(strategy_note_digest(secret), strategy_note_digest(scrubbed))
        self.assertEqual(
            strategy_note_digest("x" * 4_096),
            strategy_note_digest("x" * 4_096 + "discarded"),
        )
        with self.assertRaises(ValueError):
            strategy_note_digest(" \t ")


class RecoveryPolicyTest(unittest.TestCase):
    def setUp(self):
        self.policy = RecoveryPolicy()

    def test_decision_records_are_immutable(self):
        snapshot = progress()
        decision = self.policy.decide(state(), outcome())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.git_tree_digest = "changed"
        with self.assertRaises(dataclasses.FrozenInstanceError):
            decision.action = "changed"

    def test_live_controller_recovers_while_absent_controller_is_resumable(self):
        live = self.policy.decide(state(), outcome())
        self.assertEqual((live.action, live.run_status), ("recover", "recovering"))

        absent = self.policy.decide(state(controller_alive=False), outcome())
        self.assertEqual((absent.action, absent.run_status), ("resume", "resumable"))

    def test_healthy_simple_interruption_resumes_explicit_session(self):
        decision = self.policy.decide(state(), outcome())
        self.assertEqual(decision.session_action, "explicit_resume")
        self.assertTrue(decision.required_strategy_change)

    def test_contaminated_or_unavailable_sessions_require_fresh_session(self):
        cases = (
            {"reason_code": "stall_expired"},
            {"interruption": "repeated_signature"},
            {"interruption": "context_overflow"},
            {"interruption": "abnormal_compaction"},
            {"interruption": "session_damage"},
            {"session_health": "suspect"},
            {"session_id": None},
            {"resume_failed": True},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                state_changes = {
                    key: value
                    for key, value in changes.items()
                    if key in {"session_health", "session_id", "resume_failed"}
                }
                outcome_changes = {
                    key: value for key, value in changes.items() if key not in state_changes
                }
                decision = self.policy.decide(
                    state(**state_changes), outcome(**outcome_changes)
                )
                self.assertEqual(decision.session_action, "fresh_session")

    def test_input_digest_change_requires_new_run(self):
        decision = self.policy.decide(state(), outcome(input_digest="input-b"))
        self.assertEqual(decision.action, "fail")
        self.assertEqual(decision.run_status, "failed")
        self.assertEqual(decision.session_action, "none")
        self.assertEqual(decision.reason_code, "input_changed_requires_new_run")

    def test_initial_attempt_plus_three_distinct_changed_strategies_are_allowed(self):
        failure = canonical_failure_signature(outcome())
        notes = tuple(
            strategy_note_digest(note)
            for note in ("strategy one", "strategy two", "strategy three")
        )
        for prior_count in range(4):
            sequence = (
                {"failure_signature": failure, "strategy_note_digest": None},
                *(
                    {
                        "failure_signature": failure,
                        "strategy_note_digest": digest,
                    }
                    for digest in notes[:prior_count]
                ),
            )
            decision = self.policy.decide(
                state(failure_sequence=sequence),
                outcome(strategy_note=f"strategy {prior_count + 1} changed"),
            )
            if prior_count < 3:
                self.assertEqual(decision.run_status, "recovering")
            else:
                self.assertEqual(decision.run_status, "failed")
                self.assertEqual(decision.reason_code, "recovery_exhausted")

    def test_alternating_failure_signatures_cannot_bypass_global_strategy_cap(self):
        sequence = tuple(
            {
                "failure_signature": canonical_failure_signature(
                    outcome(
                        provider_code=f"provider-{index}",
                        command_identity=f"command-{index}",
                        candidate_head=str(index) * 40,
                    )
                ),
                "strategy_note_digest": strategy_note_digest(f"strategy-{index}"),
            }
            for index in range(3)
        )
        decision = self.policy.decide(
            state(failure_sequence=sequence),
            outcome(
                provider_code="provider-current",
                command_identity="command-current",
                candidate_head="9" * 40,
                strategy_note="fourth changed strategy",
            ),
        )
        self.assertEqual(decision.run_status, "failed")
        self.assertEqual(decision.reason_code, "recovery_exhausted")

    def test_duplicate_strategy_note_digest_is_rejected(self):
        failure = canonical_failure_signature(outcome())
        repeated = strategy_note_digest("same changed strategy")
        decision = self.policy.decide(
            state(
                failure_sequence=(
                    {"failure_signature": failure, "strategy_note_digest": None},
                    {
                        "failure_signature": failure,
                        "strategy_note_digest": repeated,
                    },
                )
            ),
            outcome(strategy_note=" same changed strategy "),
        )
        self.assertEqual(decision.run_status, "failed")
        self.assertEqual(decision.reason_code, "recovery_exhausted")

    def test_each_evidence_backed_material_progress_resets_failure_sequence(self):
        failure = canonical_failure_signature(outcome())
        exhausted = tuple(
            {
                "failure_signature": failure,
                "strategy_note_digest": strategy_note_digest(f"prior-{index}"),
            }
            for index in range(4)
        )
        baselines_and_currents = (
            (progress("tree-a"), progress("tree-b"), {}, {}),
            (
                progress(done=("T1",)),
                progress(done=("T1", "T2")),
                {"T1": "1" * 64},
                {"T1": "1" * 64, "T2": "2" * 64},
            ),
            (
                progress(receipts=("r1",)),
                progress(receipts=("r1", "r2")),
                {},
                {},
            ),
            (
                progress(findings=("F1",)),
                progress(findings=("F1", "F2")),
                {},
                {},
            ),
        )
        for baseline, current, prior_evidence, current_evidence in baselines_and_currents:
            with self.subTest(current=current):
                decision = self.policy.decide(
                    state(
                        failure_sequence=exhausted,
                        failure_baseline_progress=baseline,
                        reported_done_evidence=prior_evidence,
                    ),
                    outcome(
                        progress=current,
                        strategy_note="new reset strategy",
                        reported_done_evidence=current_evidence,
                    ),
                )
                self.assertEqual(decision.run_status, "recovering")
                self.assertEqual(decision.session_action, "explicit_resume")

    def test_tree_digest_seen_earlier_does_not_reset_after_a_to_b_to_a_toggle(self):
        failure = canonical_failure_signature(outcome())
        exhausted = tuple(
            {
                "failure_signature": f"{failure[:-1]}{index}",
                "strategy_note_digest": strategy_note_digest(f"prior-{index}"),
            }
            for index in range(3)
        )
        decision = self.policy.decide(
            state(
                failure_sequence=exhausted,
                failure_baseline_progress=progress("tree-b"),
                observed_tree_digests=("tree-a", "tree-b"),
            ),
            outcome(progress=progress("tree-a"), strategy_note="toggle again"),
        )
        self.assertEqual(decision.run_status, "failed")
        self.assertEqual(decision.reason_code, "recovery_exhausted")

    def test_reported_done_requires_novel_sha256_evidence_association(self):
        failure = canonical_failure_signature(outcome())
        exhausted = tuple(
            {
                "failure_signature": f"{failure[:-1]}{index}",
                "strategy_note_digest": strategy_note_digest(f"prior-{index}"),
            }
            for index in range(3)
        )
        baseline = progress(done=("T1",))
        current = progress(done=("T1", "T2"))
        prior = {"T1": "1" * 64}

        positive = self.policy.decide(
            state(
                failure_sequence=exhausted,
                failure_baseline_progress=baseline,
                reported_done_evidence=prior,
            ),
            outcome(
                progress=current,
                reported_done_evidence={**prior, "T2": "2" * 64},
                strategy_note="evidence-backed progress",
            ),
        )
        self.assertEqual(positive.run_status, "recovering")

        invalid_evidence = (
            {},
            {**prior, "T2": "not-a-sha256"},
            {**prior, "T2": "1" * 64},
        )
        for evidence in invalid_evidence:
            with self.subTest(evidence=evidence):
                decision = self.policy.decide(
                    state(
                        failure_sequence=exhausted,
                        failure_baseline_progress=baseline,
                        reported_done_evidence=prior,
                    ),
                    outcome(
                        progress=current,
                        reported_done_evidence=evidence,
                        strategy_note="unsupported claimed progress",
                    ),
                )
                self.assertEqual(decision.run_status, "failed")
                self.assertEqual(decision.reason_code, "recovery_exhausted")

    def test_non_material_observations_and_returned_tree_do_not_reset_sequence(self):
        failure = canonical_failure_signature(outcome())
        exhausted = tuple(
            {
                "failure_signature": failure,
                "strategy_note_digest": strategy_note_digest(f"prior-{index}"),
            }
            for index in range(4)
        )
        decision = self.policy.decide(
            state(
                failure_sequence=exhausted,
                failure_baseline_progress=progress("tree-a"),
                observed_tree_digests=("tree-a", "tree-b", "tree-a"),
                logs=["new log"],
                timestamp="later",
                token_output=999,
            ),
            outcome(
                progress=progress("tree-a"),
                logs=["different log"],
                timestamp="even later",
                token_output=10_000,
                strategy_note="still another strategy",
            ),
        )
        self.assertEqual(decision.run_status, "failed")
        self.assertEqual(decision.reason_code, "recovery_exhausted")

    def test_automatic_decision_never_selects_or_exposes_a_model(self):
        decision = self.policy.decide(
            state(model="state-model"), outcome(model="outcome-model")
        )
        self.assertNotIn("model", dataclasses.asdict(decision))
        self.assertNotIn("state-model", repr(decision))
        self.assertNotIn("outcome-model", repr(decision))


if __name__ == "__main__":
    unittest.main()
