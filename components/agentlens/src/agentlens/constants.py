"""AgentLens constants (spec §S1.6.1).

Schema identifiers, recording defaults, and enumerations referenced throughout
the v0 contract. These values are part of the public contract; changing them
is a v2 concern.
"""
from __future__ import annotations

from pathlib import Path

# --- Schema identifiers (spec §5.1) -----------------------------------------
SCHEMA_RUN_V1 = "agentlens.run.v1"
SCHEMA_EVENT_V1 = "agentlens.event.v1"
SCHEMA_FINAL_V1 = "agentlens.final.v1"
SCHEMA_EVAL_V1 = "agentlens.eval.v1"
SCHEMA_MANIFEST_V1 = "agentlens.manifest.v1"
SCHEMA_RUN_V2 = "agentlens.run.v2"
SCHEMA_EVENT_V2 = "agentlens.event.v2"
SCHEMA_FINAL_V2 = "agentlens.final.v2"
SCHEMA_EVAL_V2 = "agentlens.eval.v2"
SCHEMA_MANIFEST_V2 = "agentlens.manifest.v2"
SCHEMA_WAYGENT_PROJECTION_V1 = "agentlens.waygent_projection.v1"
SCHEMA_TRUST_REPORT_V1 = "agentlens.trust_report.v1"

# --- Recording defaults -----------------------------------------------------
MAX_EXCERPT_CHARS = 4096
MAX_SUMMARY_CHARS = 4096
DEFAULT_MODE = "minimal"

# --- Filesystem layout ------------------------------------------------------
# ``AGENTLENS_HOME`` env var, if set, overrides this at runtime. Consumers
# should call :func:`agentlens.store.paths.agentlens_home` instead of reading
# this constant directly.
AGENTLENS_HOME = Path.home() / ".agentlens"

# strftime format used in run_id timestamps.
RUN_TS_FORMAT = "%Y%m%d_%H%M%S"

# --- Enumerations -----------------------------------------------------------
EVENT_TYPES = frozenset(
    {
        "run.started",
        "checkpoint.marked",
        "command.started",
        "command.finished",
        "artifact.attached",
        "task.started",
        "task.finished",
        "failure.observed",
        "run.finalized",
        "run.cancelled",
    }
)

AGENT_OUTCOMES = frozenset(
    {"success", "failed", "partial", "cancelled", "unknown"}
)

SEAL_PHASES = frozenset({"pre_eval", "final", "recording_incomplete"})

__all__ = [
    "AGENTLENS_HOME",
    "AGENT_OUTCOMES",
    "DEFAULT_MODE",
    "EVENT_TYPES",
    "MAX_EXCERPT_CHARS",
    "MAX_SUMMARY_CHARS",
    "RUN_TS_FORMAT",
    "SCHEMA_EVAL_V1",
    "SCHEMA_EVAL_V2",
    "SCHEMA_EVENT_V1",
    "SCHEMA_EVENT_V2",
    "SCHEMA_FINAL_V1",
    "SCHEMA_FINAL_V2",
    "SCHEMA_WAYGENT_PROJECTION_V1",
    "SCHEMA_MANIFEST_V1",
    "SCHEMA_MANIFEST_V2",
    "SCHEMA_RUN_V1",
    "SCHEMA_RUN_V2",
    "SCHEMA_TRUST_REPORT_V1",
    "SEAL_PHASES",
]
