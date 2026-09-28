"""Read-only skill discovery and per-invocation overrides; no config/auth writes."""

import json
import queue
import subprocess
import threading
import time
from pathlib import Path

from bencheval.runtime import stop_group


def config_arguments(overrides: dict) -> list[str]:
    return [
        part
        for key, value in overrides.items()
        for part in ("-c", f"{key}={json.dumps(value)}")
    ]


def skills_override(paths: list[str]) -> str:
    tables = ["{path=" + json.dumps(path) + ",enabled=false}" for path in paths]
    return "skills.config=[" + ",".join(tables) + "]"


def list_skills(
    binary: str,
    cwd: Path,
    env: dict,
    overrides: dict,
    disabled: list[str] | None = None,
    timeout: float = 15,
) -> list[dict]:
    cwd = cwd.resolve()
    argv = [binary, "app-server", *config_arguments(overrides)]
    if disabled is not None:
        argv.extend(["-c", skills_override(disabled)])
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        start_new_session=True,
    )
    incoming = queue.Queue(maxsize=256)
    deadline = time.monotonic() + timeout

    def read():
        try:
            for line in process.stdout:
                # No model turn is started. Refuse unexpected oversized RPC data.
                if len(line.encode()) > 2_000_000:
                    incoming.put(None, timeout=1)
                    return
                incoming.put(line, timeout=1)
        except (ValueError, UnicodeError, queue.Full):
            pass
        finally:
            try:
                incoming.put(None, timeout=1)
            except queue.Full:
                pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()

    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def receive(identifier):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OSError("Codex skill discovery timed out")
            try:
                line = incoming.get(timeout=remaining)
            except queue.Empty as error:
                raise OSError("Codex skill discovery timed out") from error
            if line is None:
                raise OSError("Codex skill discovery ended without a response")
            try:
                message = json.loads(line)
            except ValueError as error:
                raise OSError("Invalid Codex skill discovery response") from error
            if not isinstance(message, dict):
                raise OSError("Invalid Codex skill discovery response")
            if message.get("id") == identifier:
                if "error" in message or not isinstance(message.get("result"), dict):
                    raise OSError("Codex skill discovery is unavailable")
                return message["result"]

    try:
        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "bencheval", "version": "0.1.0"}},
            }
        )
        receive(1)
        send({"method": "initialized", "params": {}})
        send(
            {
                "id": 2,
                "method": "skills/list",
                "params": {"cwds": [str(cwd)], "forceReload": True},
            }
        )
        result = receive(2)
        records = result.get("data")
        if not isinstance(records, list) or len(records) != 1:
            raise OSError("Missing Codex skill discovery scope")
        record = records[0]
        if (
            not isinstance(record, dict)
            or record.get("cwd") != str(cwd)
            or record.get("errors") != []
            or not isinstance(record.get("skills"), list)
        ):
            raise OSError(
                "Incomplete Codex skill discovery; ambient context is unknown"
            )
        skills = record["skills"]
        for skill in skills:
            if (
                not isinstance(skill, dict)
                or not isinstance(skill.get("path"), str)
                or not Path(skill["path"]).is_absolute()
                or type(skill.get("enabled")) is not bool
            ):
                raise OSError("Invalid Codex skill metadata")
        return skills
    except KeyboardInterrupt as error:
        raise OSError("Codex context preflight cancelled") from error
    finally:
        stop_group(process)
        process.wait(timeout=5)
        reader.join(timeout=2)
        for stream in (process.stdin, process.stdout):
            stream.close()


def controlled_context(binary: str, cwd: Path, env: dict, overrides: dict) -> dict:
    original = list_skills(binary, cwd, env, overrides)
    # Include previously disabled paths too: exec ignores the user's config.
    paths = sorted({skill["path"] for skill in original})
    verified = list_skills(binary, cwd, env, overrides, disabled=paths)
    if any(skill["enabled"] for skill in verified):
        raise OSError("Codex still exposes ambient skills; controlled run refused")
    if not {skill["path"] for skill in verified}.issubset(paths):
        raise OSError("Codex skill catalog changed during preflight; retry")
    return {
        "mode": "controlled",
        "verified_by": "app-server skills/list",
        "discovered_skills": len(paths),
        "enabled_skills": 0,
        "disabled_paths": paths,
        "instruction_file_max_bytes": 0,
        "global_config_modified": False,
        "boundary": "preflight snapshot; native base/managed instructions remain",
    }
