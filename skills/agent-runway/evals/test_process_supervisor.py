from __future__ import annotations

import os
import sys
from pathlib import Path

from agentrunway.adapters.process import ProcessLaunchSpec, ProcessSupervisor


def test_process_supervisor_collects_exit_and_logs(tmp_path: Path) -> None:
    script = tmp_path / "worker.py"
    output = tmp_path / "result.json"
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "print('hello stdout')\n"
        "print('hello stderr', file=sys.stderr)\n"
        f"Path({str(output)!r}).write_text('{{\"ok\": true}}', encoding='utf-8')\n",
        encoding="utf-8",
    )
    spec = ProcessLaunchSpec(
        worker_id="worker-1",
        command=[sys.executable, str(script)],
        cwd=tmp_path,
        stdout_path=stdout,
        stderr_path=stderr,
        timeout_seconds=10,
        env={},
    )

    supervisor = ProcessSupervisor()
    handle = supervisor.start(spec)
    snapshot = supervisor.wait(handle)

    assert snapshot.state == "exited"
    assert snapshot.returncode == 0
    assert stdout.read_text(encoding="utf-8").strip() == "hello stdout"
    assert stderr.read_text(encoding="utf-8").strip() == "hello stderr"
    assert output.exists()


def test_process_supervisor_reports_timeout(tmp_path: Path) -> None:
    script = tmp_path / "sleep.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    spec = ProcessLaunchSpec(
        worker_id="worker-timeout",
        command=[sys.executable, str(script)],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        timeout_seconds=0,
        env={},
    )

    supervisor = ProcessSupervisor()
    handle = supervisor.start(spec)
    snapshot = supervisor.wait(handle)

    assert snapshot.state == "timed_out"
    assert snapshot.reason == "timeout"


def test_process_supervisor_merges_environment(tmp_path: Path) -> None:
    script = tmp_path / "env.py"
    out = tmp_path / "env.txt"
    script.write_text(
        "import os\n"
        "from pathlib import Path\n"
        f"Path({str(out)!r}).write_text(os.environ['AGENTRUNWAY_TEST_VALUE'], encoding='utf-8')\n",
        encoding="utf-8",
    )
    spec = ProcessLaunchSpec(
        worker_id="worker-env",
        command=[sys.executable, str(script)],
        cwd=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        timeout_seconds=10,
        env={"AGENTRUNWAY_TEST_VALUE": "present"},
    )

    supervisor = ProcessSupervisor()
    snapshot = supervisor.wait(supervisor.start(spec))
    assert snapshot.state == "exited"
    assert out.read_text(encoding="utf-8") == "present"
    assert os.environ.get("AGENTRUNWAY_TEST_VALUE") is None
