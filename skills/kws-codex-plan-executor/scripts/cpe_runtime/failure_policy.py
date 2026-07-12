from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


FAILURE_CATEGORIES = frozenset(
    {
        "contract_invalid",
        "environment_unavailable",
        "provider_transient",
        "product_defect",
        "review_scope_expansion",
        "static_hardening",
        "runtime_defect",
        "external_effect_blocked",
        "evidence_integrity_failure",
    }
)

RELEASE_IMPACT_CLASSES = frozenset(
    {
        "acceptance_or_approved_product_behavior",
        "security_privacy_or_state_integrity",
        "evidence_authenticity_or_oracle_boundary",
        "billing_credential_or_external_effect_safety",
        "resume_or_no_duplicate_guarantee",
        "maintained_production_entrypoint",
    }
)


@dataclass(frozen=True)
class FailureDecision:
    category: str
    action: str
    root_cause_key: str
    repair_count: int
    release_impact: bool
    consumes_repair: bool = False
    preserve_run_id: bool = False
    preserve_attempt_id: bool = False
    repair_root_update: tuple[str, int] | None = None
    impact_class: str | None = None


def _validate_repair_count(repair_count: int) -> None:
    if type(repair_count) is not int or repair_count < 0:
        raise ValueError("invalid_repair_count")


def classify_same_root(
    repair_count: int,
    *,
    release_impact: bool,
    root_cause_key: str = "same-root",
    impact_class: str | None = None,
) -> FailureDecision:
    _validate_repair_count(repair_count)
    if not isinstance(root_cause_key, str) or not root_cause_key:
        raise ValueError("root_cause_key_required")
    if type(release_impact) is not bool:
        raise TypeError("release_impact_must_be_bool")
    if release_impact:
        impact_class = impact_class or "acceptance_or_approved_product_behavior"
        if impact_class not in RELEASE_IMPACT_CLASSES:
            raise ValueError("unapproved_release_impact_class")
    elif impact_class is not None:
        raise ValueError("release_impact_class_without_impact")

    if repair_count < 2:
        action = "repair"
        consumes_repair = True
    elif release_impact:
        action = "block_release"
        consumes_repair = False
    else:
        action = "backlog_and_continue"
        consumes_repair = False
    return FailureDecision(
        category="product_defect",
        action=action,
        root_cause_key=root_cause_key,
        repair_count=repair_count,
        release_impact=release_impact,
        consumes_repair=consumes_repair,
        repair_root_update=(root_cause_key, repair_count + 1) if consumes_repair else None,
        impact_class=impact_class,
    )


def classify_failure(
    category: str,
    *,
    root_cause_key: str,
    repair_count: int | None = None,
    release_impact: bool = False,
    impact_class: str | None = None,
    repair_roots: Mapping[str, int] | None = None,
) -> FailureDecision:
    if category not in FAILURE_CATEGORIES:
        raise ValueError("unknown_failure_category")
    if not isinstance(root_cause_key, str) or not root_cause_key:
        raise ValueError("root_cause_key_required")
    if repair_roots is not None:
        if repair_count is not None:
            raise ValueError("ambiguous_repair_count")
        if not isinstance(repair_roots, Mapping):
            raise TypeError("repair_roots_mapping_required")
        repair_count = repair_roots.get(root_cause_key, 0)
    elif repair_count is None:
        repair_count = 0
    _validate_repair_count(repair_count)
    if type(release_impact) is not bool:
        raise TypeError("release_impact_must_be_bool")

    if category == "product_defect":
        return classify_same_root(
            repair_count,
            release_impact=release_impact,
            root_cause_key=root_cause_key,
            impact_class=impact_class,
        )

    if release_impact or impact_class is not None:
        if category != "evidence_integrity_failure":
            raise ValueError("release_impact_not_applicable")

    table = {
        "contract_invalid": ("block_dispatch", False, False),
        "environment_unavailable": ("bootstrap_and_recheck", True, False),
        "provider_transient": ("wait_external", True, True),
        "review_scope_expansion": ("backlog_and_continue", False, False),
        "static_hardening": ("backlog_and_continue", False, False),
        "runtime_defect": ("pause_for_runtime_upgrade", True, False),
        "external_effect_blocked": ("wait_external", True, True),
        "evidence_integrity_failure": ("block_release", False, False),
    }
    action, preserve_run_id, preserve_attempt_id = table[category]
    return FailureDecision(
        category=category,
        action=action,
        root_cause_key=root_cause_key,
        repair_count=repair_count,
        release_impact=(category == "evidence_integrity_failure" or release_impact),
        preserve_run_id=preserve_run_id,
        preserve_attempt_id=preserve_attempt_id,
        impact_class=(
            "evidence_authenticity_or_oracle_boundary"
            if category == "evidence_integrity_failure"
            else None
        ),
    )
