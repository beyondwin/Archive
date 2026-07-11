import json
from pathlib import Path


def repair() -> None:
    path = Path("run/state.json")
    state = json.loads(path.read_text())
    checkpoint = json.loads(Path("run").joinpath(state["checkpoint"]).read_text())
    if checkpoint["status"] == "verified" and checkpoint["task_id"] == state["active_task"]:
        state.update(status="resumable", revision=checkpoint["revision"])
        path.write_text(json.dumps(state, sort_keys=True) + "\n")


if __name__ == "__main__":
    repair()
