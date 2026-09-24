"""SQL agent: turns a question (plus agreed definitions) into a checked, read-only query and its result."""

from a2a.types import AgentSkill
from agents import Agent, RunContextWrapper, function_tool
from agents.mcp import MCPServerStreamableHttp

from gold import a2a_host, config, llm, sql_model

INSTRUCTIONS = """You are the SQL agent. You answer data questions with numbers from the database.

1. Call generate_sql with the question and any business definitions you were given, word for word.
2. Call run_sql with exactly the SQL that generate_sql returned.
3. If run_sql returns an error, call generate_sql again with the error added to the question. Retry at most twice.
4. Reply with three parts:
   - the SQL you ran, in a ```sql block
   - the result as a markdown table (at most 20 rows; say if there are more)
   - one sentence on what the numbers show
Never invent or adjust numbers. If run_sql refused the query, explain that GOLD is read-only."""


def build_agent(servers: list[MCPServerStreamableHttp]) -> Agent:
    data_server = servers[0]

    async def schema_text() -> str:
        result = await data_server.call_tool("describe_schema", {})
        return "\n".join(getattr(c, "text", "") for c in result.content)

    @function_tool
    async def generate_sql(ctx: RunContextWrapper, question: str, definitions: str = "") -> str:
        """Write one read-only SQL query for the question using the dedicated SQL model.

        Args:
            question: The business question, in plain English.
            definitions: Agreed business definitions to follow, if any.
        """
        schema = await schema_text() if config.SQL_INCLUDE_SCHEMA else ""
        sql, usage = await sql_model.generate(question, definitions, schema)
        ctx.usage.add(usage)
        return sql

    return Agent(
        name="SQL agent",
        instructions=INSTRUCTIONS,
        model=llm.model(config.AGENT_MODEL),
        model_settings=llm.settings(),
        tools=[generate_sql],
        mcp_servers=servers,
    )


CARD = a2a_host.agent_card(
    name="SQL agent",
    description=(
        "Answers questions about business data by writing and running a read-only SQL query. "
        "Give it the question and any business definitions that apply."
    ),
    skills=[
        AgentSkill(
            id="answer_with_sql",
            name="Answer with SQL",
            description="Writes a read-only query with the dedicated SQL model, runs it, and returns the SQL and the result table.",
            tags=["sql", "analytics", "read-only"],
            examples=["What was revenue by country last year?", "Top 5 customers by lifetime value"],
        )
    ],
)


def main() -> None:
    a2a_host.serve(CARD, a2a_host.AgentsSdkExecutor(build_agent, {"data-tools": config.DATA_MCP_URL}))


if __name__ == "__main__":
    main()
