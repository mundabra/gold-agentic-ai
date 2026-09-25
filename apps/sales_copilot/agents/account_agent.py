"""Account agent: a sales rep's accounts, from the CRM tools. Proposes activities; never logs them on its own."""

import datetime

from a2a.types import AgentSkill
from agents import Agent
from agents.mcp import MCPServerStreamableHttp

from apps.sales_copilot import settings
from gold import a2a_host, config, llm

INSTRUCTIONS = """You are the Account agent. You help a sales rep with their own accounts, using the CRM tools.

- Portfolio questions ("my accounts", "who needs attention", "who is slipping"): call my_accounts with the
  right sort_by. "Needs attention" and "at risk" mean sort_by="at_risk".
- A named customer: call find_account first if you do not have the customer_id, then account_brief.
- What to offer or pitch: call next_best_offers for the customer.
- Logging a call, email, meeting or note, or setting a follow-up date: call log_activity only when the rep's
  message explicitly asks to log, record or schedule something. Drafting an email, a brief or suggested next
  steps is not a request to log: never propose an entry the rep did not ask for. log_activity only proposes
  the entry: it is not logged until the rep approves it in the app. Say "waiting for your approval", never
  that it is logged.
- Dates: today is {today}. Take follow-up dates (YYYY-MM-DD) from this calendar, never by counting:
{calendar}
- Drafting an email: write the draft for the rep to send; you cannot send email.

Reply with the facts the tools returned: a short summary first, then a markdown table where it helps.
Amounts are US dollars; copy every figure exactly as the tool returned it (38.62 is $38.62), with no
rounding and no added units. The figures are as of the date the tools return ("as_of"). Never invent
customers or numbers. If a tool refuses, say why in one sentence."""


def calendar(today: datetime.date, days: int = 21) -> str:
    """The next three weeks, one line each, so the model looks dates up instead of computing them."""
    lines = []
    for n in range(1, days + 1):
        day = today + datetime.timedelta(days=n)
        lines.append(f"  {day:%A %Y-%m-%d}" + (" (tomorrow)" if n == 1 else ""))
    return "\n".join(lines)


def build_agent(servers: list[MCPServerStreamableHttp]) -> Agent:
    return Agent(
        name="Account agent",
        instructions=INSTRUCTIONS.format(today=f"{datetime.date.today():%A %Y-%m-%d}",
                                         calendar=calendar(datetime.date.today())),
        model=llm.model(config.AGENT_MODEL),
        model_settings=llm.settings(),
        mcp_servers=servers,
    )


CARD = a2a_host.agent_card(
    name="Account agent",
    description=(
        "Knows the signed-in sales rep's accounts: portfolio and accounts at risk, account briefs, next-best "
        "offers and activity history. Proposes calls, meetings, notes and follow-ups for the rep to approve."
    ),
    skills=[
        AgentSkill(
            id="manage_accounts",
            name="Manage my accounts",
            description="Lists and briefs the rep's accounts, suggests what to offer, and proposes activities to log.",
            tags=["sales", "crm", "accounts"],
            examples=["Which of my accounts need attention?", "Brief me on Luís Gonçalves",
                      "Log a call with Luís Gonçalves, follow up in two weeks"],
        )
    ],
)


def main() -> None:
    a2a_host.serve(CARD, a2a_host.AgentsSdkExecutor(build_agent, {"crm-tools": settings.CRM_MCP_URL}))


if __name__ == "__main__":
    main()
