import os
import time

import httpx
import psycopg
import pytest

import stack
from gold import config, identity
from test_end_to_end import DB_URL, _db_available

ASK = f"http://127.0.0.1:{stack.PORTS['orchestrator']}/api/ask"


def test_signed_user_context_round_trips_and_rejects_tampering():
    user = identity.User("jane.peacock@example.com", ("sales",))
    token = identity.sign(user)
    assert identity.verify(token) == user
    payload, signature = token.split(".")
    forged = identity._b64(b'{"u": "finance@example.com", "g": [], "exp": 9999999999}') + "." + signature
    with pytest.raises(identity.AuthError):
        identity.verify(forged)
    with pytest.raises(identity.AuthError):
        identity.verify(identity.sign(user, ttl_seconds=-1))
    assert identity.verify(None) is None


def test_modes(monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "none")
    assert identity.from_request({"X-Forwarded-User": "someone"}) is None
    monkeypatch.setattr(config, "AUTH_MODE", "proxy")
    assert identity.from_request({"X-Forwarded-User": "a@example.com", "X-Forwarded-Groups": "sales, emea"}) == \
        identity.User("a@example.com", ("sales", "emea"))
    monkeypatch.setattr(config, "AUTH_MODE", "demo")
    assert identity.from_request({"X-Gold-Demo-User": "jane.peacock@example.com"}).id == "jane.peacock@example.com"
    assert identity.from_request({"X-Gold-Demo-User": "not-a-demo-user"}) is None


def test_oidc_tokens_are_validated_against_the_key_set(monkeypatch):
    jwt = pytest.importorskip("jwt")
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(config, "AUTH_MODE", "oidc")
    monkeypatch.setattr(config, "OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setattr(config, "OIDC_AUDIENCE", "gold")
    monkeypatch.setattr(identity, "_jwks_client",
                        lambda: type("Keys", (), {"get_signing_key_from_jwt": lambda self, t: type("K", (), {"key": key.public_key()})()})())
    claims = {"email": "jane.peacock@example.com", "groups": ["sales"], "iss": "https://idp.example.com",
              "aud": "gold", "exp": int(time.time()) + 60}
    good = jwt.encode(claims, key, algorithm="RS256")
    assert identity.from_request({"Authorization": f"Bearer {good}"}) == identity.User("jane.peacock@example.com", ("sales",))
    wrong_audience = jwt.encode({**claims, "aud": "other"}, key, algorithm="RS256")
    with pytest.raises(identity.AuthError):
        identity.from_request({"Authorization": f"Bearer {wrong_audience}"})


@pytest.fixture(scope="module")
def stack_with_identity():
    if not _db_available():
        pytest.skip("needs Postgres with deploy/postgres/*.sql loaded")
    os.environ.update(GOLD_DATABASE_URL=DB_URL, GOLD_AUTH_MODE="proxy")
    procs = stack.start(real_model=False)
    yield
    stack.stop(procs)
    os.environ.pop("GOLD_AUTH_MODE")


def _revenue_rows(user: str | None) -> tuple[list, str]:
    headers = {"X-Forwarded-User": user} if user else {}
    body = httpx.post(ASK, json={"question": "What was our revenue by country last year?"}, headers=headers, timeout=60).json()
    rows = next(s["output"]["rows"] for c in body["calls"] for s in c["steps"] if s["tool"] == "run_sql")
    return rows, body.get("user")


def _expected_total(user: str | None) -> float:
    with psycopg.connect(DB_URL) as conn:
        if user:
            conn.execute(psycopg.sql.SQL("SET gold.user_id = {}").format(psycopg.sql.Literal(user)))
        return float(conn.execute(
            "SELECT COALESCE(ROUND(SUM(il.unit_price * il.quantity), 2), 0) FROM invoice_line il JOIN invoice i "
            "ON i.invoice_id = il.invoice_id WHERE EXTRACT(YEAR FROM i.invoice_date) = "
            "(SELECT MAX(EXTRACT(YEAR FROM invoice_date)) FROM invoice)").fetchone()[0])


def test_each_user_sees_only_their_rows(stack_with_identity):
    finance, who = _revenue_rows("finance@example.com")
    assert who == "finance@example.com"
    jane, _ = _revenue_rows("jane.peacock@example.com")
    stranger, _ = _revenue_rows("nobody@example.com")
    total = lambda rows: round(sum(float(r[1]) for r in rows), 2)
    assert total(finance) == _expected_total("finance@example.com") == _expected_total(None)
    assert 0 < total(jane) == _expected_total("jane.peacock@example.com") < total(finance)
    assert stranger == []


def test_conversations_are_private_to_their_user(stack_with_identity):
    from gold import sessions

    assert sessions.get("jane.peacock@example.com:abc") is not sessions.get("finance@example.com:abc")
