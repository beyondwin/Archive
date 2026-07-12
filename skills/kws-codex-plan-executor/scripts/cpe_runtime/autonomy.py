from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterable


DECISION_BASIS_ORDER = (
    "approved_documents",
    "security_integrity_privacy",
    "acceptance_and_user_outcome",
    "smallest_reversible_change",
    "repository_pattern",
    "execution_economy",
)
_DECISION_BASIS_RANK = {basis: rank for rank, basis in enumerate(DECISION_BASIS_ORDER)}
_CONFIDENCE_VALUES = frozenset({"low", "medium", "high"})


@dataclass(frozen=True)
class Action:
    reversible: bool = True
    external: bool = False
    purchase_or_billing_change: bool = False
    credentials_or_new_authority: bool = False
    irreversible_external_action: bool = False
    remote_push: bool = False
    protected_branch_merge: bool = False
    material_product_contract_conflict: bool = False
    lowers_approved_security_or_privacy: bool = False

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if type(value) is not bool:
                raise TypeError(f"{name}_must_be_bool")


@dataclass(frozen=True)
class DecisionOption:
    action: str
    basis: str
    confidence: str = "medium"
    reversible: bool = True
    affected_tasks: tuple[str, ...] = ()
    authority: Action = field(default_factory=Action)


@dataclass(frozen=True)
class AutonomyDecision:
    decision_id: str
    selected: str
    alternatives: tuple[str, ...]
    basis: str
    confidence: str
    reversible: bool
    affected_tasks: tuple[str, ...]
    approval_basis: str = "standing_autonomy_policy"
    user_input_required: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.selected, str)
            or not self.selected
            or not isinstance(self.alternatives, tuple)
            or self.alternatives != tuple(sorted(set(self.alternatives)))
            or self.selected in self.alternatives
        ):
            raise ValueError("invalid_decision_actions")
        if self.basis not in _DECISION_BASIS_RANK:
            raise ValueError("invalid_decision_basis")
        if self.confidence not in _CONFIDENCE_VALUES:
            raise ValueError("invalid_decision_confidence")
        if type(self.reversible) is not bool or type(self.user_input_required) is not bool:
            raise TypeError("invalid_decision_boolean")
        if (
            not isinstance(self.affected_tasks, tuple)
            or self.affected_tasks != tuple(sorted(set(self.affected_tasks)))
            or any(not isinstance(task_id, str) or not task_id for task_id in self.affected_tasks)
        ):
            raise ValueError("invalid_affected_tasks")
        if self.approval_basis != "standing_autonomy_policy":
            raise ValueError("invalid_autonomy_approval_basis")
        body: dict[str, object] = {
            "selected": self.selected,
            "alternatives": self.alternatives,
            "basis": self.basis,
            "confidence": self.confidence,
            "reversible": self.reversible,
            "affected_tasks": self.affected_tasks,
            "approval_basis": self.approval_basis,
            "user_input_required": self.user_input_required,
        }
        if self.decision_id != _decision_id(body):
            raise ValueError("invalid_decision_id")


def needs_user_input(action: Action) -> bool:
    if not isinstance(action, Action):
        raise TypeError("action_required")
    return any(
        (
            action.purchase_or_billing_change,
            action.credentials_or_new_authority,
            action.irreversible_external_action,
            action.remote_push,
            action.protected_branch_merge,
            action.material_product_contract_conflict,
            action.lowers_approved_security_or_privacy,
            action.external and not action.reversible,
        )
    )


def _normalized_option(option: DecisionOption) -> DecisionOption:
    if not isinstance(option, DecisionOption):
        raise TypeError("decision_option_required")
    if not isinstance(option.action, str) or not option.action.strip():
        raise ValueError("decision_action_required")
    if option.basis not in _DECISION_BASIS_RANK:
        raise ValueError("invalid_decision_basis")
    if option.confidence not in _CONFIDENCE_VALUES:
        raise ValueError("invalid_decision_confidence")
    if type(option.reversible) is not bool:
        raise TypeError("decision_reversible_must_be_bool")
    if not isinstance(option.affected_tasks, tuple) or any(
        not isinstance(task_id, str) or not task_id for task_id in option.affected_tasks
    ):
        raise ValueError("invalid_affected_tasks")
    return DecisionOption(
        action=option.action.strip(),
        basis=option.basis,
        confidence=option.confidence,
        reversible=option.reversible,
        affected_tasks=tuple(sorted(set(option.affected_tasks))),
        authority=option.authority,
    )


def _decision_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"cpe.autonomy-decision.v4\0" + encoded).hexdigest()


def decide(options: Iterable[DecisionOption]) -> AutonomyDecision:
    normalized = tuple(_normalized_option(option) for option in options)
    if not normalized:
        raise ValueError("decision_options_required")
    if len({option.action for option in normalized}) != len(normalized):
        raise ValueError("duplicate_decision_action")

    ranked = tuple(
        sorted(
            normalized,
            key=lambda option: (_DECISION_BASIS_RANK[option.basis], option.action),
        )
    )
    selected = ranked[0]
    alternatives = tuple(sorted(option.action for option in ranked[1:]))
    user_input_required = needs_user_input(selected.authority)
    body: dict[str, object] = {
        "selected": selected.action,
        "alternatives": alternatives,
        "basis": selected.basis,
        "confidence": selected.confidence,
        "reversible": selected.reversible,
        "affected_tasks": selected.affected_tasks,
        "approval_basis": "standing_autonomy_policy",
        "user_input_required": user_input_required,
    }
    return AutonomyDecision(decision_id=_decision_id(body), **body)
