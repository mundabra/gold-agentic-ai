"""Who is asking, and proof of it that travels with the question.

The orchestrator identifies the user (GOLD_AUTH_MODE), then signs a short-lived user
context with GOLD_IDENTITY_SECRET. The context travels in the A2A message metadata to
the agents, and from the agents to the tool servers in the X-Gold-User header. The data
tools verify the signature and set the user for each query, so Postgres row-level
security decides which rows that user can see (deploy/postgres/03-row-level-security.sql).

Modes:
  none   no identity (the default); rows are not filtered by user
  proxy  trust the user and groups headers set by a sign-in proxy in front of GOLD
         (for example oauth2-proxy, an API gateway or a service mesh)
  oidc   validate a bearer JWT from your identity provider (needs gold-ai-agent[auth])
  demo   pick a user from GOLD_DEMO_USERS in the UI; for demonstrations only
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache

from gold import config

log = logging.getLogger("gold.identity")
HEADER = "X-Gold-User"      # agent -> tool server
METADATA_KEY = "gold_user"  # orchestrator -> agent (A2A message metadata)


DEV_SECRET = "gold-dev-identity-secret"
if config.AUTH_MODE != "none" and config.IDENTITY_SECRET in (DEV_SECRET, "change-me-for-anything-but-a-demo"):
    log.warning("GOLD_IDENTITY_SECRET is the built-in development value: set a long random secret, "
                "shared by all GOLD services, before real use.")


class AuthError(Exception):
    """The request carries credentials that cannot be accepted."""


@dataclass(frozen=True)
class User:
    id: str
    groups: tuple[str, ...] = field(default_factory=tuple)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(payload: str) -> str:
    return _b64(hmac.new(config.IDENTITY_SECRET.encode(), payload.encode(), hashlib.sha256).digest())


def sign(user: User, ttl_seconds: int = 300) -> str:
    """A short-lived, tamper-proof user context for the services behind the orchestrator."""
    payload = _b64(json.dumps({"u": user.id, "g": list(user.groups), "exp": int(time.time()) + ttl_seconds}).encode())
    return f"{payload}.{_signature(payload)}"


def verify(token: str | None) -> User | None:
    """The user in a signed context, or None if there is none. Raises AuthError if it is forged or expired."""
    if not token:
        return None
    try:
        payload, signature = token.split(".", 1)
    except ValueError as exc:
        raise AuthError("Malformed user context.") from exc
    if not hmac.compare_digest(signature, _signature(payload)):
        raise AuthError("The user context signature is invalid.")
    data = json.loads(_unb64(payload))
    if data.get("exp", 0) < time.time():
        raise AuthError("The user context has expired.")
    return User(id=data["u"], groups=tuple(data.get("g", [])))


@lru_cache(maxsize=1)
def _jwks_client():
    import jwt

    return jwt.PyJWKClient(config.OIDC_JWKS_URL, cache_keys=True)


def _from_jwt(authorization: str) -> User:
    try:
        import jwt
    except ImportError as exc:
        raise AuthError('OIDC sign-in needs: pip install "gold-ai-agent[auth]"') from exc
    if not authorization.lower().startswith("bearer "):
        raise AuthError("Sign in: a bearer token is required.")
    token = authorization.split(" ", 1)[1]
    try:
        key = _jwks_client().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["RS256", "ES256", "PS256"],
            audience=config.OIDC_AUDIENCE or None, issuer=config.OIDC_ISSUER or None,
            options={"verify_aud": bool(config.OIDC_AUDIENCE)},
        )
    except Exception as exc:
        raise AuthError(f"The sign-in token was rejected: {exc}") from exc
    user_id = claims.get(config.OIDC_USER_CLAIM) or claims.get("sub")
    groups = claims.get(config.OIDC_GROUPS_CLAIM) or []
    return User(id=str(user_id), groups=tuple(groups if isinstance(groups, list) else [groups]))


def from_request(headers) -> User | None:
    """Identify the user of an incoming request to the orchestrator, per GOLD_AUTH_MODE."""
    mode = config.AUTH_MODE
    if mode == "none":
        return None
    if mode == "proxy":
        user_id = headers.get(config.AUTH_USER_HEADER)
        groups = [g.strip() for g in (headers.get(config.AUTH_GROUPS_HEADER) or "").split(",") if g.strip()]
        return User(id=user_id, groups=tuple(groups)) if user_id else None
    if mode == "demo":
        user_id = headers.get("X-Gold-Demo-User")
        return User(id=user_id, groups=config.DEMO_GROUPS.get(user_id, ())) if user_id in config.DEMO_USERS else None
    if mode == "oidc":
        authorization = headers.get("Authorization")
        return _from_jwt(authorization) if authorization else None
    raise AuthError(f"Unknown GOLD_AUTH_MODE '{mode}'.")
