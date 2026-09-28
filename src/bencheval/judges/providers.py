import http.client
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from bencheval.contracts import Execution, ExecutionStatus, Scenario
from bencheval.executors.codex import CodexExecutor
from bencheval.json_utils import strict_json_loads
from bencheval.judges.contracts import JudgeConfig


def post_json(url: str, body: dict, headers: dict, timeout: float) -> tuple[int, bytes]:
    """Direct HTTP(S), no redirects/proxies, bounded body and read deadline.

    DNS resolution uses the operating system's timeout, not this read deadline.
    """
    parsed = urlsplit(url)
    connection_type = (
        http.client.HTTPSConnection
        if parsed.scheme == "https"
        else http.client.HTTPConnection
    )
    connection = connection_type(parsed.hostname, parsed.port, timeout=timeout)
    deadline = time.monotonic() + timeout
    response = None
    try:
        connection.connect()
        transport = connection.sock
        transport.settimeout(max(0.001, deadline - time.monotonic()))
        connection.request(
            "POST", parsed.path or "/", json.dumps(body).encode(), headers
        )
        transport.settimeout(max(0.001, deadline - time.monotonic()))
        response = connection.getresponse()
        # Do not read arbitrary error bodies or follow redirects.
        if response.status != 200:
            return response.status, b""
        data = bytearray()
        while len(data) <= 2_000_000:
            if response.isclosed():
                if response.length not in (None, 0):
                    raise ValueError("Incomplete provider body")
                return response.status, bytes(data)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Judge HTTP deadline")
            transport.settimeout(remaining)
            chunk = response.read1(min(65536, 2_000_001 - len(data)))
            if not chunk:
                if response.length not in (None, 0):
                    raise ValueError("Incomplete provider body")
                return response.status, bytes(data)
            data.extend(chunk)
        raise ValueError("Provider response exceeds 2 MB")
    finally:
        if response is not None:
            response.close()
        connection.close()


class CodexJudge:
    def invoke(
        self, config: JudgeConfig, prompt: str, schema: dict, directory: Path
    ) -> Execution:
        scenario = Scenario(
            id="llm-judge",
            prompt=prompt,
            response_schema=schema,
            executor={
                "provider": "codex",
                "model": config.model,
                "timeout_seconds": config.timeout_seconds,
                "context_mode": "controlled",
            },
            checks=[
                {
                    "id": "schema",
                    "axes": ["outcome"],
                    "type": "json_schema",
                    "json_schema": schema,
                }
            ],
        )
        return CodexExecutor().run(scenario, prompt, directory)


class HTTPJudge:
    def invoke(
        self, config: JudgeConfig, prompt: str, schema: dict, directory: Path
    ) -> Execution:
        result = Execution(
            status=ExecutionStatus.ERROR,
            provider=config.provider,
            requested_model=config.model,
            metadata={
                "base_url": config.base_url,
                "tools": "not offered",
                "api_key_env": config.api_key_env,
            },
        )
        headers = {"Content-Type": "application/json"}
        key = None
        if config.api_key_env:
            key = os.environ.get(config.api_key_env)
            if not key:
                result.status = ExecutionStatus.AUTH_REQUIRED
                result.reason = f"Set {config.api_key_env} in your environment"
                return result
            if "\n" in key or "\r" in key:
                result.reason = "Invalid API credential format"
                return result
            headers["Authorization"] = "Bearer " + key
        messages = [{"role": "user", "content": prompt}]
        if config.provider == "ollama":
            endpoint = config.base_url.rstrip("/") + "/api/chat"
            body = {
                "model": config.model,
                "messages": messages,
                "stream": False,
                "format": schema,
                "options": {"temperature": 0},
            }
        else:
            endpoint = config.base_url.rstrip("/") + "/chat/completions"
            body = {
                "model": config.model,
                "messages": messages,
                "stream": False,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "bencheval_verdict",
                        "strict": True,
                        "schema": schema,
                    },
                },
            }
        started = time.monotonic()
        try:
            status, data = post_json(endpoint, body, headers, config.timeout_seconds)
            if status != 200:
                result.status = (
                    ExecutionStatus.AUTH_REQUIRED
                    if status in (401, 403)
                    else ExecutionStatus.QUOTA_EXHAUSTED
                    if status == 429
                    else ExecutionStatus.ERROR
                )
                result.reason = (
                    f"Judge HTTP status {status}; no redirect or schema fallback"
                )
                return result
            if key and key.encode() in data:
                raise ValueError(
                    "Provider echoed an API credential; response was not saved"
                )
            value = strict_json_loads(data.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Invalid provider envelope")
            (directory / "provider-response.json").write_bytes(data)
            if config.provider == "ollama":
                message = value["message"]
                finished = value.get("done") is True
                usage = {
                    "input_tokens": value.get("prompt_eval_count"),
                    "output_tokens": value.get("eval_count"),
                }
            else:
                choices = value["choices"]
                if not isinstance(choices, list) or len(choices) != 1:
                    raise ValueError("Expected one provider choice")
                if not isinstance(choices[0], dict):
                    raise ValueError("Invalid provider choice")
                message = choices[0]["message"]
                finished = choices[0].get("finish_reason") == "stop"
                usage = value.get("usage") or {}
                if not isinstance(usage, dict):
                    raise ValueError("Invalid usage envelope")
                usage = {
                    "input_tokens": usage.get("prompt_tokens"),
                    "output_tokens": usage.get("completion_tokens"),
                }
            if (
                not isinstance(message, dict)
                or message.get("tool_calls")
                or message.get("refusal")
            ):
                raise ValueError("Judge attempted a tool call or refused")
            content = message.get("content")
            if not finished or not isinstance(content, str) or not content:
                raise ValueError("Judge response is incomplete")
            result.response = content
            result.status = ExecutionStatus.COMPLETED
            result.effective_model = (
                value.get("model") if isinstance(value.get("model"), str) else None
            )
            result.usage = {k: v for k, v in usage.items() if type(v) is int and v >= 0}
        except TimeoutError:
            result.status, result.reason = ExecutionStatus.TIMEOUT, "Judge HTTP timeout"
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            result.reason = "Malformed, refused, oversized or incomplete judge response"
        except (OSError, http.client.HTTPException):
            result.reason = "Judge transport or local evidence write failed"
        except KeyboardInterrupt:
            result.status, result.reason = (
                ExecutionStatus.CANCELLED,
                "Judge request cancelled",
            )
        finally:
            result.duration_seconds = time.monotonic() - started
        return result
