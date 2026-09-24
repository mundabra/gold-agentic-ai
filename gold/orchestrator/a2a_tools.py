"""Expose every agent in the registry to the orchestrator as a tool it can call over A2A."""

import json
import re
import time

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers import get_data_parts, get_message_text, get_text_parts, new_text_message
from a2a.types import Role, SendMessageRequest, TaskState
from agents import FunctionTool
from agents.tool_context import ToolContext

from gold import config, identity


async def discover() -> list[dict]:
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(f"{config.REGISTRY_URL}/agents")
        resp.raise_for_status()
        return resp.json()


async def call_agent(url: str, text: str, user_token: str | None = None, timeout: float = 180) -> dict:
    """Send one message to an A2A agent and collect its answer and trace."""
    async with httpx.AsyncClient(timeout=timeout) as http:
        client = await create_client(url, client_config=ClientConfig(streaming=False, httpx_client=http))
        answer, trace, failure = [], {}, None
        try:
            message = new_text_message(text, role=Role.ROLE_USER)
            if user_token:
                message.metadata.update({identity.METADATA_KEY: user_token})
            request = SendMessageRequest(message=message)
            async for response in client.send_message(request):
                if response.HasField("task"):
                    task = response.task
                    for artifact in task.artifacts:
                        answer.extend(get_text_parts(artifact.parts))
                        for data in get_data_parts(artifact.parts):
                            if isinstance(data, dict):
                                trace.update(data)
                    if task.status.state == TaskState.TASK_STATE_FAILED:
                        failure = get_message_text(task.status.message) if task.status.HasField("message") else "failed"
                elif response.HasField("message"):
                    answer.append(get_message_text(response.message))
        finally:
            await client.close()
    return {"answer": "\n".join(answer).strip(), "trace": trace, "failure": failure}


def tool_name(agent_name: str) -> str:
    return "ask_" + re.sub(r"[^a-z0-9]+", "_", agent_name.lower()).strip("_")


def make_tool(entry: dict) -> FunctionTool:
    skills = "; ".join(f"{s['name']}: {s['description']}" for s in entry.get("skills", []))
    description = f"{entry['description']} Skills: {skills}".strip()

    async def invoke(ctx: ToolContext, args_json: str) -> str:
        request = json.loads(args_json or "{}").get("request", "")
        started = time.perf_counter()
        try:
            token = ctx.context.get("user_token") if isinstance(ctx.context, dict) else None
            result = await call_agent(entry["url"], request, token)
        except Exception as exc:
            result = {"answer": "", "trace": {}, "failure": f"could not reach the agent: {exc}"}
        record = {
            "agent": entry["name"],
            "request": request,
            "answer": result["answer"],
            "steps": result["trace"].get("steps", []),
            "usage": result["trace"].get("usage", {}),
            "failure": result["failure"],
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }
        if isinstance(ctx.context, dict):
            ctx.context.setdefault("calls", []).append(record)
        if result["failure"]:
            return f"{entry['name']} could not answer: {result['failure']}"
        return result["answer"] or f"{entry['name']} returned no answer."

    return FunctionTool(
        name=tool_name(entry["name"]),
        description=description,
        params_json_schema={
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "What you need from this agent, in full sentences."}
            },
            "required": ["request"],
            "additionalProperties": False,
        },
        on_invoke_tool=invoke,
    )
