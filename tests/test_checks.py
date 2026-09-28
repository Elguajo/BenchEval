import pytest

from bencheval.checks import evaluate
from bencheval.contracts import (
    Check,
    Event,
    EvidenceRef,
    EvidenceType,
    Execution,
    ExecutionStatus,
    State,
)


@pytest.mark.parametrize(
    "kind,params,response,expected",
    [
        ("equals", {"expected": "4"}, "4", State.PASS),
        ("equals", {"expected": "4"}, "4\n", State.FAIL),
        ("contains", {"expected": "hello"}, "say hello", State.PASS),
        ("contains", {"expected": "hello"}, "goodbye", State.FAIL),
        ("regex", {"pattern": r"^4\s*$"}, "4\n", State.PASS),
        ("regex", {"pattern": "^4$"}, "four", State.FAIL),
        (
            "json_schema",
            {"json_schema": {"type": "integer", "const": 4}},
            "4",
            State.PASS,
        ),
        ("json_schema", {"json_schema": {"type": "integer"}}, '"4"', State.FAIL),
        ("json_schema", {"json_schema": {}}, "not JSON", State.FAIL),
        ("json_schema", {"json_schema": {}}, "NaN", State.FAIL),
        ("json_schema", {"json_schema": {}}, '{"x": 1, "x": 2}', State.FAIL),
    ],
)
def test_response_checks(kind, params, response, expected):
    check = Check(id="test", axes=["outcome"], type=kind, **params)
    execution = Execution(status=ExecutionStatus.COMPLETED, response=response)
    result = evaluate(check, execution)
    assert result.state == expected
    assert result.evidence == [
        EvidenceRef(id="response", type=EvidenceType.RESPONSE, source="response.txt")
    ]


@pytest.mark.parametrize(
    "status", [s for s in ExecutionStatus if s != ExecutionStatus.COMPLETED]
)
def test_incomplete_response_never_passes(scenario, status):
    assert (
        evaluate(scenario.checks[0], Execution(status=status, response="4")).state
        == State.ERROR
    )


def test_no_tools_needs_evidence_even_for_plain_response():
    check = Check(id="tools", axes=["behavior"], type="no_tools")
    execution = Execution(status=ExecutionStatus.COMPLETED, response="4")
    assert evaluate(check, execution).state == State.NOT_OBSERVABLE
    execution.trace_complete = True
    complete = evaluate(check, execution)
    assert complete.state == State.PASS
    assert [(ref.type, ref.source) for ref in complete.evidence] == [
        (EvidenceType.TOOL_EVENT, "events.json"),
        (EvidenceType.RUNTIME_METADATA, "runtime.json"),
    ]
    execution.events = [Event(id="tool-1", kind="command_execution", tool_action=True)]
    execution.trace_complete = False
    result = evaluate(check, execution)
    assert result.state == State.FAIL
    assert result.evidence == [
        EvidenceRef(
            id="tool-event-0",
            type=EvidenceType.TOOL_EVENT,
            source="events.json",
            locator="/0",
        )
    ]
