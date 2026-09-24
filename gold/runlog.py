"""Turn an Agents SDK run into a small, readable record of what happened."""

import json

from agents import RunResult
from agents.items import ToolCallItem, ToolCallOutputItem


def _field(raw, name):
    return raw.get(name) if isinstance(raw, dict) else getattr(raw, name, None)


def _parse(value):
    """Tool output as data: JSON is decoded, and MCP text envelopes ({"type": "text", "text": ...}) are unwrapped."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, dict) and value.get("type") == "text" and isinstance(value.get("text"), str):
        return _parse(value["text"])
    return value


def tool_steps(result: RunResult, max_output_chars: int = 4000) -> list[dict]:
    """One entry per tool call, in order, with its arguments and (trimmed) output."""
    steps: dict[str, dict] = {}
    order: list[str] = []
    for item in result.new_items:
        if isinstance(item, ToolCallItem):
            call_id = _field(item.raw_item, "call_id") or _field(item.raw_item, "id") or str(len(order))
            steps[call_id] = {
                "tool": _field(item.raw_item, "name") or "tool",
                "input": _parse(_field(item.raw_item, "arguments")),
                "output": None,
            }
            order.append(call_id)
        elif isinstance(item, ToolCallOutputItem):
            call_id = _field(item.raw_item, "call_id")
            if call_id in steps:
                output = _parse(item.output)
                if isinstance(output, str) and len(output) > max_output_chars:
                    output = output[:max_output_chars] + " …"
                steps[call_id]["output"] = output
    return [steps[c] for c in order]


def usage(result: RunResult) -> dict:
    u = result.context_wrapper.usage
    return {
        "model_requests": u.requests,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "total_tokens": u.total_tokens,
    }
