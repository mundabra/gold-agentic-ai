"""Serve any OpenAI Agents SDK agent over A2A and register it for discovery.

The orchestrator never hard-codes where specialists live. Each specialist
publishes an Agent Card, registers with the registry, and keeps its
registration fresh with a heartbeat.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from contextlib import AsyncExitStack

import httpx
import uvicorn
from a2a.helpers import get_message_text, new_data_part, new_task_from_user_message, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from agents import Agent, Runner
from agents.mcp import MCPServerStreamableHttp
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from gold import config, runlog

log = logging.getLogger("gold.a2a")

AgentBuilder = Callable[[list[MCPServerStreamableHttp]], Agent]


class AgentsSdkExecutor(AgentExecutor):
    """Runs one Agents SDK agent per A2A request, connected to its MCP tool servers."""

    def __init__(self, build_agent: AgentBuilder, mcp_urls: dict[str, str], max_turns: int = 12):
        self.build_agent = build_agent
        self.mcp_urls = mcp_urls
        self.max_turns = max_turns

    async def run(self, text: str) -> tuple[str, dict]:
        async with AsyncExitStack() as stack:
            servers = []
            for name, url in self.mcp_urls.items():
                server = MCPServerStreamableHttp(
                    params={"url": url, "timeout": 30},
                    name=name,
                    cache_tools_list=True,
                    client_session_timeout_seconds=30,
                )
                servers.append(await stack.enter_async_context(server))
            agent = self.build_agent(servers)
            result = await Runner.run(agent, text, max_turns=self.max_turns)
            return str(result.final_output), {"steps": runlog.tool_steps(result), "usage": runlog.usage(result)}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.start_work()
        try:
            answer, trace = await self.run(get_message_text(context.message))
        except Exception as exc:
            log.exception("agent run failed")
            await updater.failed(new_text_message(f"The agent failed: {exc}"))
            return
        await updater.add_artifact(
            parts=[new_text_part(text=answer, media_type="text/plain"), new_data_part(trace, media_type="application/json")],
            name="answer",
        )
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel is not supported.")


def agent_card(name: str, description: str, skills: list[AgentSkill]) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        version="0.1.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/json"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=config.PUBLIC_URL, protocol_version="1.0")],
        skills=skills,
    )


async def _register_forever(interval: float = 30.0) -> None:
    """Register with the registry now and every `interval` seconds, so a restarted registry recovers."""
    headers = {"Authorization": f"Bearer {config.REGISTRY_TOKEN}"} if config.REGISTRY_TOKEN else {}
    async with httpx.AsyncClient(timeout=5, headers=headers) as client:
        while True:
            try:
                resp = await client.post(f"{config.REGISTRY_URL}/agents", json={"url": config.PUBLIC_URL})
                resp.raise_for_status()
            except Exception as exc:
                log.warning("registration with %s failed: %s", config.REGISTRY_URL, exc)
                await asyncio.sleep(3)
                continue
            await asyncio.sleep(interval)


def build_app(card: AgentCard, executor: AgentExecutor) -> Starlette:
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card)

    async def healthz(_):
        return JSONResponse({"status": "ok", "agent": card.name})

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(_register_forever())
        yield
        task.cancel()

    routes = [Route("/healthz", healthz), *create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")]
    return Starlette(routes=routes, lifespan=lifespan)


def serve(card: AgentCard, executor: AgentExecutor) -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(build_app(card, executor), host=config.HOST, port=config.PORT)
