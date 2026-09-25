"""The one place a question becomes SQL. Shared by the SQL agent and the evaluation harness,
so what you measure is exactly what runs in production."""

import re

from agents.usage import Usage

from apps.data_analyst import settings
from gold import llm

DEFAULT_SQL_PROMPT = (
    "You write PostgreSQL. Answer the question with one read-only SELECT query and nothing else: "
    "no explanation, no markdown. Use only tables and columns from the schema. "
    "If business definitions are given, follow them exactly."
)

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.S | re.I)
_LINE_START = re.compile(r"^\s*(with|select)\b", re.I | re.M)
_ANYWHERE = re.compile(r"\b(with|select)\b", re.I)


def extract_sql(text: str) -> str:
    """Pull the query out of a model reply that may include reasoning, fences or chatter."""
    text = _THINK.sub("", text)
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start = _LINE_START.search(text) or _ANYWHERE.search(text)
    if start:
        text = text[start.start(1):]
    return text.strip().rstrip(";").strip()


def messages(question: str, definitions: str = "", schema: str = "") -> list[dict]:
    """The prompt contract. A fine-tuned model must be trained on exactly this shape."""
    system = settings.SQL_SYSTEM_PROMPT or DEFAULT_SQL_PROMPT
    if schema:
        system += "\n\nSchema:\n" + schema
    user = question
    if definitions and settings.SQL_PASS_DEFINITIONS:
        user += "\n\nBusiness definitions to follow:\n" + definitions
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def generate(question: str, definitions: str = "", schema: str = "", model: str | None = None) -> tuple[str, Usage]:
    response = await llm.client().chat.completions.create(
        model=model or settings.SQL_MODEL,
        messages=messages(question, definitions, schema),
        temperature=0,
        max_tokens=settings.SQL_MAX_TOKENS,
        extra_body=settings.SQL_EXTRA_BODY or None,
    )
    u = response.usage
    usage = Usage(
        requests=1,
        input_tokens=getattr(u, "prompt_tokens", 0) or 0,
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
        total_tokens=getattr(u, "total_tokens", 0) or 0,
    )
    return extract_sql(response.choices[0].message.content or ""), usage
