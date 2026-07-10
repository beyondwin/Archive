from __future__ import annotations
from .worker import Worker, WorkerRequest
from pathlib import Path

def run_scouts(requests, worker: Worker):
    return [worker.run(request) for request in requests]

def run_tasks(tasks: list[dict], worker: Worker, run_dir: Path) -> dict:
    completed = []
    for task in tasks:
        request = WorkerRequest(str(task["id"]), "implementation", str(task.get("prompt", task["id"])), run_dir, False, True)
        result = worker.run(request)
        if result.status != "completed": return {"completed": completed, "blocked": task["id"]}
        completed.append(task["id"])
    return {"completed": completed}
