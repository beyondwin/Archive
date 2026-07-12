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
FRESH_SESSION_PROMPT = "../../templates/fresh-session-prompt.txt"


@dataclass(frozen=True)
class Treatment:
    id: str
    model: str
    reasoning: str
    prompt: str


@dataclass(frozen=True)
class QualityTreatmentV4:
    id: str
    model: str
    reasoning: str


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


def worker_prompt_bytes(source: bytes, prompt_ref: str) -> bytes:
    """Compile the worker-visible prefix while retaining the full export source."""

    if prompt_ref != FRESH_SESSION_PROMPT:
        return source
    start = b"<!-- CPE_CACHE_STABLE_PREFIX_START -->"
    end = b"<!-- CPE_CACHE_STABLE_PREFIX_END -->"
    if source.count(start) != 1 or source.count(end) != 1:
        raise LiveMigrationContractError("fresh-session prompt cache markers are invalid")
    body = source.split(start, 1)[1].split(end, 1)[0].strip()
    if not body:
        raise LiveMigrationContractError("fresh-session worker prefix is empty")
    return body + b"\n"


EXPECTED_TREATMENTS = (
    Treatment(
        "gpt55_current",
        "gpt-5.5",
        "high",
        "../control-bundles/cpe-3.1.0-production.json",
    ),
    Treatment(
        "sol_current",
        "gpt-5.6-sol",
        "high",
        "../control-bundles/cpe-3.1.0-production.json",
    ),
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
    "../control-bundles/cpe-3.1.0-production.json": "4b933268aa306baee965477117945925e0124875e50bc5aca8fb340b0cd039a0",
    "../../templates/fresh-session-prompt.txt": "76e377d2b4ce4a4f8ca360972cfe6d86d2193f540bc36d46a98aad6535efe042",
    "terra-scout-generated": "4dec7101f5fb93f9b08544c46a691632c89ff0d14d62940204ab867afa98c883",
}

EXPECTED_PROMPT_SOURCE_SHA256 = {
    **EXPECTED_PROMPT_SHA256,
    "../../templates/fresh-session-prompt.txt": "9c1175a4c1ed4a3242d00483278de735dc319204e598169635b9bc122eebddd9",
}


EXPECTED_V4_TREATMENTS = (
    QualityTreatmentV4("sol_v31_control", "gpt-5.6-sol", "high"),
    QualityTreatmentV4("sol_v4_candidate", "gpt-5.6-sol", "high"),
    QualityTreatmentV4("terra_v4", "gpt-5.6-terra", "high"),
)

V4_PROMPT_RENDERERS = {
    "sol_v31_control": "../control-bundles/cpe-3.1.0-production.json",
    "sol_v4_candidate": "../../templates/cpe-v4-worker-prefix.txt",
    "terra_v4": "terra-scout-generated",
}

V4_PROMPT_SHA256 = {
    "sol_v31_control": "4b933268aa306baee965477117945925e0124875e50bc5aca8fb340b0cd039a0",
    "sol_v4_candidate": "d931fc1020b46212ed589400fdaa12f6d04e3fe0a10da6607e260ee0f625b68b",
    "terra_v4": "4dec7101f5fb93f9b08544c46a691632c89ff0d14d62940204ab867afa98c883",
}
