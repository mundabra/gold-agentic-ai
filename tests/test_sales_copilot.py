"""The Sales copilot end to end: account questions, and an action that runs only after approval.
Runs the whole stack with the scripted test model. Skipped when no Postgres is reachable."""

import json
import os
import tempfile
from pathlib import Path

import httpx
import psycopg
import pytest
import stack
from test_end_to_end import DB_URL, _db_available

BASE = f"http://127.0.0.1:{stack.PORTS['orchestrator']}"
ADMIN_URL = DB_URL.replace("gold_reader:gold_reader", "gold_admin:gold_admin")
AUDIT_LOG = Path(tempfile.gettempdir()) / f"gold-sales-audit-{os.getpid()}.jsonl"
LOG_CALL = "Log a call with Luís Gonçalves: asked for a Latin jazz bundle, follow up in two weeks"


@pytest.fixture(scope="module")
def sales_stack():
    if not _db_available():
        pytest.skip("needs Postgres with deploy/postgres/* loaded")
    os.environ.update(GOLD_DATABASE_URL=DB_URL, GOLD_AUDIT_LOG=str(AUDIT_LOG))
    AUDIT_LOG.unlink(missing_ok=True)
    procs = stack.start(real_model=False)
    yield
    stack.stop(procs)
    os.environ.pop("GOLD_AUDIT_LOG", None)
    AUDIT_LOG.unlink(missing_ok=True)
    with psycopg.connect(ADMIN_URL) as conn:  # leave the shared test database as it was
        conn.execute("DELETE FROM crm_activity WHERE action_id IS NOT NULL")


def ask(question: str) -> dict:
    resp = httpx.post(f"{BASE}/api/ask", json={"question": question, "app": "sales-copilot"}, timeout=60)
    assert resp.status_code == 200, resp.text
    return resp.json()


def logged_calls() -> int:
    with psycopg.connect(ADMIN_URL) as conn:
        return conn.execute("SELECT COUNT(*) FROM crm_activity WHERE action_id IS NOT NULL").fetchone()[0]


def test_both_apps_are_served(sales_stack):
    apps = {a["name"]: a for a in httpx.get(f"{BASE}/api/apps").json()}
    assert set(apps) == {"data-analyst", "sales-copilot"}
    assert apps["data-analyst"]["read_only"] is True and apps["sales-copilot"]["read_only"] is False
    assert apps["sales-copilot"]["ui"]["examples"]
    agents = httpx.get(f"{BASE}/api/agents", params={"app_name": "sales-copilot"}).json()
    assert {a["name"] for a in agents} == {"Account agent", "Definitions agent", "SQL agent"}
    assert httpx.post(f"{BASE}/api/ask", json={"question": "hi", "app": "nope"}).status_code == 404


def test_accounts_that_need_attention(sales_stack):
    body = ask("Which of my accounts need attention?")
    assert body["app"] == "sales-copilot" and [c["agent"] for c in body["calls"]] == ["Account agent"]
    [step] = body["calls"][0]["steps"]
    assert step["tool"] == "my_accounts" and step["input"] == {"sort_by": "at_risk"}
    assert step["output"]["as_of"] == "2025-12-22" and step["output"]["row_count"] > 0
    assert all(row[step["output"]["columns"].index("at_risk")] for row in step["output"]["rows"])
    assert body["actions"] == []


def test_a_brief_and_offers_for_one_customer(sales_stack):
    brief = ask("Brief me on Luís Gonçalves")
    assert [s["tool"] for s in brief["calls"][0]["steps"]] == ["find_account", "account_brief"]
    assert "Luís Gonçalves" in brief["answer"] and "Rock" in brief["answer"]
    offers = ask("What should I offer Luís Gonçalves next?")
    result = offers["calls"][0]["steps"][-1]["output"]
    assert offers["calls"][0]["steps"][-1]["tool"] == "next_best_offers" and result["row_count"] == 5
    assert "album" in result["columns"]


