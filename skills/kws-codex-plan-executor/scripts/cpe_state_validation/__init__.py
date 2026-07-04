from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .completion import validate_completion
from .context import validate_context
from .delegation import validate_delegation
from .graphify import validate_graphify
from .plan_audit import validate_plan_audit
from .prompt_cache import validate_prompt_cache
from .recovery import validate_recovery
from .run_quality import validate_run_quality
from .tasks import validate_tasks


LegacyValidator = Callable[[dict[str, Any]], list[str]]


def validate(data: dict[str, Any], legacy_validate: LegacyValidator | None = None) -> list[str]:
    errors = legacy_validate(data) if legacy_validate is not None else []
    validate_completion(data, errors)
    validate_context(data, errors)
    validate_graphify(data, errors)
    validate_plan_audit(data, errors)
    validate_prompt_cache(data, errors)
    validate_delegation(data, errors)
    validate_run_quality(data, errors)
    validate_tasks(data, errors)
    validate_recovery(data, errors)
    return errors
