from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .contracts import sha256_json


_ACTIVITY_KINDS = frozenset(
    {"tool_started", "tool_finished", "lifecycle_advanced"}
)
_SESSION_INVALIDATING_INTERRUPTS = frozenset(
    {
        "repeated_signature",
        "stall",
        "context_overflow",
        "abnormal_compaction",
        "session_damage",
    }
)
_SESSION_INVALIDATING_REASONS = frozenset({"stall_expired", "session_invalid"})
_SECRET = re.compile(
    r"(?i)(?:[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|API_KEY)|password)=[^\s]+"
)
_STABLE_FAILURE_FIELDS = (
    "reason_code",
    "provider_code",
    "command_identity",
    "candidate_head",
    "input_digest",
)
_MAX_STRATEGY_BYTES = 4_096
_MAX_CHANGED_STRATEGIES = 3


@dataclass(frozen=True)
class ProgressSnapshot:
    git_tree_digest: str
    reported_done_ids: tuple[str, ...]
    successful_receipt_digests: tuple[str, ...]
    resolved_finding_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.git_tree_digest, str) or not self.git_tree_digest:
            raise ValueError("Git tree digest must be a non-empty string")
        for label, values in (
            ("reported-done IDs", self.reported_done_ids),
            ("successful receipt digests", self.successful_receipt_digests),
            ("resolved finding IDs", self.resolved_finding_ids),
        ):
            if (
                not isinstance(values, tuple)
                or any(not isinstance(value, str) or not value for value in values)
                or len(values) != len(set(values))
            ):
                raise ValueError(f"{label} must be a tuple of unique strings")


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    run_status: str
    session_action: str
    failure_signature: str | None
    required_strategy_change: bool
    reason_code: str


class ActivityLease:
    def __init__(self, stall_seconds: float, started_at: float) -> None:
        if (
            not isinstance(stall_seconds, (int, float))
            or isinstance(stall_seconds, bool)
            or not math.isfinite(stall_seconds)
            or stall_seconds <= 0
        ):
            raise ValueError("stall_seconds must be positive")
        if (
            not isinstance(started_at, (int, float))
            or isinstance(started_at, bool)
            or not math.isfinite(started_at)
        ):
            raise ValueError("started_at must be finite")
        self._stall_seconds = float(stall_seconds)
        self._last_activity = float(started_at)
        self._seen_keys: set[tuple[str, str]] = set()
        self._command_deadline: float | None = None

    def observe_provider_event(self, kind: str, unique_key: str, now: float) -> bool:
        if kind not in _ACTIVITY_KINDS:
            return False
        key = (kind, unique_key)
        if key in self._seen_keys:
            return False
        self._seen_keys.add(key)
        self._last_activity = _finite_time(now, "event time")
        return True

    def cover_command_until(self, deadline: float) -> None:
        self._command_deadline = _finite_time(deadline, "command deadline")

    def command_finished(self, now: float) -> None:
        self._command_deadline = None
        self._last_activity = _finite_time(now, "command finish time")

    def expired(self, now: float) -> bool:
        observed_at = _finite_time(now, "observation time")
        if self._command_deadline is not None:
            return observed_at >= self._command_deadline
        return observed_at - self._last_activity >= self._stall_seconds


