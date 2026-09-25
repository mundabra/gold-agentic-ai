"""Postgres helpers any app can use: act as the signed-in user, and return plain JSON values.

With a user, gold.user_id and gold.user_groups are set for the transaction (SET LOCAL),
so Postgres row-level security policies can filter rows with current_setting('gold.user_id').
The model's own SQL can never set them: the data app's SQL checks refuse SET.
"""

import datetime
import decimal

from psycopg import sql as pgsql


def act_as(cur, user) -> None:
    """Run the rest of this transaction as `user` (an identity.User, or None for no user)."""
    if user is not None:
        cur.execute(pgsql.SQL("SET LOCAL gold.user_id = {}").format(pgsql.Literal(user.id)))
        cur.execute(pgsql.SQL("SET LOCAL gold.user_groups = {}").format(pgsql.Literal(",".join(user.groups))))


def jsonable(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value
