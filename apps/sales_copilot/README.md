# Sales copilot

A GOLD sample app for sales reps. It knows the rep's own accounts, briefs them before a call, tells them who needs attention and what to offer, and logs calls, meetings and follow-ups once they approve.

| Ask | What happens |
|---|---|
| "Which of my accounts need attention?" | Accounts with no purchase in 180 days, longest gap first, charted |
| "Brief me on Luís Gonçalves" | Lifetime value, orders, last purchase, revenue trend, favourite genres and artists, recent orders and activities |
| "What should I offer Luís Gonçalves next?" | Albums from the customer's two favourite genres they don't own yet, most popular first |
| "Log a call with Luís Gonçalves: interested in Latin jazz, follow up in two weeks" | A proposal with Approve and Reject; written only on Approve |
| "How much discount can I give without approval?" | An answer from the sales playbook, citing the passage it used; internal documents only for sales leadership |
| "Draft a follow-up email to him" | A draft for the rep to send; the app cannot send email |
| "What was our revenue by country last year?" | Handed to the Definitions and SQL agents from Talk to your Data |

## What it shows about the platform

- **Actions need a person.** `log_activity` never writes on its own. It returns a signed proposal; the platform runs it only after the rep approves, exactly once ([approvals](../../docs/approvals.md)).
- **Per-user data with no filtering code.** Every query runs as the signed-in rep, and Postgres row-level security returns only their accounts. Jane Peacock sees her 21 accounts; a user with no entitlement sees none.
- **Typed tools, not free-form SQL.** When the questions are known, a tool per question is safer and more predictable than text-to-SQL. The model chooses tools and fills parameters; it never writes SQL here.
- **Least-privilege writes.** The only login that can write, `gold_crm_writer`, can insert CRM activities for accounts the rep can see, and nothing else: no updates, no deletes, no other tables ([06-sales.sh](../../deploy/postgres/06-sales.sh)).
- **Answers from documents, by audience.** The playbook in [`knowledge/`](knowledge/) is loaded into pgvector by the platform. The internal discount matrix is marked `audience: sales-leadership`, so Margaret Park sees it and Jane Peacock doesn't ([knowledge](../../docs/knowledge.md)).
- **Agents are shared.** The app lists the Definitions and SQL agents from Talk to your Data in its manifest and uses them for company-wide questions. No code is copied.

## Try it

```bash
docker compose --profile scripted up --build     # with GOLD_AUTH_MODE=demo in .env
```

Open <http://localhost:8080>, choose **Sales copilot**, and set "View as" to `jane.peacock@example.com`. Click the examples; approve the logged call and ask for Luís Gonçalves's brief again to see it in his activities.

The sample data is a snapshot that ends on 22 December 2025, so "today" for account figures is the latest invoice date (`crm_as_of()` in the database). With live data, make that function return `current_date`.

## Inside

| Piece | File |
|---|---|
| Manifest | [`app.yaml`](app.yaml) |
| Orchestrator instructions | [`instructions.md`](instructions.md) |
| Account agent (A2A) | [`agents/account_agent.py`](agents/account_agent.py) |
| CRM tools (MCP): `my_accounts`, `find_account`, `account_brief`, `next_best_offers`, `list_activities`, `log_activity` | [`tools/crm_tools.py`](tools/crm_tools.py) |
| Queries and the approved write | [`crm.py`](crm.py) |
| Database: activities table, write login, row-level security, glossary term "at-risk account" | [`deploy/postgres/06-sales.sh`](../../deploy/postgres/06-sales.sh) |
| Sales playbook documents and retrieval eval questions | [`knowledge/`](knowledge/) |
| Canned replies for the scripted model | [`scripted.py`](scripted.py) |
| End-to-end tests | [`tests/test_sales_copilot.py`](../../tests/test_sales_copilot.py) |

To build something like it for your own team, follow [build an app](../../docs/build-an-app.md).
