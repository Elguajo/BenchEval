import json
from dataclasses import dataclass, field

from bencheval.contracts import Event

TOOL_ITEMS = {
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "web_search",
    "image_view",
    "image_generation",
    "collab_tool_call",
    "todo_list",
    "plan_update",
}
NON_TOOL_ITEMS = {"agent_message", "reasoning", "error"}
TOP_EVENTS = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "item.started",
    "item.updated",
    "item.completed",
    "error",
}


@dataclass
class ParsedTrace:
    events: list[Event] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    complete: bool = False
    failed: bool = False
    effective_model: str | None = None
    warnings: list[str] = field(default_factory=list)


def parse_trace(stdout: str) -> ParsedTrace:
    result = ParsedTrace()
    items = {}
    valid = True
    completed = False
    thread_started = turn_started = False
    pending = set()
    for index, line in enumerate(stdout.splitlines()):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            valid = False
            continue
        if not isinstance(event, dict):
            valid = False
            continue
        kind = event.get("type")
        if not isinstance(kind, str):
            valid = False
            continue
        if kind not in TOP_EVENTS:
            valid = False
        if completed:
            valid = False
        if kind == "thread.started":
            thread_started = True
        if kind == "turn.started":
            turn_started = True
        if kind in {"turn.failed", "error"}:
            result.failed = True
        if kind == "turn.completed":
            completed = True
            usage = event.get("usage", {})
            if isinstance(usage, dict):
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "cached_input_tokens",
                    "cache_write_input_tokens",
                    "reasoning_output_tokens",
                ):
                    value = usage.get(key)
                    if type(value) is int and value >= 0:
                        result.usage[key] = result.usage.get(key, 0) + value
        model = event.get("model")
        if isinstance(model, str):
            result.effective_model = model
        if kind in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item")
            if not isinstance(item, dict):
                valid = False
                continue
            item_kind = item.get("type")
            if not isinstance(item_kind, str):
                valid = False
                continue
            if item_kind not in TOOL_ITEMS | NON_TOOL_ITEMS:
                valid = False
            item_id = item.get("id")
            if not isinstance(item_id, str):
                item_id = f"event-{index}"
                valid = False
            # Never allow a later non-tool update to erase an observed tool action.
            previous = items.get(item_id)
            is_tool = item_kind in TOOL_ITEMS or (previous and previous.tool_action)
            items[item_id] = Event(
                id=item_id, kind=str(item_kind), tool_action=bool(is_tool)
            )
            if kind == "item.started":
                pending.add(item_id)
            elif kind == "item.completed":
                pending.discard(item_id)
            if item_kind == "error" and isinstance(item.get("message"), str):
                result.warnings.append(item["message"])
    result.events = list(items.values())
    result.complete = (
        valid
        and thread_started
        and turn_started
        and completed
        and not pending
        and not result.failed
    )
    return result
