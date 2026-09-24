"""Analyst orchestrator: the API and chat UI business users talk to."""

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

from gold import audit, config, feedback, identity, llm, rails, runlog, sessions, telemetry
from gold.orchestrator.a2a_tools import discover, make_tool

log = logging.getLogger("gold.orchestrator")

INSTRUCTIONS = """You are GOLD, an analyst assistant that answers business questions from company data.
Your tools are specialist agents found in the agent registry.

For any question about business data:
1. Ask the definitions agent what the business terms in the question mean.
2. Ask the SQL agent. Give it the original question and paste the definitions and any approved
   example queries word for word.
3. Answer in this order:
   - the answer itself, in one or two plain sentences
   - the result table the SQL agent returned
   - "Definition used:" with the definitions you relied on
   - "SQL:" with the query, in a ```sql block
Not every word needs an agreed definition. Business metrics and periods (revenue, active customer,
last year) do; ordinary words that name data in the database (album, track, customer, country) do not.
If the definitions agent has no definition for a term, still ask the SQL agent: it uses the plain
meaning of the words and the database schema. Never refuse a data question for lack of a definition.
Only report numbers the SQL agent returned. Never estimate or invent them.
If a specialist is unavailable or fails, say so plainly.
GOLD is read-only: never offer to change data."""

REFUSAL = "GOLD is read-only, so I can't change or delete data. I can answer questions about it."
RAILS_REFUSAL = "I can't help with that request. I answer questions about the company's business data."
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
    session_id: str | None = None


class Feedback(BaseModel):
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


@app.get("/api/identity")
def whoami(request: Request) -> dict:
    """The signed-in user as GOLD sees them, and (in demo mode) the users to pick from."""
    try:
        user = identity.from_request(request.headers)
    except identity.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
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
    try:
        user = identity.from_request(request.headers)
        feedback.submit(answer_id=fb.answer_id, question=fb.question, sql_ran=fb.sql, rating=fb.rating,
                        comment=fb.comment, corrected_sql=fb.corrected_sql, user=user.id if user else None)
    except identity.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except feedback.FeedbackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"received": True}


@app.get("/api/agents")
async def agents() -> list[dict]:
    return await discover()


@app.post("/api/ask")
async def ask(q: Question, request: Request) -> dict:
    question = q.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question.")
    try:
        user = identity.from_request(request.headers)
    except identity.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if user is None and config.REQUIRE_IDENTITY:
        raise HTTPException(status_code=401, detail="Sign in to ask questions.")
    session_id = q.session_id or uuid.uuid4().hex
    answer_id = uuid.uuid4().hex
    # Conversations are private to their user: the same session id can't read someone else's.
    session = sessions.get(f"{user.id}:{session_id}" if user else session_id)
    started = time.perf_counter()

    try:
        registered = await discover()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"The agent registry is unreachable: {exc}") from exc

    agent = Agent(
        name="GOLD orchestrator",
        instructions=INSTRUCTIONS,
        model=llm.model(config.ORCHESTRATOR_MODEL),
        model_settings=llm.settings(),
        tools=[make_tool(entry) for entry in registered],
        input_guardrails=[read_only_guardrail] + ([nemo_input_rails] if rails.enabled() else []),
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
            answer = REFUSAL if blocked_by == "read-only guardrail" else RAILS_REFUSAL
        calls = context["calls"] if isinstance(tripped, OutputGuardrailTripwireTriggered) else []
        audit.record(session_id=session_id, question=question, blocked=True, calls=calls, usage={},
                     elapsed_ms=elapsed, blocked_by=blocked_by, user=user.id if user else None)
        return {
            "answer": answer,
            "blocked": True,
            "blocked_by": blocked_by,
            "session_id": session_id,
            "agents": [a["name"] for a in registered],
            "calls": calls,
            "usage": {},
            "elapsed_ms": elapsed,
        }
    except Exception as exc:  # model errors, max turns: report them as JSON the UI can show
        log.exception("run failed")
        audit.record(session_id=session_id, question=question, blocked=False, calls=context["calls"], usage={},
                     elapsed_ms=round((time.perf_counter() - started) * 1000), error=str(exc),
                     user=user.id if user else None)
        raise HTTPException(status_code=502, detail=f"The answer could not be completed: {exc}") from exc

    calls = context["calls"]
    total = runlog.usage(result)
    for call in calls:
        for key in ("model_requests", "input_tokens", "output_tokens", "total_tokens"):
            total[key] += int(call.get("usage", {}).get(key, 0))
    elapsed = round((time.perf_counter() - started) * 1000)
    audit.record(session_id=session_id, question=question, blocked=False, calls=calls, usage=total, elapsed_ms=elapsed,
                 user=user.id if user else None, answer_id=answer_id)
    return {
        "answer": str(result.final_output),
        "answer_id": answer_id,
        "user": user.id if user else None,
        "blocked": False,
        "session_id": session_id,
        "agents": [a["name"] for a in registered],
        "calls": calls,
        "usage": total,
        "elapsed_ms": elapsed,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(telemetry.wrap(app, "orchestrator"), host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
