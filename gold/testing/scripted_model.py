"""A scripted, OpenAI-compatible stand-in model. It is NOT a real model.

It lets the whole system (orchestrator, A2A agents, MCP tools, Postgres) run
end to end with no API key and no GPU: for the automated tests, and for a
first look at GOLD before you connect a real model. Each app supplies its own
canned steps (the `scripted` module in its app.yaml), which follow the same
tool calls a real model is instructed to make, so only the example questions
in the chat UI get meaningful answers.

    gold serve scripted-model
"""

import hashlib
import importlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from functools import cache

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI(title="GOLD scripted test model")


def tool_call(name: str, arguments: dict) -> dict:
    """A reply that calls one tool."""
    return {"tool_calls": [{
        "id": "call_" + uuid.uuid4().hex[:12],
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }]}


def _text(content) -> str:
    """Message content can be a string or a list of content parts."""
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def _history(messages: list[dict]) -> tuple[str, list[tuple[str, str]]]:
    """Return the latest user message and the (tool name, tool output) pairs since it.

    Earlier turns of the conversation (session memory) are ignored, so each question
    follows its own steps."""
    last = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    user = _text(messages[last].get("content")) if last >= 0 else ""
    names = {}
    for m in messages:
        for call in m.get("tool_calls") or []:
            names[call["id"]] = call["function"]["name"]
    done = [(names.get(m.get("tool_call_id"), "?"), _text(m.get("content")))
            for m in messages[last + 1:] if m.get("role") == "tool"]
    return user, done


def markdown_table(result_json: str) -> str:
    try:
        result = json.loads(result_json)
    except ValueError:
        return result_json
    if "error" in result:
        return f"The query was refused: {result.get('reason')}"
    cols = result["columns"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in result["rows"][:20]]
    return "\n".join(lines)


@dataclass
class Turn:
    """One request to the model, as the canned replies see it."""

    system: str
    user: str  # the latest user message
    tools: set[str]
    called: list[str]  # tools called so far, in order
    output: dict[str, str]  # tool name -> its latest output

    @classmethod
    def from_body(cls, body: dict) -> "Turn":
        messages = body.get("messages", [])
        system = next((_text(m.get("content")) for m in messages if m.get("role") in ("system", "developer")), "")
        user, done = _history(messages)
        tools = {t["function"]["name"] for t in body.get("tools") or []}
        return cls(system=system, user=user, tools=tools, called=[n for n, _ in done], output=dict(done))


@cache
def _app_replies() -> list:
    from gold import apps

    return [importlib.import_module(a.scripted) for a in apps.all_apps().values() if a.scripted]


def decide(body: dict) -> dict:
    turn = Turn.from_body(body)
    for module in _app_replies():
        reply = module.decide(turn)
        if reply is not None:
            return reply
    return {"content": "The scripted model has no canned reply for this. Connect a real model to ask anything."}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> dict:
    body = await request.json()
    reply = decide(body)
    message = {"role": "assistant", "content": reply.get("content")}
    if "tool_calls" in reply:
        message["tool_calls"] = reply["tool_calls"]
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:12],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "scripted"),
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if "tool_calls" in reply else "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


STOPWORDS = set("a an and are as at be by for from how i in is it me my of on or our the to we what when which who why with you your".split())


def hashed_embedding(text: str, dims: int = 256) -> list[float]:
    """A deterministic bag-of-words vector (feature hashing): similar wording scores close. Not a real model."""
    vector = [0.0] * dims
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if word in STOPWORDS:
            continue
        stem = word[:-1] if len(word) > 3 and word.endswith("s") else word
        h = int(hashlib.md5(stem.encode()).hexdigest(), 16)
        vector[h % dims] += 1.0 if (h >> 8) & 1 else -1.0
    norm = sum(x * x for x in vector) ** 0.5 or 1.0
    return [x / norm for x in vector]


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> dict:
    body = await request.json()
    texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
    return {"object": "list", "model": body.get("model", "scripted"),
            "data": [{"object": "embedding", "index": i, "embedding": hashed_embedding(t)} for i, t in enumerate(texts)],
            "usage": {"prompt_tokens": 0, "total_tokens": 0}}


@app.post("/v1/checks")
async def checks(request: Request) -> dict:
    """Stand-in for a NeMo Guardrails server's /v1/checks, for tests: blocks poems and emails."""
    body = await request.json()
    text = " ".join(_text(m.get("content")) for m in body.get("messages", []) if m.get("role") != "user"
                    or "input" in body.get("guardrails", {}).get("rail_types", ["input"])).lower()
    if "poem" in text:
        return {"status": "blocked", "content": "", "rail": "self check input"}
    if "@" in text:
        return {"status": "blocked", "content": "", "rail": "regex check output"}
    return {"status": "passed", "content": ""}


@app.get("/v1/models")
def models() -> dict:
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in ("gold-general", "gold-sql", "gold-embed")]}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


def main() -> None:
    from gold import config

    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
