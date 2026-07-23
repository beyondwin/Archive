from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .contracts import sha256_json

_TRUSTED_ACTIVITY = frozenset(("tool_started", "tool_finished", "lifecycle_advanced"))
_CONTAMINATED_INTERRUPTS = frozenset(
    ("repeated_signature", "stall", "context_overflow", "abnormal_compaction", "session_damage")
)
_CONTAMINATED_REASONS = frozenset(("stall_expired", "session_invalid"))
_STABLE_FAILURE_FIELDS = (
    "reason_code", "provider_code", "command_identity", "candidate_head", "input_digest"
)
_AUTH_HEADER_VALUE = re.compile(
    r"""(?ix)
    (?P<prefix>
        (?<![A-Z0-9_.-])
        ["']?(?:proxy-)?authorization["']?
        \s*[:=]\s*
    )
    (?P<value>
        "(?:\\.|[^"\\\r\n])*"
        |'(?:\\.|[^'\\\r\n])*'
        |(?:bearer|basic)\s+[^\s,;}]+
    )
    """
)
_SECRET_KEY_VALUE = re.compile(
    r"""(?ix)
    (?P<prefix>
        (?<![A-Z0-9_.-])
        ["']?
        (?:
            (?:[A-Z][A-Z0-9_.-]*[_-])?
            (?:TOKEN|SECRET|API[_-]?KEY|PASSWORD|PASSWD|CREDENTIAL|
               ACCESS[_-]?KEY|PRIVATE[_-]?KEY|SECRET[_-]?KEY)
            |DATABASE_URL|PGPASSWORD|MYSQL_PWD
        )
        ["']?
        \s*[:=]\s*
    )
    (?P<value>
        "(?:\\.|[^"\\\r\n])*"
        |'(?:\\.|[^'\\\r\n])*'
        |[^\s,;}]+
    )
    """
)
_KNOWN_PROVIDER_SECRET = re.compile(
    r"""(?x)
    (?<![A-Za-z0-9_-])
    (?:
        sk-(?:ant|proj|svcacct)-[A-Za-z0-9_-]{12,}
        |sk-[A-Za-z0-9_-]{20,}
        |gh[pousr]_[A-Za-z0-9]{20,}
        |github_pat_[A-Za-z0-9_]{20,}
        |(?:AKIA|ASIA)[A-Z0-9]{16}
        |AIza[A-Za-z0-9_-]{20,}
        |xox[baprs]-[A-Za-z0-9-]{10,}
        |(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}
    )
    (?![A-Za-z0-9_-])
    """
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_NOTE_LIMIT = 4096
_MAX_CHANGES = 3


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
            if not isinstance(values, tuple) or len(values) != len(set(values)):
                raise ValueError(f"{label} must be a tuple of unique strings")
            if any(not isinstance(item, str) or not item for item in values):
                raise ValueError(f"{label} must be a tuple of unique strings")


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    run_status: str
    session_action: str
    failure_signature: str | None
    required_strategy_change: bool
    reason_code: str


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)


class ActivityLease:
    def __init__(self, stall_seconds: float, started_at: float) -> None:
        self._window = _finite(stall_seconds, "stall_seconds")
        if self._window <= 0:
            raise ValueError("stall_seconds must be positive")
        self._last_progress = _finite(started_at, "started_at")
        self._observed: set[tuple[str, str]] = set()
        self._covered_until: float | None = None

    def observe_provider_event(self, kind: str, unique_key: str, now: float) -> bool:
        marker = (kind, unique_key)
        if kind not in _TRUSTED_ACTIVITY or marker in self._observed:
            return False
        self._observed.add(marker)
        self._last_progress = _finite(now, "event time")
        return True

    def cover_command_until(self, deadline: float) -> None:
        self._covered_until = _finite(deadline, "command deadline")

    def command_finished(self, now: float) -> None:
        self._covered_until = None
        self._last_progress = _finite(now, "command finish time")

    def expired(self, now: float) -> bool:
        moment = _finite(now, "observation time")
        if self._covered_until is not None:
            return moment >= self._covered_until
        return moment - self._last_progress >= self._window


def canonical_failure_signature(facts: Mapping[str, object]) -> str:
    if not isinstance(facts, Mapping):
        raise ValueError("failure facts must be a mapping")
    return sha256_json({name: facts.get(name) for name in _STABLE_FAILURE_FIELDS})


def normalize_strategy_note(note: object) -> str:
    if not isinstance(note, str):
        raise ValueError("strategy note must be a string")
    cleaned = _AUTH_HEADER_VALUE.sub(
        _mask_structured_secret,
        note.strip(),
    )
    cleaned = _SECRET_KEY_VALUE.sub(
        _mask_structured_secret,
        cleaned,
    )
    cleaned = _KNOWN_PROVIDER_SECRET.sub(
        "[REDACTED_PROVIDER_CREDENTIAL]",
        cleaned,
    )
    cleaned = cleaned.encode("utf-8")[:_NOTE_LIMIT].decode("utf-8", "ignore")
    if not cleaned:
        raise ValueError("strategy note must be non-empty")
    return cleaned


