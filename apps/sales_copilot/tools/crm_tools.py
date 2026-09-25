"""MCP server: the Sales copilot's CRM tools. Typed tools over fixed queries, never model-written SQL.

Reading tools answer for the signed-in rep's accounts only (row-level security). The one
writing tool, log_activity, never writes on its own: it returns a proposal, and only runs
once the rep approves it in the GOLD app (gold/approvals.py).
"""

import json
from typing import Literal

from mcp.server.mcpserver import Context, MCPServer

from apps.sales_copilot import crm
from gold import approvals, config, identity
from gold.mcp import READ_ONLY, WRITES, current_user, serve

server = MCPServer(
    name="gold-crm-tools",
    instructions="A sales rep's accounts: portfolio, briefs, offers and activities. Logging an activity needs the rep's approval.",
)


def _dump(value) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


def _refused(reason: str) -> str:
    return _dump({"error": "refused", "reason": reason})


def _user(ctx: Context):
    user = current_user(ctx)
    if user is None and config.REQUIRE_IDENTITY:
        raise identity.AuthError("No signed-in user: GOLD requires identity.")
    return user


@server.tool(annotations=READ_ONLY)
def my_accounts(ctx: Context, sort_by: Literal["revenue", "at_risk", "recent", "declining"] = "revenue",
                limit: int = 10) -> str:
    """List the rep's accounts with lifetime value, orders, last purchase and revenue trend.

    sort_by: "revenue" (biggest first), "at_risk" (only accounts with no purchase in 180 days,
    longest gap first), "recent" (latest purchase first) or "declining" (biggest drop in
    revenue, last 12 months against the 12 months before).
    """
    try:
        user = _user(ctx)
        rows = crm.accounts(user, sort_by, limit)
        return _dump({"as_of": crm.as_of(user), "scope": crm.scope(user), "sort_by": sort_by, **crm.table(rows)})
    except identity.AuthError as exc:
        return _refused(str(exc))


@server.tool(annotations=READ_ONLY)
def find_account(ctx: Context, customer: str) -> str:
    """Find accounts by customer id, name or company (part of a name is enough)."""
    try:
        rows = crm.find(_user(ctx), customer)
    except identity.AuthError as exc:
        return _refused(str(exc))
    keep = ("customer_id", "customer", "company", "city", "country", "rep")
    return _dump({"matches": [{k: r[k] for k in keep} for r in rows]})


@server.tool(annotations=READ_ONLY)
def account_brief(ctx: Context, customer_id: int) -> str:
    """Everything a rep needs before a call: figures, favourite genres and artists, recent orders and activities."""
    try:
        user = _user(ctx)
        return _dump({"as_of": crm.as_of(user), **crm.brief(user, customer_id)})
    except (identity.AuthError, crm.NotFound) as exc:
        return _refused(str(exc))


@server.tool(annotations=READ_ONLY)
def next_best_offers(ctx: Context, customer_id: int, limit: int = 5) -> str:
    """Albums to offer: from the customer's two favourite genres, not yet bought, most popular first."""
    try:
        return _dump(crm.table(crm.offers(_user(ctx), customer_id, limit)))
    except (identity.AuthError, crm.NotFound) as exc:
        return _refused(str(exc))


@server.tool(annotations=READ_ONLY)
def list_activities(ctx: Context, customer_id: int | None = None, open_follow_ups: bool = False, limit: int = 10) -> str:
    """Logged calls, emails, meetings and notes, newest first; or only follow-ups still due."""
    try:
        return _dump(crm.table(crm.activities(_user(ctx), customer_id, open_follow_ups, limit)))
    except identity.AuthError as exc:
        return _refused(str(exc))


@server.tool(annotations=WRITES)
def log_activity(ctx: Context, customer_id: int, kind: Literal["call", "email", "meeting", "note"], note: str,
                 follow_up_on: str | None = None) -> str:
    """Log a call, email, meeting or note on an account, with an optional follow-up date (YYYY-MM-DD).

    This does not write anything by itself: it returns a proposal that the rep approves or
    rejects in the GOLD app. Tell the rep it is waiting for their approval.
    """
    try:
        user = _user(ctx)
        kind, note, follow_up_on = crm.check_activity(kind, note, follow_up_on)
        account = crm.one(user, customer_id)
    except (identity.AuthError, crm.NotFound, ValueError) as exc:
        return _refused(str(exc))
    args = {"customer_id": customer_id, "kind": kind, "note": note, "follow_up_on": follow_up_on}
    follow = f", follow up on {follow_up_on}" if follow_up_on else ""
    summary = f"Log a {kind} with {account['customer']}: \"{note}\"{follow}"
    try:
        gate = approvals.gate(ctx, "log_activity", args, summary, user)
    except approvals.ApprovalError as exc:
        return _refused(str(exc))
    if not gate.approved:
        return _dump(gate.proposal)
    try:
        done = crm.add_activity(user, **args, action_id=gate.action_id, approved_by=gate.approved_by)
    except Exception as exc:  # e.g. row-level security: not this rep's account
        return _dump({"error": "failed", "reason": str(exc).splitlines()[0]})
    verb = "Already logged" if done["already_logged"] else "Logged"
    return _dump({"status": "done", "activity_id": done["activity_id"],
                  "message": f"{verb} as activity #{done['activity_id']}."})


def main() -> None:
    serve(server)


if __name__ == "__main__":
    main()
