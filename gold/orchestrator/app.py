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
    RunContextWrapper,
    Runner,
    input_guardrail,
)
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from gold import config, llm, runlog, sessions
from gold.orchestrator.a2a_tools import discover, make_tool

log = logging.getLogger("gold.orchestrator")

INSTRUCTIONS = """You are GOLD, an analyst assistant that answers business questions from company data.
Your tools are specialist agents found in the agent registry.

For any question about business data:
1. Ask the definitions agent what the business terms in the question mean.
2. Ask the SQL agent. Give it the original question and paste the definitions word for word.
3. Answer in this order:
   - the answer itself, in one or two plain sentences
   - the result table the SQL agent returned
   - "Definition used:" with the definitions you relied on
   - "SQL:" with the query, in a ```sql block
Only report numbers the SQL agent returned. Never estimate or invent them.
If a specialist is unavailable or fails, say so plainly.
GOLD is read-only: never offer to change data."""

REFUSAL = "GOLD is read-only, so I can't change or delete data. I can answer questions about it."

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
    return GuardrailFunctionOutput(output_info={"matched": hit.group(0) if hit else None}, tripwire_triggered=bool(hit))


class Question(BaseModel):
    question: str
    session_id: str | None = None


app = FastAPI(title="GOLD orchestrator")
_STATIC = Path(__file__).parent / "static"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/agents")
async def agents() -> list[dict]:
    return await discover()


@app.post("/api/ask")
async def ask(q: Question) -> dict:
    question = q.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question.")
    session_id = q.session_id or uuid.uuid4().hex
    session = sessions.get(session_id)
    started = time.perf_counter()

    try:
        registered = await discover()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"The agent registry is unreachable: {exc}") from exc

    agent = Agent(
        name="GOLD orchestrator",
        instructions=INSTRUCTIONS,
        model=llm.model(config.ORCHESTRATOR_MODEL),
        tools=[make_tool(entry) for entry in registered],
        input_guardrails=[read_only_guardrail],
    )
    context: dict = {"calls": []}
    try:
        result = await Runner.run(agent, question, context=context, session=session, max_turns=10)
    except InputGuardrailTripwireTriggered:
        return {
            "answer": REFUSAL,
            "blocked": True,
            "session_id": session_id,
            "agents": [a["name"] for a in registered],
            "calls": [],
            "usage": {},
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:  # model errors, max turns: report them as JSON the UI can show
        log.exception("run failed")
        raise HTTPException(status_code=502, detail=f"The answer could not be completed: {exc}") from exc

    calls = context["calls"]
    total = runlog.usage(result)
    for call in calls:
        for key in ("model_requests", "input_tokens", "output_tokens", "total_tokens"):
            total[key] += int(call.get("usage", {}).get(key, 0))
    log.info("answered in %d ms with %d agent calls", (time.perf_counter() - started) * 1000, len(calls))
    return {
        "answer": str(result.final_output),
        "blocked": False,
        "session_id": session_id,
        "agents": [a["name"] for a in registered],
        "calls": calls,
        "usage": total,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
