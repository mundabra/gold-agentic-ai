"""Definitions agent: tells everyone what a business term means here, from the glossary."""

from a2a.types import AgentSkill
from agents import Agent
from agents.mcp import MCPServerStreamableHttp

from apps.data_analyst import settings
from gold import a2a_host, config, llm

INSTRUCTIONS = """You are the Definitions agent. You explain what business terms mean at this company.

1. Pick out every business term in the request: metrics (revenue, units sold), time periods (last year),
   segments (active customer, region) and rankings (top genre).
2. Call search_glossary for them. Search again with other wording if a term is not found.
3. Call find_verified_queries with the whole question.
4. Reply with:
   - one bullet per term: the term, its agreed definition word for word, its SQL hint, and its owner
   - "Approved example queries:" followed by each example that is relevant to this question,
     with its question and its SQL word for word (leave out examples about something else)
If a business term has no agreed definition, say "No agreed definition" for it. Do not guess.
Ordinary words that simply name data (album, track, customer, country) need no definition: say
"Plain meaning; use the schema" for them rather than treating them as missing.
Do not write new SQL and do not answer the question itself."""


def build_agent(servers: list[MCPServerStreamableHttp]) -> Agent:
    return Agent(
        name="Definitions agent",
        instructions=INSTRUCTIONS,
        model=llm.model(config.AGENT_MODEL),
        model_settings=llm.settings(),
        mcp_servers=servers,
    )


CARD = a2a_host.agent_card(
    name="Definitions agent",
    description=(
        "Looks up the company's agreed definitions of business terms (revenue, active customer, last year) "
        "and analyst-approved example queries, so that every answer uses the same meaning."
    ),
    skills=[
        AgentSkill(
            id="define_terms",
            name="Define business terms",
            description="Returns the agreed definition, SQL hint and owner for each business term in a request.",
            tags=["glossary", "semantic-layer", "governance"],
            examples=["What does revenue mean?", "Define active customer and last year"],
        )
    ],
)


def main() -> None:
    a2a_host.serve(CARD, a2a_host.AgentsSdkExecutor(build_agent, {"glossary-tools": settings.GLOSSARY_MCP_URL}))


if __name__ == "__main__":
    main()
