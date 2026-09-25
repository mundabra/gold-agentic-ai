"""The orchestrator: the API and chat UI people talk to, for every app.

Each request names an app (app.yaml). The orchestrator runs an Agents SDK agent with that app's
instructions, the registry agents the app may call as tools, and the platform's controls:
identity, guardrails, conversation memory, approvals for actions, audit and feedback.
"""

import logging
import re
import time
import uuid
from pathlib import Path

import uvicorn
from agents import (
    Agent,
    GuardrailFunctionOutput,
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    RunContextWrapper,
    Runner,
    input_guardrail,
    output_guardrail,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from gold import approvals, apps, audit, config, feedback, identity, llm, rails, runlog, sessions, telemetry
from gold.orchestrator.a2a_tools import discover, make_tool

log = logging.getLogger("gold.orchestrator")

REFUSAL = "{title} is read-only, so I can't change or delete data. I can answer questions about it."
RAILS_REFUSAL = "I can't help with that request."
RAILS_ANSWER_WITHHELD = "The answer was withheld by the safety checks. Try rephrasing the question."

_WRITE_INTENT = re.compile(
    r"\b(delete|drop|truncate|insert|alter|wipe|erase|purge)\b"
    r"|\bupdate\s+(the\s+)?\w+\s+(set|to)\b"
    r"|\bremove\s+(all|every|the)\b",
    re.I,
)


def _latest_user_text(user_input) -> str:
    """The guardrail receives the whole conversation; only the newest question matters."""
    if isinstance(user_input, str):
        return user_input
    for item in reversed(user_input):
        if isinstance(item, dict) and item.get("role") == "user":
            content = item.get("content", "")
            if isinstance(content, list):
                return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
            return str(content)
    return ""


@input_guardrail(run_in_parallel=False)
async def read_only_guardrail(_ctx: RunContextWrapper, _agent: Agent, user_input) -> GuardrailFunctionOutput:
    """Stop requests to change data before any model is called."""
    hit = _WRITE_INTENT.search(_latest_user_text(user_input))
    return GuardrailFunctionOutput(
        output_info={"blocked_by": "read-only guardrail", "matched": hit.group(0) if hit else None},
        tripwire_triggered=bool(hit),
    )


@input_guardrail(run_in_parallel=False)
async def nemo_input_rails(_ctx: RunContextWrapper, _agent: Agent, user_input) -> GuardrailFunctionOutput:
    """NVIDIA NeMo Guardrails input rails (optional): jailbreaks, off-topic requests, personal data."""
    result = await rails.check([{"role": "user", "content": _latest_user_text(user_input)}], "input")
    return GuardrailFunctionOutput(
        output_info={"blocked_by": f"NeMo Guardrails: {result['rail']}"}, tripwire_triggered=result["blocked"]
    )


@output_guardrail
async def nemo_output_rails(ctx: RunContextWrapper, _agent: Agent, output) -> GuardrailFunctionOutput:
    """NVIDIA NeMo Guardrails output rails (optional): nothing leaves that the policy forbids."""
    question = ctx.context.get("question", "") if isinstance(ctx.context, dict) else ""
    messages = [{"role": "user", "content": question}, {"role": "assistant", "content": str(output)}]
    result = await rails.check(messages, "output")
    return GuardrailFunctionOutput(
        output_info={"blocked_by": f"NeMo Guardrails: {result['rail']}"}, tripwire_triggered=result["blocked"]
    )


class Question(BaseModel):
    question: str
    app: str | None = None
    session_id: str | None = None


class Decision(BaseModel):
    ticket: str


class Feedback(BaseModel):
    app: str | None = None
    answer_id: str
    question: str
    sql: str | None = None
    rating: str
    comment: str | None = None
    corrected_sql: str | None = None


app = FastAPI(title="GOLD orchestrator")
_STATIC = Path(__file__).parent / "static"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


def _user(request: Request) -> identity.User | None:
    try:
        return identity.from_request(request.headers)
    except identity.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _app(name: str | None) -> apps.App:
    try:
        return apps.get(name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/apps")
def list_apps() -> list[dict]:
    """The apps this GOLD serves, for the app picker."""
    return [a.public() for a in apps.all_apps().values()]


@app.get("/api/identity")
def whoami(request: Request) -> dict:
    """The signed-in user as GOLD sees them, and (in demo mode) the users to pick from."""
    user = _user(request)
    return {
        "mode": config.AUTH_MODE,
        "user": user.id if user else None,
        "demo_users": config.DEMO_USERS if config.AUTH_MODE == "demo" else [],
    }


@app.get("/api/features")
def features() -> dict:
    return {"feedback": feedback.enabled()}


@app.post("/api/feedback")
def give_feedback(fb: Feedback, request: Request) -> dict:
    """A user rates an answer; it goes into the review queue for analysts (gold feedback list)."""
    if not feedback.enabled():
        raise HTTPException(status_code=503, detail="Feedback is not configured (GOLD_FEEDBACK_DATABASE_URL).")
    user = _user(request)
    target = _app(fb.app)
    try:
        check = target.hook("check_correction")
        corrected = check(fb.corrected_sql) if check else fb.corrected_sql
        feedback.submit(app=target.name, answer_id=fb.answer_id, question=fb.question, sql_ran=fb.sql,
                        rating=fb.rating, comment=fb.comment, corrected_sql=corrected, user=user.id if user else None)
    except feedback.FeedbackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"received": True}


@app.get("/api/agents")
async def agents(app_name: str | None = None) -> list[dict]:
    """Live agents in the registry; with ?app_name=, only those that app may call."""
    registered = await discover()
    return [a for a in registered if _app(app_name).serves(a)] if app_name else registered


@app.post("/api/actions/approve")
async def approve(decision: Decision, request: Request) -> dict:
    """Run an action an agent proposed, now that the person who asked has approved it."""
    user = _user(request)
    try:
        ticket = approvals.check_ticket(decision.ticket, user)
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        outcome = await approvals.execute(decision.ticket, user)
    except Exception as exc:
        audit.action(ticket, "failed", user=user.id if user else None, error=str(exc))
        raise HTTPException(status_code=502, detail=f"The action could not be completed: {exc}") from exc
    result = outcome["result"]
    failed = isinstance(result, dict) and "error" in result
    audit.action(ticket, "failed" if failed else "approved", user=user.id if user else None, result=result)
    return {"status": "failed" if failed else "done", **outcome}


@app.post("/api/actions/reject")
def reject(decision: Decision, request: Request) -> dict:
    user = _user(request)
    try:
        ticket = approvals.check_ticket(decision.ticket, user)
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    audit.action(ticket, "rejected", user=user.id if user else None)
    return {"status": "rejected", "action": {k: ticket[k] for k in ("id", "tool", "summary")}}


@app.post("/api/ask")
async def ask(q: Question, request: Request) -> dict:
    question = q.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question.")
    target = _app(q.app)
    user = _user(request)
    if user is None and config.REQUIRE_IDENTITY:
        raise HTTPException(status_code=401, detail="Sign in to ask questions.")
    session_id = q.session_id or uuid.uuid4().hex
    answer_id = uuid.uuid4().hex
    # Conversations are private to their user: the same session id can't read someone else's.
    session = sessions.get(f"{target.name}:{user.id}:{session_id}" if user else f"{target.name}:{session_id}")
    started = time.perf_counter()

    try:
        registered = [entry for entry in await discover() if target.serves(entry)]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"The agent registry is unreachable: {exc}") from exc

    agent = Agent(
        name=f"{target.title} orchestrator",
        instructions=target.instructions,
        model=llm.model(config.ORCHESTRATOR_MODEL),
        model_settings=llm.settings(),
        tools=[make_tool(entry) for entry in registered],
        input_guardrails=([read_only_guardrail] if target.read_only else []) + ([nemo_input_rails] if rails.enabled() else []),
        output_guardrails=[nemo_output_rails] if rails.enabled() and config.RAILS_CHECK_ANSWERS else [],
    )
    context: dict = {"calls": [], "question": question, "user_token": identity.sign(user) if user else None}
    try:
        result = await Runner.run(agent, question, context=context, session=session, max_turns=10)
    except (InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered) as tripped:
        elapsed = round((time.perf_counter() - started) * 1000)
        blocked_by = (tripped.guardrail_result.output.output_info or {}).get("blocked_by", "guardrail")
        if isinstance(tripped, OutputGuardrailTripwireTriggered):
            answer = RAILS_ANSWER_WITHHELD
        else:
            answer = REFUSAL.format(title=target.title) if blocked_by == "read-only guardrail" else RAILS_REFUSAL
        calls = context["calls"] if isinstance(tripped, OutputGuardrailTripwireTriggered) else []
        audit.record(app=target.name, session_id=session_id, question=question, blocked=True, calls=calls, usage={},
                     elapsed_ms=elapsed, blocked_by=blocked_by, user=user.id if user else None)
        return {
            "app": target.name,
            "answer": answer,
            "blocked": True,
            "blocked_by": blocked_by,
            "session_id": session_id,
            "agents": [a["name"] for a in registered],
            "calls": calls,
            "actions": [],
            "usage": {},
            "elapsed_ms": elapsed,
        }
    except Exception as exc:  # model errors, max turns: report them as JSON the UI can show
        log.exception("run failed")
        audit.record(app=target.name, session_id=session_id, question=question, blocked=False, calls=context["calls"], usage={},
                     elapsed_ms=round((time.perf_counter() - started) * 1000), error=str(exc),
                     user=user.id if user else None)
        raise HTTPException(status_code=502, detail=f"The answer could not be completed: {exc}") from exc

    calls = context["calls"]
    total = runlog.usage(result)
    for call in calls:
        for key in ("model_requests", "input_tokens", "output_tokens", "total_tokens"):
            total[key] += int(call.get("usage", {}).get(key, 0))
    elapsed = round((time.perf_counter() - started) * 1000)
    actions = approvals.pending(calls)
    audit.record(app=target.name, session_id=session_id, question=question, blocked=False, calls=calls, usage=total,
                 elapsed_ms=elapsed, user=user.id if user else None, answer_id=answer_id, actions=actions)
    return {
        "app": target.name,
        "answer": str(result.final_output),
        "answer_id": answer_id,
        "user": user.id if user else None,
        "blocked": False,
        "session_id": session_id,
        "agents": [a["name"] for a in registered],
        "calls": calls,
        "actions": actions,
        "usage": total,
        "elapsed_ms": elapsed,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(telemetry.wrap(app, "orchestrator"), host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
