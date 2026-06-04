"""Plan Reviewer model selection — pure selection logic, no SDK calls.

The Plan Reviewer (Phase 0 Step 6.5) runs a mechanical rubric. As of v2.25 it
defaults to Opus (claude-opus-4-7): the user's "Opus-everywhere" preference for
this executor's judging roles. Overridable via
``state.dispatch_config.plan_reviewer_model``. The selected model is recorded
into ``state.plan_review.model_used`` for forensics.
"""
import sys

DEFAULT_PLAN_REVIEWER_MODEL = "claude-opus-4-7"


def select_plan_reviewer_model(state: dict) -> str:
    """Return the model for the Plan Reviewer.

    Honors ``state["dispatch_config"]["plan_reviewer_model"]`` when set;
    otherwise falls back to ``DEFAULT_PLAN_REVIEWER_MODEL``.
    """
    override = state.get("dispatch_config", {}).get("plan_reviewer_model")
    return override or DEFAULT_PLAN_REVIEWER_MODEL


def record_model_used(state: dict) -> str:
    """Select the model and record it into ``state.plan_review.model_used``.

    Returns the selected model. Preserves any existing ``plan_review`` fields.
    """
    selected = select_plan_reviewer_model(state)
    state.setdefault("plan_review", {})["model_used"] = selected
    return selected


if __name__ == "__main__":
    print(select_plan_reviewer_model({}))
    sys.exit(0)
