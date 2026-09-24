"""Example: add a new specialist to GOLD without touching the orchestrator.

The Trends agent explains how a metric changed over time. It reuses the
read-only data tools over MCP, publishes an A2A Agent Card, and registers
itself. The orchestrator finds it in the registry on the next question and
can call it as `ask_trends_agent`.

    GOLD_PUBLIC_URL=http://trends-agent:8000 python examples/trends_agent.py
"""

from a2a.types import AgentSkill
from agents import Agent

from gold import a2a_host, config, llm

INSTRUCTIONS = """You are the Trends agent. You explain how a business metric changed over time.
Use describe_schema to find the right tables, then run_sql to get the metric per period.
Reply with the per-period table, the change between the last two periods in absolute and
percentage terms, and one sentence on what drove it. Only use numbers returned by run_sql."""


def build_agent(servers):
    return Agent(
        name="Trends agent",
        instructions=INSTRUCTIONS,
        model=llm.model(config.AGENT_MODEL),
        mcp_servers=servers,
    )


CARD = a2a_host.agent_card(
    name="Trends agent",
    description="Explains how a business metric changed between periods (month over month, year over year).",
    skills=[
        AgentSkill(
            id="explain_trend",
            name="Explain a trend",
            description="Computes a metric per period and explains the change between the latest periods.",
            tags=["trends", "analytics"],
            examples=["How did revenue change year over year?"],
        )
    ],
)

if __name__ == "__main__":
    a2a_host.serve(CARD, a2a_host.AgentsSdkExecutor(build_agent, {"data-tools": config.DATA_MCP_URL}))
