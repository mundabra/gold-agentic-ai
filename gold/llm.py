"""One place that decides how models are reached."""

from functools import lru_cache

from agents import ModelSettings, OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI

from gold import config

set_tracing_disabled(not config.OPENAI_TRACING)


@lru_cache(maxsize=1)
def client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)


def settings() -> ModelSettings:
    """Request settings for the orchestrator and agents (GOLD_AGENT_EXTRA_BODY)."""
    return ModelSettings(extra_body=config.AGENT_EXTRA_BODY or None)


def model(name: str) -> OpenAIChatCompletionsModel:
    # Chat Completions is the lowest common denominator: every
    # OpenAI-compatible server speaks it, while the Responses API is not
    # universally supported.
    return OpenAIChatCompletionsModel(model=name, openai_client=client())
