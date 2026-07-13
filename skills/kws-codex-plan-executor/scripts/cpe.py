#!/usr/bin/env python3
"""Run, resume, inspect, or export the durable CPE schema-4 queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from cpe_runtime.contracts import InputDocument, canonical_json
from cpe_runtime.launcher import ChildInterruption, ChildLauncher
from cpe_runtime.legacy import inspect_legacy_run
from cpe_runtime.prompt_export import render_export
from cpe_runtime.queue import QueueEngine, RunInterrupted
from cpe_runtime.store import RunStore
from cpe_runtime.worktree import Worktree


PUBLIC_FIELDS = (
    "status",
    "run_id",
    "state_path",
    "summary",
    "next_action",
    "failure_code",
    "authority_items",
    "terminal_artifact",
)
EXIT_CODES = {"completed": 0, "failed": 1, "waiting_authority": 2, "interrupted": 3}


class _StoreOnce(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        seen = set(getattr(namespace, "_cpe_seen_singular", ()))
        if self.dest in seen:
            parser.error(f"{option_string} may appear only once")
        seen.add(self.dest)
        setattr(namespace, "_cpe_seen_singular", seen)
        setattr(namespace, self.dest, self.const if self.nargs == 0 else values)


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def _result(
    *,
    status: str,
    run_id: str | None,
    state_path: str | None,
    summary: str,
    next_action: str,
    failure_code: str | None = None,
    authority_items: Sequence[str] = (),
    terminal_artifact: str | None = None,
) -> dict[str, object]:
    if status not in EXIT_CODES:
        raise ValueError("public status is invalid")
    value = {
        "status": status,
        "run_id": run_id,
        "state_path": state_path,
        "summary": summary[:2000],
        "next_action": next_action[:2000],
        "failure_code": failure_code,
        "authority_items": list(authority_items)[:100],
        "terminal_artifact": terminal_artifact,
    }
    if tuple(value) != PUBLIC_FIELDS:
        raise ValueError("public result fields are invalid")
    return value


def _emit(value: Mapping[str, object]) -> int:
    print(json.dumps(dict(value), ensure_ascii=False, sort_keys=True))
    return EXIT_CODES[str(value["status"])]


def _failure(run_id: str | None, code: str, summary: str | None = None) -> int:
    return _emit(
        _result(
            status="failed",
            run_id=run_id,
            state_path=None,
            summary=(summary or code),
            next_action="Inspect the run integrity evidence and correct the invocation.",
            failure_code=code,
        )
    )


def _runtime_failure(store: RunStore, exc: BaseException) -> int:
    message = str(exc) or type(exc).__name__
    if message in {
        "authority_answer_invalid",
        "authority_id_not_open",
        "authority_packet_invalid",
        "input_refresh_has_no_changes",
    }:
        return _failure(store.run_id, message)
    try:
        state = store.replay()
        if isinstance(exc, (ChildInterruption, RunInterrupted)):
            return _emit(_public_from_state(store, state))
        events = store.validate_event_chain()
        if not (events and events[-1]["event_type"] == "run.failed"):
            store.append_event(
                "run.failed",
                {"status": "failed", "failure_code": "state_integrity_failure"},
            )
        return _emit(
            _result(
                status="failed",
                run_id=store.run_id,
                state_path=str(store.paths.manifest),
                summary=message,
                next_action="Inspect the immutable run evidence before resuming.",
                failure_code="state_integrity_failure",
            )
        )
    except (OSError, RuntimeError, ValueError):
        return _failure(store.run_id, "state_integrity_failure", message)


def _interrupted(store: RunStore | None, run_id: str | None = None) -> int:
    """Record a resumable process interruption when durable state is available."""

    state_path: str | None = None
    if store is not None:
        run_id = store.run_id
        state_path = str(store.paths.manifest)
        try:
            events = store.validate_event_chain()
            if not (events and events[-1]["event_type"] == "run.interrupted"):
                store.append_event(
                    "run.interrupted",
                    {"status": "interrupted", "failure_code": "keyboard_interrupt"},
                )
        except (OSError, RuntimeError, ValueError):
            pass
    return _emit(
        _result(
            status="interrupted",
            run_id=run_id,
            state_path=state_path,
            summary="CPE execution was interrupted after preserving durable state.",
            next_action="Resume the durable run.",
            failure_code="keyboard_interrupt",
        )
    )


def _manifest_workspace(store: RunStore) -> Path:
    manifest = store._load_manifest()
    workspace = manifest.get("workspace")
    if not isinstance(workspace, str):
        raise ValueError("run manifest workspace is invalid")
    return Path(workspace)


def _open_worktree(store: RunStore) -> Worktree:
    source = _manifest_workspace(store)
    root = store.codex_home / "worktrees" / store.run_id
    merge_base = subprocess.run(
        ["git", "-C", str(source), "merge-base", "HEAD", f"codex/{store.run_id}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if merge_base.returncode != 0 or len(merge_base.stdout.strip()) != 40:
        raise ValueError("worktree_base_commit_invalid")
    return Worktree.open(
        source=source,
        root=root,
        branch=f"codex/{store.run_id}",
        base_commit=merge_base.stdout.strip(),
    )


def _launcher() -> ChildLauncher:
    return ChildLauncher(
        schema_path=Path(__file__).resolve().parents[1]
        / "templates"
        / "child-result-schema.json"
    )


def _terminal_artifact(store: RunStore) -> str | None:
    for event in reversed(store.validate_event_chain()):
        if event["event_type"] != "run.completed":
            continue
        terminal_paths = [
            str(path)
            for path in event["payload"].get("artifact_paths", [])
            if str(path).endswith("/terminal.json")
        ]
        if len(terminal_paths) == 1:
            return str(store.paths.root / terminal_paths[0])
    if not store.paths.result.is_file():
        return None
    return str(store.paths.result)


def _public_from_state(store: RunStore, state: Mapping[str, object]) -> dict[str, object]:
    status = str(state.get("status"))
    if status not in EXIT_CODES:
        status = "failed"
    authorities = state.get("authorities", {})
    open_ids = sorted(
        str(authority_id)
        for authority_id, item in (authorities.items() if isinstance(authorities, dict) else ())
        if isinstance(item, Mapping) and item.get("status") == "waiting_authority"
    )
    next_action = {
        "completed": "Inspect the terminal artifact.",
        "waiting_authority": "Resolve one open authority item and resume.",
        "interrupted": "Resume the durable run.",
        "failed": "Inspect the failure code and immutable run state.",
    }[status]
    return _result(
        status=status,
        run_id=store.run_id,
        state_path=str(store.paths.manifest),
        summary=f"CPE schema-4 run is {status}.",
        next_action=next_action,
        failure_code=None if status != "failed" else "run_failed",
        authority_items=open_ids,
        terminal_artifact=_terminal_artifact(store),
    )


def inspect_schema4(store: RunStore) -> dict[str, object]:
    events = store.validate_event_chain()
    state = store.replay()
    map_events = [event for event in events if event["event_type"] == "map.generation_created"]
    latest_map = map_events[-1]["payload"] if map_events else {}
    total_tasks = 0
    active_task_ids: set[str] = set()
    manifest_path = latest_map.get("publication_manifest_path")
    manifest_sha256 = latest_map.get("publication_manifest_sha256")
    generation_id = latest_map.get("generation_id")
    if all(
        isinstance(value, str)
        for value in (manifest_path, manifest_sha256, generation_id)
    ):
        manifest_raw = store.read_artifact(str(manifest_path))
        if hashlib.sha256(manifest_raw).hexdigest() != manifest_sha256:
            raise ValueError("accepted generation manifest digest is invalid")
        manifest = json.loads(manifest_raw.decode("utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest_raw != canonical_json(manifest)
            or set(manifest)
            != {
                "schema_version",
                "generation_id",
                "publication_id",
                "program_map_sha256",
                "artifacts",
            }
            or manifest.get("schema_version") != 1
            or manifest.get("generation_id") != generation_id
            or manifest.get("program_map_sha256") != latest_map.get("map_sha256")
        ):
            raise ValueError("accepted generation manifest is invalid")
        program_path = f"maps/{generation_id}/program-map.json"
        artifacts = manifest.get("artifacts")
        record = artifacts.get(program_path) if isinstance(artifacts, dict) else None
        publication_id = manifest.get("publication_id")
        if not isinstance(record, dict) or set(record) != {
            "relative_path",
            "sha256",
            "byte_length",
        } or not isinstance(publication_id, str) or len(publication_id) != 64:
            raise ValueError("accepted generation has no bound program map")
        expected_path = (
            f"maps/{generation_id}/attempts/{publication_id}/artifacts/{program_path}"
        )
        if record["relative_path"] != expected_path:
            raise ValueError("accepted generation program map path is invalid")
        program_raw = store.read_artifact(str(record["relative_path"]))
        program_digest = hashlib.sha256(program_raw).hexdigest()
        if (
            program_digest != record["sha256"]
            or len(program_raw) != record["byte_length"]
            or program_digest != manifest["program_map_sha256"]
        ):
            raise ValueError("accepted generation program map binding is invalid")
        program = json.loads(program_raw.decode("utf-8"))
        program_tasks = program.get("tasks") if isinstance(program, dict) else None
        if not isinstance(program_tasks, list) or len(program_tasks) > 4096:
            raise ValueError("accepted generation task summary is invalid")
        total_tasks = len(program_tasks)
        active_task_ids = {
            str(task["task_id"])
            for task in program_tasks
            if isinstance(task, dict) and isinstance(task.get("task_id"), str)
        }
        if len(active_task_ids) != total_tasks:
            raise ValueError("accepted generation task IDs are invalid")
    tasks = state.get("tasks", {})
    completed = sum(
        1
        for task_id, task in (tasks.items() if isinstance(tasks, dict) else ())
        if str(task_id) in active_task_ids
        if isinstance(task, Mapping)
        and task.get("task_status") == "completed"
        and task.get("review_verdict") == "pass"
    )
    active = next(
        (
            (task_id, task["active_attempt"])
            for task_id, task in (tasks.items() if isinstance(tasks, dict) else ())
            if str(task_id) in active_task_ids
            if isinstance(task, Mapping) and isinstance(task.get("active_attempt"), Mapping)
        ),
        None,
    )
    worktree = _open_worktree(store)
    authorities = state.get("authorities", {})
    return {
        "schema_version": 4,
        "run_id": store.run_id,
        "status": state["status"],
        "generation": latest_map.get("generation_id"),
        "current_item": active[0] if active else None,
        "current_role": active[1].get("role") if active else None,
        "completed_tasks": completed,
        "total_tasks": total_tasks,
        "open_authority_ids": sorted(
            str(key)
            for key, item in (authorities.items() if isinstance(authorities, dict) else ())
            if isinstance(item, Mapping) and item.get("status") == "waiting_authority"
        )[:100],
        "worktree_head": worktree.head(),
        "last_event_type": events[-1]["event_type"] if events else None,
        "terminal_artifact": _terminal_artifact(store),
    }


def _authority_item(store: RunStore, authority_id: str) -> dict[str, object]:
    state = store.replay()
    authorities = state.get("authorities", {})
    authority = authorities.get(authority_id) if isinstance(authorities, dict) else None
    if not isinstance(authority, Mapping) or authority.get("status") != "waiting_authority":
        raise ValueError("authority_id_not_open")
    matches: list[dict[str, object]] = []
    for path in authority.get("artifact_paths", []):
        try:
            payload = json.loads(store.read_artifact(str(path)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            values = payload.get("authority_items", [payload])
            if isinstance(values, list):
                matches.extend(
                    {**dict(item), "authority_id": authority_id}
                    for item in values
                    if isinstance(item, Mapping)
                    and item.get("authority_id") == authority_id
                )
    if len(matches) != 1:
        raise ValueError("authority_packet_invalid")
    return matches[0]


def resolve_authority(store: RunStore, authority_id: str, answer: str) -> None:
    item = _authority_item(store, authority_id)
    options = item.get("options")
    if not isinstance(options, list) or answer not in options:
        raise ValueError("authority_answer_invalid")
    path = f"reports/authority/{authority_id}-resolution.json"
    data = canonical_json(
        {"schema_version": 1, "authority_id": authority_id, "answer": answer}
    )
    store.put_artifact(path, data)
    store.append_event(
        "authority.resolved",
        {
            "authority_id": authority_id,
            "status": "resolved",
            "resolution_sha256": hashlib.sha256(data).hexdigest(),
            "artifact_paths": [path],
        },
    )


def _run_engine(
    store: RunStore,
    *,
    generation_id: str | None = None,
    documents: Sequence[InputDocument] | None = None,
) -> dict[str, object]:
    worktree = _open_worktree(store)
    head = worktree.head()
    for event in store.validate_event_chain():
        if event["event_type"] not in {
            "task.reported",
            "review.reported",
            "audit.reported",
            "integration.reported",
            "run.completed",
        }:
            continue
        commit = event["payload"].get("commit")
        if not isinstance(commit, str):
            continue
        ancestor = subprocess.run(
            ["git", "-C", str(worktree.root), "merge-base", "--is-ancestor", commit, head],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ancestor.returncode != 0:
            raise ValueError("recorded_commit_not_in_worktree_head")
    engine = QueueEngine(
        store,
        worktree,
        _launcher(),
        generation_id=generation_id,
        documents=documents,
    )
    return engine.run_until_terminal()


def command_run(args: argparse.Namespace) -> int:
    home = _codex_home()
    store = RunStore.create(
        codex_home=home,
        workspace=Path(args.workspace),
        specs=[Path(path) for path in args.spec],
        plans=[Path(path) for path in args.plan],
        program_plan=Path(args.program_plan) if args.program_plan else None,
    )
    try:
        (home / "worktrees").mkdir(mode=0o700, parents=True, exist_ok=True)
        Worktree.create(
            source=Path(args.workspace),
            root=home / "worktrees" / store.run_id,
            run_id=store.run_id,
        )
        return _emit(_public_from_state(store, _run_engine(store)))
    except KeyboardInterrupt:
        return _interrupted(store)
    except (OSError, RuntimeError, ValueError) as exc:
        return _runtime_failure(store, exc)


def command_resume(args: argparse.Namespace) -> int:
    home = _codex_home()
    root = home / "orchestrator" / args.run_id
    if not root.is_dir():
        return _failure(args.run_id, "run_not_found")
    if not (root / "run.json").is_file():
        if (root / "run_manifest.json").is_file():
            return _failure(args.run_id, "legacy_run_requires_historical_cpe")
        return _failure(args.run_id, "run_manifest_missing")
    store = RunStore.open(codex_home=home, run_id=args.run_id)
    try:
        if args.authority_id is not None:
            resolve_authority(store, args.authority_id, args.authority_answer)
        if args.refresh_inputs:
            generation_id, documents, _ = store.refresh_inputs()
            state = _run_engine(
                store, generation_id=generation_id, documents=documents
            )
        else:
            state = _run_engine(store)
        return _emit(_public_from_state(store, state))
    except KeyboardInterrupt:
        return _interrupted(store)
    except (OSError, RuntimeError, ValueError) as exc:
        return _runtime_failure(store, exc)


def command_inspect(args: argparse.Namespace) -> int:
    home = _codex_home()
    root = home / "orchestrator" / args.run_id
    if (root / "run.json").is_file():
        store = RunStore.open(codex_home=home, run_id=args.run_id, read_only=True)
        print(json.dumps(inspect_schema4(store), sort_keys=True))
        return 0
    if (root / "run_manifest.json").is_file():
        print(json.dumps(inspect_legacy_run(codex_home=home, run_id=args.run_id), sort_keys=True))
        return 0
    return _failure(args.run_id, "run_not_found")


def command_export(args: argparse.Namespace) -> int:
    print(
        render_export(
            workspace=Path(args.workspace),
            specs=[Path(path) for path in args.spec],
            plans=[Path(path) for path in args.plan],
            program_plan=Path(args.program_plan) if args.program_plan else None,
            mode=args.mode,
        ),
        end="",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--spec", action="append", default=[])
    run.add_argument("--plan", action="append", required=True)
    run.add_argument("--program-plan", action=_StoreOnce)
    run.add_argument("--workspace", action=_StoreOnce, required=True)
    resume = sub.add_parser("resume")
    resume.add_argument("--run-id", action=_StoreOnce, required=True)
    resume.add_argument("--authority-id", action=_StoreOnce)
    resume.add_argument("--authority-answer", action=_StoreOnce)
    resume.add_argument(
        "--refresh-inputs", action=_StoreOnce, nargs=0, const=True, default=False
    )
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--run-id", action=_StoreOnce, required=True)
    export = sub.add_parser("export")
    export.add_argument("--spec", action="append", default=[])
    export.add_argument("--plan", action="append", required=True)
    export.add_argument("--program-plan", action=_StoreOnce)
    export.add_argument("--workspace", action=_StoreOnce, required=True)
    export.add_argument(
        "--mode", action=_StoreOnce, choices=("prompt", "handoff"), default="prompt"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "resume":
        paired = (args.authority_id is None) == (args.authority_answer is None)
        if not paired or (args.refresh_inputs and args.authority_id is not None):
            parser.error("authority ID/answer must appear together and cannot combine with refresh")
    try:
        return {
            "run": command_run,
            "resume": command_resume,
            "inspect": command_inspect,
            "export": command_export,
        }[args.command](args)
    except KeyboardInterrupt:
        return _interrupted(None, getattr(args, "run_id", None))
    except (OSError, RuntimeError, ValueError) as exc:
        message = str(exc) or type(exc).__name__
        stable = message if message in {
            "authority_answer_invalid",
            "authority_id_not_open",
            "authority_packet_invalid",
            "legacy_run_requires_historical_cpe",
            "input_refresh_has_no_changes",
        } else "state_integrity_failure"
        return _failure(getattr(args, "run_id", None), stable, message)


if __name__ == "__main__":
    raise SystemExit(main())
