"""Conversation memory for the orchestrator, using the Agents SDK's own session stores.

    GOLD_SESSION_DB_URL unset         a local SQLite file: survives restarts, one orchestrator replica
    GOLD_SESSION_DB_URL=postgresql+asyncpg://user:pass@host/db
                                      a shared database: any number of orchestrator replicas
                                      (pip install "gold-agentic-ai[sessions]")

Specialist agents are stateless on purpose: the orchestrator passes them
everything they need, so they scale freely.
"""

import tempfile
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

from agents import SQLiteSession
from agents.memory.session import Session

from gold import config


@lru_cache(maxsize=1)
def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(config.SESSION_DB_URL, pool_pre_ping=True)


# Recently used session objects. Evicting one loses nothing: the history is in the store.
_open: OrderedDict[str, Session] = OrderedDict()
MAX_OPEN = 256


def _create(session_id: str) -> Session:
    url = config.SESSION_DB_URL
    if "://" in url:
        from agents.extensions.memory import SQLAlchemySession

        return SQLAlchemySession(session_id, engine=_engine(), create_tables=True)
    path = url or str(Path(tempfile.gettempdir()) / "gold-sessions.sqlite")
    return SQLiteSession(session_id, db_path=path)


def get(session_id: str) -> Session:
    session = _open.pop(session_id, None) or _create(session_id)
    _open[session_id] = session
    while len(_open) > MAX_OPEN:
        _, old = _open.popitem(last=False)
        if hasattr(old, "close"):
            old.close()
    return session
