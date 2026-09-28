import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bencheval.contracts import ExecutionStatus
from bencheval.judges.contracts import JudgeConfig
from bencheval.judges.providers import HTTPJudge, post_json


@contextmanager
def endpoint(*, envelope=None, status=200, delay=0, drip=False, missing_bytes=0):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(
                {
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": json.loads(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    ),
                }
            )
            time.sleep(delay)
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "/must-not-follow")
            data = json.dumps(envelope).encode()
            self.send_header("Content-Length", str(len(data) + missing_bytes))
            self.end_headers()
            try:
                if drip:
                    for byte in data:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.02)
                else:
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
        )
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", requests
        finally:
            server.shutdown()
            thread.join(timeout=2)


def config(provider, url, **extra):
    return JudgeConfig.model_validate(
        {
            "provider": provider,
            "model": "fixture-model",
            "base_url": url,
            "criteria": [
                {"id": "quality", "axes": ["outcome"], "requirement": "Correct answer."}
            ],
            **extra,
        }
    )


@pytest.mark.parametrize("provider", ["ollama", "openai_compatible"])
def test_real_http_adapter_contracts_are_explicit_and_normalized(tmp_path, provider):
    content = '{"job_id":"fixture","criteria":[]}'
    envelope = (
        {
            "message": {"role": "assistant", "content": content},
            "done": True,
            "prompt_eval_count": 5,
            "eval_count": 9,
            "model": "effective-fixture",
        }
        if provider == "ollama"
        else {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 9},
            "model": "effective-fixture",
        }
    )
    with endpoint(envelope=envelope) as (url, requests):
        result = HTTPJudge().invoke(
            config(provider, url), "Preserved evidence", {"type": "object"}, tmp_path
        )
    assert result.status == ExecutionStatus.COMPLETED
    assert result.response == content
    assert result.usage == {"input_tokens": 5, "output_tokens": 9}
    assert result.effective_model == "effective-fixture"
    assert result.cost_usd is None
    body = requests[0]["body"]
    assert "tools" not in body and body["stream"] is False
    assert requests[0]["path"] == (
        "/api/chat" if provider == "ollama" else "/chat/completions"
    )
    if provider == "ollama":
        assert body["format"] == {"type": "object"}
    else:
        assert body["response_format"]["json_schema"]["strict"] is True
    assert json.loads((tmp_path / "provider-response.json").read_text()) == envelope


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, ExecutionStatus.AUTH_REQUIRED),
        (403, ExecutionStatus.AUTH_REQUIRED),
        (429, ExecutionStatus.QUOTA_EXHAUSTED),
        (500, ExecutionStatus.ERROR),
        (302, ExecutionStatus.ERROR),
    ],
)
def test_http_failures_do_not_retry_redirect_or_fallback(tmp_path, status, expected):
    with endpoint(status=status) as (url, requests):
        result = HTTPJudge().invoke(
            config("ollama", url), "Private evidence", {}, tmp_path
        )
    assert result.status == expected
    assert len(requests) == 1
    assert not (tmp_path / "provider-response.json").exists()


@pytest.mark.parametrize(
    "envelope",
    [
        [],
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": {"content": "x"}, "finish_reason": "length"}]},
        {
            "choices": [
                {
                    "message": {"content": "x", "tool_calls": [{}]},
                    "finish_reason": "stop",
                }
            ]
        },
        {"choices": [{"message": {"refusal": "no"}, "finish_reason": "stop"}]},
        {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]},
    ],
)
def test_malformed_api_envelopes_never_pass(tmp_path, envelope):
    with endpoint(envelope=envelope) as (url, _):
        result = HTTPJudge().invoke(
            config("openai_compatible", url), "Evidence", {}, tmp_path
        )
    assert result.status == ExecutionStatus.ERROR


@pytest.mark.parametrize("drip", [False, True])
def test_network_timeout_is_wall_clock_bounded(tmp_path, drip):
    with endpoint(
        envelope={"message": {"content": "many characters"}, "done": True},
        delay=0 if drip else 0.2,
        drip=drip,
    ) as (url, _):
        started = time.monotonic()
        result = HTTPJudge().invoke(
            config("ollama", url, timeout_seconds=0.06), "Evidence", {}, tmp_path
        )
        elapsed = time.monotonic() - started
    assert result.status == ExecutionStatus.TIMEOUT
    assert elapsed < 0.5


def test_missing_api_key_stops_before_network(monkeypatch, tmp_path):
    monkeypatch.delenv("BENCHEVAL_TEST_KEY", raising=False)

    def forbidden(*args):
        pytest.fail("Missing credentials must not make a request")

    monkeypatch.setattr("bencheval.judges.providers.post_json", forbidden)
    result = HTTPJudge().invoke(
        config(
            "openai_compatible",
            "https://localhost/v1",
            api_key_env="BENCHEVAL_TEST_KEY",
        ),
        "Evidence",
        {},
        tmp_path,
    )
    assert result.status == ExecutionStatus.AUTH_REQUIRED
    assert not list(tmp_path.iterdir())


def test_api_secret_never_written_or_relayed_in_artifacts(monkeypatch, tmp_path):
    secret = "secret-only-fixture"
    monkeypatch.setenv("BENCHEVAL_TEST_KEY", secret)
    captured = []

    def echoed(url, body, headers, timeout):
        captured.append(headers)
        return 200, json.dumps({"credential": secret}).encode()

    monkeypatch.setattr("bencheval.judges.providers.post_json", echoed)
    result = HTTPJudge().invoke(
        config(
            "openai_compatible",
            "https://localhost/v1",
            api_key_env="BENCHEVAL_TEST_KEY",
        ),
        "Evidence",
        {},
        tmp_path,
    )
    assert captured[0]["Authorization"] == "Bearer " + secret
    assert result.status == ExecutionStatus.ERROR
    assert secret not in result.model_dump_json()
    assert not list(tmp_path.iterdir())


def test_oversized_body_is_refused(tmp_path):
    with endpoint(envelope={"x": "x" * 2_000_001}) as (url, _):
        with pytest.raises(ValueError, match="2 MB"):
            post_json(url + "/api/chat", {}, {}, 2)


def test_truncated_http_body_is_not_accepted_even_if_json_is_complete(tmp_path):
    envelope = {"message": {"content": "{}"}, "done": True}
    with endpoint(envelope=envelope, missing_bytes=10) as (url, _):
        result = HTTPJudge().invoke(config("ollama", url), "Evidence", {}, tmp_path)
    assert result.status == ExecutionStatus.ERROR
