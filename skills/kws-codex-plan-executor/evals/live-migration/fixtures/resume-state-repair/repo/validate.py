import json

state = json.load(open("run/state.json"))
assert state["status"] == "resumable"
assert state["revision"] == 2
