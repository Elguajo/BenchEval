import hashlib
import json

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from bencheval.cli import app
from bencheval.contracts import Execution, ExecutionStatus, State, Verdict
from bencheval.executors.codex import CodexExecutor
from bencheval.judges.contracts import JudgeConfig
from bencheval.judges.evaluate import (
    import_verdict,
    job_lock,
    read_judge_result,
    run_job,
)
from bencheval.judges.jobs import JudgeError, load_config, read_job


def payload(job, state="PASS"):
    return {
        "job_id": job.id,
        "criteria": [
            {
                "id": c.id,
                "state": state,
                "explanation": "Supported by preserved evidence.",
                "evidence": ["request", *c.requires],
            }
            for c in job.config.criteria
        ],
    }


class StubJudge:
    def __init__(self, reply=None, status=ExecutionStatus.COMPLETED):
        self.reply, self.status, self.calls = reply, status, 0

    def invoke(self, config, prompt, schema, directory):
        self.calls += 1
        job = read_job(directory)
        assert "untrusted data" in prompt
        return Execution(
            provider=config.provider,
            status=self.status,
            response=json.dumps(self.reply if self.reply is not None else payload(job)),
            trace_complete=True,
        )


def test_separate_evidence_verified_result_and_immutable_actor(make_job):
    job, directory, source = make_job()
    before = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()
    }
    judge = StubJudge()
    result = run_job(directory, provider=judge)
    assert judge.calls == 1
    assert result.verdicts.overall == Verdict.PASS
    assert result.checks[0].state == State.PASS
    assert result.invocation.cost_usd is None
    assert result.warnings
    assert read_judge_result(directory) == result
    assert before == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()
    }
    with pytest.raises(JudgeError, match="finalized"):
        run_job(directory, provider=judge)
    assert judge.calls == 1
    assert job.evidence["response"] == "4"


def test_judge_cannot_erase_deterministic_hard_failure(make_job):
    _, directory, _ = make_job(response="5")
    result = run_job(directory, provider=StubJudge())
    assert result.checks[0].state == State.PASS
    assert result.verdicts.overall == Verdict.FAIL


@pytest.mark.parametrize(
    "severity,expected", [("hard", Verdict.INCONCLUSIVE), ("advisory", Verdict.PASS)]
)
def test_judge_timeout_is_not_a_guessed_score(make_job, severity, expected):
    _, directory, _ = make_job(severity=severity)
    result = run_job(directory, provider=StubJudge(status=ExecutionStatus.TIMEOUT))
    assert result.checks[0].state == State.ERROR
    assert result.verdicts.overall == expected


def test_unobservable_behavior_cannot_become_pass(make_job):
    _, directory, _ = make_job(trace=False, behavior=True)
    result = run_job(directory, provider=StubJudge())
    assert result.checks[0].state == State.NOT_OBSERVABLE
    assert result.verdicts.overall == Verdict.INCONCLUSIVE


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(job_id="wrong-job"),
        lambda v: v.update(criteria=[]),
        lambda v: v["criteria"].append(v["criteria"][0]),
        lambda v: v["criteria"][0].update(id="unknown"),
        lambda v: v["criteria"][0].update(state="MAYBE"),
        lambda v: v["criteria"][0].update(evidence=[]),
        lambda v: v["criteria"][0].update(evidence=["unknown"]),
        lambda v: v["criteria"][0].update(evidence=["response", "response"]),
        lambda v: v["criteria"][0].update(evidence=["request"]),
        lambda v: v["criteria"][0].update(explanation=" "),
    ],
)
def test_malformed_or_unsupported_verdict_fails_closed(make_job, mutation):
    job, directory, _ = make_job()
    value = payload(job)
    mutation(value)
    result = run_job(directory, provider=StubJudge(value))
    assert result.checks[0].state == State.ERROR
    assert result.verdicts.overall == Verdict.INCONCLUSIVE


def test_desktop_is_explicit_manual_handoff_with_unverified_context(make_job, tmp_path):
    job, directory, source = make_job(provider="desktop")
    with pytest.raises(JudgeError, match="interactive"):
        run_job(directory)
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps(payload(job)))
    cli = CliRunner().invoke(app, ["judge", "import", str(directory), str(reply)])
    assert cli.exit_code == 0, cli.output
    result = read_judge_result(directory)
    assert result.invocation.provider == "desktop"
    assert result.invocation.metadata["identity_verified"] is False
    assert any("ambient context unverified" in warning for warning in result.warnings)
    assert read_job(directory).source_path == str((source / "result.json").resolve())
    assert CliRunner().invoke(app, ["judge", "inspect", str(directory)]).exit_code == 0
    assert (
        CliRunner()
        .invoke(app, ["judge", "import", str(directory), str(reply)])
        .exit_code
        == 2
    )


