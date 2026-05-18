"""AgentLens v1 schema package.

Re-exports the validation API defined in :mod:`agentlens.schema.validate`.
See spec §S1.5 and §S1.6.11.
"""
from __future__ import annotations

from agentlens.schema.validate import (
    EventLineError,
    SchemaError,
    SchemaName,
    load_schema,
    validate_doc,
    validate_event_line,
)

__all__ = [
    "EventLineError",
    "SchemaError",
    "SchemaName",
    "load_schema",
    "validate_doc",
    "validate_event_line",
]