def _mask_structured_secret(match: re.Match[str]) -> str:
    value = match.group("value")
    if value.startswith('"') and value.endswith('"'):
        replacement = '"[REDACTED]"'
    elif value.startswith("'") and value.endswith("'"):
        replacement = "'[REDACTED]'"
    else:
        replacement = "[REDACTED]"
    return match.group("prefix") + replacement


def strategy_note_digest(note: object) -> str:
    return hashlib.sha256(normalize_strategy_note(note).encode()).hexdigest()


def _entries(value: object) -> Sequence[Mapping[str, object]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("failure sequence must be a sequence")
    if any(not isinstance(row, Mapping) for row in value):
        raise ValueError("failure sequence entries must be mappings")
    return value


def _progressed(state: Mapping[str, object], current: ProgressSnapshot) -> bool:
    baseline = state.get("failure_baseline_progress")
    if baseline is None:
        return False
    if not isinstance(baseline, ProgressSnapshot):
        raise ValueError("failure baseline progress is invalid")
    observed = state.get("observed_tree_digests", ())
    trees = set(observed) if isinstance(observed, Sequence) and not isinstance(observed, (str, bytes)) else {baseline.git_tree_digest}
    novel_tree = current.git_tree_digest != baseline.git_tree_digest and current.git_tree_digest not in trees
    novel_receipt = bool(set(current.successful_receipt_digests) - set(baseline.successful_receipt_digests))
    novel_finding = bool(set(current.resolved_finding_ids) - set(baseline.resolved_finding_ids))
    old_evidence = state.get("reported_done_evidence", {})
    new_evidence = state.get("_current_reported_done_evidence", {})
    known = set(old_evidence.values()) if isinstance(old_evidence, Mapping) else set()
    task_progress = False
    if isinstance(new_evidence, Mapping):
        for task in set(current.reported_done_ids) - set(baseline.reported_done_ids):
            digest = new_evidence.get(task)
            task_progress |= isinstance(digest, str) and _SHA256.fullmatch(digest) is not None and digest not in known
    return novel_tree or novel_receipt or novel_finding or task_progress


class RecoveryPolicy:
    def decide(self, state: Mapping[str, object], outcome: Mapping[str, object]) -> RecoveryDecision:
        if not isinstance(state, Mapping) or not isinstance(outcome, Mapping):
            raise ValueError("recovery state and outcome must be mappings")
        if state.get("input_digest") != outcome.get("input_digest"):
            return RecoveryDecision(
                "fail", "failed", "none", None, False, "input_changed_requires_new_run"
            )
        reason = outcome.get("reason_code")
        if not isinstance(reason, str) or not reason:
            raise ValueError("recovery outcome reason_code must be non-empty")
        current = outcome.get("progress")
        if not isinstance(current, ProgressSnapshot):
            raise ValueError("outcome progress is invalid")
        augmented = dict(state)
        augmented["_current_reported_done_evidence"] = outcome.get("reported_done_evidence", {})
        reset = _progressed(augmented, current)
        signature = canonical_failure_signature(outcome)
        session_action = self._session_action(state, outcome, signature, reset)
        if not state.get("controller_alive"):
            return RecoveryDecision("resume", "resumable", session_action, signature, True, reason)
        sequence = [] if reset else list(_entries(state.get("failure_sequence", ())))
        try:
            proposed = strategy_note_digest(outcome.get("strategy_note"))
        except ValueError:
            return self._exhausted(signature)
        prior = {
            row.get("strategy_note_digest")
            for row in sequence
            if row.get("failure_signature") == signature
            and isinstance(row.get("strategy_note_digest"), str)
        }
        if proposed in prior or len(prior) >= _MAX_CHANGES:
            return self._exhausted(signature)
        return RecoveryDecision("recover", "recovering", session_action, signature, True, reason)

    @staticmethod
    def _session_action(
        state: Mapping[str, object],
        outcome: Mapping[str, object],
        signature: str,
        reset: bool,
    ) -> str:
        repeated = not reset and any(
            row.get("failure_signature") == signature
            for row in _entries(state.get("failure_sequence", ()))
        )
        invalid = (
            not state.get("session_id")
            or state.get("session_health") != "healthy"
            or state.get("resume_failed") is True
            or outcome.get("reason_code") in _CONTAMINATED_REASONS
            or outcome.get("interruption") in _CONTAMINATED_INTERRUPTS
            or repeated
        )
        return "fresh_session" if invalid else "explicit_resume"

    @staticmethod
    def _exhausted(signature: str) -> RecoveryDecision:
        return RecoveryDecision("fail", "failed", "none", signature, False, "recovery_exhausted")