def test_codex_cli_judge_uses_same_subscription_transport_in_new_invocation(
    make_job, fake_codex, monkeypatch
):
    job, directory, _ = make_job()
    binary = fake_codex(response=json.dumps(payload(job)), expected_prompt=None)
    monkeypatch.setattr(
        "bencheval.judges.providers.CodexExecutor", lambda: CodexExecutor(binary)
    )
    result = run_job(directory)
    assert result.verdicts.overall == Verdict.PASS
    assert result.invocation.metadata["context"]["enabled_skills"] == 0
    assert result.invocation.metadata["authentication"] == "stored ChatGPT login"


@pytest.mark.parametrize(
    "target", ["job.json", "prompt.txt", "response-schema.json", "actor"]
)
def test_changed_evidence_refused_before_call(make_job, target):
    _, directory, source = make_job()
    path = source / "response.txt" if target == "actor" else directory / target
    path.write_text("changed")
    judge = StubJudge()
    with pytest.raises(JudgeError):
        run_job(directory, provider=judge)
    assert judge.calls == 0


def test_job_lock_prevents_duplicate_inference(make_job):
    _, directory, _ = make_job()
    judge = StubJudge()
    with job_lock(directory), pytest.raises(JudgeError, match="already running"):
        run_job(directory, provider=judge)
    assert judge.calls == 0


def test_manual_import_rejects_other_provider_and_duplicate_json_keys(
    make_job, tmp_path
):
    _, directory, _ = make_job()
    reply = tmp_path / "reply.json"
    reply.write_text("{}")
    with pytest.raises(JudgeError, match="explicit desktop"):
        import_verdict(directory, reply)
    job, directory, _ = make_job(provider="desktop")
    reply.write_text(
        json.dumps(payload(job)).replace('"job_id":', '"job_id":"bad","job_id":', 1)
    )
    result = import_verdict(directory, reply)
    assert result.checks[0].state == State.ERROR


@pytest.mark.parametrize(
    "extra",
    [
        {"provider": "claude"},
        {"provider": "desktop", "api_key_env": "KEY"},
        {
            "provider": "openai_compatible",
            "model": "x",
            "base_url": "http://remote.example/v1",
            "allow_remote": True,
        },
        {
            "provider": "openai_compatible",
            "model": "x",
            "base_url": "https://remote.example/v1",
        },
        {
            "provider": "ollama",
            "model": "x",
            "base_url": "http://user:pass@localhost:11434",
        },
        {
            "provider": "ollama",
            "model": "x",
            "base_url": "http://localhost:11434?token=secret",
        },
        {
            "provider": "ollama",
            "model": "x",
            "base_url": "http://localhost:11434",
            "api_key_env": "KEY",
        },
        {"provider": "ollama"},
    ],
)
def test_configuration_blocks_implicit_external_disclosure_or_credentials(extra):
    with pytest.raises(ValidationError):
        JudgeConfig.model_validate(
            {
                "criteria": [{"id": "x", "axes": ["outcome"], "requirement": "x"}],
                **extra,
            }
        )


def test_behavior_requires_trace_and_config_rejects_duplicate_keys(tmp_path):
    with pytest.raises(ValidationError, match="trace evidence"):
        JudgeConfig.model_validate(
            {"criteria": [{"id": "x", "axes": ["behavior"], "requirement": "x"}]}
        )
    path = tmp_path / "invalid.yaml"
    path.write_text("provider: codex\nprovider: desktop\n")
    with pytest.raises(JudgeError):
        load_config(path)


def test_judge_rejects_incomplete_or_tool_using_codex_trace(make_job):
    from bencheval.contracts import Event

    for trace_complete, events in [
        (False, []),
        (True, [Event(id="x", kind="command_execution", tool_action=True)]),
    ]:
        _, directory, _ = make_job()

        class InvalidJudge(StubJudge):
            def invoke(self, *args, trace_complete=trace_complete, events=events):
                result = super().invoke(*args)
                result.trace_complete, result.events = trace_complete, events
                return result

        result = run_job(directory, provider=InvalidJudge())
        assert result.checks[0].state == State.ERROR
        assert result.verdicts.overall == Verdict.INCONCLUSIVE


def test_judge_cannot_claim_behaviors_from_missing_arguments(make_job):
    job, directory, _ = make_job(behavior=True)
    assert "not arguments/effects" in (directory / "prompt.txt").read_text()
    reply = payload(job, state="NOT_OBSERVABLE")
    reply["criteria"][0]["evidence"] = []
    result = run_job(directory, provider=StubJudge(reply))
    assert result.checks[0].state == State.NOT_OBSERVABLE
    assert result.verdicts.overall == Verdict.INCONCLUSIVE
