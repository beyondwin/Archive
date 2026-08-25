import json, os, tempfile, threading
import statefile

def test_roundtrip():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "state.json")
    statefile.write_state(p, {"schema_version": 3, "tasks": {}})
    assert statefile.read_state(p)["schema_version"] == 3

def test_atomic_no_partial():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "state.json")
    statefile.write_state(p, {"schema_version": 3, "big": "x" * 100000})
    # 동시 쓰기 경쟁에서도 항상 파싱 가능한 전체 문서만 관측되어야 한다
    def writer(i):
        statefile.write_state(p, {"schema_version": 3, "n": i, "big": "y" * 100000})
    ts = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    obj = statefile.read_state(p)
    assert obj["schema_version"] == 3 and "n" in obj

def test_active_resolution():
    single = {"schema_version": 3, "tasks": {"task_1": {}}}
    assert statefile.active(single) is single
    multi = {"schema_version": 3, "active_plan": 1,
             "plan_chain": [{"tasks": {}}, {"tasks": {"task_9": {}}}]}
    assert "task_9" in statefile.active(multi)["tasks"]

if __name__ == "__main__":
    test_roundtrip(); test_atomic_no_partial(); test_active_resolution()
    print("OK")
