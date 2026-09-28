import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from bencheval.checks import evaluate
from bencheval.contracts import Check, Execution, ExecutionStatus, State
from bencheval.events import parse_trace


def full_trace(*items):
    return "\n".join(
        json.dumps(event)
        for event in (
            {"type": "thread.started", "thread_id": "t"},
            {"type": "turn.started"},
            *items,
            {"type": "turn.completed"},
        )
    )


def test_codex_nonfatal_error_item_does_not_hide_complete_trace():
    warning = "Skill descriptions were shortened to fit the skills context budget."
    trace = parse_trace(
        full_trace(
            {
                "type": "item.completed",
                "item": {"id": "w", "type": "error", "message": warning},
            },
            {
                "type": "item.completed",
                "item": {"id": "a", "type": "agent_message", "text": '{"answer":4}'},
            },
        )
    )
    assert trace.complete and not trace.failed
    assert trace.warnings == [warning]
    execution = Execution(
        status=ExecutionStatus.COMPLETED,
        events=trace.events,
        trace_complete=trace.complete,
    )
    assert (
        evaluate(Check(id="tools", axes=["behavior"], type="no_tools"), execution).state
        == State.PASS
    )


@pytest.mark.parametrize("kind", ["todo_list", "plan_update", "collab_tool_call"])
def test_planning_and_collaboration_are_tool_actions(kind):
    trace = parse_trace(
        full_trace({"type": "item.completed", "item": {"id": "a", "type": kind}})
    )
    assert trace.events[0].tool_action


def test_completed_marker_alone_does_not_establish_complete_evidence():
    assert not parse_trace('{"type":"turn.completed"}').complete
    assert not parse_trace(
        full_trace({"type": "item.started", "item": {"id": "a", "type": "reasoning"}})
    ).complete
    assert not parse_trace(full_trace() + '\n{"type":"turn.started"}').complete


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "https://example.invalid/remote.json"},
        {"$ref": "#/$defs/missing"},
        {"properties": {"x": {"$dynamicRef": "#node"}}},
        {"$schema": "http://json-schema.org/draft-07/schema#"},
        {"const": float("nan")},
        {"const": datetime(2026, 9, 28)},
    ],
)
def test_unsupported_schema_cannot_trigger_network_resolution(schema):
    with pytest.raises(ValidationError):
        Check(id="schema", axes=["outcome"], type="json_schema", json_schema=schema)
