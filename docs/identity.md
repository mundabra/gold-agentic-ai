# Identity and row-level security

Two people can ask GOLD the same question and get different, correct answers: each sees only the rows they're entitled to. The database enforces this, not the model.

```text
Jane (sales rep)     "What was our revenue by country last year?"  →  her customers only
Finance              "What was our revenue by country last year?"  →  every country
Someone not listed   "What was our revenue by country last year?"  →  no rows
```

## How it works

1. **The orchestrator identifies the user**, according to `GOLD_AUTH_MODE` (below).
2. It **signs a short-lived user context** with `GOLD_IDENTITY_SECRET`, a secret shared by the GOLD services. The context travels in the A2A message metadata to each agent, and from the agents to the tool servers in the `X-Gold-User` header. A forged or expired context is rejected.
3. The data tools **set the user for the query**, with `SET LOCAL gold.user_id` inside the query's read-only transaction. The model's SQL can't do this, because SQLGlot refuses `SET` and the `set_config()` function is revoked.
4. **Postgres row-level security** filters every table that has a policy ([`03-row-level-security.sql`](../deploy/postgres/03-row-level-security.sql)).

Conversation memory is private too: a session is stored under the user, so one user can't read another's history by reusing a session id. Every audit record carries the user.

## Sign-in modes

| `GOLD_AUTH_MODE` | Who is the user | Use it when |
|---|---|---|
| `none` (default) | Nobody; rows are not filtered by user | Trying GOLD out |
| `proxy` | The `X-Forwarded-User` (and `X-Forwarded-Groups`) headers set by a sign-in proxy in front of GOLD, such as oauth2-proxy, an API gateway or a service mesh | Your platform already signs users in. Make sure only the proxy can reach the orchestrator. |
| `oidc` | The `email` (or `sub`) claim of a bearer JWT validated against your identity provider's key set | Clients call GOLD's API with tokens from your identity provider |
| `demo` | A user picked from a list in the UI | Showing row-level security to an audience. **Not for real data.** |

Set `GOLD_REQUIRE_IDENTITY=true` to refuse questions without a signed-in user, at both the orchestrator and the data tools. With identity required, a failure to pass the user on means *no answer*, not *all rows*.

Try it:

```bash
cat >> .env <<'ENV'
GOLD_AUTH_MODE=demo
ENV
docker compose --profile scripted up --build
# at http://localhost:8080, pick "View as" jane.peacock@example.com, then finance@example.com
```

## The sample policy

The sample data follows a common sales model:

| User | Sees | Revenue across all years |
|---|---|---|
| `finance@example.com` | Everything (`full_access`) | 2,328.60 |
| `jane.peacock@example.com` | Her 21 customers and their invoices | 833.04 |
| `margaret.park@example.com` | Her 20 customers and their invoices | 775.40 |
| anyone else | Nothing | none |

Entitlements live in `gold_user_access`. GOLD's database login can't read that table. The policies read it through `gold_rep_scope()`, a function that runs with its owner's rights. Invoices and invoice lines are filtered through the customers the user can see.

## For your data

- Replace `gold_user_access` with your entitlements, for example a view over your identity or HR system.
- Write one policy per table that needs filtering. `current_setting('gold.user_id', true)` is the user, and `current_setting('gold.user_groups', true)` is a comma-separated list of their groups.
- Policies apply to GOLD's login only. Admin and ETL logins are unaffected.
- Add questions to your evaluation set that different users should answer differently.

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `GOLD_AUTH_MODE` | `none` | `none`, `proxy`, `oidc` or `demo` |
| `GOLD_IDENTITY_SECRET` | development value (logged as a warning) | Signs the user context. Set a long random value shared by every GOLD service; the Helm chart generates one. |
| `GOLD_REQUIRE_IDENTITY` | `false` | Refuse questions without a user |
| `GOLD_AUTH_USER_HEADER`, `GOLD_AUTH_GROUPS_HEADER` | `X-Forwarded-User`, `X-Forwarded-Groups` | Proxy mode headers |
| `GOLD_OIDC_JWKS_URL`, `GOLD_OIDC_ISSUER`, `GOLD_OIDC_AUDIENCE` | empty | OIDC validation (needs the `auth` extra, which is in the image) |
| `GOLD_OIDC_USER_CLAIM`, `GOLD_OIDC_GROUPS_CLAIM` | `email`, `groups` | Which claims name the user and their groups |
| `GOLD_DEMO_USERS` | the four sample users | Demo mode's "View as" list |
