"""POSIX process lifecycle: drain both streams and terminate the whole group."""

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcessResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float
    timed_out: bool = False
    cancelled: bool = False


def stop_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    # Wait for the leader, then still kill its group: children can outlive it.
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_process(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float, stdin: str = ""
) -> ProcessResult:
    if os.name != "posix":
        raise OSError("The first BenchEval runtime supports macOS and Linux only")
    start = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    timed_out = cancelled = False
    try:
        stdout, stderr = process.communicate(stdin, timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        timed_out = isinstance(error, subprocess.TimeoutExpired)
        cancelled = not timed_out
        stop_group(process)
        stdout, stderr = process.communicate(timeout=5)
    return ProcessResult(
        stdout,
        stderr,
        process.returncode,
        time.monotonic() - start,
        timed_out,
        cancelled,
    )
