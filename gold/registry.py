"""Agent registry: specialists register their A2A Agent Card; the orchestrator discovers them here.

Registrations live in memory and expire unless refreshed, and agents re-register
every 30 seconds, so the registry needs no database and recovers from restarts.
"""

import hmac
import time

import httpx
import uvicorn
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from gold import config

TTL_SECONDS = 90

app = FastAPI(title="GOLD agent registry")
_agents: dict[str, dict] = {}


class Registration(BaseModel):
    url: str


@app.post("/agents")
async def register(reg: Registration, authorization: str = Header(default="")) -> dict:
    if config.REGISTRY_TOKEN and not hmac.compare_digest(authorization, f"Bearer {config.REGISTRY_TOKEN}"):
        raise HTTPException(status_code=401, detail="A valid registry token is required to register an agent.")
    card_url = reg.url.rstrip("/") + AGENT_CARD_WELL_KNOWN_PATH
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(card_url)
            resp.raise_for_status()
            card = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read an Agent Card at {card_url}: {exc}") from exc
    name = card.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="The Agent Card has no name.")
    url = reg.url.rstrip("/")
    current = _agents.get(name)
    if current and current["url"] != url and time.time() - current["last_seen"] < TTL_SECONDS:
        # A live agent keeps its name: a second service cannot take it over.
        raise HTTPException(status_code=409, detail=f"'{name}' is already registered from {current['url']}.")
    _agents[name] = {"url": url, "card": card, "last_seen": time.time()}
    return {"registered": name}


@app.get("/agents")
def list_agents() -> list[dict]:
    now = time.time()
    live = [a for a in _agents.values() if now - a["last_seen"] < TTL_SECONDS]
    return [
        {
            "name": a["card"]["name"],
            "description": a["card"].get("description", ""),
            "url": a["url"],
            "skills": [
                {"name": s.get("name", ""), "description": s.get("description", "")}
                for s in a["card"].get("skills", [])
            ],
            "seconds_since_heartbeat": round(now - a["last_seen"]),
        }
        for a in sorted(live, key=lambda a: a["card"]["name"])
    ]


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "agents": len(_agents)}


def main() -> None:
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
