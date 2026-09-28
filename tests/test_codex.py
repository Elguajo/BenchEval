from bencheval.contracts import ExecutionStatus
from bencheval.executors.codex import CodexExecutor, child_environment, probe_codex


def test_real_fake_cli_and_no_api_fallback(fake_codex, scenario, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-forward")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-forward")
    monkeypatch.setenv("CODEX_API_KEY", "do-not-forward")
    execution = CodexExecutor(fake_codex()).run(scenario, "Return 4.", tmp_path)
    assert execution.status == ExecutionStatus.COMPLETED
    assert execution.response == "4"
    assert execution.trace_complete
    assert execution.usage == {"input_tokens": 3, "output_tokens": 1}
    assert execution.cost_usd is None and execution.quota_consumed is None
    assert execution.effective_model is None
    argv = execution.metadata["argv"]
    assert "--ignore-user-config" in argv and "--ignore-rules" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert (tmp_path / "stdout.jsonl").is_file()
    assert (tmp_path / "stderr.txt").read_text().strip() == "local diagnostic"


def test_missing_binary(scenario, tmp_path):
    execution = CodexExecutor("bencheval-no-such-codex").run(
        scenario, "Return 4.", tmp_path
    )
    assert execution.status == ExecutionStatus.ERROR
    assert "not found" in execution.reason


def test_auth_required(fake_codex, scenario, tmp_path):
    binary = fake_codex(login=False)
    assert not probe_codex(binary, tmp_path)["available"]
    execution = CodexExecutor(binary).run(scenario, "Return 4.", tmp_path)
    assert execution.status == ExecutionStatus.AUTH_REQUIRED
    assert "codex login" in execution.reason
    assert execution.cost_usd is None


def test_timeout_preserves_partial_streams(fake_codex, scenario, tmp_path):
    scenario.executor.timeout_seconds = 0.2
    execution = CodexExecutor(fake_codex(delay=30)).run(scenario, "Return 4.", tmp_path)
    assert execution.status == ExecutionStatus.TIMEOUT
    assert (tmp_path / "stdout.jsonl").read_text()
    assert (tmp_path / "stderr.txt").read_text()


def test_quota_is_distinct_from_failure(fake_codex, scenario, tmp_path):
    binary = fake_codex(
        exit_code=1, trace=[{"type": "error", "message": "usage limit"}]
    )
    execution = CodexExecutor(binary).run(scenario, "Return 4.", tmp_path)
    assert execution.status == ExecutionStatus.QUOTA_EXHAUSTED
    assert not execution.trace_complete


def test_no_final_response_is_error(fake_codex, scenario, tmp_path):
    execution = CodexExecutor(fake_codex(response=None)).run(
        scenario, "Return 4.", tmp_path
    )
    assert execution.status == ExecutionStatus.ERROR


def test_environment_does_not_copy_unrelated_secrets(monkeypatch):
    monkeypatch.setenv("MY_PRIVATE_TOKEN", "secret")
    assert "MY_PRIVATE_TOKEN" not in child_environment()
