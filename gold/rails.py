"""Optional NVIDIA NeMo Guardrails, called as Agents SDK guardrails.

When GOLD_RAILS_URL points at a NeMo Guardrails server, every question is checked by
its input rails before any model runs, and (with GOLD_RAILS_CHECK_ANSWERS=true) every
answer by its output rails before it reaches the user. GOLD uses the server's
/v1/checks endpoint, which runs the rails without generating a reply. The rails
themselves (patterns, policy self-checks, NemoGuard safety models) are configured in
deploy/guardrails/gold/. See docs/guardrails.md.

If the rails server cannot be reached, the question is blocked (fail closed) unless
GOLD_RAILS_FAIL_OPEN=true.
"""

import logging

import httpx

from gold import config

log = logging.getLogger("gold.rails")


def enabled() -> bool:
    return bool(config.RAILS_URL)


async def check(messages: list[dict], rail_type: str) -> dict:
    """Run the input or output rails on messages. Returns {"blocked": bool, "rail": str | None}."""
    body = {
        "model": config.RAILS_MODEL,
        "messages": messages,
        "guardrails": {"config_id": config.RAILS_CONFIG_ID, "rail_types": [rail_type]},
    }
    try:
        async with httpx.AsyncClient(timeout=config.RAILS_TIMEOUT) as client:
            resp = await client.post(f"{config.RAILS_URL.rstrip('/')}/v1/checks", json=body)
            resp.raise_for_status()
            result = resp.json()
    except Exception as exc:
        log.warning("guardrails check failed: %s", exc)
        if config.RAILS_FAIL_OPEN:
            return {"blocked": False, "rail": None}
        return {"blocked": True, "rail": "guardrails unavailable"}
    return {"blocked": result.get("status") == "blocked", "rail": result.get("rail")}
