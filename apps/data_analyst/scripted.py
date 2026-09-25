"""Canned replies for the scripted stand-in model (gold/testing/scripted_model.py): this app's steps."""

import json

from gold.testing.scripted_model import Turn, markdown_table, tool_call

CANNED_SQL = [
    (
        ("lifetime value", "top 5 customers"),
        "SELECT c.first_name || ' ' || c.last_name AS customer, c.country, "
        "ROUND(SUM(il.unit_price * il.quantity), 2) AS lifetime_value "
        "FROM customer c JOIN invoice i ON i.customer_id = c.customer_id "
        "JOIN invoice_line il ON il.invoice_id = i.invoice_id "
        "GROUP BY c.customer_id, c.first_name, c.last_name, c.country "
        "ORDER BY lifetime_value DESC LIMIT 5",
    ),
    (
        ("genre",),
        "SELECT g.name AS genre, ROUND(SUM(il.unit_price * il.quantity), 2) AS revenue "
        "FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id "
        "JOIN track t ON t.track_id = il.track_id JOIN genre g ON g.genre_id = t.genre_id "
        "WHERE EXTRACT(YEAR FROM i.invoice_date) = (SELECT MAX(EXTRACT(YEAR FROM invoice_date)) FROM invoice) "
        "GROUP BY g.name ORDER BY revenue DESC LIMIT 1",
    ),
    (
        ("active customers",),
        "SELECT COUNT(DISTINCT customer_id) AS active_customers FROM invoice "
        "WHERE invoice_date > (SELECT MAX(invoice_date) FROM invoice) - INTERVAL '12 months'",
    ),
    (
        ("revenue by country",),
        "SELECT i.billing_country AS country, ROUND(SUM(il.unit_price * il.quantity), 2) AS revenue "
        "FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id "
        "WHERE EXTRACT(YEAR FROM i.invoice_date) = (SELECT MAX(EXTRACT(YEAR FROM invoice_date)) FROM invoice) "
        "GROUP BY i.billing_country ORDER BY revenue DESC",
    ),
]
DEFAULT_SQL = "SELECT COUNT(*) AS invoices FROM invoice"



def decide(turn: Turn) -> dict | None:
    if turn.system.startswith("You are Talk to your Data"):  # this app's orchestrator
        if "ask_definitions_agent" not in turn.called:
            return tool_call("ask_definitions_agent", {"request": f"Define the business terms in: {turn.user}"})
        if "ask_sql_agent" not in turn.called:
            request = f"Question: {turn.user}\n\nDefinitions:\n{turn.output['ask_definitions_agent']}"
            return tool_call("ask_sql_agent", {"request": request})
        return {"content": f"Here is the answer.\n\n{turn.output['ask_sql_agent']}\n\n"
                           f"Definition used:\n{turn.output['ask_definitions_agent']}"}

    if "search_glossary" in turn.tools:  # definitions agent
        if "search_glossary" not in turn.called:
            return tool_call("search_glossary", {"terms": turn.user})
        if "find_verified_queries" in turn.tools and "find_verified_queries" not in turn.called:
            question = turn.user.split(":", 1)[-1].strip()  # "Define the business terms in: <question>"
            return tool_call("find_verified_queries", {"question": question})
        matches = json.loads(turn.output["search_glossary"]).get("matches", [])
        bullets = [f"- **{m['term']}**: {m['definition']} (owner: {m['owner']})" for m in matches]
        examples = json.loads(turn.output.get("find_verified_queries") or "{}").get("examples", [])
        if examples:
            bullets.append("Approved example queries:")
            bullets += [f"- {e['question']}: {e['sql']}" for e in examples]
        return {"content": "\n".join(bullets) or "No agreed definition found."}

    if "generate_sql" in turn.tools:  # SQL agent
        if "generate_sql" not in turn.called:
            return tool_call("generate_sql", {"question": turn.user})
        if "run_sql" not in turn.called:
            return tool_call("run_sql", {"sql": turn.output["generate_sql"]})
        return {"content": f"```sql\n{turn.output['generate_sql']}\n```\n\n{markdown_table(turn.output['run_sql'])}"}

    if not turn.tools:
        # The dedicated SQL model being asked for a query. Match on the question
        # only, not on the definitions and examples appended to it.
        lowered = turn.user.split("\n\nBusiness definitions")[0].split("\n\nDefinitions")[0].lower()
        for keywords, sql in CANNED_SQL:
            if any(k in lowered for k in keywords):
                return {"content": sql}
        return {"content": DEFAULT_SQL}
    return None
