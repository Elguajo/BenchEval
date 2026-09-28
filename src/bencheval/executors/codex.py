"""Adapted from the local CodexCLIModel addition in the DeepEval checkout.

Changes: independent contracts, subscription preflight, captured evidence,
controlled configuration, process-group cancellation and unknown cost accounting.
Provenance: docs/provenance.md.
Upstream license: licenses/deepeval-apache-2.0.txt.
"""

import fcntl
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from bencheval.contracts import Execution, ExecutionStatus, Scenario
from bencheval.events import parse_trace
from bencheval.runtime import run_process

REQUIRED_FLAGS = (
    "--ignore-user-config",
    "--ignore-rules",
    "--ephemeral",
    "--json",
    "--output-schema",
    "--output-last-message",
)
OVERRIDES = {
    "forced_login_method": "chatgpt",
    "project_doc_max_bytes": 0,
    "web_search": "disabled",
    "features.shell_tool": False,
    "features.unified_exec": False,
    "features.apps": False,
    "features.plugins": False,
    "features.hooks": False,
    "features.skill_search": False,
    "features.memories": False,
    "features.skill_mcp_dependency_install": False,
    "features.multi_agent": False,
}


def child_environment() -> dict[str, str]:
    # Credentials are left in the official CLI store, not read or copied here.
    allowed = {
        "PATH",
        "HOME",
        "CODEX_HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SYSTEMROOT",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    return {name: value for name, value in os.environ.items() if name in allowed}


@contextmanager
def provider_lock():
    directory = Path(tempfile.gettempdir()) / f"bencheval-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise OSError("Unsafe provider-lock directory")
    descriptor = os.open(
        directory / "codex.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise OSError(
                "Codex is already running in another BenchEval process"
            ) from error
        yield
    finally:
        os.close(descriptor)


def probe_codex(binary: str, cwd: Path) -> dict:
    path = shutil.which(binary)
    if path is None:
        return {"available": False, "reason": "Codex not found; install Codex CLI"}
    env = child_environment()
    version = run_process([path, "--version"], cwd=cwd, env=env, timeout=10)
    help_result = run_process([path, "exec", "--help"], cwd=cwd, env=env, timeout=10)
    missing = [flag for flag in REQUIRED_FLAGS if flag not in help_result.stdout]
    login = run_process([path, "login", "status"], cwd=cwd, env=env, timeout=10)
    probes = (version, help_result, login)
    if any(p.cancelled or p.timed_out for p in probes):
        status = (
            ExecutionStatus.CANCELLED
            if any(p.cancelled for p in probes)
            else ExecutionStatus.TIMEOUT
        )
        return {
            "available": False,
            "cli_version": version.stdout.strip(),
            "status": status.value,
            "reason": f"Codex preflight: {status.value}",
        }
    auth = login.stdout + login.stderr
    subscription = login.exit_code == 0 and "logged in using chatgpt" in auth.lower()
    available = (
        version.exit_code == 0
        and help_result.exit_code == 0
        and not missing
        and subscription
    )
    return {
        "available": available,
        "binary": path,
        "cli_version": version.stdout.strip(),
        "subscription_login": subscription,
        "missing_flags": missing,
        "reason": (
            "Ready"
            if available
            else "Authenticate with codex login using ChatGPT"
            if not subscription
            else "Codex CLI lacks required capabilities; update the CLI"
        ),
    }


class CodexExecutor:
    def __init__(self, binary: str = "codex"):
        self.binary = binary

    def run(self, scenario: Scenario, prompt: str, artifact_dir: Path) -> Execution:
        execution = Execution(
            status=ExecutionStatus.ERROR,
            requested_model=scenario.executor.model,
            metadata={
                "sandbox": "read-only",
                "config_overrides": OVERRIDES,
                "user_config": "ignored",
                "rules": "ignored",
                "tool_policy": "restricted; CLI events observed",
                "authentication": "stored ChatGPT login",
            },
        )
        try:
            with (
                provider_lock(),
                tempfile.TemporaryDirectory(prefix="bencheval-") as name,
            ):
                cwd = Path(name)
                probe = probe_codex(self.binary, cwd)
                execution.cli_version = probe.get("cli_version")
                if not probe["available"]:
                    if probe.get("status"):
                        execution.status = ExecutionStatus(probe["status"])
                    elif probe.get("subscription_login") is False:
                        execution.status = ExecutionStatus.AUTH_REQUIRED
                    execution.reason = probe["reason"]
                    return execution
                argv = [
                    probe["binary"],
                    "exec",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--sandbox",
                    "read-only",
                    "--skip-git-repo-check",
                    "--json",
                    "--color",
                    "never",
                ]
                for key, value in OVERRIDES.items():
                    argv.extend(["-c", f"{key}={json.dumps(value)}"])
                if scenario.executor.model:
                    argv.extend(["--model", scenario.executor.model])
                response_path = cwd / "response.txt"
                argv.extend(["--output-last-message", str(response_path)])
                if scenario.response_schema is not None:
                    schema_path = cwd / "response-schema.json"
                    schema_path.write_text(
                        json.dumps(scenario.response_schema), encoding="utf-8"
                    )
                    argv.extend(["--output-schema", str(schema_path)])
                argv.append("-")
                execution.metadata["argv"] = argv
                process = run_process(
                    argv,
                    cwd=cwd,
                    env=child_environment(),
                    timeout=scenario.executor.timeout_seconds,
                    stdin=prompt,
                )
                (artifact_dir / "stdout.jsonl").write_text(
                    process.stdout, encoding="utf-8"
                )
                (artifact_dir / "stderr.txt").write_text(
                    process.stderr, encoding="utf-8"
                )
                execution.duration_seconds = process.duration_seconds
                execution.exit_code = process.exit_code
                trace = parse_trace(process.stdout)
                execution.metadata["cli_warnings"] = trace.warnings
                execution.metadata["ambient_skills"] = (
                    "native CLI discovery; not isolated"
                )
                execution.events, execution.usage = trace.events, trace.usage
                execution.trace_complete = trace.complete
                execution.effective_model = trace.effective_model
                if response_path.exists():
                    execution.response = response_path.read_text(encoding="utf-8")
                if process.cancelled:
                    execution.status, execution.reason = (
                        ExecutionStatus.CANCELLED,
                        "Cancelled",
                    )
                elif process.timed_out:
                    execution.status, execution.reason = (
                        ExecutionStatus.TIMEOUT,
                        "CLI timeout",
                    )
                elif process.exit_code != 0 or trace.failed:
                    diagnostics = (process.stdout + process.stderr).lower()
                    if any(
                        s in diagnostics
                        for s in (
                            "usage limit",
                            "quota exceeded",
                            "rate limit",
                            "rate_limit",
                        )
                    ):
                        execution.status = ExecutionStatus.QUOTA_EXHAUSTED
                    execution.reason = "Codex failed; inspect the local CLI logs"
                elif not execution.response:
                    execution.reason = "Codex did not return a final response"
                else:
                    execution.status = ExecutionStatus.COMPLETED
        except OSError as error:
            execution.reason = str(error)
        return execution