def _finite_time(value: object, label: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValueError(f"{label} must be finite")
    return float(value)


def canonical_failure_signature(facts: Mapping[str, object]) -> str:
    if not isinstance(facts, Mapping):
        raise ValueError("failure facts must be a mapping")
    stable = {field: facts.get(field) for field in _STABLE_FAILURE_FIELDS}
    return sha256_json(stable)


def _normalized_strategy_note(note: object) -> str:
    if not isinstance(note, str):
        raise ValueError("strategy note must be a string")
    normalized = _SECRET.sub(
        lambda match: match.group(0).split("=", 1)[0] + "=[REDACTED]",
        note.strip(),
    )
    encoded = normalized.encode("utf-8")[:_MAX_STRATEGY_BYTES]
    normalized = encoded.decode("utf-8", "ignore")
    if not normalized:
        raise ValueError("strategy note must be non-empty")
    return normalized


def strategy_note_digest(note: object) -> str:
    normalized = _normalized_strategy_note(note)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _material_progress(
    baseline: ProgressSnapshot | None, current: ProgressSnapshot
) -> bool:
    if baseline is None:
        return False
    return (
        current.git_tree_digest != baseline.git_tree_digest
        or bool(set(current.reported_done_ids) - set(baseline.reported_done_ids))
        or bool(
            set(current.successful_receipt_digests)
            - set(baseline.successful_receipt_digests)
        )
        or bool(
            set(current.resolved_finding_ids) - set(baseline.resolved_finding_ids)
        )
    )


def _sequence_entries(value: object) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("failure sequence must be a sequence")
    if any(not isinstance(entry, Mapping) for entry in value):
        raise ValueError("failure sequence entries must be mappings")
    return value


class RecoveryPolicy:
    def decide(
        self, state: Mapping[str, object], outcome: Mapping[str, object]
    ) -> RecoveryDecision:
        if not isinstance(state, Mapping) or not isinstance(outcome, Mapping):
            raise ValueError("recovery state and outcome must be mappings")

        expected_input = state.get("input_digest")
        observed_input = outcome.get("input_digest")
        if expected_input != observed_input:
            return RecoveryDecision(
                action="fail",
                run_status="failed",
                session_action="none",
                failure_signature=None,
                required_strategy_change=False,
                reason_code="input_changed_requires_new_run",
            )

        reason_code = outcome.get("reason_code")
        if not isinstance(reason_code, str) or not reason_code:
            raise ValueError("recovery outcome reason_code must be non-empty")
        signature = canonical_failure_signature(outcome)
        baseline = state.get("failure_baseline_progress")
        current = outcome.get("progress")
        progress_reset = (
            isinstance(current, ProgressSnapshot)
            and (baseline is None or isinstance(baseline, ProgressSnapshot))
            and _material_progress(baseline, current)
        )
        session_action = self._session_action(
            state, outcome, signature, progress_reset=progress_reset
        )

        if not state.get("controller_alive"):
            return RecoveryDecision(
                action="resume",
                run_status="resumable",
                session_action=session_action,
                failure_signature=signature,
                required_strategy_change=True,
                reason_code=reason_code,
            )

        sequence = _sequence_entries(state.get("failure_sequence", ()))
        if baseline is not None and not isinstance(baseline, ProgressSnapshot):
            raise ValueError("failure baseline progress is invalid")
        if not isinstance(current, ProgressSnapshot):
            raise ValueError("outcome progress is invalid")

        same_failure = [] if _material_progress(baseline, current) else [
            entry
            for entry in sequence
            if entry.get("failure_signature") == signature
        ]
        try:
            next_strategy = strategy_note_digest(outcome.get("strategy_note"))
        except ValueError:
            return self._exhausted(signature)
        prior_strategies = {
            digest
            for entry in same_failure
            if isinstance(
                (digest := entry.get("strategy_note_digest")),
                str,
            )
        }
        if (
            next_strategy in prior_strategies
            or len(prior_strategies) >= _MAX_CHANGED_STRATEGIES
        ):
            return self._exhausted(signature)

        return RecoveryDecision(
            action="recover",
            run_status="recovering",
            session_action=session_action,
            failure_signature=signature,
            required_strategy_change=True,
            reason_code=reason_code,
        )

    @staticmethod
    def _session_action(
        state: Mapping[str, object],
        outcome: Mapping[str, object],
        failure_signature: str,
        *,
        progress_reset: bool,
    ) -> str:
        sequence = _sequence_entries(state.get("failure_sequence", ()))
        repeated_signature = not progress_reset and any(
            entry.get("failure_signature") == failure_signature
            for entry in sequence
        )
        if (
            not state.get("session_id")
            or state.get("session_health") != "healthy"
            or state.get("resume_failed") is True
            or outcome.get("reason_code") in _SESSION_INVALIDATING_REASONS
            or outcome.get("interruption") in _SESSION_INVALIDATING_INTERRUPTS
            or repeated_signature
        ):
            return "fresh_session"
        return "explicit_resume"

    @staticmethod
    def _exhausted(signature: str) -> RecoveryDecision:
        return RecoveryDecision(
            action="fail",
            run_status="failed",
            session_action="none",
            failure_signature=signature,
            required_strategy_change=False,
            reason_code="recovery_exhausted",
        )
