"""Canonical, cost-free contracts for the subscription live matrix."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


CHATGPT_SUBSCRIPTION = "chatgpt_subscription"
METERED_DOLLAR_MODE = "metered_dollar"
MAX_METERED_BUDGET_USD = 50.0

CREDENTIALLED_CALL = "credentialed_call"
EXPECTED_POLICY_FAILURE = "expected_policy_failure"


@dataclass(frozen=True)
class Treatment:
    id: str
    model: str
    reasoning: str
    prompt: str


@dataclass(frozen=True)
class CaseRef:
    id: str
    slug: str


@dataclass(frozen=True, order=True)
class SlotKey:
    treatment_id: str
    case_id: str


class LiveMigrationContractError(ValueError):
    """Raised when checked-in live-matrix inputs violate the fixed contract."""


# Compatibility for the initial T1 implementation name. New consumers use the
# approved LiveMigrationContractError contract above.
MatrixContractError = LiveMigrationContractError


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


EXPECTED_TREATMENTS = (
    Treatment("gpt55_current", "gpt-5.5", "high", "current-v2-prompt.txt"),
    Treatment("sol_current", "gpt-5.6-sol", "high", "current-v2-prompt.txt"),
    Treatment("sol_v3", "gpt-5.6-sol", "high", "../../templates/fresh-session-prompt.txt"),
    Treatment("terra_scout", "gpt-5.6-terra", "high", "terra-scout-generated"),
)

EXPECTED_CASES = (
    CaseRef("single-file implementation", "single-file-implementation"),
    CaseRef("cross-package implementation", "cross-package-implementation"),
    CaseRef("root-cause repair", "root-cause-repair"),
    CaseRef("defect review", "defect-review"),
    CaseRef("failed-test interpretation", "failed-test-interpretation"),
    CaseRef("security/migration block", "security-migration-block"),
    CaseRef("resume/state repair", "resume-state-repair"),
    CaseRef("large read-only exploration", "large-read-only-exploration"),
)

EXPECTED_PROMPT_SHA256 = {
    "current-v2-prompt.txt": "48586761ca6bc42b249672332d0f07c4ad33d5aa980e6caaf8aa77744e896f2d",
    "../../templates/fresh-session-prompt.txt": "bb78e41238f8657dc45f173906b5a7e1475e6415e578d99244e86df41407170f",
    "terra-scout-generated": "4dec7101f5fb93f9b08544c46a691632c89ff0d14d62940204ab867afa98c883",
}
