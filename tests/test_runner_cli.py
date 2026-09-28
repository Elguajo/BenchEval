import pytest
from typer.testing import CliRunner

from bencheval.artifacts import ArtifactError, read_result
from bencheval.cli import STARTER, app
from bencheval.contracts import Execution, ExecutionStatus, Verdict
from bencheval.runner import run_scenario


class FakeExecutor:
    def __init__(self, response="4", status=ExecutionStatus.COMPLETED):
        self.response = response
        self.status = status

    def run(self, scenario, prompt, artifact_dir):
        assert "User request:" in prompt
        return Execution(status=self.status, response=self.response)


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
    assert read_result(directory) == result
    assert (directory / "prompt.txt").read_text().endswith("Return 4.")
    assert (directory / "response.txt").read_text() == response
    assert result.evidence_hashes.keys() >= {
        "prompt.txt",
        "scenario.json",
        "response.txt",
    }


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
