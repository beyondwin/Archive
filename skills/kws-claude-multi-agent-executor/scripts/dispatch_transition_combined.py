"""Combined Phase Transition T1.2 dispatch helper — pure parse + write plumbing.

v2.22 spec §2.A2 merges the back-to-back batch Verifier (T1) and Phase Docs
Updater (T2) into a single dispatch that issues both tools — ``verify_low_batch``
and ``update_phase_docs`` — in one sub-agent turn. This helper splits that
two-tool output into the combined ``{verify, docs}`` shape and persists it to
``<orch_dir>/transition_results/<plan_idx>_<compaction_idx>.json``.

No SDK calls: the orchestrator drives the live dispatch; this module only parses
the returned tool output and writes the result file.
"""
import json
import os
import sys

VERIFY_TOOL = "verify_low_batch"
DOCS_TOOL = "update_phase_docs"


def parse_combined_result(subagent_output: dict) -> dict:
    """Split a two-tool sub-agent output into ``{verify, docs}``.

    ``subagent_output`` is the parsed turn containing a ``tool_calls`` list, one
    entry per tool the sub-agent invoked. Each entry has ``name`` and ``result``.
    Both ``verify_low_batch`` and ``update_phase_docs`` must be present.

    Raises ``ValueError`` when either tool result is missing.
    """
    by_name = {
        call.get("name"): call.get("result")
        for call in subagent_output.get("tool_calls", [])
    }
    missing = [name for name in (VERIFY_TOOL, DOCS_TOOL) if name not in by_name]
    if missing:
        raise ValueError(
            "combined transition output missing tool result(s): " + ", ".join(missing)
        )
    return {"verify": by_name[VERIFY_TOOL], "docs": by_name[DOCS_TOOL]}


def dispatch_combined_via_api(
    task_context: dict,
    model: str,
    orch_dir: str,
    sk_root,
    plan_idx,
    compaction_idx,
    client=None,
):
    """Drive the combined transition through the Anthropic Messages API (v2.22).

    Thin delegation to ``dispatch_via_api.dispatch`` with
    ``role="transition_combined"``: the two-tool turn is built and extracted
    there, and the combined ``{verify, docs}`` dict is written to
    ``transition_result_path(orch_dir, plan_idx, compaction_idx)``. Returns the
    combined result dict (or an ENV_BLOCKER ESCALATE dict on persistent failure).

    ``dispatch_via_api`` has no eager ``anthropic`` import, so a normal import is
    safe even when the SDK is absent (unit tests inject ``client=``).
    """
    import dispatch_via_api  # safe: no eager SDK import

    output_path = transition_result_path(orch_dir, plan_idx, compaction_idx)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    return dispatch_via_api.dispatch(
        role="transition_combined",
        task_context=task_context,
        model=model,
        orch_dir=orch_dir,
        sk_root=sk_root,
        output_path=output_path,
        client=client,
    )


def transition_result_path(orch_dir: str, plan_idx, compaction_idx) -> str:
    """Return the combined-result path for the given plan/compaction indices."""
    return os.path.join(
        orch_dir, "transition_results", "{}_{}.json".format(plan_idx, compaction_idx)
    )


def write_transition_result(orch_dir: str, plan_idx, compaction_idx, result: dict) -> str:
    """Write the combined ``{verify, docs}`` result and return its path.

    Creates ``<orch_dir>/transition_results/`` when absent.
    """
    path = transition_result_path(orch_dir, plan_idx, compaction_idx)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


if __name__ == "__main__":
    raw = json.load(sys.stdin)
    print(json.dumps(parse_combined_result(raw), indent=2, sort_keys=True))
    sys.exit(0)
