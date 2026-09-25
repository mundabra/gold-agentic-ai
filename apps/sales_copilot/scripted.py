"""Canned replies for the scripted stand-in model (gold/testing/scripted_model.py): this app's steps."""

import datetime
import json
import re

from gold.testing.scripted_model import Turn, markdown_table, tool_call

NAME = re.compile(r"([A-ZÀ-Þ][\w'’-]+(?: [A-ZÀ-Þ][\w'’-]+)+)")


def _customer_name(text: str) -> str:
    names = [n for n in NAME.findall(text) if n.split()[0] not in {"Log", "Brief", "What", "Which", "Who"}]
    return names[0] if names else text


def _intent(text: str) -> str:
    lowered = text.lower()
    if re.search(r"discount|policy|licen[cs]e|objection|playbook|how (much|do|should)|allowed|approv", lowered):
        return "playbook"
    if re.search(r"\blog\b|follow.?up|remind", lowered):
        return "log"
    if re.search(r"offer|pitch|recommend|sell", lowered):
        return "offer"
    if re.search(r"\bbrief\b|tell me about|history", lowered):
        return "brief"
    return "portfolio"


def decide(turn: Turn) -> dict | None:
    if turn.system.startswith("You are the Sales copilot"):  # this app's orchestrator
        if "ask_account_agent" not in turn.called:
            return tool_call("ask_account_agent", {"request": turn.user})
        return {"content": turn.output["ask_account_agent"]}

    if "my_accounts" not in turn.tools:  # not the Account agent
        return None
    intent = _intent(turn.user)
    if intent == "playbook":
        if "search_knowledge" not in turn.called:
            return tool_call("search_knowledge", {"collection": "sales-playbook", "query": turn.user, "k": 3})
        found = json.loads(turn.output["search_knowledge"])
        results = found.get("results", [])
        if not results:
            return {"content": f"The sales playbook has nothing on that. ({found.get('reason', 'no passages')})"}
        top = results[0]
        return {"content": f"{top['text']} {top['cite']}"}
    if intent == "portfolio":
        if "my_accounts" not in turn.called:
            return tool_call("my_accounts", {"sort_by": "at_risk" if "attention" in turn.user or "risk" in turn.user else "revenue"})
        result = json.loads(turn.output["my_accounts"])
        return {"content": f"{result['row_count']} accounts ({result['scope']}), as of {result['as_of']}.\n\n"
                           + markdown_table(turn.output["my_accounts"])}
    if "find_account" not in turn.called:
        return tool_call("find_account", {"customer": _customer_name(turn.user)})
    matches = json.loads(turn.output["find_account"]).get("matches", [])
    if not matches:
        return {"content": "I couldn't find that customer among your accounts."}
    customer_id = matches[0]["customer_id"]
    if intent == "brief":
        if "account_brief" not in turn.called:
            return tool_call("account_brief", {"customer_id": customer_id})
        brief = json.loads(turn.output["account_brief"])
        a = brief["account"]
        genres = ", ".join(g["genre"] for g in brief["top_genres"])
        return {"content": f"**{a['customer']}** ({a['country']}): lifetime value {a['lifetime_value']} over "
                           f"{a['orders']} orders; last purchase {a['last_purchase']} "
                           f"({a['days_since_last_purchase']} days before {brief['as_of']}). Favourite genres: {genres}."}
    if intent == "offer":
        if "next_best_offers" not in turn.called:
            return tool_call("next_best_offers", {"customer_id": customer_id})
        return {"content": "Albums to offer, from their favourite genres:\n\n" + markdown_table(turn.output["next_best_offers"])}
    if "log_activity" not in turn.called:
        note = turn.user.split(":", 1)[1].split(",")[0].strip() if ":" in turn.user else turn.user
        kind = next((k for k in ("call", "email", "meeting") if k in turn.user.lower()), "note")
        follow_up = (datetime.date.today() + datetime.timedelta(days=14)).isoformat() if "follow" in turn.user.lower() else None
        return tool_call("log_activity", {"customer_id": customer_id, "kind": kind, "note": note, "follow_up_on": follow_up})
    result = json.loads(turn.output["log_activity"])
    if result.get("status") == "needs_approval":
        return {"content": f"Ready to log, waiting for your approval: {result['action']['summary']}"}
    return {"content": f"Could not prepare that: {result.get('reason', 'unknown error')}"}
