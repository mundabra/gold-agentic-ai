"""Approval tickets and tokens: an agent can propose, only the person who asked can approve."""

import time
from types import SimpleNamespace

import pytest

from gold import approvals
from gold.identity import User

JANE, STEVE = User("jane@example.com"), User("steve@example.com")
ARGS = {"customer_id": 1, "kind": "call", "note": "hello", "follow_up_on": None}


def ctx(headers: dict | None = None):
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers=headers or {})))


def propose(user=JANE) -> dict:
    gate = approvals.gate(ctx(), "log_activity", ARGS, "Log a call", user)
    assert gate.approved is False
    return gate.proposal


def approval_for(ticket: str, approver=JANE, **overrides) -> str:
    payload = approvals.check_ticket(ticket, approver)
    return approvals._sign("approval", {"ticket": {**payload, **overrides}, "approved_by": approver.id,
                                        "exp": int(time.time()) + 60})


def test_without_approval_a_write_tool_only_proposes():
    proposal = propose()
    assert proposal["status"] == "needs_approval" and proposal["action"]["args"] == ARGS
    assert approvals.pending([{"agent": "Account agent", "steps": [{"output": proposal}]}])[0]["summary"] == "Log a call"


def test_an_approved_call_proceeds_with_the_ticket_id_as_idempotency_key():
    proposal = propose()
    token = approval_for(proposal["ticket"])
    gate = approvals.gate(ctx({approvals.HEADER: token}), "log_activity", ARGS, "Log a call", JANE)
    assert gate.approved and gate.action_id == proposal["action"]["id"] and gate.approved_by == JANE.id


def test_only_the_person_who_asked_can_decide():
    proposal = propose(JANE)
    with pytest.raises(approvals.ApprovalError, match="Only the person who asked"):
        approvals.check_ticket(proposal["ticket"], STEVE)


def test_an_approval_covers_exactly_one_action():
    token = approval_for(propose()["ticket"])
    with pytest.raises(approvals.ApprovalError, match="different action"):
        approvals.gate(ctx({approvals.HEADER: token}), "log_activity", {**ARGS, "note": "changed"}, "x", JANE)
    with pytest.raises(approvals.ApprovalError, match="different action"):
        approvals.gate(ctx({approvals.HEADER: token}), "delete_account", ARGS, "x", JANE)
    with pytest.raises(approvals.ApprovalError, match="different user"):
        approvals.gate(ctx({approvals.HEADER: token}), "log_activity", ARGS, "x", STEVE)


def test_a_ticket_is_not_an_approval_and_forgeries_fail():
    ticket = propose()["ticket"]
    with pytest.raises(approvals.ApprovalError):  # the signed kind differs
        approvals.gate(ctx({approvals.HEADER: ticket}), "log_activity", ARGS, "x", JANE)
    body, sig = ticket.split(".")
    with pytest.raises(approvals.ApprovalError, match="signature"):
        approvals.check_ticket(body + "." + sig[:-2] + "AA", JANE)


def test_expired_approvals_are_refused():
    expired = approvals._sign("approval", {"ticket": {}, "approved_by": JANE.id, "exp": int(time.time()) - 1})
    with pytest.raises(approvals.ApprovalError, match="expired"):
        approvals.gate(ctx({approvals.HEADER: expired}), "log_activity", ARGS, "x", JANE)
