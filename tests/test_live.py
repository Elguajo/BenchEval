import os
from pathlib import Path

import pytest

from bencheval.artifacts import read_result
from bencheval.contracts import ExecutionStatus, Verdict
from bencheval.runner import run_scenario


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("BENCHEVAL_LIVE") != "1",
    reason="Set BENCHEVAL_LIVE=1 explicitly; consumes subscription usage",
)
def test_codex_subscription_schema_smoke(tmp_path):
    example = Path(__file__).resolve().parents[1] / "examples/response/arithmetic.yaml"
    result, directory = run_scenario(example, tmp_path / "runs")
    assert result.execution.status == ExecutionStatus.COMPLETED, result.execution.reason
    assert result.verdicts.overall == Verdict.PASS
    assert result.execution.cost_usd is None
    assert read_result(directory) == result