def test_an_action_is_only_proposed_until_approved(sales_stack):
    before = logged_calls()
    body = ask(LOG_CALL)
    [action] = body["actions"]
    assert action["tool"] == "log_activity" and action["args"]["customer_id"] == 1 and action["args"]["kind"] == "call"
    assert "Luís Gonçalves" in action["summary"] and "approval" in body["answer"]
    assert logged_calls() == before  # nothing written yet

    done = httpx.post(f"{BASE}/api/actions/approve", json={"ticket": action["ticket"]}, timeout=30).json()
    assert done["status"] == "done" and done["result"]["status"] == "done"
    assert logged_calls() == before + 1
    with psycopg.connect(ADMIN_URL) as conn:
        kind, note, follow_up, action_id = conn.execute(
            "SELECT kind, note, follow_up_on, action_id FROM crm_activity ORDER BY activity_id DESC LIMIT 1").fetchone()
    assert (kind, action_id) == ("call", action["id"]) and "Latin jazz" in note and follow_up is not None

    again = httpx.post(f"{BASE}/api/actions/approve", json={"ticket": action["ticket"]}, timeout=30).json()
    assert again["status"] == "done" and again["result"]["message"].startswith("Already logged")
    assert logged_calls() == before + 1  # an approval replayed adds nothing


def test_rejected_and_forged_actions_do_nothing(sales_stack):
    before = logged_calls()
    [action] = ask(LOG_CALL)["actions"]
    rejected = httpx.post(f"{BASE}/api/actions/reject", json={"ticket": action["ticket"]}).json()
    assert rejected["status"] == "rejected"
    body, sig = action["ticket"].split(".")
    forged = httpx.post(f"{BASE}/api/actions/approve", json={"ticket": body + "." + sig[::-1]})
    assert forged.status_code == 403
    assert logged_calls() == before


def test_the_agent_cannot_approve_its_own_action(sales_stack):
    """Calling the tool again, as an agent would, only makes another proposal: approval needs the platform's key."""
    import asyncio

    from agents.mcp import MCPServerStreamableHttp

    async def call_tool():
        server = MCPServerStreamableHttp(params={"url": f"http://127.0.0.1:{stack.PORTS['mcp-crm']}/mcp",
                                                 "headers": {"X-Gold-Approval": "not-a-real-approval"}}, name="crm")
        async with server:
            result = await server.call_tool("log_activity", {"customer_id": 1, "kind": "note", "note": "sneaky"})
        return json.loads(result.content[0].text)

    before = logged_calls()
    out = asyncio.run(call_tool())
    assert out["error"] == "refused" and logged_calls() == before


def test_approvals_are_audited(sales_stack):
    records = [json.loads(line) for line in AUDIT_LOG.read_text().splitlines()]
    decisions = [r["decision"] for r in records if r.get("event") == "action"]
    assert "approved" in decisions and "rejected" in decisions
    proposed = [r for r in records if r.get("event") == "question" and r["actions_proposed"]]
    assert proposed and proposed[0]["app"] == "sales-copilot"
    assert "Account agent: log_activity" in proposed[0]["tools"]


def test_playbook_questions_are_answered_from_documents_with_citations(sales_stack):
    body = ask("How much discount can I give without approval?")
    [step] = body["calls"][0]["steps"]
    assert step["tool"] == "search_knowledge" and step["input"]["collection"] == "sales-playbook"
    top = step["output"]["results"][0]
    assert top["source"] == "pricing-and-discounts.md"
    assert top["cite"] in body["answer"] and "10%" in body["answer"]


def test_restricted_documents_reach_only_their_audience(sales_stack):
    """Called as each user would be: sales leadership sees the internal matrix, a rep does not."""
    import asyncio

    from agents.mcp import MCPServerStreamableHttp

    from gold import identity

    async def search(groups: tuple[str, ...]) -> list[str]:
        token = identity.sign(identity.User("someone@example.com", groups))
        server = MCPServerStreamableHttp(params={"url": f"http://127.0.0.1:{stack.PORTS['mcp-knowledge']}/mcp",
                                                 "headers": {identity.HEADER: token}}, name="knowledge")
        async with server:
            result = await server.call_tool("search_knowledge", {
                "collection": "sales-playbook", "query": "Who can approve 30% off? Floor price for Enterprise?", "k": 10})
        return [r["source"] for r in json.loads(result.content[0].text)["results"]]

    assert "discount-approval-matrix.md" in asyncio.run(search(("sales", "sales-leadership")))
    assert "discount-approval-matrix.md" not in asyncio.run(search(("sales",)))
