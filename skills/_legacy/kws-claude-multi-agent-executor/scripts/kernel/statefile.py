import fcntl, json, os

class StateWriteError(Exception):
    pass

def read_state(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_state(path, state):
    lock_path = path + ".lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        try:
            read_state(path)
        except Exception as e:
            raise StateWriteError(f"post-write verification failed: {e}")

def active(state):
    if "plan_chain" in state:
        return state["plan_chain"][state["active_plan"]]
    return state
