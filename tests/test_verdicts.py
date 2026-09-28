from itertools import product

import pytest

from bencheval.contracts import (
    Axis,
    CheckResult,
    CleanSuccess,
    EvidenceRef,
    EvidenceType,
    ExecutionStatus,
    State,
    Verdict,
)
from bencheval.verdicts import aggregate


def result(state, axis=Axis.OUTCOME, severity="hard"):
    return CheckResult(
        id="check",
        axes=[axis],
        severity=severity,
        state=state,
        expected="expected",
        actual="actual",
        evidence=(
            [EvidenceRef(id="proof", type=EvidenceType.GENERIC_ARTIFACT, source="x")]
            if state in (State.PASS, State.FAIL)
            else []
        ),
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
    assert verdict.axes[Axis.BEHAVIOR] == Verdict.NOT_OBSERVABLE


@pytest.mark.parametrize(
    "name,states,status,expected_axes,overall,clean_success",
    [
        (
            "A clean pass",
            (State.PASS, State.PASS, State.PASS),
            ExecutionStatus.COMPLETED,
            (Verdict.PASS, Verdict.PASS, Verdict.PASS),
            Verdict.PASS,
            CleanSuccess.YES,
        ),
        (
            "B forbidden behavior",
            (State.PASS, State.PASS, State.FAIL),
            ExecutionStatus.COMPLETED,
            (Verdict.PASS, Verdict.PASS, Verdict.FAIL),
            Verdict.FAIL,
            CleanSuccess.NO,
        ),
        (
            "C instruction failure",
            (State.PASS, State.FAIL, State.PASS),
            ExecutionStatus.COMPLETED,
            (Verdict.PASS, Verdict.FAIL, Verdict.PASS),
            Verdict.FAIL,
            CleanSuccess.NO,
        ),
        (
            "E missing behavior evidence",
            (State.PASS, State.PASS, State.NOT_OBSERVABLE),
            ExecutionStatus.COMPLETED,
            (Verdict.PASS, Verdict.PASS, Verdict.NOT_OBSERVABLE),
            Verdict.INCONCLUSIVE,
            CleanSuccess.INCONCLUSIVE,
        ),
        (
            "F timeout",
            (State.ERROR, State.ERROR, State.NOT_OBSERVABLE),
            ExecutionStatus.TIMEOUT,
            (Verdict.INCONCLUSIVE, Verdict.INCONCLUSIVE, Verdict.NOT_OBSERVABLE),
            Verdict.INCONCLUSIVE,
            CleanSuccess.INCONCLUSIVE,
        ),
        (
            "G failure dominates error",
            (State.FAIL, State.ERROR, State.PASS),
            ExecutionStatus.COMPLETED,
            (Verdict.FAIL, Verdict.INCONCLUSIVE, Verdict.PASS),
            Verdict.FAIL,
            CleanSuccess.NO,
        ),
    ],
)
def test_decision_table(name, states, status, expected_axes, overall, clean_success):
    checks = [result(state, axis) for state, axis in zip(states, Axis, strict=True)]
    verdict = aggregate(checks, status)
    assert tuple(verdict.axes.values()) == expected_axes, name
    assert verdict.overall == overall, name
    assert {
        Verdict.PASS: CleanSuccess.YES,
        Verdict.FAIL: CleanSuccess.NO,
        Verdict.INCONCLUSIVE: CleanSuccess.INCONCLUSIVE,
    }[verdict.overall] == clean_success, name


def test_advisory_failure_is_visible_without_changing_hard_results():
    checks = [result(State.PASS, axis) for axis in Axis]
    checks.append(result(State.FAIL, Axis.INSTRUCTIONS, "advisory"))
    verdict = aggregate(checks, ExecutionStatus.COMPLETED)
    assert verdict.axes[Axis.INSTRUCTIONS] == Verdict.PASS
    assert verdict.overall == Verdict.PASS
    assert checks[-1].state == State.FAIL and checks[-1].severity == "advisory"


def test_unassessed_behavior_not_observable():
    verdict = aggregate([result(State.PASS)], ExecutionStatus.COMPLETED)
    assert verdict.axes[Axis.BEHAVIOR] == Verdict.NOT_OBSERVABLE


def test_only_explicit_inapplicability_is_not_applicable():
    verdict = aggregate(
        [result(State.PASS), result(State.NOT_APPLICABLE, Axis.BEHAVIOR)],
        ExecutionStatus.COMPLETED,
    )
    assert verdict.axes[Axis.BEHAVIOR] == Verdict.NOT_APPLICABLE
