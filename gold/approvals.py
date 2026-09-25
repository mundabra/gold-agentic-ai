"""Human approval for tools that change things: agents propose, people decide.

1. An agent calls a write tool (for example log_activity). The tool server calls gate(). With no
   approval attached, the tool does nothing and returns a proposal: a one-line summary of what
   would happen and a signed ticket.
2. The proposal travels back in the agent's trace, not in the model's words, so the model cannot
   alter it. The orchestrator returns it with the answer as a pending action, and the UI shows
   Approve and Reject.
3. On Approve, the orchestrator checks the ticket and that the approver is the user who asked,
   then calls the same tool on the same server itself, with an approval token in the
   X-Gold-Approval header. The tool server checks the token is for exactly this tool and these
   arguments, and acts.

Tickets and approval tokens are HMAC-signed with GOLD_IDENTITY_SECRET, which every GOLD service
shares and no model ever sees, so an agent cannot approve its own action. Both expire, and the
ticket's action id is the tool's idempotency key: an approval replayed does nothing twice.
Every proposal, approval and rejection is written to the audit trail.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass

from gold import config, identity

HEADER = "X-Gold-Approval"
TICKET_TTL = int(config.env("GOLD_APPROVAL_TTL_SECONDS", "3600"))
TOKEN_TTL = 120


class ApprovalError(Exception):
    """A ticket or approval that cannot be accepted."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _sign(kind: str, payload: dict) -> str:
    body = _b64(json.dumps({**payload, "kind": kind}, sort_keys=True, default=str).encode())
    # The kind is signed too, so a ticket can never be passed off as an approval.
    mac = hmac.new(config.IDENTITY_SECRET.encode(), f"{kind}.{body}".encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def _open(kind: str, token: str) -> dict:
    try:
        body, mac = token.split(".", 1)
        expected = _b64(hmac.new(config.IDENTITY_SECRET.encode(), f"{kind}.{body}".encode(), hashlib.sha256).digest())
    except (ValueError, AttributeError) as exc:
        raise ApprovalError("Malformed approval data.") from exc
    if not hmac.compare_digest(mac, expected):
        raise ApprovalError("The approval data has an invalid signature.")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    if payload.get("kind") != kind:
        raise ApprovalError("Wrong kind of approval data.")
    if payload.get("exp", 0) < time.time():
        raise ApprovalError("This approval request has expired. Ask again.")
    return payload


def _same(a: dict, b: dict) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


# --- Tool-server side -------------------------------------------------------

@dataclass(frozen=True)
class Gate:
    approved: bool
    action_id: str | None = None
    approved_by: str | None = None
    proposal: dict | None = None


def gate(ctx, tool: str, args: dict, summary: str, user: identity.User | None) -> Gate:
    """In a write tool: proceed only with a valid approval for exactly this call; otherwise propose it."""
    from gold.mcp import header

    token = header(ctx, HEADER)
    if token:
        approval = _open("approval", token)
        ticket = approval["ticket"]
        if ticket["tool"] != tool or not _same(ticket["args"], args):
            raise ApprovalError("The approval is for a different action.")
        if approval["approved_by"] != (user.id if user else None):
            raise ApprovalError("The approval was given by a different user.")
        return Gate(approved=True, action_id=ticket["id"], approved_by=approval["approved_by"])
    ticket = {
        "id": uuid.uuid4().hex,
        "tool": tool,
        "args": args,
        "summary": summary,
        "server": config.PUBLIC_URL.rstrip("/") + "/mcp",
        "user": user.id if user else None,
        "exp": int(time.time()) + TICKET_TTL,
    }
    return Gate(approved=False, proposal={
        "status": "needs_approval",
        "action": {"id": ticket["id"], "tool": tool, "summary": summary, "args": args},
        "ticket": _sign("ticket", ticket),
        "note": "Nothing has been done yet. The user must approve this action in the GOLD app.",
    })


# --- Orchestrator side ------------------------------------------------------

def pending(calls: list[dict]) -> list[dict]:
    """The proposals in a run's agent calls, as pending actions for the UI.

    What is shown comes from the signed ticket, not the trace, so the person approves exactly what would run."""
    found: dict[str, dict] = {}
    for call in calls:
        for step in call.get("steps", []):
            out = step.get("output")
            if isinstance(out, dict) and out.get("status") == "needs_approval" and out.get("ticket"):
                try:
                    ticket = _open("ticket", out["ticket"])
                except ApprovalError:
                    continue
                found[ticket["id"]] = {**{k: ticket[k] for k in ("id", "tool", "summary", "args")},
                                       "agent": call.get("agent"), "ticket": out["ticket"]}
    return list(found.values())


def check_ticket(ticket: str, user: identity.User | None) -> dict:
    """The ticket's contents, if it is genuine, unexpired and was raised for this user."""
    payload = _open("ticket", ticket)
    if payload["user"] != (user.id if user else None):
        raise ApprovalError("Only the person who asked can approve or reject this action.")
    return payload


async def execute(ticket: str, user: identity.User | None) -> dict:
    """Run an approved action: call the tool that proposed it, with a one-time approval token."""
    from agents.mcp import MCPServerStreamableHttp

    from gold.runlog import parse_output

    payload = check_ticket(ticket, user)
    token = _sign("approval", {"ticket": payload, "approved_by": user.id if user else None,
                               "exp": int(time.time()) + TOKEN_TTL})
    headers = {HEADER: token}
    if user:
        headers[identity.HEADER] = identity.sign(user)
    server = MCPServerStreamableHttp(params={"url": payload["server"], "timeout": 30, "headers": headers},
                                     name="approved-action", client_session_timeout_seconds=30)
    async with server:
        result = await server.call_tool(payload["tool"], payload["args"])
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    return {"action": {k: payload[k] for k in ("id", "tool", "summary", "args")}, "result": parse_output(text)}
