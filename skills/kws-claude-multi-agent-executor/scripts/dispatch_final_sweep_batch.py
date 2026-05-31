#!/usr/bin/env python3
"""Phase 2 Step 0 LOW-task verification sweep via the Message Batches API (v2.22 §2.C1).

The final LOW-task verification sweep can run through the Anthropic **Message
Batches API** — one request per LOW task — to cut cost ~50% at the price of a
24h SLA. This helper submits the batch, polls until it ends (or a configurable
``--timeout`` elapses), and returns a summary dict. On timeout it emits a
``kws-cme.batch_timeout`` AgentLens event, WARNs, and FALLS BACK to per-task
synchronous dispatch through ``dispatch_via_api.dispatch``.

The ``anthropic`` SDK is imported LAZILY (only inside
``dispatch_final_sweep_batch`` when a live client must be constructed), so this
module imports and unit-tests cleanly with no SDK installed. Tests inject a fake
``client=`` exposing ``.messages.batches.create/retrieve/results`` to drive every
path without a live call.

CLI:
    dispatch_final_sweep_batch.py --state <path-to-json> --orch-dir <abs-path> \\
      --model <claude-...> --sk-root <abs-path> [--timeout <seconds>]

``--state`` is a JSON file holding the list of LOW task-context dicts (one
Message per task), under the ``low_tasks`` key (or a bare top-level list).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

MAX_TOKENS = 4096
VERIFIER_TOOL = "report_verifier"


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def _load_dispatch_via_api():
    """Import ``dispatch_via_api`` lazily (no eager SDK import, so this is safe).

    Tests monkeypatch this loader to inject a fake module so no real API call
    happens on the fallback path.
    """
    sys.path.insert(0, str(_scripts_dir()))
    import dispatch_via_api  # safe: no eager SDK import

    return dispatch_via_api


def _emit_agentlens(fields: dict) -> None:
    """Best-effort AgentLens event emit (``kws-cme.batch_timeout``).

    Mirrors the ``dispatch_via_api._emit_agentlens`` shim: writes/forwards the
    event and never raises. Tests monkeypatch this function to record the call.
    """
    try:
        import subprocess

        subprocess.run(
            [
                "agentlens", "event", "append",
                "--event", fields.get("event", "kws-cme.batch_timeout"),
                "--json", json.dumps(fields),
            ],
            check=False,
            capture_output=True,
        )
    except Exception:
        pass


def _task_id(task_context: dict, index: int) -> str:
    """Stable custom_id for a LOW task-context dict."""
    return str(task_context.get("task_id") or task_context.get("id") or f"low_{index}")


def _build_batch_request(task_context: dict, model: str, index: int) -> dict:
    """Build one Message Batches request for a single LOW task.

    Shape: ``{"custom_id": <task_id>, "params": {...message create kwargs...}}``.
    The verifier tool is forced so the per-task outcome is structured. The
    payload is the JSON task-context (the orchestrator owns the contract for the
    verifier prompt body); we keep this helper agnostic to the exact prompt.
    """
    return {
        "custom_id": _task_id(task_context, index),
        "params": {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "user", "content": json.dumps(task_context, ensure_ascii=False)},
            ],
        },
    }


def _result_status(row) -> str:
    """Extract the per-task verifier status from a batch result row.

    Best-effort: walks ``row.result.message.content`` for the forced
    ``report_verifier`` tool_use block's ``status``; defaults to ``"FAIL"`` for
    any errored / non-succeeded outcome.
    """
    result = getattr(row, "result", None)
    if getattr(result, "type", None) != "succeeded":
        return "FAIL"
    message = getattr(result, "message", None)
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "tool_use":
            data = getattr(block, "input", None)
            if isinstance(data, dict):
                return str(data.get("status", "FAIL"))
    return "FAIL"


def _collect_results(client, batch_id: str) -> list[dict]:
    """Gather per-task outcomes from ``client.messages.batches.results``."""
    rows = client.messages.batches.results(batch_id)
    out = []
    for row in rows:
        out.append({
            "custom_id": getattr(row, "custom_id", None),
            "status": _result_status(row),
        })
    return out


def _api_fallback(low_tasks, model, orch_dir, sk_root, client, *, reason: str) -> dict:
    """Per-task synchronous dispatch fallback (v2.22 §2.C1 timeout branch)."""
    dispatch_via_api = _load_dispatch_via_api()
    results = []
    overall = "PASS"
    for index, task_context in enumerate(low_tasks):
        task_id = _task_id(task_context, index)
        output_path = str(Path(orch_dir) / "verifier_results" / f"final_fallback_{task_id}.json")
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        result = dispatch_via_api.dispatch(
            role="verifier",
            task_context=task_context,
            model=model,
            orch_dir=orch_dir,
            sk_root=sk_root,
            output_path=output_path,
            client=client,
        )
        status = str(result.get("status", "FAIL"))
        if status != "PASS":
            overall = "FAIL"
        results.append({"custom_id": task_id, "status": status, "result": result})
    return {
        "status": overall,
        "mode": "api_fallback",
        "fallback_reason": reason,
        "results": results,
    }


def dispatch_final_sweep_batch(
    low_tasks,
    model: str,
    orch_dir,
    sk_root,
    *,
    timeout_seconds: int = 1800,
    poll_interval: int = 30,
    client=None,
    clock=time.monotonic,
    sleep=time.sleep,
) -> dict:
    """Run the Phase 2 Step 0 LOW sweep through the Message Batches API.

    Submits one batch request per LOW task, polls until the batch ends, and
    returns a summary dict ``{"status", "mode": "batch", "batch_id", "results"}``.
    If the ``timeout_seconds`` deadline elapses before the batch ends, emits a
    ``kws-cme.batch_timeout`` event, WARNs, and falls back to per-task
    synchronous dispatch (``mode == "api_fallback"``,
    ``fallback_reason == "batch_timeout"``).

    ``clock`` / ``sleep`` are injectable so tests run without real time or
    waiting; ``client`` is injectable so tests drive every path without the SDK.
    """
    low_tasks = list(low_tasks)

    if client is None:
        # Lazy import — only reached for real runs; SDK absent in unit tests.
        import anthropic  # noqa: F401

        client = anthropic.Anthropic()

    requests = [
        _build_batch_request(tc, model, i) for i, tc in enumerate(low_tasks)
    ]
    batch = client.messages.batches.create(requests=requests)
    batch_id = getattr(batch, "id", None)

    deadline = clock() + timeout_seconds
    while True:
        current = client.messages.batches.retrieve(batch_id)
        if getattr(current, "processing_status", None) == "ended":
            results = _collect_results(client, batch_id)
            overall = "PASS" if all(
                r["status"] == "PASS" for r in results) else "FAIL"
            return {
                "status": overall,
                "mode": "batch",
                "batch_id": batch_id,
                "results": results,
            }
        if clock() >= deadline:
            # TIMEOUT branch — emit, WARN, then per-task API fallback.
            _emit_agentlens({
                "event": "kws-cme.batch_timeout",
                "batch_id": batch_id,
                "model": model,
                "low_task_count": len(low_tasks),
                "timeout_seconds": timeout_seconds,
            })
            print(
                f"WARN: batch sweep {batch_id} did not end within "
                f"{timeout_seconds}s; falling back to per-task API dispatch.",
                file=sys.stderr,
            )
            return _api_fallback(
                low_tasks, model, orch_dir, sk_root, client,
                reason="batch_timeout",
            )
        sleep(poll_interval)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Phase 2 Step 0 LOW sweep via the Message Batches API (v2.22 §2.C1).")
    ap.add_argument("--state", required=True,
                    help="path to JSON holding the LOW task-context list "
                         "(under 'low_tasks', or a bare top-level list)")
    ap.add_argument("--orch-dir", required=True,
                    help="absolute orchestrator dir (holds state.json)")
    ap.add_argument("--model", required=True, help="claude model id")
    ap.add_argument("--sk-root", required=True,
                    help="absolute skill root (holds references/)")
    ap.add_argument("--timeout", type=int, default=1800,
                    help="batch poll timeout in seconds before per-task API "
                         "fallback (default 1800)")
    return ap


def _load_low_tasks(state_path) -> list:
    data = json.loads(Path(state_path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return list(data.get("low_tasks", []))


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    low_tasks = _load_low_tasks(args.state)
    summary = dispatch_final_sweep_batch(
        low_tasks,
        model=args.model,
        orch_dir=args.orch_dir,
        sk_root=args.sk_root,
        timeout_seconds=args.timeout,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary.get("status") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
