import os
import signal
import subprocess
import sys
import time

from bencheval.runtime import run_process


def test_both_large_streams_drained_without_deadlock(tmp_path):
    script = "import sys; sys.stdout.write('x'*200000); sys.stderr.write('y'*200000)"
    result = run_process(
        [sys.executable, "-c", script], cwd=tmp_path, env=os.environ.copy(), timeout=5
    )
    assert result.exit_code == 0
    assert len(result.stdout) == len(result.stderr) == 200000


def test_timeout_terminates_child_group(tmp_path):
    marker = tmp_path / "survived"
    child = (
        "import time; from pathlib import Path; time.sleep(0.8); "
        f"Path({str(marker)!r}).touch()"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "print('child started',flush=True); time.sleep(30)"
    )
    result = run_process(
        [sys.executable, "-c", parent], cwd=tmp_path, env=os.environ.copy(), timeout=0.2
    )
    assert result.timed_out
    assert "child started" in result.stdout
    time.sleep(1)
    assert not marker.exists()


def test_interrupt_terminates_process_and_retains_output(tmp_path, monkeypatch):
    original = subprocess.Popen.communicate
    calls = 0

    def interrupt_once(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            time.sleep(0.1)
            raise KeyboardInterrupt
        return original(self, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupt_once)
    result = run_process(
        [
            sys.executable,
            "-c",
            "import time; print('started',flush=True); time.sleep(30)",
        ],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout=5,
    )
    assert result.cancelled
    assert not result.timed_out
    assert result.exit_code in (-signal.SIGTERM, -signal.SIGKILL)
    assert "started" in result.stdout
