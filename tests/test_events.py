import json

import pytest

from bencheval.events import parse_trace


def stream(*events):
    return "\n".join(json.dumps(event) for event in events)


def test_complete_response_trace_and_usage():
    trace = parse_trace(
        stream(
            {"type": "thread.started", "thread_id": "t"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "a", "type": "agent_message"}},
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 5,
                    "cached_input_tokens": 10,
                },
            },
        )
    )
    assert trace.complete
    assert not trace.events[0].tool_action
    assert trace.usage == {
        "input_tokens": 20,
        "output_tokens": 5,
        "cached_input_tokens": 10,
    }
    assert trace.effective_model is None


@pytest.mark.parametrize(
    "event",
    [
        {"type": "future.event"},
        {"type": []},
        [],
        {"type": "item.completed", "item": {}},
        {"type": "item.completed", "item": {"id": "a", "type": []}},
        {"type": "item.completed", "item": {"id": "a", "type": "future_tool"}},
        {"type": "error", "message": "failed"},
    ],
)
def test_unknown_or_malformed_trace_not_complete(event):
    trace = parse_trace(stream(event, {"type": "turn.completed"}))
    assert not trace.complete


def test_truncation_and_invalid_json_not_complete():
    assert not parse_trace('{"type": "turn.started"}').complete
    assert not parse_trace('{broken\n{"type": "turn.completed"}').complete


@pytest.mark.parametrize(
    "kind",
    [
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "web_search",
        "image_view",
        "image_generation",
    ],
)
def test_tool_action_cannot_be_erased_by_update(kind):
    trace = parse_trace(
        stream(
            {"type": "item.started", "item": {"id": "a", "type": kind}},
            {"type": "item.completed", "item": {"id": "a", "type": "agent_message"}},
            {"type": "turn.completed"},
        )
    )
    assert trace.events[0].tool_action


def test_invalid_usage_not_invented():
    trace = parse_trace(
        stream(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": -1,
                    "output_tokens": True,
                    "cached_input_tokens": "1",
                },
            }
        )
    )
    assert trace.usage == {}
