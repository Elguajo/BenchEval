from itertools import product

import pytest

from bencheval.contracts import Axis, CheckResult, ExecutionStatus, State, Verdict
from bencheval.verdicts import aggregate


def result(state, axis=Axis.OUTCOME, severity="hard"):
    return CheckResult(
        id="check",
        axes=[axis],
        severity=severity,
        state=state,
        expected="expected",
        actual="actual",
    )


@pytest.mark.parametrize("states", list(product(State, repeat=3)))
@pytest.mark.parametrize("status", list(ExecutionStatus))
def test_full_hard_rule_table(states, status):
    checks = [result(state, axis) for state, axis in zip(states, Axis, strict=True)]
    verdict = aggregate(checks, status)
    # Independent specification: proven violations dominate incomplete execution.
    if State.FAIL in states:
        expected = Verdict.FAIL
    elif (
        status != ExecutionStatus.COMPLETED
        or State.ERROR in states
        or State.NOT_OBSERVABLE in states
        or states[0] != State.PASS
    ):
        expected = Verdict.INCONCLUSIVE
    else:
        expected = Verdict.PASS
    assert verdict.overall == expected


def test_correct_outcome_does_not_hide_instruction_failure():
    verdict = aggregate(
        [result(State.PASS), result(State.FAIL, Axis.INSTRUCTIONS)],
        ExecutionStatus.COMPLETED,
    )
    assert verdict.axes[Axis.OUTCOME] == Verdict.PASS
    assert verdict.axes[Axis.INSTRUCTIONS] == Verdict.FAIL
    assert verdict.overall == Verdict.FAIL


@pytest.mark.parametrize("state", list(State))
def test_advisory_cannot_change_overall(state):
    verdict = aggregate(
        [result(State.PASS), result(state, Axis.BEHAVIOR, "advisory")],
        ExecutionStatus.COMPLETED,
    )
    assert verdict.overall == Verdict.PASS


def test_unassessed_behavior_not_observable():
    verdict = aggregate([result(State.PASS)], ExecutionStatus.COMPLETED)
    assert verdict.axes[Axis.BEHAVIOR] == Verdict.NOT_OBSERVABLE


def test_only_explicit_inapplicability_is_not_applicable():
    verdict = aggregate(
        [result(State.PASS), result(State.NOT_APPLICABLE, Axis.BEHAVIOR)],
        ExecutionStatus.COMPLETED,
    )
    assert verdict.axes[Axis.BEHAVIOR] == Verdict.NOT_APPLICABLE
