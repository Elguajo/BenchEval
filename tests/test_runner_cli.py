import json

import pytest
from typer.testing import CliRunner

from bencheval.artifacts import ArtifactError, read_result
from bencheval.cli import STARTER, app
from bencheval.contracts import (
    Axis,
    Check,
    CleanSuccess,
    Execution,
    ExecutionStatus,
    SuiteResult,
    Verdict,
)
from bencheval.runner import run_scenario


class FakeExecutor:
    def __init__(
        self, response="4", status=ExecutionStatus.COMPLETED, trace_complete=False
    ):
        self.response = response
        self.status = status
        self.trace_complete = trace_complete

    def run(self, scenario, prompt, artifact_dir):
        assert "User request:" in prompt
        return Execution(
            status=self.status,
            response=self.response,
            trace_complete=self.trace_complete,
        )


@pytest.mark.parametrize(
    "response,status,expected",
    [
        ("4", ExecutionStatus.COMPLETED, Verdict.PASS),
        ("5", ExecutionStatus.COMPLETED, Verdict.FAIL),
        ("4", ExecutionStatus.TIMEOUT, Verdict.INCONCLUSIVE),
    ],
)
def test_runner_preserves_artifacts_and_separates_status(
    scenario_file, tmp_path, response, status, expected
):
    result, directory = run_scenario(
        scenario_file, tmp_path / "runs", executor=FakeExecutor(response, status)
    )
    assert result.verdicts.overall == expected
    assert (
        result.clean_success
        == {
            Verdict.PASS: CleanSuccess.YES,
            Verdict.FAIL: CleanSuccess.NO,
            Verdict.INCONCLUSIVE: CleanSuccess.INCONCLUSIVE,
        }[expected]
    )
    assert result.version == 2
    assert read_result(directory) == result
    assert (directory / "prompt.txt").read_text().endswith("Return 4.")
    assert (directory / "response.txt").read_text() == response
    assert result.evidence_hashes.keys() >= {
        "prompt.txt",
        "scenario.json",
        "response.txt",
        "runtime.json",
    }


def test_suite_csr_counts_all_scheduled_attempts(scenario, tmp_path):
    scenario.checks.append(Check(id="tools", axes=["behavior"], type="no_tools"))
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(scenario.model_dump_json())
    executors = [FakeExecutor(trace_complete=True)] * 7 + [
        FakeExecutor(response="5", trace_complete=True),
        FakeExecutor(),
        FakeExecutor(status=ExecutionStatus.TIMEOUT),
    ]
    attempts = [
        run_scenario(scenario_path, tmp_path / "runs", executor=executor)[0]
        for executor in executors
    ]
    suite = SuiteResult.from_attempts("suite", 10, attempts)
    assert (
        suite.clean_successes,
        suite.failures,
        suite.inconclusive,
        suite.execution_failures,
        suite.completed_attempts,
    ) == (7, 1, 1, 1, 9)
    assert suite.clean_success_rate == 0.70
    assert suite.model_dump()["clean_success_rate"] == 0.70
    assert SuiteResult.model_validate_json(suite.model_dump_json()) == suite
    assert SuiteResult.from_attempts("empty", 0, []).clean_success_rate is None


def test_advisory_failure_visible_in_saved_result_and_inspect(scenario, tmp_path):
    scenario.checks.extend(
        [
            Check(id="format", axes=[Axis.INSTRUCTIONS], type="equals", expected="4"),
            Check(
                id="style",
                axes=[Axis.INSTRUCTIONS],
                severity="advisory",
                type="equals",
                expected="5",
            ),
        ]
    )
    path = tmp_path / "scenario.json"
    path.write_text(scenario.model_dump_json())
    result, directory = run_scenario(path, tmp_path / "runs", executor=FakeExecutor())
    assert result.verdicts.axes[Axis.INSTRUCTIONS] == Verdict.PASS
    assert result.verdicts.overall == Verdict.PASS
    assert result.clean_success == CleanSuccess.YES
    assert [check.id for check in result.advisories] == ["style"]
    inspected = CliRunner().invoke(app, ["inspect", str(directory)])
    assert inspected.exit_code == 0
    assert "Clean Success: YES" in inspected.output
    assert "Advisories:" in inspected.output
    assert "style: FAIL" in inspected.output
    assert "Evidence: response [response] response.txt" in inspected.output


def test_old_actor_schema_is_rejected(scenario_file, tmp_path):
    _, directory = run_scenario(
        scenario_file, tmp_path / "runs", executor=FakeExecutor()
    )
    path = directory / "result.json"
    value = json.loads(path.read_text())
    value["version"] = 1
    path.write_text(json.dumps(value))
    with pytest.raises(ArtifactError, match="Unsupported actor result version 1"):
        read_result(directory)


def test_evidence_tampering_detected(scenario_file, tmp_path):
    _, directory = run_scenario(
        scenario_file, tmp_path / "runs", executor=FakeExecutor()
    )
    (directory / "response.txt").write_text("changed")
    with pytest.raises(ArtifactError, match="Evidence changed"):
        read_result(directory)
    result = CliRunner().invoke(app, ["inspect", str(directory)])
    assert result.exit_code == 2


def test_cli_validate_and_non_overwriting_init(tmp_path):
    path = tmp_path / "scenario.yaml"
    runner = CliRunner()
    assert runner.invoke(app, ["init", str(path)]).exit_code == 0
    assert path.read_text() == STARTER
    assert runner.invoke(app, ["validate", str(path)]).exit_code == 0
    assert runner.invoke(app, ["init", str(path)]).exit_code == 2
    assert path.read_text() == STARTER


def test_bad_config_never_creates_attempt(tmp_path):
    path = tmp_path / "scenario.yaml"
    path.write_text("kind: coding-agent")
    output = tmp_path / "runs"
    result = CliRunner().invoke(app, ["run", str(path), "--output", str(output)])
    assert result.exit_code == 2
    assert not output.exists()


@pytest.mark.parametrize(
    "response,status,code",
    [
        ("4", ExecutionStatus.COMPLETED, 0),
        ("5", ExecutionStatus.COMPLETED, 1),
        ("4", ExecutionStatus.ERROR, 3),
    ],
)
def test_cli_exit_codes(scenario_file, tmp_path, monkeypatch, response, status, code):
    import bencheval.cli

    original = run_scenario
    monkeypatch.setattr(
        bencheval.cli,
        "run_scenario",
        lambda path, output: original(
            path, output, executor=FakeExecutor(response, status)
        ),
    )
    result = CliRunner().invoke(
        app, ["run", str(scenario_file), "--output", str(tmp_path / "runs")]
    )
    assert result.exit_code == code, result.output
    assert "Artifacts:" in result.output


def test_unique_run_ids(scenario_file, tmp_path):
    _, first = run_scenario(scenario_file, tmp_path / "runs", executor=FakeExecutor())
    _, second = run_scenario(scenario_file, tmp_path / "runs", executor=FakeExecutor())
    assert first != second
